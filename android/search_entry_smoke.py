#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real browsing/search/favorite input assertions.
import json
import re
import time
import xml.etree.ElementTree as ET


def run(h, start, control, shot, record):
    """Runs inside the fresh touch session, using its owned frontend and geometry."""
    root = h.settings.rsplit('/settings/', 1)[0]
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
        action()
        h.wait_for(lambda: opens() == before + 1, 'one search opened from browsing')
        assert f'SearchEntry: open initial={initial} scope={scope}' in h.log()
        for key in ['KEYCODE_INSERT', 'KEYCODE_SEARCH']:
            h.key(key)
        h.key('KEYCODE_INSERT')
        assert opens() == before + 1, 'Search stacked while its screen was open'
        return before + 1

    def close_popup():
        h.key('KEYCODE_ESCAPE')  # Unchanged initial value: closes without a save dialog.

    def game_flag(name, expected):
        def saved():
            text = h.shell('cat', gamelist_path, check=False)
            if not text.lstrip().startswith('<?xml') and not text.lstrip().startswith('<gameList'):
                return False
            games = ET.fromstring(text)
            return any(g.findtext('path') == './' + name + '.nes' and
                       g.findtext('favorite', 'false') == str(expected).lower() for g in games)
        h.wait_for(saved, 'actual persisted favorite ' + name + '=' + str(expected))

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
        mappings = dict(up=1073741906, down=1073741905, left=1073741904, right=1073741903,
                        a=13, b=8, x=127, y=1073741897, back=1073741882, start=27)
        keyboard = ET.Element('inputList')
        config = ET.SubElement(keyboard, 'inputConfig', type='keyboard', deviceName='Keyboard', deviceGUID='-1')
        for action, code in mappings.items():
            ET.SubElement(config, 'input', name=action, type='key', id=str(code), value='1')
        # M is a letter, but a user mapping takes priority over typing-to-search.
        ET.SubElement(config, 'input', name='leftshoulder', type='key', id=str(ord('m')), value='1')
        write('settings/es_input.xml', ET.tostring(keyboard, encoding='unicode'))
        start(InputTouchOverlay=True, UIMode='full', StartupView='gamelist')
        h.key('KEYCODE_M')
        assert opens() == 0, 'A mapped letter was stolen by typing-to-search'
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
        assert 'Scripting::fireEvent(): screensaver-start "manual"' in h.log()
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
        h.key('KEYCODE_FORWARD_DEL')
        h.wait_for(lambda: 'Scripting::fireEvent(): mediaviewer-start' in h.log(), 'real media viewer opened')
        shot('search-entry-media-viewer')
        count = opens()
        h.key('KEYCODE_INSERT')
        h.key('KEYCODE_SEARCH')
        control(102)
        assert opens() == count, 'Search opened over the media viewer'
        h.key('KEYCODE_DEL')
        opening(lambda: h.key('KEYCODE_INSERT'), 'nes')
        close_popup()
        record('search-entry-media-viewer')

        # Favorite sorting, persisted metadata and the actual enabled favorites collection.
        start(InputTouchOverlay=True, UIMode='full', StartupView='gamelist',
              GamelistYButton='search', CollectionSystemsAuto='favorites', FavoritesFirst=True,
              FavoritesAddButton=True, SaveGamelistsMode='always')
        h.key('KEYCODE_DPAD_DOWN')  # Beta; favorite sort should move it to the first row.
        for expected in [True, False]:
            h.key('KEYCODE_F1')  # Select options.
            h.key('KEYCODE_DPAD_DOWN')  # Sort.
            h.key('KEYCODE_DPAD_DOWN')  # Add/remove favorite.
            shot('search-entry-favorite-options-' + str(expected))
            h.key('KEYCODE_ENTER')
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
        write('collections/custom-SearchEntrySmoke.cfg', h.roms + '/nes/Smoke Alpha.nes\n')
        start(InputTouchOverlay=True, UIMode='full', StartupSystem='SearchEntrySmoke',
              StartupView='gamelist', CollectionSystemsCustom='SearchEntrySmoke',
              CollectionCustomGrouping='never', GamelistYButton='search', FavoritesAddButton=False)
        h.key('KEYCODE_F1')
        # Jump, sort, favorites, filter, edit collection.
        for _ in range(4):
            h.key('KEYCODE_DPAD_DOWN')
        h.key('KEYCODE_ENTER')
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
    finally:
        prepare('restore')
    (h.evidence / 'search-entry-result.txt').write_text(
        'PASS: Y in full/kiosk/kid system and gamelist views; magnifier; no stacking; '
        'physical letter/digit exactly once; slash and search key empty; main-menu ownership; '
        'screensaver ownership; Select favorites flag/collection/sort; favorites preference and '
        'disabled upstream button; custom collection editing.\n')
