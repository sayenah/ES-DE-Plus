#!/usr/bin/env python3
#  SPDX-License-Identifier: MIT
#
#  ES-DE-Plus
#  search_screen_smoke.py
#
#  Written for ES-DE-Plus. Real controller, IME, direct-touch and timing evidence.
#

import json
import math
import re
import time
import xml.etree.ElementTree as ET

TARGET = re.compile(r'Search touch target: area=(\d+) index=(\d+) norm=([0-9.]+),([0-9.]+)')


def run(h, start, control, shot, record):
    root = h.settings.rsplit('/settings/', 1)[0]
    measurements = []
    prefix = f'search-screen-api{h.api}-'
    def prepare(operation, **arguments):
        h.shell('am', 'force-stop', h.app)
        result = h.shell('am', 'instrument', '-w', '-e', 'mode', 'search-fixture', '-e', 'steps',
                         json.dumps(dict(operation=operation, **arguments)),
                         h.app + '/org.esdeplus.frontend.TouchSmoke')
        assert 'PASS: search entry fixture ' + operation in result, result
        h.shell('am', 'force-stop', h.app)
    def write(relative, contents):
        prepare('write', relative=relative, contents=contents)
    def pad(button):
        result = h.shell('am', 'broadcast', '-n', h.app + '/org.esdeplus.frontend.TouchSmoke$SearchInput',
                         '--ei', 'button', str(button))
        assert 'PASS: SDL controller event' in result, result
        time.sleep(.25)
    def attach():
        pad(-1)
        h.wait_for(lambda: 'Search smoke controller' in h.log(), 'real virtual controller configured')
    def point(nx, ny):
        geometry = h.shell('am', 'broadcast', '-n', h.app + '/org.esdeplus.frontend.TouchSmoke$SurfaceGeometry')
        assert 'PASS: owned surface geometry recorded' in geometry
        view = json.loads(h.adb('exec-out', 'run-as', h.app, 'cat', 'cache/touch-surface-geometry.json'))
        return str(round(view['x'] + nx * view['bufferWidth'])), str(round(view['y'] + ny * view['bufferHeight']))
    def magnifier():
        current = h.log().rsplit('InputOverlay: layout ', 1)[-1]
        match = re.findall(r'InputOverlay: button id=102 .*? norm=([0-9.]+),([0-9.]+)', current)
        assert match, current
        h.shell('input', 'touchscreen', 'tap', *point(*map(float, match[-1])))
        time.sleep(.3)
    def target(area, index=0):
        current = h.log().rsplit('Search layout:', 1)[-1]
        found = [(float(x), float(y)) for a, i, x, y in TARGET.findall(current)
                 if int(a) == area and int(i) == index]
        assert found, (area, index, current)
        return point(*found[-1])
    def tap(area, index=0, hold=False):
        x, y = target(area, index)
        before = h.log()
        if hold:
            h.shell('input', 'touchscreen', 'swipe', x, y, x, y, '800')
        else:
            h.shell('input', 'touchscreen', 'tap', x, y)
        h.wait_for(lambda: 'InputOverlay: event type=up' in h.log()[len(before):], 'search owns complete touch')
        assert 'InputOverlay: owner=overlay' not in h.log()[len(before):], 'Overlay stole an in-screen control'
        time.sleep(.3)
    def ime(operation, text=''):
        result = h.shell('am', 'broadcast', '-n', h.app + '/org.esdeplus.frontend.TouchSmoke$SearchInput',
                         '--es', 'ime', operation, '--es', 'text', text)
        assert 'PASS: active SDL input connection' in result, result
        time.sleep(.25)
    def typed(text, private=False):
        value = ''
        for character in text:
            value += character
            before = len(h.log())
            h.shell('input', 'text', character)
            if private:
                h.wait_for(lambda: re.search(r'Search keystroke: query=<private> results=\d+ query_bytes=' +
                                            str(len(value.encode())) + r'\b', h.log()[before:]), 'private live stroke')
            else:
                h.wait_for(lambda: 'Search keystroke: query=' + value + ' results=' in h.log()[before:], 'live stroke ' + value)
            time.sleep(.15)
    def timing(name):
        times = [float(value) for value in re.findall(r'Search frame: .*? work_ms=([0-9.]+)', h.log())]
        assert times, 'Missing actual search frame measurements'
        measurements.extend(times)
        record(name)
    prepare('prepare')
    try:
        write('gamelists/nes/gamelist.xml',
              '<gameList><game><path>./Smoke Alpha.nes</path><name>Final Fantasy VII</name>'
              '<kidgame>true</kidgame><favorite>true</favorite><genre>RPG</genre>'
              '<releasedate>19970101T000000</releasedate><lastplayed>20261018T120000</lastplayed>'
              '<playtime>7200</playtime></game><game><path>./Smoke Beta.nes</path><name>Final Fight</name>'
              '<kidgame>false</kidgame><favorite>false</favorite>'
              '<lastplayed>20261019T120000</lastplayed></game></gameList>')
        write('custom_systems/es_systems.xml', '<systemList><loadExclusive/><system><name>nes</name><fullname>NES</fullname>'
              '<path>%ROMPATH%/nes</path><extension>.nes .NES</extension>'
              '<command>%EMULATOR_SEARCH_SMOKE% %ACTION%=android.intent.action.VIEW '
              '%MIMETYPE%=application/octet-stream %DATA%=%ROMPROVIDER%</command>'
              '<platform>nes</platform><theme>nes</theme></system></systemList>')
        write('custom_systems/es_find_rules.xml', '<ruleList><emulator name="SEARCH_SMOKE">'
              '<rule type="androidpackage"><entry>org.esdeplus.stub/.RecipientActivity</entry></rule></emulator></ruleList>')
        write('settings/search_history.xml', '<searchHistory/>')
        start(InputTouchOverlay=False, UIMode='full', CollectionSystemsAuto='favorites', SearchHistory=True)
        attach()
        pad(3)
        h.wait_for(lambda: 'Search screen opened:' in h.log(), 'Y search')
        # A/X/Y are actual controller events through InputManager, including deletion/space.
        pad(0)
        h.wait_for(lambda: 'Search keystroke: query=1 ' in h.log(), 'A types digit')
        pad(2)
        pad(3)
        h.wait_for(lambda: 'Search keystroke: query=  ' in h.log(), 'Y inserts a space')
        pad(2)
        for button in [12, 12, 14, 14, 14]: pad(button)  # f
        pad(0)
        for button in [11, 14, 14, 14, 14]: pad(button)  # i
        pad(0)
        for button in [12, 12, 13, 13]: pad(button)  # n
        pad(0)
        h.wait_for(lambda: 'Search keystroke: query=fin ' in h.log(), 'grid typed fin')
        shot(prefix + 'controller-fin')
        for _ in range(4): pad(11)
        h.wait_for(lambda: 'Search focus: area=2' in h.log(), 'Up reaches suggestions')
        pad(0)
        pad(10)
        pad(9)
        pad(6)
        shot(prefix + 'controller-results')
        before = len(h.log())
        pad(3)
        h.wait_for(lambda: 'game=Final Fantasy VII favorite=0' in h.log()[before:],
                   'Y removes the focused favorite and refreshes collections')
        before = len(h.log())
        pad(3)
        h.wait_for(lambda: 'game=Final Fantasy VII favorite=1' in h.log()[before:],
                   'Y keeps the same focused game after ranking changes')
        pad(0)
        h.wait_for(lambda: 'Search show game: nes/Final Fantasy VII' in h.log(), 'A puts cursor on real game list')
        history = ET.fromstring(h.shell('cat', root + '/settings/search_history.xml'))
        query = history.findtext('query')
        assert query and history.find('game').get('path') in ['Smoke Alpha.nes', 'Smoke Beta.nes']
        pad(3)
        pad(6)
        pad(11)
        h.wait_for(lambda: 'Search focus: area=5' in h.log(), 'recent searches focused')
        pad(2)
        history = ET.fromstring(h.shell('cat', root + '/settings/search_history.xml'))
        assert query not in [q.text for q in history.findall('query')], 'X did not remove recent search'
        h.key('KEYCODE_ESCAPE')
        pad(3)
        typed('fin')
        pad(6)
        pad(2)
        h.wait_for(lambda: re.search(r'mCurrentFocus=.* org\.esdeplus\.stub/', h.focused_window()), 'X normal game launch')
        h.key('KEYCODE_BACK')
        h.wait_for(lambda: re.search(r'mCurrentFocus=.* ' + re.escape(h.app) + '/', h.focused_window()), 'return from game')
        timing('search-screen-controller')
        # Magnifier starts a touch session with the actual system keyboard, irrespective of VirtualKeyboard.
        for name, width, height, density in [('phone', 1080, 2400, 420), ('tablet', 2560, 1600, 320)]:
            h.shell('am', 'force-stop', h.app)
            h.shell('wm', 'size', f'{width}x{height}')
            h.shell('wm', 'density', str(density))
            start(InputTouchOverlay=True, UIMode='full', ScreenRotate=0, SearchHistory=True,
                  VirtualKeyboard=False)
            magnifier()
            h.wait_for(lambda: 'Search screen opened:' in h.log(), 'magnifier search')
            h.wait_for(lambda: 'mInputShown=true' in h.shell('dumpsys', 'input_method') or
                       'isInputViewShown=true' in h.shell('dumpsys', 'input_method'), 'real IME visible')
            shot(prefix + name + '-zero')
            typed('fin')
            shot(prefix + name + '-fin-ime')
            tap(4, 1)
            shot(prefix + name + '-filter')
            attach()
            pad(6)
            shot(prefix + name + '-results-focused')
            pad(1)
            tap(0)  # Return to the touch IME before the direct result tap.
            tap(6)
            h.wait_for(lambda: 'Search show game: nes/Final' in h.log(), 'tap shows game list')
            magnifier()
            tap(5)
            h.wait_for(lambda: 'Search keystroke: query=fin ' in h.log(), 'recent search tap runs query')
            shot(prefix + name + '-recent')
            tap(6, hold=True)
            shot(prefix + name + '-long-press')
            h.key('KEYCODE_ENTER')  # Play now in the native dialog.
            h.wait_for(lambda: re.search(r'mCurrentFocus=.* org\.esdeplus\.stub/', h.focused_window()), 'long-press Play now normal launch')
            h.key('KEYCODE_BACK')
            magnifier()
            typed('qqqqqqqq')
            shot(prefix + name + '-no-results')
            h.key('KEYCODE_ESCAPE')
            magnifier()
            h.wait_for(lambda: 'mInputShown=true' in h.shell('dumpsys', 'input_method') or
                       'isInputViewShown=true' in h.shell('dumpsys', 'input_method'), 'IME ready for composition')
            ime('compose', 'が')
            ime('compose', 'がく')
            ime('commit', '学')
            h.wait_for(lambda: 'Search keystroke: query=学 ' in h.log(), 'Japanese composition replacement exactly once')
            ime('delete')
            h.key('KEYCODE_ESCAPE')
            # Switching from native prefill to an empty IME buffer still permits Backspace.
            h.key('KEYCODE_M')
            tap(0)
            before = len(h.log())
            ime('delete')
            h.wait_for(lambda: 'Search keystroke: query= results=' in h.log()[before:], 'IME deletes native prefill')
            h.key('KEYCODE_ESCAPE')
            timing('search-screen-touch-' + name)
        # A real privacy-mode launch must not expose or write the previous query history.
        for mode, remember in [('kid', True), ('full', False)]:
            start(InputTouchOverlay=False, UIMode=mode, SearchHistory=remember)
            before = h.shell('cat', root + '/settings/search_history.xml')
            h.key('KEYCODE_INSERT')
            current = h.log().rsplit('Search layout:', 1)[-1]
            assert not any(int(area) == 5 for area, _, _, _ in TARGET.findall(current)), 'Private history was shown'
            typed('fin', private=True)
            if mode == 'kid':
                assert re.search(r'Search keystroke: query=<private> results=1 query_bytes=3\b', h.log()), 'Kid search exposed non-kid game'
            assert 'query=fin ' not in h.log(), 'Private query leaked into search diagnostics'
            h.key('KEYCODE_ENTER')
            h.key('KEYCODE_ENTER')
            after = h.shell('cat', root + '/settings/search_history.xml')
            assert before == after, 'Private search mutated history'
            timing('search-screen-privacy-' + mode + '-' + str(remember))
        ordered = sorted(measurements)
        summary = dict(samples=len(ordered), p95_ms=ordered[math.ceil(len(ordered) * .95) - 1], max_ms=max(ordered))
        (h.evidence / 'search-screen-timing.json').write_text(json.dumps(summary, indent=2) + '\n')
        assert summary['max_ms'] <= 50, ('Search-attributable work exceeded 50ms', summary)
        (h.evidence / 'search-screen-result.txt').write_text(f'PASS: API {h.api} controller grid A/X/Y, suggestions, L/R, A show/cursor, recent X removal, X launch; phone/tablet IME, tap, long-press Play now, recent tap; kid/history-off privacy.\n')
    finally:
        h.shell('am', 'force-stop', h.app)
        h.shell('wm', 'size', 'reset')
        h.shell('wm', 'density', 'reset')
        prepare('restore')
