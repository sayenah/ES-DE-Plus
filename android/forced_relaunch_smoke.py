#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real ASSETS_PATHS relaunches; no startup recovery.
import os
import re
import shlex
import subprocess
import time


def run(harness):
    h = type('Harness', (), harness)
    baseline = os.environ.get('ESDE_ASSETS_UNFIXED') == 'true'
    overlay = 'com.android.shell:esde_wo18'
    failures = []
    outcomes = []

    def capture(name):
        h.save_logs(name)
        (h.evidence / (name + '-activities.txt')).write_text(h.activity_records()[0])
        (h.evidence / (name + '-window.txt')).write_text(h.focused_window())

    def root_action(*args):
        # Only the overlay manager requires root. App actions/focus checks use
        # ordinary shell, including all resource/configurator instrumentation.
        h.adb('root')
        h.adb('wait-for-device')
        try:
            h.wait_for(lambda: h.shell('id', '-u').strip() == '0', 'overlay-manager root', timeout=10)
            return h.shell(*args)
        finally:
            h.adb('unroot')
            h.adb('wait-for-device')
            h.wait_for(lambda: h.shell('id', '-u').strip() == '2000', 'ordinary shell after overlay', timeout=10)

    # ThemeResources is Android's public palette overlayable on these images.
    # No APK, dependency or platform source is added for the trigger.
    root_action('cmd', 'overlay', 'fabricate', '--target', 'android', '--target-name', 'ThemeResources',
                '--name', 'esde_wo18', 'android:color/system_neutral1_500', '0x1c', '0xff123456')
    (h.evidence / 'assets-overlay-created.txt').write_text(h.shell('cmd', 'overlay', 'dump', overlay))

    for mode in ('game', 'configurator', 'copy', 'steady'):
        name = 'assets-' + mode
        process = None
        h.shell('am', 'force-stop', h.app)
        h.shell('am', 'force-stop', 'org.esdeplus.stub')
        root_action('cmd', 'overlay', 'disable', overlay)
        h.shell('rm', '-f', '/data/local/tmp/esde-assets-configurator')
        h.adb('logcat', '-c')
        try:
            if mode in ('copy', 'configurator'):
                output = (h.evidence / (name + '-instrumentation.txt')).open('w')
                process = subprocess.Popen(['adb', 'shell', shlex.join([
                    'am', 'instrument', '-w', '-e', 'mode', mode,
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
            dump, records = h.activity_records()
            frontend = [r for r in records if r[0] == 'MainActivity']
            assert len(frontend) == 1, dump
            task = frontend[0][1]
            if mode == 'game':
                h.shell('am', 'start', '-n', 'org.esdeplus.stub/.RecipientActivity')
            elif mode == 'configurator':
                h.shell('touch', '/data/local/tmp/esde-assets-configurator')
                h.ui('Save and start frontend')
            if mode in ('game', 'configurator'):
                h.wait_for(lambda: re.search(r'state=STOPPED', next((s for s in re.split(
                    r'\n\s*\*\s+Hist\s+#\d+:', h.activity_records()[0])
                    if frontend[0][2] in s), '')) is not None, name + ' frontend STOPPED', timeout=30)
            capture(name + '-before-overlay')

            # Use a separate root shell only for this one overlay command; keep
            # the ordinary-shell sampler running through the whole transition.
            focus_samples = []
            def game_focus():
                window = h.focused_window()
                focus_samples.append(f'{time.monotonic():.3f}: {window}')
                assert h.smoke_checks.package_window_focused(window, 'org.esdeplus.stub'), window
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
            old_lines = '\n'.join(line for line in logs.splitlines() if re.search(r'\s' + old + r'\s', line))
            destruction = next(line for line in old_lines.splitlines() if 'Destroying SDL activity' in line)
            assert 'changingConfigurations=true' in destruction and 'finishing=false' in destruction, destruction
            assert 'configurationChanges=0x-80000000' in destruction, 'Not ASSETS_PATHS-only: ' + destruction
            assert old_lines.count('Running main function') == 1, 'Second native main in old VM'
            if baseline:
                # These are separate positive controls, never an expected-fail
                # path in the candidate gate. Record races that happen to pass.
                helper = f'SDL process {old} retired; restarting entry'
                until = time.monotonic() + 10
                while helper not in h.adb('logcat', '-d') and time.monotonic() < until:
                    time.sleep(0.25)
                restored = helper in h.adb('logcat', '-d')
                if mode in ('game', 'configurator'):
                    assert not restored, 'Unfixed positive control unexpectedly restored stopped host'
                outcomes.append(f'{mode}: ' + ('race did not reproduce' if restored else 'G-30 reproduced; no helper restoration'))
            else:
                h.wait_for(lambda: f'SDL process {old} retired; restarting entry' in h.adb('logcat', '-d'),
                           name + ' helper restoration', timeout=15)
                logs = h.adb('logcat', '-d', '-v', 'threadtime')
                assert 'Frontend restart decision requested=true' in old_lines, old_lines
                assert 'configured=true' in old_lines and 'helperStarted=true' in old_lines, old_lines
                assert re.search(r'START .*FrontendRestartActivity', logs), logs
                h.wait_for(lambda: h.shell('pidof', h.app, check=False).strip().isdigit() and
                           h.shell('pidof', h.app).strip() != old and 'Application startup time:' in h.log(),
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
            h.shell('am', 'force-stop', h.app)
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
    (h.evidence / 'assets-summary.txt').write_text('\n'.join(outcomes + failures) + '\n')
    assert not failures, '\n'.join(failures)
