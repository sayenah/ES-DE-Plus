#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real predictive-back cancellation over pending ASSETS.
import re
import struct
import threading
import time


def preview_evidence(logs, app):
    # Android 13 reads the opt-in from ApplicationInfo, not ActivityInfo. The
    # CI stub must opt in at application level to get the system callback;
    # TYPE_CALLBACK from its compat callback is a probe failure, not N/A.
    # https://android.googlesource.com/platform/frameworks/base/+/android-13.0.0_r1/core/java/android/window/WindowOnBackInvokedDispatcher.java#285
    lines = logs.splitlines()
    callback = next((line for line in reversed(lines) if 'startBackNavigation currentTask=' in line), '')
    navigation = next((line for line in reversed(lines) if 'Received backNavigationInfo:' in line), '')
    behind = next((line for line in reversed(lines) if 'Setting Activity.mLauncherTaskBehind to true.' in line), '')
    assert 'org.esdeplus.stub/' in callback and 'PredictiveBackActivity' in callback, callback
    assert re.search(r'\bmPriority=-1(?=[,}])', callback), 'Probe lacks system Back callback: ' + callback
    assert 'mType=TYPE_RETURN_TO_HOME (1)' in navigation, 'Probe lacks return-to-HOME preview: ' + navigation
    assert re.search(re.escape(app) + r'/(?:\.|' + re.escape(app) + r'\.)HomeEntry\b', behind), \
        'Probe lacks frontend HOME launch-behind: ' + behind
    return '\n'.join((callback, behind, navigation)) + '\n'


def controls():
    callback = ('startBackNavigation currentTask=Task{game}, '
                'topRunningActivity=ActivityRecord{game u0 org.esdeplus.stub/.PredictiveBackActivity}, '
                'callbackInfo=OnBackInvokedCallbackInfo{mPriority=-1}')
    behind = ('Setting Activity.mLauncherTaskBehind to true. '
              'Activity=ActivityRecord{home u0 org.esdeplus.frontend/.HomeEntry} t10}')
    navigation = 'Received backNavigationInfo:BackNavigationInfo{mType=TYPE_RETURN_TO_HOME (1)}'
    logs = '\n'.join((callback, behind, navigation))
    preview_evidence(logs, 'org.esdeplus.frontend')
    mutants = [logs.replace(old, new) for old, new in (
        ('mPriority=-1', 'mPriority=0'), ('mPriority=-1', 'mPriority=-10'),
        ('TYPE_RETURN_TO_HOME (1)', 'TYPE_CALLBACK (4)'),
        ('org.esdeplus.stub/', 'other.game/'), ('PredictiveBackActivity', 'RecipientActivity'),
        ('org.esdeplus.frontend/', 'other.home/'), ('.HomeEntry', '.MainActivity'))]
    mutants += [logs.replace(line, '') for line in (callback, behind, navigation)]
    mutants += [logs + '\n' + navigation.replace('TYPE_RETURN_TO_HOME (1)', 'TYPE_CALLBACK (4)'),
                logs + '\n' + callback.replace('mPriority=-1', 'mPriority=0')]
    for mutant in mutants:
        try:
            preview_evidence(mutant, 'org.esdeplus.frontend')
        except AssertionError:
            pass
        else:
            raise AssertionError('Missing or compat-only preview evidence escaped')
    return f'PASS: {len(mutants)} missing/wrong/stale preview records rejected; system callback, return-to-HOME and HOME launch-behind required on both phones\n'


def run(harness):
    h = type('Harness', (), harness)
    name = 'assets-back-cancel'
    if h.api < 33 or h.television:
        reason = ('Predictive Back was introduced in API 33; absent on API ' + str(h.api)
                  if h.api < 33 else 'TV has no edge-back gesture navigation')
        (h.evidence / (name + '-result.txt')).write_text('NOT APPLICABLE: ' + reason + '\n')
        return 'back-cancel: NOT APPLICABLE: ' + reason

    import forced_relaunch_smoke
    import lifecycle_smoke
    overlay = 'org.esdeplus.relaunchprobe'
    _, original_home = lifecycle_smoke.resolved_home(h)
    if 'ResolverActivity' in original_home:
        candidates = h.shell('cmd', 'package', 'query-activities', '--brief', '-a', 'android.intent.action.MAIN',
                             '-c', 'android.intent.category.HOME')
        original_home = next(line.strip() for line in candidates.splitlines() if
                             line.strip().startswith(h.stock_package + '/') and ' ' not in line.strip())
    settings = {key: h.shell('settings', 'get', 'global', key).strip() for key in
                ('enable_back_animation', 'window_animation_scale', 'transition_animation_scale', 'animator_duration_scale')}
    overlays = h.shell('cmd', 'overlay', 'list', '--user', 'current')
    original_navigation = next((m.group(1) for line in overlays.splitlines()
                                if (m := re.match(r'\[x\] (com\.android\.internal\.systemui\.navbar\.\S+)', line))), None)
    assert original_navigation, overlays
    stop = threading.Event()
    samples = []
    errors = []
    monitor = None
    pointer_down = False

    def capture(stage):
        h.save_logs(name + '-' + stage)
        (h.evidence / (name + '-' + stage + '-activities.txt')).write_text(h.activity_records()[0])
        (h.evidence / (name + '-' + stage + '-window.txt')).write_text(h.focused_window())
        h.screenshot(name + '-' + stage)

    def game_focused():
        window = h.focused_window()
        samples.append(f'{time.monotonic():.3f}: {window}')
        assert h.smoke_checks.package_window_focused(window, 'org.esdeplus.stub'), window

    def sample_focus():
        try:
            while not stop.is_set():
                game_focused()
                stop.wait(0.25)
        except Exception as error:
            errors.append(str(error))

    try:
        h.shell('am', 'force-stop', h.app)
        h.shell('am', 'force-stop', 'org.esdeplus.stub')
        h.shell('cmd', 'overlay', 'disable', overlay)
        for key in settings:
            h.shell('settings', 'put', 'global', key, '1')
        back_animation = h.shell('settings', 'get', 'global', 'enable_back_animation').strip()
        assert back_animation == '1', 'Predictive Back developer option was not enabled: ' + back_animation
        h.shell('cmd', 'overlay', 'enable-exclusive', '--category', 'com.android.internal.systemui.navbar.gestural')
        h.wait_for(lambda: h.shell('settings', 'get', 'secure', 'navigation_mode').strip() == '2',
                   name + ' gesture navigation active', timeout=30)
        selected = h.shell('cmd', 'package', 'set-home-activity', h.app + '/org.esdeplus.frontend.HomeEntry')
        assert 'Success' in selected, selected
        assert lifecycle_smoke.resolved_home(h)[1] == h.app + '/org.esdeplus.frontend.HomeEntry'
        (h.evidence / (name + '-preconditions.txt')).write_text(
            h.shell('cmd', 'overlay', 'list') + '\n' + '\n'.join(
                key + '=' + h.shell('settings', 'get', 'global', key).strip() for key in settings))
        h.adb('logcat', '-c')
        h.shell('am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME', '-p', h.app)
        h.configured_system(name + '-before')
        dump, records = h.activity_records()
        assert lifecycle_smoke.home_record(dump, records), dump
        record = records[0][2]
        old = h.shell('pidof', h.app).strip()
        before = h.log()
        h.shell('am', 'start', '-n', 'org.esdeplus.stub/.PredictiveBackActivity')
        h.wait_for(lambda: forced_relaunch_smoke.frontend_stopped(h.activity_records()[0], record) and
                   h.smoke_checks.package_window_focused(h.focused_window(), 'org.esdeplus.stub'),
                   name + ' HOME frontend STOPPED behind game', timeout=30)
        game_focused()
        capture('before-overlay')
        monitor = threading.Thread(target=sample_focus)
        monitor.start()
        h.shell('cmd', 'overlay', 'enable', overlay)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            game_focused()
            assert 'Destroying SDL activity' not in h.adb('logcat', '-d'), 'ASSETS was not deferred while stopped'
            time.sleep(0.25)
        capture('pending')
        # With the CI game's application-level opt-in, Android 13 and 14 use
        # the system callback and can launch HOME behind this gesture. Require
        # the real platform path and ASSETS recreation; neither app is instrumented.
        png = h.adb('exec-out', 'screencap', '-p', binary=True)
        width, height = struct.unpack('>II', png[16:24])
        y = height // 2
        h.shell('input', 'touchscreen', 'motionevent', 'DOWN', '1', str(y))
        pointer_down = True
        for x in (width // 40, width // 15, width // 8, width // 5):
            h.shell('input', 'touchscreen', 'motionevent', 'MOVE', str(x), str(y))
        h.wait_for(lambda: 'Recreated frontend waiting for committed entry' in h.adb('logcat', '-d'),
                   name + ' real launch-behind ASSETS recreation', timeout=30)
        logs = h.adb('logcat', '-d', '-v', 'threadtime')
        (h.evidence / (name + '-platform.txt')).write_text(preview_evidence(logs, h.app))
        forced_relaunch_smoke.destruction_evidence(logs, old)
        assert 'SDL activity destroy join returned' in logs, 'Old native main did not return/join'
        assert not re.search(r'START .*FrontendRestartActivity', logs), 'Helper started during back preview'
        capture('preview')
        h.shell('input', 'touchscreen', 'motionevent', 'CANCEL')
        pointer_down = False
        until = time.monotonic() + 5
        while time.monotonic() < until:
            game_focused()
            logs = h.adb('logcat', '-d')
            assert not re.search(r'START .*FrontendRestartActivity', logs), 'Helper started after cancelled back'
            assert logs.count('Running main function') == 1, 'Native main restarted in retired VM'
            assert h.shell('pidof', h.app).strip() == old, 'Pending gate lost its process'
            time.sleep(0.25)
        stop.set()
        monitor.join(timeout=30)
        assert not monitor.is_alive() and not errors, errors
        assert len(samples) >= 20, len(samples)
        capture('cancelled')
        # A later, committed user Back must still restore through the helper.
        h.key('KEYCODE_BACK')
        h.wait_for(lambda: f'SDL process {old} retired; restarting entry' in h.adb('logcat', '-d'),
                   name + ' committed Back helper restoration', timeout=30)
        forced_relaunch_smoke.restoration_evidence(h.adb('logcat', '-d', '-v', 'threadtime'), old)
        h.wait_for(lambda: h.shell('pidof', h.app, check=False).strip().isdigit() and
                   h.shell('pidof', h.app).strip() != old and
                   h.log().splitlines()[:1] != before.splitlines()[:1] and 'Application startup time:' in h.log(),
                   name + ' committed entry completed startup', timeout=90)
        h.configured_system(name + '-committed')
        assert lifecycle_smoke.home_record(*h.activity_records()), 'Committed return lost HOME semantics'
        capture('result')
        result = f'PASS: actual ASSETS launch-behind; cancelled Back retained game focus in {len(samples)} samples; no helper or second native main; later committed Back restored HOME through helper.\n'
        (h.evidence / (name + '-result.txt')).write_text(result)
        return 'back-cancel: ' + result.strip()
    except Exception as error:
        capture('failure')
        (h.evidence / (name + '-result.txt')).write_text('FAIL: ' + str(error) + '\n')
        raise
    finally:
        stop.set()
        if monitor is not None:
            monitor.join(timeout=30)
        (h.evidence / (name + '-recipient-focus.txt')).write_text('\n'.join(samples) + '\n')
        if pointer_down:
            h.shell('input', 'touchscreen', 'motionevent', 'CANCEL')
        h.shell('am', 'force-stop', h.app)
        h.shell('am', 'force-stop', 'org.esdeplus.stub')
        h.shell('cmd', 'overlay', 'disable', overlay)
        h.shell('cmd', 'package', 'set-home-activity', original_home)
        h.shell('cmd', 'overlay', 'enable-exclusive', '--category', original_navigation)
        for key, value in settings.items():
            if value == 'null':
                h.shell('settings', 'delete', 'global', key)
            else:
                h.shell('settings', 'put', 'global', key, value)
