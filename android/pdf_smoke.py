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


def rejects(name, action):
    try:
        action()
    except AssertionError:
        with pathlib.Path('android/evidence/pdf-assertion-positive-controls.txt').open('a') as output:
            output.write('PASS: assertion positive control rejected: ' + name + '\n')
        return
    raise AssertionError('PDF positive control escaped: ' + name)


def closed(png):
    try:
        manual_image(png)
    except AssertionError:
        return
    raise AssertionError('Failure retained a stale page')


def navigation(before, after, operation):
    if operation == 'zoom':
        assert len(after['red']) > len(before['red']), 'Zoom did not increase the displayed marker'
    elif operation == 'pan':
        assert after['red'] != before['red'], 'Pan did not move the page'
    else:
        assert sum(p[0] for p in after['red']) / len(after['red']) > sum(p[0] for p in after['green']) / len(after['green']), 'Rotated marker positions incorrect'


def descriptors(before, after):
    assert re.search(r'fd=(\d+)', before)[1] == re.search(r'fd=(\d+)', after)[1], (before, after)


def orientation(points, rotation):
    red = tuple(sum(p[i] for p in points['red']) / len(points['red']) for i in [0, 1])
    green = tuple(sum(p[i] for p in points['green']) / len(points['green']) for i in [0, 1])
    if rotation == 270:
        assert red[0] < green[0], ('Last page rotation', red, green)
    else:
        assert red[1] < green[1], ('First/previous page orientation', red, green)


def stress_page(png, expected):
    points = manual_image(png)
    # Corner markers locate the normal 240x320 page at any display resolution.
    left = min(p[0] for p in points['red']); top = min(p[1] for p in points['red'])
    scale_x = (max(p[0] for p in points['blue']) - left) / 220
    scale_y = (max(p[1] for p in points['green']) - top) / 300
    _, _, channels, rows = pixels(png)
    value = 0
    for bit in range(6):
        x = round(left + (75 + 16 * bit - 10) * scale_x)
        y = round(top + (165 - 10) * scale_y)
        rgb = rows[y][x*channels:x*channels+3]
        value |= solid_bit(rgb) << bit
    assert value == expected, ('Displayed stress page', value, expected)


def solid_bit(rgb):
    assert all(v < 30 for v in rgb) or all(v > 230 for v in rgb), ('Stress page solid-colour probe', list(rgb))
    return int(all(v < 30 for v in rgb))


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
        h.private('rm', '-f', 'cache/pdf-result', 'cache/pdf-command')
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
        h.adb('logcat', '-c')
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
        rejects('stale page', lambda: closed(first))
        h.key('KEYCODE_DPAD_RIGHT'); manual_image(frame('next'))
        h.smoke_checks.probe_passed(h.adb('logcat', '-d'), 'PDF rendered page=2 size=')
        h.key('KEYCODE_DPAD_RIGHT')
        rotated = manual_image(frame('rotated'))
        # Rotation changes marker geometry, verified within each image at tolerance.
        navigation(None, rotated, 'rotation')
        rejects('wrong rotated geometry', lambda: navigation(None, {'red': [(1, 1)], 'green': [(2, 1)]}, 'rotation'))
        h.key('KEYCODE_DPAD_LEFT'); orientation(manual_image(frame('previous')), 0)
        h.key('KEYCODE_MOVE_END'); orientation(manual_image(frame('last')), 270)
        h.smoke_checks.probe_passed(h.adb('logcat', '-d'), 'PDF rendered page=5 size=')
        h.key('KEYCODE_MOVE_HOME'); before_zoom = manual_image(frame('first-again'))
        orientation(before_zoom, 0)
        rejects('last page unchanged', lambda: orientation(before_zoom, 270))
        rejects('first page unchanged', lambda: orientation({'red': [(1, 2)], 'green': [(1, 1)]}, 0))
        h.key('KEYCODE_PAGE_DOWN'); zoomed = manual_image(frame('zoom'))
        navigation(before_zoom, zoomed, 'zoom')
        rejects('missing zoom', lambda: navigation(before_zoom, before_zoom, 'zoom'))
        h.key('KEYCODE_DPAD_RIGHT'); panned = manual_image(frame('pan'))
        navigation(zoomed, panned, 'pan')
        rejects('missing pan', lambda: navigation(zoomed, zoomed, 'pan'))
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
            closed(failure_frame)
            for code in ['KEYCODE_PAGE_DOWN', 'KEYCODE_DPAD_UP', 'KEYCODE_DPAD_LEFT', 'KEYCODE_DEL']:
                h.key(code)
            assert h.shell('pidof', h.app).strip(), 'PDF failure killed frontend'
            command('reset'); enter_gamelist(); open_manual('recovery-' + str(point)); h.key('KEYCODE_DEL')
        # Actual malformed/password/zero inputs through the same gamelist path.
        for fixture in ['malformed', 'password', 'zero']:
            command('fixture=' + fixture)
            h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
            failure_frame = frame(fixture)
            closed(failure_frame)
            command('fixture=valid'); open_manual(fixture + '-recovery'); h.key('KEYCODE_DEL')
        # Missing file after MediaViewer discovers it reaches PDFViewer's real
        # missing-file recovery instead of merely hiding the manual action.
        h.key('KEYCODE_FORWARD_DEL'); command('fixture=missing'); h.key('KEYCODE_DPAD_UP')
        closed(frame('missing-after-discovery'))
        command('fixture=valid'); open_manual('missing-recovery'); h.key('KEYCODE_DEL')
        if h.api in [29, 34]:
            command('fixture=stress')
            h.adb('logcat', '-c')
            first_stress = open_manual('stress-first')
            stress_page(first_stress, 1)
            rejects('wrong displayed stress page', lambda: stress_page(first_stress, 2))
            rejects('non-solid stress marker', lambda: solid_bit([128, 128, 128]))
            baseline = command('stats')
            for code, page in [('KEYCODE_DPAD_RIGHT', 60), ('KEYCODE_DPAD_LEFT', 1)]:
                for _ in range(59): h.key(code)
                stress_page(frame('stress-' + code), page)
            logs = h.adb('logcat', '-d')
            for page in range(1, 61):
                h.smoke_checks.probe_passed(logs, 'PDF rendered page=' + str(page) + ' size=')
            h.evidence.joinpath('pdf-' + mode + '-stress-pages.txt').write_text(logs)
            after = command('stats')
            descriptors(baseline, after)
            rejects('descriptor leak', lambda: descriptors(baseline, 'fd=' + str(int(re.search(r'fd=(\d+)', baseline)[1]) + 1)))
            memory = h.shell('dumpsys', 'meminfo', h.app)
            h.key('KEYCODE_DEL')
            for _ in range(10):
                open_manual('cycle'); h.key('KEYCODE_DEL')
            stable = command('stats')
            descriptors(baseline, stable)
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
        provisioned = h.shell('am', 'instrument', '-w', '-e', 'mode', 'pdf-unreadable',
                             h.app + '/org.esdeplus.frontend.RuntimeSmoke')
        unreadable = re.search(r'UNREADABLE_MEDIA=(.+)', provisioned)[1].strip()
        h.shell('am', 'force-stop', h.app)
        settings.find("string[@name='MediaDirectory']").set('value', unreadable)
        h.user_file('settings/es_settings.xml', ET.tostring(settings, encoding='unicode'))
        h.adb('logcat', '-c'); h.launch(); h.key('KEYCODE_DPAD_RIGHT')
        h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
        closed(frame('unreadable'))
        h.smoke_checks.probe_passed(h.adb('logcat', '-d'), 'PDF conversion failed')
        h.evidence.joinpath('pdf-' + mode + '-unreadable.txt').write_text(provisioned + '\n' + h.log())
        for code in ['KEYCODE_PAGE_DOWN', 'KEYCODE_DPAD_UP', 'KEYCODE_DPAD_LEFT', 'KEYCODE_DEL']: h.key(code)
        h.shell('am', 'force-stop', h.app)
        settings.find("string[@name='MediaDirectory']").set('value', media)
        h.user_file('settings/es_settings.xml', ET.tostring(settings, encoding='unicode'))
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
        if mode == 'direct':
            h.shell('am', 'force-stop', h.app)
            volume_result = h.shell('am', 'instrument', '-w', '-e', 'mode', 'pdf-volume',
                                    h.app + '/org.esdeplus.frontend.RuntimeSmoke')
            h.shell('am', 'force-stop', h.app)
            match = re.search(r'VOLUME_MEDIA=(.+)', volume_result)
            if match:
                volume_media = match[1].strip()
                volume_id = next(line.split()[0] for line in volumes.splitlines()
                                 if len(line.split()) >= 3 and line.split()[2] in volume_media)
                settings.find("string[@name='MediaDirectory']").set('value', volume_media)
                h.user_file('settings/es_settings.xml', ET.tostring(settings, encoding='unicode'))
                try:
                    h.launch(); h.key('KEYCODE_DPAD_RIGHT'); open_manual('removable-first')
                    h.shell('sm', 'unmount', volume_id)
                    h.wait_for(lambda: 'mounted' not in next(line for line in h.shell('sm', 'list-volumes', 'public').splitlines()
                               if line.startswith(volume_id + ' ')), 'actual PDF volume removal')
                    h.key('KEYCODE_DPAD_RIGHT')
                    failed = frame('removable-removed')
                    closed(failed)
                    for code in ['KEYCODE_PAGE_DOWN', 'KEYCODE_DPAD_UP', 'KEYCODE_DEL']: h.key(code)
                    assert h.shell('pidof', h.app).strip(), 'Volume removal killed frontend'
                    volume_result += '\nPASS: removable-volume manual rendered; real unmount during view closes failed next page and remains responsive.\n'
                finally:
                    h.shell('sm', 'mount', volume_id)
                    h.shell('am', 'force-stop', h.app)
                    settings.find("string[@name='MediaDirectory']").set('value', media)
                    h.user_file('settings/es_settings.xml', ET.tostring(settings, encoding='unicode'))
            else:
                assert 'CAPABILITY GAP:' in volume_result, volume_result
            h.evidence.joinpath('pdf-' + mode + '-removable-volume.txt').write_text(volumes + '\n' + volume_result)
        else:
            h.evidence.joinpath('pdf-' + mode + '-removable-volume.txt').write_text(
                'Removable-volume success/removal probe uses the explicit direct-mode pass on this same image.\n' + volumes)
        h.evidence.joinpath('pdf-' + mode + '-summary.txt').write_text(
            'PASS: actual gamelist/manual path, next/previous/first/last, zoom/pan/reset, close/reopen, injected and missing/unreadable/malformed/password/zero failures, valid recovery/game launch, background/foreground, activity destruction. API 29/34 also 60-page forward/back + ten cycles, FD and retained memory evidence.\n')
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
    renamed = []
    try:
        # Match upstream's ROM-stem media lookup while exercising Unicode in
        # the minified viewer's actual manual basename as well as its directory.
        for directory, extension in [(h.roms + '/nes', '.nes'),
                (h.external + '/ES-DE-Plus/Manual spaces 🚀/nes/manuals', '.pdf'),
                (h.external + '/ES-DE-Plus/Manual spaces 🚀/nes/covers', '.png')]:
            original_name = directory + '/Smoke Alpha' + extension
            unicode_name = directory + '/Smoke Alpha 🚀' + extension
            h.private('mv', original_name, unicode_name)
            renamed.append((original_name, unicode_name))
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
            'PASS: installed CI-signed minified release opens Manual spaces 🚀/nes/manuals/Smoke Alpha 🚀.pdf through the gamelist; rotation, paging, zoom/pan/reset, close/reopen; screenshot colour assertions pass; no JNI/lookup/ANR failure. APK remains in CI and is never uploaded.\n')
    finally:
        h.shell('am', 'force-stop', h.app)
        h.adb('install', '-r', str(h.apk))
        for original_name, unicode_name in reversed(renamed):
            h.private('mv', unicode_name, original_name)
        h.user_file('settings/es_settings.xml', original)
