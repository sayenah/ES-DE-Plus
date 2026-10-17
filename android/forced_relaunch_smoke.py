#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real ASSETS_PATHS relaunches; no startup recovery.
import os
import hashlib
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time
import sys


def frontend_stopped(dump, record):
    sections = re.split(r'\n\s*\*\s+Hist\s+#\d+:', dump)
    # The previous task can mention this same record in mLastPausedActivity.
    # Only the matching Hist header owns the state we are checking.
    return any(section.lstrip().startswith('ActivityRecord{' + record + '}') and
               re.search(r'\bstate=STOPPED\b', section) for section in sections[1:])


def configurator_focused(window, app):
    focus = next((line for line in window.splitlines() if 'mCurrentFocus=' in line), '')
    return bool(re.search(r'\s' + re.escape(app) + r'/(?:\.|' + re.escape(app) +
                          r'\.)ConfiguratorActivity[\s}]', focus))


def destruction_evidence(logs, old):
    # Bind the PID column of logcat threadtime, never a TID or a payload number.
    prefix = r'^\S+\s+\S+\s+' + re.escape(old) + r'\s+\d+\s+[VDIWEF]\s'
    old_lines = '\n'.join(line for line in logs.splitlines() if re.match(prefix, line))
    destruction = next((line for line in old_lines.splitlines() if 'Destroying SDL activity' in line), '')
    assert 'held=false' in destruction, 'Held-host outcome is not G-30: ' + destruction
    assert 'changingConfigurations=true' in destruction and 'finishing=false' in destruction, destruction
    assert 'configurationChanges=0x-80000000' in destruction, 'Not ASSETS_PATHS-only: ' + destruction
    assert old_lines.count('Running main function') == 1, 'Second/missing native main in old VM'
    return old_lines


def restoration_evidence(logs, old):
    old_lines = destruction_evidence(logs, old)
    decisions = [line for line in old_lines.splitlines() if 'Frontend restart decision ' in line]
    assert len(decisions) == 1, ('Expected one decision', decisions)
    decision_line = decisions[0]
    assert 'requested=true configured=true helperStarted=false' in decision_line, decision_line
    assert 'Frontend restart helper started configured=true' in old_lines, old_lines
    decision = logs.find(decision_line) if decision_line else -1
    helper = re.search(r'START .*FrontendRestartActivity', logs)
    retirement = logs.find(f'SDL process {old} retired; restarting entry')
    assert decision >= 0 and helper and retirement >= 0, 'Missing decision, helper START or observed old-process retirement'
    assert decision < helper.start() < retirement, 'Restore chain is out of order'
    if 'Frontend restart deferred until committed entry' in old_lines:
        committed_line = next((line for line in old_lines.splitlines() if
                               'Frontend entry committed resumed=true focused=true' in line), '')
        assert committed_line and logs.find(committed_line) < decision, 'Deferred restore lacks committed entry'


def controls():
    for component in ('.ConfiguratorActivity', 'smoke.app.ConfiguratorActivity'):
        assert configurator_focused('mCurrentFocus=Window{1 u0 smoke.app/' + component + '}', 'smoke.app')
    for component in ('.MainActivity', '.ConfiguratorActivityExtra'):
        assert not configurator_focused('mCurrentFocus=Window{1 u0 smoke.app/' + component +
                                        '}\nmFocusedApp=smoke.app/.ConfiguratorActivity', 'smoke.app')
    logs = ('01-01 00:00:00.000 123 124 V SDL: Running main function\n'
            '01-01 00:00:00.001 123 123 I ES-DE-Plus: Destroying SDL activity held=false finishing=false changingConfigurations=true '
            'configurationChanges=0x-80000000\n'
            '01-01 00:00:00.002 123 123 I ES-DE-Plus: Frontend restart decision requested=true configured=true helperStarted=false\n'
            '01-01 00:00:00.003 456 456 I ActivityTaskManager: START cmp=FrontendRestartActivity\n'
            '01-01 00:00:00.004 123 123 I ES-DE-Plus: Frontend restart helper started configured=true\n'
            '01-01 00:00:00.005 789 789 I ES-DE-Plus: SDL process 123 retired; restarting entry\n')
    restoration_evidence(logs, '123')
    mutants = [logs.replace(token, replacement) for token, replacement in (
        ('requested=true', 'requested=false'), ('configured=true', 'configured=false'),
        ('helperStarted=false', 'helperStarted=true'), ('START', 'NOT_STARTED'),
        ('SDL process 123 retired;', 'SDL process 999 retired;'),
        ('configurationChanges=0x-80000000', 'configurationChanges=0x10000000'),
        ('finishing=false', 'finishing=true'), ('changingConfigurations=true', 'changingConfigurations=false'))]
    mutants.append(logs.replace('held=false', 'held=true'))
    mutants += [logs + '01-01 00:00:00.006 123 124 V SDL: Running main function\n',
                logs.replace(' 123 ', ' 999 '),
                logs.replace('123 123 I ES-DE-Plus: Destroying', '999 123 I ES-DE-Plus: Destroying')]
    lines = logs.splitlines(keepends=True)
    mutants.append(logs + lines[2])
    mutants.append(logs.replace('Frontend restart helper started configured=true', 'Frontend restart helper not started'))
    mutants += [''.join(lines[:2] + [lines[3], lines[2]] + lines[4:]),
                ''.join(lines[:3] + [lines[5], lines[3], lines[4]])]
    deferred = logs.replace(lines[2],
        '01-01 00:00:00.002 123 123 I ES-DE-Plus: Frontend restart deferred until committed entry\n'
        '01-01 00:00:00.002 123 123 I ES-DE-Plus: Frontend entry committed resumed=true focused=true\n' + lines[2])
    restoration_evidence(deferred, '123')
    mutants += [deferred.replace('resumed=true', 'resumed=false'), deferred.replace('focused=true', 'focused=false'),
                deferred.replace('Frontend entry committed', 'No committed entry')]
    for mutant in mutants:
        try:
            restoration_evidence(mutant, '123')
        except AssertionError:
            pass
        else:
            raise AssertionError('Incomplete/mismatched restore chain escaped')
    dump = ('mLastPausedActivity: ActivityRecord{frontend}\n'
            ' * Hist #0: ActivityRecord{game}\n state=RESUMED\n'
            ' mLastPausedActivity: ActivityRecord{frontend}\n'
            ' * Hist #0: ActivityRecord{frontend}\n state=STOPPED\n')
    assert frontend_stopped(dump, 'frontend')
    assert not frontend_stopped(dump.replace('state=STOPPED', 'state=RESUMED'), 'frontend')
    assert not frontend_stopped(dump, 'game')
    return (f'PASS: {len(mutants)} broken restore chains rejected; matching Hist state checked; '
            'no recovery or action retry\n')


def run(harness):
    h = type('Harness', (), harness)
    baseline = os.environ.get('ESDE_ASSETS_UNFIXED') == 'true'
    overlay = 'org.esdeplus.relaunchprobe'
    failures = []
    outcomes = []
    (h.evidence / 'assets-chain-controls.txt').write_text(controls())
    source = Path(__file__).resolve().parent / 'app/src/main/kotlin/org/esdeplus/frontend/MainActivity.kt'
    (h.evidence / 'assets-host-source.txt').write_text('Build source: ' + os.environ.get('GITHUB_SHA', 'local') +
        '\nMainActivity SHA-256: ' + hashlib.sha256(source.read_bytes()).hexdigest() + '\n')

    def capture(name):
        h.save_logs(name)
        (h.evidence / (name + '-activities.txt')).write_text(h.activity_records()[0])
        (h.evidence / (name + '-window.txt')).write_text(h.focused_window())

    # The debug-only target's public policy allows shell to toggle this test
    # RRO on production TV images too. It changes only the frontend's asset
    # paths, leaving the game and system palette untouched. No root is used.
    assert h.shell('id', '-u').strip() == '2000', 'Probe requires ordinary shell'
    (h.evidence / 'assets-overlay-installed.txt').write_text(h.shell('cmd', 'overlay', 'dump', overlay))

    for mode in ('game', 'configurator', 'copy', 'steady'):
        name = 'assets-' + mode
        process = None
        monitor = None
        stop_sampling = threading.Event()
        focus_samples = []
        focus_errors = []
        h.shell('am', 'force-stop', h.app)
        h.shell('am', 'force-stop', 'org.esdeplus.stub')
        h.shell('cmd', 'overlay', 'disable', overlay)
        h.shell('rm', '-f', '/data/local/tmp/esde-assets-configurator')
        h.adb('logcat', '-c')
        try:
            if mode in ('copy', 'configurator'):
                # AOSP's ordinary instrumentation cleanup force-stops the
                # whole package when the parent dies, removing the helper.
                # Attach without restart to a Java-only VM instead. The debug
                # bootstrap requires shell's DUMP permission; game cases remain
                # uninstrumented and receive no background-start grant.
                h.shell('am', 'start', '-W', '-n',
                            h.app + '/org.esdeplus.frontend.ForcedRelaunchBootstrapActivity')
                assert 'Running main function' not in h.adb('logcat', '-d'), 'Bootstrap started native main'
                output = (h.evidence / (name + '-instrumentation.txt')).open('w')
                process = subprocess.Popen(['adb', 'shell', shlex.join([
                    'am', 'instrument', '--no-restart', '-w', '-e', 'mode', mode,
                    'org.esdeplus.stub/.ForcedRelaunchProbe'])], stdout=output, stderr=subprocess.STDOUT)
                output.close()
            else:
                h.start_entry()
            if mode == 'copy':
                h.wait_for(lambda: 'ASSETS copy barrier entered' in h.adb('logcat', '-d'),
                           name + ' real setupResources barrier', timeout=45)
            else:
                h.configured_system(name + '-before')
            old = h.shell('pidof', h.app).strip()
            assert old.isdigit(), old
            before = h.log()
            dump, records = h.activity_records()
            frontend = [r for r in records if r[0] == 'MainActivity']
            assert len(frontend) == 1, dump
            task = frontend[0][1]
            if mode == 'game':
                h.shell('am', 'start', '-n', 'org.esdeplus.stub/.RecipientActivity')
            elif mode == 'configurator':
                h.shell('touch', '/data/local/tmp/esde-assets-configurator')
                h.wait_for(lambda: configurator_focused(h.focused_window(), h.app),
                           name + ' configurator focused', timeout=30)
                # Data-folder disclosure makes Save scroll below the viewport.
                # Reach it using real D-pad navigation, without activating it.
                h.ui('Save and start frontend', dpad=True, focus_only=True)
            if mode in ('game', 'configurator'):
                h.wait_for(lambda: frontend_stopped(h.activity_records()[0], frontend[0][2]),
                           name + ' frontend STOPPED', timeout=30)
            capture(name + '-before-overlay')

            def game_focus():
                window = h.focused_window()
                focus_samples.append(f'{time.monotonic():.3f}: {window}')
                assert h.smoke_checks.package_window_focused(window, 'org.esdeplus.stub'), window
            if mode == 'game':
                game_focus()
                def sample_focus():
                    try:
                        while not stop_sampling.is_set():
                            game_focus()
                            stop_sampling.wait(0.25)
                    except Exception as error:
                        focus_errors.append(str(error))
                monitor = threading.Thread(target=sample_focus)
                monitor.start()
            # Focus sampling spans delivery; no adbd restart interrupts it.
            h.shell('cmd', 'overlay', 'enable', overlay)
            (h.evidence / (name + '-overlay.txt')).write_text(h.shell('cmd', 'overlay', 'dump', overlay))
            if mode in ('game', 'configurator'):
                # A background resource update must remain deferred. Observe
                # five seconds beyond delivery, as in PR #11's N-1 controls.
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    if mode == 'game':
                        game_focus()
                    assert h.shell('pidof', h.app).strip() == old, 'Stopped frontend retired before user return'
                    assert 'Destroying SDL activity' not in h.adb('logcat', '-d'), 'Invisible ASSETS relaunch'
                    time.sleep(0.25)
                capture(name + '-background-negative')
                stop_sampling.set()
                if monitor is not None:
                    monitor.join(timeout=30)
                    assert not monitor.is_alive(), 'Focus sampler stuck'
                    assert not focus_errors, focus_errors
                (h.evidence / (name + '-recipient-focus.txt')).write_text('\n'.join(focus_samples) + '\n')
                if mode == 'game':
                    h.key('KEYCODE_BACK')  # User returns to the existing task, no app launch retry.
                else:
                    h.ui('Save and start frontend', dpad=True)

            h.wait_for(lambda: 'Destroying SDL activity' in h.adb('logcat', '-d'),
                       name + ' forced destroy', timeout=30)
            h.wait_for(lambda: old not in h.shell('pidof', h.app, check=False).split(),
                       name + ' old PID retired', timeout=10)
            logs = h.adb('logcat', '-d', '-v', 'threadtime')
            destruction_evidence(logs, old)
            if mode == 'copy':
                assert 'Resource copy cancelled for destruction; files closed; repair marker absent' in logs, \
                    'Probe did not cancel an actual resource copy'
            if baseline:
                # These are separate positive controls, never an expected-fail
                # path in the candidate gate. Record races that happen to pass.
                helper = f'SDL process {old} retired; restarting entry'
                until = time.monotonic() + 10
                while helper not in h.adb('logcat', '-d') and time.monotonic() < until:
                    time.sleep(0.25)
                restored = helper in h.adb('logcat', '-d')
                if mode in ('game', 'configurator', 'copy'):
                    assert not restored, 'Unfixed positive control unexpectedly restored stopped host'
                if mode == 'copy':
                    assert 'ASSETS actual SDL finish followed the destruction snapshot' in logs, 'Copy race seam not reached'
                if not restored:
                    logs = h.adb('logcat', '-d')
                    assert not re.search(r'START .*FrontendRestartActivity', logs), 'Helper started but did not restore'
                    assert not h.shell('pidof', h.app + ':lifecycle', check=False).strip(), 'Helper still running'
                outcomes.append(f'{mode}: ' + ('race did not reproduce' if restored else 'G-30 reproduced; no helper restoration'))
            else:
                h.wait_for(lambda: f'SDL process {old} retired; restarting entry' in h.adb('logcat', '-d'),
                           name + ' helper restoration', timeout=15)
                logs = h.adb('logcat', '-d', '-v', 'threadtime')
                restoration_evidence(logs, old)
                h.wait_for(lambda: h.shell('pidof', h.app, check=False).strip().isdigit() and
                           h.shell('pidof', h.app).strip() != old and
                           h.log().splitlines()[:1] != before.splitlines()[:1] and
                           'Application startup time:' in h.log(),
                           name + ' new PID ready', timeout=90)
                h.configured_system(name + '-restored')
                dump, records = h.activity_records()
                assert len(records) == 1 and records[0][1] == task, ('Task changed', task, dump)
                outcomes.append(f'{mode}: PASS old={old} new={h.shell("pidof", h.app).strip()} task={task}')
            capture(name + '-result')
        except Exception as error:
            capture(name + '-failure')
            try:
                h.screenshot(name + '-failure')
            except Exception as diagnostic:
                (h.evidence / (name + '-failure-screenshot-error.txt')).write_text(str(diagnostic))
            try:
                h.hierarchy()
                (h.evidence / (name + '-failure-ui.txt')).write_bytes(
                    (h.evidence / 'latest-ui.txt').read_bytes())
            except Exception as diagnostic:
                (h.evidence / (name + '-failure-ui-error.txt')).write_text(str(diagnostic))
            failures.append(name + ': ' + str(error))
        finally:
            stop_sampling.set()
            if monitor is not None:
                monitor.join(timeout=30)
                (h.evidence / (name + '-recipient-focus.txt')).write_text('\n'.join(focus_samples) + '\n')
            h.shell('am', 'force-stop', h.app)
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
    if not baseline:
        try:
            import predictive_back_smoke
            outcomes.append(predictive_back_smoke.run(harness))
        except Exception as error:
            failures.append('assets-back-cancel: ' + str(error))
    (h.evidence / 'assets-summary.txt').write_text('\n'.join(outcomes + failures) + '\n')
    assert not failures, '\n'.join(failures)


if __name__ == '__main__':
    assert sys.argv[1:] == ['self-test']
    print(controls(), end='')
