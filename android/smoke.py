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

apk = pathlib.Path(sys.argv[1]).resolve()
app = next(line.split('=', 1)[1] for line in pathlib.Path('android/gradle.properties').read_text().splitlines()
           if line.startswith('esde.applicationId='))
activity = app + '/org.esdeplus.frontend.MainActivity'
evidence = pathlib.Path('android/evidence')
evidence.mkdir(parents=True, exist_ok=True)
external = f'/sdcard/Android/data/{app}/files'
roms = external + '/ROMs'
logpath = external + '/ES-DE-Plus/logs/es_log.txt'
settings = external + '/ES-DE-Plus/settings/es_settings.xml'


def adb(*args, check=True, binary=False):
    result = subprocess.run(['adb', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=not binary, timeout=90)
    if check and result.returncode:
        print(result.stderr.decode(errors='replace') if binary else result.stderr, file=sys.stderr)
        result.check_returncode()
    return result.stdout


def shell(*args, check=True):
    # adb shell joins arguments without escaping, including arguments to sh -c.
    return adb('shell', shlex.join(args), check=check)


def private(*args, check=True):
    return shell('run-as', app, *args, check=check)


def wait_for(condition, description, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.25)
    raise AssertionError('Timed out: ' + description)


def log():
    return shell('cat', logpath, check=False)


def screenshot(name):
    time.sleep(1)
    (evidence / (name + '.png')).write_bytes(adb('exec-out', 'screencap', '-p', binary=True))


def launch():
    # Each stopped-process restart must produce new startup evidence.
    shell('rm', '-f', logpath)
    shell('am', 'start', '-n', activity)
    wait_for(lambda: 'Application startup time:' in log(), 'frontend startup/system loading')
    assert 'Error:' not in log(), log()
    assert re.search(r'Total game count: 2\s', log()), 'The two adb-provisioned ROMs were not loaded: ' + log()
    # Dismiss the real Android immersive-mode tutorial if it is covering SDL.
    # Read its actual button bounds and send a tap; no setting/state is fabricated.
    hierarchy = '/data/local/tmp/esde-smoke-window.xml'
    shell('uiautomator', 'dump', hierarchy)
    window = shell('cat', hierarchy)
    (evidence / 'frontend-ui.txt').write_text(window)
    for node in ET.fromstring(window).iter('node'):
        if node.get('text') == 'Got it':
            x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.attrib['bounds']))
            shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
            time.sleep(0.5)


def save_logs(name):
    (evidence / (name + '-es_log.txt')).write_text(log())
    (evidence / (name + '-logcat.txt')).write_text(adb('logcat', '-d', '-v', 'threadtime'))


def key(code):
    shell('input', 'keyevent', code)
    time.sleep(0.4)


try:
    # The debugging daemon needs access to app-owned external evidence. This
    # does not change the frontend's UID, manifest permissions or bridge results.
    # Restarting adbd may close the request's transport before its reply. Verify
    # the resulting daemon UID after reconnecting, rather than trusting the reply.
    root = adb('root', check=False)
    adb('wait-for-device')
    identity = shell('id')
    assert shell('id', '-u').strip() == '0', root + identity
    (evidence / 'adb-access.txt').write_text(root + identity)
    print(adb('install', '-r', str(apk)), flush=True)
    shell('setprop', 'debug.checkjni', '1')
    shell('am', 'force-stop', app)
    shell('pm', 'clear', app)
    provisioning = shell('am', 'instrument', '-w', '-e', 'mode', 'provision',
                         app + '/org.esdeplus.frontend.RuntimeSmoke')
    assert 'PROVISIONED:' in provisioning, provisioning
    (evidence / 'fixture-provisioning.txt').write_text(provisioning)
    shell('am', 'force-stop', app)
    private('test', '!', '-f', 'files/resources-installed')
    # Provision ROMs using adb before any frontend launch, as AC-3 requires.
    dummy = evidence / 'dummy.nes'
    dummy.write_bytes(b'\x00')
    adb('push', str(dummy), roms + '/nes/Smoke Alpha.nes')
    adb('push', str(dummy), roms + '/nes/Smoke Beta.nes')
    dummy.unlink()
    # Interrupt an actual first-run copy. STOP freezes every thread before force-stop.
    adb('logcat', '-c')
    follower = subprocess.Popen(['adb', 'logcat', '-v', 'brief', 'ES-DE-Plus:I', '*:S'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    shell('am', 'start', '-n', activity)
    deadline = time.monotonic() + 60
    observed = b''
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([follower.stdout], [], [], 1)
            if readable:
                observed += follower.stdout.read1(65536)
                if b'Installed resource: fonts/' in observed:
                    pid = shell('pidof', app).strip()
                    assert pid.isdigit(), pid
                    private('kill', '-STOP', pid)
                    break
        else:
            raise AssertionError('No actual font copy observed to interrupt')
        assert private('test', '!', '-f', 'files/resources-installed') == ''
        assert private('find', 'files/resources/fonts', '-type', 'f').strip()
        shell('am', 'force-stop', app)
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
    key('KEYCODE_ESCAPE')  # GuiSettings saves the actual user change.
    key('KEYCODE_ESCAPE')
    shell('am', 'force-stop', app)
    before = shell('cat', settings)
    assert '<bool ' in before and '<string ' in before, 'Settings were not saved'
    volume = re.search(r'<int name="SoundVolumeNavigation" value="(\d+)"', before)
    assert volume and int(volume.group(1)) < 70, 'Keyboard change to default navigation volume (70) was not saved'
    (evidence / 'preserved-settings.txt').write_text(before)
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
    print('PASS: runtime bridge and real font-copy failure probes under CheckJNI', flush=True)
    (evidence / 'smoke-summary.txt').write_text('PASS: interruption/recovery, system view, keyboard SEARCH, missing-emulator attempt, second launch, settings, deleted-file repair, user theme, CheckJNI/Unicode/resource-failure probes\n')
except BaseException:
    save_logs('failure')
    screenshot('failure')
    raise
