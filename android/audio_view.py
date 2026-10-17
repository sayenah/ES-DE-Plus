#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Same-session audio navigation view identity.
import json
import struct
import time
import zlib
import pdf_smoke


def frame(png):
    width, height, channels, rows = pdf_smoke.pixels(png)
    # Sample throughout the frame, including text missed by the old sparse grid.
    rgb = bytes(c for y in range(0, height, 4) for x in range(0, width, 4)
                for c in rows[y][x * channels:x * channels + 3])
    return (width, height), rgb


def distance(first, second):
    assert len(first) == len(second) and first, 'Incompatible view samples'
    return sum(abs(a - b) for a, b in zip(first, second)) / (len(first) * 255)


class ViewIdentity:
    def __init__(self, references):
        assert set(references) == {'system', 'gamelist'}
        self.references = {view: [frame(png) for png in images]
                           for view, images in references.items()}
        assert all(self.references.values()), 'Missing view references'
        sizes = {size for images in self.references.values() for size, _ in images}
        assert len(sizes) == 1, 'View references must have the same dimensions'
        self.size = sizes.pop()
        self.separation = min(distance(a, b) for _, a in self.references['system']
                              for _, b in self.references['gamelist'])
        assert self.separation > 0, 'System and gamelist references are indistinguishable'
        self.records = []

    def expect(self, expected, png, label):
        size, sample = frame(png)
        assert size == self.size, ('View size changed', size, self.size)
        distances = {view: min(distance(sample, ref) for _, ref in images)
                     for view, images in self.references.items()}
        actual, other = sorted(distances, key=distances.get)
        # A tie or a frame far from both identities must fail, rather than turn
        # an unrelated screen into whichever view happens to be closer.
        recognized = (distances[actual] < distances[other] and
                      distances[actual] < self.separation / 2)
        result = dict(label=label, expected=expected, actual=actual,
                      distances=distances, reference_separation=self.separation,
                      recognized=recognized, passed=recognized and actual == expected)
        self.records.append(result)
        assert result['passed'], result


def capture(h, name):
    # Called at the known system view after normal startup. References belong
    # to this process, theme and full-size window; none are supplied externally.
    pid = h.shell('pidof', h.app).strip()
    assert pid.isdigit(), 'View references require a live frontend'
    references = {}
    for view in ('system', 'gamelist'):
        h.screenshot(name + '-reference-' + view + '-1')
        images = [(h.evidence / (name + '-reference-' + view + '-1.png')).read_bytes()]
        # Retain multiple real frames so the original looping video can show
        # either colour without being confused with a different view.
        for index in (2, 3):
            time.sleep(.4)
            png = h.adb('exec-out', 'screencap', '-p', binary=True)
            (h.evidence / f'{name}-reference-{view}-{index}.png').write_bytes(png)
            images.append(png)
        references[view] = images
        h.key('KEYCODE_ENTER' if view == 'system' else 'KEYCODE_DEL')
    oracle = ViewIdentity(references)
    oracle.records.append(dict(reference_pid=pid, reference_size=oracle.size,
                               reference_frames={view: [f'{name}-reference-{view}-{i}.png'
                                                        for i in (1, 2, 3)]
                                                 for view in references}))
    path = h.evidence / (name + '-view-identity.txt')
    try:
        # Deliberately omit each navigation key. Shift only wakes an idle
        # screensaver: the opposite view must fail the same assertion used
        # after stress. Then perform the real navigation and require identity.
        for view, expected, key in (('system', 'gamelist', 'KEYCODE_ENTER'),
                                    ('gamelist', 'system', 'KEYCODE_DEL')):
            h.key('KEYCODE_SHIFT_LEFT')
            label = name + '-wrong-navigation-' + expected
            h.screenshot(label)
            png = (h.evidence / (label + '.png')).read_bytes()
            oracle.expect(view, png, label + '-actual')
            try:
                oracle.expect(expected, png, label + '-control')
            except AssertionError:
                oracle.records.append(dict(control=label, detected=True))
            else:
                raise AssertionError('Wrong navigation escaped view identity: ' + label)
            h.key(key)
            label = name + '-reference-navigation-' + expected
            h.screenshot(label)
            oracle.expect(expected, (h.evidence / (label + '.png')).read_bytes(), label)
        assert h.shell('pidof', h.app).strip() == pid, 'PID changed while capturing view references'
    finally:
        path.write_text(json.dumps(oracle.records, indent=2) + '\n')
    return oracle


def controls():
    def png(value, width=32):
        def chunk(kind, data):
            return (struct.pack('>I', len(data)) + kind + data +
                    struct.pack('>I', zlib.crc32(kind + data)))
        # A small text-like patch gives the two views a distance below .01.
        rows = b''.join(b'\0' + bytes(c for x in range(width) for c in
                          ([value] * 3 if x < 8 and y < 8 else [240] * 3))
                        for y in range(24))
        return (b'\x89PNG\r\n\x1a\n' +
                chunk(b'IHDR', struct.pack('>IIBBBBB', width, 24, 8, 2, 0, 0, 0)) +
                chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))

    system, gamelist = png(240), png(224)
    oracle = ViewIdentity(dict(system=[system], gamelist=[gamelist]))
    assert oracle.separation < .01
    oracle.expect('system', system, 'system')
    oracle.expect('gamelist', gamelist, 'enter')
    oracle.expect('system', system, 'back')
    for name, action in (
            ('missing Enter', lambda: oracle.expect('gamelist', system, 'wrong-enter')),
            ('missing Back', lambda: oracle.expect('system', gamelist, 'wrong-back')),
            ('ambiguous frame', lambda: oracle.expect('system', png(232), 'tie')),
            ('unrelated frame', lambda: oracle.expect('system', png(0), 'unknown')),
            ('resized frame', lambda: oracle.expect('system', png(240, 36), 'size')),
            ('identical references', lambda: ViewIdentity(dict(system=[system], gamelist=[system]))),
            ('resized references', lambda: ViewIdentity(dict(system=[system], gamelist=[png(224, 36)])))):
        try:
            action()
        except AssertionError:
            pass
        else:
            raise AssertionError('View identity control escaped: ' + name)
    animated = ViewIdentity(dict(system=[system], gamelist=[png(0), png(64)]))
    animated.expect('gamelist', png(0), 'video-first')
    animated.expect('gamelist', png(64), 'video-second')
    return ('PASS: view identity accepts sparse changes below .01; rejects missing Enter/Back, '
            'ambiguous/unrelated/resized frames and invalid references; accepts both video frames.\n')


if __name__ == '__main__':
    print(controls(), end='')
