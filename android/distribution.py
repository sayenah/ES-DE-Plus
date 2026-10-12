#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. D-009 source provenance and publication gates.
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import time
import zipfile

ROOT = pathlib.Path.cwd()
ABIS = ['arm64-v8a', 'x86_64']
REPOSITORY = 'sayenah/ES-DE-Plus'
LICENCES = {
    'icu': 'Unicode-3.0 / ICU', 'libpng': 'libpng-2.0', 'harfbuzz': 'MIT',
    'freetype': 'FTL selected', 'libgit2': 'GPL-2.0 with linking exception',
    'pugixml': 'MIT', 'SDL': 'zlib', 'ogg': 'BSD-3-Clause', 'dav1d': 'BSD-2-Clause',
    'ffmpeg': 'LGPL-2.1-or-later and permissive notices; GPL/nonfree disabled',
    'libiconv': 'LGPL-2.1-or-later runtime', 'gettext': 'LGPL-2.1-or-later runtime',
    'openssl': 'Apache-2.0', 'curl': 'curl (MIT-like)',
    'freeimage': 'FIPL, GPL-2.0 or GPL-3.0; FIPL selected; bundled codec notices; LibRaw LGPL-2.1 or CDDL-1.0; LGPL-2.1 selected',
}
LIBRARIES = {
    **dict.fromkeys(['libmain.so', 'libes-core.a'], 'repository'),
    'libes-pdf-convert.so': 'repository', 'libc++_shared.so': 'NDK',
    **dict.fromkeys(['libSDL2.so', 'libSDL2main.a'], 'SDL'),
    **dict.fromkeys(['libavcodec.so', 'libavfilter.so', 'libavformat.so', 'libavutil.so',
                    'libswresample.so', 'libswscale.so', 'libavdevice.so'], 'ffmpeg'),
    'libiconv.so': 'libiconv', 'libcharset.so': 'libiconv',
    'libintl.so': 'gettext', 'libgnu.a': 'gettext', 'libfreeimage.so': 'freeimage',
    'libfreetype.so': 'freetype', 'libgit2.so': 'libgit2', 'libcurl.so': 'curl',
    **dict.fromkeys(['libcrypto.so', 'libssl.so', 'libcrypto.a', 'libssl.a', 'libcommon.a',
                    'libdefault.a', 'liblegacy.a', 'libtemplate.a', 'capi.so', 'dasync.so',
                    'loader_attic.so', 'ossltest.so', 'padlock.so', 'legacy.so'], 'openssl'),
    'libpng16.so': 'libpng', 'libpng16.a': 'libpng', 'libogg.so': 'ogg',
    **dict.fromkeys(['libharfbuzz.so', 'libharfbuzz-gpu.so', 'libharfbuzz-raster.so',
                    'libharfbuzz-vector.so'], 'harfbuzz'),
    **dict.fromkeys(['libdav1d.so', 'libdav1d_bitdepth_8.a', 'libdav1d_bitdepth_16.a',
                    'libdav1d_input.a'], 'dav1d'),
    **dict.fromkeys(['libicudata.a', 'libicui18n.a', 'libicuuc.a', 'libicutu.a',
                    'libicutest.a'], 'icu'), 'libpugixml.a': 'pugixml',
    'liblunasvg.a': 'external/lunasvg', 'libplutovg.a': 'external/lunasvg',
    'librlottie.a': 'external/rlottie',
}
CODECS = {
    'LibJPEG': 'IJG', 'LibPNG': 'libpng', 'LibTIFF4': 'BSD', 'ZLib': 'zlib',
    'LibOpenJPEG': 'BSD-2-Clause', 'OpenEXR': 'BSD', 'LibRawLite': 'LGPL-2.1 or CDDL-1.0; LGPL-2.1 selected',
    'LibWebP': 'BSD-3-Clause', 'LibJXR': 'BSD-2-Clause',
}
DEX_SOURCES = {
    'org.jetbrains.kotlin:kotlin-stdlib:2.2.21': {
        'url': 'https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/2.2.21/kotlin-stdlib-2.2.21-sources.jar',
        'sha256': '664f515359444a92267a13266101431a630f99d6b8d04407a92b1a0e558d33ee',
        'file': 'archives/kotlin-stdlib-sources.jar', 'licence': 'Apache-2.0; licenses/Kotlin'},
    'org.jetbrains:annotations:13.0': {
        'url': 'https://repo.maven.apache.org/maven2/org/jetbrains/annotations/13.0/annotations-13.0-sources.jar',
        'sha256': '42a5e144b8e81d50d6913d1007b695e62e614705268d8cf9f13dbdc478c2c68e',
        'file': 'archives/annotations-sources.jar', 'licence': 'Apache-2.0; licenses/Kotlin'},
}
FONT_PATH = 'resources/fonts/FreeMono.ttf'
FONT_SOURCE = {
    'url': 'https://ftp.gnu.org/gnu/freefont/freefont-src-20120503.tar.gz',
    'sha256': '0d62e2e22655f841c3ac5fb8c8059a52fe2c09c695d9e8eda9903406e942657a',
    'file': 'archives/freefont.archive', 'release': '20120503',
    'licence': 'GPL-3.0; licenses/GNUFreeFont',
}
FONT_SHA256 = 'fb1fc7fbdfaf524841d2a6d57d9b0c9add87f6bdcfdde7fc2b27821d7ae0b454'
FONT_VERSION = '0412.2268'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with pathlib.Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def ttf_version(data):
    # OpenType name ID 5 is the version string; the bundled font has Unicode names.
    count = struct.unpack_from('>H', data, 4)[0]
    tables = {tag: (offset, size) for tag, checksum, offset, size in
              (struct.unpack_from('>4sIII', data, 12 + 16 * i) for i in range(count))}
    start, size = tables[b'name']
    form, count, strings = struct.unpack_from('>HHH', data, start)
    versions = set()
    for i in range(count):
        platform, encoding, language, name, length, position = struct.unpack_from(
            '>HHHHHH', data, start + 6 + 12 * i)
        if name == 5 and platform in {0, 3}:
            text = data[start + strings + position:start + strings + position + length].decode('utf-16-be').strip()
            require(text.startswith('Version '), 'Missing FreeMono version prefix')
            versions.add(text.removeprefix('Version '))
    require(len(versions) == 1, 'Missing or inconsistent FreeMono TTF version')
    return versions.pop()


def match_font_versions(binary, source, name):
    require(binary == source == FONT_VERSION and name == 'FreeMono',
            'FreeMono source/font version mismatch')


def font_mapping(archive, font):
    require(digest(archive) == FONT_SOURCE['sha256'], 'FreeFont source checksum mismatch')
    require(hashlib.sha256(font).hexdigest() == FONT_SHA256, 'Bundled FreeMono checksum mismatch')
    with tarfile.open(archive) as source:
        members = [e for e in source if e.isfile() and e.name.endswith('/sfd/FreeMono.sfd')]
        require(len(members) == 1, 'Missing or ambiguous FreeMono source')
        text = source.extractfile(members[0]).read().decode()
        version = re.search(r'^Version: (.+)$', text, re.M)
        name = re.search(r'^FontName: (.+)$', text, re.M)
        require(version and name, 'Missing FreeMono source metadata')
        binary = ttf_version(font)
        match_font_versions(binary, version[1].strip(), name[1].strip())
        return {'archive': 'freefont', 'source_path': members[0].name,
                'font_sha256': FONT_SHA256, 'font_version': binary, **FONT_SOURCE}


def font_ci():
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'FreeFont is fetched in CI only')
    archive = ROOT / 'android/.deps/downloads/freefont.archive'
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        subprocess.check_call(['curl', '--fail', '--location', '--retry', '3',
                               FONT_SOURCE['url'], '-o', str(archive)])
    font = (ROOT / FONT_PATH).read_bytes()
    record = font_mapping(archive, font)
    print(json.dumps(record, indent=2))
    for binary, source, name in [('wrong', FONT_VERSION, 'FreeMono'),
                                 (FONT_VERSION, 'wrong', 'FreeMono'),
                                 (FONT_VERSION, FONT_VERSION, 'wrong')]:
        try:
            match_font_versions(binary, source, name)
        except ValueError as error:
            print(f'PASS: wrong font/source metadata rejected: {error}')
        else:
            raise ValueError('Font metadata control escaped')
    with tempfile.TemporaryDirectory(dir=archive.parent) as temporary:
        corrupt = pathlib.Path(temporary) / 'freefont.archive'
        corrupt.write_bytes(b'corrupt FreeFont source control')
        for path, binary in [(corrupt, font), (archive, b'corrupt font control')]:
            try:
                font_mapping(path, binary)
            except ValueError as error:
                print(f'PASS: corrupt font/source rejected: {error}')
            else:
                raise ValueError('Font integrity control escaped')
    print(f'PASS: bundled FreeMono Version {record["font_version"]} matches official GNU FreeFont {FONT_SOURCE["release"]}')


def dependency_cache(key, hit):
    require(isinstance(key, str) and re.fullmatch(r'android-ndk28\.2\.13676358-api29-[a-f0-9]{64}', key),
            'Missing or invalid dependency-cache key')
    require(isinstance(hit, bool), 'Invalid dependency-cache hit state')
    return {'key': key, 'hit': hit}


def publication_result(eligible, outcome, artifact_id):
    if eligible:
        require(outcome == 'success' and str(artifact_id).isdecimal() and int(artifact_id) > 0,
                'Eligible main publication missed its APK upload')
    else:
        require(outcome == 'skipped' and not artifact_id, 'Unexpected APK upload outside main')


def verify_publication(injection):
    validate_injection(injection)
    eligible = permitted_publication(os.environ['GITHUB_REPOSITORY'],
                                     os.environ['GITHUB_EVENT_NAME'], os.environ['GITHUB_REF'])
    # Simulate only the eligible-main verdict; the actual upload guard stays main-only.
    if injection == 'apk-upload':
        eligible = True
    publication_result(eligible, os.environ['APK_UPLOAD_OUTCOME'], os.environ.get('APK_ARTIFACT_ID', ''))
    print('PASS: APK publication completed' if eligible else 'PASS: dry run uploaded no APK')


def audit_module():
    spec = importlib.util.spec_from_file_location('license_inputs', ROOT / 'android/license-inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pins(text):
    result = {name: {'url': url, 'sha256': sha, 'file': f'archives/{name}.archive',
                     'licence': LICENCES[name]}
              for name, url, sha in re.findall(r'^fetch (\w+) (\S+) ([a-f0-9]{64})$', text, re.M)}
    freeimage = re.search(r'archive=\$archives/freeimage.zip\nexpected=([a-f0-9]{64})', text)
    url = re.search(r'curl --fail --location --retry 3 (\S+FreeImage3180.zip)', text)
    require(freeimage and url, 'Missing FreeImage pin')
    result['freeimage'] = {'url': url[1], 'sha256': freeimage[1], 'file': 'archives/freeimage.zip',
                           'licence': LICENCES['freeimage']}
    require(set(result) == set(LICENCES), 'Archive component set changed without provenance review')
    return result


def provenance(path, tracked, audit):
    audit.permitted(path)
    parts = pathlib.PurePosixPath(path.replace('\\ ', ' ')).parts
    require('..' not in parts and not path.startswith('/'), f'Unsafe input: {path}')
    if path.startswith('NDK/'):
        return {'toolchain': 'NDK 28.2.13676358', 'path': path[4:],
                'licence': 'Apache-2.0 with LLVM exception; NDK sysroot/system notices',
                'source': 'https://android.googlesource.com/toolchain/llvm-project/'}
    if path in tracked:
        return {'repository_path': path,
                'licence': 'CeCILL-C selected' if path.startswith('external/CImg/') else
                           'Preserved repository licence and copyright notices'}
    if parts[:3] == ('android', '.deps', 'sources'):
        return {'archive': parts[3], 'source_path': '/'.join(parts[4:])}
    if parts[:3] == ('android', '.deps', 'build'):
        component = 'freeimage' if parts[4] == 'freeimage-project' else parts[4]
        return {'archive': component, 'generated_path': path,
                'recipe': 'tools/Android_dependencies_build.sh'}
    name = audit.library_name(path)
    if name in LIBRARIES:
        component = LIBRARIES[name]
        if component in LICENCES:
            return {'archive': component, 'library': name, 'recipe': 'tools/Android_dependencies_build.sh'}
        if component == 'NDK':
            abi = next((part for part in parts if part in ABIS), None)
            require(abi is not None, 'Unidentified NDK runtime ABI')
            triple = 'aarch64-linux-android' if abi == 'arm64-v8a' else 'x86_64-linux-android'
            return provenance('NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/' +
                              triple + '/' + name, tracked, audit)
        return {'repository_path': component if component != 'repository' else
                ('android/pdf/ConvertPDF.cpp' if name == 'libes-pdf-convert.so' else 'CMakeLists.txt'),
                'library': name, 'recipe': 'android/app/build.gradle.kts'}
    if parts[:3] == ('android', '.deps', 'install') and parts[4] == 'include':
        header = '/'.join(parts[5:])
        prefix = parts[5]
        component = {'unicode': 'icu', 'curl': 'curl', 'harfbuzz': 'harfbuzz', 'freetype2': 'freetype',
                     'openssl': 'openssl', 'git2': 'libgit2', 'git2.h': 'libgit2', 'SDL2': 'SDL',
                     'dav1d': 'dav1d', 'libpng16': 'libpng', 'png.h': 'libpng', 'pngconf.h': 'libpng',
                     'pnglibconf.h': 'libpng', 'iconv.h': 'libiconv', 'libcharset.h': 'libiconv',
                     'localcharset.h': 'libiconv', 'libintl.h': 'gettext', 'FreeImage.h': 'freeimage',
                     'pugixml.hpp': 'pugixml', 'pugiconfig.hpp': 'pugixml', 'ogg': 'ogg'}.get(prefix)
        if prefix in {'libavcodec', 'libavfilter', 'libavformat', 'libavutil', 'libswresample', 'libswscale'}:
            component = 'ffmpeg'
        require(component is not None, f'Unmapped installed header: {path}')
        return {'archive': component, 'installed_header': header, 'recipe': 'tools/Android_dependencies_build.sh'}
    if path == 'android/.deps/layout/generated/libintl.h':
        return {'archive': 'gettext', 'recipe': 'tools/Android_dependencies_build.sh'}
    if path == 'android/.deps/layout/generated/libavutil/avconfig.h':
        return {'archive': 'ffmpeg', 'recipe': 'tools/Android_dependencies_build.sh'}
    if parts[:3] == ('android', 'app', '.cxx'):
        return {'repository_path': 'android/app/build.gradle.kts', 'generated_path': path,
                'recipe': 'CMakeLists.txt; compiled graph in this manifest'}
    require(False, f'Unmapped input: {path}')


def permitted_publication(repository, event, ref):
    return repository == REPOSITORY and event in {'push', 'workflow_dispatch'} and ref == 'refs/heads/main'


def artifact_names(commit, run_id, attempt):
    require(re.fullmatch('[a-f0-9]{40}', commit) and str(run_id).isdecimal() and str(attempt).isdecimal(),
            'Invalid artefact identity')
    source = f'es-de-plus-source-{commit[:9]}-run{run_id}-attempt{attempt}'
    return source, source.replace('-source-', '-debug-apk-')


def validate_injection(injection):
    require(not injection or injection == 'none' or
            not permitted_publication(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_EVENT_NAME'],
                                      os.environ['GITHUB_REF']), 'Failure injection is forbidden on main')


def gate(android, linux, source):
    require(android == 'success', f'Publication suppressed: Android result {android}')
    require(linux == 'success', f'Publication suppressed: Linux result {linux}')
    require(source == 'success', f'Publication suppressed: source result {source}')


def api(endpoint):
    return json.loads(run('gh', 'api', endpoint))


def linux_gate(injection):
    validate_injection(injection)
    event = os.environ['GITHUB_EVENT_NAME']
    payload = json.loads(pathlib.Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    head = payload['pull_request']['head']['sha'] if event == 'pull_request' else os.environ['GITHUB_SHA']
    expected_event = 'pull_request' if event == 'pull_request' else 'push'
    commit = run('git', 'rev-parse', 'HEAD')
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        candidates = api(f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/workflows/build-linux.yml/runs'
                         f'?head_sha={head}&event={expected_event}&per_page=100')['workflow_runs']
        if candidates:
            selected = max(candidates, key=lambda r: r['id'])
            print(f'Linux gate: {selected["html_url"]} SHA={head} status={selected["status"]}', flush=True)
            if selected['status'] == 'completed':
                conclusion = 'failure' if injection == 'linux' else selected['conclusion']
                gate('success', conclusion, 'success')
                jobs = api(f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{selected["id"]}/jobs')['jobs']
                require(len(jobs) == 1 and jobs[0]['conclusion'] == 'success', 'Linux jobs incomplete')
                # New gh versions require explicit permission to read raw ANSI
                # log data. Parse it from a file, without replaying it to a terminal.
                arguments = ['gh', 'api', f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/jobs/{jobs[0]["id"]}/logs']
                if '--allow-escape-sequences' in run('gh', 'api', '--help'):
                    arguments.append('--allow-escape-sequences')
                with tempfile.TemporaryFile(mode='w+', dir=ROOT / 'android/evidence') as log:
                    subprocess.run(arguments, stdout=log, check=True)
                    log.seek(0)
                    logs = log.read()
                match = re.search(r'git log -1 --format=%H\n\S+ ([a-f0-9]{40})', logs)
                require(match and match[1] == commit, 'Linux checkout is not the exact Android-tested commit')
                (ROOT / 'android/evidence/distribution-linux.txt').write_text(
                    f'PASS: {selected["html_url"]} tested checkout {commit}; conclusion success\n')
                return
        time.sleep(20)
    raise ValueError('Publication suppressed: same-commit Linux success timed out after 30 minutes')


def identity(apk):
    tools = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0'
    certificate = run(str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(apk))
    badging = run(str(tools / 'aapt2'), 'dump', 'badging', str(apk))
    require('CN=Android Debug' in certificate and 'Number of signers: 1' in certificate,
            'Expected one Android Debug signer')
    fingerprint = re.search(r'Signer #1 certificate SHA-256 digest: ([a-f0-9]{64})', certificate)
    require(fingerprint is not None, 'Missing signer fingerprint')
    require("package: name='org.esdeplus.frontend'" in badging and
            "application-label:'ES-DE Plus'" in badging and 'application-debuggable' in badging,
            'Unexpected APK identity')
    with zipfile.ZipFile(apk) as archive:
        abis = sorted({name.split('/')[1] for name in archive.namelist() if name.startswith('lib/')})
        require(abis == ABIS, f'Unexpected ABIs: {abis}')
    record = {'sha256': digest(apk), 'signer_sha256': fingerprint[1], 'abis': abis,
              'certificate': certificate, 'badging': badging}
    path = ROOT / 'android/evidence/distribution-apk.txt'
    if path.exists():
        require(json.loads(path.read_text()) == record, 'APK changed after audit/smoke')
    path.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    return record


def source_tree_unmodified(archives):
    # Compare extracted source bytes against the verified originals, including cache restores.
    # Setup creates only .ready/include links and two ABI-neutral generated-header links.
    for component, pin in archives.items():
        source = ROOT / 'android/.deps/sources' / component
        require(source.resolve().is_relative_to(ROOT.resolve()), 'Source tree escapes checkout')
        archive = ROOT / 'android/.deps/downloads' / pathlib.Path(pin['file']).name
        require(digest(archive) == pin['sha256'], f'Corrupt source archive: {component}')
        expected_paths = set()
        if component == 'freeimage':
            with zipfile.ZipFile(archive) as entries:
                for entry in entries.infolist():
                    if not entry.is_dir():
                        expected_paths.add(entry.filename)
                        require(hashlib.sha256(entries.read(entry)).hexdigest() == digest(source / entry.filename),
                                f'Source patch detected: {component}/{entry.filename}')
        else:
            with tarfile.open(archive) as entries:
                for entry in entries:
                    relative = pathlib.PurePosixPath(entry.name).parts[1:]
                    if entry.isfile() or entry.issym() or entry.islnk():
                        expected_paths.add('/'.join(relative))
                    if entry.isfile():
                        require(relative and '..' not in relative, 'Unsafe source archive member')
                        with entries.extractfile(entry) as stream:
                            expected = hashlib.file_digest(stream, 'sha256').hexdigest()
                        require(expected == digest(source.joinpath(*relative)),
                                f'Source patch detected: {component}/{entry.name}')
        generated_links = {'gettext': {'gettext-runtime/intl/libintl.h'},
                           'ffmpeg': {'libavutil/avconfig.h'}}.get(component, set())
        actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
        # SDL2 is an include-directory alias created by setup, not additional source.
        allowed = expected_paths | {'.ready'} | generated_links | ({'SDL2'} if component == 'SDL' else set())
        require(actual <= allowed, f'Added/unmapped source files: {component}: {actual - allowed}')


def archive_members(bundle, archives):
    result = {}
    for component, pin in archives.items():
        archive = bundle / pin['file']
        if component == 'freeimage':
            with zipfile.ZipFile(archive) as entries:
                result[component] = {p for p in entries.namelist() if not p.endswith('/')}
        else:
            with tarfile.open(archive) as entries:
                result[component] = {'/'.join(pathlib.PurePosixPath(p.name).parts[1:])
                                     for p in entries if p.isfile() or p.issym() or p.islnk()}
        require(not any(re.search(r'\.(apk|jks|keystore)$', p, re.I) for p in result[component]),
                f'Forbidden APK/Android keystore in source archive: {component}')
    return result


def make_bundle(apk):
    record = identity(apk)
    audit = audit_module()
    commit = run('git', 'rev-parse', 'HEAD')
    require(commit == os.environ['GITHUB_SHA'], 'Checkout differs from workflow SHA')
    archives = pins((ROOT / 'tools/Android_dependencies_setup.sh').read_text())
    source_tree_unmodified(archives)
    destination = ROOT / 'android/.deps/distribution/source'
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'archives').mkdir()
    subprocess.check_call(['git', 'archive', '--format=tar.gz', '-o', str(destination / 'repository.tar.gz'), commit])
    with tarfile.open(destination / 'repository.tar.gz') as repository:
        tracked = {entry.name for entry in repository if entry.isfile()}
    require(not any(re.search(r'\.(apk|jks|keystore)$', p, re.I) for p in tracked), 'Forbidden tracked binary/key')
    for pin in archives.values():
        shutil.copyfile(ROOT / 'android/.deps/downloads' / pathlib.Path(pin['file']).name,
                        destination / pin['file'])
    # Corresponding sources for the two already-audited dex runtimes, not new dependencies.
    for pin in DEX_SOURCES.values():
        archive = ROOT / 'android/.deps/downloads' / pathlib.Path(pin['file']).name
        if not archive.exists():
            subprocess.check_call(['curl', '--fail', '--location', '--retry', '3', pin['url'], '-o', str(archive)])
        require(digest(archive) == pin['sha256'], 'Dex source archive checksum mismatch')
        shutil.copyfile(archive, destination / pin['file'])
    font_archive = ROOT / 'android/.deps/downloads/freefont.archive'
    asset_sources = {FONT_PATH: font_mapping(font_archive, (ROOT / FONT_PATH).read_bytes())}
    shutil.copyfile(font_archive, destination / FONT_SOURCE['file'])
    graphs = {abi: json.loads((ROOT / f'android/.deps/install/{abi}/license-inputs.json').read_text()) for abi in ABIS}
    graphs['native'] = json.loads((ROOT / 'android/evidence/license-native-inputs.txt').read_text())
    inputs = {path: provenance(path, tracked, audit) for graph in graphs.values()
              for paths in graph.values() for path in paths}
    with zipfile.ZipFile(apk) as archive:
        require(hashlib.sha256(archive.read('assets/fonts/FreeMono.ttf')).hexdigest() == FONT_SHA256,
                'APK FreeMono differs from the mapped repository font')
        shared = {name: {'sha256': hashlib.sha256(archive.read(name)).hexdigest(),
                         **provenance(name.replace('lib/', 'android/libs/', 1), tracked, audit)}
                  for name in archive.namelist() if name.startswith('lib/') and name.endswith('.so')}
    tools = {
        'NDK': (pathlib.Path(os.environ['ANDROID_NDK_HOME']) / 'source.properties').read_text(),
        'java': subprocess.check_output(['java', '-version'], stderr=subprocess.STDOUT, text=True),
        'cmake': run('cmake', '--version'), 'ninja': run('ninja', '--version'),
        'meson': run('meson', '--version'), 'clang': run(str(pathlib.Path(os.environ['ANDROID_NDK_HOME']) /
            'toolchains/llvm/prebuilt/linux-x86_64/bin/clang'), '--version'),
        'Gradle': '8.13', 'AGP': '8.13.2', 'Kotlin': '2.2.21', 'SDK': '36',
        'SDK CMake': '3.31.5', 'build-tools': '36.0.0', 'minSdk': '29',
    }
    require('Pkg.Revision = 28.2.13676358' in tools['NDK'], 'Unexpected NDK provenance')
    require(os.environ.get('DEPENDENCY_CACHE_HIT') in {'true', 'false'}, 'Missing cache restore result')
    cache = dependency_cache(os.environ['DEPENDENCY_CACHE_KEY'], os.environ['DEPENDENCY_CACHE_HIT'] == 'true')
    manifest = {'schema': 2, 'commit': commit, 'run_id': os.environ['GITHUB_RUN_ID'],
                'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'repository': os.environ['GITHUB_REPOSITORY'],
                'apk': record, 'archives': archives, 'graphs': graphs, 'inputs': inputs, 'shared': shared,
                'bundled_codecs': {f'FreeImage/Source/{k}': {'archive': 'freeimage', 'licence': v} for k, v in CODECS.items()},
                'runtime_dex': DEX_SOURCES,
                'asset_sources': asset_sources, 'dependency_cache': cache,
                'toolchain': tools, 'recipes': ['tools/Android_dependencies_setup.sh',
                    'tools/Android_dependencies_build.sh', 'android/app/build.gradle.kts',
                    'CMakeLists.txt', 'android/rebuild-source.sh'],
                'no_patches': 'Every downloaded source file was compared with its pinned archive. No source patches; build flags and generated include layout are recorded in the recipes.',
                'files': {'repository.tar.gz': digest(destination / 'repository.tar.gz'),
                          **{p['file']: p['sha256'] for p in archives.values()},
                          **{p['file']: p['sha256'] for p in DEX_SOURCES.values()},
                          FONT_SOURCE['file']: FONT_SOURCE['sha256']}}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    validate_bundle(destination)
    apk_dir = destination.parent / 'apk'
    apk_dir.mkdir()
    shutil.copyfile(apk, apk_dir / 'app-debug.apk')
    # Notices come from the exact source commit, never an incidental/untracked file.
    with tarfile.open(destination / 'repository.tar.gz') as repository:
        for path in sorted(tracked):
            if path == 'LICENSE' or path.startswith('licenses/'):
                notice = apk_dir / path
                notice.parent.mkdir(parents=True, exist_ok=True)
                notice.write_bytes(repository.extractfile(path).read())
        (apk_dir / 'DEPENDENCY-LICENSES.md').write_bytes(
            repository.extractfile('android/DEPENDENCY-LICENSES.md').read())
        text = repository.extractfile('android/DISTRIBUTION-README.md').read().decode()
    shutil.copyfile(destination / 'manifest.json', apk_dir / 'manifest.json')
    source_name, apk_name = artifact_names(commit, manifest['run_id'], manifest['run_attempt'])
    text = text.replace('@SOURCE_NAME@', source_name)
    text = text.replace('@RUN_URL@', f'https://github.com/{manifest["repository"]}/actions/runs/{manifest["run_id"]}')
    (apk_dir / 'README.md').write_text(text)
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a') as stream:
            stream.write(f'source_name={source_name}\napk_name={apk_name}\n')
    print(f'PASS: exact source bundle {source_name}; APK SHA256 {record["sha256"]}')


def validate_bundle(bundle):
    manifest = json.loads((bundle / 'manifest.json').read_text())
    require(manifest['schema'] == 2 and re.fullmatch('[a-f0-9]{40}', manifest['commit']), 'Invalid manifest commit')
    require(manifest['dependency_cache'] == dependency_cache(
        manifest['dependency_cache']['key'], manifest['dependency_cache']['hit']), 'Unexpected cache metadata')
    require(re.fullmatch('[a-f0-9]{64}', manifest['apk']['sha256']), 'Missing APK hash')
    for file, expected in manifest['files'].items():
        require(file == 'repository.tar.gz' or re.fullmatch(r'archives/[\w-]+\.(archive|zip|jar)', file), 'Unsafe bundle path')
        require(digest(bundle / file) == expected, f'Bundle hash mismatch: {file}')
    with tarfile.open(bundle / 'repository.tar.gz') as repository:
        require(repository.pax_headers.get('comment') == manifest['commit'], 'git archive commit mismatch')
        tracked = {entry.name for entry in repository if entry.isfile()}
        actual_pins = pins(repository.extractfile('tools/Android_dependencies_setup.sh').read().decode())
        asset_sources = {FONT_PATH: font_mapping(bundle / FONT_SOURCE['file'],
                                                repository.extractfile(FONT_PATH).read())}
    require(manifest['asset_sources'] == asset_sources, 'FreeMono source mapping mismatch')
    require(manifest['files'][FONT_SOURCE['file']] == FONT_SOURCE['sha256'], 'FreeFont source pin mismatch')
    require(manifest['archives'] == actual_pins, 'Source pins differ from the archived build recipe')
    for pin in actual_pins.values():
        require(manifest['files'][pin['file']] == pin['sha256'], 'Archive file hash differs from pin')
    require(manifest['runtime_dex'] == DEX_SOURCES, 'Unmapped dex runtime input')
    for pin in DEX_SOURCES.values():
        require(manifest['files'][pin['file']] == pin['sha256'], 'Dex source hash differs from pin')
    require(set(manifest['files']) == {'repository.tar.gz'} | {p['file'] for p in actual_pins.values()} |
            {p['file'] for p in DEX_SOURCES.values()} | {FONT_SOURCE['file']}, 'Missing/extra source files')
    require(all(path in tracked for path in manifest['recipes']), 'Build recipe absent from exact source archive')
    require('No source patches' in manifest['no_patches'], 'Missing no-patches declaration')
    expected_files = {'manifest.json'} | set(manifest['files'])
    require({str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file()} == expected_files,
            'Incidental output in source bundle')
    audit = audit_module()
    members = archive_members(bundle, actual_pins)
    require(set(manifest['graphs']) == set(ABIS) | {'native'}, 'Missing actual input graph')
    expected_inputs = set()
    for graph in manifest['graphs'].values():
        require(set(graph) == {'compiled', 'headers', 'links'} and all(graph.values()), 'Incomplete input graph')
        for paths in graph.values():
            expected_inputs.update(paths)
    require(set(manifest['inputs']) == expected_inputs, 'Input manifest incomplete')
    for path, mapping in manifest['inputs'].items():
        require(mapping == provenance(path, tracked, audit), f'Unmapped/mismatched input: {path}')
        if 'source_path' in mapping:
            require(mapping['source_path'] in members[mapping['archive']], f'Input absent from source archive: {path}')
    for abi in ABIS:
        actual = {pathlib.PurePosixPath(p).name for p in manifest['shared'] if p.startswith(f'lib/{abi}/')}
        require(actual == audit.SHARED, f'Shared closure mismatch: {abi}')
    require(len(manifest['shared']) == len(ABIS) * len(audit.SHARED), 'Extra ABI/shared entries')
    for path, mapping in manifest['shared'].items():
        require(re.fullmatch('[a-f0-9]{64}', mapping['sha256']), 'Missing shared-input hash')
        require({k: v for k, v in mapping.items() if k != 'sha256'} ==
                provenance(path.replace('lib/', 'android/libs/', 1), tracked, audit), 'Shared input mapping mismatch')
    require(manifest['bundled_codecs'] == {f'FreeImage/Source/{k}': {'archive': 'freeimage', 'licence': v}
                                         for k, v in CODECS.items()}, 'Missing bundled codec provenance')
    print(f'PASS: validated source commit {manifest["commit"]}, run {manifest["run_id"]}, attempt {manifest["run_attempt"]}')
    return manifest


def uploaded_source(injection):
    validate_injection(injection)
    source = ROOT / 'android/.deps/distribution/source'
    downloaded = source.parent / 'downloaded-source'
    if injection == 'source-validation':
        (downloaded / 'repository.tar.gz').write_bytes(b'injected uploaded-source corruption')
    manifest = validate_bundle(downloaded)
    require((source / 'manifest.json').read_bytes() == (downloaded / 'manifest.json').read_bytes(),
            'Uploaded source differs from this runner source bundle')
    metadata = api(f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/artifacts/{os.environ["SOURCE_ID"]}')
    require(not metadata['expired'] and metadata['name'] == os.environ['SOURCE_NAME'] and
            str(metadata['workflow_run']['id']) == os.environ['GITHUB_RUN_ID'], 'Wrong uploaded source artefact')
    expiry = datetime.datetime.fromisoformat(metadata['expires_at'].replace('Z', '+00:00'))
    require(expiry > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=13),
            'Uploaded source retention is shorter than 14 days; APK publication suppressed')
    require(manifest['commit'] == os.environ['GITHUB_SHA'] and
            manifest['run_id'] == os.environ['GITHUB_RUN_ID'] and
            manifest['run_attempt'] == os.environ['GITHUB_RUN_ATTEMPT'], 'Wrong uploaded source identity')
    require(digest(source.parent / 'apk/app-debug.apk') == manifest['apk']['sha256'], 'Staged APK hash changed')
    print(f'PASS: uploaded source {metadata["id"]} independently downloaded/validated; expires {expiry}; APK retention 7 days')


def bundle_controls(bundle):
    validate_bundle(bundle)
    original = (bundle / 'manifest.json').read_text()
    manifest = json.loads(original)
    archive = bundle / next(iter(manifest['archives'].values()))['file']
    saved = archive.with_suffix('.saved')
    archive.rename(saved)
    try:
        for mode in ['missing', 'corrupt']:
            if mode == 'corrupt':
                archive.write_bytes(b'corrupt archive control')
            try:
                validate_bundle(bundle)
            except (ValueError, FileNotFoundError) as error:
                print(f'PASS: {mode} archive rejected: {error}')
            else:
                raise ValueError(f'{mode} source control escaped')
    finally:
        archive.unlink(missing_ok=True)
        saved.rename(archive)
    for path in ['android/.deps/install/x86_64/include/unmapped.h',
                 'android/.deps/sources/ffmpeg/unmapped-added-source.c']:
        try:
            manifest = json.loads(original)
            manifest['graphs']['native']['headers'].append(path)
            manifest['inputs'][path] = ({'archive': 'ffmpeg', 'source_path': 'unmapped-added-source.c'}
                                        if path.endswith('.c') else {'repository_path': path})
            (bundle / 'manifest.json').write_text(json.dumps(manifest))
            try:
                validate_bundle(bundle)
            except (ValueError, AssertionError) as error:
                print(f'PASS: unmapped input rejected: {error}')
            else:
                raise ValueError('Unmapped input control escaped')
        finally:
            (bundle / 'manifest.json').write_text(original)
    validate_bundle(bundle)


def gate_controls():
    require(permitted_publication(REPOSITORY, 'push', 'refs/heads/main'), 'Main push rejected')
    require(permitted_publication(REPOSITORY, 'workflow_dispatch', 'refs/heads/main'), 'Main dispatch rejected')
    for repository, event, ref in [(REPOSITORY, 'pull_request', 'refs/heads/main'),
                                   (REPOSITORY, 'push', 'refs/heads/feature/distribution-posture'),
                                   ('someone/ES-DE-Plus', 'push', 'refs/heads/main')]:
        require(not permitted_publication(repository, event, ref), 'Non-main publication escaped')
        print(f'PASS: dry-run only: {repository} {event} {ref}')
    gate('success', 'success', 'success')
    for position, label in enumerate(['Android', 'Linux', 'source upload/validation']):
        for failure in ['failure', 'skipped', 'cancelled', '']:
            values = ['success'] * 3
            values[position] = failure
            try:
                gate(*values)
            except ValueError as error:
                print(f'PASS: {label} {failure!r} rejected: {error}')
            else:
                raise ValueError('Gate control escaped')
    first = artifact_names('a' * 40, '123', '1')
    rerun = artifact_names('a' * 40, '123', '2')
    require(set(first).isdisjoint(rerun), 'Rerun artefacts would overwrite an earlier pair')
    print(f'PASS: attempt identities never overwrite: {first} versus {rerun}')
    print('PASS: green gates would publish; no overwrite or delete operation')
    publication_result(True, 'success', '123')
    publication_result(False, 'skipped', '')
    for eligible, outcome, artifact_id in [(True, outcome, '') for outcome in
                                           ['success', 'skipped', 'failure', 'cancelled', '']] + [
                                           (False, 'success', '123')]:
        try:
            publication_result(eligible, outcome, artifact_id)
        except ValueError as error:
            print(f'PASS: missed/forbidden APK upload rejected: {error}')
        else:
            raise ValueError('APK publication control escaped')
    key = 'android-ndk28.2.13676358-api29-' + 'a' * 64
    dependency_cache(key, True)
    dependency_cache(key, False)
    for invalid_key, invalid_hit in [('', False), (key, 'true')]:
        try:
            dependency_cache(invalid_key, invalid_hit)
        except ValueError as error:
            print(f'PASS: invalid cache provenance rejected: {error}')
        else:
            raise ValueError('Cache provenance control escaped')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['identity', 'bundle', 'validate', 'controls', 'gates', 'linux', 'inject', 'uploaded', 'font', 'publication'])
    parser.add_argument('path', nargs='?', default='none')
    args = parser.parse_args()
    if args.mode == 'identity':
        identity(pathlib.Path(args.path))
    elif args.mode == 'bundle':
        make_bundle(pathlib.Path(args.path))
    elif args.mode == 'validate':
        validate_bundle(pathlib.Path(args.path))
    elif args.mode == 'controls':
        bundle_controls(pathlib.Path(args.path))
    elif args.mode == 'gates':
        gate_controls()
    elif args.mode == 'linux':
        linux_gate(args.path)
    elif args.mode == 'uploaded':
        uploaded_source(args.path)
    elif args.mode == 'font':
        font_ci()
    elif args.mode == 'publication':
        verify_publication(args.path)
    else:
        validate_injection(args.path)
