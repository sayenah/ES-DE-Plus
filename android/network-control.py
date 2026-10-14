#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. CI-only APK missing INTERNET, never uploaded.
import hashlib
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import zipfile

manifest = pathlib.Path('android/app/src/main/AndroidManifest.xml')
original = manifest.read_bytes()
declaration = b'    <uses-permission android:name="android.permission.INTERNET" />\n'
assert original.count(declaration) == 1
destination = pathlib.Path('android/.deps/network/no-internet.apk')
destination.parent.mkdir(parents=True, exist_ok=True)
evidence = pathlib.Path('android/evidence/network-control-build.txt')
evidence.parent.mkdir(parents=True, exist_ok=True)
apk = pathlib.Path('android/app/build/outputs/apk/debug/app-debug.apk')
fixed = destination.parent / 'fixed.apk'
shutil.copyfile(apk, fixed)
fixed_hash = hashlib.sha256(fixed.read_bytes()).hexdigest()
exclusions = []
# Only this manifest-only control reuses the native code already compiled by
# normal assembleDebug on both ABIs. The ordinary debug/release builds and
# every audit/smoke gate still run. Re-running native CMake here can link the
# other ABI's upstream root-level libplutovg.a; no CMake/source workaround.
for abi in ('arm64-v8a', 'x86_64'):
    for task in (f'configureCMakeDebug[{abi}]', f'buildCMakeDebug[{abi}][es-pdf-convert,main]'):
        exclusions += ['--exclude-task', ':app:' + task]
try:
    manifest.write_bytes(original.replace(declaration, b''))
    subprocess.run(['./gradlew', '--no-daemon', *shlex.split(os.environ.get('GRADLE_NETWORK_ARGS', '')),
                    ':app:assembleDebug', *exclusions], cwd='android', check=True)
    shutil.copyfile(apk, destination)
    with zipfile.ZipFile(fixed) as before, zipfile.ZipFile(destination) as after:
        payload = {p for p in before.namelist() if p.startswith(('lib/', 'assets/', 'res/')) or
                   re.fullmatch(r'classes\d*\.dex|resources\.arsc', p)}
        assert payload and any(p.startswith('lib/arm64-v8a/') for p in payload)
        assert any(p.startswith('lib/x86_64/') for p in payload)
        assert payload == {p for p in after.namelist() if p.startswith(('lib/', 'assets/', 'res/')) or
                           re.fullmatch(r'classes\d*\.dex|resources\.arsc', p)}
        assert all(before.read(p) == after.read(p) for p in payload), 'Control changed executable/assets payload'
    aapt = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0/aapt'
    badging = subprocess.check_output([str(aapt), 'dump', 'badging', str(destination)], text=True)
    actual = set(re.findall(r"^uses-permission(?:-sdk-\d+)?: name='([^']+)'", badging, re.M))
    expected = {'android.permission.' + name for name in
                ['READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE', 'MANAGE_EXTERNAL_STORAGE']}
    assert actual == expected, actual
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    evidence.write_text(f'CI-only positive control built from {sha} with only INTERNET removed.\n'
                        f'Fixed APK SHA256={fixed_hash}\n'
                        f'Control APK SHA256={hashlib.sha256(destination.read_bytes()).hexdigest()}\n'
                        f'PASS: {len(payload)} executable/asset entries are byte-identical; normal native builds retained.\n' + badging)
    print('PASS: control APK declares exactly the original three permissions; no INTERNET')
finally:
    manifest.write_bytes(original)
    shutil.copyfile(fixed, apk)
    assert manifest.read_bytes() == original
    assert hashlib.sha256(apk.read_bytes()).hexdigest() == fixed_hash, 'Fixed APK was not restored exactly'
    print('PASS: source manifest and exact normally-built fixed APK restored; control APK stays on runner')
