#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Bounded pre-build SDK-download infrastructure retry.
import os
from pathlib import Path
import subprocess
import sys

SIGNATURE = 'Error on ZipFile unknown archive'


def install(run=subprocess.run):
    sdk = Path(os.environ['ANDROID_HOME']) / 'cmdline-tools/latest/bin/sdkmanager'
    command = [str(sdk), 'platforms;android-36', 'build-tools;36.0.0',
               'ndk;28.2.13676358', 'cmake;3.31.5']
    for attempt in range(3):
        result = run(command, capture_output=True, text=True)
        output = result.stdout + result.stderr
        print(output, flush=True)
        if result.returncode == 0:
            return
        if SIGNATURE not in output or attempt == 2:
            raise SystemExit(result.returncode)
        print(f'SDK_DOWNLOAD_INFRASTRUCTURE: corrupt SDK archive; pre-build retry {attempt + 1}/2; no build/session retried', flush=True)


def self_test():
    import contextlib
    import io
    from unittest import mock
    for codes, text, count, success in [([1, 0], SIGNATURE, 2, True),
                                      ([1, 1, 1], SIGNATURE, 3, False),
                                      ([1], 'Unknown package or SDK error', 1, False)]:
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, codes[len(calls)-1], text, '')
        with mock.patch.dict(os.environ, {'ANDROID_HOME': '/sdk'}), contextlib.redirect_stdout(io.StringIO()):
            try:
                install(run)
            except SystemExit:
                assert not success
            else:
                assert success
        assert len(calls) == count
    print('PASS: only exact SDK corrupt-download signature retried; two-retry bound; all other SDK errors fail immediately')


if __name__ == '__main__':
    self_test() if sys.argv[1:] == ['self-test'] else install()
