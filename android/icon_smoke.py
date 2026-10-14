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

    # Use the stock launcher's actual Wallpaper & style UI. The google_apis
    # image includes Pixel Launcher; do not assume another launcher's private
    # preferences or replace a real themed-icon screenshot with a preview.
    def theme_toggle():
        candidates = []
        for parent in hierarchy():
            children = list(parent.iter('node'))
            switches = [n for n in children if n.get('checkable') == 'true' and
                        n.get('class', '').endswith('Switch')]
            if len(switches) == 1 and any(matches(n, 'Themed icons') for n in children):
                candidates.append((len(children), switches[0]))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    def open_theme_settings():
        home()
        x, y = width // 4, height // 2
        shell('input', 'swipe', str(x), str(y), str(x), str(y), '1000')
        names = ['Wallpaper & style', 'Wallpapers & style']
        wait_for(lambda: any(target(name) is not None for name in names), 'real Wallpaper & style menu')
        record('icon-api34-wallpaper-menu')
        tap(next(target(name) for name in names if target(name) is not None))
        wait_for(lambda: target('Home screen') is not None or theme_toggle() is not None,
                 'Wallpaper & style Home screen controls')
        if target('Home screen') is not None:
            tap(target('Home screen'))
        for _ in range(8):
            toggle = theme_toggle()
            if toggle is not None:
                return toggle
            shell('input', 'swipe', str(width // 2), str(height * 4 // 5),
                  str(width // 2), str(height // 3), '500')
        record('icon-api34-missing-themed-toggle')
        raise AssertionError('The real Wallpaper & style UI has no Themed icons switch')

    toggle = open_theme_settings()
    original = toggle.get('checked')
    assert original in ('true', 'false'), ('Missing themed-icon switch state', toggle.attrib)
    try:
        if original != 'true':
            tap(toggle)
        wait_for(lambda: theme_toggle() is not None and theme_toggle().get('checked') == 'true',
                 'real Themed icons switch checked')
        record('icon-api34-themed-setting')
        home()
        wait_for(lambda: target(label) is not None, 'Pixel Plus in themed launcher HOME')
        record('icon-api34-themed-launcher')
        themed = colour_counts(evidence / 'icon-api34-themed-launcher.png')
        assert max(themed) < 5, ('Themed HOME still shows colour layers', themed, bounds)
        (evidence / 'icon-api34-themed-mode.txt').write_text(
            f'PASS: real Wallpaper & style Themed icons switch checked=true; actual HOME icon '
            f'colour samples normal={normal}, themed={themed}; monochrome mode rendered.\n')
    finally:
        toggle = open_theme_settings()
        if toggle.get('checked') != original:
            tap(toggle)
        wait_for(lambda: theme_toggle() is not None and theme_toggle().get('checked') == original,
                 'original themed-icon setting restored through UI')
        home()
