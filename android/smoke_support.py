#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Emulator/transport readiness, never product retries.
import pathlib
import subprocess
import sys
import time

EVIDENCE = pathlib.Path('android/evidence')


def record(message):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    print(message, flush=True)
    with (EVIDENCE / 'emulator-transport.txt').open('a') as output:
        output.write(message + '\n')


def transport_error(stderr):
    return any(value in stderr for value in (
        'device offline', 'device not found', 'no devices/emulators found',
        'error: closed', 'protocol fault', 'connection reset'))


def connected():
    # Establish transport before sending a command with side effects. A failed
    # UI action/instrumentation is never replayed: execution may be ambiguous.
    for attempt in range(1, 4):
        result = subprocess.run(['adb', 'get-state'], capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip() == 'device':
            if attempt > 1:
                record(f'ADB transport recovered on attempt {attempt}/3')
            return
        record(f'ADB transport attempt {attempt}/3: {result.stdout.strip()} {result.stderr.strip()}')
        if attempt < 3:
            time.sleep(1)
    raise RuntimeError('ADB transport unavailable after three checks; no action sent')


def boot():
    # sys.boot_completed alone precedes PackageManager, mounted shared storage
    # and usable input/window services. Wait for all before installing/driving.
    deadline = time.monotonic() + 120
    previous = None
    checks = {
        'boot': ['shell', 'getprop', 'sys.boot_completed'],
        'package': ['shell', 'pm', 'path', 'android'],
        'activity': ['shell', 'service', 'check', 'activity'],
        'window': ['shell', 'service', 'check', 'window'],
        'storage': ['shell', 'test', '-d', '/sdcard/Android'],
    }
    poll = 0
    while time.monotonic() < deadline:
        poll += 1
        states = {}
        for name, arguments in checks.items():
            try:
                result = subprocess.run(['adb', *arguments], capture_output=True, text=True, timeout=10)
                states[name] = result.returncode == 0 and (
                    result.stdout.strip() == '1' if name == 'boot' else
                    'package:' in result.stdout if name == 'package' else
                    'found' in result.stdout and 'not found' not in result.stdout if name in ('activity', 'window') else True)
            except subprocess.TimeoutExpired:
                states[name] = False
        if states != previous or poll % 10 == 0:
            record(f'Emulator boot readiness poll {poll}: {states}')
            previous = states
        if all(states.values()):
            connected()
            record('PASS: emulator boot, package/activity/window services, shared storage and adb ready')
            return
        time.sleep(1)
    raise RuntimeError('Emulator readiness failed within 120 seconds; smoke was not started')


def controls():
    assert transport_error('adb: device offline')
    assert transport_error('adb: error: closed')
    assert not transport_error('Error: Activity not started')
    assert not transport_error('FAIL: product assertion')
    assert not transport_error('Permission denied')
    print('PASS: only identified adb transport failures qualify for read-only retries')


if __name__ == '__main__':
    {'boot': boot, 'controls': controls}[sys.argv[1]]()
