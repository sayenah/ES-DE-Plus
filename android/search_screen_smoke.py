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


class TimingBudgetExceeded(AssertionError):
    """Preserves the exact timing failure while independent overlay checks finish."""


def run(h, start, control, shot, record):
    root = h.settings.rsplit('/settings/', 1)[0]
    measurements = []
    timed_prefix = ''
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
        assert 'PASS: owned surface geometry recorded' in geometry, geometry
        view = json.loads(h.adb('exec-out', 'run-as', h.app, 'cat', 'cache/touch-surface-geometry.json'))
        return str(round(view['x'] + nx * view['bufferWidth'])), str(round(view['y'] + ny * view['bufferHeight']))
    def magnifier():
        before = h.log().count('Search entry ready:')
        current = h.log().rsplit('InputOverlay: layout ', 1)[-1]
        match = re.findall(r'InputOverlay: button id=102 .*? norm=([0-9.]+),([0-9.]+)', current)
        assert match, current
        h.shell('input', 'touchscreen', 'tap', *point(*map(float, match[-1])))
        h.wait_for(lambda: h.log().count('Search entry ready:') == before + 1,
                   'one complete search screen from magnifier')
    def visible(area, index=0):
        current = h.log().rsplit('Search layout:', 1)[-1]
        return [(float(x), float(y)) for a, i, x, y in TARGET.findall(current)
                if int(a) == area and int(i) == index]
    def target(area, index=0):
        found = visible(area, index)
        assert found, (area, index, h.log().rsplit('Search layout:', 1)[-1])
        return point(*found[-1])
    def swipe_shelf(index, delta):
        nx, ny = visible(6, index)[-1]
        before = len(h.log())
        h.shell('input', 'touchscreen', 'swipe', *point(nx, ny), *point(nx, ny + delta), '500')
        h.wait_for(lambda: 'InputOverlay: event type=up' in h.log()[before:], 'shelf swipe released')
        assert 'InputOverlay: owner=overlay' not in h.log()[before:], 'Overlay stole shelf scroll'
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
    def return_from_game():
        previous_pid = h.shell('pidof', h.app, check=False).strip()
        released = 'Android foreground input block released'
        previous_releases = h.log().count(released)
        h.key('KEYCODE_BACK')
        h.wait_for(lambda: re.search(r'mCurrentFocus=.* ' + re.escape(h.app) + '/', h.focused_window()),
                   'return from game to frontend focus')
        def native_ready():
            current = h.log()
            if h.shell('pidof', h.app, check=False).strip() == previous_pid:
                return current.count(released) > previous_releases
            return ('Application startup time:' in current and
                    current.rfind(released) >= current.rfind('Android foreground input block started'))
        h.wait_for(native_ready, 'native frontend ready for input after game return')
    def timing(name):
        nonlocal timed_prefix
        def rendered():
            current = h.log()
            last = current.rfind('Search keystroke:')
            return last >= 0 and 'Search frame:' in current[last:]
        h.wait_for(rendered, 'last search keystroke rendered before checkpoint')
        current = h.log()
        complete = current[:current.rfind('\n') + 1]
        added = complete[len(timed_prefix):] if complete.startswith(timed_prefix) else complete
        times = [float(value) for value in re.findall(r'Search frame: .*? work_ms=([0-9.]+)', added)]
        assert times, 'Missing actual search frame measurements'
        measurements.extend(times)
        timed_prefix = complete
        record(name)
    def scheduler_control():
        # A separate traced control, never replacement timing evidence. Retain it
        # even if a sporadic outlier does not recur in the ordinary journey.
        for name, width, height, density in [('phone', 1080, 2400, 420), ('tablet', 2560, 1600, 320)]:
            h.shell('am', 'force-stop', h.app)
            h.shell('wm', 'size', f'{width}x{height}')
            h.shell('wm', 'density', str(density))
            start(InputTouchOverlay=True, UIMode='full', ScreenRotate=0, SearchHistory=True,
                  VirtualKeyboard=False, InputDeviceNotifications=False)
            tracing = False
            try:
                h.shell('atrace', '--async_start', '-b', '32768', 'sched')
                tracing = True
                magnifier()
                h.wait_for(lambda: 'mInputShown=true' in h.shell('dumpsys', 'input_method') or
                           'isInputViewShown=true' in h.shell('dumpsys', 'input_method'),
                           'scheduler diagnostic IME visible')
                for _ in range(3):
                    typed('fin')
                    for _ in range(3):
                        ime('delete')
                h.wait_for(lambda: 'Search frame:' in h.log()[h.log().rfind('Search keystroke:'):],
                           'scheduler diagnostic last edit rendered')
                current = record('search-screen-scheduler-' + name)
                (h.evidence / ('search-screen-scheduler-' + name + '-threads.txt')).write_text(
                    h.shell('ps', '-A', '-T'))
                times = sorted(float(value) for value in re.findall(
                    r'Search frame: .*? work_ms=([0-9.]+)', current))
                assert times, 'Scheduler diagnostic produced no measured search frames'
                (h.evidence / ('search-screen-scheduler-' + name + '-summary.txt')).write_text(
                    json.dumps(dict(diagnostic_only=True, samples=len(times),
                                    p95_ms=times[math.ceil(len(times) * .95) - 1], max_ms=max(times)),
                               indent=2) + '\n')
            finally:
                if tracing:
                    trace = h.adb('shell', 'atrace', '--async_stop', '-z', binary=True)
                    (h.evidence / ('search-screen-scheduler-' + name + '.atrace')).write_bytes(trace)
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
        start(InputTouchOverlay=False, UIMode='full', CollectionSystemsAuto='favorites', SearchHistory=True,
              InputDeviceNotifications=False)
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
        timing('search-screen-controller')
        pad(2)
        h.wait_for(lambda: re.search(r'mCurrentFocus=.* org\.esdeplus\.stub/', h.focused_window()), 'X normal game launch')
        return_from_game()
        record('search-screen-controller-launch-return')
        # Magnifier starts a touch session with the actual system keyboard, irrespective of VirtualKeyboard.
        for name, width, height, density in [('phone', 1080, 2400, 420), ('tablet', 2560, 1600, 320)]:
            h.shell('am', 'force-stop', h.app)
            h.shell('wm', 'size', f'{width}x{height}')
            h.shell('wm', 'density', str(density))
            start(InputTouchOverlay=True, UIMode='full', ScreenRotate=0, SearchHistory=True,
                  VirtualKeyboard=False, InputDeviceNotifications=False)
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
            play = re.findall(r'GuiMsgBox: button=play now norm=([0-9.eE+-]+),([0-9.eE+-]+)',
                              h.log(), re.I)
            assert play, 'Native Play now button was not rendered'
            timing('search-screen-touch-' + name + '-before-play')
            before = len(h.log())
            h.shell('input', 'touchscreen', 'tap', *point(*map(float, play[-1])))
            h.wait_for(lambda: 'guimsgbox: direct touch confirmed play now' in h.log()[before:].lower(),
                       'direct touch confirms Play now')
            assert 'InputOverlay: owner=overlay' not in h.log()[before:], 'Overlay stole modal Play now'
            h.wait_for(lambda: re.search(r'mCurrentFocus=.* org\.esdeplus\.stub/', h.focused_window()), 'long-press Play now normal launch')
            return_from_game()
            magnifier()
            typed('qqqqqqqq')
            shot(prefix + name + '-no-results')
            tap(7)  # Close stays reachable above the system IME.
            magnifier()
            h.wait_for(lambda: 'mInputShown=true' in h.shell('dumpsys', 'input_method') or
                       'isInputViewShown=true' in h.shell('dumpsys', 'input_method'), 'IME ready for composition')
            ime('compose', 'が')
            ime('compose', 'がく')
            ime('commit', '学')
            h.wait_for(lambda: 'Search keystroke: query=学 ' in h.log(), 'Japanese composition replacement exactly once')
            ime('delete')
            tap(7)
            # Switching from native prefill to an empty IME buffer still permits Backspace.
            h.key('KEYCODE_M')
            tap(0)
            before = len(h.log())
            ime('delete')
            h.wait_for(lambda: 'Search keystroke: query= results=' in h.log()[before:], 'IME deletes native prefill')
            timing('search-screen-touch-' + name)
            tap(7)
            if name == 'tablet':
                # Keep the original cold typing journey above unchanged. With the
                # landscape IME open, vertical swipes must expose the lower shelf.
                magnifier()
                h.wait_for(lambda: 'mInputShown=true' in h.shell('dumpsys', 'input_method') or
                           'isInputViewShown=true' in h.shell('dumpsys', 'input_method'), 'IME ready for shelf scroll')
                h.wait_for(lambda: visible(6, 0) and not visible(6, 2),
                           'constrained zero state applied above IME')
                swipe_shelf(0, -.16)
                h.wait_for(lambda: visible(6, 2), 'favorite shelf scrolls above IME')
                shot(prefix + name + '-zero-favorites-scrolled')
                swipe_shelf(2, .16)
                h.wait_for(lambda: visible(6, 0) and not visible(5), 'scroll back to recent shelf')
                swipe_shelf(0, .16)
                h.wait_for(lambda: visible(5), 'scroll back to recent searches')
                shot(prefix + name + '-zero-history-restored')
                tap(0)
                typed('fin')
                timing('search-screen-touch-' + name + '-zero-scroll')
                tap(7)
        # A real privacy-mode launch must not expose or write the previous query history.
        for mode, remember in [('kid', True), ('full', False)]:
            start(InputTouchOverlay=False, UIMode=mode, SearchHistory=remember,
                  expected_games=1 if mode == 'kid' else 2)
            before = h.shell('cat', root + '/settings/search_history.xml')
            h.key('KEYCODE_INSERT')
            current = h.log().rsplit('Search layout:', 1)[-1]
            assert not any(int(area) == 5 for area, _, _, _ in TARGET.findall(current)), 'Private history was shown'
            typed('fin', private=True)
            if mode == 'kid':
                assert re.search(r'Search keystroke: query=<private> results=1 query_bytes=3\b', h.log()), 'Kid search exposed non-kid game'
            assert 'query=fin ' not in h.log(), 'Private query leaked into search diagnostics'
            timing('search-screen-privacy-' + mode + '-' + str(remember))
            h.key('KEYCODE_ENTER')
            h.key('KEYCODE_ENTER')
            after = h.shell('cat', root + '/settings/search_history.xml')
            assert before == after, 'Private search mutated history'
            record('search-screen-privacy-after-show-' + mode + '-' + str(remember))
        ordered = sorted(measurements)
        summary = dict(samples=len(ordered), p95_ms=ordered[math.ceil(len(ordered) * .95) - 1], max_ms=max(ordered))
        (h.evidence / 'search-screen-timing.json').write_text(json.dumps(summary, indent=2) + '\n')
        try:
            scheduler_control()
        except Exception as error:
            # A diagnostic failure cannot erase or turn the original budget
            # failure into a passing result.
            (h.evidence / 'search-screen-scheduler-error.txt').write_text(repr(error) + '\n')
        try:
            assert summary['max_ms'] <= 50, ('Search-attributable work exceeded 50ms', summary)
        except AssertionError as error:
            raise TimingBudgetExceeded(*error.args) from error
        (h.evidence / 'search-screen-result.txt').write_text(f'PASS: API {h.api} controller grid A/X/Y, suggestions, L/R, A show/cursor, recent X removal, X launch; phone/tablet IME, tap, long-press Play now, recent tap; kid/history-off privacy.\n')
    finally:
        h.shell('am', 'force-stop', h.app)
        h.shell('wm', 'size', 'reset')
        h.shell('wm', 'density', 'reset')
        prepare('restore')
