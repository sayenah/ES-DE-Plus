#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus from open input callers, MIT SVGs and Android SDK docs.
# B-4 runtime evidence. Provenance review is separate B-5 evidence, never a smoke result.
import json
import re
import time
import types
import xml.etree.ElementTree as ET

import pdf_smoke
import smoke_support

IDS = [11, 12, 13, 14, 0, 1, 2, 3, 4, 6, 9, 10, 100, 101]
TOUCH = re.compile(r'Window::logInput\(Touch\): Button (\d+), isMappedTo=.*?value=([01])')
BUTTON = re.compile(r'InputOverlay: button id=(\d+) hit=([^ ]+) centre=([^ ]+) norm=([^\s]+)')


def transitions(log):
    return [(int(i), int(v)) for i, v in TOUCH.findall(log)]


def balanced(log):
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
                  InputTouchOverlaySize='medium', InputTouchOverlayOpacity='normal', InputSwapButtons=False)
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
        nodes = [n for n in h.hierarchy() if 'Surface' in n.get('class', '')]
        assert nodes, 'SDL SurfaceView must have independently observed on-display bounds'
        rectangles = [list(map(int, re.findall(r'\d+', n.get('bounds', '')))) for n in nodes]
        rectangles = [r for r in rectangles if len(r) == 4 and r[2] > r[0] and r[3] > r[1]]
        x0, y0, x1, y1 = max(rectangles, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        return x0, y0, x1 - x0, y1 - y0

    def tap(point):
        h.shell('input', 'tap', str(round(point[0])), str(round(point[1])))
        time.sleep(0.25)

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
        assert transitions(current) == wanted, (name, transitions(current), wanted)
        return current

    def pointer(button, finger=0):
        return dict(id=finger, x=centres[button]['norm'][0], y=centres[button]['norm'][1])

    def step(action, pointers, wait=150, **extra):
        return dict(action=action, pointers=pointers, wait=wait, **extra)

    try:
        disabled = start(InputTouchOverlay=False)
        assert 'InputOverlay: textures built' not in disabled
        off = shot('touch-disabled-reference')
        output = start(InputTouchOverlay=True)
        centres = buttons(output)
        on = shot('touch-startup-fourteen-controls')
        surface = surface_bounds()
        pixels, boxes = rendered_centres(off, on, centres, surface)
        (h.evidence / 'touch-rendered-centres.json').write_text(json.dumps(dict(surface=surface, boxes=boxes, taps=pixels), indent=2))
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
        inject('touch-slide-and-stationary-hold', [step('down', [up]), step('move', [slid]),
            step('up', [slid], wait=1000)], [(11, 1), (11, 0), (14, 1), (14, 0)])
        down = pointer(12, 0); shoulder = pointer(9, 5); face = pointer(3, 11)
        inject('touch-three-clusters-cancel', [step('down', [down]),
            step('pointer-down', [shoulder, down], changed=5),
            step('pointer-down', [face, down, shoulder], changed=11),
            step('cancel', [shoulder, face, down])],
            [(12, 1), (9, 1), (3, 1), (9, 0), (3, 0), (12, 0)])

        # Geometry matrix uses the same executable getter as rendering. Pure tests
        # additionally cover independent offset/padding/clip fixtures and every ID.
        for rotation in [90, 180, 270]:
            output = start(InputTouchOverlay=True, ScreenRotate=rotation)
            rotated = buttons(output)
            s = surface_bounds()
            for button in [0, 11, 6]:
                neutral()
                if button != 6:
                    h.key('KEYCODE_ESCAPE')
                before = h.log()
                nx, ny = rotated[button]['norm']
                tap((s[0] + nx * s[2], s[1] + ny * s[3]))
                check_delta(before, [(button, 1), (button, 0)], f'rotation {rotation} id {button}')
            shot(f'touch-rotation-{rotation}')
            record(f'touch-rotation-{rotation}')

        # Fade: one complete waking gesture is inert, including its motion and UP.
        output = start(InputTouchOverlay=True, InputTouchOverlayFadeTime=2)
        assert 'InputOverlay: faded' in output  # launch() waits ten seconds.
        centres = buttons(output)
        s = surface_bounds()
        before = h.log()
        nx, ny = centres[1]['norm']
        p = (s[0] + nx * s[2], s[1] + ny * s[3])
        tap(p)
        check_delta(before, [], 'hidden wake-only gesture')
        before = h.log()
        tap(p)  # Back is a non-launch control.
        check_delta(before, [(1, 1), (1, 0)], 'visible non-launch tap')
        record('touch-fade-wake')

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
