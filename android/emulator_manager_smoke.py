#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Drives the actual native GUI, including minified builds.
import hashlib
import json
import re
import xml.etree.ElementTree as ET


def run(mode, harness, minified=False):
    h = type('Harness', (), harness)
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
    def start():
        h.shell('am', 'force-stop', h.app)
        h.adb('logcat', '-c')
        h.start_entry()
        h.wait_for(lambda: 'Total game count: 0' in h.log(), 'no recognised games from fixture')
        h.wait_for(lambda: bool(h.hierarchy()), 'no-games native window')
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
        h.adb('logcat', '-c')
        h.shell('input', 'tap', str(round(float(match[2]))), str(round(float(match[3]))))
        h.time.sleep(0.5)

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
        pick(1); page('apps')
        # Search is UI input, preserving the actual component even with equal labels.
        pick(0); text('.RecipientActivity')
        h.wait_for(lambda: 'Emulator manager discovery complete:' in h.adb('logcat', '-d'), 'discovery completion', timeout=30)
        # Wait for the asynchronous completion before selecting its first result.
        h.wait_for(lambda: h.adb('logcat', '-d').count('Emulator manager page: apps;') >= 1, 'app picker rebuilt')
        pick(1); page('draft')
        pick(3); page('profiles'); pick(0)
        # Decline the source TelevisionOnly receiver; keep the manually chosen activity.
        if h.api != 36: tap('CANCEL')
        else: h.key('KEYCODE_DPAD_RIGHT'); h.key('KEYCODE_ENTER')
        page('draft')
        pick(4); text('.zip .ZIP'); page('draft')
        pick(15); page('files'); pick(0); text(fixture_data['file']); page('draft')
        h.screenshot('emulator-manager-' + mode + '-draft')
        # Exact candidate test, independent of the original/default profile.
        pick(16)
        h.wait_for(lambda: 'Emulator manager test: accepted;' in h.adb('logcat', '-d'), 'unsaved candidate accepted')
        h.wait_for(lambda: fixture_data['file'] in h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json', check=False), 'candidate recipient observed file')
        observation = json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
        controls('org.esdeplus.stub/org.esdeplus.stub.RecipientActivity', observation['component'], 'selected candidate component')
        if h.api == 29 or mode.startswith('direct'):
            controls(fixture_data['sha256'], observation.get('sha256'), 'exact ZIP bytes via path')
        else:
            controls(True, bool(observation.get('readError')), 'recipient reports scoped raw-path access refusal')
        controls('java.lang.Integer', observation['extras']['slot']['type'], 'typed integer')
        controls('java.lang.Boolean', observation['extras']['boot']['type'], 'typed boolean')
        controls(before, current(), 'test leaves files/default/statistics unchanged')
        h.evidence.joinpath('emulator-manager-' + mode + '-test-recipient.json.txt').write_text(json.dumps(observation, indent=2))
        h.key('KEYCODE_BACK')
        h.wait_for(lambda: h.app in h.focused_window(), 'test return keeps editable draft')
        h.screenshot('emulator-manager-' + mode + '-test-return')
        h.key('KEYCODE_ENTER')  # Close the accepted-request notice.
        # Test refusal must also preserve the candidate. App-private SAF is refused.
        if mode.startswith('scoped'):
            pick(5); page('draft')  # path -> document URI, same named ROM extra
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
            pick(5); page('draft'); pick(5); page('draft')
        if minified:
            h.adb('uninstall', 'org.esdeplus.stub')
            pick(16)
            h.wait_for(lambda: 'The receiving activity is unavailable' in h.adb('logcat', '-d'), 'removed package gives actionable error')
            controls(before, current(), 'package-removal refusal preserves draft files')
            h.screenshot('emulator-manager-' + mode + '-package-removed')
            h.key('KEYCODE_ENTER')
            h.adb('install', '-r', 'android/stub-emulator/build/outputs/apk/debug/stub-emulator-debug.apk')
        pick(16)
        h.wait_for(lambda: 'Emulator manager test: accepted;' in h.adb('logcat', '-d'), 'unsaved provider candidate')
        h.wait_for(lambda: 'content://' + h.app + '.roms/' in h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json', check=False), 'provider recipient observation')
        provider = json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
        controls(fixture_data['sha256'], provider.get('sha256'), 'provider exact ZIP bytes')
        controls(True, provider['data'].startswith('content://' + h.app + '.roms/'), 'provider chosen explicitly')
        controls(before, current(), 'provider test isolation')
        h.key('KEYCODE_BACK'); h.wait_for(lambda: h.app in h.focused_window(), 'provider test return'); h.key('KEYCODE_ENTER')
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
        h.key('KEYCODE_ESCAPE')
        # Main menu: SEARCH, SCRAPER, UI, SOUND, INPUT, GAME COLLECTION, OTHER.
        for _ in range(6): h.key('KEYCODE_DPAD_DOWN')
        h.key('KEYCODE_ENTER'); h.key('KEYCODE_ENTER'); h.key('KEYCODE_ENTER'); page('systems')
        pick(1); page('system')
        if h.api != 36:
            tap('SET SYSTEM DEFAULT'); page('defaults'); tap('EMUPLUS TEST'); page('system')
        else:
            pick(1); page('defaults'); pick(1); page('system')
        h.wait_for(lambda: 'Emulator manager default saved: ps3; label: EMUPLUS TEST' in h.adb('logcat', '-d'), 'ordinary default persisted')
        controls('EMUPLUS TEST', fragment(current()[2]).find('alternativeEmulator/label').text, 'gamelist default')
        # Closing and a fresh start prove the unchanged upstream readers consume the files.
        h.shell('am', 'force-stop', h.app); h.adb('logcat', '-c'); h.start_entry()
        h.wait_for(lambda: 'Total game count: 2' in h.log(), 'fresh startup manager configuration')
        h.wait_for(lambda: bool(h.hierarchy()), 'fresh startup native window')
        h.search_launch('Manager', 'emulator-manager-' + mode + '-saved')
        h.wait_for(lambda: 'Activity launch accepted:' in h.adb('logcat', '-d'), 'saved command resolves immediately')
        receipt = json.loads(h.shell('run-as', 'org.esdeplus.stub', 'cat', 'files/observation.json'))
        for field in ['component', 'action', 'mime', 'data', 'flags', 'categories']:
            controls(provider[field], receipt[field], 'test/saved Intent ' + field)
        controls(fixture_data['sha256'], receipt.get('sha256'), 'saved provider exact ZIP bytes')
        h.screenshot('emulator-manager-' + mode + '-saved-recipient')
        h.save_logs('emulator-manager-' + mode)
        h.evidence.joinpath('emulator-manager-' + mode + '-summary.txt').write_text(
            'PASS: native no-games link, effective/loadExclusive system, installed component via UI search, copied structured profile, .zip/.ZIP and matching draft file, exact archive bytes, accepted/refused unsaved test isolation, provider data transport, immediate rescan/rule resolution, default gamelist persistence, fresh upstream readback and equal test/saved Intent. Screenshots capture the real GUI; APK never uploaded.\n')
    finally:
        h.shell('am', 'force-stop', h.app)
        if release_installed: h.adb('install', '-r', str(h.apk))
        fixture('cleanup')
        for name, content in original.items(): h.user_file('custom_systems/' + name, content)
        h.user_file('settings/es_settings.xml', original_settings)
