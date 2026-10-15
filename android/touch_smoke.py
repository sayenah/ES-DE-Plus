#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus from open input callers, MIT SVGs and Android SDK docs.
# B-4 runtime evidence. Provenance review is separate B-5 evidence, never a smoke result.
import json
import hashlib
import re
import struct
import time
import types
import xml.etree.ElementTree as ET

import pdf_smoke
import smoke_support

IDS = [11, 12, 13, 14, 0, 1, 2, 3, 4, 6, 9, 10, 100, 101]
MAPPINGS = dict(zip(IDS, ['up', 'down', 'left', 'right', 'a', 'b', 'x', 'y', 'back', 'start',
                          'leftshoulder', 'rightshoulder', 'lefttrigger', 'righttrigger']))
TOUCH = re.compile(r'Window::logInput\(Touch\): Button (\d+), isMappedTo=.*?value=([01])')
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
    return 'PASS: orphan release, double release and missing release rejected\n'


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


def run(namespace):
    h = types.SimpleNamespace(**namespace)
    smoke_support.connected()
    (h.evidence / 'touch-assertion-positive-controls.txt').write_text(assertion_controls())
    original = h.shell('cat', h.settings)
    common = dict(DebugMode=True, InputTouchOverlayFadeTime=0, ScreensaverTimer=0,
                  InputTouchOverlaySize='medium', InputTouchOverlayOpacity='normal',
                  InputSwapButtons=False, VirtualKeyboard=True)
    logs = []

    def record(name):
        output = h.log()
        (h.evidence / (name + '-es_log.txt')).write_text(output)
        logs.append(output)
        balanced(output)
        return output

    def start(**changes):
        selected = dict(common, **changes)
        h.user_file('settings/es_settings.xml', configure(original, **selected))
        h.launch()
        return h.log()

    def shot(name):
        data = h.adb('exec-out', 'screencap', '-p', binary=True)
        (h.evidence / (name + '.png')).write_bytes(data)
        return data

    def surface_bounds():
        hierarchy = h.hierarchy()
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
        return x0, y0, x1 - x0, y1 - y0

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
        result = h.shell('am', 'instrument', '-w', '-e', 'steps', json.dumps(steps, separators=(',', ':')),
                         *sum((['-e', k, str(v)] for k, v in options.items()), []),
                         h.app + '/org.esdeplus.frontend.TouchSmoke')
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
        start(InputTouchOverlay=True)
        touch_control(6)
        touch_control(12, 4)
        touch_control(0)
        touch_control(12)
        touch_control(14)  # One save changes size, opacity and enable together.
        touch_control(12)
        touch_control(14, 2)
        touch_control(12, 2)
        touch_control(0)
        touch_control(0)  # Confirm the warning; wording awaits PR #16 integration.
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

        if h.api == 34:
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
                shot('touch-only-return-no-highlight')
                touch_control(6)
                touch_control(1)
                record('touch-only-launch-return-menu')
            finally:
                for name in override_names:
                    h.user_file(name, overrides[name] or None)
                start(InputTouchOverlay=True)
                surface_bounds_cached = surface_bounds()
                centres = buttons(h.log())

        # A menu context prevents a face press from launching another app during
        # the independent multi-pointer scenarios. The stream itself opens menus.
        right = pointer(14, 7); a = pointer(0, 2)
        inject('touch-two-independent', [
            step('down', [right]), step('pointer-down', [right, a], changed=2),
            step('pointer-up', [a, right], changed=2),  # Pointer-index reordering.
            step('pointer-down', [a, right], changed=2), step('pointer-up', [right, a], changed=2),
            step('up', [right])], [(14, 1), (0, 1), (0, 0), (0, 1), (0, 0), (14, 0)], menu='true')
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
            [(0, 1), (0, 0), (1, 1), (1, 0)], menu='true')
        inject('touch-leave-cluster', [step('down', [a]), step('move', [empty]),
            step('up', [empty])], [(0, 1), (0, 0)], menu='true')
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
                    step('down', [fresh], wait=0), step('up', [fresh], wait=lift_delay),
                    step('down', [fresh], wait=400), step('up', [fresh])],
                    accepted_around_block)

        # The corrupt override is the first resource lookup and parses as invalid;
        # APK asset fallback cannot hide this fixture, unlike deleting an internal copy.
        try:
            invalid = inject('touch-invalid-art', [step('down', [pointer(0)]),
                step('up', [pointer(0)])], [(0, 1), (0, 0)], asset='invalid', menu='true')
            assert 'InputOverlay: unavailable art id=0; primitive fallback' in invalid
            assert 'emergencyShutdown' not in invalid
        finally:
            h.shell('am', 'force-stop', h.app)
            restored = h.shell('am', 'instrument', '-w', '-e', 'asset', 'restore',
                               h.app + '/org.esdeplus.frontend.TouchSmoke')
            assert 'PASS: overlay asset fixture restored' in restored, restored

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

        # Live drawable invalidation while a pointer is held must cancel it before
        # the new mapping/layout generation is published. No old transform is reused.
        output = start(InputTouchOverlay=True)
        centres = buttons(output)
        s = surface_bounds()
        nx, ny = centres[12]['norm']
        x, y = str(round(s[0] + nx * s[2])), str(round(s[1] + ny * s[3]))
        before = h.log()
        h.shell('input', 'touchscreen', 'motionevent', 'DOWN', x, y)
        dimensions = h.shell('wm', 'size')
        physical = re.search(r'Physical size:\s*(\d+)x(\d+)', dimensions)
        assert physical and 'Override size:' not in dimensions, dimensions
        try:
            width, height = map(int, physical.groups())
            h.shell('wm', 'size', f'{width * 9 // 10}x{height * 9 // 10}')
            h.wait_for(lambda: 'Window size has changed' in h.log()[len(before):], 'overlay resize reload')
            time.sleep(1)
            h.shell('input', 'touchscreen', 'motionevent', 'UP', x, y)
            check_delta(before, [(12, 1), (12, 0)], 'held pointer cancelled on resize')
            resized = buttons(h.log())
            bounds = surface_bounds()
            for button in [0, 11, 6, 9]:
                neutral()
                if button != 6:
                    h.key('KEYCODE_ESCAPE')
                before_tap = h.log()
                nx, ny = resized[button]['norm']
                tap((bounds[0] + nx * bounds[2], bounds[1] + ny * bounds[3]))
                check_delta(before_tap, [(button, 1), (button, 0)], 'resized control ' + str(button))
            shot('touch-resized-after-cancel')
            record('touch-resize-held')
        finally:
            reset_before = h.log()
            overridden = 'Override size:' in h.shell('wm', 'size')
            h.shell('wm', 'size', 'reset')
            if overridden:
                h.wait_for(lambda: 'Window size has changed' in h.log()[len(reset_before):], 'overlay resize reset')

        # Fade: one complete waking gesture is inert, including its motion and UP.
        output = start(InputTouchOverlay=True, InputTouchOverlayFadeTime=2,
                       ScreensaverTimer=1000, ScreensaverType='dim')
        assert 'InputOverlay: faded' in output  # launch() waits ten seconds.
        centres = buttons(output)
        s = surface_bounds()
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
        h.wait_for(lambda: 'InputOverlay: faded' in h.log(), 'clamped twenty-second fade', timeout=15)
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
            'refcounts, index reordering, stationary slide-and-hold and ACTION_CANCEL; rotations; wake-only fade.\n'
            'OPEN: hardware ergonomics/multitouch, gesture-navigation/cutout safety; configurator reset after '
            'PR #15; PR #16 ownership and lockout warning. See PR AC evidence for remaining checks.\n')
    finally:
        if h.shell('pidof', h.app, check=False).strip():
            record('touch-final')
        h.user_file('settings/es_settings.xml', original)
        h.launch()


if __name__ == '__main__':
    print(assertion_controls(), end='')
