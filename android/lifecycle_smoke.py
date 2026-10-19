#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real Activity destruction in debug/minified builds.
import pathlib
import re
import shlex
import subprocess
import time


def home_record(dump, records):
    if len(records) != 1:
        return False
    section = next((part for part in re.split(r'\n\s*\*\s+Hist\s+#\d+:', dump)
                    if re.match(r'\s*ActivityRecord\{' + re.escape(records[0][2]) + r'\}', part)), '')
    # Android 10 prints the Activity type in its own TaskRecord section;
    # newer releases also print the type in the Task header. Tie either
    # representation to this frontend record/task, never a stock HOME task.
    return bool(re.search(r'^\s*mActivityType=home\b', section, re.M) or
                re.search(r'Task\{[^}\n]+ #' + records[0][1] + r'\b[^}\n]*type=home', dump))


def resolved_home(h):
    raw = h.shell('cmd', 'package', 'resolve-activity', '--brief', '-a', 'android.intent.action.MAIN',
                  '-c', 'android.intent.category.HOME')
    component = next(line.strip() for line in raw.splitlines() if '/' in line and ' ' not in line.strip())
    package, name = component.split('/', 1)
    return raw, package + '/' + (package + name if name.startswith('.') else name)


def framework_recreation(harness, variant, failures, home=False, background=False):
    h = type('Harness', (), harness)
    name = 'lifecycle-' + variant + '-framework-recreation' + ('-home' if home else '-background' if background else '')
    setting = 'debug_view_attributes_application_package'
    original = h.shell('settings', 'get', 'global', setting).strip()
    h.shell('am', 'force-stop', h.app)
    original_home = None
    default_before = None
    default_selected = False
    def background_focus():
        if background:
            window = h.focused_window()
            with (h.evidence / (name + '-recipient-focus.txt')).open('a') as output:
                output.write(f'{time.monotonic():.3f}: {window}\n')
            assert h.smoke_checks.package_window_focused(window, 'org.esdeplus.stub'), \
                'Background recipient lost focus before next user entry: ' + window
    if home:
        resolved = h.shell('cmd', 'package', 'resolve-activity', '--brief', '-a', 'android.intent.action.MAIN',
                           '-c', 'android.intent.category.HOME')
        original_home = next(line.strip() for line in resolved.splitlines() if '/' in line and ' ' not in line.strip())
        if 'ResolverActivity' in original_home:
            candidates = h.shell('cmd', 'package', 'query-activities', '--brief', '-a', 'android.intent.action.MAIN',
                                 '-c', 'android.intent.category.HOME')
            original_home = next(line.strip() for line in candidates.splitlines() if '/' in line and
                                 ' ' not in line.strip() and not line.strip().startswith(h.app + '/') and 'ResolverActivity' not in line)
        request = h.shell('cmd', 'package', 'set-home-activity', h.app + '/org.esdeplus.frontend.HomeEntry')
        assert 'Success' in request, request
        # A successful setter does not guarantee that the device permits a
        # different global HOME. Measure it before starting or destroying the
        # frontend; the actual HOME Activity type is required either way.
        deadline = time.monotonic() + 5
        while True:
            resolved, default_before = resolved_home(h)
            default_selected = default_before == h.app + '/org.esdeplus.frontend.HomeEntry'
            if default_selected or time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        (h.evidence / (name + '-default-home-request.txt')).write_text(
            request + '\n' + resolved + f'Frontend selected as global HOME: {default_selected}\n')
    try:
        assert h.shell('settings', 'get', 'global', 'debug_view_attributes').strip() in ['null', '0'], 'Global view debugging unexpectedly enabled'
        if original == h.app:
            h.shell('settings', 'delete', 'global', setting)
        h.adb('logcat', '-c')
        if home:
            harness['startup_baseline'] = h.log()
            h.shell('am', 'start', '-a', 'android.intent.action.MAIN',
                    '-c', 'android.intent.category.HOME', '-p', h.app)
        else:
            h.launch()
        h.configured_system(name + '-before')
        if home:
            dump, records = h.activity_records()
            (h.evidence / (name + '-before-home-activities.txt')).write_text(dump)
            assert home_record(dump, records), dump
            assert 'HOME=true' in h.adb('logcat', '-d'), 'Probe did not enter actual HOME mode'
        before = h.log()
        old = h.shell('pidof', h.app).strip()
        assert old.isdigit()
        if background:
            h.shell('am', 'start', '-n', 'org.esdeplus.stub/.RecipientActivity')
            def stopped():
                dump, records = h.activity_records()
                sections = re.split(r'\n\s*\*\s+Hist\s+#\d+:', dump)
                return (len(records) == 1 and any(records[0][2] in section and
                        re.search(r'\bstate=STOPPED\b', section) for section in sections) and
                        h.smoke_checks.package_window_focused(h.focused_window(), 'org.esdeplus.stub'))
            h.wait_for(stopped, name + ' ordinary frontend STOPPED behind recipient', timeout=30)
            (h.evidence / (name + '-stopped-activities.txt')).write_text(h.activity_records()[0])
            (h.evidence / (name + '-stopped-window.txt')).write_text(h.focused_window())
        # AOSP's CoreSettings observer requests a real local relaunch when
        # this app's view-attribute flag changes. No target instrumentation,
        # injected quit, Activity retry or harness relaunch is involved.
        h.begin_startup()
        h.shell('settings', 'put', 'global', setting, h.app)
        def destroyed():
            background_focus()
            return any('Destroying SDL activity' in line and re.search(r'\s' + old + r'\s', line)
                       for line in h.adb('logcat', '-d', '-v', 'threadtime').splitlines())
        h.wait_for(destroyed,
                   name + ' framework destruction', timeout=60)
        started = time.monotonic()
        def retired():
            background_focus()
            return old not in h.shell('pidof', h.app, check=False).split()
        h.wait_for(retired,
                   name + ' old host exits', timeout=5)
        elapsed = time.monotonic() - started
        logs = h.adb('logcat', '-d', '-v', 'threadtime')
        old_lines = '\n'.join(line for line in logs.splitlines() if re.search(r'\s' + old + r'\s', line))
        assert 'changingConfigurations=true' in old_lines and 'finishing=false' in old_lines
        if variant == 'debug':
            assert 'handleRelaunchActivityLocally' in old_lines, 'Not the original framework trigger'
        else:
            assert 'SDL destruction caller' not in old_lines, 'Release logged the debug stack trace'
        assert 'Finished main function' in old_lines and 'SDL activity destroy join returned' in old_lines
        assert old_lines.count('Running main function') == 1
        if background:
            # Observe the real task transition through retirement and five
            # more seconds, in both variants. No instrumentation can remove
            # the helper or supply background-launch privileges in this case.
            until = time.monotonic() + 5
            while time.monotonic() < until:
                background_focus()
                time.sleep(0.25)
            h.save_logs(name + '-before-next-entry')
            (h.evidence / (name + '-before-next-entry-activities.txt')).write_text(h.activity_records()[0])
            (h.evidence / (name + '-before-next-entry-window.txt')).write_text(h.focused_window())
            background_focus()
            logs = h.adb('logcat', '-d')
            assert f'SDL process {old} retired; restarting entry' not in logs, 'Background helper restored frontend without user entry'
            assert logs.count('Running main function') == 1, 'Background relaunch started native main before user entry'
            h.start_entry()
        else:
            h.wait_for(lambda: f'SDL process {old} retired; restarting entry' in h.adb('logcat', '-d'),
                       name + ' product restores entry', timeout=10)
        h.wait_for(lambda: h.log().splitlines()[0:1] != before.splitlines()[0:1] and
                   'Application startup time:' in h.log(), name + ' fresh startup')
        harness['startup_baseline'] = before
        h.configured_system(name + '-automatic-relaunch')
        new = h.shell('pidof', h.app).strip()
        assert new.isdigit() and new != old
        logs = h.adb('logcat', '-d', '-v', 'threadtime')
        new_lines = '\n'.join(line for line in logs.splitlines() if re.search(r'\s' + new + r'\s', line))
        assert new_lines.count('Running main function') == 1
        if background:
            assert logs.count('Running main function') == 2, 'Background relaunch started an extra native main'
        assert 'ANR in ' + h.app not in logs and 'JNI DETECTED ERROR' not in logs
        if home:
            assert 'HOME=true' in new_lines, 'Restored entry lost HOME semantics'
            resolved, default_after = resolved_home(h)
            assert default_after == default_before, (default_before, resolved)
            dump, records = h.activity_records()
            (h.evidence / (name + '-home-activities.txt')).write_text(dump)
            (h.evidence / (name + '-home-resolver.txt')).write_text(resolved)
            assert len(records) == 1 and records[0][0] in ['MainActivity', 'HomeEntry'], dump
            assert home_record(dump, records), dump
            if default_selected:
                h.key('KEYCODE_HOME')
            else:
                # Some devices retain a protected stock default. Exercise our
                # real HOME entry without changing or disabling that launcher.
                h.shell('am', 'start', '-a', 'android.intent.action.MAIN',
                        '-c', 'android.intent.category.HOME', '-p', h.app)
            h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), h.app),
                       name + ' next HOME entry focused', timeout=30)
            (h.evidence / (name + '-default-home-capability.txt')).write_text(
                f'Frontend selected as global HOME: {default_selected}; before={default_before}; '
                f'after={default_after}; actual frontend HOME type and next '
                + ('system HOME key' if default_selected else 'package-scoped HOME entry') + ' verified.\n')
            assert h.shell('pidof', h.app).strip() == new
            h.save_logs(name + '-next-home')
        h.save_logs(name)
        (h.evidence / (name + '-result.txt')).write_text(
            f'PASS: AOSP CoreSettings local relaunch; old PID {old} returned/joined and ended '
            f'within 5 s (observed {elapsed:.3f}s); ' +
            ('recipient kept focus through STOPPED destruction and 5 s after retirement until user entry; '
             'next foreground entry restored the frontend; ' if background else
             'private product activity restored the entry without a harness relaunch; ') +
            f'new PID {new} loaded two games with one native main; HOME={home}; background={background}; '
            f'frontend selected as global HOME={default_selected if home else "not queried"}.\n')
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
        if original_home:
            restored = h.shell('cmd', 'package', 'set-home-activity', original_home)
            assert 'Success' in restored, restored
            # Finish the stock launcher's actual return transition and late
            # onboarding before the next frontend launch is measured. This is
            # cleanup after the recorded outcome, never a frontend replay.
            h.shell('am', 'start', '-a', 'android.intent.action.MAIN',
                    '-c', 'android.intent.category.HOME', '-n', original_home)
            stock = original_home.split('/', 1)[0]
            h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), stock),
                       name + ' original HOME returned', timeout=30)
            h.screenshot(name + '-original-home-return')
            h.dismiss_stock_onboarding(force=True)
            h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), stock) and
                       not h.smoke_checks.stock_onboarding_focused(h.focused_window(), h.stock_package),
                       name + ' original HOME transition complete', timeout=30)
        if original == 'null':
            h.shell('settings', 'delete', 'global', setting)
        else:
            h.shell('settings', 'put', 'global', setting, original)


def slow_restart(harness, variant, failures, expire=False):
    h = type('Harness', (), harness)
    mode = 'restart-timeout' if expire else 'restart-wait'
    name = 'lifecycle-' + variant + '-' + mode
    h.shell('am', 'force-stop', h.app)
    h.adb('logcat', '-c')
    h.dismiss_stock_onboarding(force=True)
    with (h.evidence / (name + '-instrumentation.txt')).open('w') as output:
        process = subprocess.Popen(['adb', 'shell', shlex.join([
            'am', 'instrument', '-w', '-e', 'mode', mode,
            'org.esdeplus.stub/.LifecycleProbe'])], stdout=output, stderr=subprocess.STDOUT)
        try:
            h.wait_for(lambda: 'Lifecycle slow restart parent pid=' in h.adb('logcat', '-d') and
                       'FrontendRestartActivity' in h.focused_window(), name + ' helper visible', timeout=30)
            old = re.search(r'Lifecycle slow restart parent pid=(\d+)', h.adb('logcat', '-d'))[1]
            time.sleep(6)
            assert old in h.shell('pidof', h.app).split(), 'Slow parent ended before the wait control'
            assert 'FrontendRestartActivity' in h.focused_window(), 'Helper disappeared after former 5 s limit'
            assert 'Running main function' not in h.adb('logcat', '-d'), 'Helper overlapped the live parent'
            h.screenshot(name + '-still-waiting')
            if expire:
                h.wait_for(lambda: 'Frontend restart recovery shown; entry remains available' in h.adb('logcat', '-d'),
                           name + ' actual two-minute recovery screen', timeout=135)
                assert 'FrontendRestartActivity' in h.focused_window(), 'Recovery screen disappeared'
                assert any(h.smoke_checks.exact_label(node, 'Retry startup') for node in h.hierarchy()), 'No visible retry action'
                assert old in h.shell('pidof', h.app).split() and 'Running main function' not in h.adb('logcat', '-d')
                h.screenshot(name + '-visible-recovery')
            if expire:
                h.ui('Retry startup', dpad=True)
                assert 'FrontendRestartActivity' in h.focused_window(), 'Retry lost the visible helper'
            assert old in h.shell('pidof', h.app).split()
            logs = h.adb('logcat', '-d', '-v', 'threadtime')
            assert 'Running main function' not in logs, 'Helper started native main over a live parent'
            assert 'ANR in ' + h.app not in logs and 'JNI DETECTED ERROR' not in logs
            h.save_logs(name)
            (h.evidence / (name + '-result.txt')).write_text(
                f'PASS: isolated helper stayed visible with live parent {old} for more than 6 s; '
                f'no native main over the live parent; timeout/retry={expire}. '
                'Ordinary framework cases separately verify real parent retirement and automatic restoration.\n')
        except Exception as error:
            failures.append(name + ': ' + str(error))
            h.save_logs(name + '-failure')
            (h.evidence / (name + '-failure-window.txt')).write_text(h.shell('dumpsys', 'window'))
            (h.evidence / (name + '-result.txt')).write_text('FAIL: ' + str(error) + '\n')
        finally:
            h.shell('am', 'force-stop', h.app)
            if process.poll() is None:
                process.wait(timeout=15)


def expired_restart_resume(harness, variant, failures):
    h = type('Harness', (), harness)
    name = 'lifecycle-' + variant + '-restart-resume'
    command = '/data/local/tmp/esde-lifecycle-command'
    h.shell('am', 'force-stop', h.app)
    # The prior timeout/retry control can leave its window in the display
    # transition briefly after force-stop. Retire that fixture before a new
    # helper can satisfy readiness; never mistake its old window for this one.
    h.wait_for(lambda: not h.shell('pidof', h.app + ':lifecycle', check=False).strip() and
               not h.smoke_checks.package_window_focused(h.focused_window(), h.app),
               name + ' previous helper window retired', timeout=15)
    h.shell('rm', '-f', command)
    h.adb('logcat', '-c')
    harness['startup_baseline'] = h.log()
    h.dismiss_stock_onboarding(force=True)
    h.begin_startup()
    # A real isolated shell process supplies a parent whose death does not
    # make instrumentation teardown remove the helper. No native main runs
    # until that process is gone and the existing helper regains focus.
    parent = subprocess.Popen(['adb', 'shell', 'sh', '-c', shlex.quote('echo $$; exec sleep 180')],
                              stdout=subprocess.PIPE, text=True)
    old = parent.stdout.readline().strip()
    assert old.isdigit(), old
    with (h.evidence / (name + '-instrumentation.txt')).open('w') as output:
        process = subprocess.Popen(['adb', 'shell', shlex.join([
            'am', 'instrument', '-w', '-e', 'mode', 'restart-resume', '-e', 'parentPid', old,
            'org.esdeplus.stub/.LifecycleProbe'])], stdout=output, stderr=subprocess.STDOUT)
        try:
            def helper_focused():
                if f'Lifecycle slow restart parent pid={old}' not in h.adb('logcat', '-d'):
                    return False
                window = h.focused_window()
                return (h.shell('pidof', h.app + ':lifecycle', check=False).strip().isdigit() and
                        h.smoke_checks.package_window_focused(window, h.app) and
                        re.search(r'mCurrentFocus=.*[./]FrontendRestartActivity\b', window))
            h.wait_for(helper_focused, name + ' fresh helper focused', timeout=30)
            helper = h.shell('pidof', h.app + ':lifecycle').strip()
            assert helper.isdigit()
            began = time.monotonic()
            h.shell('am', 'start', '-n', 'org.esdeplus.stub/.RecipientActivity')
            h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), 'org.esdeplus.stub'),
                       name + ' helper backgrounded', timeout=30)
            h.shell('kill', old)
            parent.wait(timeout=15)
            while time.monotonic() - began < 121:
                assert h.smoke_checks.package_window_focused(h.focused_window(), 'org.esdeplus.stub')
                assert 'Running main function' not in h.adb('logcat', '-d'), 'Unfocused helper restarted frontend'
                time.sleep(1)
            h.shell('touch', command)
            h.wait_for(lambda: f'SDL process {old} retired; restarting entry' in h.adb('logcat', '-d'),
                       name + ' expired helper restores retired parent entry', timeout=15)
            logs = h.adb('logcat', '-d', '-v', 'threadtime')
            assert 'Frontend restart recovery shown' not in logs, 'Dead parent incorrectly required recovery'
            assert any(re.search(r'\s' + helper + r'\s', line) and
                       f'SDL process {old} retired' in line for line in logs.splitlines()), 'Helper process was replaced'
            h.configured_system(name + '-restored')
            logs = h.adb('logcat', '-d')
            assert logs.count('Running main function') == 1, 'Expired resume started multiple native mains'
            assert 'ANR in ' + h.app not in logs and 'JNI DETECTED ERROR' not in logs
            h.save_logs(name)
            (h.evidence / (name + '-result.txt')).write_text(
                'PASS: same helper resumed after its real 120 s deadline with its isolated parent dead; '
                'recipient kept focus while helper paused; entry restored without recovery or retry.\n')
        except Exception as error:
            failures.append(name + ': ' + str(error))
            h.save_logs(name + '-failure')
            (h.evidence / (name + '-failure-window.txt')).write_text(h.shell('dumpsys', 'window'))
            (h.evidence / (name + '-result.txt')).write_text('FAIL: ' + str(error) + '\n')
        finally:
            if parent.poll() is None:
                h.shell('kill', old, check=False)
            parent.wait(timeout=15)
            h.shell('am', 'force-stop', h.app)
            if process.poll() is None:
                process.wait(timeout=15)


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
        framework_recreation(harness, variant, failures, home=True)
        framework_recreation(harness, variant, failures, background=True)
        slow_restart(harness, variant, failures)
        slow_restart(harness, variant, failures, expire=True)
        expired_restart_resume(harness, variant, failures)
        # Recreate an actual uncommitted installation for the startup schedule
        # probe. Release retains the files generated by its installed-start case.
        if variant == 'debug':
            h.shell('run-as', h.app, 'rm', '-rf', 'files/resources', 'files/themes/linear-es-de',
                    'files/resources-installed')
        modes = ['recreate-early', 'recreate-preconfiguration', 'recreate-running', 'finish-running', 'recreate-background']
        if variant == 'debug':
            modes.insert(2, 'recreate-startup')
        for mode in modes:
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
            h.dismiss_stock_onboarding(force=True)
            with output_path.open('w') as output:
                process = subprocess.Popen(['adb', 'shell', shlex.join([
                    'am', 'instrument', '-w', '-e', 'mode', mode,
                    'org.esdeplus.stub/.LifecycleProbe'])], stdout=output, stderr=subprocess.STDOUT)
                try:
                    if mode not in ['recreate-early', 'recreate-preconfiguration', 'recreate-startup']:
                        h.wait_for(lambda: 'Lifecycle probe ready mode=' + mode in h.adb('logcat', '-d') and
                                   h.log() != baseline and 'Application startup time:' in h.log(),
                                   name + ' actual frontend startup', timeout=60)
                        time.sleep(10)
                        h.dismiss_stock_onboarding(force=True)
                        h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), h.app),
                                   name + ' frontend focused before action', timeout=30)
                        h.screenshot(name + '-before')
                        if mode == 'recreate-background':
                            h.shell('am', 'start', '-n', 'org.esdeplus.stub/.RecipientActivity')
                            h.wait_for(lambda: 'Lifecycle frontend stopped mode=' + mode in h.adb('logcat', '-d') and
                                       h.smoke_checks.package_window_focused(h.focused_window(), 'org.esdeplus.stub'),
                                       name + ' real STOPPED frontend behind recipient', timeout=30)
                            h.save_logs(name + '-stopped')
                            (h.evidence / (name + '-stopped-activities.txt')).write_text(h.activity_records()[0])
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
                    elif mode == 'recreate-startup':
                        assert startup_exit, 'Installed-resource startup checkpoint was not exercised'
                        assert 'Resource copy required=false' in old_lines, 'Startup unexpectedly needed resource copy'
                        assert 'Resource installation committed' not in old_lines and not copy_cancelled
                        assert 'Lifecycle installed-resource selection preserved' in old_lines
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
                    if mode in ['recreate-early', 'recreate-preconfiguration', 'recreate-startup']:
                        assert 'Lifecycle startup barrier released after destruction quit/join' in old_lines, 'Startup barrier did not release'
                        assert old_lines.count(trigger) == 1, 'Early trigger repeated'
                    if mode == 'recreate-early':
                        assert 'Lifecycle resource selection preserved' in old_lines, 'Persisted selection changed'
                    h.save_logs(name)
                    if root_parked:
                        h.shell('mv', parked_root, h.shared)
                        root_parked = False
                    if mode == 'recreate-background':
                        # Android may defer a background launch. A user entry
                        # must recover one clean frontend in either case.
                        h.save_logs(name + '-before-next-entry')
                        (h.evidence / (name + '-before-next-entry-activities.txt')).write_text(h.activity_records()[0])
                        (h.evidence / (name + '-before-next-entry-window.txt')).write_text(h.focused_window())
                    if mode == 'recreate-background':
                        harness['startup_baseline'] = baseline
                        h.start_entry()
                        h.wait_for(lambda: h.log().splitlines()[0:1] != baseline.splitlines()[0:1] and
                                   'Application startup time:' in h.log(), name + ' fresh next entry')
                        h.configured_system(name + '-next-foreground')
                    else:
                        h.launch()
                    new = h.shell('pidof', h.app).strip()
                    assert new.isdigit() and new != old
                    new_lines = '\n'.join(line for line in h.adb('logcat', '-d', '-v', 'threadtime').splitlines()
                                          if re.search(r'\s' + new + r'\s', line))
                    assert new_lines.count('Running main function') == 1, 'Next entry started more than one native main'
                    if variant == 'minified':
                        assert 'SDL destruction caller' not in old_lines, 'Release logged a destruction stack'
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
                         'native startup quit observed with installed resources and no copy required; bounded process exit, '
                         if mode == 'recreate-startup' else
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
        'PASS: debug/minified helper wait, timeout recovery and expired resume, ordinary framework/HOME/STOPPED relaunch and resource/preconfiguration/running/finish probes; recipient keeps focus until user entry; debug-only installed-resource startup checkpoint; 5 s destruction bound, saved-state exit or native return/join, no second main, clean next entry.\n')
    assert not failures, '\n'.join(failures)
    h.start_entry('HomeEntry', 'android.intent.category.HOME')
    h.configured_system('lifecycle-restored-home')
