#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real ASSETS_PATHS relaunches; no startup recovery.
import os
import re
import shlex
import subprocess
import threading
import time
import sys


def destruction_evidence(logs, old):
    old_lines = '\n'.join(line for line in logs.splitlines() if re.search(r'\s' + old + r'\s', line))
    destruction = next((line for line in old_lines.splitlines() if 'Destroying SDL activity' in line), '')
    assert 'held=false' in destruction, 'Held-host outcome is not G-30: ' + destruction
    assert 'changingConfigurations=true' in destruction and 'finishing=false' in destruction, destruction
    assert 'configurationChanges=0x-80000000' in destruction, 'Not ASSETS_PATHS-only: ' + destruction
    assert old_lines.count('Running main function') == 1, 'Second/missing native main in old VM'
    return old_lines


def restoration_evidence(logs, old):
    old_lines = destruction_evidence(logs, old)
    assert 'Frontend restart decision requested=true configured=true helperStarted=true' in old_lines, old_lines
    assert re.search(r'START .*FrontendRestartActivity', logs), 'Missing helper START'
    assert f'SDL process {old} retired; restarting entry' in logs, 'Missing observed old-process retirement'


def controls():
    logs = (' I 123 124 Running main function\n'
            ' I 123 123 Destroying SDL activity held=false finishing=false changingConfigurations=true '
            'configurationChanges=0x-80000000\n'
            ' I 123 123 Frontend restart decision requested=true configured=true helperStarted=true\n'
            ' I 456 456 START cmp=FrontendRestartActivity\n'
            ' I 789 789 SDL process 123 retired; restarting entry\n')
    restoration_evidence(logs, '123')
    mutants = [logs.replace(token, replacement) for token, replacement in (
        ('requested=true', 'requested=false'), ('configured=true', 'configured=false'),
        ('helperStarted=true', 'helperStarted=false'), ('START', 'NOT_STARTED'),
        ('SDL process 123 retired;', 'SDL process 999 retired;'),
        ('configurationChanges=0x-80000000', 'configurationChanges=0x10000000'),
        ('finishing=false', 'finishing=true'), ('changingConfigurations=true', 'changingConfigurations=false'))]
    mutants.append(logs.replace('held=false', 'held=true'))
    mutants += [logs + ' I 123 124 Running main function\n', logs.replace(' I 123 ', ' I 999 ')]
    for mutant in mutants:
        try:
            restoration_evidence(mutant, '123')
        except AssertionError:
            pass
        else:
            raise AssertionError('Incomplete/mismatched restore chain escaped')
    return 'PASS: eleven broken restore chains rejected; no recovery or action retry\n'


def run(harness):
    h = type('Harness', (), harness)
    baseline = os.environ.get('ESDE_ASSETS_UNFIXED') == 'true'
    overlay = 'com.android.shell:esde_wo18'
    failures = []
    outcomes = []
    (h.evidence / 'assets-chain-controls.txt').write_text(controls())

    def capture(name):
        h.save_logs(name)
        (h.evidence / (name + '-activities.txt')).write_text(h.activity_records()[0])
        (h.evidence / (name + '-window.txt')).write_text(h.focused_window())

    def root_action(*args):
        # Emulator userdebug su scopes root to this command. Keep adbd and
        # concurrent focus sampling/instrumentation connected as ordinary shell.
        return h.shell('su', '0', *args)

    # ThemeResources is Android's public palette overlayable on these images.
    # No APK, dependency or platform source is added for the trigger.
    root_action('cmd', 'overlay', 'fabricate', '--target', 'android', '--target-name', 'ThemeResources',
                '--name', 'esde_wo18', 'android:color/system_neutral1_500', '0x1c', '0xff123456')
    (h.evidence / 'assets-overlay-created.txt').write_text(h.shell('cmd', 'overlay', 'dump', overlay))

    for mode in ('game', 'configurator', 'copy', 'steady'):
        name = 'assets-' + mode
        process = None
        monitor = None
        stop_sampling = threading.Event()
        focus_samples = []
        focus_errors = []
        h.shell('am', 'force-stop', h.app)
        h.shell('am', 'force-stop', 'org.esdeplus.stub')
        root_action('cmd', 'overlay', 'disable', overlay)
        h.shell('rm', '-f', '/data/local/tmp/esde-assets-configurator')
        h.adb('logcat', '-c')
        try:
            if mode in ('copy', 'configurator'):
                # AOSP's ordinary instrumentation cleanup force-stops the
                # whole package when the parent dies, removing the helper.
                # Attach without restart to a Java-only VM instead. Root is
                # used only for the private debug bootstrap and overlay manager,
                # never for game focus or product restoration.
                root_action('am', 'start', '-W', '-n',
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
                h.wait_for(lambda: any(h.node_matches(n, 'Save and start frontend') for n in h.hierarchy()),
                           name + ' configurator visible', timeout=30)
            if mode in ('game', 'configurator'):
                h.wait_for(lambda: re.search(r'state=STOPPED', next((s for s in re.split(
                    r'\n\s*\*\s+Hist\s+#\d+:', h.activity_records()[0])
                    if frontend[0][2] in s), '')) is not None, name + ' frontend STOPPED', timeout=30)
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
            # ThemeResources requires root for activation as well as fabrication.
            # Focus sampling spans delivery; no adbd restart interrupts it.
            root_action('cmd', 'overlay', 'enable', overlay)
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
    (h.evidence / 'assets-summary.txt').write_text('\n'.join(outcomes + failures) + '\n')
    assert not failures, '\n'.join(failures)


if __name__ == '__main__':
    assert sys.argv[1:] == ['self-test']
    print(controls(), end='')
