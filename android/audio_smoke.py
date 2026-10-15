#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real window-reload audio regression and controls.
import hashlib
import io
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
import pdf_smoke


# Main at WO-15 dispatch. Only this source file replaces the current source in
# the isolated control; no other workstream or APK is used.
CONTROL_BASE = '063e454da'
ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTROL = ROOT / 'android/.deps/audio-control'


class ControlComplete(Exception):
    pass


def build_control():
    source = CONTROL / 'source'
    assert not source.exists(), 'Control build must start in a fresh directory'
    source.mkdir(parents=True)
    archive = subprocess.check_output(['git', 'archive', 'HEAD'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(source, filter='data')
    original = subprocess.check_output(
        ['git', 'show', CONTROL_BASE + ':es-core/src/AudioManager.cpp'], cwd=ROOT)
    assert b'SDL_CloseAudio();' in original
    (source / 'es-core/src/AudioManager.cpp').write_bytes(original)
    # Reuse verified dependency sources/installs, never native app objects.
    (source / 'android/.deps').symlink_to(ROOT / 'android/.deps', target_is_directory=True)
    (source / 'android/libs').symlink_to(ROOT / 'android/libs', target_is_directory=True)
    normal_apk = ROOT / 'android/app/build/outputs/apk/debug/app-debug.apk'
    before = hashlib.sha256(normal_apk.read_bytes()).hexdigest()
    subprocess.run(['bash', 'tools/Android_dependencies_setup.sh'], cwd=source, check=True)
    subprocess.run(['./gradlew', '--no-daemon', *shlex.split(os.environ.get('GRADLE_NETWORK_ARGS', '')),
                    '-Pesde.versionCode=' + os.environ['ESDE_VERSION_CODE'],
                    '-Pesde.versionName=test-' + subprocess.check_output(
                        ['git', 'rev-parse', '--short=9', 'HEAD'], cwd=ROOT, text=True).strip(),
                    ':app:assembleDebug'], cwd=source / 'android', check=True)
    shutil.copyfile(source / 'android/app/build/outputs/apk/debug/app-debug.apk', CONTROL / 'unfixed.apk')
    assert hashlib.sha256(normal_apk.read_bytes()).hexdigest() == before
    evidence = ROOT / 'android/evidence/audio-control-build.txt'
    evidence.write_text(f'Unfixed AudioManager source: {CONTROL_BASE}\n'
                        f'Unfixed source SHA256: {hashlib.sha256(original).hexdigest()}\n'
                        f'Normal APK unchanged: {before}\n'
                        'Control rebuilt in isolated source; runner only, never uploaded.\n')


def control_launch():
    if os.environ['IMAGE'] == 'api34':
        return
    app = next(line.split('=', 1)[1] for line in (ROOT / 'android/gradle.properties').read_text().splitlines()
               if line.startswith('esde.applicationId='))
    try:
        subprocess.run([sys.executable, 'android/smoke.py', str(CONTROL / 'unfixed.apk'),
                        '--audio-control'], cwd=ROOT, check=True)
    finally:
        # Controls use the normal SDK debug signer, preceding the full gating
        # smoke's independently signed APK. Never transfer data across signers.
        subprocess.run(['adb', 'uninstall', app], check=True)


def xml_settings(document):
    return '<?xml version="1.0"?>\n' + ''.join(ET.tostring(n, encoding='unicode') for n in document)


def set_setting(document, kind, name, value):
    node = document.find(f"{kind}[@name='{name}']")
    if node is None:
        node = ET.SubElement(document, kind, name=name)
    node.set('value', str(value))


def fatal_lines(logcat, pid, app):
    # libc/FORTIFY messages carry the crashing PID; crash-buffer records carry
    # the package. Unrelated stock-launcher crashes do not count as this defect.
    return [line for line in logcat.splitlines()
            if (re.search(r'\s' + re.escape(pid) + r'\s', line) or app in line)
            and re.search(r'FORTIFY|Fatal signal|tombstone|>>>.*' + re.escape(app), line, re.I)]


def controls():
    assert fatal_lines('10-14 00:00:00.000 123 124 F libc: Fatal signal 6', '123', 'app')
    assert not fatal_lines('10-14 00:00:00.000 555 556 F libc: Fatal signal 6', '123', 'app')
    assert fatal_lines('10-14 00:00:00.000 123 124 F libc: FORTIFY: destroyed mutex', '123', 'app')
    assert not fatal_lines('10-14 00:00:00.000 123 124 I AudioTrack: start', '123', 'app')
    return 'PASS: app crash detector rejects unrelated PIDs and ordinary audio startup.\n'


def image_distance(first, second):
    def samples(png):
        width, height, channels, rows = pdf_smoke.pixels(png)
        return [rows[int(y * (height - 1) / 17)][int(x * (width - 1) / 31) * channels + c]
                for y in range(18) for x in range(32) for c in range(3)]
    return sum(abs(a - b) for a, b in zip(samples(first), samples(second))) / (32 * 18 * 3 * 255)


def video_visible(png):
    width, height, channels, rows = pdf_smoke.pixels(png)
    count = 0
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            r, g, b = rows[y][x * channels:x * channels + 3]
            count += r < 30 and ((g > 220 and b < 30) or (b > 220 and g < 30))
    return count > width * height / 400


def cycle(h, name, count, allow_crash=False):
    physical = re.search(r'Physical size: (\d+)x(\d+)', h.shell('wm', 'size'))
    assert physical, 'Physical display dimensions unavailable'
    reduced = 'x'.join(str(int(int(n) * .9)) for n in physical.groups())
    session_pid = h.shell('pidof', h.app).strip()
    assert session_pid.isdigit()
    rows = []
    try:
        h.screenshot(name + '-system-before')
        for index in range(count):
            for size in (reduced, 'reset'):
                pid = h.shell('pidof', h.app).strip()
                before = h.log()
                reloads = before.count('Window size has changed from ')
                setups = before.count('Setting up AudioManager...')
                h.adb('logcat', '-c')
                h.shell('wm', 'size', size)
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    current_pid = h.shell('pidof', h.app, check=False).strip()
                    logs = h.adb('logcat', '-d', '-v', 'threadtime')
                    fatal = fatal_lines(logs, pid, h.app)
                    if fatal or current_pid != pid:
                        # A lifecycle stall without a native fatal is never a control hit.
                        assert allow_crash and fatal, (name, index, size, current_pid, fatal, logs)
                        row = dict(cycle=index + 1, size=size, pid=pid, crash=True, fatal=fatal)
                        break
                    current = h.log()
                    new_reloads = current.count('Window size has changed from ') - reloads
                    new_setups = current.count('Setting up AudioManager...') - setups
                    # Wait for actual reload and audio reinit, then let theme/resource
                    # reload finish before the next size event. No synthetic input sound.
                    if new_reloads > 0 and new_setups == new_reloads:
                        time.sleep(2)
                        assert h.shell('pidof', h.app).strip() == pid
                        assert not fatal_lines(h.adb('logcat', '-d', '-v', 'threadtime'), pid, h.app)
                        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app)
                        current = h.log()
                        assert current.count('Setting up AudioManager...') - setups == current.count(
                            'Window size has changed from ') - reloads
                        row = dict(cycle=index + 1, size=size, pid=pid, crash=False,
                                   reloads=new_reloads, audio_setups=new_setups)
                        break
                    time.sleep(.25)
                else:
                    raise AssertionError(f'{name}: reload failed to complete: cycle={index + 1}, size={size}')
                rows.append(row)
                (h.evidence / (name + '-cycles.txt')).write_text(json.dumps(rows, indent=2) + '\n')
                h.save_logs(f'{name}-{index + 1}-{size}')
                if row['crash']:
                    # Positive controls intentionally restart after each observed fatal;
                    # fixed and negative-control sessions may never change PID.
                    h.shell('am', 'force-stop', h.app)
                    h.launch()
        if not allow_crash:
            assert h.shell('pidof', h.app).strip() == session_pid
        h.screenshot(name + '-system-restored')
        # Prove the real system view was restored: Enter exposes the NES game
        # list, and Back returns to system selection, without launching a game.
        h.key('KEYCODE_ENTER')
        h.screenshot(name + '-gamelist-after')
        h.key('KEYCODE_DEL')
        h.screenshot(name + '-system-after-back')
        restored = (h.evidence / (name + '-system-restored.png')).read_bytes()
        gamelist = (h.evidence / (name + '-gamelist-after.png')).read_bytes()
        returned = (h.evidence / (name + '-system-after-back.png')).read_bytes()
        changed = image_distance(restored, gamelist)
        assert changed > .01, 'Enter did not expose a visibly different gamelist'
        assert image_distance(restored, returned) < changed / 2, 'Back did not restore system view'
        (h.evidence / (name + '-view-oracle.txt')).write_text(
            f'Enter image distance={changed}; Back distance={image_distance(restored, returned)}\n')
        return sum(row['crash'] for row in rows)
    finally:
        h.shell('wm', 'size', 'reset')
        (h.evidence / (name + '-cycles.txt')).write_text(json.dumps(rows, indent=2) + '\n')
        h.save_logs(name + '-final')


def run_control(harness):
    h = type('Harness', (), harness)
    assert h.device_api == 29 or h.television
    original = h.shell('cat', h.settings)
    document = h.launch_checks.settings_fragment(original)
    navigation = document.find("bool[@name='NavigationSounds']")
    assert navigation is None or navigation.get('value') == 'true', 'Control requires default sounds'
    crashes = cycle(h, 'audio-unfixed-default', 20, allow_crash=True)
    assert crashes > 0, 'No native crash in 20 unfixed cycles; positive control not established'
    set_setting(document, 'bool', 'NavigationSounds', 'false')
    h.user_file('settings/es_settings.xml', xml_settings(document))
    h.launch()
    negative = cycle(h, 'audio-unfixed-sounds-disabled', 20)
    (h.evidence / 'audio-control-summary.txt').write_text(
        f'Unfixed source={CONTROL_BASE}; default crashes={crashes}/40 resize actions (20 cycles); '
        f'NavigationSounds=false crashes={negative}/40.\n')
    raise ControlComplete()


def video_fixture(path):
    # Original 64x64 RGB animation + 440 Hz stereo PCM in an AVI container.
    # stdlib only; no downloaded media, codec binary or test dependency.
    def chunk(kind, data):
        return kind + struct.pack('<I', len(data)) + data + b'\0' * (len(data) % 2)

    def listing(kind, data):
        return chunk(b'LIST', kind + data)

    frames = 50
    header = struct.pack('<14I', 100000, 400000, 0, 0x100, frames, 0, 2, 0, 64, 64, 0, 0, 0, 0)
    def stream(kind, handler, scale, rate, length, sample_size):
        return struct.pack('<4s4sIHH8I4h', kind, handler, 0, 0, 0, 0, scale, rate, 0,
                           length, 0, 0xffffffff, sample_size, 0, 0, 64 if kind == b'vids' else 0,
                           64 if kind == b'vids' else 0)
    video = listing(b'strl', chunk(b'strh', stream(b'vids', b'DIB ', 1, 10, frames, 0)) +
                    chunk(b'strf', struct.pack('<IiiHHIIiiII', 40, 64, 64, 1, 24, 0, 64*64*3, 0, 0, 0, 0)))
    # WAVEFORMATEXTENSIBLE declares the stereo channel mask explicitly. A plain
    # PCM header leaves FFmpeg's channel layout unspecified on some versions.
    pcm_format = struct.pack('<HHIIHHHHI', 0xfffe, 2, 44100, 44100*4, 4, 16, 22, 16, 3)
    pcm_format += bytes.fromhex('0100000000001000800000aa00389b71')
    audio = listing(b'strl', chunk(b'strh', stream(b'auds', b'\0'*4, 4, 44100*4, frames*4410, 4)) +
                    chunk(b'strf', pcm_format))
    movie = b''
    for frame in range(frames):
        colour = b'\0\xff\0' if frame % 10 < 5 else b'\xff\0\0'
        movie += chunk(b'00db', colour * (64*64))
        pcm = b''.join(struct.pack('<hh', value, value) for value in
                       (int(8000 * math.sin(i * 2 * math.pi * 440 / 44100))
                        for i in range(frame*4410, (frame+1)*4410)))
        movie += chunk(b'01wb', pcm)
    content = listing(b'hdrl', chunk(b'avih', header) + video + audio) + listing(b'movi', movie)
    path.write_bytes(b'RIFF' + struct.pack('<I', len(content) + 4) + b'AVI ' + content)


def run(harness):
    h = type('Harness', (), harness)
    (h.evidence / 'audio-assertion-controls.txt').write_text(controls())
    if h.device_api != 29 and not h.television:
        return
    assert cycle(h, 'audio-fixed-default', 20) == 0
    original = h.shell('cat', h.settings)
    document = h.launch_checks.settings_fragment(original)
    media = '/sdcard/ESDEPlusAudioMedia'
    fixture = h.evidence / 'audio-video.avi'
    video_fixture(fixture)
    h.shell('mkdir', '-p', media + '/nes/videos')
    h.adb('push', str(fixture), media + '/nes/videos/Smoke Alpha.avi')
    set_setting(document, 'string', 'MediaDirectory', media)
    set_setting(document, 'bool', 'ViewsVideoAudio', 'true')
    set_setting(document, 'string', 'ThemeVariant', 'textlistWithVideos')
    try:
        h.user_file('settings/es_settings.xml', xml_settings(document))
        h.launch()
        h.key('KEYCODE_ENTER')
        h.wait_for(lambda: video_visible(h.adb('exec-out', 'screencap', '-p', binary=True)),
                   'original audio-track video visibly plays before reload')
        h.screenshot('audio-video-before-reload')
        h.save_logs('audio-video-before-reload')
        assert cycle(h, 'audio-fixed-video', 1) == 0
        h.key('KEYCODE_ENTER')
        h.wait_for(lambda: video_visible(h.adb('exec-out', 'screencap', '-p', binary=True)),
                   'original audio-track video visibly plays after reload')
        h.screenshot('audio-video-after-reload')
        h.save_logs('audio-video-after-reload')
        (h.evidence / 'audio-fixed-summary.txt').write_text(
            'PASS: 20 default-sound size/reset cycles, zero native fatals, unchanged PID, '
            'audio setup count equals reload count; original audio-track video fixture reload.\n'
            'Screenshots/logs retain system/gamelist restoration evidence. Real nonzero navigation '
            'and video PCM mixing after reinit is asserted by the Linux detector.\n')
    finally:
        h.user_file('settings/es_settings.xml', original)
        h.start_entry('HomeEntry', 'android.intent.category.HOME')
        h.configured_system('audio-restored-home')


if __name__ == '__main__':
    {'build-control': build_control, 'control': control_launch, 'controls': controls}[sys.argv[1]]()
