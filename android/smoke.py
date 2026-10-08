#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Exercises the real installed frontend with adb.
import pathlib
import re
import select
import subprocess
import sys
import time

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
    return subprocess.run(['adb', *args], check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=not binary, timeout=90).stdout


def shell(*args, check=True):
    return adb('shell', *args, check=check)


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


def save_logs(name):
    (evidence / (name + '-es_log.txt')).write_text(log())
    (evidence / (name + '-logcat.txt')).write_text(adb('logcat', '-d', '-v', 'threadtime'))


def key(code):
    shell('input', 'keyevent', code)
    time.sleep(0.4)


try:
    print(adb('install', '-r', str(apk)), flush=True)
    shell('setprop', 'debug.checkjni', '1')
    shell('am', 'force-stop', app)
    shell('pm', 'clear', app)
    # Provision ROMs using adb before any frontend launch, as AC-3 requires.
    dummy = evidence / 'dummy.nes'
    dummy.write_bytes(b'\x00')
    shell('mkdir', '-p', roms + '/nes')
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
    shell('am', 'force-stop', app)
    before = shell('cat', settings)
    assert '<bool ' in before and '<string ' in before, 'Settings were not saved'
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
