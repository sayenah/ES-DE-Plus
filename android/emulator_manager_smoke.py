#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Drives the actual native GUI, including minified builds.
import hashlib
import json
import re
import xml.etree.ElementTree as ET


def run(mode, harness, minified=False):
    h = type('Harness', (), harness)
    if h.api == 29:
        h.shell('pm', 'grant', 'org.esdeplus.stub', 'android.permission.READ_EXTERNAL_STORAGE')
    elif mode.startswith('direct'):
        h.shell('am', 'start', '-n', 'org.esdeplus.stub/.RecipientActivity', '--es', 'queryMode', 'storage-permission')
        h.grant_from_settings('ES-DE Plus recipient', recipient=True)
    original_settings = h.shell('cat', h.settings)
    # The no-games fixture uses the documented effective custom configuration,
    # including loadExclusive. No bundled resource or production fixture branch.
    systems = ('<!-- retained user comment --><loadExclusive/><systemList custom="keep">'
               '<system><name>ps3</name><fullname>Manager fixture</fullname><path>%ROMPATH%/ps3</path>'
               '<extension>.ps3</extension><command label="Original">%EMULATOR_FIXTURE% '
               '%ACTION%=android.intent.action.VIEW %CATEGORY%=android.intent.category.DEFAULT '
               '%MIMETYPE%=application/zip %EXTRA_ROM%=%ROM% %EXTRAINTEGER_slot%=2 '
               '%EXTRABOOL_boot%=true %ACTIVITY_CLEAR_TOP%</command>'
               '<unknown attribute="keep">user data</unknown><platform>ps3</platform><theme>ps3</theme>'
               '</system></systemList>')
    rules = ('<ruleList><!-- user rule --><emulator name="FIXTURE"><rule type="androidpackage">'
             '<entry>org.esdeplus.stub/.TelevisionOnly</entry></rule></emulator></ruleList>')
    def fixture(action):
        h.shell('am', 'force-stop', h.app)
        result = h.shell('am', 'instrument', '-w', '-e', 'mode', 'emulator-manager-' + action,
                         h.app + '/org.esdeplus.frontend.RuntimeSmoke')
        h.smoke_checks.probe_passed(result, 'PASS: emulator-manager fixture at selected roots; no extraction')
        return json.loads(re.search(r'EMULATOR_MANAGER_JSON=(.*)', result)[1])
    fixture_data = fixture('prepare')
    data_root = fixture_data['dataRoot']
    original = {}
    for name in ['es_systems.xml', 'es_find_rules.xml']:
        path = data_root + '/custom_systems/' + name
        original[name] = h.shell('cat', path, check=False) if h.shell('test', '-f', path, check=False) == '' and h.shell('ls', path, check=False).strip() == path else None
    def read(relative):
        return h.shell('cat', data_root + '/' + relative, check=False)
    def receipt_ready(predicate):
        try:
            return predicate(json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json', check=False)))
        except (json.JSONDecodeError, KeyError, TypeError):
            return False
    def discard_receipt():
        # Compare identical cold recipient states. Android can add
        # FLAG_ACTIVITY_BROUGHT_TO_FRONT when reusing an existing recipient task;
        # retain exact flag equality rather than masking any delivered flags.
        h.shell('am', 'force-stop', 'org.esdeplus.stub')
        h.shell('run-as', 'org.esdeplus.stub', 'rm', '-f', 'files/observation.json')
    def fragment(value):
        return ET.fromstring('<document>' + re.sub(r'<\?xml[^>]*\?>', '', value) + '</document>')
    def current():
        return (read('custom_systems/es_systems.xml'), read('custom_systems/es_find_rules.xml'),
                read('gamelists/ps3/gamelist.xml'))
    def controls(expected, actual, label):
        h.launch_checks.equal(actual, expected, label)
    def page(name):
        marker = 'Emulator manager page: ' + name + ';'
        h.wait_for(lambda: marker in h.adb('logcat', '-d'), 'manager page ' + name, timeout=30)
    def pick(index):
        h.key('KEYCODE_MOVE_HOME')
        for _ in range(index): h.key('KEYCODE_DPAD_DOWN')
        h.adb('logcat', '-c')
        h.key('KEYCODE_ENTER')
    def text(value, erase=0):
        if erase:
            h.key('KEYCODE_MOVE_END')
            for _ in range(erase): h.key('KEYCODE_DEL')
        if value: h.shell('input', 'text', value.replace(' ', '%s'))
        h.key('KEYCODE_ENTER')
    def start_native(count, description):
        h.shell('am', 'force-stop', h.app)
        baseline = h.log()
        h.adb('logcat', '-c')
        h.start_entry()
        def fresh_start():
            log = h.log()
            return (log != baseline and 'Application startup time:' in log and
                    re.search(r'Total game count: ' + str(count) + r'\s', log) is not None)
        h.wait_for(fresh_start, description)
        h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), h.app),
                   'fresh frontend window focused')
        h.wait_for(lambda: any(n.get('package') == h.app for n in h.hierarchy()),
                   'fresh frontend native window')
    def start():
        start_native(0, 'fresh no-recognised-games fixture startup')
        if any(n.get('text') == 'Got it' for n in h.hierarchy()): h.ui('Got it')
        h.screenshot('emulator-manager-' + mode + '-no-games')
        if h.api != 36:
            tap('EMULATORS')
        else:
            h.key('KEYCODE_DPAD_RIGHT'); h.key('KEYCODE_ENTER')
        page('systems')
        pick(1); page('system')
        pick(0); page('draft')
    def tap(prefix):
        pattern = r'Emulator manager touch target: (' + re.escape(prefix) + r'[^\t\r\n]*)\tx:([0-9.]+)\ty:([0-9.]+)'
        h.wait_for(lambda: re.search(pattern, h.adb('logcat', '-d')) is not None, 'visible touch target ' + prefix, timeout=30)
        match = list(re.finditer(pattern, h.adb('logcat', '-d')))[-1]
        # Targets are renderer coordinates. adb taps use display coordinates;
        # derive the actual surface origin/scale instead of assuming no system bars.
        nodes = h.hierarchy()
        surfaces = [n for n in nodes if n.get('class', '').endswith(('SurfaceView', 'SDLSurface'))]
        if not surfaces:
            surfaces = [n for n in nodes if n.get('resource-id') == 'android:id/content']
        controls(1, len(surfaces), 'one visible SDL content surface')
        left, top, right, bottom = map(int, re.findall(r'\d+', surfaces[0].get('bounds')))
        width, height = map(int, re.findall(r'Application resolution: (\d+)x(\d+)', h.log())[-1])
        display_x = left + float(match[2]) * (right - left) / width
        display_y = top + float(match[3]) * (bottom - top) / height
        h.adb('logcat', '-c')
        h.shell('input', 'tap', str(round(display_x)), str(round(display_y)))
        h.time.sleep(0.5)
    def manager():
        h.key('KEYCODE_ESCAPE')
        for _ in range(6): h.key('KEYCODE_DPAD_DOWN')
        h.key('KEYCODE_ENTER'); h.key('KEYCODE_ENTER'); h.key('KEYCODE_ENTER'); page('systems')
        pick(1); page('system')
    def restart_games():
        start_native(2, 'fresh startup manager configuration')
    def cancel_notice():
        if h.api != 36: tap('CANCEL')
        else: h.key('KEYCODE_DPAD_RIGHT'); h.key('KEYCODE_ENTER')

    release_installed = False
    try:
        parsed = h.launch_checks.settings_fragment(original_settings)
        debug = parsed.find("bool[@name='DebugMode']")
        if debug is None: debug = ET.SubElement(parsed, 'bool', name='DebugMode')
        debug.set('value', 'true')
        h.user_file('settings/es_settings.xml', '\n'.join(ET.tostring(e, encoding='unicode') for e in parsed))
        h.user_file('custom_systems/es_systems.xml', systems)
        h.user_file('custom_systems/es_find_rules.xml', rules)
        if minified:
            h.adb('install', '-r', 'android/app/build/outputs/apk/release/app-release-smoke.apk')
            release_installed = True
        start()
        before = current()
        if h.api != 36:
            # Tap a field, type one character on the real virtual keyboard, cancel
            # the edit and then cancel the complete draft. Neither file is written.
            tap('EMULATOR LABEL:')
            tap('x')
            h.screenshot('emulator-manager-' + mode + '-touch-keyboard')
            tap('CANCEL')
            tap('BACK')
            tap('CONTINUE')
            page('system')
            controls(before, current(), 'touch cancellation preserves configuration')
            tap('ADD EMULATOR')
            page('draft')
        pick(0); text('EMUPLUS TEST'); page('draft')
        # Cancel asynchronous discovery through the ordinary keyboard back mapping.
        cancel_started = h.time.monotonic()
        pick(1); page('apps'); h.key('KEYCODE_DEL'); page('draft')
        controls(True, h.time.monotonic() - cancel_started < 10, 'discovery cancellation stays responsive')
        controls(before, current(), 'discovery cancellation preserves configuration')
        pick(1); page('apps')
        # Search is UI input, preserving the actual component even with equal labels.
        pick(0); text('.RecipientActivity')
        h.wait_for(lambda: 'Emulator manager discovery complete:' in h.adb('logcat', '-d'), 'discovery completion', timeout=30)
        # Wait for the asynchronous completion before selecting its first result.
        h.wait_for(lambda: h.adb('logcat', '-d').count('Emulator manager page: apps;') >= 1, 'app picker rebuilt')
        pick(1); h.screenshot('emulator-manager-' + mode + '-receiving-component'); h.key('KEYCODE_ENTER'); page('draft')
        pick(3); page('profiles'); pick(0)
        # Decline the source TelevisionOnly receiver; keep the manually chosen activity.
        if h.api != 36: tap('CANCEL')
        else: h.key('KEYCODE_DPAD_RIGHT'); h.key('KEYCODE_ENTER')
        page('draft')
        pick(4); text('.zip .ZIP'); page('draft')
        pick(15); page('files'); pick(0); text(fixture_data['file']); page('draft')
        # Configure a supported typed extra in the GUI and exercise its validation.
        pick(11); page('extras'); pick(2); page('extra')
        pick(2); text('2147483648', erase=1); page('extra')
        h.key('KEYCODE_DEL'); page('extras'); h.key('KEYCODE_DEL'); page('draft')
        pick(16)
        h.wait_for(lambda: 'Integer extras must fit a signed 32-bit integer' in h.adb('logcat', '-d'), 'typed integer validation error')
        controls(before, current(), 'invalid typed extra test isolation')
        h.screenshot('emulator-manager-' + mode + '-typed-extra-error'); h.key('KEYCODE_ENTER')
        pick(11); page('extras'); pick(2); page('extra')
        pick(2); text('3', erase=10); page('extra')
        h.key('KEYCODE_DEL'); page('extras'); h.key('KEYCODE_DEL'); page('draft')
        pick(13); page('draft'); pick(13); page('draft')
        h.screenshot('emulator-manager-' + mode + '-draft')
        # Exact candidate test, independent of the original/default profile.
        discard_receipt()
        pick(16)
        h.wait_for(lambda: 'Emulator manager test: accepted;' in h.adb('logcat', '-d'), 'unsaved candidate accepted')
        h.wait_for(lambda: receipt_ready(lambda r: r.get('extras', {}).get('ROM', {}).get('value') == fixture_data['file']), 'candidate recipient observed file')
        observation = json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
        controls('org.esdeplus.stub/org.esdeplus.stub.RecipientActivity', observation['component'], 'selected candidate component')
        if h.api == 29 or mode.startswith('direct'):
            controls(fixture_data['sha256'], observation.get('sha256'), 'exact ZIP bytes via path')
        else:
            controls(True, bool(observation.get('readError')), 'recipient reports scoped raw-path access refusal')
        controls('java.lang.Integer', observation['extras']['slot']['type'], 'typed integer')
        controls('3', str(observation['extras']['slot']['value']), 'GUI-edited typed integer value')
        controls('java.lang.Boolean', observation['extras']['boot']['type'], 'typed boolean')
        controls(before, current(), 'test leaves files/default/statistics unchanged')
        h.evidence.joinpath('emulator-manager-' + mode + '-test-recipient.json.txt').write_text(json.dumps(observation, indent=2))
        h.key('KEYCODE_BACK')
        h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), h.app), 'test return keeps editable draft')
        h.screenshot('emulator-manager-' + mode + '-test-return')
        h.key('KEYCODE_ENTER')  # Close the accepted-request notice.
        pick(5); page('draft')  # path -> document URI, same named ROM extra
        pick(5)  # provider is invalid in a named extra; the error is modal
        h.wait_for(lambda: 'The ROM provider can only be used as Intent data' in h.adb('logcat', '-d'), 'invalid transport selection gives actionable error')
        controls(before, current(), 'invalid transport selection preserves files/defaults')
        h.screenshot('emulator-manager-' + mode + '-transport-selection-error')
        h.key('KEYCODE_ENTER'); page('draft')
        controls(True, 'ROM TRANSPORT: DOCUMENT URI' in h.adb('logcat', '-d'), 'rejected transport keeps displayed document URI choice')
        # Test refusal must also preserve the candidate. App-private SAF is refused.
        if mode.startswith('scoped'):
            pick(16)
            h.wait_for(lambda: 'Emulator manager test: refused;' in h.adb('logcat', '-d'), 'app-private SAF refusal')
            controls(before, current(), 'refused test isolation')
            h.screenshot('emulator-manager-' + mode + '-refused-saf')
            h.key('KEYCODE_ENTER')
            # Switch to provider and Intent data explicitly; no transport substitution.
            pick(6); text('', erase=3); page('draft')
            pick(5); page('draft')  # document URI -> provider
        else:
            pick(6); text('', erase=3); page('draft')
            pick(5); page('draft')  # document URI -> provider, now in Intent data
        if minified:
            h.adb('uninstall', 'org.esdeplus.stub')
            pick(16)
            h.wait_for(lambda: 'The receiving activity is unavailable' in h.adb('logcat', '-d'), 'removed package gives actionable error')
            controls(before, current(), 'package-removal refusal preserves draft files')
            h.screenshot('emulator-manager-' + mode + '-package-removed')
            h.key('KEYCODE_ENTER')
            h.adb('install', '-r', 'android/stub-emulator/build/outputs/apk/debug/stub-emulator-debug.apk')
        discard_receipt()
        pick(16)
        h.wait_for(lambda: 'Emulator manager test: accepted;' in h.adb('logcat', '-d'), 'unsaved provider candidate')
        h.wait_for(lambda: receipt_ready(lambda r: r.get('data', '').startswith('content://' + h.app + '.roms/')), 'provider recipient observation')
        provider = json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
        controls(fixture_data['sha256'], provider.get('sha256'), 'provider exact ZIP bytes')
        controls(True, provider['data'].startswith('content://' + h.app + '.roms/'), 'provider chosen explicitly')
        controls(before, current(), 'provider test isolation')
        h.key('KEYCODE_BACK')
        h.wait_for(lambda: h.smoke_checks.package_window_focused(h.focused_window(), h.app), 'provider test return')
        h.screenshot('emulator-manager-' + mode + '-provider-test-return')
        h.key('KEYCODE_ENTER')
        pick(17)
        h.wait_for(lambda: 'Emulator manager saved: ps3; label: EMUPLUS TEST' in h.adb('logcat', '-d'), 'manager saved')
        h.wait_for(lambda: 'Total game count: 2' in h.log(), 'both case extensions visible immediately')
        saved = current()
        root = fragment(saved[0])
        controls(True, root.find('loadExclusive') is not None, 'loadExclusive preserved')
        system = root.find('systemList/system')
        controls('keep', root.find('systemList').get('custom'), 'unknown attribute preserved')
        controls('user data', system.find('unknown').text, 'unknown element preserved')
        controls(True, 'retained user comment' in saved[0], 'comment preserved')
        commands = system.findall('command')
        controls(['Original', 'EMUPLUS TEST'], [e.get('label') for e in commands], 'labels preserved')
        rule_id = re.search(r'%EMULATOR_([^%]+)%', commands[-1].text)[1]
        controls(True, ET.fromstring(saved[1]).find("emulator[@name='" + rule_id + "']") is not None, 'new rule read back')
        # Re-enter through the ordinary menu, set default and launch through normal search.
        manager()
        if h.api != 36:
            tap('SET SYSTEM DEFAULT'); page('defaults'); tap('EMUPLUS TEST'); page('system')
        else:
            pick(1); page('defaults'); pick(1); page('system')
        h.wait_for(lambda: 'Emulator manager default saved: ps3; label: EMUPLUS TEST' in h.adb('logcat', '-d'), 'ordinary default persisted')
        controls('EMUPLUS TEST', fragment(current()[2]).find('alternativeEmulator/label').text, 'gamelist default')
        # Close manager/system-list, alternative-emulator, Other settings and main
        # dialogs through their normal callbacks, then exercise the fresh find rules
        # before restarting the native frontend.
        h.key('KEYCODE_DEL'); page('systems')
        for _ in range(4): h.key('KEYCODE_DEL')
        discard_receipt()
        h.search_launch('Manager', 'emulator-manager-' + mode + '-immediate')
        h.wait_for(lambda: 'Activity launch accepted:' in h.adb('logcat', '-d'), 'new saved command resolves before restart')
        h.wait_for(lambda: receipt_ready(lambda r: r.get('data', '').startswith('content://' + h.app + '.roms/')), 'fresh immediate-launch recipient observation')
        immediate = json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
        for field in ['component', 'action', 'mime', 'data', 'flags', 'categories', 'extras']:
            controls(provider[field], immediate[field], 'test/immediate Intent ' + field)
        controls(fixture_data['sha256'], immediate.get('sha256'), 'immediate provider exact ZIP bytes')
        h.evidence.joinpath('emulator-manager-' + mode + '-immediate-recipient.json.txt').write_text(json.dumps(immediate, indent=2))
        h.screenshot('emulator-manager-' + mode + '-immediate-recipient')
        # Closing and a fresh start prove the unchanged upstream readers consume the files.
        restart_games()
        discard_receipt()
        h.search_launch('Manager', 'emulator-manager-' + mode + '-saved')
        h.wait_for(lambda: 'Activity launch accepted:' in h.adb('logcat', '-d'), 'saved command resolves immediately')
        h.wait_for(lambda: receipt_ready(lambda r: r.get('data', '').startswith('content://' + h.app + '.roms/')), 'fresh saved-launch recipient observation')
        receipt = json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
        for field in ['component', 'action', 'mime', 'data', 'flags', 'categories', 'extras']:
            controls(provider[field], receipt[field], 'test/saved Intent ' + field)
        controls(fixture_data['sha256'], receipt.get('sha256'), 'saved provider exact ZIP bytes')
        h.screenshot('emulator-manager-' + mode + '-saved-recipient')
        if not minified:
            # Standard gamelist fixtures exercise the unchanged per-game reader.
            # Keep unrelated choices and ordinary play metadata across the apply cycles.
            selections = fragment(current()[2])
            games = selections.find('gameList')
            if games is None: games = ET.SubElement(selections, 'gameList')
            for filename, label in [('ESDEPlus Manager Test.zip', 'EMUPLUS TEST'),
                                    ('ESDEPlus Upper Test.ZIP', 'Original')]:
                game = next((g for g in games.findall('game') if g.findtext('path') == './' + filename), None)
                if game is None:
                    game = ET.SubElement(games, 'game'); ET.SubElement(game, 'path').text = './' + filename
                choice = game.find('altemulator')
                if choice is None: choice = ET.SubElement(game, 'altemulator')
                choice.text = label
                count = game.find('playcount')
                if count is None: count = ET.SubElement(game, 'playcount')
                count.text = '7'
            h.user_file('gamelists/ps3/gamelist.xml', '\n'.join(ET.tostring(e, encoding='unicode') for e in selections))
            restart_games()
            discard_receipt()
            h.search_launch('Upper', 'emulator-manager-' + mode + '-per-game')
            h.wait_for(lambda: receipt_ready(lambda r: r.get('extras', {}).get('ROM', {}).get('value') == fixture_data['upper']), 'per-game recipient')
            per_game = json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
            controls('org.esdeplus.stub/org.esdeplus.stub.TelevisionOnly', per_game['component'], 'per-game overrides system default')
            h.evidence.joinpath('emulator-manager-' + mode + '-per-game.json.txt').write_text(json.dumps(per_game, indent=2))
            # A real filesystem obstacle exercises ordinary gamelist save failure.
            # Restore the original data before any following configuration operation.
            overrides_before = current()[:2]
            fixture('default-block')
            restart_games(); manager(); pick(1); page('defaults'); pick(1)
            h.wait_for(lambda: 'Could not save the default emulator to gamelist.xml' in h.adb('logcat', '-d'), 'actionable default persistence failure')
            controls(overrides_before, current()[:2], 'default failure leaves emulator definitions unchanged')
            h.screenshot('emulator-manager-' + mode + '-default-save-failure')
            fixture('default-unblock')
            restart_games(); manager()
            before_removal = current()
            pick(3); cancel_notice()
            controls(before_removal, current(), 'cancelled removal preserves selections and definitions')
            pick(3); h.key('KEYCODE_ENTER')
            # Removal requires explicit repair of the selected manager entry.
            h.screenshot('emulator-manager-' + mode + '-repair-consent')
            cancel_notice()
            controls(before_removal, current(), 'declined repair preserves selections and definitions')
            pick(3); h.key('KEYCODE_ENTER'); h.key('KEYCODE_ENTER')
            h.wait_for(lambda: 'Emulator manager applied: ps3' in h.adb('logcat', '-d'), 'remove reapplies with accepted extensions')
            repaired = fragment(current()[2])
            controls('', repaired.findtext('alternativeEmulator/label') or '', 'affected system selection repaired')
            choices = {g.findtext('path'): g.findtext('altemulator') or '' for g in repaired.find('gameList').findall('game')}
            controls('', choices['./ESDEPlus Manager Test.zip'], 'affected per-game selection repaired')
            controls('Original', choices['./ESDEPlus Upper Test.ZIP'], 'unrelated per-game selection preserved')
            controls(1, len(fragment(current()[0]).find('systemList/system').findall('command')), 'only manager command removed')
            manager()
            before_reset = current()
            pick(3); h.screenshot('emulator-manager-' + mode + '-whole-override-reset-consent'); cancel_notice()
            controls(before_reset, current(), 'reset needs explicit confirmation')
            pick(3); h.key('KEYCODE_ENTER')
            # The remaining per-game Original choice also needs explicit repair.
            h.key('KEYCODE_ENTER')
            h.wait_for(lambda: 'Emulator manager applied: ps3' in h.adb('logcat', '-d') and 'Total game count: 0' in h.log(), 'reset reapplies bundled file types immediately')
            reset = fragment(current()[0])
            controls(True, reset.find('loadExclusive') is not None, 'exclusive directive survives reset')
            controls('Sony PlayStation 3', reset.findtext('systemList/system/fullname'), 'bundled snapshot retained under exclusive reset')
            controls(False, '.zip' in reset.findtext('systemList/system/extension').split(), 'reset restores bundled extensions')
            repaired_after_reset = fragment(current()[2])
            controls(True, all(not g.findtext('altemulator') for g in repaired_after_reset.find('gameList').findall('game')), 'reset repairs remaining invalid selections')
            h.screenshot('emulator-manager-' + mode + '-reset-applied')
            h.evidence.joinpath('emulator-manager-' + mode + '-selection-reset-summary.txt').write_text(
                'PASS: per-game override beats system default; real gamelist save failure reported without changing definitions; cancelled removal and declined repair preserve files; explicit repair clears affected system/game choices and keeps unrelated choice; removal reapplies with accepted types; whole-override reset requires confirmation, repairs remaining choices and immediately restores bundled types under loadExclusive.\n')
        h.save_logs('emulator-manager-' + mode)
        h.evidence.joinpath('emulator-manager-' + mode + '-summary.txt').write_text(
            'PASS: native no-games link, effective/loadExclusive system, installed component via UI search, copied structured profile, .zip/.ZIP and matching draft file, exact archive bytes, accepted/refused unsaved test isolation, provider data transport, immediate rescan/rule resolution, default gamelist persistence, fresh upstream readback and equal test/saved Intent. Screenshots capture the real GUI; APK never uploaded.\n')
    except Exception:
        h.screenshot('emulator-manager-' + mode + '-failure-before-cleanup')
        h.save_logs('emulator-manager-' + mode + '-failure-before-cleanup')
        h.evidence.joinpath('emulator-manager-' + mode + '-failure-hierarchy.xml.txt').write_text(
            '\n'.join(ET.tostring(n, encoding='unicode') for n in h.hierarchy()))
        raise
    finally:
        h.shell('am', 'force-stop', h.app)
        if release_installed: h.adb('install', '-r', str(h.apk))
        fixture('cleanup')
        for name, content in original.items(): h.user_file('custom_systems/' + name, content)
        h.user_file('settings/es_settings.xml', original_settings)
    # Match the PDF/launch-probe helper contract: the inherited warm-alias
    # assertions require a live HOME task, not a drawer task. Restore that
    # precondition after fixture cleanup without retrying any failed operation.
    h.wait_for(lambda: not h.shell('pidof', h.app, check=False).strip(),
               'manager frontend stopped before restoring HOME')
    h.adb('logcat', '-c')
    h.start_entry('HomeEntry', 'android.intent.category.HOME')
    h.configured_system('emulator-manager-' + mode + '-restored-home')
    controls(True, 'HOME=true' in h.adb('logcat', '-d'), 'HOME precondition after manager smoke')
