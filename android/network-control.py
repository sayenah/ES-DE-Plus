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

manifest = pathlib.Path('android/app/src/main/AndroidManifest.xml')
original = manifest.read_bytes()
declaration = b'    <uses-permission android:name="android.permission.INTERNET" />\n'
assert original.count(declaration) == 1
destination = pathlib.Path('android/.deps/network/no-internet.apk')
destination.parent.mkdir(parents=True, exist_ok=True)
evidence = pathlib.Path('android/evidence/network-control-build.txt')
evidence.parent.mkdir(parents=True, exist_ok=True)
try:
    manifest.write_bytes(original.replace(declaration, b''))
    subprocess.run(['./gradlew', '--no-daemon', *shlex.split(os.environ.get('GRADLE_NETWORK_ARGS', '')),
                    ':app:assembleDebug'], cwd='android', check=True)
    shutil.copyfile('android/app/build/outputs/apk/debug/app-debug.apk', destination)
    aapt = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0/aapt'
    badging = subprocess.check_output([str(aapt), 'dump', 'badging', str(destination)], text=True)
    actual = set(re.findall(r"^uses-permission(?:-sdk-\d+)?: name='([^']+)'", badging, re.M))
    expected = {'android.permission.' + name for name in
                ['READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE', 'MANAGE_EXTERNAL_STORAGE']}
    assert actual == expected, actual
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    evidence.write_text(f'CI-only positive control built from {sha} with only INTERNET removed.\n'
                        f'APK SHA256={hashlib.sha256(destination.read_bytes()).hexdigest()}\n' + badging)
    print('PASS: control APK declares exactly the original three permissions; no INTERNET')
finally:
    manifest.write_bytes(original)
    assert manifest.read_bytes() == original
