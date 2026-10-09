#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Exercises the real installed frontend with adb.
import pathlib
import re
import select
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import smoke_checks
import launch_checks
import json
import os
import tempfile

apk = pathlib.Path(sys.argv[1]).resolve()
app = next(line.split('=', 1)[1] for line in pathlib.Path('android/gradle.properties').read_text().splitlines()
           if line.startswith('esde.applicationId='))
activity = app + '/org.esdeplus.frontend.MainActivity'
label = ET.parse('android/app/src/main/res/values/strings.xml').find("string[@name='app_name']").text
evidence = pathlib.Path('android/evidence')
evidence.mkdir(parents=True, exist_ok=True)
(evidence / 'followups-assertion-positive-controls.txt').write_text(smoke_checks.positive_controls())
(evidence / 'launch-assertion-positive-controls.txt').write_text(launch_checks.positive_controls())
external = f'/sdcard/Android/data/{app}/files'
roms = external + '/ROMs'
logpath = external + '/ES-DE-Plus/logs/es_log.txt'
settings = external + '/ES-DE-Plus/settings/es_settings.xml'
startup_baseline = ''
stock_package = 'com.google.android.tvlauncher'
onboarding_guard = False
dismissing_onboarding = False
last_onboarding_check = 0.0


def adb(*args, check=True, binary=False):
    # Retry only read-only log collection after a transient transport closure.
    # UI actions, process changes and assertions are never replayed here.
    for attempt in range(3 if args[:2] == ('logcat', '-d') else 1):
        result = subprocess.run(['adb', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=not binary, timeout=90)
        if not result.returncode:
            break
        if args[:2] == ('logcat', '-d'):
            with (evidence / 'logcat-transport-retries.txt').open('a') as output:
                output.write(f'Attempt {attempt + 1}: exit {result.returncode}; {result.stderr}\n')
            time.sleep(1)
    if check and result.returncode:
        print(result.stderr.decode(errors='replace') if binary else result.stderr, file=sys.stderr)
        result.check_returncode()
    return result.stdout


def shell(*args, check=True):
    # adb shell joins arguments without escaping, including arguments to sh -c.
    return adb('shell', shlex.join(args), check=check)


def instrument_with_ui(*arguments):
    # The retained-window probe waits inside instrumentation. Keep inspecting
    # actual system UI during that wait so the existing external-ANR handler
    # can dismiss a crashed stock launcher. Frontend ANRs still fail, and the
    # instrumentation assertions, activity state and deadline are unchanged.
    with tempfile.TemporaryFile(mode='w+t') as output, tempfile.TemporaryFile(mode='w+t') as errors:
        process = subprocess.Popen(['adb', 'shell', shlex.join(arguments)], stdout=output, stderr=errors)
        deadline = time.monotonic() + 90
        try:
            while process.poll() is None:
                hierarchy()
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(process.args, 90)
                time.sleep(0.25)
            output.seek(0)
            errors.seek(0)
            result = subprocess.CompletedProcess(process.args, process.returncode, output.read(), errors.read())
            result.check_returncode()
            return result.stdout
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def private(*args, check=True):
    if args and args[0] == 'test':
        # test is a shell builtin; older Android images need not ship an
        # executable applet that run-as can exec directly.
        return shell('run-as', app, 'sh', '-c', shlex.join(args), check=check)
    return shell('run-as', app, *args, check=check)


def wait_for(condition, description, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if timeout >= 30:
            dismiss_stock_onboarding()
        if condition():
            return
        time.sleep(0.25)
    raise AssertionError('Timed out: ' + description)


def log():
    return shell('cat', logpath, check=False)


def screenshot(name):
    # Give menu transitions and their cached backdrops time to finish rendering.
    time.sleep(5)
    (evidence / (name + '.png')).write_bytes(adb('exec-out', 'screencap', '-p', binary=True))


def launch():
    # Each stopped-process restart must produce new startup evidence.
    global startup_baseline
    startup_baseline = log()
    shell('am', 'start', '-n', activity)
    wait_for(lambda: log() != startup_baseline and 'Application startup time:' in log(), 'fresh frontend startup/system loading')
    assert 'Error:' not in log(), log()
    assert re.search(r'Total game count: 2\s', log()), 'The two adb-provisioned ROMs were not loaded: ' + log()
    # Startup logging precedes the render loop's first frame/texture uploads.
    time.sleep(10)
    # Dismiss the real Android immersive-mode tutorial through its actual UI.
    wait_for(lambda: bool(hierarchy()), 'frontend UI hierarchy')
    if any(node.get('text') == 'Got it' for node in hierarchy()):
        ui('Got it')


def save_logs(name):
    (evidence / (name + '-es_log.txt')).write_text(log())
    (evidence / (name + '-logcat.txt')).write_text(adb('logcat', '-d', '-v', 'threadtime'))


def key(code):
    shell('input', 'keyevent', code)
    time.sleep(0.4)


def hierarchy():
    location = '/data/local/tmp/esde-smoke-window.xml'
    shell('rm', '-f', location)
    dump = shell('uiautomator', 'dump', location, check=False)
    xml = shell('cat', location, check=False)
    if not xml.strip().startswith('<?xml'):
        with (evidence / 'ui-dump-retries.txt').open('a') as output:
            output.write(dump + '\n')
        return []
    (evidence / 'latest-ui.txt').write_text(xml)
    nodes = list(ET.fromstring(xml).iter('node'))
    anr = next((n.get('text', '') for n in nodes if n.get('resource-id') == 'android:id/alertTitle' and
                "isn't responding" in n.get('text', '')), None)
    if anr:
        assert label.casefold() not in anr.casefold(), 'Frontend ANR: ' + anr
        # A system launcher ANR can obscure a healthy foreground activity.
        # Record and close that external process through its real dialog.
        screenshot('external-process-anr')
        with (evidence / 'external-process-anr.txt').open('a') as output:
            output.write(anr + '\n')
        close = next(n for n in nodes if n.get('resource-id') == 'android:id/aerr_close')
        x1, y1, x2, y2 = map(int, re.findall(r'\d+', close.attrib['bounds']))
        shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
        time.sleep(1)
        return hierarchy()
    return nodes


def node_matches(node, label):
    return label.casefold() in node.get('text', '').casefold() or label.casefold() in node.get('content-desc', '').casefold()


def dismiss_stock_onboarding(force=False):
    global dismissing_onboarding, last_onboarding_check
    if not onboarding_guard or dismissing_onboarding:
        return
    if not force and time.monotonic() - last_onboarding_check < 2:
        return
    last_onboarding_check = time.monotonic()
    window = shell('dumpsys', 'window', 'windows')
    if not smoke_checks.stock_onboarding_focused(window, stock_package):
        return
    dismissing_onboarding = True
    try:
        nodes = hierarchy()
        smoke_checks.probe_passed('Dismiss' if any(n.get('package') == stock_package and
            n.get('text') == 'Dismiss' for n in nodes) else '', 'Dismiss')
        with (evidence / 'tv-onboarding-events.txt').open('a') as output:
            output.write('Actual focused stock ShowDialogsActivity; dismissing external onboarding only.\n' +
                         window + '\n' + (evidence / 'latest-ui.txt').read_text() + '\n')
        screenshot('tv-onboarding-before-dismiss')
        ui('Dismiss')
        smoke_checks.onboarding_clear(hierarchy(), stock_package, app)
        screenshot('tv-onboarding-dismissed')
        # No frontend launch, task focus change, process restart or assertion
        # retry is performed. The original condition still has to pass.
    finally:
        dismissing_onboarding = False


def ui(label, dpad=False):
    if dpad:
        wait_for(lambda: any(n.get('package') == app for n in hierarchy()), 'configurator before D-pad navigation')
        direction = 'KEYCODE_DPAD_DOWN'
        last_focus = None
        for _ in range(50):
            nodes = hierarchy()
            if any(node_matches(n, label) and n.get('focused') == 'true' for n in nodes):
                key('KEYCODE_DPAD_CENTER')
                return
            focused = next((n for n in nodes if n.get('focused') == 'true'), None)
            target = next((n for n in nodes if node_matches(n, label) and n.get('focusable') == 'true'), None)
            if focused is not None and target is not None:
                current_y = sum(map(int, re.findall(r'\d+', focused.attrib['bounds'])[1::2]))
                target_y = sum(map(int, re.findall(r'\d+', target.attrib['bounds'])[1::2]))
                direction = 'KEYCODE_DPAD_UP' if target_y < current_y else 'KEYCODE_DPAD_DOWN'
            elif focused is not None and focused.attrib == last_focus:
                direction = 'KEYCODE_DPAD_UP' if direction == 'KEYCODE_DPAD_DOWN' else 'KEYCODE_DPAD_DOWN'
            last_focus = focused.attrib.copy() if focused is not None else None
            key(direction)
        raise AssertionError('D-pad cannot reach: ' + label)
    wait_for(lambda: any(node_matches(n, label) for n in hierarchy()), 'UI: ' + label)
    nodes = hierarchy()
    exact = [n for n in nodes if n.get('text', '').casefold() == label.casefold() or
             n.get('content-desc', '').casefold() == label.casefold()]
    node = exact[0] if exact else next(n for n in nodes if node_matches(n, label))
    x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.attrib['bounds']))
    shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
    time.sleep(1)


def start_entry(name='MainActivity', category='android.intent.category.LAUNCHER'):
    global startup_baseline
    if not shell('pidof', app, check=False).strip():
        startup_baseline = log()
    shell('am', 'start', '-a', 'android.intent.action.MAIN', '-c', category,
          '-n', app + '/org.esdeplus.frontend.' + name)


def resolved_component(action, data=None):
    args = ['cmd', 'package', 'resolve-activity', '--brief', '-a', action]
    if data:
        args += ['-d', data]
    result = shell(*args, check=False)
    return next((line.strip() for line in result.splitlines() if '/' in line and ' ' not in line.strip()), None)


def permission_row(app_label=None):
    # Phone settings can show one app; TV settings can show a list of apps.
    # Select the switch in the smallest subtree containing our exact app label.
    candidates = []
    for parent in hierarchy():
        children = list(parent.iter('node'))
        switches = [n for n in children if n.get('checkable') == 'true']
        if len(switches) == 1 and any(n.get('text', '').casefold() == (app_label or label).casefold() for n in children):
            candidates.append((len(children), parent))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def permission_toggle(app_label=None):
    row = permission_row(app_label)
    return next(n for n in row.iter('node') if n.get('checkable') == 'true') if row is not None else None


def grant_from_settings(app_label=None, recipient=False):
    # Both app-specific and generic Settings are opened by the application.
    # A generic phone list needs its real app row; TV exposes switches inline.
    wait_for(lambda: bool(hierarchy()), 'all-files Settings UI')
    if permission_toggle(app_label) is None:
        ui(app_label or label)
    wait_for(lambda: permission_toggle(app_label) is not None, 'app-associated all-files switch')
    if recipient and permission_toggle(app_label).get('checked') == 'true':
        screenshot('recipient-all-files-already-granted')
        key('KEYCODE_BACK')
        return
    if television:
        for _ in range(40):
            row = permission_row(app_label)
            focused = row is not None and any(n.get('focused') == 'true' for n in row.iter('node'))
            if focused:
                screenshot('tv-all-files-switch-focused')
                key('KEYCODE_DPAD_CENTER')
                break
            key('KEYCODE_DPAD_DOWN')
        else:
            raise AssertionError('TV D-pad cannot reach our all-files switch')
    else:
        toggle = permission_toggle(app_label)
        x1, y1, x2, y2 = map(int, re.findall(r'\d+', toggle.attrib['bounds']))
        shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
    wait_for(lambda: permission_toggle(app_label) is not None and permission_toggle(app_label).get('checked') == 'true',
             'real app all-files grant')
    screenshot('recipient-all-files-granted' if recipient else 'all-files-granted')
    key('KEYCODE_BACK')
    if recipient:
        return
    if not any(n.get('package') == app for n in hierarchy()):
        key('KEYCODE_BACK')
    wait_for(lambda: any(node_matches(n, 'Choose shared ROM folder') for n in hierarchy()),
             'configurator returned from all-files Settings')


def activity_records():
    dump = shell('dumpsys', 'activity', 'activities')
    records = []
    for record in re.findall(r'Hist\s+#\d+: ActivityRecord\{([^}]+)\}', dump):
        match = re.search(r'\bu\d+ ' + re.escape(app) + r'/([^\s]+) t(\d+)', record)
        if match:
            records.append((match[1].rsplit('.', 1)[-1], match[2], record))
    return dump, records


def select_tree(folder):
    nodes = hierarchy()
    if not any(n.get('text') == folder for n in nodes):
        ui('Show roots')
        nodes = hierarchy()
        root = next((n for n in nodes if n.get('text') in ['Internal storage', 'Internal shared storage', shell('getprop', 'ro.product.model').strip()]), None)
        if root is None:
            root = next(n for n in nodes if n.get('resource-id', '').endswith('title') and n.get('text', '') not in ['Downloads', 'Recent', 'Images', 'Videos', 'Audio', 'Documents', 'Drive', 'Open from'])
        ui(root.get('text'))
    ui(folder)
    confirmation = next(n for n in hierarchy() if n.get('enabled') == 'true' and
                        ('use this folder' in n.get('text', '').casefold() or
                         'allow access to' in n.get('text', '').casefold()))
    ui(confirmation.get('text'))
    if any(n.get('text', '').casefold() == 'allow' for n in hierarchy()):
        ui('Allow')


def grant_count(expected):
    counts = re.findall(r'Persisted tree grant count=(\d+)', adb('logcat', '-d'))
    return bool(counts) and int(counts[-1]) == expected


def cancelled_grant_retained():
    counts = re.findall(r'Persisted tree grant count=(\d+)', adb('logcat', '-d'))
    smoke_checks.grants(int(counts[-1]) if counts else None, 1)


def destroy_held(name):
    dump, records = activity_records()
    assert any(r[0] == 'ConfiguratorActivity' for r in records), dump
    assert len({r[1] for r in records}) == 1 and len(records) == 2, dump
    (evidence / (name + '-before-activities.txt')).write_text(dump)
    old_pid = shell('pidof', app).strip()
    adb('logcat', '-c')
    started = time.monotonic()
    # Clear the actual HOME frontend/configurator task through ActivityManager.
    # The exported entry is used; no test-only finish or native quit injection.
    result = shell('am', 'start', '-f', '0x10008000',
                   '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME',
                   '-n', app + '/org.esdeplus.frontend.HomeEntry')
    wait_for(lambda: shell('pidof', app, check=False).strip() != old_pid,
             'held native host ends on actual Activity destruction', timeout=5)
    elapsed = time.monotonic() - started
    # pidof may observe process teardown before logcat delivers its last write.
    # Keep the real five-second process bound and wait separately for evidence.
    wait_for(lambda: any('SDL_QUIT observed during configuration hold; ending process' in line and
                         re.search(r'\s' + old_pid + r'\s', line)
                         for line in adb('logcat', '-d', '-v', 'threadtime').splitlines()),
             'old process SDL_QUIT diagnostic delivered', timeout=5)
    output = adb('logcat', '-d', '-v', 'threadtime')
    old_lines = '\n'.join(line for line in output.splitlines() if re.search(r'\s' + old_pid + r'\s', line))
    assert 'Destroying SDL activity held=true' in old_lines, output
    assert 'SDL_QUIT observed during configuration hold; ending process' in old_lines, output
    assert 'Configurator draft saved' in old_lines, output
    assert old_lines.index('Configurator draft saved') < old_lines.index('SDL_QUIT observed'), output
    assert 'ANR in ' + app not in output and 'JNI DETECTED ERROR' not in output, output
    (evidence / (name + '-destroy.txt')).write_text(
        f'Actual am task clear: {result}\nOld PID {old_pid}; exited in {elapsed:.3f}s.\n' + output)
    # _exit ends the entire process, including the pending UI join; a post-join
    # Java callback is not claimed on this path. Normal quits still assert it.
    start_entry('HomeEntry', 'android.intent.category.HOME')
    def restored():
        try:
            smoke_checks.held_restored(activity_records()[1], hierarchy(), shell('pidof', app).strip(), old_pid, app)
            return True
        except AssertionError:
            return False
    wait_for(restored, 'held configuration restored on a new host in the same task')
    (evidence / (name + '-restored-activities.txt')).write_text(activity_records()[0])
    screenshot(name + '-restored')
    save_logs(name + '-restored')


def real_system_home():
    global startup_baseline
    resolved = shell('cmd', 'package', 'resolve-activity', '--brief', '-a', 'android.intent.action.MAIN',
                     '-c', 'android.intent.category.HOME')
    original = next(line.strip() for line in resolved.splitlines() if '/' in line and ' ' not in line.strip())
    candidates = shell('cmd', 'package', 'query-activities', '--brief',
                       '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME')
    stock = next(line.strip() for line in candidates.splitlines() if '/' in line and
                 ' ' not in line.strip() and not line.strip().startswith(app + '/') and
                 'ResolverActivity' not in line)
    # Installing a second HOME candidate can leave the fresh image at the
    # chooser. Record an explicit stock baseline instead of treating the
    # chooser as a launcher or pretending it can be restored as the default.
    baseline = resolved + '\n' + candidates
    if 'ResolverActivity' in original:
        original = stock
        baseline += '\nEstablish stock HOME baseline: ' + shell('cmd', 'package', 'set-home-activity', stock)
    (evidence / 'system-home-stock-baseline.txt').write_text(baseline)
    shell('am', 'force-stop', app)
    startup_baseline = log()
    adb('logcat', '-c')
    try:
        changed = shell('cmd', 'package', 'set-home-activity', app + '/org.esdeplus.frontend.HomeEntry')
        assert 'Success' in changed, changed
        # Open the real stock drawer, then tap this application's launcher icon.
        shell('am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME', '-n', stock)
        width, height = map(int, re.findall(r'(\d+)x(\d+)', shell('wm', 'size'))[-1])
        shell('input', 'swipe', str(width // 2), str(height - 100), str(width // 2), '100', '500')
        ui(label)
        configured_system('system-home-drawer-launch')
        pid = shell('pidof', app).strip()
        before, records = activity_records()
        assert len(records) == 1 and records[0][0] == 'MainActivity', before
        assert re.search(r'Task\{[^}\n]+ #' + records[0][1] + r'\b[^}\n]*type=standard', before), before
        assert 'HOME=false' in adb('logcat', '-d'), 'Drawer launch did not clear HOME'
        (evidence / 'system-home-before-activities.txt').write_text(before)
        adb('logcat', '-c')
        key('KEYCODE_HOME')
        wait_for(lambda: 'HOME=true' in adb('logcat', '-d') and len(activity_records()[1]) == 1,
                 'system HOME forwards to sole SDL instance')
        after, current = activity_records()
        assert current[0][1:] == records[0][1:], (before, after)
        assert shell('pidof', app).strip() == pid, 'System HOME changed PID'
        output = adb('logcat', '-d', '-v', 'threadtime')
        assert 'Creating sole SDL activity' not in output and 'Running main function' not in output, output
        assert 'Focused redirect forwarding entry to sole SDL activity' in output or 'SDL entry reused via onNewIntent' in output, output
        (evidence / 'system-home-after-activities.txt').write_text(after)
        (evidence / 'system-home-set-default.txt').write_text(changed + '\n' + output)
        def frontend_focused():
            window = shell('dumpsys', 'window', '-a')
            (evidence / 'system-home-current-window.txt').write_text(window)
            return re.search(r'mCurrentFocus=.* ' + re.escape(app) + r'/', window)
        wait_for(frontend_focused, 'system HOME handoff restores frontend window focus', timeout=30)
        screenshot('system-home-reused')
        key('KEYCODE_BACK')
        assert shell('pidof', app).strip() == pid, 'System HOME Back ended the frontend process'
        resumed = 'topResumedActivity=ActivityRecord{' + records[0][2] + '}'
        wait_for(lambda: resumed in activity_records()[0],
                 'system HOME Back retains resumed frontend activity', timeout=30)
        back_dump, back_records = activity_records()
        assert len(back_records) == 1 and back_records[0][1:] == records[0][1:], back_dump
        wait_for(frontend_focused, 'system HOME Back retains focused frontend window', timeout=30)
        focus = shell('dumpsys', 'window')
        assert re.search(r'mCurrentFocus=.* ' + re.escape(app) + r'/', focus), focus
        (evidence / 'system-home-back-activities.txt').write_text(back_dump)
        (evidence / 'system-home-back-window.txt').write_text(focus)
        screenshot('system-home-back')
        save_logs('system-home-back')
        assert 'ANR in ' + app not in adb('logcat', '-d'), 'System HOME handoff caused a frontend ANR'
    finally:
        restored = shell('cmd', 'package', 'set-home-activity', original)
        (evidence / 'system-home-default-restored.txt').write_text(original + '\n' + restored)
        assert 'Success' in restored, restored


def component_enabled(component, enabled):
    # Only PackageManager component availability is changed by privileged adbd.
    # Grants/configuration are never injected; return to the ordinary shell
    # before any user flow or file-provisioning evidence.
    root = adb('root', check=False)
    adb('wait-for-device')
    if 'cannot run as root' in root:
        with (evidence / 'capability-controls.txt').open('a') as output:
            output.write(f'Component availability control unavailable: {root.strip()}; actual capability UX exercised without privilege.\n')
        assert shell('id', '-u').strip() == '2000'
        return False
    wait_for(lambda: shell('id', '-u', check=False).strip() == '0', 'privileged capability control shell')
    try:
        user = shell('am', 'get-current-user').strip()
        change = shell('pm', 'enable' if enabled else 'disable', '--user', user, component)
        assert 'new state: ' + ('enabled' if enabled else 'disabled') in change, change
    finally:
        adb('unroot', check=False)
        adb('wait-for-device')
    wait_for(lambda: shell('id', '-u', check=False).strip() == '2000', 'ordinary shell after capability control')
    with (evidence / 'capability-controls.txt').open('a') as output:
        output.write(f'{change.strip()}; adbd restored to UID 2000. No permission/configuration injection.\n')
    return True


def owned_fixture(action, directory):
    result = shell('am', 'instrument', '-w', '-e', 'mode', 'owned-fixture',
                   '-e', 'action', action, '-e', 'directory', directory,
                   app + '/org.esdeplus.frontend.RuntimeSmoke')
    assert f'PASS: SDK-context owned fixture {action} {directory}' in result, result
    with (evidence / 'owned-fixtures.txt').open('a') as output:
        output.write(result)
    shell('am', 'force-stop', app)


def clear_app():
    shell('am', 'force-stop', app)
    shell('pm', 'clear', app)
    wait_for(lambda: not shell('pidof', app, check=False).strip(), 'cleared app process stopped')
    # PackageManager removes old tasks asynchronously; starting immediately
    # can let that cleanup kill the new process as part of the old task.
    time.sleep(1)


def configured_system(name):
    wait_for(lambda: log() != startup_baseline and 'Application startup time:' in log(), 'fresh configured system view')
    assert 'Error:' not in log(), log()
    assert re.search(r'Total game count: 2\s', log()), log()
    time.sleep(10)
    if any(n.get('text') == 'Got it' for n in hierarchy()):
        ui('Got it')
    screenshot(name)
    save_logs(name)


def launch_contract_probes(mode):
    if api >= 30 and mode.startswith('direct'):
        # A raw-path emulator needs its own explicitly granted filesystem
        # permission. Drive the recipient's real Settings flow under its UID;
        # provider grants are tested separately and never widened.
        shell('am', 'start', '-n', 'org.esdeplus.stub/.RecipientActivity',
              '--es', 'queryMode', 'storage-permission')
        grant_from_settings('ES-DE Plus recipient', recipient=True)
        (evidence / ('recipient-filesystem-permission-' + mode + '.txt')).write_text(
            'Recipient opened its own all-files Settings; actual app-associated switch selected.\n' +
            shell('appops', 'get', '--uid', 'org.esdeplus.stub', 'MANAGE_EXTERNAL_STORAGE'))
    shell('am', 'force-stop', app)
    adb('logcat', '-c')
    result = shell('am', 'instrument', '-w', '-e', 'mode', 'launch-probe',
                   app + '/org.esdeplus.frontend.RuntimeSmoke')
    (evidence / ('launch-contract-' + mode + '.txt')).write_text(result)
    smoke_checks.probe_passed(result,
        'PASS: PR-C launch/discovery/provider/query probes; assertion positive controls rejected')
    (evidence / ('launch-contract-' + mode + '-logcat.txt')).write_text(adb('logcat', '-d', '-v', 'threadtime'))
    shell('am', 'force-stop', 'org.esdeplus.stub')
    shell('am', 'force-stop', app)
    launch()
    screenshot('launch-contract-' + mode + '-returned-frontend')
    save_logs('launch-contract-' + mode + '-returned-frontend')
    gamelist_recipient_flow(mode)


def search_launch(term):
    key('KEYCODE_ESCAPE')
    key('KEYCODE_ENTER')
    shell('input', 'text', term)
    key('KEYCODE_ENTER')
    key('KEYCODE_DPAD_DOWN')
    key('KEYCODE_ENTER')


def gamelist_recipient_flow(mode):
    custom = external + '/ES-DE-Plus/custom_systems'
    user_root = shared if mode.startswith('direct') else roms
    temporary = evidence / 'launch-custom'
    temporary.mkdir(exist_ok=True)
    systems = ET.Element('systemList')
    for name, command in [('nes', '%EMULATOR_PROBE% %ACTION%=android.intent.action.VIEW %CATEGORY%=android.intent.category.DEFAULT '
                           '%MIMETYPE%=application/octet-stream %DATA%=%ROMPROVIDER% %EXTRA_literal%=雪 '
                           '%EXTRAARRAY_words%="one,t\\,wo,雪" %EXTRAINTEGER_number%=-2147483648 '
                           '%EXTRABOOL_yes%=1 %EXTRABOOL_no%=false %ACTIVITY_CLEAR_TOP% %ACTIVITY_NO_HISTORY%'),
                          ('androidapps', '%ANDROIDAPP%=%FILEINJECT%')]:
        system = ET.SubElement(systems, 'system')
        for tag, value in [('name', name), ('fullname', name), ('path', '%ROMPATH%/' + name),
                           ('extension', '.nes' if name == 'nes' else '.app'), ('command', command),
                           ('platform', name), ('theme', name)]:
            ET.SubElement(system, tag).text = value
    ET.ElementTree(systems).write(temporary / 'es_systems.xml', encoding='utf-8', xml_declaration=True)
    rules = ET.Element('ruleList')
    emulator = ET.SubElement(rules, 'emulator', name='PROBE')
    rule = ET.SubElement(emulator, 'rule', type='androidpackage')
    ET.SubElement(rule, 'entry').text = 'org.esdeplus.stub/.RecipientActivity'
    ET.ElementTree(rules).write(temporary / 'es_find_rules.xml', encoding='utf-8', xml_declaration=True)
    shell('am', 'force-stop', app)
    shell('mkdir', '-p', custom)
    for name in ['es_systems.xml', 'es_find_rules.xml']:
        adb('push', str(temporary / name), custom + '/' + name)
        (evidence / (mode + '-' + name + '.txt')).write_text((temporary / name).read_text())
    def start_custom():
        shell('am', 'force-stop', app)
        adb('logcat', '-c')
        launch()
    def failed_target(name):
        start_custom()
        search_launch('Smoke')
        wait_for(lambda: "Couldn't launch game, emulator not found" in log(), name + ' target visible error')
        screenshot(mode + '-' + name + '-target-error')
        save_logs(mode + '-' + name + '-target-error')
        launch_checks.equal(bool(shell('pidof', app).strip()), True, 'Frontend survives target failure')
    try:
        start_custom()
        pid = shell('pidof', app).strip()
        frontend_uid = int(shell('run-as', app, 'id', '-u').strip())
        search_launch('Smoke')
        wait_for(lambda: 'Activity launch accepted: ComponentInfo{org.esdeplus.stub/' in adb('logcat', '-d'), 'native gamelist launch into recipient')
        wait_for(lambda: re.search(r'mCurrentFocus=.* org\.esdeplus\.stub/',
                 shell('dumpsys', 'window', 'windows')), 'recipient focused window')
        observation = json.loads(shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
        launch_checks.recipient(observation, frontend_uid, b'\x00')
        (evidence / ('gamelist-recipient-' + mode + '.txt')).write_text(json.dumps(observation, ensure_ascii=False, indent=2))
        screenshot('gamelist-recipient-' + mode)
        save_logs('gamelist-recipient-' + mode)
        key('KEYCODE_BACK')
        wait_for(lambda: re.search(r'mCurrentFocus=.* ' + re.escape(app) + r'/', shell('dumpsys', 'window', 'windows')), 'return from recipient to frontend')
        launch_checks.equal(shell('pidof', app).strip(), pid, 'Return resumes same frontend process')
        screenshot('gamelist-return-' + mode)
        if component_enabled('org.esdeplus.stub/.RecipientActivity', False):
            try:
                failed_target('disabled')
            finally:
                component_enabled('org.esdeplus.stub/.RecipientActivity', True)
        shell('am', 'force-stop', app)
        adb('uninstall', 'org.esdeplus.stub')
        failed_target('removed')
        adb('install', '-r', 'android/stub-emulator/build/outputs/apk/debug/stub-emulator-debug.apk')
        if api == 29:
            shell('pm', 'grant', 'org.esdeplus.stub', 'android.permission.READ_EXTERNAL_STORAGE')
        start_custom()
        key('KEYCODE_ESCAPE')
        for _ in range(7):
            key('KEYCODE_DPAD_DOWN')
        key('KEYCODE_ENTER')  # UTILITIES
        key('KEYCODE_ENTER')  # GAME IMPORTER
        screenshot('importer-' + mode)
        key('KEYCODE_INSERT')  # real Y/start importer action
        temp_files = external + '/ES-DE-Plus/importer_temp/files'
        wait_for(lambda: bool(shell('ls', temp_files, check=False).strip()), 'real app importer inventory files')
        time.sleep(3)  # finish the actual importer thread and selector animation
        paths = shell('find', temp_files, '-type', 'f').splitlines()
        paths.sort(key=lambda path: pathlib.PurePosixPath(path).stem.upper())
        recipient_path = next(path for path in paths if shell('cat', path).strip() ==
                              'org.esdeplus.stub/org.esdeplus.stub.RecipientActivity')
        for _ in range(paths.index(recipient_path)):
            key('KEYCODE_DPAD_DOWN')
        key('KEYCODE_ENTER')  # select this app only
        screenshot('importer-selection-' + mode)
        key('KEYCODE_INSERT')  # real Y/import action
        wait_for(lambda: 'Imported 1 entry for system "androidapps"' in log(), 'import one native app')
        imported = user_root + '/androidapps/' + pathlib.PurePosixPath(recipient_path).name
        launch_checks.equal(shell('cat', imported).strip(), 'org.esdeplus.stub/org.esdeplus.stub.RecipientActivity', 'Importer target file')
        screenshot('importer-imported-' + mode)
        save_logs('importer-imported-' + mode)
        key('KEYCODE_DEL')  # close importer; its real callback rescans
        wait_for(lambda: 'Total game count: 3' in log(), 'importer callback rescans gamelist')
        time.sleep(5)
        adb('logcat', '-c')
        search_launch('recipient')
        wait_for(lambda: 'Activity launch accepted: ComponentInfo{org.esdeplus.stub/' in adb('logcat', '-d'), 'imported app gamelist launch')
        screenshot('imported-app-launched-' + mode)
        save_logs('imported-app-launched-' + mode)
        key('KEYCODE_BACK')
        wait_for(lambda: re.search(r'mCurrentFocus=.* ' + re.escape(app) + r'/', shell('dumpsys', 'window', 'windows')), 'imported app returns to frontend')
        screenshot('imported-app-return-' + mode)
    finally:
        shell('am', 'force-stop', app)
        shell('am', 'force-stop', 'org.esdeplus.stub')
        shell('rm', '-f', custom + '/es_systems.xml', custom + '/es_find_rules.xml')
        shell('rm', '-rf', user_root + '/androidapps', external + '/ES-DE-Plus/importer_temp')
        launch()


def real_retroarch_flow():
    apk_path = pathlib.Path(os.environ['RUNNER_TEMP']) / 'RetroArch.apk'
    # Download/verification occurs in CI before this smoke. No copy enters the
    # checkout or the evidence upload's explicitly enumerated text/image paths.
    print(adb('install', '-r', str(apk_path)), flush=True)
    package = shell('dumpsys', 'package', 'com.retroarch')
    version = re.search(r'versionName=([^\s]+)', package).group(1)
    launch_checks.equal(version, '1.22.2', 'Installed official RetroArch version')
    (evidence / 'real-retroarch-package.txt').write_text(package)
    shell('am', 'force-stop', app)
    original = shell('cat', settings)
    document = ET.fromstring(original)
    enabled = document.find("bool[@name='RetroArchCoreQueryExperimental']")
    if enabled is None:
        enabled = ET.SubElement(document, 'bool', name='RetroArchCoreQueryExperimental')
    enabled.set('value', 'true')
    edited = evidence / 'retroarch-query-settings.txt'
    edited.write_text(ET.tostring(document, encoding='unicode'))
    adb('push', str(edited), settings)
    try:
        adb('logcat', '-c')
        launch()
        search_launch('Smoke')
        wait_for(lambda: 'Timed out attempting to query RetroArch, proceeding with game launch anyway' in log(), 'bundled RetroArch query timeout proceeds')
        wait_for(lambda: 'com.retroarch/com.retroarch.browser.retroactivity.RetroActivityFuture' in
                 shell('dumpsys', 'activity', 'activities'), 'unchanged bundled rule launches real RetroArch activity')
        native = log()
        launch_checks.equal('Emulator core is not installed' in native, False, 'Stable query never vetoes launch')
        current = adb('logcat', '-d', '-v', 'threadtime')
        smoke_checks.probe_passed(current, 'Activity launch accepted: ComponentInfo{com.retroarch/')
        # Capture RetroArch's own process messages and ActivityManager's actual
        # activity/Intent record; no real core/game load is asserted.
        wait_for(lambda: bool(shell('pidof', 'com.retroarch', check=False).strip()), 'real RetroArch process')
        recipient_pid = shell('pidof', 'com.retroarch').strip().split()[0]
        recipient_log = adb('logcat', '-d', '--pid=' + recipient_pid, '-v', 'threadtime')
        launch_checks.equal(bool(recipient_log.strip()), True, 'Real RetroArch process logcat')
        (evidence / 'real-retroarch-recipient-logcat.txt').write_text(recipient_log)
        (evidence / 'real-retroarch-activities.txt').write_text(shell('dumpsys', 'activity', 'activities'))
        screenshot('real-retroarch-launched')
        save_logs('real-retroarch-launch')
        launch_checks.equal('Core query cleanup: com.retroarch result=-1' in current, True, 'Real core query cleanup/timeout')
        shell('am', 'force-stop', 'com.retroarch')
        start_entry()
        wait_for(lambda: re.search(r'mCurrentFocus=.* ' + re.escape(app) + r'/', shell('dumpsys', 'window', 'windows')), 'return from real RetroArch')
        screenshot('real-retroarch-return')
    finally:
        shell('am', 'force-stop', app)
        shell('am', 'force-stop', 'com.retroarch')
        restored = evidence / 'retroarch-settings-restored.txt'
        restored.write_text(original)
        adb('push', str(restored), settings)
        adb('uninstall', 'com.retroarch')


def native_shutdown(pid):
    # Android Runtime.exit skips native atexit cleanup, so the final buffered
    # es_log line is not evidence of SDL completion. Require the actual native
    # return and successful VM exit, both from this frontend process.
    lines = [line for line in adb('logcat', '-d', '-v', 'threadtime').splitlines()
             if re.search(r'\s' + re.escape(pid) + r'\s', line)]
    return (any('Finished main function' in line for line in lines) and
            any('SDL activity destroy join returned' in line for line in lines) and
            any('VM exiting with result code 0' in line for line in lines))


try:
    features = shell('pm', 'list', 'features')
    (evidence / 'device-features.txt').write_text(features)
    television = 'feature:android.software.leanback' in features.splitlines()
    if television:
        # Google's TV image launches this dialog asynchronously over other
        # apps. Disable only that external onboarding component before testing.
        onboarding = stock_package + '/' + stock_package + '.dialog.ShowDialogsActivity'
        # dumpsys' resolver table omits activities without intent filters.
        # The installed stock package owns this explicitly addressed dialog;
        # pm disable validates that the component itself exists.
        if 'package:' + onboarding.split('/')[0] in shell('pm', 'list', 'packages').splitlines():
            if component_enabled(onboarding, False):
                smoke_checks.onboarding_disabled(True)
                (evidence / 'tv-onboarding-preamble.txt').write_text(
                    'Stock TV ShowDialogsActivity disabled before frontend smoke; frontend assertions unchanged.\n')
            else:
                # Promotions are optional and may arrive after content loads.
                # Prepare the actual stock UI, dismiss any present onboarding,
                # and retain the same guard for a late external dialog.
                onboarding_guard = True
                shell('am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME',
                      '-n', stock_package + '/.MainActivity')
                wait_for(lambda: any(n.get('package') == stock_package for n in hierarchy()), 'stock TV HOME UI')
                dismiss_stock_onboarding(force=True)
                smoke_checks.onboarding_clear(hierarchy(), stock_package)
                screenshot('tv-onboarding-preamble')
                (evidence / 'tv-onboarding-preamble.txt').write_text(
                    'Actual stock TV HOME UI verified without onboarding before frontend smoke; focused late stock dialogs are dismissed without relaunching the frontend or weakening its assertions.\n' +
                    (evidence / 'latest-ui.txt').read_text())
    print(adb('install', '-r', str(apk)), flush=True)
    print(adb('install', '-r', 'android/stub-emulator/build/outputs/apk/debug/stub-emulator-debug.apk'), flush=True)
    shell('setprop', 'debug.checkjni', '1')
    clear_app()
    retained = instrument_with_ui('am', 'instrument', '-w', '-e', 'mode', 'retained-configurator',
                     app + '/org.esdeplus.frontend.RuntimeSmoke')
    (evidence / 'retained-configurator-probe.txt').write_text(retained)
    smoke_checks.probe_passed(retained,
        'PASS: retained configurator reorders above the same live SDL host; positive controls rejected')
    clear_app()
    api = int(shell('getprop', 'ro.build.version.sdk').strip())
    if api == 29:
        shell('pm', 'grant', 'org.esdeplus.stub', 'android.permission.READ_EXTERNAL_STORAGE')
    (evidence / 'image.txt').write_text(shell('getprop'))
    # Genuine shared files, accessible to users through file transfer; no settings
    # or preferences are written by the host-side automation.
    shared = '/sdcard/ESDEPlusSmoke'
    shell('mkdir', '-p', shared + '/nes')
    dummy = evidence / 'dummy.nes'
    dummy.write_bytes(b'\x00')
    for name in ['Smoke Alpha.nes', 'Smoke Beta.nes']:
        adb('push', str(dummy), shared + '/nes/' + name)
    start_entry('HomeEntry', 'android.intent.category.HOME')
    ui('Cancel configuration', dpad=True)
    ui('Configuration cancelled')
    screenshot('home-cancel-recoverable')
    assert shell('pidof', app).strip(), 'HOME cancellation killed the process'
    key('KEYCODE_BACK')
    ui('Configuration cancelled')
    # Resize a real display while the native caller is held. Android recreates
    # the plain-view activity; its selections and static registration survive.
    adb('logcat', '-c')
    shell('wm', 'size', '1280x720' if television else '720x1280')
    wait_for(lambda: 'Configurator created savedState=true' in adb('logcat', '-d'), 'configurator recreation')
    shell('wm', 'size', 'reset')
    ui('Configuration cancelled')
    screenshot('configurator-recreated')
    save_logs('configurator-recreated')
    held_pid = shell('pidof', app).strip()
    density = int(re.findall(r'density: (\d+)', shell('wm', 'density'))[-1])
    adb('logcat', '-c')
    try:
        shell('wm', 'density', str(density + 40))
        wait_for(lambda: 'Configurator created savedState=true' in adb('logcat', '-d'), 'density configurator recreation')
        assert shell('pidof', app).strip() == held_pid, 'Display-scale change destroyed the held SDL host'
        ui('Configuration cancelled')
        screenshot('configurator-density-recreated')
        save_logs('configurator-density-recreated')
    finally:
        shell('wm', 'density', str(density))
    if api >= 31:
        previous_weight = shell('settings', 'get', 'secure', 'font_weight_adjustment').strip()
        before_records = activity_records()[1]
        adb('logcat', '-c')
        requested_weight = '300' if previous_weight != '300' else '0'
        try:
            shell('settings', 'put', 'secure', 'font_weight_adjustment',
                  requested_weight)
            wait_for(lambda: 'fontWeightAdjustment=' + requested_weight in
                     shell('dumpsys', 'activity', 'activities'), 'actual font-weight configuration changed')
            # Make the hidden host process its pending configuration through a
            # real re-entry; it immediately re-presents the held configurator.
            start_entry('HomeEntry', 'android.intent.category.HOME')
            wait_for(lambda: 'SDL activity configuration handled' in adb('logcat', '-d'),
                     'held SDL host handles the actual font-weight change')
            assert shell('pidof', app).strip() == held_pid
            after_records = activity_records()[1]
            assert next(r for r in after_records if r[0] != 'ConfiguratorActivity') == next(
                r for r in before_records if r[0] != 'ConfiguratorActivity'), (before_records, after_records)
            assert 'Creating sole SDL activity' not in adb('logcat', '-d')
            (evidence / 'font-weight-held-activities.txt').write_text(activity_records()[0])
            save_logs('font-weight-held')
            screenshot('font-weight-held')
        finally:
            if previous_weight == 'null':
                shell('settings', 'delete', 'secure', 'font_weight_adjustment')
            else:
                shell('settings', 'put', 'secure', 'font_weight_adjustment', previous_weight)
    ui('Use app-owned storage', dpad=True)
    ui('Create system folders', dpad=True)
    destroy_held('destroy-initial-held')
    ui('How to add games')
    assert any(n.get('text') == 'Create system folders' and n.get('checked') == 'false' for n in hierarchy())
    ui('Create system folders', dpad=True)
    ui('Use direct filesystem compatibility', dpad=True)
    screenshot('mode-before-permission')
    if api >= 30:
        settings_component = resolved_component('android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION', 'package:' + app)
        if settings_component and component_enabled(settings_component, False):
            try:
                ui('Grant direct filesystem access', dpad=True)
                grant_from_settings()
                screenshot('generic-all-files-settings-return')
                # Revoke only for the subsequent denial/grant UI probe.
                shell('appops', 'set', '--uid', app, 'MANAGE_EXTERNAL_STORAGE', 'deny')
                start_entry('HomeEntry', 'android.intent.category.HOME')
            finally:
                component_enabled(settings_component, True)
    ui('Grant direct filesystem access', dpad=True)
    if api == 29:
        ui('Deny')
        ui('Access was not granted')
        screenshot('permission-denied')
        ui('Grant direct filesystem access', dpad=True)
        ui('Allow')
    else:
        # Return without granting once, from either app-specific or generic UI.
        key('KEYCODE_BACK')
        if not any(n.get('package') == app for n in hierarchy()):
            key('KEYCODE_BACK')
        ui('Access was not granted')
        screenshot('all-files-denied')
        ui('Grant direct filesystem access', dpad=True)
        grant_from_settings()
    # Real editable field and focus survive an Activity resume/re-render.
    ui('Absolute shared ROM folder path', dpad=television)
    if television:
        (evidence / 'tv-path-ime.txt').write_text(shell('dumpsys', 'input_method'))
        screenshot('tv-path-ime-open')
    shell('input', 'text', shared)
    key('KEYCODE_BACK')
    shell('am', 'start', '-a', 'android.settings.SETTINGS')
    settings_package = resolved_component('android.settings.SETTINGS').split('/')[0]
    wait_for(lambda: any(n.get('package') == settings_package for n in hierarchy()),
             'real Settings foreground before returning to the typed path')
    key('KEYCODE_BACK')
    wait_for(lambda: any(n.get('class') == 'android.widget.EditText' and n.get('text') == shared and
                         n.get('focused') == 'true' for n in hierarchy()), 'typed text and D-pad focus retained on resume')
    screenshot('typed-path-focus-preserved')
    (evidence / 'typed-path-focus-preserved-ui.txt').write_text((evidence / 'latest-ui.txt').read_text())
    picker_component = resolved_component('android.intent.action.OPEN_DOCUMENT_TREE')
    if picker_component and component_enabled(picker_component, False):
        try:
            ui('Choose shared ROM folder', dpad=True)
            wait_for(lambda: any(node_matches(n, 'A folder picker is unavailable') or
                                  node_matches(n, 'Folder selection cancelled') for n in hierarchy()),
                     'missing picker returns a recoverable message')
            screenshot('missing-picker-fallback')
        finally:
            component_enabled(picker_component, True)
    ui('Choose shared ROM folder', dpad=True)
    nodes = hierarchy()
    if any(node_matches(n, 'A folder picker is unavailable') or
           node_matches(n, 'Folder selection cancelled') for n in nodes):
        # Some devices resolve the action to a capability stub that immediately
        # returns cancellation. The same visible typed-path fallback applies.
        screenshot('picker-unavailable-or-returned-cancel')
        save_logs('picker-capability')
        ui('Use typed folder path', dpad=True)
    else:
        # Exercise cancellation without replacing the existing selection.
        key('KEYCODE_BACK')
        ui('Folder selection cancelled')
        screenshot('picker-cancelled')
        ui('Choose shared ROM folder', dpad=True)
        select_tree('ESDEPlusSmoke')
        wait_for(lambda: grant_count(1), 'actual pending persisted tree grant')
        ui('Cancel configuration', dpad=True)
        cancelled_grant_retained()
        save_logs('cancel-retains-selected-grant')
        ui('Choose shared ROM folder', dpad=True)
        select_tree('ESDEPlusSmoke')
        shell('mkdir', '-p', '/sdcard/ESDEPlusOtherFolder')
        ui('Choose shared ROM folder', dpad=True)
        select_tree('ESDEPlusOtherFolder')
        wait_for(lambda: grant_count(1), 'new selection releases superseded pending grant')
        save_logs('selection-releases-pending-grant')
        ui('Choose shared ROM folder', dpad=True)
        select_tree('ESDEPlusSmoke')
        ui('Cancel configuration', dpad=True)
        cancelled_grant_retained()
    ui('Save and start frontend', dpad=True)
    configured_system('direct-system-view')
    completion = adb('logcat', '-d')
    assert completion.index('Storage configuration committed mode=direct') < completion.index('Native startup hold released'), completion
    launch_contract_probes('direct')
    shell('am', 'force-stop', app)
    revoked_tree = shell('am', 'instrument', '-w', '-e', 'mode', 'revoke-tree',
                         app + '/org.esdeplus.frontend.RuntimeSmoke')
    (evidence / 'revoked-tree-launch.txt').write_text(revoked_tree)
    shell('am', 'force-stop', app)
    start_entry('HomeEntry', 'android.intent.category.HOME')
    if 'PASS: real selected tree revoked' in revoked_tree:
        ui('Configure ' + label)
        screenshot('revoked-tree-recovery')
        save_logs('revoked-tree-recovery')
        ui('Use typed folder path', dpad=True)
        ui('Save and start frontend', dpad=True)
        configured_system('direct-typed-path-system')
        wait_for(lambda: grant_count(0), 'typed-path recovery has no persisted tree grant')
    else:
        smoke_checks.probe_passed(revoked_tree,
            'CAPABILITY: real typed-path selection already has no persisted tree')
        configured_system('direct-typed-path-system')
    launch_contract_probes('direct-typed')
    # Cold/warm entry semantics: each alias reuses the SDL activity and updates
    # HOME only through the HOME entry. No preference or native flag injection.
    pid = shell('pidof', app).strip()
    for name, category, home in [('LeanbackEntry', 'android.intent.category.LEANBACK_LAUNCHER', False),
                                  ('HomeEntry', 'android.intent.category.HOME', True),
                                  ('MainActivity', 'android.intent.category.LAUNCHER', False)]:
        adb('logcat', '-c')
        start_entry(name, category)
        wait_for(lambda: ('SDL entry reused via onNewIntent' in adb('logcat', '-d') or
                         'Focused redirect forwarding' in adb('logcat', '-d')) and
                 f'HOME={str(home).lower()}' in adb('logcat', '-d'), 'warm entry and HOME state')
        assert shell('pidof', app).strip() == pid, 'Warm entry replaced the process'
        entry_log = adb('logcat', '-d')
        smoke_checks.warm_entry(entry_log, home)
        assert 'Creating sole SDL activity' not in entry_log and 'Running main function' not in entry_log
        assert len(activity_records()[1]) == 1, activity_records()[0]
        if home:
            assert 'SDL entry reused via onNewIntent' in entry_log, 'Same-type HOME re-entry did not use onNewIntent'
        (evidence / (name + '-activities.txt')).write_text(shell('dumpsys', 'activity', 'activities'))
        screenshot(name + '-warm')
        key('KEYCODE_ESCAPE')
        screenshot(name + '-menu')
        key('KEYCODE_DEL')
        if home:
            key('KEYCODE_BACK')
            assert shell('pidof', app).strip() == pid, 'Warm HOME Back exited the frontend'
            assert any(n.get('package') == app for n in hierarchy()), 'Warm HOME Back left the frontend'
    shell('am', 'force-stop', app)
    # Preserve user-edited system metadata and a genuinely deleted empty system
    # across an ordinary restart, in addition to checking the consumed flag.
    # These are user edits to the shared directory through ordinary adb, the
    # same access used to provision its ROMs. run-as has a separate mount view.
    shell('test', '-d', shared + '/3do')
    shell('rm', '-rf', shared + '/3do')
    shell('sh', '-c', 'echo user-system-metadata > ' + shlex.quote(shared + '/nes/systeminfo.txt'))
    start_entry()
    configured_system('direct-restart')
    shell('test', '!', '-d', shared + '/3do')
    assert shell('cat', shared + '/nes/systeminfo.txt').strip() == 'user-system-metadata'
    smoke_checks.no_generation(log())
    (evidence / 'one-shot-direct.txt').write_text('PASS: deleted 3do stayed absent; user NES systeminfo.txt unchanged on restart.\n' + log())
    if api == 34:
        real_system_home()
    shell('am', 'force-stop', app)
    volume_probe = shell('am', 'instrument', '-w', '-e', 'mode', 'storage',
                         app + '/org.esdeplus.frontend.RuntimeSmoke')
    assert 'PASS: real persisted direct selection rejects unavailable' in volume_probe, volume_probe
    (evidence / 'selected-volume-unavailable.txt').write_text(volume_probe)
    shell('am', 'force-stop', app)
    session_probe = shell('am', 'instrument', '-w', '-e', 'mode', 'configurator-session',
                          app + '/org.esdeplus.frontend.RuntimeSmoke')
    (evidence / 'configurator-session-probe.txt').write_text(session_probe)
    smoke_checks.probe_passed(session_probe,
        'PASS: session-matched draft only; no-config startup clears abandoned draft; positive controls rejected')
    # Remove the selected shared folder while retaining the real grant/selection.
    # Failure must be a recovery screen; restore it and accept the same selection.
    shell('am', 'force-stop', app)
    shell('mv', shared, shared + '.smoke-saved')
    try:
        start_entry('HomeEntry', 'android.intent.category.HOME')
        ui('Configure ' + label)
        screenshot('selected-shared-folder-unavailable')
        save_logs('selected-shared-folder-unavailable')
        assert shell('pidof', app).strip(), 'Missing selected folder exited HOME'
    finally:
        shell('mv', shared + '.smoke-saved', shared)
    ui('Save and start frontend', dpad=True)
    configured_system('selected-folder-restored-system')
    # Revoke actual access after persisted configuration; ordinary startup must
    # show recovery, never substitute a directory or restart-loop HOME.
    shell('am', 'force-stop', app)
    if api == 29:
        shell('pm', 'revoke', app, 'android.permission.WRITE_EXTERNAL_STORAGE')
    else:
        shell('appops', 'set', '--uid', app, 'MANAGE_EXTERNAL_STORAGE', 'deny')
        revoked = shell('appops', 'get', '--uid', app, 'MANAGE_EXTERNAL_STORAGE')
        assert 'deny' in revoked, revoked
        (evidence / 'revoked-all-files-appop.txt').write_text(revoked)
    start_entry('HomeEntry', 'android.intent.category.HOME')
    ui('Configure ' + label)
    screenshot('revoked-access-recovery')
    save_logs('revoked-access-recovery')
    # Recover through an explicit scoped choice, without pm clear hiding old
    # persisted grants. The accepted shared grant must be released on save.
    ui('Use app-owned storage', dpad=True)
    ui('Create system folders', dpad=True)
    ui('How to add games')
    screenshot('scoped-provisioning-howto')
    # Demonstrate the displayed provisioning route as the ordinary shell UID.
    # The app owns and creates this directory; no root or run-as is involved.
    assert shell('id', '-u').strip() == '2000', shell('id')
    shell('mkdir', '-p', roms + '/nes')
    for name in ['Smoke Alpha.nes', 'Smoke Beta.nes']:
        adb('push', str(dummy), roms + '/nes/' + name)
    dummy.unlink()
    (evidence / 'scoped-adb-provisioning.txt').write_text('Ordinary shell UID 2000 populated the displayed app-owned ROM path using adb push.\n')
    # Put the configurator in the background, then kill its process through
    # ActivityManager. am kill can retain recently backgrounded processes;
    # SELinux can prevent run-as from signaling the app's different domain.
    old_pid = shell('pidof', app).strip()
    assert old_pid.isdigit(), old_pid
    adb('logcat', '-c')
    shell('am', 'start', '-a', 'android.settings.SETTINGS')
    wait_for(lambda: any(n.get('package', '').startswith('com.android.') and
                         n.get('package') != app for n in hierarchy()) and
             not any(n.get('package') == app for n in hierarchy()), 'configurator backgrounded')
    def state_saved():
        return 'Configurator instance state saved mode=scoped' in adb('logcat', '-d')
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not state_saved():
        time.sleep(0.5)
    if not state_saved():
        # TV Settings may only pause an activity behind its translucent panel.
        # Try the actual system HOME before declaring an honest SDK-state gap.
        key('KEYCODE_HOME')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not state_saved():
            time.sleep(0.5)
    framework_saved = state_saved()
    task_dump, task_records = activity_records()
    saved_task = next(r[1] for r in task_records if r[0] == 'ConfiguratorActivity')
    save_logs('saved-state-background')
    shell('am', 'kill', app)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and shell('pidof', app, check=False).strip() == old_pid:
        time.sleep(0.5)
    if shell('pidof', app, check=False).strip() != old_pid and framework_saved:
        adb('logcat', '-c')
        shell('am', 'task', 'focus', saved_task)
        ui('How to add games')
        wait_for(lambda: 'Configurator created savedState=true mode=scoped' in adb('logcat', '-d'),
                 'framework Bundle restored after honest background am kill')
        (evidence / 'saved-state-restore.txt').write_text('PASS: am kill ended the background process; retained task restored the actual saved Bundle.\n' + task_dump + '\n' + adb('logcat', '-d'))
    else:
        (evidence / 'saved-state-restore.txt').write_text(
            f'EVIDENCE GAP: SDK state callback observed={framework_saved}; '
            f'am kill retained old process={shell("pidof", app, check=False).strip() == old_pid}. '
            'OS process-death saved-Bundle restoration was not driven. '
            'The force-stop/draft probe follows.\n' + task_dump)
        shell('am', 'force-stop', app)
        wait_for(lambda: not shell('pidof', app, check=False).strip(), 'background configuration process death')
        start_entry('HomeEntry', 'android.intent.category.HOME')
        ui('How to add games')
    assert shell('pidof', app).strip() != old_pid, 'Process-death probe did not restart the host'
    screenshot('configurator-after-process-death')
    save_logs('configurator-after-process-death')
    adb('logcat', '-c')
    ui('Save and start frontend', dpad=True)
    wait_for(lambda: 'Storage configuration committed mode=scoped' in adb('logcat', '-d') and
             'Persisted tree grant count=0' in adb('logcat', '-d'), 'scoped save releases actual shared grants')
    wait_for(lambda: 'HOME=true' in adb('logcat', '-d') and len(activity_records()[1]) == 1,
             'process-death configurator return starts recorded HOME entry on one SDL host')
    save_logs('scoped-save-releases-grants')
    shell('am', 'force-stop', app)
    # Resource installation is uncommitted on a fresh start; remove resources
    # solely to guarantee a real copy for the interruption probe.
    private('rm', '-rf', 'files/resources', 'files/themes', 'files/resources-installed')
    # Interrupt an actual first-run copy through ActivityManager. Inspect the
    # partial installation after the process is stopped, never before it.
    adb('logcat', '-c')
    shell('am', 'start', '-n', activity)
    wait_for(lambda: shell('pidof', app, check=False).strip().isdigit(), 'copy-probe process started')
    copy_pid = shell('pidof', app).strip()
    # PID filtering also excludes messages already buffered by the prior
    # configurator process; clearing logcat alone does not bind this probe.
    follower = subprocess.Popen(['adb', 'logcat', '--pid=' + copy_pid, '-v', 'brief', 'ES-DE-Plus:I', '*:S'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 60
    observed = b''
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([follower.stdout], [], [], 1)
            if readable:
                observed += follower.stdout.read1(65536)
                if b'Installed resource: fonts/' in observed:
                    assert shell('pidof', app).strip() == copy_pid, 'Copy-probe process changed'
                    shell('am', 'force-stop', app)
                    wait_for(lambda: not shell('pidof', app, check=False).strip(), 'resource-copy process stopped')
                    break
        else:
            raise AssertionError('No actual font copy observed to interrupt')
        assert private('test', '!', '-f', 'files/resources-installed') == ''
        assert private('find', 'files/resources/fonts', '-type', 'f').strip()
    finally:
        follower.terminate()
        follower.wait(timeout=10)
    (evidence / 'interrupted-copy-logcat.txt').write_text(observed.decode(errors='replace'))
    print('PASS: killed during real copy, partial fonts exist, marker absent', flush=True)
    adb('logcat', '-c')
    launch()
    processes = shell('ps', '-A', '-o', 'UID,NAME')
    frontend = [line for line in processes.splitlines() if line.split()[-1] == app]
    assert frontend and all(int(line.split()[0]) >= 10000 for line in frontend), processes
    (evidence / 'frontend-uid.txt').write_text('\n'.join(frontend) + '\n')
    assert private('test', '-f', 'files/resources-installed') == ''
    private('test', '-f', 'files/resources/fonts/DejaVuSans.ttf')
    private('test', '-f', 'files/resources/locale/en_US/LC_MESSAGES/en_US.mo')
    private('test', '-f', 'files/resources/certificates/curl-ca-bundle.crt')
    private('test', '-f', 'files/themes/linear-es-de/theme.xml')
    screenshot('system-view')
    save_logs('first-launch-recovered')
    launch_contract_probes('scoped')
    # Real keyboard navigation: open the menu, its first SEARCH entry, type, accept.
    key('KEYCODE_ESCAPE')
    screenshot('main-menu-search')
    key('KEYCODE_ENTER')
    shell('input', 'text', 'Smoke')
    key('KEYCODE_ENTER')
    screenshot('search-results')
    # Move past the search header to the first result, then use the real launch path.
    key('KEYCODE_DPAD_DOWN')
    key('KEYCODE_ENTER')
    wait_for(lambda: "Couldn't launch game, emulator not found" in log(), 'existing missing-emulator error')
    screenshot('missing-emulator')
    save_logs('search-and-launch')
    assert shell('pidof', app).strip(), 'Launch attempt terminated the frontend'
    # Missing-emulator errors are expected in this phase; startup errors were checked above.
    key('KEYCODE_ENTER')  # Dismiss the existing missing-emulator message.
    key('KEYCODE_ESCAPE')
    for _ in range(3):  # SEARCH, SCRAPER, UI SETTINGS, then SOUND SETTINGS.
        key('KEYCODE_DPAD_DOWN')
    key('KEYCODE_ENTER')
    key('KEYCODE_DPAD_DOWN')  # Audio driver, then navigation volume.
    key('KEYCODE_DPAD_LEFT')
    screenshot('changed-sound-setting')
    # Upstream's keyboard Back action is Backspace; Escape maps to Start and
    # does not close GuiSettings. Closing the settings GUI runs its save funcs.
    key('KEYCODE_DEL')
    key('KEYCODE_DEL')
    def volume_saved():
        value = re.search(r'<int name="SoundVolumeNavigation" value="(\d+)"',
                          shell('cat', settings, check=False))
        return value and int(value.group(1)) < 70
    wait_for(volume_saved, 'real navigation-volume change saved to settings')
    shell('am', 'force-stop', app)
    before = shell('cat', settings)
    (evidence / 'preserved-settings.txt').write_text(before)
    assert '<bool ' in before and '<string ' in before, 'Settings were not saved'
    volume = re.search(r'<int name="SoundVolumeNavigation" value="(\d+)"', before)
    assert volume and int(volume.group(1)) < 70, 'Keyboard change to default navigation volume (70) was not saved'
    adb('logcat', '-c')
    launch()
    current_logcat = adb('logcat', '-d')
    assert 'Resource copy required=false' in current_logcat, current_logcat
    assert 'Installed resource:' not in current_logcat, current_logcat
    assert shell('cat', settings) == before, 'Settings changed on second launch'
    save_logs('second-launch')
    print('PASS: second launch skips copying and preserves settings', flush=True)
    shell('am', 'force-stop', app)
    private('mkdir', '-p', 'files/themes/user-theme')
    # Write a genuine user file; the resource installer must not overwrite/delete it.
    private('sh', '-c', 'echo user-content > files/themes/user-theme/keep.txt')
    private('rm', 'files/resources/fonts/DejaVuSans.ttf')
    adb('logcat', '-c')
    launch()
    assert 'Installed resource: fonts/DejaVuSans.ttf' in adb('logcat', '-d')
    assert private('cat', 'files/themes/user-theme/keep.txt').strip() == 'user-content'
    assert shell('cat', settings) == before
    save_logs('deleted-file-recovery')
    print('PASS: deleted font restored despite marker; user theme and settings preserved', flush=True)
    shell('am', 'force-stop', app)
    adb('logcat', '-c')
    result = shell('am', 'instrument', '-w', app + '/org.esdeplus.frontend.RuntimeSmoke')
    (evidence / 'instrumentation.txt').write_text(result)
    assert 'PASS: descriptors, CheckJNI 10000 calls' in result, result
    checkjni = adb('logcat', '-d', '-v', 'threadtime')
    (evidence / 'instrumentation-logcat.txt').write_text(checkjni)
    assert 'Late-enabling -Xcheck:jni' in checkjni or 'CheckJNI' in checkjni, checkjni
    assert 'JNI DETECTED ERROR' not in checkjni and 'JNI WARNING' not in checkjni, checkjni
    assert 'Early resource copy failed: fonts/' in checkjni, checkjni
    assert 'cheap normal start, explicit hash/size repair, unavailable-storage rejection' in result, result
    assert 'invalid UTF-16' in checkjni, checkjni
    print('PASS: runtime bridge and real font-copy failure probes under CheckJNI', flush=True)
    # Ordinary startup against unavailable/obstructed selected storage is
    # recoverable. Existing selections and user data must be preserved.
    for directory in ['ES-DE-Plus', 'ROMs']:
        shell('am', 'force-stop', app)
        owned_fixture('block', directory)
        try:
            adb('logcat', '-c')
            start_entry('HomeEntry', 'android.intent.category.HOME')
            ui('Configure ' + label)
            screenshot('blocked-' + directory + '-recoverable')
            save_logs('blocked-' + directory)
            assert shell('pidof', app).strip(), 'Storage error killed HOME frontend'
            private('test', '!', '-d', 'files/settings')
        finally:
            shell('am', 'force-stop', app)
            owned_fixture('restore', directory)
        print('PASS: obstructed ' + directory + ' has recoverable UI without fallback', flush=True)
    # A real resource-copy failure on the ordinary native startup path is shown
    # to the user. Removing the obstruction and pressing Retry resumes startup.
    shell('am', 'force-stop', app)
    private('mv', 'files/resources/fonts', 'files/resources/fonts.smoke-saved')
    try:
        private('sh', '-c', 'echo obstruction > files/resources/fonts')
        start_entry('HomeEntry', 'android.intent.category.HOME')
        ui('Resource installation failed')
        screenshot('resource-copy-failure')
        destroy_held('destroy-resource-held')
        ui('Resource installation failed')
        private('rm', 'files/resources/fonts')
        private('mv', 'files/resources/fonts.smoke-saved', 'files/resources/fonts')
        ui('Retry startup', dpad=True)
        configured_system('resource-copy-retry-system')
    finally:
        shell('am', 'force-stop', app)
        private('mv', 'files/resources/fonts.smoke-saved', 'files/resources/fonts', check=False)
    adb('logcat', '-c')
    launch()
    assert shell('cat', settings) == before, 'Directory-failure recovery changed settings'

    screenshot('scoped-restart-system-view')
    shell('am', 'force-stop', app)
    # Scoped files require the application's SDK mount context on current TV.
    # Perform real filesystem edits through the existing debug fixture driver;
    # no configuration, permission or grant is injected.
    owned_fixture('edit-systems', 'ROMs')
    start_entry()
    configured_system('scoped-one-shot-restart')
    restarted_log = log()
    smoke_checks.no_generation(restarted_log)
    shell('am', 'force-stop', app)
    owned_fixture('verify-systems', 'ROMs')
    (evidence / 'one-shot-scoped.txt').write_text('PASS: SDK-context filesystem probe: deleted app-owned 3do stayed absent; edited NES systeminfo.txt unchanged on restart. No preferences or grants changed.\n' + restarted_log)
    for name, category, home in [('HomeEntry', 'android.intent.category.HOME', True),
                                  ('LeanbackEntry', 'android.intent.category.LEANBACK_LAUNCHER', False),
                                  ('MainActivity', 'android.intent.category.LAUNCHER', False)]:
        shell('am', 'force-stop', app)
        adb('logcat', '-c')
        start_entry(name, category)
        configured_system(name + '-cold')
        pid = shell('pidof', app).strip()
        assert pid.isdigit(), 'Cold entry has no frontend process'
        key('KEYCODE_BACK')
        if home:
            assert shell('pidof', app).strip() == pid, 'Cold HOME Back exited the frontend'
            assert any(n.get('package') == app for n in hierarchy()), 'Cold HOME Back left the frontend'
            assert 'cleanly shutting down' not in log(), log()
        else:
            wait_for(lambda: native_shutdown(pid), 'non-HOME native Back completion and successful VM exit')
            wait_for(lambda: not shell('pidof', app, check=False).strip(), 'terminal native host exit')
            wait_for(lambda: bool(hierarchy()) and not any(n.get('package') == app for n in hierarchy()),
                     'non-HOME Back Activity exit')
        screenshot(name + '-after-back')
        save_logs(name + '-back')
        if not home:
            # Real user relaunch after quit, without another force-stop/reset.
            start_entry(name, category)
            configured_system(name + '-after-quit-relaunch')
            relaunched_pid = shell('pidof', app).strip()
            assert relaunched_pid.isdigit() and relaunched_pid != pid, 'Quit/relaunch did not create a fresh native host'
            key('KEYCODE_BACK')
            wait_for(lambda: not shell('pidof', app, check=False).strip() and
                     native_shutdown(relaunched_pid), 'relaunch quits cleanly')
    real_retroarch_flow()
    (evidence / 'smoke-summary.txt').write_text('PASS: interruption/recovery, system view, keyboard SEARCH, missing-emulator attempt, second launch, settings, deleted-file repair, user theme, CheckJNI/Unicode/resource-failure probes, cheap normal-start and hash/size repair, recoverable data/ROM-directory failure, real configurator, both storage modes, entry aliases, revoked permission, one-shot folders in both modes, actual destruction during both native holds, retained typed text/focus, stale-grant release; PR-C recipient probes and native gamelist/provider/app-importer launches in both modes; pinned stable RetroArch timeout and actual activity launch; API 34 additionally real system HOME over drawer launch. Saved-state and image capability outcomes are recorded separately.\n')
except BaseException:
    save_logs('failure')
    screenshot('failure')
    raise
