#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Pixel Plus evidence from the real system UI.
import re
import xml.etree.ElementTree as ET
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

    # The google_apis image ships AOSP Launcher3, whose themed_icons preference
    # has no Wallpaper & Style switch. Enable its real mode on the userdebug
    # emulator, using the preference documented by AOSP Themes/LauncherPrefs.
    # Only the stock launcher's preference changes; restore it in finally.
    assert package == 'com.android.launcher3', ('Unsupported themed-icon launcher', stock)
    print(adb('root'), flush=True)
    adb('wait-for-device')
    preference = '/data/user/0/' + package + '/shared_prefs/com.android.launcher3.prefs.xml'
    shell('am', 'force-stop', package)
    original = shell('cat', preference)
    owner = shell('stat', '-c', '%u:%g', preference).strip()
    document = ET.fromstring(original)
    for node in list(document):
        if node.get('name') == 'themed_icons':
            document.remove(node)
    ET.SubElement(document, 'boolean', name='themed_icons', value='true')
    temporary = evidence / 'icon-launcher-preference.xml'

    def write_preference(value):
        temporary.write_text(value)
        adb('push', str(temporary), preference)
        shell('chown', owner, preference)
        shell('chmod', '660', preference)
        shell('restorecon', preference)

    try:
        write_preference(ET.tostring(document, encoding='unicode'))
        enabled = shell('cat', preference)
        assert ET.fromstring(enabled).find("boolean[@name='themed_icons']").get('value') == 'true'
        (evidence / 'icon-api34-themed-mode.txt').write_text(
            'Real AOSP Launcher3 themed_icons=true, read back before launcher restart.\n' + enabled)
        home()
        wait_for(lambda: target(label) is not None, 'Pixel Plus in themed launcher HOME')
        record('icon-api34-themed-launcher')
        themed = colour_counts(evidence / 'icon-api34-themed-launcher.png')
        assert max(themed) < 5, ('Themed HOME still shows colour layers', themed, bounds)
        with (evidence / 'icon-api34-themed-mode.txt').open('a') as output:
            output.write(f'PASS: actual HOME icon colour samples normal={normal}, themed={themed}; monochrome mode rendered.\n')
    finally:
        shell('am', 'force-stop', package)
        write_preference(original)
        temporary.unlink(missing_ok=True)
        home()
        print(adb('unroot'), flush=True)
        adb('wait-for-device')
