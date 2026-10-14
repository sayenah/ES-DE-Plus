#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. D-011/D-013 immutable test pre-releases.
import copy
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import tarfile
import tempfile
import urllib.parse
import zipfile

import distribution
import test_signing

require = distribution.require
REPOSITORY = distribution.REPOSITORY
# GitHub documents assets must be smaller than 2 GiB.
ASSET_LIMIT = 2 * 1024 ** 3
MARKER = re.compile(r'<!-- ESDEPLUS-PROVENANCE (\{[^\n]+\}) -->')


def bytes_hash(data):
    return hashlib.sha256(data).hexdigest()


def provenance(release):
    matches = MARKER.findall(release.get('body') or '')
    require(len(matches) == 1, 'Missing or ambiguous release provenance')
    value = json.loads(matches[0])
    require(value['schema'] == 1 and re.fullmatch('[a-f0-9]{40}', value['commit']) and
            value['repository'] == REPOSITORY and
            all(str(value[k]).isdecimal() and int(value[k]) > 0 for k in
                ('run_id', 'run_attempt', 'source_id', 'apk_id')) and
            type(value['version_code']) is int, 'Invalid release provenance')
    return value


def validate_pair(source, apk_dir, expected_cert):
    manifest = distribution.validate_bundle(source)
    require(manifest['schema'] == 5, 'Publisher requires versioned source provenance')
    require({key: manifest['apk'][key] for key in test_signing.public_version(manifest['commit'])} ==
            test_signing.public_version(manifest['commit']), 'Publisher version differs from the exact source commit')
    require((source / 'manifest.json').read_bytes() == (apk_dir / 'manifest.json').read_bytes(),
            'APK and source manifests differ')
    actual = test_signing.inspect_apk(apk_dir / 'app-debug.apk', expected_cert)
    actual['abis'] = distribution.ABIS
    require(actual == manifest['apk'], 'APK differs from audited/smoked manifest')
    with zipfile.ZipFile(apk_dir / 'app-debug.apk') as archive:
        abis = sorted({name.split('/')[1] for name in archive.namelist() if name.startswith('lib/')})
        require(abis == distribution.ABIS, 'Publisher ABI mismatch')
        shared = {name: bytes_hash(archive.read(name)) for name in archive.namelist()
                  if name.startswith('lib/') and name.endswith('.so')}
        require(shared == {name: record['sha256'] for name, record in manifest['shared'].items()},
                'APK native inputs differ from the corresponding source manifest')
    distribution.validate_apk_notices(apk_dir)
    with tarfile.open(source / 'repository.tar.gz') as repository:
        expected = {}
        for member in repository:
            if member.isfile() and (member.name in ('LICENSE', 'CREDITS.md') or member.name.startswith('licenses/')):
                expected[member.name] = repository.extractfile(member).read()
        expected['DEPENDENCY-LICENSES.md'] = repository.extractfile('android/DEPENDENCY-LICENSES.md').read()
        readme = repository.extractfile('android/DISTRIBUTION-README.md').read().decode()
        source_name, _ = distribution.artifact_names(manifest['commit'], manifest['run_id'], manifest['run_attempt'])
        readme = readme.replace('@SOURCE_NAME@', source_name).replace('@RUN_URL@',
                   f'https://github.com/{manifest["repository"]}/actions/runs/{manifest["run_id"]}')
        expected['README.md'] = readme.encode()
    expected['manifest.json'] = (source / 'manifest.json').read_bytes()
    expected['app-debug.apk'] = (apk_dir / 'app-debug.apk').read_bytes()
    require({str(p.relative_to(apk_dir)) for p in apk_dir.rglob('*') if p.is_file()} == set(expected),
            'Missing/extra APK artefact contents')
    for name, data in expected.items():
        require((apk_dir / name).read_bytes() == data, 'Mismatched APK notice/content: ' + name)
    return manifest


def package(source, apk_dir, destination, source_id, apk_id, expected_cert):
    manifest = validate_pair(source, apk_dir, expected_cert)
    require(manifest['repository'] == REPOSITORY, 'Foreign source repository')
    short = manifest['commit'][:9]
    destination.mkdir(parents=True, exist_ok=False)
    names = {'apk': f'es-de-plus-{short}-debug.apk', 'source': f'es-de-plus-{short}-source.tar',
             'licences': f'es-de-plus-{short}-licenses.zip'}
    # Standalone release source tar carries the entire exact Actions source set.
    # Normalize outer packaging only; do not modify any source file or APK byte.
    with tarfile.open(destination / names['source'], 'w') as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file():
                info = tarfile.TarInfo(str(path.relative_to(source)))
                info.size = path.stat().st_size; info.mode = 0o644
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
    with zipfile.ZipFile(destination / names['licences'], 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(apk_dir.rglob('*')):
            if path.is_file() and path.name != 'app-debug.apk':
                info = zipfile.ZipInfo(str(path.relative_to(apk_dir)), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
    import shutil
    shutil.copyfile(apk_dir / 'app-debug.apk', destination / names['apk'])
    files = {name: {'sha256': distribution.digest(destination / name), 'size': (destination / name).stat().st_size}
             for name in names.values()}
    sums = ''.join(f'{files[name]["sha256"]}  {name}\n' for name in sorted(files))
    (destination / 'SHA256SUMS.txt').write_text(sums)
    files['SHA256SUMS.txt'] = {'sha256': distribution.digest(destination / 'SHA256SUMS.txt'),
                              'size': (destination / 'SHA256SUMS.txt').stat().st_size}
    require(all(0 < record['size'] < ASSET_LIMIT for record in files.values()), 'Release asset exceeds GitHub size limit')
    origin = {k: manifest[k] for k in ('repository', 'commit', 'run_id', 'run_attempt')}
    origin.update(schema=1, source_id=str(source_id), apk_id=str(apk_id), files=files,
                  version_code=manifest['apk']['version_code'], version_name=manifest['apk']['version_name'],
                  signer_sha256=manifest['apk']['signer_sha256'], apk_sha256=manifest['apk']['sha256'])
    tag = 'android-test-' + short
    text = pathlib.Path('android/RELEASE-NOTES.md').read_text()
    substitutions = {'SHA': manifest['commit'], 'SHORT': short, 'TAG': tag, 'RUN': manifest['run_id'],
                     'ATTEMPT': manifest['run_attempt'], 'VERSION': origin['version_name'],
                     'CODE': str(origin['version_code']), 'CERT': origin['signer_sha256'],
                     'HASH': origin['apk_sha256'], 'APK': names['apk'], 'SOURCE': names['source'],
                     'LICENCES': names['licences']}
    for key, value in substitutions.items():
        text = text.replace('@' + key + '@', value)
    text += '\n<!-- ESDEPLUS-PROVENANCE ' + json.dumps(origin, sort_keys=True) + ' -->\n'
    return {'tag_name': tag, 'target_commitish': manifest['commit'],
            'name': 'ES-DE-Plus Android test build ' + short, 'body': text,
            'draft': True, 'prerelease': True, 'make_latest': 'false'}, origin


class GitHub:
    """The only writing transport. Never constructed by a branch/PR run."""
    def request(self, endpoint, method='GET', body=None, raw=None, output=None):
        require(endpoint.startswith((f'repos/{REPOSITORY}/', f'https://uploads.github.com/repos/{REPOSITORY}/')),
                'Foreign release endpoint')
        args = ['gh', 'api', endpoint, '--method', method]
        if raw:
            args += ['-H', 'Content-Type: application/octet-stream', '--input', str(raw)]
        elif body is not None:
            args += ['--input', '-']
        elif not output:
            args += ['-H', 'Accept: application/vnd.github+json']
        if output:
            args += ['-H', 'Accept: application/octet-stream']
            with output.open('wb') as stream:
                subprocess.run(args, stdout=stream, check=True)
            return
        result = subprocess.check_output(args, input=json.dumps(body).encode() if body is not None else None)
        return json.loads(result)

    def releases(self):
        result = []; page = 1
        while True:
            batch = self.request(f'repos/{REPOSITORY}/releases?per_page=100&page={page}')
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def tag(self, name):
        # Listing refs distinguishes absence from API/auth/network failure.
        refs = self.request(f'repos/{REPOSITORY}/git/matching-refs/tags/{name}')
        exact = [ref for ref in refs if ref['ref'] == 'refs/tags/' + name]
        require(len(exact) <= 1, 'Ambiguous release tag')
        if not exact:
            return None
        value = exact[0]['object']
        for _ in range(8):
            if value['type'] == 'commit':
                return value['sha']
            require(value['type'] == 'tag', 'Release tag does not resolve to a commit')
            value = self.request(f'repos/{REPOSITORY}/git/tags/{value["sha"]}')['object']
        raise ValueError('Release tag chain too deep')

    def create(self, description):
        return self.request(f'repos/{REPOSITORY}/releases', 'POST', description)

    def upload(self, release, path):
        endpoint = release['upload_url'].split('{')[0] + '?name=' + urllib.parse.quote(path.name)
        return self.request(endpoint, 'POST', raw=path)

    def assets(self, release):
        result = []; page = 1
        while True:
            batch = self.request(f'repos/{REPOSITORY}/releases/{release["id"]}/assets?per_page=100&page={page}')
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def download(self, asset, path):
        self.request(f'repos/{REPOSITORY}/releases/assets/{asset["id"]}', output=path)

    def publish(self, release):
        return self.request(f'repos/{REPOSITORY}/releases/{release["id"]}', 'PATCH',
                            {'draft': False, 'prerelease': True, 'make_latest': 'false'})


class Memory:
    """Non-writing transport: the same packaging and decisions, zero release API calls."""
    def __init__(self):
        self.records = []; self.tags = {}; self.data = {}; self.operations = []
        self.fail_upload = False; self.fail_publish = False

    def releases(self):
        return copy.deepcopy(self.records)

    def tag(self, name):
        return self.tags.get(name)

    def create(self, description):
        self.operations.append('draft')
        record = dict(description, id=len(self.records) + 1, assets=[])
        self.records.append(record)
        return copy.deepcopy(record)

    def assets(self, release):
        return copy.deepcopy(next(r for r in self.records if r['id'] == release['id'])['assets'])

    def upload(self, release, path):
        require(not self.fail_upload, 'Injected release upload failure')
        self.operations.append('upload:' + path.name)
        data = path.read_bytes(); identity = len(self.data) + 1
        record = {'id': identity, 'name': path.name, 'size': len(data), 'state': 'uploaded',
                  'digest': 'sha256:' + bytes_hash(data)}
        self.data[identity] = data
        next(r for r in self.records if r['id'] == release['id'])['assets'].append(record)
        return record

    def download(self, asset, path):
        path.write_bytes(self.data[asset['id']])

    def publish(self, release):
        require(not self.fail_publish, 'Injected release publish failure')
        self.operations.append('publish')
        record = next(r for r in self.records if r['id'] == release['id'])
        record['draft'] = False
        self.tags[record['tag_name']] = record['target_commitish']
        return copy.deepcopy(record)


def verify_asset(transport, asset, expected, directory):
    require(asset['state'] == 'uploaded' and asset['size'] == expected['size'] and
            asset.get('digest') == 'sha256:' + expected['sha256'], 'Release asset metadata/hash conflict')
    # Download every asset, including source, before publishing and on retries.
    with tempfile.TemporaryDirectory(dir=directory.parent) as temporary:
        path = pathlib.Path(temporary) / 'asset'
        transport.download(asset, path)
        require(path.stat().st_size == expected['size'] and distribution.digest(path) == expected['sha256'],
                'Downloaded release asset is corrupt')


def deliver(transport, description, origin, directory):
    records = transport.releases()
    matches = [record for record in records if record['tag_name'] == description['tag_name']]
    require(len(matches) <= 1, 'Duplicate release tag')
    tag_commit = transport.tag(description['tag_name'])
    require(tag_commit in (None, origin['commit']), 'Existing tag points to the wrong full commit')
    release = matches[0] if matches else None
    if release:
        require(provenance(release) == origin and release['body'] == description['body'] and
                release['name'] == description['name'] and release['prerelease'], 'Release provenance conflicts')
        require(release['target_commitish'] == origin['commit'], 'Release target conflicts')
    if not release or release['draft']:
        # Refuse out-of-order publication, including an old interrupted draft.
        for record in records:
            if not record['draft'] and record['tag_name'].startswith('android-test-') and MARKER.search(record.get('body') or ''):
                prior = provenance(record)
                require(origin['version_code'] > prior['version_code'], 'Delayed older/equal-code publication refused')
    if not release:
        release = transport.create(description)
    assets = transport.assets(release)
    require(len({a['name'] for a in assets}) == len(assets) and
            set(a['name'] for a in assets) <= set(origin['files']), 'Extra/duplicate release assets')
    # Validate all existing assets before the first mutation on a retry.
    for asset in assets:
        verify_asset(transport, asset, origin['files'][asset['name']], directory)
    existing = {a['name'] for a in assets}
    missing = set(origin['files']) - existing
    require(release['draft'] or not missing, 'Completed release has missing assets; never repair/overwrite it')
    if release['draft']:
        for name in sorted(missing):
            asset = transport.upload(release, directory / name)
            verify_asset(transport, asset, origin['files'][name], directory)
        assets = transport.assets(release)
        require(len(assets) == 4 and {a['name'] for a in assets} == set(origin['files']), 'Incomplete staged release')
        for asset in assets:
            verify_asset(transport, asset, origin['files'][asset['name']], directory)
        require(transport.tag(description['tag_name']) in (None, origin['commit']), 'Tag changed during staging')
        release = transport.publish(release)
    require(not release['draft'] and release['prerelease'] and provenance(release) == origin and
            transport.tag(description['tag_name']) == origin['commit'], 'Release publication did not complete')
    assets = transport.assets(release)
    require(len(assets) == 4 and {a['name'] for a in assets} == set(origin['files']), 'Published asset set differs')
    for asset in assets:
        verify_asset(transport, asset, origin['files'][asset['name']], directory)
    print('PASS: complete immutable pre-release verified: ' + description['tag_name'])


def rejected(label, action):
    try:
        action()
    except (ValueError, FileNotFoundError):
        print('PASS: release control rejected: ' + label)
    else:
        raise ValueError('Release control escaped: ' + label)


def controls(description, origin, directory):
    transport = Memory()
    deliver(transport, description, origin, directory)
    operations = transport.operations[:]
    deliver(transport, description, origin, directory)
    require(transport.operations == operations, 'Completed matching retry mutated a release')
    print('PASS: completed same-origin rerun verified without mutation')
    for label in ('wrong tag', 'conflicting APK', 'corrupt source', 'missing asset', 'extra asset', 'mismatched provenance'):
        broken = copy.deepcopy(transport)
        if label == 'wrong tag':
            broken.tags[description['tag_name']] = 'f' * 40
        elif label in ('conflicting APK', 'corrupt source'):
            asset = next(a for a in broken.records[0]['assets'] if a['name'].endswith('.apk' if label == 'conflicting APK' else '.tar'))
            broken.data[asset['id']] = b'corrupt'
        elif label == 'missing asset':
            broken.records[0]['assets'].pop()
        elif label == 'extra asset':
            broken.records[0]['assets'].append(dict(broken.records[0]['assets'][0], name='extra'))
        else:
            broken.records[0]['body'] += '\nwrong provenance'
        before = broken.operations[:]
        rejected(label, lambda: deliver(broken, description, origin, directory))
        require(before == broken.operations, 'Rejection mutated a release')
    staged = Memory()
    draft = staged.create(description)
    first = next(iter(origin['files']))
    staged.upload(draft, directory / first)
    deliver(staged, description, origin, directory)
    require(sum(op == 'draft' for op in staged.operations) == 1 and staged.operations.count('upload:' + first) == 1,
            'Interrupted draft did not resume')
    print('PASS: matching interrupted draft resumed and verified')
    for failure in ('upload', 'publish'):
        broken = Memory(); setattr(broken, 'fail_' + failure, True)
        rejected(failure + ' failure required', lambda: deliver(broken, description, origin, directory))
        require(all(r['draft'] for r in broken.records), 'Failure published an incomplete release')
    older = copy.deepcopy(origin); older['version_code'] -= 1; older['commit'] = 'b' * 40
    delayed = dict(description, tag_name='android-test-' + older['commit'][:9], target_commitish=older['commit'],
                   body='<!-- ESDEPLUS-PROVENANCE ' + json.dumps(older) + ' -->')
    before = transport.operations[:]
    rejected('delayed older-run publication', lambda: deliver(transport, delayed, older, directory))
    require(transport.operations == before, 'Older publication mutated release state')
    print('PASS: dry transport exercised real packaging, all decisions, staging and retries; zero release API calls')


def validate_origin(transport, source, apk_dir):
    manifest = json.loads((source / 'manifest.json').read_text())
    require(manifest['commit'] == os.environ['GITHUB_SHA'] and manifest['run_id'] == os.environ['GITHUB_RUN_ID'] and
            manifest['run_attempt'] == os.environ['ORIGIN_ATTEMPT'], 'Wrong originating run/attempt/commit')
    run = transport.request(f'repos/{REPOSITORY}/actions/runs/{manifest["run_id"]}')
    require(run['repository']['full_name'] == REPOSITORY and run['head_sha'] == manifest['commit'] and
            run['head_branch'] == 'main' and run['event'] in ('push', 'workflow_dispatch'), 'Foreign/ineligible originating run')
    names = distribution.artifact_names(manifest['commit'], manifest['run_id'], manifest['run_attempt'])
    for identity, name in zip((os.environ['SOURCE_ID'], os.environ['APK_ID']), names):
        require(identity.isdecimal() and int(identity) > 0, 'Missing exact artefact ID')
        metadata = transport.request(f'repos/{REPOSITORY}/actions/artifacts/{identity}')
        require(not metadata['expired'] and metadata['name'] == name and
                str(metadata['workflow_run']['id']) == manifest['run_id'] and
                metadata['workflow_run']['head_sha'] == manifest['commit'], 'Wrong artefact provenance')


if __name__ == '__main__':
    import sys
    mode = sys.argv[1]
    require(mode in ('publish', 'dry-run'), 'Unknown release mode')
    source = pathlib.Path(os.getenv('RELEASE_SOURCE', 'android/.deps/distribution/downloaded-source'))
    apk_dir = pathlib.Path(os.getenv('RELEASE_APK', 'android/.deps/distribution/apk'))
    if mode == 'publish':
        require(test_signing.stable_run(), 'Release API transport forbidden on this event/ref/repository/leg')
        transport = GitHub()
        validate_origin(transport, source, apk_dir)
        cert = test_signing.TEST_CERT_SHA256
    else:
        transport = Memory()
        cert = test_signing.expected_cert()
    destination = pathlib.Path('android/.deps/release-assets')
    description, origin = package(source, apk_dir, destination, os.getenv('SOURCE_ID', '1'), os.getenv('APK_ID', '2'), cert)
    if mode == 'dry-run':
        controls(description, origin, destination)
        original = (apk_dir / 'manifest.json').read_bytes()
        try:
            (apk_dir / 'manifest.json').write_text('{}')
            rejected('mismatched APK/source manifest', lambda: validate_pair(source, apk_dir, cert))
        finally:
            (apk_dir / 'manifest.json').write_bytes(original)
    else:
        deliver(transport, description, origin, destination)
        print(f'https://github.com/{REPOSITORY}/releases/tag/{description["tag_name"]}')
