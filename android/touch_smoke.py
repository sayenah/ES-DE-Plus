#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus from open input callers, MIT SVGs and Android SDK docs.
# B-4 runtime evidence. Provenance review is separate B-5 evidence, never a smoke result.
import json
import hashlib
import re
import struct
import subprocess
import tempfile
import shlex
import time
import types
import xml.etree.ElementTree as ET

import pdf_smoke
import smoke_support
import touch_startup

IDS = [11, 12, 13, 14, 0, 1, 2, 3, 4, 6, 9, 10, 100, 101]
MAPPINGS = dict(zip(IDS, ['up', 'down', 'left', 'right', 'a', 'b', 'x', 'y', 'back', 'start',
                          'leftshoulder', 'rightshoulder', 'lefttrigger', 'righttrigger']))
TOUCH = re.compile(r'Window::logInput\(Touch\): Button (\d+), isMappedTo=.*?value=([01])')
MANAGER_SYSTEM_TARGET = re.compile(
    r'Emulator manager touch target: ([^\t\r\n]* — [^\t\r\n]*)\tx:[^\t]+\ty:[^\t]+\tnorm:([0-9.]+),([0-9.]+)')
BUTTON = re.compile(r'InputOverlay: button id=(\d+) hit=([^ ]+) centre=([^ ]+) norm=([^\s]+)')


def transitions(log):
    return [(int(i), int(v)) for i, v in TOUCH.findall(log)]


def balanced(log):
    for button, names in re.findall(r'Window::logInput\(Touch\): Button (\d+), isMappedTo=(.*?)value=', log):
        assert int(button) in IDS and MAPPINGS[int(button)] in [n.strip() for n in names.split(',')], (button, names)
    held = set()
    for button, value in transitions(log):
        assert button in IDS, ('Unmapped touch ID', button)
        assert (button in held) != bool(value), ('Unbalanced accepted input', button, value)
        if value:
            held.add(button)
        else:
            held.remove(button)
    assert not held, ('Unreleased accepted holds', held)


def buttons(log):
    layout = log.rsplit('InputOverlay: layout ', 1)[-1]
    result = {int(i): {'hit': tuple(map(float, hit.split(','))),
                       'centre': tuple(map(float, centre.split(','))),
                       'norm': tuple(map(float, norm.split(',')))}
              for i, hit, centre, norm in BUTTON.findall(layout)}
    assert set(result) == set(IDS), ('Fourteen layout centres required', layout)
    assert all(0 <= n <= 1 for b in result.values() for n in b['norm']), layout
    return result


def configure(original, **values):
    document = ET.fromstring('<fragment>' + re.sub(r'^\s*<\?xml[^?]*\?>', '', original, count=1) + '</fragment>')
    for name, value in values.items():
        element = document.find(f"*[@name='{name}']")
        if element is None:
            element = ET.SubElement(document, 'bool' if isinstance(value, bool) else
                                    'int' if isinstance(value, int) else 'string', name=name)
        element.set('value', str(value).lower() if isinstance(value, bool) else str(value))
    return '<?xml version="1.0"?>\n' + ''.join(ET.tostring(e, encoding='unicode') for e in document)


def assertion_controls():
    good = 'Window::logInput(Touch): Button 11, isMappedTo=up, value=1\n' \
           'Window::logInput(Touch): Button 11, isMappedTo=up, value=0\n'
    balanced(good)
    for bad in [good.splitlines()[1], good + good.splitlines()[1], good.splitlines()[0]]:
        try:
            balanced(bad)
        except AssertionError:
            pass
        else:
            raise AssertionError('Touch balance positive control escaped')
    assert configure('', InputTouchOverlay=True).count('value="true"') == 1
    sample = 'Emulator manager touch target: 3do — 3DO\tx:540\ty:500\tnorm:0.5,0.26'
    assert MANAGER_SYSTEM_TARGET.search(sample).group(1) == '3do — 3DO'
    assert not MANAGER_SYSTEM_TARGET.search(sample.replace('3do — 3DO', 'FIND SYSTEM'))
    return 'PASS: orphan release, double release and missing release rejected; visible manager system target parsed\n'


def fallback_contrast(png, centre, hit_width):
    width, height, channels, rows = pdf_smoke.pixels(png)
    radius = max(2, round(hit_width * 0.05))
    def mean(x, y):
        values = [rows[py][px * channels + c]
                  for py in range(max(0, round(y) - radius), min(height, round(y) + radius + 1))
                  for px in range(max(0, round(x) - radius), min(width, round(x) + radius + 1))
                  for c in range(3)]
        assert values, 'Fallback sample must be on screen'
        return sum(values) / len(values)
    x, y = centre
    distance = hit_width * 0.7
    background = sum(mean(x + dx, y + dy) for dx, dy in
                     [(distance, 0), (-distance, 0), (0, distance), (0, -distance)]) / 4
    return abs(mean(x, y) - background)


def rendered_centres(off, on, expected, surface):
    """Locate the largest connected difference component near each predicted glyph.

    Its actual pixel bounding box, rather than the logged centre, drives the tap.
    Failure to draw a glyph or mapping it outside its independent search region fails.
    """
    w, h, channels, rows = pdf_smoke.pixels(on)
    ow, oh, och, old = pdf_smoke.pixels(off)
    assert (w, h) == (ow, oh)
    left, top, sw, sh = surface
    points = {}
    boxes = {}
    for button, data in expected.items():
        nx, ny = data['norm']
        cx, cy = left + nx * sw, top + ny * sh
        # Neighbour separation bounds the independent image search. At least a
        # stroke loop with a substantial extent must exist, not a single log pixel.
        nearest = min(((nx - b['norm'][0]) * sw) ** 2 + ((ny - b['norm'][1]) * sh) ** 2
                      for other, b in expected.items() if other != button) ** 0.5
        radius = max(8, int(nearest * 0.46))
        candidates = set()
        for y in range(max(0, int(cy - radius)), min(h, int(cy + radius + 1))):
            for x in range(max(0, int(cx - radius)), min(w, int(cx + radius + 1))):
                rgb = rows[y][x * channels:x * channels + 3]
                previous = old[y][x * och:x * och + 3]
                if max(abs(a - b) for a, b in zip(rgb, previous)) > 18:
                    candidates.add((x, y))
        largest = []
        while candidates:
            seed = candidates.pop()
            component = [seed]
            queue = [seed]
            while queue:
                x, y = queue.pop()
                for neighbour in [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]:
                    if neighbour in candidates:
                        candidates.remove(neighbour)
                        component.append(neighbour)
                        queue.append(neighbour)
            if len(component) > len(largest):
                largest = component
        assert len(largest) >= 20, ('No rendered control', button, len(largest))
        x0 = min(p[0] for p in largest); x1 = max(p[0] for p in largest)
        y0 = min(p[1] for p in largest); y1 = max(p[1] for p in largest)
        assert x1 - x0 >= radius * 0.4 and y1 - y0 >= radius * 0.3, ('Missing glyph extent', button)
        boxes[button] = [x0, y0, x1, y1]
        points[button] = ((x0 + x1) / 2, (y0 + y1) / 2)
    return points, boxes


def run_fresh(namespace):
    """Provision a separate emulator through the existing real configurator UI."""
    h = types.SimpleNamespace(**namespace)
    namespace['api'] = int(h.shell('getprop', 'ro.build.version.sdk').strip())
    namespace['shared'] = '/sdcard/ESDEPlusSmoke'
    shared = namespace['shared']
    h.shell('mkdir', '-p', shared + '/nes')
    dummy = h.evidence / 'dummy.nes'
    dummy.write_bytes(b'\x00')
    for name in ('Smoke Alpha.nes', 'Smoke Beta.nes'):
        h.adb('push', str(dummy), shared + '/nes/' + name)
    import smoke_phases
    smoke_phases.prepare(namespace, 'direct')
    h = types.SimpleNamespace(**namespace)
    assert 'InputOverlay: setup reset saved and consumed' in h.log(), h.log()
    original = h.shell('cat', h.settings)
    h.user_file('settings/es_settings.xml', configure(original, InputTouchOverlay=False))
    h.launch()
    assert 'InputOverlay: setup reset saved and consumed' not in h.log()
    # Exercise both a live PR15 restart and death before setup commit. Pending
    # intent is separate from the draft in both cases; later disable stays false.
    for kill_during_setup in (False, True):
        before_pid = h.shell('pidof', h.app).strip()
        if kill_during_setup:
            # Android kills the app when all-files access is revoked. This is
            # the cold/process-death route, not the live Settings consumer.
            h.shell('appops', 'set', '--uid', h.app, 'MANAGE_EXTERNAL_STORAGE', 'deny')
            h.key('KEYCODE_HOME')
            h.start_entry()
        else:
            # Lose and restore the selected data root while backgrounded, as
            # the main app-data session does, without killing its consumer.
            h.shell('am', 'start', '-a', 'android.settings.SETTINGS')
            h.shell('mv', h.data_root, h.data_root + '.touch-unavailable')
            try:
                h.key('KEYCODE_BACK')
                h.ui('Configure ' + h.label)
            finally:
                h.shell('mv', h.data_root + '.touch-unavailable', h.data_root)
        if not kill_during_setup:
            h.ui('Cancel configuration', dpad=True)
            pending = h.shell('run-as', h.app, 'sh', '-c',
                              'if test -e files/touch-overlay-reset; then echo PENDING; else echo ABSENT; fi')
            assert pending.strip() == 'ABSENT', pending
        if kill_during_setup:
            h.ui('Grant direct filesystem access', dpad=True)
            h.grant_from_settings()
        h.ui('Use direct filesystem compatibility', dpad=True)
        if not kill_during_setup:
            assert h.shell('pidof', h.app).strip() == before_pid, 'Live reset case lost its original native consumer'
        if kill_during_setup:
            h.shell('am', 'force-stop', h.app)
            h.start_entry()
        h.ui('Save and start frontend', dpad=True)
        h.configured_system('touch-setup-reset-' + str(kill_during_setup))
        assert h.shell('pidof', h.app).strip() != before_pid, 'Setup recovery must select fresh native paths'
        assert 'InputOverlay: setup reset saved and consumed' in h.log(), h.log()
        restored = h.shell('cat', h.settings)
        assert ET.fromstring('<f>' + re.sub(r'<\?xml[^?]*\?>', '', restored) + '</f>').find(
            "bool[@name='InputTouchOverlay']").get('value') == 'true', restored
        h.user_file('settings/es_settings.xml', configure(restored, InputTouchOverlay=False))
        h.launch()
        disabled = h.shell('cat', h.settings)
        assert ET.fromstring('<f>' + re.sub(r'<\?xml[^?]*\?>', '', disabled) + '</f>').find(
            "bool[@name='InputTouchOverlay']").get('value') == 'false', disabled
        assert 'InputOverlay: setup reset saved and consumed' not in h.log()
    # The other qualifying storage route must reset the selected private root,
    # independently of the shared root exercised above.
    h.shell('appops', 'set', '--uid', h.app, 'MANAGE_EXTERNAL_STORAGE', 'deny')
    h.key('KEYCODE_HOME')
    # A newly created adb-pushed file belongs to shell (0644), which correctly
    # fails PR15's write preflight. Prepare valid native-owned test data instead.
    prepared = h.shell('am', 'instrument', '-w', '-e', 'mode', 'private-settings-prepare',
                       h.app + '/org.esdeplus.frontend.TouchSmoke')
    h.smoke_checks.probe_passed(prepared, 'PASS: private settings false prepared and validated under frontend UID=')
    (h.evidence / 'touch-private-seed.txt').write_text(prepared)
    h.start_entry()
    h.ui('Use app-owned storage', dpad=True)
    private = h.external + '/ES-DE-Plus'
    h.shell('mkdir', '-p', h.roms + '/nes')
    for name in ('Smoke Alpha.nes', 'Smoke Beta.nes'):
        h.adb('push', str(dummy), h.roms + '/nes/' + name)
    h.select_data_root(private)
    h = types.SimpleNamespace(**namespace)
    metadata = [private, private + '/settings', private + '/settings/es_settings.xml']
    (h.evidence / 'touch-private-seed-access.txt').write_text(
        h.shell('ls', '-ld', *metadata, check=False) + '\nApp UID:\n' +
        h.shell('run-as', h.app, 'ls', '-ld', *metadata, check=False) + '\nSeed under app UID:\n' +
        h.shell('run-as', h.app, 'cat', metadata[-1], check=False))
    import forced_relaunch_smoke
    h.wait_for(lambda: forced_relaunch_smoke.configurator_focused(h.focused_window(), h.app),
               'private setup window focused before Save')
    (h.evidence / 'touch-private-before-save.txt').write_text(h.focused_window() + '\n' +
        h.shell('dumpsys', 'input'))
    h.ui('Save and start frontend', dpad=True)
    h.configured_system('touch-private-setup-reset')
    assert 'InputOverlay: setup reset saved and consumed' in h.log(), h.log()
    restored = h.shell('cat', h.settings)
    assert ET.fromstring('<f>' + re.sub(r'<\?xml[^?]*\?>', '', restored) + '</f>').find(
        "bool[@name='InputTouchOverlay']").get('value') == 'true', restored
    (h.evidence / 'touch-setup-reset.txt').write_text(
        'PASS: initial setup consumes reset; cancel before choice creates no intent; '
        'normal startup preserves disabled setting; live recovery after native Settings uses PR15 fresh PID; '
        'process death after qualifying choice restores setup; selected shared and private folders enabled once; later disable survives startup.\n')
    run(namespace)
    # Recover by editing the existing native-owned file, as documented. Close
    # the app first and require adb to preserve its owner; do not recreate it.
    receipts = []
    for enabled in (False, True):
        h.shell('am', 'force-stop', h.app)
        previous = h.shell('cat', h.settings)
        owner = h.shell('stat', '-c', '%u', h.settings).strip()
        edited = configure(previous, InputTouchOverlay=enabled, DebugMode=True,
                           InputTouchOverlayFadeTime=0)
        # adb push replaces the destination inode/owner on these images. Shell
        # redirection edits the existing file in place, preserving app ownership.
        h.shell('sh', '-c', 'printf %s ' + shlex.quote(edited) + ' > ' + shlex.quote(h.settings))
        assert h.shell('stat', '-c', '%u', h.settings).strip() == owner, 'adb replaced the settings owner'
        h.launch()
        actual = ET.fromstring('<f>' + re.sub(r'<\?xml[^?]*\?>', '', h.shell('cat', h.settings)) + '</f>')
        assert actual.find("bool[@name='InputTouchOverlay']").get('value') == str(enabled).lower()
        assert 'InputOverlay: setup reset saved and consumed' not in h.log()
        if enabled:
            h.wait_for(lambda: 'InputOverlay: textures built' in h.log(), 'adb recovery draws overlay')
            h.screenshot('touch-private-adb-recovery')
        else:
            assert 'InputOverlay: textures built' not in h.log()
        receipts.append(f'PASS: existing private XML adb edit enabled={enabled}; owner={owner} preserved; no setup reset')
    (h.evidence / 'touch-private-adb-recovery.txt').write_text('\n'.join(receipts) + '\n')

    # Fault the acknowledgement independently of settings verification: a bound,
    # native-owned intent in a read-only parent cannot be removed. Native must
    # show the error, wait for OK, keep the intent, then exit without relaunching.
    h.shell('am', 'force-stop', h.app)
    root = h.shell('readlink', '-f', h.settings).strip().rsplit('/settings/', 1)[0]
    intent = 'touch-smoke-ack-failure\n' + root
    original_mode = h.private('stat', '-c', '%a', 'files').strip()
    h.private('sh', '-c', 'test ! -e files/touch-overlay-reset && printf %s ' +
              shlex.quote(intent) + ' > files/touch-overlay-reset && chmod 500 files')
    try:
        denied = h.private('rm', 'files/touch-overlay-reset', check=False)
        assert h.private('cat', 'files/touch-overlay-reset') == intent, denied
        h.start_entry()
        message = 'Unable to save the touch overlay setup.'
        h.wait_for(lambda: any(message in n.get('text', '') for n in h.hierarchy()),
                   'reset failure is visible before frontend input')
        pid = h.shell('pidof', h.app).strip()
        assert pid
        h.screenshot('touch-reset-failure-dialog')
        assert h.private('cat', 'files/touch-overlay-reset') == intent
        logcat = h.adb('logcat', '-d', '--pid', pid)
        assert 'Finished main function' not in logcat, 'Failure exited before acknowledgement'
        h.ui('OK', exact=True)
        h.wait_for(lambda: 'Finished main function' in h.adb('logcat', '-d', '--pid', pid),
                   'acknowledged reset failure exits native')
        time.sleep(1)
        logcat = h.adb('logcat', '-d', '--pid', pid)
        assert logcat.count('Running main function') == 1, 'Reset failure restarted native'
        assert h.private('cat', 'files/touch-overlay-reset') == intent
        (h.evidence / 'touch-reset-failure-logcat.txt').write_text(logcat)
    finally:
        h.shell('am', 'force-stop', h.app)
        h.private('chmod', original_mode, 'files')
    h.launch()
    assert 'InputOverlay: setup reset saved and consumed' in h.log()
    assert h.private('sh', '-c', 'test ! -e files/touch-overlay-reset && echo RETIRED').strip() == 'RETIRED'
    (h.evidence / 'touch-reset-failure.txt').write_text(
        'PASS: controlled acknowledgement failure shows a blocking native Android dialog; '
        'intent unchanged before/after OK; one native main exits; repairing permissions '
        'consumes the retained intent exactly once.\n')


def run(namespace):
    h = types.SimpleNamespace(**namespace)
    smoke_support.connected()
    (h.evidence / 'touch-assertion-positive-controls.txt').write_text(assertion_controls())
    original = h.shell('cat', h.settings)
    common = dict(DebugMode=True, InputTouchOverlayFadeTime=0, ScreensaverTimer=0,
                  InputTouchOverlaySize='medium', InputTouchOverlayOpacity='normal',
                  InputSwapButtons=False, VirtualKeyboard=True, StartupSystem='nes', StartupView='system')
    logs = []
    ready_surface_nodes = None

    def record(name):
        output = h.log()
        (h.evidence / (name + '-es_log.txt')).write_text(output)
        logs.append(output)
        balanced(output)
        return output

    def start(**changes):
        nonlocal ready_surface_nodes
        selected = dict(common, **changes)
        h.user_file('settings/es_settings.xml', configure(original, **selected))
        ready_surface_nodes = h.launch()
        return h.log()

    def shot(name):
        data = h.adb('exec-out', 'screencap', '-p', binary=True)
        (h.evidence / (name + '.png')).write_bytes(data)
        return data

    def surface_bounds():
        # Reuse the actual ready-window dump from this launch. Its independent
        # accessibility bounds are unchanged; live buffer geometry is still queried.
        hierarchy = ready_surface_nodes if ready_surface_nodes is not None else h.hierarchy()
        nodes = [n for n in hierarchy if n.get('package') == h.app and 'Surface' in n.get('class', '')]
        if not nodes:
            # SDL exposes its focused surface as android.view.View on some SDKs.
            # This remains a live accessibility rectangle, independent of Renderer.
            nodes = [n for n in hierarchy if n.get('package') == h.app and
                     n.get('class') == 'android.view.View' and n.get('focused') == 'true' and
                     n.get('focusable') == 'true']
        assert nodes, 'SDL surface must have independently observed on-display bounds'
        rectangles = [list(map(int, re.findall(r'\d+', n.get('bounds', '')))) for n in nodes]
        rectangles = [r for r in rectangles if len(r) == 4 and r[2] > r[0] and r[3] > r[1]]
        x0, y0, x1, y1 = max(rectangles, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        probe = h.shell('am', 'broadcast', '-n', h.app + '/org.esdeplus.frontend.TouchSmoke$SurfaceGeometry')
        assert 'PASS: owned surface geometry recorded' in probe, probe
        live = json.loads(h.adb('exec-out', 'run-as', h.app, 'cat',
                               'cache/touch-surface-geometry.json'))
        native = re.findall(r'InputOverlay: layout .*?surface=(\d+)x(\d+)', h.log())[-1]
        assert tuple(map(int, native)) == (live['bufferWidth'], live['bufferHeight']), live
        with (h.evidence / 'touch-surface-observations.txt').open('a') as output:
            output.write(json.dumps(dict(accessibility=[x0, y0, x1, y1], sdk=live)) + '\n')
        # SDLSurface.onTouch normalizes by SurfaceHolder's dimensions, which need
        # not equal a clipped View/accessibility extent after fullscreen resize.
        return live['x'], live['y'], live['bufferWidth'], live['bufferHeight']

    def tap(point, wait=True):
        before = h.log() if wait else ''
        h.shell('input', 'touchscreen', 'tap', str(round(point[0])), str(round(point[1])))
        if wait:
            h.wait_for(lambda: 'InputOverlay: event type=up ' in h.log()[len(before):],
                       'native touch UP processed and frame log flushed', timeout=20)

    def neutral():
        # Return to the system view using the ordinary configured keyboard Back;
        # this is setup for ID probes, not the touch-only user journey.
        for _ in range(4):
            h.key('KEYCODE_DEL')

    def check_delta(before, wanted, label):
        current = h.log()
        assert current.startswith(before), 'Log generation changed during gesture'
        actual = transitions(current[len(before):])
        assert actual == wanted, (label, actual, wanted)
        return current

    def inject(name, steps, wanted, **options):
        # Instrumentation owns a fresh app window. A missing/failed injection is a
        # hard failure, never a silently passing diagnostic.
        h.shell('am', 'force-stop', h.app)
        h.private('rm', '-f', 'cache/touch-startup-owner')
        arguments = ['am', 'instrument', '-w', '-e', 'steps', json.dumps(steps, separators=(',', ':')),
                     *sum((['-e', k, str(v)] for k, v in options.items()), []),
                     h.app + '/org.esdeplus.frontend.TouchSmoke']
        # Keep the existing external stock-dialog guard active while the SDK
        # waits for its owned activity. Preserve the same 90-second deadline;
        # no frontend action, assertion or instrumentation stream is replayed.
        with tempfile.TemporaryFile(mode='w+t') as output, tempfile.TemporaryFile(mode='w+t') as errors:
            process = subprocess.Popen(['adb', 'shell', shlex.join(arguments)], stdout=output, stderr=errors)
            deadline = time.monotonic() + 90
            ownership = touch_startup.StartupOwnership(h, process, deadline, name)
            try:
                h.wait_for(ownership.finished, name + ' SDK pointer stream', timeout=90)
                output.seek(0); errors.seek(0)
                completed = subprocess.CompletedProcess(process.args, process.returncode, output.read(), errors.read())
                completed.check_returncode()
                result = completed.stdout
            finally:
                try:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)
                finally:
                    ownership.report()
        (h.evidence / (name + '-injected.txt')).write_text(result)
        assert 'PASS: complete Android multi-pointer stream injected' in result and 'FAIL:' not in result, result
        current = record(name)
        expected = wanted(current) if callable(wanted) else wanted
        assert transitions(current) == expected, (name, transitions(current), expected)
        (h.evidence / (name + '.png')).write_bytes(h.adb('exec-out', 'run-as', h.app,
            'cat', 'cache/touch-last.png', binary=True))
        for step in steps:
            if step['action'] == 'snapshot':
                (h.evidence / (name + '-' + step['name'] + '.png')).write_bytes(h.adb(
                    'exec-out', 'run-as', h.app, 'cat', 'cache/touch-' + step['name'] + '.png', binary=True))
        return current

    def pointer(button, finger=0):
        return dict(id=finger, x=centres[button]['norm'][0], y=centres[button]['norm'][1])

    def step(action, pointers, wait=150, **extra):
        return dict(action=action, pointers=pointers, wait=wait, **extra)

    def touch_control(button, count=1, wait=True):
        for _ in range(count):
            current = buttons(h.log())
            s = surface_bounds_cached
            nx, ny = current[button]['norm']
            tap((s[0] + nx * s[2], s[1] + ny * s[3]), wait=wait)
            time.sleep(0.2)

    try:
        diameters = []
        for size in ('x-small', 'small', 'medium', 'large'):
            sized = start(InputTouchOverlay=True, InputTouchOverlaySize=size)
            diameter = float(re.findall(r'InputOverlay: layout .*? D=([^ ]+)', sized)[-1])
            if diameters:
                assert diameter + 0.01 >= diameters[-1][1] * 1.1, (size, diameters, diameter)
            diameters.append((size, diameter))
            shot('touch-size-' + size)
            record('touch-size-' + size)
        (h.evidence / 'touch-size-diameters.txt').write_text(json.dumps(diameters) + '\n')
        disabled = start(InputTouchOverlay=False)
        assert 'InputOverlay: textures built' not in disabled
        off = shot('touch-disabled-reference')
        output = start(InputTouchOverlay=True)
        centres = buttons(output)
        on = shot('touch-startup-fourteen-controls')
        surface = surface_bounds()
        surface_bounds_cached = surface
        pixels, boxes = rendered_centres(off, on, centres, surface)
        (h.evidence / 'touch-rendered-centres.txt').write_text(json.dumps(dict(surface=surface, boxes=boxes, taps=pixels), indent=2))
        for button in IDS:
            neutral()
            if button != 6:
                h.key('KEYCODE_ESCAPE')  # Safe menu context for A/shoulder probes.
            before = h.log()
            tap(pixels[button])
            check_delta(before, [(button, 1), (button, 0)], 'rendered control ' + str(button))
        neutral()
        before = h.log()
        tap((surface[0] + surface[2] * 0.5, surface[1] + surface[3] * 0.1))
        check_delta(before, [], 'empty space')
        record('touch-rendered-ids')
        assert 'InputOverlay: faded' not in h.log()
        shot('touch-zero-fade-still-visible')
        neutral()
        tap(pixels[0])  # System view -> gamelist, no launch.
        time.sleep(1)
        before = h.log()
        x, y = map(lambda value: str(round(value)), pixels[12])
        h.shell('input', 'touchscreen', 'swipe', x, y, x, y, '2000')
        time.sleep(0.5)
        first = shot('touch-held-after-lift-half-second')
        time.sleep(1)
        second = shot('touch-held-after-lift-onehalf-second')
        check_delta(before, [(12, 1), (12, 0)], 'stationary two-second hold')
        def frame_hash(png):
            width, height, channels, rows = pdf_smoke.pixels(png)
            digest = hashlib.sha256()
            # Gamelist region, excluding Android/status/help widgets and the deck.
            for row in rows[height // 5:height * 3 // 5]:
                digest.update(row[width // 10 * channels:width * 7 // 10 * channels])
            return digest.hexdigest()
        assert frame_hash(first) == frame_hash(second), 'Gamelist kept moving after release'
        record('touch-held-no-repeat-after-release')

        # Touch-only menu/device-configuration and text-entry journey. No keyboard
        # action is issued between this fresh start and the captured completion.
        start(InputTouchOverlay=True, VirtualKeyboard=True)
        touch_control(6)
        touch_control(12, 4)
        touch_control(0)
        touch_control(101)
        touch_control(0)
        touch_control(0)
        shot('touch-only-device-configuration')
        touch_control(1)
        assert 'GuiDetectDevice: touch cancel' in h.log(), h.log()
        touch_control(100)  # First settings row, then size and opacity.
        touch_control(12)
        touch_control(14)  # Medium -> large.
        touch_control(12)
        touch_control(14, 2)  # Normal -> low -> verylow.
        touch_control(1)  # Saving rebuilds twice while the Back gesture is held.
        saved = h.shell('cat', h.settings)
        assert re.search(r'name="InputTouchOverlaySize" value="large"', saved), saved
        assert re.search(r'name="InputTouchOverlayOpacity" value="verylow"', saved), saved
        shot('touch-only-settings-saved')
        touch_control(1)
        touch_control(6)
        touch_control(0)  # Search.
        shot('touch-only-text-empty')
        touch_control(12)  # On-screen keyboard, first key.
        touch_control(0)  # Enter a character using the overlay.
        shot('touch-only-text-entered')
        touch_control(1)  # Changed text opens its confirmation.
        shot('touch-only-text-confirmation')
        touch_control(0)
        record('touch-only-menu-device-settings-text')
        start(InputTouchOverlay=True, InputTouchOverlayFadeTime=10)
        # Refresh visibility after the normal startup wait before this render
        # comparison. The separate fade-behaviour probes still use T=2.
        tap((surface[0] + surface[2] * 0.5, surface[1] + surface[3] * 0.1))
        touch_control(6)
        touch_control(12, 4)
        touch_control(0)
        touch_control(12)
        touch_control(14)  # One save changes size, opacity and enable together.
        touch_control(12)
        touch_control(14, 2)
        touch_control(12, 2)
        touch_control(0)
        warning_on = shot('touch-disable-recovery-warning')
        rect = list(map(float, re.findall(r'InputOverlay: modal rect=([^\s]+)', h.log())[-1].split(',')))
        # The entire modal interior (text AND confirmation), independently sized
        # by the GUI, must be unchanged when the underlying overlay fades away.
        fade_baseline = h.log()
        h.wait_for(lambda: 'InputOverlay: faded' in h.log()[len(fade_baseline):],
                   'warning overlay fades under modal')
        warning_off = shot('touch-disable-recovery-warning-faded')
        width, height, channels, on_rows = pdf_smoke.pixels(warning_on)
        off_width, off_height, off_channels, off_rows = pdf_smoke.pixels(warning_off)
        assert (width, height, channels) == (off_width, off_height, off_channels)
        x, y, w, height = rect
        inset = 24  # Exclude only the rounded border and shadow.
        x0, y0, x1, y1 = round(x + inset), round(y + inset), round(x + w - inset), round(y + height - inset)
        assert x1 > x0 and y1 > y0
        changed = sum(on_rows[py][px * channels + c] != off_rows[py][px * channels + c]
                      for py in range(y0, y1) for px in range(x0, x1) for c in range(3))
        assert changed == 0, ('Overlay covered modal content', rect, changed)
        ax0, ay0, ax1, ay1 = map(round, boxes[0])
        exposed = sum(on_rows[py][px * channels + c] != off_rows[py][px * channels + c]
                      for py in range(ay0, ay1) for px in range(ax0, ax1) for c in range(3))
        assert exposed > 0, 'Visible/faded comparison must observe exposed A artwork changing'
        (h.evidence / 'touch-modal-priority.txt').write_text(
            f'PASS: modal interior {rect}: {changed} changed channels with overlay visible/faded; '
            'text and confirmation take visual priority.\n')
        tap((surface[0] + surface[2] * 0.5, surface[1] + surface[3] * 0.1))  # Wake-only.
        touch_control(0)  # Confirm the non-destructive, localized recovery warning.
        touch_control(1)
        assert 'InputOverlay: cleared' in h.log(), h.log()
        saved = h.shell('cat', h.settings)
        assert re.search(r'name="InputTouchOverlay" value="false"', saved), saved
        before = h.log()
        tap(pixels[0])
        check_delta(before, [], 'disabled overlay is inert')
        shot('touch-disabled-through-menu')
        enable_before = h.log()
        h.key('KEYCODE_DEL')
        h.key('KEYCODE_ESCAPE')
        for _ in range(4):
            h.key('KEYCODE_DPAD_DOWN')
        h.key('KEYCODE_ENTER')
        for _ in range(4):
            h.key('KEYCODE_DPAD_DOWN')
        h.key('KEYCODE_ENTER')
        h.key('KEYCODE_DEL')
        assert re.search(r'name="InputTouchOverlay" value="true"', h.shell('cat', h.settings))
        h.wait_for(lambda: 'InputOverlay: restored (menu)' in h.log()[len(enable_before):] and
                   'InputOverlay: textures built' in h.log()[len(enable_before):],
                   'fresh menu enable rebuild and render')
        shot('touch-reenabled-through-menu')
        record('touch-disable-reenable')
        start(InputTouchOverlay=True)
        centres = buttons(h.log())

        if h.api in (33, 35):
            root = h.logpath.rsplit('/logs/', 1)[0]
            override_names = ['custom_systems/es_systems.xml', 'custom_systems/es_find_rules.xml']
            overrides = {name: h.shell('cat', root + '/' + name, check=False) for name in override_names}
            try:
                h.user_file(override_names[0], '<systemList><system><name>nes</name><fullname>NES</fullname>'
                    '<path>%ROMPATH%/nes</path><extension>.nes .NES</extension>'
                    '<command>%EMULATOR_TOUCH_SMOKE% %ACTION%=android.intent.action.VIEW '
                    '%MIMETYPE%=application/octet-stream %DATA%=%ROMPROVIDER%</command>'
                    '<platform>nes</platform><theme>nes</theme></system></systemList>')
                h.user_file(override_names[1], '<ruleList><emulator name="TOUCH_SMOKE">'
                    '<rule type="androidpackage"><entry>org.esdeplus.stub/.RecipientActivity</entry>'
                    '</rule></emulator></ruleList>')
                start(InputTouchOverlay=True, StartupSystem='nes', StartupView='system')
                surface_bounds_cached = surface_bounds()
                touch_control(0)
                time.sleep(1)
                touch_control(0, wait=False)
                h.wait_for(lambda: re.search(r'mCurrentFocus=.* org\.esdeplus\.stub/', h.focused_window()),
                           'touch-only game launch to real recipient')
                receipt = h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json')
                assert json.loads(receipt).get('sha256'), receipt
                (h.evidence / 'touch-only-launch-receipt.txt').write_text(receipt)
                recipient = shot('touch-only-recipient')
                back = [n for n in h.hierarchy() if n.get('package') == 'com.android.systemui' and
                        n.get('content-desc', '').lower() == 'back']
                if back:
                    x0, y0, x1, y1 = map(int, re.findall(r'\d+', back[0].get('bounds', '')))
                    tap(((x0 + x1) / 2, (y0 + y1) / 2), wait=False)
                else:
                    width, height = struct.unpack('>II', recipient[16:24])
                    h.shell('input', 'touchscreen', 'swipe', '1', str(height // 2), str(min(200, width // 3)),
                            str(height // 2), '500')
                h.wait_for(lambda: re.search(r'mCurrentFocus=.* ' + re.escape(h.app) + '/', h.focused_window()),
                           'touch-only return from recipient')
                time.sleep(1)
                assert 'InputOverlay: restored (resume)' in h.log()
                returned = shot('touch-only-return-no-highlight')
                time.sleep(2)
                later = shot('touch-only-return-stable')
                assert frame_hash(returned) == frame_hash(later), 'Gamelist moved after game return'
                touch_control(6)
                touch_control(1)
                record('touch-only-launch-return-menu')
            finally:
                for name in override_names:
                    h.user_file(name, overrides[name] or None)
                start(InputTouchOverlay=True)
                surface_bounds_cached = surface_bounds()
                centres = buttons(h.log())

        # Keep refcount/slide probes separate from GUI-routing cancellation:
        # A is inert on the sound slider, and A/B browse views without stacking
        # dialogs from an explicit system-view start. Routing has its own probe.
        h.user_file('settings/es_settings.xml', configure(original, **dict(common,
            InputTouchOverlay=True, StartupSystem='nes', StartupView='system')))
        right = pointer(14, 7); a = pointer(0, 2)
        inject('touch-two-independent', [
            step('down', [right]), step('pointer-down', [right, a], changed=2),
            step('pointer-up', [a, right], changed=2),  # Pointer-index reordering.
            step('pointer-down', [a, right], changed=2), step('pointer-up', [right, a], changed=2),
            step('up', [right])], [(14, 1), (0, 1), (0, 0), (0, 1), (0, 0), (14, 0)], menu='sound')
        b0 = pointer(1, 9); b1 = pointer(1, 3)
        inject('touch-shared-button', [step('down', [b0]), step('pointer-down', [b1, b0], changed=3),
            step('pointer-up', [b0, b1], changed=9), step('up', [b1])], [(1, 1), (1, 0)])
        up = pointer(11, 4); slid = pointer(14, 4)
        h.user_file('settings/es_settings.xml', configure(original, **dict(common,
            InputTouchOverlay=True, SoundVolumeNavigation=0)))
        inject('touch-slide-and-stationary-hold', [step('down', [up]), step('move', [slid]),
            step('snapshot', [], wait=1000, name='right-held', held=14), step('up', [slid])],
            [(11, 1), (11, 0), (14, 1), (14, 0)], menu='sound')
        volume = re.search(r'name="SoundVolumeNavigation" value="(\d+)"', h.shell('cat', h.settings))
        assert volume and int(volume[1]) > 1, 'Right did not repeat during the stationary hold'
        a = pointer(0); b = pointer(1); up = pointer(11)
        empty = dict(id=0, x=0.5, y=0.15)
        inject('touch-face-slide-lift-elsewhere', [step('down', [a]),
            step('move', [b]), step('up', [a])],
            [(0, 1), (0, 0), (1, 1), (1, 0)])
        inject('touch-leave-cluster', [step('down', [a]), step('move', [empty]),
            step('up', [empty])], [(0, 1), (0, 0)])
        inject('touch-empty-cannot-slide-in', [step('down', [empty]), step('move', [a]),
            step('up', [a])], [], menu='true')
        inject('touch-cannot-cross-clusters', [step('down', [up]), step('move', [a]),
            step('up', [a])], [(11, 1), (11, 0)], menu='true')
        down = pointer(12, 0); shoulder = pointer(9, 5); face = pointer(3, 11)
        inject('touch-three-clusters-cancel', [step('down', [down]),
            step('pointer-down', [shoulder, down], changed=5),
            step('pointer-down', [face, down, shoulder], changed=11),
            step('cancel', [shoulder, face, down])],
            [(12, 1), (9, 1), (3, 1), (9, 0), (3, 0), (12, 0)])

        for absence in [100, 3000]:
            for lift_delay in [0, 150, 400]:
                fresh = pointer(12, 1)
                def accepted_around_block(output):
                    # Classify from the independently logged live Window state,
                    # rather than assuming a 300ms block survives a long absence.
                    downs = re.findall(r'InputOverlay: event type=down finger=1 blocked=([01])', output)
                    assert len(downs) == 2 and downs[-1] == '0', output
                    return [(12, 1), (12, 0)] + ([(12, 1), (12, 0)] if downs[0] == '0' else []) + [(12, 1), (12, 0)]
                inject(f'touch-focus-return-{absence}-{lift_delay}', [
                    step('down', [down]), step('background', []),
                    step('resume', [], wait=absence),
                    step('up', [down], wait=lift_delay),
                    step('down', [fresh], wait=0), step('up', [fresh]),
                    step('down', [fresh], wait=400), step('up', [fresh])],
                    accepted_around_block)

        # The corrupt override is the first resource lookup and parses as invalid;
        # APK asset fallback cannot hide this fixture, unlike deleting an internal copy.
        try:
            invalid = inject('touch-invalid-art', [step('down', [pointer(0)]),
                step('up', [pointer(0)])], [(0, 1), (0, 0)], asset='invalid', menu='true')
            assert 'InputOverlay: unavailable art id=0; primitive fallback' in invalid
            assert 'emergencyShutdown' not in invalid
            button = buttons(invalid)[0]
            point = (surface[0] + button['norm'][0] * surface[2],
                     surface[1] + button['norm'][1] * surface[3])
            contrast = fallback_contrast((h.evidence / 'touch-invalid-art.png').read_bytes(),
                                         point, button['hit'][2])
            (h.evidence / 'touch-fallback-contrast.txt').write_text(str(contrast) + '\n')
            assert contrast > 20, ('Fallback must be visibly distinct from its surroundings', contrast)
        finally:
            h.shell('am', 'force-stop', h.app)
            restored = h.shell('am', 'instrument', '-w', '-e', 'asset', 'restore',
                               h.app + '/org.esdeplus.frontend.TouchSmoke')
            assert 'PASS: overlay asset fixture restored' in restored, restored

        # Enter the real Android-app importer with two physical pointers held.
        # Its first blocking render must cancel accepted holds before the menu
        # rejects input. Motion/lifts from those pointers remain inert afterwards.
        h.user_file('settings/es_settings.xml', configure(original, **dict(common,
            InputTouchOverlay=True, ImporterTargetSystem='androidapps',
            ImporterRemoveEntries='never', ImporterImportMedia=False,
            ImporterImportMediaAdditional=False, ImporterGamesOnly=False)))
        down = pointer(12, 0); start_import = pointer(3, 1)
        moved = pointer(14, 0)
        inventory = inject('touch-importer-cancellation', [step('down', [down]),
            step('snapshot', [], name='importer-down-held', held=12),
            step('pointer-down', [down, start_import], changed=1),
            step('inventory', [], wait=0),
            step('move', [moved, start_import], wait=1000),
            step('pointer-up', [start_import, moved], changed=1),
            step('up', [moved]), step('down', [moved]), step('up', [moved]),
            step('importer-return', [], wait=500)],
            [(12, 1), (3, 1), (12, 0), (3, 0), (14, 1), (14, 0)], menu='importer')
        assert 'InputOverlay: importer cancellation boundary' in inventory
        for name in [f'importer-cancelled-{frame}' for frame in range(5)] + [
                'importer-return-first', 'importer-return-later']:
            (h.evidence / ('touch-' + name + '.png')).write_bytes(h.adb(
                'exec-out', 'run-as', h.app, 'cat', 'cache/touch-' + name + '.png', binary=True))

        # Sample beyond the rotated arrow SVG's side but inside its pressed
        # disc. Compare with nearby bare background, independently of model flags.
        diameter = float(re.findall(r'InputOverlay: layout .*? D=([^ ]+)', inventory)[-1])
        current = buttons(inventory)[12]['norm']
        bounds = surface_bounds_cached
        cx, cy = bounds[0] + current[0] * bounds[2], bounds[1] + current[1] * bounds[3]
        def down_highlight(name):
            w, height, channels, rows = pdf_smoke.pixels((h.evidence / (name + '.png')).read_bytes())
            def mean(x, y):
                x, y = round(x), round(y)
                assert 2 <= x < w - 2 and 2 <= y < height - 2
                return sum(rows[j][i * channels + c] for j in range(y - 2, y + 3)
                           for i in range(x - 2, x + 3) for c in range(3)) / 75
            return abs(mean(cx - 0.45 * diameter, cy) - mean(cx - 0.65 * diameter, cy))
        held_contrast = down_highlight('touch-importer-cancellation-importer-down-held')
        cancelled = [down_highlight(f'touch-importer-cancelled-{frame}') for frame in range(5)]
        assert held_contrast > 20, ('No rendered held highlight in the positive fixture', held_contrast)
        assert min(cancelled) < 15 and cancelled[-1] < 15, ('Importer highlight did not clear', cancelled)
        (h.evidence / 'touch-importer-highlight-contrast.txt').write_text(
            json.dumps(dict(held=held_contrast, cancelled=cancelled), indent=2))

        def retained_menu_hash(name):
            w, height, channels, rows = pdf_smoke.pixels((h.evidence / ('touch-' + name + '.png')).read_bytes())
            return hashlib.sha256(b''.join(row[w * 3 // 10 * channels:w * 7 // 10 * channels]
                for row in rows[height * 15 // 100:height * 45 // 100])).hexdigest()
        first = retained_menu_hash('importer-return-first')
        later = retained_menu_hash('importer-return-later')
        assert first == later, ('Retained importer menu kept scrolling', first, later)
        (h.evidence / 'touch-importer-retained-menu-stability.txt').write_text(first + '\n' + later + '\n')

        # Geometry matrix uses the same executable getter as rendering. Pure tests
        # additionally cover independent offset/padding/clip fixtures and every ID.
        geometries = [(f'rotation-{r}', dict(ScreenRotate=r), IDS if r == 90 else [0, 11, 6, 9])
                      for r in [90, 180, 270]]
        geometries += [(f'offset-{sign}', dict(ScreenOffsetX=80 * sign, ScreenOffsetY=40 * sign,
                                              FullscreenPadding=True), [0, 11, 6, 9])
                       for sign in [-1, 1]]
        for name, changes, selected in geometries:
            start(InputTouchOverlay=False, **changes)
            reference = shot('touch-' + name + '-off')
            output = start(InputTouchOverlay=True, **changes)
            rotated = buttons(output)
            s = surface_bounds()
            actual, boxes = rendered_centres(reference, shot('touch-' + name + '-on'), rotated, s)
            (h.evidence / ('touch-' + name + '-rendered.txt')).write_text(json.dumps(boxes, indent=2))
            for button in selected:
                neutral()
                if button != 6:
                    h.key('KEYCODE_ESCAPE')
                before = h.log()
                tap(actual[button])
                check_delta(before, [(button, 1), (button, 0)], name + ' id ' + str(button))
            record('touch-' + name)

        # WO-15 is now merged: exercise the real held-pointer reload rather
        # than retaining the obsolete pre-Android-13 audio dependency.
        start(InputTouchOverlay=True, ScreenRotate=0)
        surface_bounds_cached = surface_bounds()
        pid = h.shell('pidof', h.app).strip()
        p = buttons(h.log())[12]['norm']
        x, y = (round(surface_bounds_cached[0] + p[0] * surface_bounds_cached[2]),
                round(surface_bounds_cached[1] + p[1] * surface_bounds_cached[3]))
        before = h.log()
        h.shell('input', 'touchscreen', 'motionevent', 'DOWN', str(x), str(y))
        h.wait_for(lambda: (12, 1) in transitions(h.log()[len(before):]), 'held Down before resize')
        try:
            h.shell('wm', 'size', '900x1600')
            h.wait_for(lambda: 'reloading' in h.log()[len(before):] and
                       'InputOverlay: layout ' in h.log()[h.log().rfind('reloading'):],
                       'live resize completes renderer reload', timeout=60)
            assert h.shell('pidof', h.app).strip() == pid, 'Resize changed native process'
            h.shell('input', 'touchscreen', 'motionevent', 'MOVE', str(x), str(y))
            h.shell('input', 'touchscreen', 'motionevent', 'UP', str(x), str(y))
            time.sleep(1)
            check_delta(before, [(12, 1), (12, 0)], 'reload cancels and residual motion stays inert')
            record('touch-live-resize')
            ready_surface_nodes = None
            surface_bounds_cached = surface_bounds()
            shot('touch-live-resize-controls')
            for control in (6, 0, 9, 11, 1, 1):
                resumed = h.log()
                touch_control(control)
                check_delta(resumed, [(control, 1), (control, 0)],
                            'fresh control after reload ' + str(control))
        finally:
            before_reset = h.log()
            h.shell('wm', 'size', 'reset')
            h.wait_for(lambda: 'reloading' in h.log()[len(before_reset):] and
                       'InputOverlay: layout ' in h.log()[h.log().rfind('reloading'):],
                       'reset renderer size completes reload', timeout=60)
        record('touch-live-resize-reset')

        # Fade: one complete waking gesture is inert, including its motion and UP.
        output = start(InputTouchOverlay=True, InputTouchOverlayFadeTime=2,
                       ScreensaverTimer=1000, ScreensaverType='dim', CustomEventScripts=True)
        assert 'Scripting::fireEvent(): screensaver-start "timer"' in output
        centres = buttons(output)
        s = surface_bounds()
        # TV automatic wakes start Hidden, so startup need not emit "faded".
        # Explicitly wake on every platform, then observe a fresh timed fade.
        before = h.log()
        tap((s[0] + s[2] * 0.5, s[1] + s[3] * 0.1))
        check_delta(before, [], 'explicit empty-space visibility wake')
        h.wait_for(lambda: 'InputOverlay: faded' in h.log()[len(before):],
                   'two-second fade after explicit wake', timeout=15)
        shot('touch-two-second-faded')
        before = h.log()
        nx, ny = centres[1]['norm']
        p = (s[0] + nx * s[2], s[1] + ny * s[3])
        tap(p)
        check_delta(before, [], 'hidden wake-only gesture')
        assert 'Scripting::fireEvent(): screensaver-end' not in h.log()[len(before):]
        before = h.log()
        tap(p)  # Back is a non-launch control.
        check_delta(before, [(1, 1), (1, 0)], 'visible non-launch tap')
        assert 'Scripting::fireEvent(): screensaver-end "cancel"' in h.log()[len(before):]
        record('touch-fade-wake')

        output = start(InputTouchOverlay=True, InputTouchOverlaySize='bogus',
                       InputTouchOverlayOpacity='bogus', InputTouchOverlayFadeTime=-5)
        assert 'InputOverlay: unknown size; using medium' in output
        assert 'InputOverlay: unknown opacity; using normal' in output
        assert 'InputOverlay: fade time clamped to 0' in output and 'InputOverlay: faded' not in output
        record('touch-setting-fallbacks')
        output = start(InputTouchOverlay=True, InputTouchOverlayFadeTime=99)
        assert 'InputOverlay: fade time clamped to 20' in output
        s = surface_bounds()
        before = h.log()
        tap((s[0] + s[2] * 0.5, s[1] + s[3] * 0.1))
        check_delta(before, [], 'explicit wake before clamped fade')
        h.wait_for(lambda: 'InputOverlay: faded' in h.log()[len(before):],
                   'clamped twenty-second fade after explicit wake', timeout=30)
        record('touch-setting-fade-clamp')

        # Automatic TV wakes neither show controls nor persist a setting change.
        if 'android.software.leanback' in h.shell('pm', 'list', 'features'):
            output = start(InputTouchOverlay=True, InputTouchOverlayFadeTime=6)
            assert 'InputOverlay: textures built' not in output
            before = h.shell('cat', h.settings)
            shot('touch-tv-automatic-hidden')
            h.key('KEYCODE_DPAD_RIGHT')
            assert h.shell('cat', h.settings) == before
            record('touch-tv-key-input')

        # Select must open Search, and Back must restore the same menu under
        # either button-swap setting. Compare settled UI content above the deck.
        def menu_error(first, second):
            w, height, channels, rows = pdf_smoke.pixels(first)
            ow, oh, och, old = pdf_smoke.pixels(second)
            assert (w, height, channels) == (ow, oh, och)
            total = count = 0
            for y in range(height * 15 // 100, height * 45 // 100):
                for x in range(w * 3 // 10, w * 7 // 10):
                    for channel in range(3):
                        total += abs(rows[y][x * channels + channel] - old[y][x * channels + channel])
                        count += 1
            return total / count

        # Stable ownership in both directions on actual manager dialogs. Direct
        # targets use the renderer's same authoritative inverse mapping.
        for enabled in (True, False):
            start(InputTouchOverlay=enabled, ScreenRotate=0)
            ready_surface_nodes = None
            surface_bounds_cached = surface_bounds()
            h.emulator_manager_smoke.manager_menus(h, 'touch-owner-' + str(enabled))
            time.sleep(0.5)
            if enabled:
                before = h.log()
                touch_control(12)
                check_delta(before, [(12, 1), (12, 0)], 'overlay controls manager first')
                assert 'owner=gui' not in h.log()[len(before):], 'Overlay gesture reached underlying manager'
                selected = h.log()
                nx, ny = buttons(selected)[0]['norm']
                bounds = surface_bounds_cached
                ax, ay = round(bounds[0] + nx * bounds[2]), round(bounds[1] + ny * bounds[3])
                h.shell('input', 'touchscreen', 'motionevent', 'DOWN', str(ax), str(ay))
                try:
                    h.wait_for(lambda: 'Emulator manager page: system;' in h.log()[len(selected):],
                               'overlay select opens actual manager system page')
                    check_delta(selected, [(0, 1), (0, 0)],
                                'manager page change cancels overlay hold before physical lift')
                finally:
                    h.shell('input', 'touchscreen', 'motionevent', 'UP', str(ax), str(ay))
                assert 'owner=gui' not in h.log()[len(selected):], 'Overlay gesture reached a manager widget'
                returned = h.log()
                touch_control(1)
                h.wait_for(lambda: 'Emulator manager page: systems;' in h.log()[len(returned):],
                           'overlay Back returns to manager systems')
            # The manager lists every bundled system, not just games present.
            # Choose a currently visible system row, independently of its name.
            h.wait_for(lambda: MANAGER_SYSTEM_TARGET.search(h.log()) is not None,
                       'mapped visible manager system target')
            match = list(MANAGER_SYSTEM_TARGET.finditer(h.log()))[0]
            nx, ny = float(match[2]), float(match[3])
            s = surface_bounds_cached
            target = (round(s[0] + nx * s[2]), round(s[1] + ny * s[3]))
            before = h.log()
            tap(target)
            h.wait_for(lambda: 'Emulator manager page: system;' in h.log()[len(before):],
                       'unclaimed direct manager gesture opens system')
            assert not transitions(h.log()[len(before):]), 'Direct gesture also activated overlay'
            assert 'owner=gui' in h.log()[len(before):]
            h.key('KEYCODE_DEL')
            if enabled:
                # A direct gesture that crosses an overlay control retains its
                # original owner; a routing change cancels its residual events.
                before = h.log()
                a = buttons(before)[0]['norm']
                ax, ay = round(s[0] + a[0] * s[2]), round(s[1] + a[1] * s[3])
                h.shell('input', 'touchscreen', 'motionevent', 'DOWN', str(target[0]), str(target[1]))
                h.wait_for(lambda: 'owner=gui' in h.log()[len(before):], 'direct gesture claimed before routing change')
                h.shell('input', 'touchscreen', 'motionevent', 'MOVE', str(ax), str(ay))
                h.key('KEYCODE_DEL') # Close the manager during the direct gesture.
                h.shell('input', 'touchscreen', 'motionevent', 'MOVE', str(ax), str(ay))
                h.shell('input', 'touchscreen', 'motionevent', 'UP', str(ax), str(ay))
                assert not transitions(h.log()[len(before):]), 'Cancelled GUI gesture leaked into overlay'
            (h.evidence / ('touch-manager-ownership-' + str(enabled) + '-injected.txt')).write_text(
                json.dumps(dict(overlay=enabled, direct_target=target, label=match[1],
                                routing_cancel=enabled, source='Android touchscreen MotionEvent DOWN/MOVE/UP'), indent=2))
            record('touch-manager-ownership-' + str(enabled))
            neutral()

        for swapped in [False, True]:
            start(InputTouchOverlay=True, UIMode='full', InputSwapButtons=swapped)
            surface_bounds_cached = surface_bounds()
            touch_control(6)
            time.sleep(0.5)
            menu = shot(f'touch-swap-{swapped}-menu')
            touch_control(1 if swapped else 0)
            time.sleep(0.5)
            selected = shot(f'touch-swap-{swapped}-selected')
            touch_control(0 if swapped else 1)
            time.sleep(0.5)
            returned = shot(f'touch-swap-{swapped}-back')
            changed = menu_error(menu, selected)
            restored = menu_error(menu, returned)
            assert changed > 1 and restored < changed / 2, (swapped, changed, restored)
            record(f'touch-select-back-swap-{swapped}')

        # Real kiosk/kid passkey, including the two Up/two Down prefix. Only
        # fixture preparation restarts the app; unlocking itself uses touch only.
        h.shell('am', 'force-stop', h.app)
        try:
            prepared = h.shell('am', 'instrument', '-w', '-e', 'mode', 'kid-prepare',
                               h.app + '/org.esdeplus.frontend.TouchSmoke')
            assert 'PASS: kid-prepare' in prepared, prepared
            for mode in ['kiosk', 'kid']:
                for swapped in [False, True]:
                    start(InputTouchOverlay=True, UIMode=mode, InputSwapButtons=swapped)
                    surface_bounds_cached = surface_bounds()
                    for button in [11, 11, 12, 12, 13, 14, 13, 14,
                                   0 if swapped else 1, 1 if swapped else 0]:
                        touch_control(button)
                    h.wait_for(lambda: 'Passkey sequence completed, switching UI mode to Full' in h.log(),
                               'touch-only ' + mode + ' unlock')
                    saved = h.shell('cat', h.settings)
                    assert re.search(r'name="UIMode" value="full"', saved), saved
                    shot(f'touch-unlock-{mode}-swap-{swapped}')
                    record(f'touch-unlock-{mode}-swap-{swapped}')
        finally:
            h.shell('am', 'force-stop', h.app)
            restored = h.shell('am', 'instrument', '-w', '-e', 'mode', 'kid-restore',
                               h.app + '/org.esdeplus.frontend.TouchSmoke')
            assert 'PASS: kid-restore' in restored, restored

        # Orderly native exit is distinct from process death between instrumentation
        # cases. SDL's native completion marker must follow the real Back action.
        start(InputTouchOverlay=True, BackEventAppExit=True)
        exit_pid = h.shell('pidof', h.app).strip()
        h.adb('logcat', '-c')
        h.key('KEYCODE_BACK')
        h.wait_for(lambda: 'Finished main function' in h.adb('logcat', '-d', '--pid', exit_pid),
                   'orderly touch-overlay native exit')
        completion = h.adb('logcat', '-d', '-v', 'threadtime', '--pid', exit_pid)
        assert not re.search(r'Fatal signal|FATAL EXCEPTION|JNI DETECTED ERROR', completion), completion
        (h.evidence / 'touch-orderly-exit-logcat.txt').write_text(completion)

        # Logical DPI, live resizing, focus loss and touch-only journeys remain in
        # the evidence matrix; do not infer hardware inset safety from these taps.
        (h.evidence / 'touch-summary.txt').write_text(
            'PASS: rendered fourteen-ID taps; empty space; lazy disabled textures; Android multi-pointer '
            'refcounts, index reordering, stationary slide-and-hold and ACTION_CANCEL; importer cancellation; rotations; wake-only fade.\n'
            'PASS: held-pointer live resize; overlay-first/direct-manager ownership; non-destructive warning; setup reset.\n'
            'OPEN: hardware ergonomics/multitouch, gesture-navigation/cutout safety. See PR AC evidence for remaining checks.\n')
    finally:
        try:
            if h.shell('pidof', h.app, check=False).strip():
                record('touch-final')
        finally:
            # A deliberately failing balance probe must still restore the seed.
            h.user_file('settings/es_settings.xml', original)
            h.launch()


if __name__ == '__main__':
    print(assertion_controls(), end='')
