#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real gamelist PDF runtime smoke; no framework.
import pathlib
import os
import pdf_close_probe
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


def colour_points(png, decoded=None):
    w, h, channels, rows = pixels(png) if decoded is None else decoded
    points = {name: [] for name in ['red', 'blue', 'green']}
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            r, g, b = rows[y][x*channels:x*channels+3]
            if r > 240 and g < 15 and b < 15: points['red'].append((x, y))
            if b > 240 and r < 15 and g < 15: points['blue'].append((x, y))
            if g > 240 and r < 15 and b < 15: points['green'].append((x, y))
    return points


def manual_image(png, decoded=None):
    points = colour_points(png, decoded)
    assert all(len(p) >= 12 for p in points.values()), {k: len(v) for k, v in points.items()}
    return points


def manual_visible(png):
    try:
        manual_image(png)
    except AssertionError:
        return False
    return True


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
    decoded = pixels(png)
    points = manual_image(png, decoded)
    # Corner markers locate the normal 240x320 page at any display resolution.
    left = min(p[0] for p in points['red']); top = min(p[1] for p in points['red'])
    scale_x = (max(p[0] for p in points['blue']) - left) / 220
    scale_y = (max(p[1] for p in points['green']) - top) / 300
    _, _, channels, rows = decoded
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


def displayed_page(png, expected):
    try:
        stress_page(png, expected)
    except AssertionError:
        return False
    return True


def runtime_log(output, app):
    assert not any(error in output for error in ['JNI DETECTED ERROR', 'NoSuchMethod', 'ANR in ' + app]), output


def volume_mounted(output, identifier):
    return any(len(fields) >= 2 and fields[0] == identifier and fields[1] == 'mounted'
               for fields in (line.split() for line in output.splitlines()))


def wait_for_focus(h, package, description):
    h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), package), description)


def controls():
    # A valid PNG with no manual markers must fail the real viewer-image gate.
    root = pathlib.Path('android/evidence/pdf-fixtures')
    png = (root / 'cover.png').read_bytes()
    checks = []
    try: manual_image(png)
    except AssertionError: checks.append('PASS: actual cover PNG rejects the manual-image assertion')
    else: raise AssertionError('PDF image positive control escaped')
    assert not manual_visible(png), 'Cover escaped manual readiness control'
    checks.append('PASS: actual cover PNG rejects manual readiness')
    depth = bytearray(png); depth[24] = 16
    length = struct.unpack_from('>I', png, 33)[0]
    filtered = bytearray(zlib.decompress(png[41:41 + length])); filtered[0] = 5
    compressed = zlib.compress(filtered)
    bad_filter = png[:33] + struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', zlib.crc32(b'IDAT' + compressed)) + png[45 + length:]
    for name, invalid in [('PNG signature', b'invalid!' + png[8:]), ('PNG depth', depth), ('PNG filter', bad_filter)]:
        try: pixels(invalid)
        except AssertionError: checks.append('PASS: PNG decoder control rejected: ' + name)
        else: raise AssertionError('PNG control escaped: ' + name)
    assert session_acknowledged('16:end\nEND', '16:end', True, 'PASS: session completed')
    assert not session_acknowledged('15:reset\nRESET', '16:end', False, '')
    checks.append('PASS: final acknowledgement remains valid after instrumentation exit; stale live ack waits')
    for result in ['', '15:reset\nRESET', '16:end-wrong\nEND']:
        try: session_acknowledged(result, '16:end', True, 'failed session')
        except AssertionError: checks.append('PASS: terminated session without exact acknowledgement rejected')
        else: raise AssertionError('PDF session exit control escaped')
    import smoke_checks
    for package in ('org.esdeplus.stub', 'org.esdeplus.frontend'):
        live = 'WINDOW MANAGER DISPLAY CONTENTS\nmCurrentFocus=Window{x u0 ' + package + '/.Activity}'
        stale = 'WINDOW MANAGER LAST ANR\nmCurrentFocus=Window{x u0 other/.Activity}\n' + live
        class FocusHarness:
            def __init__(self, current, full):
                self.current, self.full = current, full
                self.smoke_checks = smoke_checks
                self.samples = 0
            def shell(self, *args):
                assert args == ('dumpsys', 'window'), args
                return self.full
            def focused_window(self):
                self.samples += 1
                return smoke_checks.live_window(self.current)
            def wait_for(self, predicate, description):
                assert predicate(), description
        h = FocusHarness(live, stale)
        assert not smoke_checks.package_window_focused(h.shell('dumpsys', 'window'), package)
        wait_for_focus(h, package, 'PDF live focus despite stale ANR')
        assert h.samples == 1
        checks.append('PASS: PDF focus wait ignores stale ANR for ' + package)
        wrong = FocusHarness(live.replace(package, 'other'), stale.replace('other', package))
        try: wait_for_focus(wrong, package, 'PDF wrong live focus')
        except AssertionError: checks.append('PASS: PDF wrong live owner rejected despite matching cached ANR for ' + package)
        else: raise AssertionError('PDF live focus control escaped')
        assert wrong.samples == 1
    checks.append(pdf_close_probe.controls())
    return '\n'.join(checks) + '\n'


def settings_xml(document):
    # Upstream persists sibling settings, not the parser's temporary wrapper.
    return '<?xml version="1.0"?>\n' + ''.join(ET.tostring(child, encoding='unicode') for child in document)


def session_acknowledged(result, value, finished, diagnostic):
    # "end" writes its acknowledgement and exits normally. A completed
    # instrumentation process is only an error when its expected ack is absent.
    if result.startswith(value + '\n'):
        return True
    if finished:
        raise AssertionError('PDF session ended before ' + value + ': ' + diagnostic)
    return False


def run(mode, harness):
    h = type('Harness', (), harness)
    diagnostic_cycles = int(os.environ.get('ESDE_PDF_CLOSE_DIAGNOSTIC_CYCLES', '0'))
    assert 0 <= diagnostic_cycles <= 20, 'PDF diagnostic cycles must be 0..20'
    input_trace_level = h.shell('getprop', 'log.tag.ESDE-PDF-CLOSE').strip()
    h.evidence.joinpath('pdf-assertion-positive-controls.txt').write_text(controls())
    h.shell('am', 'force-stop', h.app)
    original = h.shell('cat', h.settings)
    settings = h.launch_checks.settings_fragment(original)
    node = settings.find("string[@name='MediaDirectory']")
    media = h.data_root + '/Manual spaces 🚀'
    node.set('value', media)
    # Runtime Debug logging includes SDL repeats and Window's blocked-input
    # state before any early return, and mirrors native logs into logcat.
    for name, value in [('DebugMode', 'true'), ('DebugSkipInputLogging', 'false')]:
        option = settings.find("bool[@name='" + name + "']")
        if option is None:
            option = ET.SubElement(settings, 'bool', name=name)
        option.set('value', value)
    h.user_file('settings/es_settings.xml', settings_xml(settings))
    h.adb('logcat', '-c')
    output_path = h.evidence / ('pdf-' + mode + '-instrumentation.txt')
    command_number = 0
    process = None
    output = output_path.open('w')
    try:
        # G-28 instrumentation: remove this log-tag switch/restore with the host
        # trace when the root cause is found or 20 consecutive main runs lose no first key.
        h.shell('setprop', 'log.tag.ESDE-PDF-CLOSE', 'DEBUG')
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
            # The instrumentation polls every 50 ms. Publish a complete command
            # by rename so it cannot observe a truncated/partially written file.
            h.private('sh', '-c', 'printf "%s\\n" ' + shlex.quote(value) +
                      ' > cache/pdf-command.next && mv cache/pdf-command.next cache/pdf-command')
            def completed():
                # Sample exit before reading: if exit has been observed, all
                # preceding ack writes are complete. Sampling it afterward can
                # mistake a command completing between the two reads for failure.
                finished = process.poll() is not None
                result = h.private('cat', 'cache/pdf-result', check=False)
                return session_acknowledged(result, value, finished, output_path.read_text())
            h.wait_for(completed, 'PDF session ' + action)
            return h.private('cat', 'cache/pdf-result')
        def resumed_input(stage, pid):
            latest = {}
            def ready():
                logs = h.adb('logcat', '-d', '-v', 'threadtime')
                release = pdf_close_probe.resume_input_release(logs, pid)
                if release is None:
                    return False
                latest.update(logs=logs, release=release)
                return True
            try:
                h.wait_for(ready, 'PDF foreground input block released ' + stage)
            except Exception:
                pdf_close_probe.CloseProbe(h, mode).capture('resume-' + stage + '-timeout')
                raise
            h.evidence.joinpath('pdf-' + mode + '-input-ready-' + stage + '.txt').write_text(latest['logs'])
            pdf_close_probe.CloseProbe(h, mode).record(
                event='input-ready', stage=stage, pid=pid, **latest['release'])
        def paused_command(action, stage):
            # Active frames create and retire graphics fence descriptors. Use
            # the real paused host for every full-process descriptor snapshot.
            pid = h.shell('pidof', h.app).strip()
            _, before = h.activity_records()
            # TV Settings can be an overlay that leaves SDL RESUMED. The
            # existing recipient has an opaque full-screen activity on every
            # image; the instrumentation still verifies SDL is really PAUSED.
            paused = h.shell('am', 'start', '-W', '-n', 'org.esdeplus.stub/.RecipientActivity')
            wait_for_focus(h, 'org.esdeplus.stub', 'PDF descriptor snapshot recipient focus')
            time.sleep(2)
            snapshot = command(action)
            h.evidence.joinpath('pdf-' + mode + '-paused-' + stage + '.txt').write_text(
                paused + '\n' + h.shell('dumpsys', 'activity', 'activities') + '\n' + snapshot)
            # Keep this resume's start/release in the evidence; clearing after
            # BACK erased the deliberate input-block window (D-024 am. 1).
            h.adb('logcat', '-c')
            h.key('KEYCODE_BACK')
            wait_for_focus(h, h.app, 'PDF descriptor snapshot returns frontend focus')
            h.launch_checks.equal(h.shell('pidof', h.app).strip(), pid, 'PDF snapshot retains process')
            rejects('PDF snapshot changed process', lambda: h.launch_checks.equal(pid + 'x', pid, 'PDF snapshot process control'))
            _, after = h.activity_records()
            h.launch_checks.equal([r[:2] for r in after], [r[:2] for r in before], 'PDF snapshot retains host and task')
            rejects('PDF snapshot changed host/task', lambda: h.launch_checks.equal(
                [r[:2] for r in before] + [('wrong', '-1')], [r[:2] for r in before], 'PDF snapshot task control'))
            resumed_input(stage, pid)
            return snapshot
        result = paused_command('contract', 'contract')
        h.smoke_checks.probe_passed(result, 'PASS: D-008 real JNI')
        h.evidence.joinpath('pdf-' + mode + '-contract.txt').write_text(result)
        def frame(name):
            h.screenshot('pdf-' + mode + '-' + name)
            return (h.evidence / ('pdf-' + mode + '-' + name + '.png')).read_bytes()
        def enter_gamelist():
            # Back returns to the system view; A enters the NES gamelist.
            h.key('KEYCODE_DEL'); h.key('KEYCODE_ENTER')
        def open_manual(name):
            h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
            # Rendering and releasing the visited-page cache can outlast a fixed
            # screenshot delay. Await the actual frame without reissuing input.
            try:
                h.wait_for(lambda: manual_visible(h.adb('exec-out', 'screencap', '-p', binary=True)),
                           'actual manual frame ' + name)
            except Exception:
                pdf_close_probe.CloseProbe(h, mode).capture('open-' + name + '-timeout')
                raise
            png = frame(name)
            manual_image(png)
            return png
        h.key('KEYCODE_ENTER')
        if diagnostic_cycles:
            # This is a separate, focused diagnostic workload. The normal
            # PR-D smoke below remains complete. Keep the existing total
            # instrumentation deadline and per-close timeout unchanged.
            assert h.api >= 31 and not h.television
            command('fixture=stress')
            probe = pdf_close_probe.CloseProbe(h, mode)
            poll_counts = []
            for cycle in range(diagnostic_cycles):
                # Exercise the open path's first post-resume key too, with
                # the viewer stopped. Each cycle then warms and closes it.
                paused_command('stats', 'diagnostic-open-' + str(cycle))
                h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
                def first_ready():
                    png = h.adb('exec-out', 'screencap', '-p', binary=True)
                    if not displayed_page(png, 1):
                        return False
                    h.evidence.joinpath('pdf-' + mode + '-diagnostic-first-' + str(cycle) + '.png').write_bytes(png)
                    return True
                try:
                    h.wait_for(first_ready, 'diagnostic actual first page')
                except Exception:
                    probe.capture('open-timeout')
                    raise
                # Multiple keycodes are ordinary input keyevent presses; no
                # 0.4 s host sleep per warm-up page. Every page must render.
                h.shell('input', 'keyevent', *(['KEYCODE_DPAD_RIGHT'] * 59))
                h.wait_for(lambda: displayed_page(h.adb('exec-out', 'screencap', '-p', binary=True), 60),
                           'diagnostic cached-page endpoint 60')
                logs = h.adb('logcat', '-d')
                for page in range(1, 61):
                    h.smoke_checks.probe_passed(logs, 'PDF rendered page=' + str(page) + ' size=')
                h.evidence.joinpath('pdf-' + mode + '-diagnostic-open-' + str(cycle) + '-logcat.txt').write_text(logs)
                h.key('KEYCODE_MOVE_HOME')
                h.wait_for(lambda: displayed_page(h.adb('exec-out', 'screencap', '-p', binary=True), 1),
                           'diagnostic cached-page endpoint 1')
                paused_command('stats', 'diagnostic-resume-' + str(cycle))
                poll_counts.append(probe.close(manual_visible, diagnostic=True, kind='cached-resume'))
            command('end')
            process.wait(timeout=15)
            h.smoke_checks.probe_passed(output_path.read_text(), 'PASS: PDF viewer session completed')
            h.evidence.joinpath('pdf-' + mode + '-diagnostic-summary.txt').write_text(
                'Diagnostic workload completed: ' + str(diagnostic_cycles) +
                ' cached-60-page pause/resume single-key closes; polls=' + str(poll_counts) + '\n')
            if diagnostic_cycles == 20:
                assert poll_counts == [1] * 20, 'Twenty consecutive native-stop/single-poll closes required: ' + str(poll_counts)
            return
        first = open_manual('first')
        h.launch_checks.equal(manual_visible(first), True, 'Actual manual readiness control')
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
            h.launch_checks.equal(bool(h.shell('pidof', h.app).strip()), True, 'Frontend process after PDF failure')
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
        # Every supported phone image runs this stress path. TV remains excluded.
        if not h.television and h.api >= 31:
            command('fixture=stress')
            h.adb('logcat', '-c')
            first_stress = open_manual('stress-first')
            stress_page(first_stress, 1)
            rejects('wrong displayed stress page', lambda: stress_page(first_stress, 2))
            h.launch_checks.equal(displayed_page(first_stress, 1), True, 'Displayed stress page ready')
            h.launch_checks.equal(displayed_page(first_stress, 2), False, 'Wrong stress page readiness control')
            rejects('non-solid stress marker', lambda: solid_bit([128, 128, 128]))
            first_stress_logs = h.adb('logcat', '-d')
            baseline = paused_command('stats', 'before-stress')
            for code, page in [('KEYCODE_DPAD_RIGHT', 60), ('KEYCODE_DPAD_LEFT', 1)]:
                for _ in range(59): h.key(code)
                h.wait_for(lambda: displayed_page(h.adb('exec-out', 'screencap', '-p', binary=True), page),
                           'actual displayed stress endpoint ' + str(page))
                stress_page(frame('stress-' + code), page)
            logs = first_stress_logs + '\n' + h.adb('logcat', '-d')
            for page in range(1, 61):
                h.smoke_checks.probe_passed(logs, 'PDF rendered page=' + str(page) + ' size=')
            h.evidence.joinpath('pdf-' + mode + '-stress-pages.txt').write_text(logs)
            after = paused_command('stats', 'after-stress')
            memory = h.shell('dumpsys', 'meminfo', h.app)
            memory_path = h.evidence / ('pdf-' + mode + '-stress-memory-fds.txt')
            memory_path.write_text(baseline + '\n' + after + '\n' + memory)
            descriptors(baseline, after)
            rejects('descriptor leak', lambda: descriptors(baseline, 'fd=' + str(int(re.search(r'fd=(\d+)', baseline)[1]) + 1)))
            probe = pdf_close_probe.CloseProbe(h, mode)
            def close_cycle():
                return probe.close(manual_visible)
            polls = close_cycle()
            if h.api >= 31:
                if polls != 1:
                    probe.capture('slow-stress-close')
                h.launch_checks.equal(polls, 1, 'Cached PDF closes on first poll after resume')
            for _ in range(10):
                open_manual('cycle'); close_cycle()
            stable = paused_command('stats', 'after-cycles')
            memory_path.write_text(baseline + '\n' + after + '\n' + stable + '\n' + memory)
            descriptors(baseline, stable)
            command('fixture=valid')
        open_manual('lifecycle')
        pid = h.shell('pidof', h.app).strip()
        # Use the same opaque recipient on every image. TV Settings can leave
        # SDL resumed, which cannot produce a foreground-block release.
        paused_command('stats', 'lifecycle')
        h.launch_checks.equal(h.shell('pidof', h.app).strip(), pid, 'PDF foreground process')
        manual_image(frame('foreground'))
        h.key('KEYCODE_DEL')
        command('end')
        process.wait(timeout=15)
        h.smoke_checks.probe_passed(output_path.read_text(), 'PASS: PDF viewer session completed')
        h.shell('am', 'force-stop', h.app)
        provisioned = h.shell('am', 'instrument', '-w', '-e', 'mode', 'pdf-unreadable',
                             h.app + '/org.esdeplus.frontend.RuntimeSmoke')
        unreadable = re.search(r'UNREADABLE_MEDIA=(.+)', provisioned)[1].strip()
        h.shell('am', 'force-stop', h.app)
        settings.find("string[@name='MediaDirectory']").set('value', unreadable)
        h.user_file('settings/es_settings.xml', settings_xml(settings))
        h.adb('logcat', '-c'); h.launch(); h.key('KEYCODE_ENTER')
        h.key('KEYCODE_FORWARD_DEL'); h.key('KEYCODE_DPAD_UP')
        closed(frame('unreadable'))
        h.smoke_checks.probe_passed(h.adb('logcat', '-d'), 'PDF conversion failed')
        h.evidence.joinpath('pdf-' + mode + '-unreadable.txt').write_text(provisioned + '\n' + h.log())
        for code in ['KEYCODE_PAGE_DOWN', 'KEYCODE_DPAD_UP', 'KEYCODE_DPAD_LEFT', 'KEYCODE_DEL']: h.key(code)
        h.shell('am', 'force-stop', h.app)
        settings.find("string[@name='MediaDirectory']").set('value', media)
        h.user_file('settings/es_settings.xml', settings_xml(settings))
        h.launch(); h.key('KEYCODE_ENTER'); open_manual('before-destroy')
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
                h.launch_checks.equal(volume_mounted(volumes, volume_id), True, 'PDF volume initially mounted')
                rejects('removable state unchanged', lambda: h.launch_checks.equal(
                    volume_mounted(volume_id + ' mounted UUID', volume_id), False, 'PDF volume removed'))
                h.launch_checks.equal(volume_mounted(volume_id + ' unmounted UUID', volume_id), False,
                                      'Unmounted volume state control')
                settings.find("string[@name='MediaDirectory']").set('value', volume_media)
                h.user_file('settings/es_settings.xml', settings_xml(settings))
                try:
                    h.launch(); h.key('KEYCODE_ENTER'); open_manual('removable-first')
                    h.shell('sm', 'unmount', volume_id)
                    h.wait_for(lambda: not volume_mounted(h.shell('sm', 'list-volumes', 'public'), volume_id),
                               'actual PDF volume removal')
                    h.key('KEYCODE_DPAD_RIGHT')
                    failed = frame('removable-removed')
                    closed(failed)
                    for code in ['KEYCODE_PAGE_DOWN', 'KEYCODE_DPAD_UP', 'KEYCODE_DEL']: h.key(code)
                    h.launch_checks.equal(bool(h.shell('pidof', h.app).strip()), True, 'Frontend process after volume removal')
                    volume_result += '\nPASS: removable-volume manual rendered; real unmount during view closes failed next page and remains responsive.\n'
                finally:
                    h.shell('sm', 'mount', volume_id)
                    h.shell('am', 'force-stop', h.app)
                    settings.find("string[@name='MediaDirectory']").set('value', media)
                    h.user_file('settings/es_settings.xml', settings_xml(settings))
            else:
                h.smoke_checks.probe_passed(volume_result, 'CAPABILITY GAP:')
            h.evidence.joinpath('pdf-' + mode + '-removable-volume.txt').write_text(volumes + '\n' + volume_result)
        else:
            h.evidence.joinpath('pdf-' + mode + '-removable-volume.txt').write_text(
                'Removable-volume success/removal probe uses the explicit direct-mode pass on this same image.\n' + volumes)
        h.evidence.joinpath('pdf-' + mode + '-summary.txt').write_text(
            'PASS: actual gamelist/manual path, next/previous/first/last, zoom/pan/reset, close/reopen, injected and missing/unreadable/malformed/password/zero failures, valid recovery/game launch, background/foreground, activity destruction. API 31/34 also 60-page forward/back + ten cycles, FD and retained memory evidence.\n')
    finally:
        if process and process.poll() is None:
            h.shell('am', 'force-stop', h.app)
            process.wait(timeout=15)
        output.close()
        h.shell('am', 'force-stop', h.app)
        h.user_file('settings/es_settings.xml', original)
        h.shell('setprop', 'log.tag.ESDE-PDF-CLOSE', input_trace_level)
    # The inherited warm-alias checks expect a live HOME session, just as
    # launch_contract_probes restores after its standalone gamelist probes.
    h.wait_for(lambda: not h.shell('pidof', h.app, check=False).strip(), 'PDF frontend stopped before restoring HOME')
    time.sleep(1)
    h.adb('logcat', '-c')
    h.start_entry('HomeEntry', 'android.intent.category.HOME')
    h.configured_system('pdf-' + mode + '-restored-home')
    h.launch_checks.equal('HOME=true' in h.adb('logcat', '-d'), True, 'HOME precondition after PDF smoke')


def release(harness):
    h = type('Harness', (), harness)
    h.shell('am', 'force-stop', h.app)
    original = h.shell('cat', h.settings)
    settings = h.launch_checks.settings_fragment(original)
    settings.find("string[@name='MediaDirectory']").set('value', h.data_root + '/Manual spaces 🚀')
    h.user_file('settings/es_settings.xml', settings_xml(settings))
    prepared = False
    try:
        # Match upstream's ROM-stem media lookup while exercising Unicode in
        # the minified viewer's actual manual basename as well as its directory.
        # Scoped external files require the actual app's SDK context, not run-as.
        result = h.shell('am', 'instrument', '-w', '-e', 'mode', 'pdf-unicode-prepare',
                         h.app + '/org.esdeplus.frontend.RuntimeSmoke')
        h.smoke_checks.probe_passed(result, 'PASS: Unicode PDF fixture prepared through app SDK context; rename controls rejected')
        prepared = True
        h.evidence.joinpath('pdf-unicode-fixture.txt').write_text(result)
        # Same CI-only ephemeral key as debug, so the real saved configuration
        # and Unicode fixture remain installed for the minified runtime check.
        h.adb('install', '-r', 'android/app/build/outputs/apk/release/app-release-smoke.apk')
        h.adb('logcat', '-c')
        h.launch(); h.key('KEYCODE_ENTER')
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
        runtime_log(logs, h.app)
        for error in ['JNI DETECTED ERROR', 'NoSuchMethod', 'ANR in ' + h.app]:
            rejects('minified runtime ' + error, lambda: runtime_log(logs + '\n' + error, h.app))
        h.save_logs('pdf-minified-runtime')
        h.evidence.joinpath('pdf-minified-summary.txt').write_text(
            'PASS: installed CI-signed minified release opens Manual spaces 🚀/nes/manuals/Smoke Alpha 🚀.pdf through the gamelist; rotation, paging, zoom/pan/reset, close/reopen; screenshot colour assertions pass; no JNI/lookup/ANR failure. APK remains in CI and is never uploaded.\n')
    finally:
        h.shell('am', 'force-stop', h.app)
        h.adb('install', '-r', str(h.apk))
        if prepared:
            result = h.shell('am', 'instrument', '-w', '-e', 'mode', 'pdf-unicode-restore',
                             h.app + '/org.esdeplus.frontend.RuntimeSmoke')
            h.smoke_checks.probe_passed(result, 'PASS: Unicode PDF fixture restored through app SDK context; rename controls rejected')
            with h.evidence.joinpath('pdf-unicode-fixture.txt').open('a') as output: output.write(result)
        h.user_file('settings/es_settings.xml', original)
