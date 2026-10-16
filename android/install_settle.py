#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Observe installed package overlay processing.
import json
from pathlib import Path
import re
import subprocess
import time


DEADLINE = 120


def processed(snapshot, package, version, user):
    if any(snapshot[key]['status'] != 0 for key in ('list', 'overlays', 'package')):
        return None
    listing = snapshot['list']['output']
    # A successful target query is empty when no overlays target android.
    if listing.strip() and not re.search(r'^\s*android\s*$', listing, re.M):
        return None
    enabled = set(re.findall(r'^\s*\[x\]\s+(\S+)\s*$', listing, re.M))
    paths = {}
    for match in re.finditer(r'^\s*([^\s{}]+):' + re.escape(user) + r'\s+\{(.*?)^\s*\}',
                             snapshot['overlays']['output'], re.M | re.S):
        target = re.search(r'mTargetPackageName\.*:\s*(\S+)', match[2])
        path = re.search(r'mBaseCodePath\.*:\s*(/\S+)', match[2])
        if target and target[1] == 'android' and path:
            paths[match[1]] = path[1]
    if not enabled.issubset(paths):
        return None
    if not listing.strip() and paths:
        return None  # The two OMS reads disagree; do not accept state churn.
    dump = snapshot['package']['output']
    if ('Package [' + package + ']') not in dump or not re.search(r'\bversionCode=' + re.escape(version) + r'\b', dump):
        return None
    state = re.search(r'^\s*User ' + re.escape(user) + r':([^\n]*)(.*?)(?=^\s*User \d+:|\Z)', dump, re.M | re.S)
    if not state or 'installed=true' not in state[1]:
        return None
    block = re.search(r'^\s*overlay paths:\n((?:\s*/[^\n]+\n)+)', state[2], re.M)
    actual = set(block[1].split()) if block else set()
    expected = {paths[name] for name in enabled}
    if actual.intersection(paths.values()) != expected:
        return None
    return dict(enabled=sorted(enabled), expected_paths=sorted(expected), applied_paths=sorted(actual))


def sample(package, user, remaining):
    result = {}
    for name, args in (('list', ['cmd', 'overlay', 'list', '--user', user, 'android']),
                       ('overlays', ['cmd', 'overlay', 'dump', '--user', user]),
                       ('package', ['dumpsys', 'package', package])):
        try:
            completed = subprocess.run(['adb', 'shell', *args], capture_output=True, text=True,
                                       timeout=max(.01, min(5, remaining / 3)))
            result[name] = dict(status=completed.returncode, output=completed.stdout, error=completed.stderr)
        except subprocess.TimeoutExpired:
            result[name] = dict(status='timeout', output='', error='Install readiness sample timed out')
    return result


def wait(package, version, user, evidence, install, take_sample=sample, now=time.monotonic, pause=time.sleep,
         began=None):
    began = now() if began is None else began
    deadline = began + DEADLINE
    previous = None
    consecutive = 0
    count = 0
    outcome = 'DEADLINE_EXPIRED'
    journal = evidence / 'install-settle-outcomes.txt'
    number = len(journal.read_text().splitlines()) + 1 if journal.exists() else 1
    with (evidence / f'install-{number}-settle-samples.txt').open('w') as output:
        while now() < deadline:
            snapshot = take_sample(package, user, deadline - now())
            count += 1
            proof = processed(snapshot, package, version, user)
            consecutive = (consecutive + 1 if proof == previous else 1) if proof is not None else 0
            previous = proof
            snapshot.update(seconds=now() - began, processed=proof, consecutive=consecutive)
            output.write(json.dumps(snapshot) + '\n')
            output.flush()
            if consecutive >= 2 and now() < deadline:
                outcome = 'PROCESSED'
                break
            pause(max(0, min(1, deadline - now())))
    result = dict(install=number, apk=install, package=package, version=version, user=user,
                  outcome=outcome, seconds=now() - began, samples=count, deadline_seconds=DEADLINE,
                  proof=previous)
    with journal.open('a') as output:
        output.write(json.dumps(result) + '\n')
    print('INSTALL_SETTLE ' + json.dumps(result), flush=True)
    return result


def after_install(arguments, output, evidence):
    if 'Success' not in output:
        return  # Rejected installs do not replace installed package resources.
    began = time.monotonic()
    apk = Path(arguments[-1])
    import test_signing
    badging = subprocess.check_output([str(test_signing.tools() / 'aapt2'), 'dump', 'badging', str(apk)],
                                     text=True, timeout=15)
    identity = re.search(r"^package: name='([^']+)' versionCode='(\d+)'", badging, re.M)
    assert identity, 'Installed APK identity unavailable: ' + str(apk)
    user = subprocess.check_output(['adb', 'shell', 'am', 'get-current-user'], text=True, timeout=10).strip()
    assert user.isdigit(), user
    return wait(identity[1], identity[2], user, evidence, str(apk), began=began)


def controls():
    import contextlib
    import io
    import tempfile
    package = 'org.esdeplus.frontend'
    def snapshot(applied=True, path='/data/resource-cache/accent.frro'):
        return dict(list=dict(status=0, output='android\n[x] com.android.systemui:accent\n'),
                    overlays=dict(status=0, output='com.android.systemui:accent:0 {\n'
                        ' mTargetPackageName.....: android\n mBaseCodePath..........: ' + path + '\n}\n'),
                    package=dict(status=0, output='Package [' + package + ']\n versionCode=42\n'
                        ' User 0: installed=true\n' + ('  overlay paths:\n   ' + path + '\n' if applied else '')))
    def exercise(values):
        clock, calls = [0], [0]
        def take(*args):
            value = values[min(calls[0], len(values)-1)]
            calls[0] += 1
            return value
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            return wait(package, '42', '0', Path(directory), 'control.apk', take,
                        lambda: clock[0], lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert exercise([snapshot()])['seconds'] == 1
    # Unchanged pre-broadcast state is insufficient, however long it is stable.
    result = exercise([snapshot(False)] * 19 + [snapshot(), snapshot()])
    assert result['outcome'] == 'PROCESSED' and result['seconds'] == 20
    assert exercise([snapshot(False)])['outcome'] == 'DEADLINE_EXPIRED'
    assert exercise([snapshot(), snapshot(path='/new.frro'), snapshot(path='/new.frro')])['seconds'] == 2
    for key in ('list', 'overlays', 'package'):
        bad = snapshot()
        bad[key]['status'] = 1
        assert processed(bad, package, '42', '0') is None
    assert processed(snapshot(), package, '43', '0') is None
    assert processed(snapshot(), package, '42', '10') is None
    bad = snapshot(); bad['overlays']['output'] = ''
    assert processed(bad, package, '42', '0') is None
    stale = snapshot()
    stale['overlays']['output'] += ('com.android.systemui:old:0 {\n'
        ' mTargetPackageName.....: android\n mBaseCodePath..........: /old.frro\n}\n')
    stale['package']['output'] += '   /old.frro\n'
    assert processed(stale, package, '42', '0') is None
    none = snapshot(False); none['list']['output'] = 'android\n[ ] com.android.systemui:accent\n'
    assert processed(none, package, '42', '0') == dict(enabled=[], expected_paths=[], applied_paths=[])
    none['list']['output'] = ''; none['overlays']['output'] = ''
    assert processed(none, package, '42', '0') == dict(enabled=[], expected_paths=[], applied_paths=[])
    return ('PASS: install controls: stable-but-unprocessed package blocked; enabled overlay paths must be applied; '
            'replacement paths reset proof; wrong version/user, missing mapping and failed reads do not qualify; '
            'bounded deadline records expiry without failing.\n')
