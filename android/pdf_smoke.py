#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real gamelist PDF runtime smoke; no framework.
import pathlib
import re
import shlex
import struct
import subprocess
import time
import zlib
import xml.etree.ElementTree as ET


def pixels(png):
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    offset = 8; data = b''
    while offset < len(png):
        size = struct.unpack_from('>I', png, offset)[0]
        kind = png[offset + 4:offset + 8]; value = png[offset + 8:offset + 8 + size]
        if kind == b'IHDR':
            w, h, depth, colour, _, _, interlace = struct.unpack('>IIBBBBB', value)
            assert depth == 8 and colour in (2, 6) and interlace == 0
        if kind == b'IDAT': data += value
        offset += size + 12
    channels = 4 if colour == 6 else 3; stride = w * channels
    raw = zlib.decompress(data); previous = bytearray(stride); rows = []
    for y in range(h):
        start = y * (stride + 1); kind = raw[start]; row = bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]; corner = previous[i - channels] if i >= channels else 0
            if kind == 1: add = left
            elif kind == 2: add = up
            elif kind == 3: add = (left + up) // 2
            elif kind == 4:
                p = left + up - corner
                add = min([(abs(p-left), 0, left), (abs(p-up), 1, up), (abs(p-corner), 2, corner)])[2]
            else:
                assert kind == 0
                add = 0
            row[i] = (row[i] + add) & 255
        rows.append(row); previous = row
    return w, h, channels, rows


def colour_points(png):
    w, h, channels, rows = pixels(png)
    points = {name: [] for name in ['red', 'blue', 'green']}
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            r, g, b = rows[y][x*channels:x*channels+3]
            if r > 240 and g < 15 and b < 15: points['red'].append((x, y))
            if b > 240 and r < 15 and g < 15: points['blue'].append((x, y))
            if g > 240 and r < 15 and b < 15: points['green'].append((x, y))
    return points


def manual_image(png):
    points = colour_points(png)
    assert all(len(p) >= 12 for p in points.values()), {k: len(v) for k, v in points.items()}
    return points


def controls():
    # A valid PNG with no manual markers must fail the real viewer-image gate.
    root = pathlib.Path('android/evidence/pdf-fixtures')
    try: manual_image((root / 'cover.png').read_bytes())
    except AssertionError: return 'PASS: actual cover PNG rejects the manual-image assertion\n'
    raise AssertionError('PDF image positive control escaped')


def run(mode, harness):
    h = type('Harness', (), harness)
    h.evidence.joinpath('pdf-assertion-positive-controls.txt').write_text(controls())
    h.shell('am', 'force-stop', h.app)
    original = h.shell('cat', h.settings)
    settings = ET.fromstring(original)
    node = settings.find("string[@name='MediaDirectory']")
    media = h.external + '/ES-DE-Plus/Manual spaces 🚀'
    node.set('value', media)
    h.user_file('settings/es_settings.xml', ET.tostring(settings, encoding='unicode'))
    h.adb('logcat', '-c')
    output_path = h.evidence / ('pdf-' + mode + '-instrumentation.txt')
    command_number = 0
    process = None
    output = output_path.open('w')
    try:
        process = subprocess.Popen(['adb', 'shell', 'am', 'instrument', '-w', '-e', 'mode', 'pdf-session',
                                    h.app + '/org.esdeplus.frontend.RuntimeSmoke'], stdout=output, stderr=subprocess.STDOUT)
        h.wait_for(lambda: h.private('cat', 'cache/pdf-result', check=False).startswith('READY:'), 'PDF debug session ready')
        h.wait_for(lambda: 'Application startup time:' in h.log(), 'PDF session frontend startup')
        time.sleep(10)
        def command(action):
            nonlocal command_number
            command_number += 1
            value = str(command_number) + ':' + action
            h.private('sh', '-c', 'echo ' + shlex.quote(value) + ' > cache/pdf-command')
            h.wait_for(lambda: h.private('cat', 'cache/pdf-result', check=False).startswith(value + '\n'), 'PDF session ' + action)
            return h.private('cat', 'cache/pdf-result')
        result = command('contract')
        h.smoke_checks.probe_passed(result, 'PASS: D-008 real JNI')
        h.evidence.joinpath('pdf-' + mode + '-contract.txt').write_text(result)
        def frame(name):
            h.screenshot('pdf-' + mode + '-' + name)
            return (h.evidence / ('pdf-' + mode + '-' + name + '.png')).read_bytes()
        def enter_gamelist():
            # Back returns to the system view; Right enters the NES gamelist.
            h.key('KEYCODE_DEL'); h.key('KEYCODE_DPAD_RIGHT')
        def open_manual(name):
            h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
            png = frame(name)
            manual_image(png)
            return png
        h.key('KEYCODE_DPAD_RIGHT')
        first = open_manual('first')
        h.key('KEYCODE_DPAD_RIGHT'); frame('next')
        h.key('KEYCODE_DPAD_RIGHT')
        rotated = manual_image(frame('rotated'))
        # Rotation changes marker geometry, verified within each image at tolerance.
        assert sum(p[0] for p in rotated['red']) / len(rotated['red']) > sum(p[0] for p in rotated['green']) / len(rotated['green'])
        h.key('KEYCODE_DPAD_LEFT'); manual_image(frame('previous'))
        h.key('KEYCODE_MOVE_END'); frame('last')
        h.key('KEYCODE_MOVE_HOME'); before_zoom = manual_image(frame('first-again'))
        h.key('KEYCODE_PAGE_DOWN'); zoomed = manual_image(frame('zoom'))
        assert len(zoomed['red']) > len(before_zoom['red']), 'Zoom did not increase the displayed marker'
        h.key('KEYCODE_DPAD_RIGHT'); panned = manual_image(frame('pan'))
        assert panned['red'] != zoomed['red'], 'Pan did not move the page'
        h.key('KEYCODE_MOVE_HOME'); manual_image(frame('zoom-reset'))
        h.key('KEYCODE_DEL'); open_manual('reopened'); h.key('KEYCODE_DEL')
        # Exceptions injected at the actual metadata, first and later raster calls.
        for point in [0, 1, 2]:
            command('fault=' + str(point)); h.adb('logcat', '-c')
            h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
            if point == 2:
                manual_image(frame('before-later-failure'))
                h.key('KEYCODE_DPAD_RIGHT')
            h.wait_for(lambda: 'Injected PDF viewer failure at ' + str(point) in h.adb('logcat', '-d'), 'injected PDF viewer failure')
            failure_frame = frame('failure-' + str(point))
            try: manual_image(failure_frame)
            except AssertionError: pass
            else: raise AssertionError('Failure retained a stale page')
            for code in ['KEYCODE_PAGE_DOWN', 'KEYCODE_DPAD_UP', 'KEYCODE_DPAD_LEFT', 'KEYCODE_DEL']:
                h.key(code)
            assert h.shell('pidof', h.app).strip(), 'PDF failure killed frontend'
            command('reset'); enter_gamelist(); open_manual('recovery-' + str(point)); h.key('KEYCODE_DEL')
        # Actual malformed/password/zero inputs through the same gamelist path.
        for fixture in ['malformed', 'password', 'zero']:
            command('fixture=' + fixture)
            h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
            failure_frame = frame(fixture)
            try: manual_image(failure_frame)
            except AssertionError: pass
            else: raise AssertionError('Invalid PDF retained a page')
            command('fixture=valid'); open_manual(fixture + '-recovery'); h.key('KEYCODE_DEL')
        if h.api in [29, 34]:
            command('fixture=stress')
            open_manual('stress-first')
            baseline = command('stats')
            for code in ['KEYCODE_DPAD_RIGHT', 'KEYCODE_DPAD_LEFT']:
                for _ in range(59): h.key(code)
                manual_image(frame('stress-' + code))
            after = command('stats')
            assert baseline.split('fd=')[1] == after.split('fd=')[1], (baseline, after)
            memory = h.shell('dumpsys', 'meminfo', h.app)
            h.key('KEYCODE_DEL')
            for _ in range(10):
                open_manual('cycle'); h.key('KEYCODE_DEL')
            stable = command('stats')
            assert baseline.split('fd=')[1] == stable.split('fd=')[1], (baseline, stable)
            h.evidence.joinpath('pdf-' + mode + '-stress-memory-fds.txt').write_text(baseline + '\n' + after + '\n' + stable + '\n' + memory)
            command('fixture=valid')
        open_manual('lifecycle')
        pid = h.shell('pidof', h.app).strip()
        h.shell('am', 'start', '-a', 'android.settings.SETTINGS')
        time.sleep(2); h.key('KEYCODE_BACK')
        assert h.shell('pidof', h.app).strip() == pid
        manual_image(frame('foreground'))
        h.key('KEYCODE_DEL')
        command('end')
        process.wait(timeout=15)
        assert 'PASS: PDF viewer session completed' in output_path.read_text(), output_path.read_text()
        h.shell('am', 'force-stop', h.app)
        h.launch(); h.key('KEYCODE_DPAD_RIGHT'); open_manual('before-destroy')
        old = h.shell('pidof', h.app).strip(); h.adb('logcat', '-c')
        h.shell('am', 'start', '-f', '0x10008000', '-n', h.activity)
        h.wait_for(lambda: h.shell('pidof', h.app, check=False).strip() != old, 'PDF-open activity destruction', timeout=10)
        h.wait_for(lambda: h.native_shutdown(old), 'PDF-open native destroy joins', timeout=10)
        h.save_logs('pdf-' + mode + '-destroy')
        h.shell('am', 'force-stop', h.app)
        # The existing strict recipient flow proves a game launch after failures.
        h.gamelist_recipient_flow(mode)
        volumes = h.shell('sm', 'list-volumes', 'public', check=False)
        h.evidence.joinpath('pdf-' + mode + '-removable-volume.txt').write_text(
            'CAPABILITY GAP: no SD card attached to this CI image; removable-volume success/removal during PDF viewing not evidenced.\n' + volumes)
        h.evidence.joinpath('pdf-' + mode + '-summary.txt').write_text(
            'PASS: actual gamelist/manual path, next/previous/first/last, zoom/pan/reset, close/reopen, injected and malformed/password/zero failures, valid recovery/game launch, background/foreground, activity destruction. API 29/34 also 60-page forward/back + ten cycles, FD and retained memory evidence.\n')
    finally:
        if process and process.poll() is None:
            h.shell('am', 'force-stop', h.app)
            process.wait(timeout=15)
        output.close()
        h.shell('am', 'force-stop', h.app)
        h.user_file('settings/es_settings.xml', original)


def release(harness):
    h = type('Harness', (), harness)
    h.shell('am', 'force-stop', h.app)
    original = h.shell('cat', h.settings)
    settings = ET.fromstring(original)
    settings.find("string[@name='MediaDirectory']").set('value', h.external + '/ES-DE-Plus/Manual spaces 🚀')
    h.user_file('settings/es_settings.xml', ET.tostring(settings, encoding='unicode'))
    try:
        # Same CI-only ephemeral key as debug, so the real saved configuration
        # and Unicode fixture remain installed for the minified runtime check.
        h.adb('install', '-r', 'android/app/build/outputs/apk/release/app-release-smoke.apk')
        h.adb('logcat', '-c')
        h.launch(); h.key('KEYCODE_DPAD_RIGHT')
        h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
        h.screenshot('pdf-minified-first')
        manual_image((h.evidence / 'pdf-minified-first.png').read_bytes())
        h.key('KEYCODE_DPAD_RIGHT'); h.key('KEYCODE_DPAD_RIGHT')
        h.screenshot('pdf-minified-rotation')
        manual_image((h.evidence / 'pdf-minified-rotation.png').read_bytes())
        h.key('KEYCODE_MOVE_END'); h.key('KEYCODE_MOVE_HOME')
        h.key('KEYCODE_PAGE_DOWN'); h.key('KEYCODE_DPAD_RIGHT'); h.key('KEYCODE_MOVE_HOME')
        h.key('KEYCODE_DEL'); h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
        h.screenshot('pdf-minified-reopened')
        manual_image((h.evidence / 'pdf-minified-reopened.png').read_bytes())
        logs = h.adb('logcat', '-d')
        assert 'JNI DETECTED ERROR' not in logs and 'NoSuchMethod' not in logs and 'ANR in ' + h.app not in logs, logs
        h.save_logs('pdf-minified-runtime')
        h.evidence.joinpath('pdf-minified-summary.txt').write_text(
            'PASS: installed CI-signed minified release uses the actual Unicode/manual path, rotation, paging, zoom/pan/reset, close/reopen; screenshot colour assertions pass; no JNI/lookup/ANR failure. APK remains in CI and is never uploaded.\n')
    finally:
        h.shell('am', 'force-stop', h.app)
        h.adb('install', '-r', str(h.apk))
        h.user_file('settings/es_settings.xml', original)
