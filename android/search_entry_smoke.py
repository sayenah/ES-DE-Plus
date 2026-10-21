#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real browsing/search/favorite input assertions.
import json
import math
import re
import time
import xml.etree.ElementTree as ET

from importer_navigation import activate


def run(h, start, control, shot, record):
    """Runs inside the fresh touch session, using its owned frontend and geometry."""
    root = h.settings.rsplit('/settings/', 1)[0]
    entry_times = []
    gamelist_path = root + '/gamelists/nes/gamelist.xml'
    fixture = ('<gameList><game><path>./Smoke Alpha.nes</path><name>Smoke Alpha</name>'
               '<kidgame>true</kidgame><favorite>false</favorite></game>'
               '<game><path>./Smoke Beta.nes</path><name>Smoke Beta</name>'
               '<kidgame>true</kidgame><favorite>false</favorite></game></gameList>')

    def prepare(operation, **arguments):
        h.shell('am', 'force-stop', h.app)
        result = h.shell('am', 'instrument', '-w', '-e', 'mode', 'search-fixture', '-e', 'steps',
                         json.dumps(dict(operation=operation, **arguments)),
                         h.app + '/org.esdeplus.frontend.TouchSmoke')
        assert 'PASS: search entry fixture ' + operation in result, result
        h.shell('am', 'force-stop', h.app)

    def write(relative, contents):
        prepare('write', relative=relative, contents=contents)

    def opens():
        return h.log().count('SearchEntry: open ')

    def opening(action, scope, initial=''):
        before = opens()
        ready_before = h.log().count('Search entry ready:')
        action()
        h.wait_for(lambda: opens() == before + 1, 'one search opened from browsing')
        assert f'SearchEntry: open initial={initial} scope={scope}' in h.log()
        h.wait_for(lambda: h.log().count('Search entry ready:') == ready_before + 1,
                   'entry completes before collecting its timing')
        current = h.log()
        assert current.count('Search renderer prepared once:') == 1, 'Renderer preparation repeated on entry'
        entry_times.append(float(re.findall(r'Search entry ready: ms=([0-9.]+)', current)[-1]))
        def query_is(value):
            values = re.findall(r'Search keystroke: query=(.*?) results=\d+ query_bytes=(\d+)', h.log())
            return bool(values) and (values[-1][0] == value or
                                    (values[-1][0] == '<private>' and
                                     int(values[-1][1]) == len(value.encode())))
        h.wait_for(lambda: query_is(initial), 'opening text inserted exactly once')
        marker = len(h.log())
        for key in ['KEYCODE_INSERT', 'KEYCODE_SEARCH']:
            h.key(key)
        h.key('KEYCODE_INSERT')
        h.wait_for(lambda: len(re.findall(r'Key Insert, .*value=0', h.log()[marker:])) == 2,
                   'both duplicate-entry probe keys released')
        assert opens() == before + 1, 'Search stacked while its screen was open'
        # Y now has its controller action inside Search: each mapped Insert adds
        # one space. Verify that action, then restore the seed for the entry tests.
        # The later custom-keyboard case maps Y to M, leaving Insert unmapped.
        inserted = len(re.findall(r'Key Insert, isMappedTo=y, value=1', h.log()[marker:]))
        h.wait_for(lambda: query_is(initial + ' ' * inserted), 'mapped Y spaces without another entry')
        for _ in range(inserted):
            h.key('KEYCODE_DEL')
        h.wait_for(lambda: query_is(initial), 'exact seed restored after duplicate-entry probes')
        return before + 1

    def close_popup():
        before = h.log().count('Search screen closed')
        current = h.log().rsplit('Search layout:', 1)[-1]
        close = re.findall(r'Search touch target: area=7 index=0 norm=([0-9.]+),([0-9.]+)', current)
        if close:
            geometry = h.shell('am', 'broadcast', '-n', h.app + '/org.esdeplus.frontend.TouchSmoke$SurfaceGeometry')
            assert 'PASS: owned surface geometry recorded' in geometry
            view = json.loads(h.adb('exec-out', 'run-as', h.app, 'cat', 'cache/touch-surface-geometry.json'))
            nx, ny = map(float, close[-1])
            h.shell('input', 'touchscreen', 'tap', str(round(view['x'] + nx * view['bufferWidth'])),
                    str(round(view['y'] + ny * view['bufferHeight'])))
        else:
            h.key('KEYCODE_ESCAPE')
        h.wait_for(lambda: h.log().count('Search screen closed') == before + 1,
                   'search actually closed before the next entry')

    def live_event(event, occurrence=1):
        # A key can finish before the next rendered frame flushes es_log.txt.
        # Observe this process's actual event, without a second input or restart.
        pid = h.shell('pidof', h.app).strip()
        assert pid.isdigit(), ('Frontend process missing', pid)
        def observed():
            output = h.adb('logcat', '-d', '-v', 'threadtime', '--pid=' + pid)
            if output.count('Scripting::fireEvent(): ' + event) >= occurrence:
                (h.evidence / ('search-entry-' + event.split()[0] + '-logcat.txt')).write_text(output)
                return True
            return False
        h.wait_for(observed, 'live frontend ' + event, timeout=20)

    def game_flag(name, expected):
        def saved():
            text = h.shell('cat', gamelist_path, check=False)
            if not text.lstrip().startswith('<?xml') and not text.lstrip().startswith('<gameList'):
                return False
            games = ET.fromstring(text)
            return any(g.findtext('path') == './' + name + '.nes' and
                       g.findtext('favorite', 'false') == str(expected).lower() for g in games)
        h.wait_for(saved, 'actual persisted favorite ' + name + '=' + str(expected))

    def option_row(target):
        # Observe native key release and focus, rather than assuming a fixed
        # number of row movements while an animated menu is opening.
        before = len(h.log())
        def key(code, name, mapping):
            marker = len(h.log())
            h.key(code)
            h.wait_for(lambda: f'Key {name}, isMappedTo={mapping}, value=0' in h.log()[marker:],
                       'gamelist options key release ' + name, timeout=20)
        def focused():
            rows = re.findall(r'Gamelist options: focused=(.*)', h.log()[before:])
            return rows[-1] if rows else None
        order = {'JUMP TO...': 0, 'SORT GAMES BY': 1, 'ADD TO FAVORITES': 2,
                 'REMOVE FROM FAVORITES': 2, 'FILTER GAMELIST': 3,
                 'ADD/REMOVE GAMES TO THIS COLLECTION': 4, "EDIT THIS GAME'S METADATA": 5}
        key('KEYCODE_F1', 'F1', 'back')
        h.wait_for(lambda: focused() is not None, 'gamelist options initial focus', timeout=20)
        for _ in range(12):
            label = focused()
            assert label in order, ('Unexpected game options focus', label, target)
            with (h.evidence / 'search-entry-options-navigation.txt').open('a') as trace:
                trace.write(f'focused={label}; target={target}\n')
            if label == target:
                shot('search-entry-options-' + target.lower().replace(' ', '-').replace('/', '-'))
                activate(label, target, h.key)
                return
            assert order[label] != order[target], ('Unexpected favorite state', label, target)
            up = order[label] > order[target]
            key('KEYCODE_DPAD_UP' if up else 'KEYCODE_DPAD_DOWN',
                'Up' if up else 'Down', 'up' if up else 'down')
            h.wait_for(lambda: focused() != label, 'gamelist options focus changed', timeout=20)
        raise AssertionError('Game options did not reach verified target: ' + target)

    prepare('prepare')
    try:
        write('gamelists/nes/gamelist.xml', fixture)
        for mode in ['full', 'kiosk', 'kid']:
            start(InputTouchOverlay=True, UIMode=mode, GamelistYButton='search')
            opening(lambda: h.key('KEYCODE_INSERT'), 'all')
            shot('search-entry-' + mode + '-system')
            close_popup()
            h.key('KEYCODE_ENTER')  # Enter NES.
            opening(lambda: h.key('KEYCODE_INSERT'), 'nes')
            shot('search-entry-' + mode + '-gamelist')
            close_popup()
            record('search-entry-' + mode)

        for mode in ['kid', 'kiosk']:
            start(InputTouchOverlay=True, UIMode=mode, UIMode_passkey='yya',
                  GamelistYButton='search')
            count = opens()
            h.key('KEYCODE_INSERT')
            h.key('KEYCODE_INSERT')
            assert opens() == count, 'Y interrupted a custom restricted-mode passkey'
            h.key('KEYCODE_ENTER')
            h.wait_for(lambda: 'Passkey sequence completed, switching UI mode to Full' in h.log(),
                       'custom passkey containing Y completed')
            record('search-entry-passkey-' + mode)

        start(InputTouchOverlay=True, UIMode='full', GamelistYButton='search')
        # Mapped Enter keeps its select action, and the magnifier is independent of Y.
        h.key('KEYCODE_ENTER')
        assert opens() == 0
        opening(lambda: control(102), 'nes')
        shot('search-entry-magnifier')
        close_popup()
        for key, initial in [('KEYCODE_M', 'm'), ('KEYCODE_7', '7'),
                             ('KEYCODE_SLASH', ''), ('KEYCODE_SEARCH', '')]:
            opening(lambda: h.key(key), 'nes', initial)
            if initial:
                queries = re.findall(r'Search keystroke: query=(.*?) results=', h.log())
                assert queries[-1] == initial, ('Opening key was inserted twice', queries)
                h.key('KEYCODE_ENTER')  # Records the query and focuses the live results.
                shot('search-entry-' + initial + '-exactly-once')
                count = opens()
                h.key('KEYCODE_INSERT')
                h.key('KEYCODE_SEARCH')
                assert opens() == count, 'Search stacked over results'
                close_popup()
            else:
                # Empty Enter keeps the full screen open and moves to zero-state results.
                count = opens()
                h.key('KEYCODE_ENTER')
                assert opens() == count
                close_popup()
        # A shifted digit must seed the live field with layout text, not its key identity.
        opening(lambda: h.shell('input', 'keycombination', 'KEYCODE_SHIFT_LEFT', 'KEYCODE_7'),
                'nes', '&')
        queries = re.findall(r'Search keystroke: query=(.*?) results=', h.log())
        assert queries[-1] == '&', ('Layout text was inserted more than once', queries)
        count = opens()
        h.key('KEYCODE_ENTER')
        assert opens() == count
        assert re.findall(r'Search keystroke: query=(.*?) results=', h.log())[-1] == '&'
        close_popup()
        record('search-entry-layout-text')
        mappings = dict(up=1073741906, down=1073741905, left=1073741904, right=1073741903,
                        a=13, b=8, x=127, y=1073741897, back=1073741882, start=27)
        keyboard = ET.Element('inputList')
        config = ET.SubElement(keyboard, 'inputConfig', type='keyboard', deviceName='Keyboard', deviceGUID='-1')
        for action, code in mappings.items():
            ET.SubElement(config, 'input', name=action, type='key', id=str(code), value='1')
        # M is a letter, but a user mapping takes priority over typing-to-search.
        next(e for e in config if e.get('name') == 'y').set('id', str(ord('m')))
        write('settings/es_input.xml', ET.tostring(keyboard, encoding='unicode'))
        start(InputTouchOverlay=True, UIMode='full', StartupView='gamelist')
        opening(lambda: h.key('KEYCODE_M'), 'nes', '')
        h.key('KEYCODE_ENTER')
        assert re.findall(r'Search keystroke: query=(.*?) results=', h.log())[-1] == '', \
            'A mapped letter also inserted text into the search screen'
        close_popup()
        opening(lambda: h.key('KEYCODE_SEARCH'), 'nes')
        close_popup()
        record('search-entry-mapping-priority')
        prepare('restore-one', relative='settings/es_input.xml')
        start(InputTouchOverlay=True, UIMode='full', StartupView='gamelist')
        # Main menu owns its input: Y/Search/magnifier cannot open another GUI.
        h.key('KEYCODE_ESCAPE')
        count = opens()
        h.key('KEYCODE_INSERT')
        h.key('KEYCODE_SEARCH')
        control(102)
        assert opens() == count, 'Search opened over the main menu'
        h.key('KEYCODE_ENTER')  # Its SEARCH entry uses the same seam.
        assert opens() == count + 1
        close_popup()
        h.key('KEYCODE_DEL')  # Close menu.
        record('search-entry-keyboard-menu')

        # Non-media screensaver is an observable live screensaver, with no fixtures needed.
        start(InputTouchOverlay=True, UIMode='full', ScreensaverControls=True,
              ScreensaverType='dim', ScreensaverTimer=0, CustomEventScripts=True)
        h.key('KEYCODE_FORWARD_DEL')  # System X starts the screensaver.
        live_event('screensaver-start "manual"')
        shot('search-entry-screensaver')
        count = opens()
        control(102)  # Magnifier is inert; Y only dismisses the screensaver.
        h.key('KEYCODE_INSERT')
        assert opens() == count, 'Search opened while screensaver was on top'
        opening(lambda: h.key('KEYCODE_INSERT'), 'all')
        close_popup()
        record('search-entry-screensaver')

        start(InputTouchOverlay=True, UIMode='full', StartupView='gamelist',
              CustomEventScripts=True, MediaDirectory='')
        for occurrence, key in enumerate(['KEYCODE_INSERT', 'KEYCODE_SEARCH'], 1):
            h.key('KEYCODE_FORWARD_DEL')
            live_event('mediaviewer-start', occurrence)
            shot('search-entry-media-viewer-' + key)
            count = opens()
            stops = h.log().count('Scripting::fireEvent(): mediaviewer-stop')
            control(102)
            assert opens() == count, 'Magnifier opened Search over the media viewer'
            assert h.log().count('Scripting::fireEvent(): mediaviewer-stop') == stops, \
                'Magnifier dismissed the media viewer'
            # Upstream dismisses the viewer on other inputs. A later key may then
            # open Search, so test each dismissing input with a newly active viewer.
            h.key(key)
            live_event('mediaviewer-stop', occurrence)
            assert opens() == count, 'Viewer dismissal also opened Search'
            record('search-entry-media-viewer-' + key)
        opening(lambda: h.key('KEYCODE_INSERT'), 'nes')
        close_popup()
        record('search-entry-media-viewer')

        # Favorite sorting, persisted metadata and the actual enabled favorites collection.
        start(InputTouchOverlay=True, UIMode='full', StartupView='gamelist',
              GamelistYButton='search', CollectionSystemsAuto='favorites', FavoritesFirst=True,
              FavoritesAddButton=True, SaveGamelistsMode='always')
        h.key('KEYCODE_DPAD_DOWN')  # Beta; favorite sort should move it to the first row.
        for expected in [True, False]:
            option_row('ADD TO FAVORITES' if expected else 'REMOVE FROM FAVORITES')
            game_flag('Smoke Beta', expected)
            value = int(expected)
            h.wait_for(lambda: f'Favorites collection: game=Smoke Beta favorite={value} enabled=1 count={value}' in h.log(),
                       'favorite collection membership refreshed')
            if expected:
                assert 'first=Smoke Beta' in h.log(), 'Favorites-first sort was not refreshed'
                # Upstream keeps the list position (Alpha), so navigate back to Beta.
                h.key('KEYCODE_DPAD_UP')
        record('search-entry-favorites-menu')

        start(InputTouchOverlay=True, UIMode='full', StartupView='gamelist',
              GamelistYButton='favorites', CollectionSystemsAuto='favorites', FavoritesAddButton=True)
        h.key('KEYCODE_INSERT')
        game_flag('Smoke Alpha', True)
        assert opens() == 0, 'Favorites setting failed to restore upstream Y'
        h.key('KEYCODE_DPAD_UP')  # Upstream retained the next row when Alpha became favorite.
        h.key('KEYCODE_INSERT')
        game_flag('Smoke Alpha', False)
        h.key('KEYCODE_DEL')
        opening(lambda: h.key('KEYCODE_INSERT'), 'all')
        close_popup()
        record('search-entry-favorites-setting')
        start(InputTouchOverlay=True, UIMode='full', StartupView='gamelist',
              GamelistYButton='favorites', FavoritesAddButton=False)
        h.key('KEYCODE_INSERT')
        assert opens() == 0
        game_flag('Smoke Alpha', False)
        record('search-entry-favorites-disabled')

        # An ordinary user-owned custom collection. Enter editing through its Select menu.
        # Use the format ES-DE itself saves. Shell aliases such as /sdcard need
        # not match the frontend's canonical keys in its all-games index.
        write('collections/custom-SearchEntrySmoke.cfg', '%ROMPATH%/nes/Smoke Alpha.nes\n')
        start(InputTouchOverlay=True, UIMode='full', StartupSystem='collections',
              StartupView='gamelist', CollectionSystemsCustom='SearchEntrySmoke',
              CollectionCustomGrouping='always', GamelistYButton='search')
        assert 'ignoring entry' not in h.log(), 'Grouped custom collection fixture did not load'
        count = opens()
        h.key('KEYCODE_INSERT')  # Upstream jumps from the folder to its sole game.
        assert opens() == count, 'Y opened search instead of jumping into the grouped collection'
        opening(lambda: h.key('KEYCODE_INSERT'), 'collections')
        close_popup()
        record('search-entry-grouped-collection-jump')
        start(InputTouchOverlay=True, UIMode='full', StartupSystem='SearchEntrySmoke',
              StartupView='gamelist', CollectionSystemsCustom='SearchEntrySmoke',
              CollectionCustomGrouping='never', GamelistYButton='search', FavoritesAddButton=False)
        assert 'ignoring entry' not in h.log(), 'Custom collection fixture did not load: ' + h.log()
        option_row('ADD/REMOVE GAMES TO THIS COLLECTION')
        count = opens()
        h.key('KEYCODE_INSERT')
        assert opens() == count, 'Y opened search while editing a custom collection'
        h.wait_for(lambda: 'editing=1' in h.log(), 'existing collection editing handler ran')
        content = h.shell('cat', root + '/collections/custom-SearchEntrySmoke.cfg')
        assert 'Smoke Alpha.nes' not in content, 'Collection-editing Y did not remove the entry'
        game_flag('Smoke Alpha', False)
        shot('search-entry-collection-editing')
        record('search-entry-collection-editing')
        try:
            for label, width, height, density in [
                    ('phone-portrait', 1080, 1920, 420), ('phone-landscape', 1920, 1080, 420),
                    ('tablet-portrait', 1600, 2560, 320), ('tablet-landscape', 2560, 1600, 320)]:
                h.shell('am', 'force-stop', h.app)
                h.shell('wm', 'size', str(width) + 'x' + str(height))
                h.shell('wm', 'density', str(density))
                start(InputTouchOverlay=True, UIMode='full', ScreenRotate=0,
                      InputTouchOverlaySize='medium', StartupView='system')
                current = h.log().rsplit('InputOverlay: layout ', 1)[-1]
                ids = re.findall(r'InputOverlay: button id=(\d+)', current)
                assert len(ids) == 15 and len(set(ids)) == 15, (label, current)
                assert 'supported=1' in current
                if label.startswith('tablet'):
                    assert 'fit=2' not in current, 'MEDIUM-1 tablet regressed to compact'
                time.sleep(0.5)
                shot('search-entry-' + label + '-fifteen-controls')
                record('search-entry-' + label)
        finally:
            h.shell('am', 'force-stop', h.app)
            h.shell('wm', 'size', 'reset')
            h.shell('wm', 'density', 'reset')
    except Exception:
        record('search-entry-failure')
        shot('search-entry-failure')
        (h.evidence / 'search-entry-failure-logcat.txt').write_text(
            h.adb('logcat', '-d', '-v', 'threadtime'))
        raise
    finally:
        prepare('restore')
    entry_times.sort()
    assert entry_times, 'Missing entry-point timing samples'
    timing = dict(samples=len(entry_times), p50_ms=entry_times[math.ceil(len(entry_times) * .5) - 1],
                  p95_ms=entry_times[math.ceil(len(entry_times) * .95) - 1], max_ms=entry_times[-1])
    (h.evidence / 'search-entry-timing.txt').write_text(json.dumps(timing, indent=2) + '\n')
    print('GATING shared search entry: p95 <= 150ms; measured', json.dumps(timing), flush=True)
    assert timing['p95_ms'] <= 150, ('Search entry points exceeded p95 150ms', timing)
    (h.evidence / 'search-entry-result.txt').write_text(
        'PASS: Y in full/kiosk/kid system and gamelist views; magnifier; no stacking; '
        'physical letter/digit exactly once; slash and search key empty; main-menu ownership; '
        'screensaver ownership; Select favorites flag/collection/sort; favorites preference and '
        'disabled upstream button; grouped collection jump; custom collection editing; '
        'layout text exactly once; custom kid/kiosk passkeys containing Y.\n')
