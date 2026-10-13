#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real Activity destruction in debug/minified builds.
import pathlib
import re
import shlex
import subprocess
import time


def run(harness):
    h = type('Harness', (), harness)
    failures = []
    command = '/data/local/tmp/esde-lifecycle-command'
    for variant, apk in [('debug', h.apk),
                         ('minified', pathlib.Path('android/app/build/outputs/apk/release/app-release-smoke.apk'))]:
        h.shell('am', 'force-stop', h.app)
        # Debug remains installed before either variant's first test, so
        # run-as can remove only app-private generated resources before the
        # minified install. No runtime privilege change is needed.
        h.shell('run-as', h.app, 'rm', '-rf', 'files/resources', 'files/themes',
                'files/resources-installed')
        h.adb('install', '-r', str(apk))
        for mode in ['recreate-early', 'recreate-running', 'finish-running']:
            name = 'lifecycle-' + variant + '-' + mode
            h.shell('am', 'force-stop', h.app)
            h.shell('rm', '-f', command)
            h.adb('logcat', '-c')
            baseline = h.log()
            output_path = h.evidence / (name + '-instrumentation.txt')
            with output_path.open('w') as output:
                process = subprocess.Popen(['adb', 'shell', shlex.join([
                    'am', 'instrument', '-w', '-e', 'mode', mode,
                    'org.esdeplus.stub/.LifecycleProbe'])], stdout=output, stderr=subprocess.STDOUT)
                try:
                    if mode != 'recreate-early':
                        h.wait_for(lambda: 'Lifecycle probe ready mode=' + mode in h.adb('logcat', '-d') and
                                   h.log() != baseline and 'Application startup time:' in h.log(),
                                   name + ' actual frontend startup', timeout=60)
                        time.sleep(10)
                        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app)
                        h.screenshot(name + '-before')
                        h.shell('touch', command)
                    trigger = 'Lifecycle probe triggering ' + mode
                    h.wait_for(lambda: trigger in h.adb('logcat', '-d'), name + ' platform trigger', timeout=60)
                    logs = h.adb('logcat', '-d', '-v', 'threadtime')
                    old = re.search(re.escape(trigger) + r' pid=(\d+)', logs)[1]
                    started = time.monotonic()
                    # The action is issued exactly once. A timeout stays a
                    # failure even though later diagnostic cleanup ends it.
                    h.wait_for(lambda: h.shell('pidof', h.app, check=False).strip() != old,
                               name + ' old host process exits', timeout=5)
                    elapsed = time.monotonic() - started
                    logs = h.adb('logcat', '-d', '-v', 'threadtime')
                    old_lines = '\n'.join(line for line in logs.splitlines()
                                          if re.search(r'\s' + old + r'\s', line))
                    assert 'Destroying SDL activity held=false' in old_lines, logs
                    assert 'Finished main function' in old_lines, logs
                    assert 'SDL activity destroy join returned' in old_lines, logs
                    assert old_lines.count('Running main function') == 1, logs
                    assert 'ANR in ' + h.app not in logs and 'JNI DETECTED ERROR' not in logs, logs
                    h.save_logs(name)
                    h.launch()
                    assert h.shell('pidof', h.app).strip() != old
                    h.save_logs(name + '-next-launch')
                    (h.evidence / (name + '-result.txt')).write_text(
                        f'PASS: {mode} via platform Activity API; old PID {old} ended within 5 s '
                        f'(observed {elapsed:.3f}s), native main returned, join returned, '
                        'one native main in old process; next ordinary launch loaded two games.\n')
                except Exception as error:
                    failures.append(name + ': ' + str(error))
                    h.save_logs(name + '-failure')
                    (h.evidence / (name + '-failure-activities.txt')).write_text(h.activity_records()[0])
                    (h.evidence / (name + '-failure-window.txt')).write_text(h.shell('dumpsys', 'window'))
                    h.capture_frontend_stacks(name + '-failure')
                    (h.evidence / (name + '-result.txt')).write_text('FAIL: ' + str(error) + '\n')
                finally:
                    # Cleanup follows the recorded outcome. The same failed
                    # case is never retried, and every failure remains gating.
                    h.shell('am', 'force-stop', h.app)
                    if process.poll() is None:
                        process.wait(timeout=15)
        h.shell('am', 'force-stop', h.app)
    h.adb('install', '-r', str(h.apk))
    (h.evidence / 'lifecycle-summary.txt').write_text(
        '\n'.join(failures) + '\n' if failures else
        'PASS: debug and minified early recreation, running recreation and running finish; 5 s bound, native return/join, no second main, next launch.\n')
    assert not failures, '\n'.join(failures)
    h.start_entry('HomeEntry', 'android.intent.category.HOME')
    h.configured_system('lifecycle-restored-home')
