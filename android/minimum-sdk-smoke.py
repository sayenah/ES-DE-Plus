#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Verifies D-023's installation boundary.
import os
import pathlib
import subprocess
import sys

apk = sys.argv[1]
aapt = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0/aapt'
badging = subprocess.check_output([str(aapt), 'dump', 'badging', apk], text=True)
assert "sdkVersion:'31'" in badging and "targetSdkVersion:'36'" in badging, badging
assert subprocess.check_output(
    ['adb', 'shell', 'getprop', 'ro.build.version.sdk'], text=True).strip() == '30'
result = subprocess.run(['adb', 'install', '-r', apk], capture_output=True, text=True, timeout=180)
output = result.stdout + result.stderr
record = '\n'.join(line for line in badging.splitlines()
                   if 'sdkVersion:' in line or 'targetSdkVersion:' in line) + '\n' + output
evidence = pathlib.Path('android/evidence')
evidence.mkdir(parents=True, exist_ok=True)
(evidence / 'minimum-sdk-api30.txt').write_text(record)
print(record, flush=True)
assert result.returncode != 0 and 'INSTALL_FAILED_OLDER_SDK' in output, output
print('PASS: API 30 rejects the actual minSdk 31 / targetSdk 36 frontend APK')
