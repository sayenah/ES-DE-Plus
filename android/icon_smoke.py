#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Pixel Plus evidence from the real system UI.
import re
import pdf_smoke


def capture(shell, adb, hierarchy, wait_for, screenshot, app, label, evidence, television):
    # Run before the frontend starts: system identity evidence remains available
    # even if an unrelated lifecycle regression fails a later smoke probe.
    candidates = shell('cmd', 'package', 'query-activities', '--brief',
                       '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME')
    stock = next(line.strip() for line in candidates.splitlines() if '/' in line and
                 ' ' not in line.strip() and not line.strip().startswith(app + '/') and
                 'ResolverActivity' not in line)
    package = stock.split('/')[0]

    def home():
        shell('am', 'start', '-a', 'android.intent.action.MAIN',
              '-c', 'android.intent.category.HOME', '-n', stock)
        wait_for(lambda: any(n.get('package') == package for n in hierarchy()), 'icon stock HOME')

    def matches(node, text):
        return any(text.casefold() == node.get(key, '').casefold() for key in ('text', 'content-desc'))

    def target(text):
        return next((n for n in hierarchy() if matches(n, text)), None)

    def centre(node):
        x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.get('bounds')))
        return (x1 + x2) // 2, (y1 + y2) // 2

    def tap(node):
        shell('input', 'tap', *map(str, centre(node)))

    def record(name):
        nodes = hierarchy()
        (evidence / (name + '-ui.txt')).write_text('\n'.join(str(n.attrib) for n in nodes))
        screenshot(name)

    home()
    if television:
        # Select the stock launcher's own Add app tile and actual package label;
        # never substitute a fabricated banner preview for the home row.
        if target(label) is None:
            choices = ['Add app to favorites', 'Add app to favourites', 'Add app']
            tile = next((target(text) for text in choices if target(text) is not None), None)
            record('icon-tv-home-before')
            assert tile is not None, 'Stock TV HOME has no Add app tile; see icon-tv-home-before-ui.txt'
            tap(tile)
            wait_for(lambda: target(label) is not None, 'TV favorite picker Pixel Plus')
            tap(target(label))
            home()
        wait_for(lambda: target(label) is not None, 'Pixel Plus banner in real TV HOME row')
        record('icon-tv-home-banner')
        return

    if int(shell('getprop', 'ro.build.version.sdk').strip()) != 34:
        return
    width, height = map(int, re.findall(r'(\d+)x(\d+)', shell('wm', 'size'))[-1])
    shell('input', 'swipe', str(width // 2), str(height - 100), str(width // 2), '100', '500')
    wait_for(lambda: target(label) is not None, 'Pixel Plus in real launcher drawer')
    record('icon-api34-launcher-drawer')
    x, y = centre(target(label))
    shell('input', 'draganddrop', str(x), str(y), str(width // 2), str(height // 3), '1500')
    home()
    wait_for(lambda: target(label) is not None, 'Pixel Plus placed on real launcher HOME')
    record('icon-api34-launcher')
    bounds = list(map(int, re.findall(r'\d+', target(label).get('bounds'))))

    def colour_counts(path):
        width, height, channels, rows = pdf_smoke.pixels(path.read_bytes())
        colours = [(0, 209, 255), (255, 45, 120), (255, 194, 61), (34, 214, 140)]
        counts = [0] * len(colours)
        x1, y1, x2, y2 = bounds
        for y in range(max(0, y1), min(height, y2)):
            for x in range(max(0, x1), min(width, x2)):
                rgb = rows[y][x * channels:x * channels + 3]
                for i, colour in enumerate(colours):
                    if all(abs(a - b) <= 3 for a, b in zip(rgb, colour)):
                        counts[i] += 1
        return counts

    normal = colour_counts(evidence / 'icon-api34-launcher.png')
    assert min(normal) >= 5, ('Launcher does not show all four Pixel Plus colours', normal, bounds)
    shell('am', 'start', '-a', 'android.settings.APPLICATION_DETAILS_SETTINGS', '-d', 'package:' + app)
    wait_for(lambda: target(label) is not None and any(n.get('package') == 'com.android.settings'
                                                     for n in hierarchy()), 'Pixel Plus app info')
    record('icon-api34-app-info')
    home()

    # Launcher3's exported GridCustomizationsProvider is the public interface
    # used by Wallpaper & style for this setting. The emulator's wallpaper app
    # crashes in its clock carousel; query/update the real launcher mode and
    # verify the actual HOME rendering through that interface instead.
    provider = 'content://' + package + '.grid_control/icon_themed'

    def read_mode():
        response = shell('content', 'query', '--uri', provider)
        values = re.findall(r'\bboolean_value=([01])\b', response)
        assert len(values) == 1, ('Unexpected public themed-icon provider reply', provider, response)
        return values[0], response

    def set_mode(value):
        response = shell('content', 'update', '--uri', provider, '--bind',
                         'boolean_value:b:' + ('true' if value == '1' else 'false'))
        wait_for(lambda: read_mode()[0] == value, 'public themed-icon provider state=' + value)
        return response

    original, before = read_mode()
    transcript = evidence / 'icon-api34-themed-mode.txt'
    transcript.write_text('Real launcher public provider: ' + provider + '\nOriginal query: ' + before)
    try:
        changed = set_mode('1')
        enabled, after = read_mode()
        assert enabled == '1'
        with transcript.open('a') as output:
            output.write('Enable update: ' + changed + '\nEnabled query: ' + after)
        home()
        wait_for(lambda: target(label) is not None, 'Pixel Plus in themed launcher HOME')
        record('icon-api34-themed-launcher')
        themed = colour_counts(evidence / 'icon-api34-themed-launcher.png')
        assert max(themed) < 5, ('Themed HOME still shows colour layers', themed, bounds)
        with transcript.open('a') as output:
            output.write(f'PASS: actual HOME icon colour samples normal={normal}, themed={themed}; '
                         'public provider readback=1 and monochrome mode rendered.\n')
    finally:
        restored = set_mode(original)
        with transcript.open('a') as output:
            output.write('Restore update: ' + restored + '\nRestored query: ' + read_mode()[1])
        home()
