#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Fresh-session evidence and read-only CI telemetry.
import argparse
from collections import Counter
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


# API 34 core telemetry (38841218615 attempts 1/2) ranged from 2.8–67.03%;
# both attempts reached <20%. Require that lower-pressure band, not boot's
# 34–59% samples. This is a readiness heuristic, not a product pass criterion.
# PSI avg10 is a percent: https://docs.kernel.org/accounting/psi.html
SETTLE_CPU_AVG10 = 20.0
SETTLE_DEADLINE = 120
SETTLE_SAMPLES = 3


def application_info(output):
    # resolve-activity (without --brief) dumps the component's ApplicationInfo,
    # including resourceDirs/overlayPaths/sharedLibraryFiles when non-null.
    # GET_SHARED_LIBRARY_FILES (0x400) requests the latter. No app is launched.
    info = output.partition('ApplicationInfo:')[2].strip()
    # Android 16 stamps each newly returned ApplicationInfo with its creation
    # uptime. That is query metadata, not package/overlay state. Keep the raw
    # sample but exclude only this field from the stability comparison.
    info = re.sub(r'(?m)^\s*createTimestamp=\d+\s*$', '', info).strip()
    return info if 'packageName=' in info and 'sourceDir=' in info else None


def settle_sample(app, remaining):
    result = dict(host_cpu_pressure=read('/proc/pressure/cpu'))
    for name, arguments in (
            ('overlays', ['cmd', 'overlay', 'list']),
            ('frontend', ['cmd', 'package', 'resolve-activity', '--query-flags', '1024',
                          '-n', app + '/org.esdeplus.frontend.MainActivity'])):
        try:
            completed = subprocess.run(['adb', 'shell', *arguments], capture_output=True,
                                       text=True, timeout=max(0.01, min(5, remaining / 2)))
            result[name] = dict(status=completed.returncode, output=completed.stdout,
                                error=completed.stderr)
        except subprocess.TimeoutExpired:
            result[name] = dict(status='timeout', output='', error='Settle sample timed out')
    return result


def settle_key(snapshot):
    overlay, frontend = snapshot['overlays'], snapshot['frontend']
    info = application_info(frontend['output'])
    if overlay['status'] != 0 or frontend['status'] != 0 or not overlay['output'].strip() or not info:
        return None
    return overlay['output'], info


def cpu_avg10(pressure):
    match = re.search(r'^some avg10=(\d+(?:\.\d+)?)\b', pressure, re.M)
    value = float(match[1]) if match else None
    return value if value is not None and 0 <= value <= 100 else None


def settle(app, evidence, take_sample=settle_sample, now=time.monotonic, pause=time.sleep):
    began = now()
    deadline = began + SETTLE_DEADLINE
    previous = None
    consecutive = 0
    count = 0
    outcome = 'DEADLINE_EXPIRED'
    with (evidence / 'session-settle-samples.txt').open('w') as output:
        while now() < deadline:
            snapshot = take_sample(app, deadline - now())
            count += 1
            current = settle_key(snapshot)
            cpu = cpu_avg10(snapshot['host_cpu_pressure'])
            eligible = current is not None and cpu is not None and cpu < SETTLE_CPU_AVG10
            consecutive = (consecutive + 1 if current == previous else 1) if eligible else 0
            previous = current
            snapshot.update(seconds=now() - began, cpu_some_avg10=cpu, consecutive=consecutive)
            output.write(json.dumps(snapshot) + '\n')
            output.flush()
            print('SETTLE_SAMPLE ' + json.dumps(dict(seconds=snapshot['seconds'],
                  cpu_some_avg10=cpu, consecutive=consecutive)), flush=True)
            if consecutive >= SETTLE_SAMPLES and now() < deadline:
                outcome = 'SETTLED'
                break
            pause(max(0, min(5, deadline - now())))
    result = dict(outcome=outcome, seconds=now() - began, samples=count,
                  deadline_seconds=SETTLE_DEADLINE, cpu_some_avg10_below=SETTLE_CPU_AVG10,
                  required_consecutive_samples=SETTLE_SAMPLES)
    (evidence / 'session-settle-summary.txt').write_text(json.dumps(result, indent=2) + '\n')
    print('SESSION_SETTLE ' + json.dumps(result), flush=True)
    # Deadline expiry or unavailable telemetry is evidence, never a session
    # failure or permission to replay a product action. The original suite runs.
    return result


def settle_controls():
    import contextlib
    import io
    import tempfile

    def snapshot(overlays='android\n[x] overlay\n', info='sourceDir=/data/app/base.apk', cpu='10.0', status=0):
        return dict(overlays=dict(status=status, output=overlays),
                    frontend=dict(status=0, output='ApplicationInfo:\n packageName=org.esdeplus.frontend\n ' + info),
                    host_cpu_pressure='some avg10=' + cpu + ' avg60=30.0 total=1\n')

    def exercise(samples):
        clock = [0]
        calls = [0]
        def take_sample(app, remaining):
            index = min(calls[0], len(samples) - 1)
            calls[0] += 1
            return dict(samples[index])
        def pause(seconds):
            clock[0] += seconds
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            result = settle('org.esdeplus.frontend', root, take_sample, lambda: clock[0], pause)
            assert json.loads((root / 'session-settle-summary.txt').read_text()) == result
            assert len((root / 'session-settle-samples.txt').read_text().splitlines()) == calls[0]
            return result

    assert exercise([snapshot()])['seconds'] == 10
    timestamps = [snapshot(info='sourceDir=/data/app/base.apk\n createTimestamp=' + str(t))
                  for t in (1000, 6000, 11000)]
    assert exercise(timestamps)['seconds'] == 10
    # Stable but busy/unknown samples must not qualify. Overlay or ApplicationInfo
    # churn resets the consecutive count even when CPU pressure is already low.
    for changed in (snapshot(overlays='android\n[ ] overlay\n'),
                    snapshot(info='sourceDir=/data/app/new.apk'),
                    snapshot(info='sourceDir=/data/app/base.apk\n overlayPaths=[changed.frro]'),
                    snapshot(cpu='66.48'), snapshot(cpu='20.0'), snapshot(cpu='unavailable'),
                    snapshot(status=1), snapshot(info='No activity found')):
        result = exercise([snapshot(), changed, snapshot(), snapshot(), snapshot()])
        assert result['outcome'] == 'SETTLED' and result['seconds'] == 20, result
    for unavailable in (snapshot(cpu='66.48'), snapshot(status='timeout'), snapshot(info='')):
        result = exercise([unavailable])
        assert result['outcome'] == 'DEADLINE_EXPIRED' and result['seconds'] == SETTLE_DEADLINE, result
    assert cpu_avg10('full avg10=0.00') is None
    assert cpu_avg10('some avg10=100.1') is None
    return ('PASS: settle controls: stable/low pressure qualifies; overlay/ApplicationInfo churn, high/boundary/missing '
            'CPU and failed reads delay readiness; bounded deadline returns without failing the session.\n')


def command_kind(args):
    text = ' '.join(args)
    return next((name for name in ('screencap', 'uiautomator', 'dumpsys', 'logcat', 'instrument')
                 if name in text), 'other')


def record_command(args, seconds, status):
    path = os.environ.get('ESDE_SMOKE_COMMAND_METRICS')
    if path:
        with open(path, 'a') as output:
            output.write(json.dumps(dict(kind=command_kind(args), seconds=seconds, status=status)) + '\n')


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return ''


def sample():
    # Never drive UI or replay an action for diagnostics. Missing/failed samples
    # are recorded independently of the child's unchanged exit status.
    qemu = []
    for entry in Path('/proc').glob('[0-9]*'):
        name = read(entry / 'comm').strip()
        if 'qemu' not in name:
            continue
        status = read(entry / 'status')
        stat = read(entry / 'stat').rsplit(')', 1)[-1].split()
        qemu.append(dict(pid=entry.name, name=name,
                         status=[x for x in status.splitlines() if x.startswith(('VmRSS:', 'Threads:'))],
                         cpu_ticks=stat[11:13]))
    result = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  host_meminfo=read('/proc/meminfo'), host_cpu=read('/proc/stat').splitlines()[:1],
                  host_vmstat=[x for x in read('/proc/vmstat').splitlines()
                               if x.split()[0] in ('oom_kill', 'pswpin', 'pswpout', 'pgmajfault')],
                  pressure={x: read('/proc/pressure/' + x) for x in ('cpu', 'memory', 'io')},
                  qemu=qemu)
    try:
        guest = subprocess.run(['adb', 'shell', 'cat /proc/meminfo /proc/stat'],
                               capture_output=True, text=True, timeout=5)
        result['guest'] = dict(status=guest.returncode, output=guest.stdout, error=guest.stderr)
    except subprocess.TimeoutExpired:
        result['guest'] = dict(error='read-only resource sample timed out after 5 seconds')
    return result


def run_child(command, env, observe):
    child = subprocess.Popen(command, env=env)
    try:
        while True:
            observe()
            try:
                return child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


def boot_identity():
    result = subprocess.run(['adb', 'shell', 'cat', '/proc/sys/kernel/random/boot_id'],
                            capture_output=True, text=True, timeout=15, check=True)
    identity = result.stdout.strip()
    assert len(identity) == 36, ('Missing live guest boot identity', identity)
    return identity


def summary(snapshots, commands, elapsed, status):
    rss = []
    available = []
    costs = {}
    for snapshot in snapshots:
        rss.append(sum(int(line.split()[1]) for process in snapshot['qemu']
                       for line in process['status'] if line.startswith('VmRSS:')))
        available.extend(int(line.split()[1]) for line in snapshot['host_meminfo'].splitlines()
                         if line.startswith('MemAvailable:'))
    for command in commands:
        cost = costs.setdefault(command['kind'], dict(count=0, seconds=0, timeouts=0))
        cost['count'] += 1
        cost['seconds'] += command['seconds']
        cost['timeouts'] += command['status'] == 'timeout'
    return dict(seconds=elapsed, child_status=status, samples=len(snapshots),
                peak_qemu_rss_kib=max(rss, default=0),
                minimum_host_available_kib=min(available, default=None), commands=costs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('core', 'touch', 'lifecycle', 'integration',
                                         'pdf-direct', 'pdf-scoped', 'self-test'))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.phase == 'self-test':
        import fresh_session_checks
        controls = fresh_session_checks.controls() + settle_controls()
        root = Path('android/evidence')
        root.mkdir(parents=True, exist_ok=True)
        (root / 'fresh-session-controls.txt').write_text(controls)
        print(controls, end='')
        for status in (0, 7):
            assert run_child([sys.executable, '-c', f'raise SystemExit({status})'],
                             dict(os.environ), lambda: None) == status
        assert command_kind(('exec-out', 'screencap', '-p')) == 'screencap'
        assert command_kind(('shell', 'uiautomator dump /tmp/ui.xml')) == 'uiautomator'
        measured = summary([
            dict(qemu=[dict(status=['VmRSS: 40 kB']), dict(status=['VmRSS: 60 kB'])],
                 host_meminfo='MemAvailable: 500 kB\n'),
            dict(qemu=[dict(status=['VmRSS: 80 kB'])], host_meminfo='MemAvailable: 300 kB\n')],
            [dict(kind='logcat', seconds=2, status=0), dict(kind='logcat', seconds=3, status='timeout')], 9, 7)
        assert measured['peak_qemu_rss_kib'] == 100 and measured['minimum_host_available_kib'] == 300
        assert measured['commands']['logcat'] == dict(count=2, seconds=5, timeouts=1)
        assert measured['child_status'] == 7 and measured['seconds'] == 9
        print('PASS: child failures propagate unchanged; command cost classification')
        return 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    assert command, 'A smoke command is required'
    root = Path('android/evidence')
    root.mkdir(parents=True, exist_ok=True)
    identity = boot_identity()
    for previous in root.glob('*-session-boot-id.txt'):
        assert identity != previous.read_text().strip(), 'Reused emulator across smoke sessions'
    app = next(x.split('=', 1)[1] for x in Path('android/gradle.properties').read_text().splitlines()
               if x.startswith('esde.applicationId='))
    installed = subprocess.run(['adb', 'shell', 'pm', 'list', 'packages', app], capture_output=True,
                               text=True, timeout=15, check=True)
    assert 'package:' + app not in installed.stdout.splitlines(), 'Each session must start with clean emulator app data'
    (root / (args.phase + '-session-boot-id.txt')).write_text(identity + '\n')
    env = dict(os.environ)
    env['ESDE_SMOKE_COMMAND_METRICS'] = str(root / (args.phase + '-command-costs.txt'))
    Path(env['ESDE_SMOKE_COMMAND_METRICS']).write_text('')
    if args.phase != 'core':
        env['ESDE_SMOKE_EVIDENCE'] = str(root / args.phase)
    health = root / (args.phase + '-session-health.txt')
    began = time.monotonic()
    with health.open('w') as output:
        def observe():
            snapshot = sample()
            output.write(json.dumps(snapshot) + '\n')
            output.flush()
            available = next((x for x in snapshot['host_meminfo'].splitlines()
                              if x.startswith('MemAvailable:')), 'MemAvailable: unavailable')
            costs = Path(env['ESDE_SMOKE_COMMAND_METRICS'])
            counts = Counter()
            if costs.exists():
                for line in costs.read_text().splitlines(keepends=True):
                    if line.endswith('\n'):
                        counts[json.loads(line)['kind']] += 1
            # Keep a compact sample in the job log even if the runner dies before
            # its final artifact upload. Full counters remain in the text artifact.
            print('HEALTH ' + json.dumps(dict(phase=args.phase, utc=snapshot['utc'],
                  memory=available, qemu=snapshot['qemu'], commands=counts,
                  pressure=snapshot['pressure'], vmstat=snapshot['host_vmstat'])), flush=True)
        print(f'SESSION {args.phase}: fresh guest {identity}; UTC telemetry every 30 seconds', flush=True)
        # Keep a continuous copy even when an older suite clears its own
        # assertion buffer. Start before installation/settling; never clear it.
        with (root / (args.phase + '-session-logcat.txt')).open('w') as session_log:
            follower = subprocess.Popen(['adb', 'logcat', '-b', 'all', '-v', 'threadtime'],
                                        stdout=session_log, stderr=subprocess.STDOUT)
            try:
                status = run_child(command, env, observe)
            finally:
                streaming = follower.poll() is None
                if streaming:
                    follower.terminate()
                follower.wait(timeout=5)
                (root / (args.phase + '-session-logcat-status.txt')).write_text(
                    json.dumps(dict(streaming_until_child_exit=streaming, status=follower.returncode)) + '\n')
        observe()
        records = lambda path: [json.loads(line) for line in path.read_text().splitlines(keepends=True)
                                if line.endswith('\n')]
        measured = summary(records(health), records(Path(env['ESDE_SMOKE_COMMAND_METRICS'])),
                           time.monotonic() - began, status)
        settle_record = Path(env.get('ESDE_SMOKE_EVIDENCE', str(root))) / 'session-settle-summary.txt'
        measured['settle'] = json.loads(settle_record.read_text()) if settle_record.exists() else None
        startup_record = settle_record.parent / 'startup-outcomes.txt'
        measured['stock_onboarding_relaunches'] = sum(
            row['outcome'] == 'RELAUNCH_STOCK_ONBOARDING'
            for row in records(startup_record)) if startup_record.exists() else 0
        (root / (args.phase + '-session-summary.txt')).write_text(json.dumps(measured, indent=2) + '\n')
        print('SESSION_SUMMARY ' + json.dumps(dict(phase=args.phase, **measured)), flush=True)
        print(f'SESSION {args.phase}: child exit status {status}', flush=True)
        return status


if __name__ == '__main__':
    sys.exit(main())
