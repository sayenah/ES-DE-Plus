#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Fresh-session evidence and read-only CI telemetry.
import argparse
from collections import Counter
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time


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
                                         'pdf-direct', 'pdf-scoped', 'assets', 'clear-task', 'self-test'))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.phase == 'self-test':
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
        status = run_child(command, env, observe)
        observe()
        records = lambda path: [json.loads(line) for line in path.read_text().splitlines(keepends=True)
                                if line.endswith('\n')]
        measured = summary(records(health), records(Path(env['ESDE_SMOKE_COMMAND_METRICS'])),
                           time.monotonic() - began, status)
        (root / (args.phase + '-session-summary.txt')).write_text(json.dumps(measured, indent=2) + '\n')
        print('SESSION_SUMMARY ' + json.dumps(dict(phase=args.phase, **measured)), flush=True)
        print(f'SESSION {args.phase}: child exit status {status}', flush=True)
        return status


if __name__ == '__main__':
    sys.exit(main())
