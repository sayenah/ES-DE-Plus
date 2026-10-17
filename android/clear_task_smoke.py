#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. G-32 real task-clear positive control and regression probe.
import os
import re
import shlex
import subprocess
import time


def pid_lines(logs, pid):
    return '\n'.join(line for line in logs.splitlines() if re.match(
        r'^\d\d-\d\d\s+\d\d:\d\d:\d\d\.\d+\s+' + re.escape(pid) + r'\s+\d+\s+[VDIWEF]\s', line))


def completed(logs, old, new, helper_required=True):
    before = pid_lines(logs, old)
    after = pid_lines(logs, new)
    assert old != new and old.isdigit() and new.isdigit(), 'No distinct new frontend PID'
    for token in ('Finished main function', 'SDL activity destroy join returned', 'VM exiting with result code 0'):
        assert token in before, 'Old PID missing ' + token
    assert before.count('Running main function') == 1, 'Old PID native-main count'
    assert after.count('Running main function') == 1, 'New PID native-main count'
    assert logs.count('Running main function') == 2, 'Unexpected native main in another process'
    sequence = ['Finished main function', 'SDL activity destroy join returned', 'VM exiting with result code 0']
    helper = f'SDL process {old} retired; restarting entry'
    if helper_required or 'Clear-task entry retiring SDL session' in before:
        assert 'Clear-task entry retiring SDL session' in before, 'No explicit clear-task retirement'
        assert helper in logs, 'Helper did not observe retirement'
        sequence.append(helper)
    offsets = [logs.index(token) for token in sequence]
    assert offsets == sorted(offsets), 'Retirement chain out of order'
    new_main = next(line for line in after.splitlines() if 'Running main function' in line)
    assert offsets[-1] < logs.index(new_main), 'New native main preceded retirement'
    assert 'Focused redirect forwarding entry' not in logs, 'Clear entry used the live-session forwarding path'
    assert 'ANR in ' not in logs and 'JNI DETECTED ERROR' not in logs and 'Fatal signal' not in logs, 'Runtime failure'


def controls():
    old = ('Running main function', 'Clear-task entry retiring SDL session', 'Finished main function',
           'SDL activity destroy join returned', 'VM exiting with result code 0')
    logs = ''.join(f'01-01 00:00:00.000 123 123 I SDL: {token}\n' for token in old)
    logs += ('01-01 00:00:00.001 456 456 I ES-DE-Plus: SDL process 123 retired; restarting entry\n'
             '01-01 00:00:00.002 789 790 I SDL: Running main function\n')
    completed(logs, '123', '789')
    natural = '\n'.join(line for line in logs.splitlines() if
                        'Clear-task entry retiring' not in line and 'SDL process 123 retired;' not in line)
    completed(natural, '123', '789', helper_required=False)
    mutants = [logs.replace(token, 'absent') for token in old[1:]]
    mutants += [logs.replace('SDL process 123', 'SDL process 999'),
                logs + '01-01 00:00:00.003 789 790 I SDL: Running main function\n',
                logs.replace(' 123 ', ' 999 '),
                logs + 'Focused redirect forwarding entry\n', logs + 'ANR in frontend\n',
                logs + '01-01 00:00:00.004 999 999 I SDL: Running main function\n']
    assert not pid_lines('01-01 00:00:00.000 456 456 I SDL: original PID 123 Running main function', '123')
    for mutant in mutants:
        try:
            completed(mutant, '123', '789')
        except AssertionError:
            pass
        else:
            raise AssertionError('Broken clear-task chain escaped')
    return f'PASS: {len(mutants)} broken clear-task chains rejected\n'


def run(harness):
    h = type('Harness', (), harness)
    baseline = os.environ.get('ESDE_CLEAR_TASK_UNFIXED') == 'true'
    outcomes = []
    (h.evidence / 'clear-task-chain-controls.txt').write_text(controls())

    def capture(name):
        h.save_logs(name)
        (h.evidence / (name + '-activities.txt')).write_text(h.activity_records()[0])
        (h.evidence / (name + '-window.txt')).write_text(h.focused_window())
        (h.evidence / (name + '-events.txt')).write_text(h.adb('logcat', '-d', '-b', 'events', '-v', 'threadtime'))

    # Exercise each public entry alias and cross-entry task selection. Include
    # ordinary uninstrumented launches; only scheduling cases widen idle.
    count = 1 if baseline else 24
    for cycle in range(count):
        source = ('MainActivity', 'HomeEntry', 'LeanbackEntry')[cycle % 3]
        target = ('MainActivity', 'HomeEntry', 'LeanbackEntry')[(cycle // 3) % 3]
        scheduled = baseline or cycle < 20
        name = f'clear-task-{cycle + 1:02d}-{source}-{target}'
        process = None
        h.shell('am', 'force-stop', h.app)
        h.adb('logcat', '-c')
        try:
            harness['startup_baseline'] = h.log()
            if scheduled:
                # --no-restart avoids instrumentation cleanup force-stopping
                # the surviving private helper when the old frontend exits.
                h.shell('am', 'start', '-W', '-n',
                        h.app + '/org.esdeplus.frontend.ForcedRelaunchBootstrapActivity')
                output = (h.evidence / (name + '-instrumentation.txt')).open('w')
                process = subprocess.Popen(['adb', 'shell', shlex.join([
                    'am', 'instrument', '--no-restart', '-w', '-e', 'entry', source,
                    'org.esdeplus.stub/.ClearTaskProbe'])], stdout=output, stderr=subprocess.STDOUT)
                output.close()
            else:
                category = {'MainActivity': 'LAUNCHER', 'HomeEntry': 'HOME', 'LeanbackEntry': 'LEANBACK_LAUNCHER'}[source]
                h.start_entry(source, 'android.intent.category.' + category)
            h.configured_system(name + '-before')
            old = h.shell('pidof', h.app).strip()
            assert old.isdigit(), old
            capture(name + '-before-clear')
            previous = h.log()
            category = {'MainActivity': 'LAUNCHER', 'HomeEntry': 'HOME', 'LeanbackEntry': 'LEANBACK_LAUNCHER'}[target]
            # Issue this action once. Never relaunch/retry to obtain readiness.
            result = h.shell('am', 'start', '-f', '0x10008000', '-a', 'android.intent.action.MAIN',
                             '-c', 'android.intent.category.' + category,
                             '-n', h.app + '/org.esdeplus.frontend.' + target)
            (h.evidence / (name + '-action.txt')).write_text(result)
            if baseline:
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    time.sleep(0.25)
                logs = h.adb('logcat', '-d', '-v', 'threadtime')
                capture(name + '-positive-control')  # Before any cleanup.
                before = pid_lines(logs, old)
                assert 'Clear-task replacement idle barrier armed' in before, 'Scheduling seam not reached'
                assert 'Clear-task replacement draw barrier armed' in before, 'Drawing seam not reached'
                assert h.shell('pidof', h.app, check=False).strip() == old, 'Unfixed host did not reproduce G-32'
                assert before.count('Focused redirect forwarding entry') >= 3, 'No redirect loop'
                assert 'flg=0x10100000' in logs, 'No task-history replay'
                assert all(token not in before for token in ('Destroying SDL activity', 'Finished main function',
                           'SDL activity destroy join returned')), 'Positive control retired the old session'
                outcomes.append('PASS: unfixed G-32 reproduced; old PID alive, history redirects, no destruction/return/join')
            else:
                h.wait_for(lambda: old not in h.shell('pidof', h.app, check=False).split(),
                           name + ' original PID retired', timeout=10)
                h.wait_for(lambda: h.native_shutdown(old), name + ' native return/join/exit', timeout=10)
                h.wait_for(lambda: h.shell('pidof', h.app, check=False).strip().isdigit() and
                           h.log().splitlines()[:1] != previous.splitlines()[:1] and
                           'Application startup time:' in h.log() and
                           h.smoke_checks.package_window_focused(h.focused_window(), h.app),
                           name + ' automatic new frontend', timeout=90)
                new = h.shell('pidof', h.app).strip()
                logs = h.adb('logcat', '-d', '-v', 'threadtime')
                completed(logs, old, new, helper_required=scheduled)
                if scheduled:
                    assert 'Clear-task replacement idle barrier armed' in pid_lines(logs, old), 'Scheduling seam not reached'
                    assert 'Clear-task replacement draw barrier armed' in pid_lines(logs, old), 'Drawing seam not reached'
                h.wait_for(lambda: len(h.activity_records()[1]) == 1,
                           name + ' helper and old entry records removed', timeout=10)
                assert len(h.activity_records()[1]) == 1, 'Entry left duplicate frontend records'
                expected = 'HOME=true' if target == 'HomeEntry' else 'HOME=false'
                assert expected in pid_lines(logs, new), 'Restart lost entry semantics'
                capture(name + '-after')
                outcomes.append(f'PASS: {name} old={old} new={new} scheduled={scheduled}; native return/join/exit, one new main')
            (h.evidence / (name + '-result.txt')).write_text(outcomes[-1] + '\n')
        except Exception:
            capture(name + '-failure')
            h.screenshot(name + '-failure')
            raise
        finally:
            h.shell('am', 'force-stop', h.app)
            if process is not None:
                process.wait(timeout=15)
    (h.evidence / 'clear-task-summary.txt').write_text('\n'.join(outcomes) + '\n')


if __name__ == '__main__':
    print(controls(), end='')
