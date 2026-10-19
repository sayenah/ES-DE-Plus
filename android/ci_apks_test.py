#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Transfer corruption and publication-boundary controls.
import contextlib
import io
import os
from pathlib import Path
import tempfile
import tarfile
from unittest import mock

import ci_apks


def rejected(action):
    try:
        action()
    except (AssertionError, FileNotFoundError):
        return
    raise AssertionError('Corrupt/forbidden APK transfer escaped')


with tempfile.TemporaryDirectory() as temporary:
    before = Path.cwd()
    try:
        os.chdir(temporary)
        paths = ('android/app/build/outputs/apk/debug/app-debug.apk',
                 'android/app/build/outputs/apk/release/app-release-smoke.apk',
                 'android/stub-emulator/build/outputs/apk/debug/stub-emulator-debug.apk')
        for name in paths:
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'APK transfer fixture')
        with mock.patch.dict(os.environ, dict(GITHUB_OUTPUT='output', PUBLISH='false',
                             GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/feature/test',
                             GITHUB_REPOSITORY='sayenah/ES-DE-Plus')):
            with mock.patch.object(ci_apks.subprocess, 'check_output', return_value='a' * 40 + '\n'):
                with contextlib.redirect_stdout(io.StringIO()):
                    ci_apks.record()
                    checksum = ci_apks.digest(ci_apks.MANIFEST)
                    ci_apks.verify(checksum)
                    rejected(ci_apks.pack)  # Branch APK artifacts remain forbidden.
                    with mock.patch.dict(os.environ, dict(PUBLISH='true', GITHUB_REF='refs/heads/main')):
                        ci_apks.pack()
                    checksum = ci_apks.digest(ci_apks.MANIFEST)
                    for name in paths:
                        Path(name).unlink()
                    ci_apks.verify(checksum, unpack=True)
                    # A foreign tar member cannot replace even a hash-valid manifest.
                    with tarfile.open(ci_apks.ARCHIVE, 'a') as archive:
                        info = tarfile.TarInfo('../outside.apk')
                        info.size = 3
                        archive.addfile(info, io.BytesIO(b'bad'))
                    rejected(lambda: ci_apks.verify(checksum, unpack=True))
                    assert not Path('../outside.apk').exists()
                    rejected(lambda: ci_apks.verify('0' * 64))
                    Path(paths[0]).write_bytes(b'corrupted in transit')
                    rejected(lambda: ci_apks.verify(checksum))
                    ci_apks.MANIFEST.write_text('{}')
                    rejected(lambda: ci_apks.verify(checksum))
    finally:
        os.chdir(before)
print('PASS: exact APK hashes verified; changed APK/manifest/wrong digest rejected; unsafe archive refused; branch transfer upload refused')
