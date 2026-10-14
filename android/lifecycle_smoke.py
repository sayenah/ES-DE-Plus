#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real Activity destruction in debug/minified builds.
import pathlib
import re
import shlex
import subprocess
import time


def framework_recreation(harness, variant, failures):
    h = type('Harness', (), harness)
    name = 'lifecycle-' + variant + '-framework-recreation'
    setting = 'debug_view_attributes_application_package'
    original = h.shell('settings', 'get', 'global', setting).strip()
    h.shell('am', 'force-stop', h.app)
    try:
        assert h.shell('settings', 'get', 'global', 'debug_view_attributes').strip() in ['null', '0'], 'Global view debugging unexpectedly enabled'
        if original == h.app:
            h.shell('settings', 'delete', 'global', setting)
        h.adb('logcat', '-c')
        h.launch()
        h.configured_system(name + '-before')
        before = h.log()
        old = h.shell('pidof', h.app).strip()
        assert old.isdigit()
        # AOSP's CoreSettings observer requests a real local relaunch when
        # this app's view-attribute flag changes. No target instrumentation,
        # injected quit, Activity retry or harness relaunch is involved.
        h.shell('settings', 'put', 'global', setting, h.app)
        h.wait_for(lambda: any('Destroying SDL activity' in line and
                              re.search(r'\s' + old + r'\s', line)
                              for line in h.adb('logcat', '-d', '-v', 'threadtime').splitlines()),
                   name + ' framework destruction', timeout=60)
        started = time.monotonic()
        h.wait_for(lambda: old not in h.shell('pidof', h.app, check=False).split(),
                   name + ' old host exits', timeout=5)
        elapsed = time.monotonic() - started
        logs = h.adb('logcat', '-d', '-v', 'threadtime')
        old_lines = '\n'.join(line for line in logs.splitlines() if re.search(r'\s' + old + r'\s', line))
        assert 'changingConfigurations=true' in old_lines and 'finishing=false' in old_lines
        assert 'handleRelaunchActivityLocally' in old_lines, 'Not the original framework trigger'
        assert 'Finished main function' in old_lines and 'SDL activity destroy join returned' in old_lines
        assert old_lines.count('Running main function') == 1
        h.wait_for(lambda: f'SDL process {old} retired; restarting entry' in h.adb('logcat', '-d'),
                   name + ' product restores entry', timeout=10)
        # The first log line changes only when the new native process opens
        # its log. Old-process shutdown messages cannot satisfy fresh startup.
        h.wait_for(lambda: h.log().splitlines()[0:1] != before.splitlines()[0:1] and
                   'Application startup time:' in h.log(), name + ' automatic fresh startup')
        harness['startup_baseline'] = before
        h.configured_system(name + '-automatic-relaunch')
        new = h.shell('pidof', h.app).strip()
        assert new.isdigit() and new != old
        logs = h.adb('logcat', '-d', '-v', 'threadtime')
        new_lines = '\n'.join(line for line in logs.splitlines() if re.search(r'\s' + new + r'\s', line))
        assert new_lines.count('Running main function') == 1
        assert 'ANR in ' + h.app not in logs and 'JNI DETECTED ERROR' not in logs
        h.save_logs(name)
        (h.evidence / (name + '-result.txt')).write_text(
            f'PASS: AOSP CoreSettings local relaunch; old PID {old} returned/joined and ended '
            f'within 5 s (observed {elapsed:.3f}s); private product activity restored the entry '
            f'without a harness relaunch; new PID {new} loaded two games with one native main.\n')
    except Exception as error:
        failures.append(name + ': ' + str(error))
        h.save_logs(name + '-failure')
        (h.evidence / (name + '-failure-activities.txt')).write_text(h.activity_records()[0])
        (h.evidence / (name + '-failure-window.txt')).write_text(h.shell('dumpsys', 'window'))
        (h.evidence / (name + '-failure.png')).write_bytes(h.adb('exec-out', 'screencap', '-p', binary=True))
        h.capture_frontend_stacks(name + '-failure')
        (h.evidence / (name + '-result.txt')).write_text('FAIL: ' + str(error) + '\n')
    finally:
        # End the recorded case before restoring its developer setting. No
        # failed destruction/start is retried and every failure stays gating.
        h.shell('am', 'force-stop', h.app)
        if original == 'null':
            h.shell('settings', 'delete', 'global', setting)
        else:
            h.shell('settings', 'put', 'global', setting, original)


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
        h.shell('run-as', h.app, 'rm', '-rf', 'files/resources', 'files/themes/linear-es-de',
                'files/resources-installed')
        h.adb('install', '-r', str(apk))
        # Match the original failure's first ordinary launch after replacement,
        # before instrumentation can change the package/task startup sequence.
        h.adb('logcat', '-c')
        try:
            h.launch()
            h.save_logs('lifecycle-' + variant + '-installed-start')
        except Exception as error:
            failures.append('lifecycle-' + variant + '-installed-start: ' + str(error))
            for source in list(h.evidence.glob('frontend-readiness-failure*')):
                (h.evidence / ('lifecycle-' + variant + '-installed-start-' + source.name)).write_bytes(source.read_bytes())
        finally:
            h.shell('am', 'force-stop', h.app)
        framework_recreation(harness, variant, failures)
        # Recreate an actual uncommitted installation for the startup schedule
        # probe. Release retains the files generated by its installed-start case.
        if variant == 'debug':
            h.shell('run-as', h.app, 'rm', '-rf', 'files/resources', 'files/themes/linear-es-de',
                    'files/resources-installed')
        for mode in ['recreate-early', 'recreate-preconfiguration', 'recreate-running', 'finish-running']:
            name = 'lifecycle-' + variant + '-' + mode
            h.shell('am', 'force-stop', h.app)
            h.shell('rm', '-f', command)
            h.adb('logcat', '-c')
            baseline = h.log()
            parked_root = h.shared + '.lifecycle-missing'
            root_parked = mode == 'recreate-preconfiguration'
            if root_parked:
                # Actual missing selected storage forces the existing recovery
                # hold after the first native configuration query. Preserve
                # every ROM and restore the directory before the next launch.
                h.shell('mv', h.shared, parked_root)
            output_path = h.evidence / (name + '-instrumentation.txt')
            with output_path.open('w') as output:
                process = subprocess.Popen(['adb', 'shell', shlex.join([
                    'am', 'instrument', '-w', '-e', 'mode', mode,
                    'org.esdeplus.stub/.LifecycleProbe'])], stdout=output, stderr=subprocess.STDOUT)
                try:
                    if mode not in ['recreate-early', 'recreate-preconfiguration']:
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
                    h.wait_for(lambda: old not in h.shell('pidof', h.app, check=False).split(),
                               name + ' old host process exits', timeout=5)
                    elapsed = time.monotonic() - started
                    logs = h.adb('logcat', '-d', '-v', 'threadtime')
                    old_lines = '\n'.join(line for line in logs.splitlines()
                                          if re.search(r'\s' + old + r'\s', line))
                    assert 'Destroying SDL activity held=false' in old_lines, 'No destruction callback; see ' + name + '-failure-logcat.txt'
                    startup_exit = ('SDL_QUIT observed before frontend initialization; configuration and '
                                    'resources saved; ending process') in old_lines
                    configuration_exit = 'SDL_QUIT observed during configuration hold; ending process' in old_lines
                    copy_cancelled = 'Resource copy cancelled for destruction; files closed; repair marker absent' in old_lines
                    if mode == 'recreate-preconfiguration':
                        assert configuration_exit, 'Quit was lost before the recovery hold'
                        assert 'Lifecycle preconfiguration selection preserved' in old_lines, 'Persisted selection changed'
                        assert not startup_exit, 'Recovery hold was not exercised'
                    elif copy_cancelled:
                        assert mode == 'recreate-early', 'Resource cancellation on a running frontend'
                        assert not startup_exit and 'Resource installation committed' not in old_lines, 'Cancelled installation was committed'
                        assert 'Lifecycle resource selection preserved' in old_lines, 'Persisted selection changed'
                        assert 'Finished main function' in old_lines, 'Cancelled copy did not return main'
                        assert 'SDL activity destroy join returned' in old_lines, 'Cancelled copy did not join'
                    elif startup_exit:
                        # The handoff permits the held-style bounded startup
                        # exit after state is saved. Require its real checkpoint
                        # and completed resource repair, never infer a main return.
                        assert mode == 'recreate-early', 'Startup exit on a running frontend'
                        assert 'Resource installation committed' in old_lines, 'Resource repair was not committed before startup exit'
                        assert old_lines.index('Resource installation committed') < old_lines.index('SDL_QUIT observed before frontend initialization'), 'Startup exit preceded resource commit'
                    else:
                        assert 'Finished main function' in old_lines, 'Native main did not return; see ' + name + '-failure-logcat.txt'
                        assert 'SDL activity destroy join returned' in old_lines, 'Native join did not return; see ' + name + '-failure-logcat.txt'
                    assert old_lines.count('Running main function') == 1, 'Second native main; see ' + name + '-failure-logcat.txt'
                    assert 'ANR in ' + h.app not in logs and 'JNI DETECTED ERROR' not in logs, 'ANR/JNI failure; see ' + name + '-failure-logcat.txt'
                    if mode in ['recreate-early', 'recreate-preconfiguration']:
                        assert 'Lifecycle startup barrier released after destruction quit/join' in old_lines, 'Startup barrier did not release'
                        assert old_lines.count(trigger) == 1, 'Early trigger repeated'
                    if mode == 'recreate-early':
                        assert 'Lifecycle resource selection preserved' in old_lines, 'Persisted selection changed'
                    h.save_logs(name)
                    if root_parked:
                        h.shell('mv', parked_root, h.shared)
                        root_parked = False
                    h.launch()
                    new = h.shell('pidof', h.app).strip()
                    assert new != old
                    if copy_cancelled:
                        next_logs = '\n'.join(line for line in h.adb('logcat', '-d', '-v', 'threadtime').splitlines()
                                              if re.search(r'\s' + new + r'\s', line))
                        assert 'Resource installation committed' in next_logs, 'Next launch did not complete pending repair'
                    h.save_logs(name + '-next-launch')
                    (h.evidence / (name + '-result.txt')).write_text(
                        f'PASS: {mode} via platform Activity API; old PID {old} ended within 5 s '
                        f'(observed {elapsed:.3f}s), ' +
                        ('native recovery hold quit observed; persisted storage selection unchanged; bounded process exit, '
                         if configuration_exit else
                         'resource copy cancelled between closed operations; repair marker absent, selection preserved, main returned/joined; next launch committed repair, '
                         if copy_cancelled else
                         'native startup quit observed after resources were committed; bounded process exit, '
                         if startup_exit else 'native main returned, join returned, ') +
                        'one native main in old process; next ordinary launch loaded two games.\n')
                except Exception as error:
                    failures.append(name + ': ' + str(error))
                    h.save_logs(name + '-failure')
                    (h.evidence / (name + '-failure-activities.txt')).write_text(h.activity_records()[0])
                    (h.evidence / (name + '-failure-window.txt')).write_text(h.shell('dumpsys', 'window'))
                    (h.evidence / (name + '-failure.png')).write_bytes(h.adb('exec-out', 'screencap', '-p', binary=True))
                    h.capture_frontend_stacks(name + '-failure')
                    (h.evidence / (name + '-result.txt')).write_text('FAIL: ' + str(error) + '\n')
                finally:
                    # Cleanup follows the recorded outcome. The same failed
                    # case is never retried, and every failure remains gating.
                    if root_parked:
                        h.shell('mv', parked_root, h.shared)
                    h.shell('am', 'force-stop', h.app)
                    if process.poll() is None:
                        process.wait(timeout=15)
        h.shell('am', 'force-stop', h.app)
    h.adb('install', '-r', str(h.apk))
    (h.evidence / 'lifecycle-summary.txt').write_text(
        '\n'.join(failures) + '\n' if failures else
        'PASS: debug and minified framework recreation with automatic product restoration, resource-startup and preconfiguration recreation, running recreation and running finish; 5 s bound, saved-state startup exit or running native return/join, no second main, next launch.\n')
    assert not failures, '\n'.join(failures)
    h.start_entry('HomeEntry', 'android.intent.category.HOME')
    h.configured_system('lifecycle-restored-home')
