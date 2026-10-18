#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Hash-bound APK transfer for parallel CI.
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path('android/.deps/ci-apks')
MANIFEST = ROOT / 'manifest.json'
ARCHIVE = ROOT / 'apks.tar'


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def record():
    roots = ['android/app/build/outputs/apk/debug/app-debug.apk',
             'android/app/build/outputs/apk/release/app-release-smoke.apk',
             'android/stub-emulator/build/outputs/apk/debug/stub-emulator-debug.apk',
             'android/forced-relaunch-overlay/build/outputs/apk/debug/forced-relaunch-overlay-debug.apk',
             'android/handler-stub/build/outputs/apk/debug/handler-stub-debug.apk',
             'android/.deps/update', 'android/.deps/network', 'android/.deps/theme-owner',
             'android/evidence/update-identity.txt',
             'android/evidence/test-signer.txt', 'android/.deps/distribution/apk']
    paths = set()
    for name in roots:
        path = Path(name)
        if path.is_dir():
            paths.update(p for p in path.rglob('*') if p.is_file())
        elif path.is_file():
            paths.add(path)
    assert all(not p.is_symlink() and p.suffix not in ('.p12', '.jks', '.keystore') for p in paths)
    assert Path(roots[0]) in paths and Path(roots[1]) in paths and Path(roots[2]) in paths
    value = dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                 files={p.as_posix(): digest(p) for p in sorted(paths)})
    ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('manifest_sha=' + digest(MANIFEST) + '\n')
        output.write('debug_sha=' + value['files'][roots[0]] + '\n')
    print('APK manifest SHA-256:', digest(MANIFEST))
    return value


def pack():
    assert os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch' and os.environ['GITHUB_REF'] == 'refs/heads/main'
    assert os.environ['GITHUB_REPOSITORY'] == 'sayenah/ES-DE-Plus' and os.environ.get('PUBLISH') == 'true'
    value = record()
    with tarfile.open(ARCHIVE, 'w') as archive:
        for name in value['files']:
            archive.add(name, recursive=False)


def verify(expected, unpack=False):
    assert digest(MANIFEST) == expected, 'Transfer manifest SHA-256 differs from build-job output'
    value = json.loads(MANIFEST.read_text())
    assert value['commit'] == subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if unpack:
        with tarfile.open(ARCHIVE) as archive:
            members = archive.getmembers()
            assert len(members) == len(value['files'])
            assert {p.name for p in members} == set(value['files'])
            for member in members:
                path = Path(member.name)
                assert member.isfile() and not path.is_absolute() and '..' not in path.parts
                assert member.name.startswith('android/')
                assert path.suffix not in ('.p12', '.jks', '.keystore')
                with archive.extractfile(member) as data:
                    assert hashlib.file_digest(data, 'sha256').hexdigest() == value['files'][member.name]
            archive.extractall('.', filter='data')
    for name, expected_hash in value['files'].items():
        assert digest(Path(name)) == expected_hash, 'APK set changed: ' + name
        if name.endswith('.apk'):
            print('PASS SHA-256 verified before install/publish:', name, expected_hash)
    if os.environ.get('PUBLISH') == 'true':
        import test_signing
        for apk, debug in ((test_signing.DEBUG, True), (test_signing.RELEASE, False)):
            info = test_signing.inspect_apk(apk, test_signing.TEST_CERT_SHA256, debug)
            assert {k: info[k] for k in test_signing.public_version()} == test_signing.public_version()
        assert Path('android/evidence/test-signer.txt').read_text().strip() == test_signing.TEST_CERT_SHA256
        print('PASS: transferred smoke variants keep the stable signer pin and commit version')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('record', 'pack', 'verify', 'restore'))
    parser.add_argument('expected', nargs='?')
    args = parser.parse_args()
    if args.mode == 'record':
        record()
    elif args.mode == 'pack':
        pack()
    else:
        verify(args.expected, args.mode == 'restore')
