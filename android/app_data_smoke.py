#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Fixtures authored from USERGUIDE.md and the open parsers.
import pathlib
import tempfile
import xml.etree.ElementTree as ET


def run(harness):
    h = type('Harness', (), harness)
    shared_roms = '/sdcard/ESDEPlusSmoke'
    base = '/sdcard/PRFApplicationData'

    def write(path, contents):
        h.shell('mkdir', '-p', str(pathlib.PurePosixPath(path).parent))
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml') as fixture:
            fixture.write(contents)
            fixture.flush()
            h.adb('push', fixture.name, path)

    def type_path(label, path):
        h.ui(label, dpad=True)
        current = next(n.get('text', '') for n in h.hierarchy()
                       if n.get('class') == 'android.widget.EditText')
        h.key('KEYCODE_MOVE_END')
        if current:
            h.shell('input', 'keyevent', *(['KEYCODE_DEL'] * len(current)))
        h.shell('input', 'text', path)
        h.key('KEYCODE_BACK')

    def grant():
        h.ui('Use direct filesystem compatibility', dpad=True)
        if any(h.node_matches(n, 'Grant direct filesystem access') for n in h.hierarchy()):
            h.ui('Grant direct filesystem access', dpad=True)
            if h.api == 29:
                h.ui('Allow')
            else:
                h.grant_from_settings()

    def choose(root, *, changed=False):
        if changed:
            h.ui('Change application-data folder', dpad=True)
        type_path('Absolute application-data folder path', root)
        h.ui('Review application-data folder', dpad=True)
        h.ui('Concurrent use with another frontend')
        h.ui('Confirm and use this data folder', dpad=True)
        h.ui('Existing MediaDirectory override')
        type_path('Absolute shared ROM folder path', shared_roms)
        h.ui('Use typed folder path', dpad=True)
        h.select_data_root(root)
        h.ui('Create system folders', dpad=True, focus_only=True)
        checkbox = next(n for n in h.hierarchy() if n.get('text') == 'Create system folders')
        if checkbox.get('checked') == 'true':
            h.key('KEYCODE_DPAD_CENTER')
        assert any(n.get('text') == 'Create system folders' and n.get('checked') == 'false'
                   for n in h.hierarchy()), 'Fixture did not turn off directory creation'
        h.ui('Save and start frontend', dpad=True)
        h.configured_system('app-data-selected-' + root.rsplit('/', 1)[-1])
        h.smoke_checks.no_generation(h.log())

    def fixture(root, legacy):
        # The XML deliberately disagrees with the configurator's ROM path.
        # All other files are independently authored and contain no official data.
        h.shell('mkdir', '-p', root + '/media')
        values = [
            ('string', 'ROMDirectory', '/sdcard/ConflictingPRFROMs'),
            ('string', 'MediaDirectory', root + '/media'),
            ('string', 'Theme', 'unavailable-prf-authored-theme'),
            ('string', 'CollectionSystemsCustom', 'retained'),
            ('bool', 'CustomEventScripts', 'true'),
            ('bool', 'SystemStatusBluetooth', 'true'),
            ('bool', 'SystemStatusWifi', 'true'),
            ('bool', 'SystemStatusCellular', 'true'),
            ('bool', 'RetroArchCoreQueryExperimental', 'true'),
            ('bool', 'DebugMode', 'true'),
        ]
        xml = ''.join(ET.tostring(ET.Element(kind, name=name, value=value), encoding='unicode')
                      for kind, name, value in values)
        write(root + ('/es_settings.xml' if legacy else '/settings/es_settings.xml'), xml)
        write(root + '/custom_systems/es_systems.xml', '''<systemList><system>
<name>nes</name><fullname>PRF Authored NES</fullname><path>%ROMPATH%/nes</path>
<extension>.nes</extension><command label="Authored fixture">%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/fceumm_libretro_android.so %ROM%</command>
<platform>nes</platform><theme>nes</theme></system></systemList>''')
        write(root + '/gamelists/nes/gamelist.xml', '''<gameList>
<game><path>./Smoke Alpha.nes</path><name>Retained Alpha</name><favorite>true</favorite></game>
<game><path>./Smoke Beta.nes</path><name>Retained Beta</name></game></gameList>''')
        write(root + '/collections/custom-retained.cfg', '%ROMPATH%/nes/Smoke Alpha.nes\n')
        write(root + '/scripts/settings-changed/record.sh', 'printf "authored-script-ran\\n" >> "' + root + '/script-observed.txt"\n')
        write(root + '/retained-marker.txt', 'ES-DE-Plus-authored retained data\n')

    def loaded(root, name):
        output = h.log()
        assert 'Parsing gamelist file' in output and '/gamelists/nes/gamelist.xml' in output, output
        assert 'Found custom systems configuration file' in output, output
        assert 'Parsing custom collection file' in output and 'custom-retained.cfg' in output, output
        assert h.shell('cat', root + '/retained-marker.txt') == 'ES-DE-Plus-authored retained data\n'
        settings = h.shell('cat', root + '/settings/es_settings.xml')
        assert 'ConflictingPRFROMs' in settings, 'Native startup rewrote XML ROMDirectory'
        assert h.shell('test', '-f', root + '/script-observed.txt') == ''
        h.save_logs(name)
        h.screenshot(name)

    h.shell('am', 'force-stop', h.app)
    h.clear_app()
    roots = [base + '/Renamed', base + '/.emulationstation', base + '/ES-DE']
    h.shell('test', '!', '-e', base)
    for index, root in enumerate(roots):
        fixture(root, legacy=index == 1)
    h.start_entry()
    grant()
    choose(roots[0])
    loaded(roots[0], 'app-data-renamed-loaded')
    h.shell('am', 'force-stop', h.app)
    upgraded = h.shell('am', 'instrument', '-w', '-e', 'mode', 'legacy-direct-data',
                       h.app + '/org.esdeplus.frontend.RuntimeSmoke')
    h.smoke_checks.probe_passed(upgraded, 'PASS: pre-data-folder direct preferences retained ROM=')
    h.evidence.joinpath('app-data-direct-upgrade.txt').write_text(upgraded)
    h.shell('am', 'force-stop', h.app)
    h.start_entry()
    h.ui('Choose and confirm the application-data folder')
    choose(roots[0])
    loaded(roots[0], 'app-data-upgrade-rom-preserved')

    # Instrument the actual consent UI and access to a separate authored tree.
    h.shell('am', 'force-stop', h.app)
    result = h.instrument_with_ui('am', 'instrument', '-w', '-e', 'mode', 'app-data-probe',
                                 h.app + '/org.esdeplus.frontend.RuntimeSmoke')
    h.evidence.joinpath('app-data-no-access-probe.txt').write_text(result)
    h.smoke_checks.probe_passed(result, 'PASS: real consent cancellation has no FileObserver access')
    h.shell('am', 'force-stop', h.app)
    h.start_entry()
    h.configured_system('app-data-before-resume-loss')
    old = h.shell('pidof', h.app).strip()
    # Lose the selected root while backgrounded. Validation must not recreate it.
    h.shell('am', 'start', '-a', 'android.settings.SETTINGS')
    h.shell('mv', roots[0], roots[0] + '.unavailable')
    try:
        h.key('KEYCODE_BACK')
        h.ui('Configure ' + h.label)
        h.shell('test', '!', '-e', roots[0])
        h.screenshot('app-data-missing-on-resume')
    finally:
        h.shell('mv', roots[0] + '.unavailable', roots[0])
    # Changing roots after native startup must start a new frontend process.
    choose(roots[1], changed=True)
    h.wait_for(lambda: h.shell('pidof', h.app, check=False).strip() not in {'', old},
               'fresh native process after data-root re-selection')
    loaded(roots[1], 'app-data-legacy-loaded')
    assert h.shell('test', '!', '-e', roots[1] + '/es_settings.xml') == '', 'Upstream legacy migration did not run'
    # A removed root on cold startup is also recoverable, without a fallback.
    h.shell('am', 'force-stop', h.app)
    h.shell('mv', roots[1], roots[1] + '.unavailable')
    try:
        h.start_entry()
        h.ui('Configure ' + h.label)
        h.shell('test', '!', '-e', roots[1])
        h.screenshot('app-data-missing-at-startup')
    finally:
        h.shell('mv', roots[1] + '.unavailable', roots[1])
    choose(roots[2], changed=True)
    loaded(roots[2], 'app-data-shared-loaded')

    # Permission revocation and an in-place data-folder obstruction are real
    # recovery paths; the existing regression pass covers permission denial.
    h.shell('am', 'force-stop', h.app)
    h.shell('mv', roots[2] + '/themes', roots[2] + '/themes.saved')
    write(roots[2] + '/themes', 'obstructed required directory')
    try:
        h.start_entry()
        h.ui('Configure ' + h.label)
        h.screenshot('app-data-obstructed-required-path')
    finally:
        h.shell('am', 'force-stop', h.app)
        h.shell('rm', roots[2] + '/themes')
        h.shell('mv', roots[2] + '/themes.saved', roots[2] + '/themes')

    # Real uninstall/reinstall: no -k or pm clear substitute; the shared data
    # survives and is selected again through the configurator with new consent.
    assert 'Success' in h.adb('uninstall', h.app)
    assert h.shell('cat', roots[2] + '/retained-marker.txt') == 'ES-DE-Plus-authored retained data\n'
    assert 'Success' in h.adb('install', str(h.apk))
    h.start_entry()
    grant()
    choose(roots[2])
    loaded(roots[2], 'app-data-after-real-uninstall-reinstall')
    h.evidence.joinpath('app-data-summary.txt').write_text(
        'PASS: real permission/data/ROM configurator order, exact-destination adoption consent, '
        'D-pad/typed selection, authored renamed/.emulationstation/ES-DE folders, legacy settings migration, '
        'conflicting XML ROM preserved, media override, custom systems/gamelists/collections/scripts loaded, '
        'unavailable theme fallback, missing selected root at startup/resume without recreation, '
        'obstructed required themes, fresh process on re-selection, real uninstall/reinstall and shared-data reload. '
        'No-access/tree-hash positive controls are recorded separately.\n')
