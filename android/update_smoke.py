#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. D-013 real in-place update with throwaway signing.
import hashlib
import json
import pathlib
import xml.etree.ElementTree as ET

import pdf_smoke


def run(harness):
    h = type('Harness', (), harness)
    record = json.loads((h.evidence / 'update-identity.txt').read_text())
    assert record['higher']['version_code'] == record['lower']['version_code'] + 1
    assert record['lower']['signer_sha256'] == record['higher']['signer_sha256']
    h.adb('install', 'android/.deps/update/lower.apk')
    h.start_entry()
    h.ui('Use app-owned storage')
    h.ui('Create system folders')
    h.shell('mkdir', '-p', h.roms + '/nes')
    dummy = h.evidence / 'update-dummy.nes'
    dummy.write_bytes(b'\0')
    for name in ('Smoke Alpha.nes', 'Smoke Beta.nes'):
        h.adb('push', str(dummy), h.roms + '/nes/' + name)
    dummy.unlink()
    h.ui('Save and start frontend')
    h.wait_for(lambda: 'Application startup time:' in h.log(), 'lower-code frontend startup')
    h.configured_system('update-lower-system')
    h.shell('am', 'force-stop', h.app)
    settings = h.launch_checks.settings_fragment(h.shell('cat', h.settings))
    node = settings.find("int[@name='ScreensaverTimer']")
    assert node is not None, 'Real saved ScreensaverTimer setting absent'
    node.set('value', '123456')
    h.user_file('settings/es_settings.xml', pdf_smoke.settings_xml(settings))
    h.private('sh', '-c', "printf 'ES-DE-Plus update continuity sentinel\\n' > files/update-proof")
    sentinel = 'files/update-proof'
    prefs = h.private('cat', 'shared_prefs/storage.xml')
    snapshot = h.shell('cat', h.settings)
    data = h.private('cat', sentinel)
    h.launch()
    h.configured_system('update-lower-saved')
    h.shell('am', 'force-stop', h.app)
    # Capture after upstream's normal settings writes; the replacement itself
    # must preserve exact bytes, preferences and selected storage configuration.
    snapshot = h.shell('cat', h.settings)
    prefs = h.private('cat', 'shared_prefs/storage.xml')
    before = h.shell('dumpsys', 'package', h.app)
    assert 'versionCode=' + str(record['lower']['version_code']) in before
    result = h.adb('install', '-r', 'android/.deps/update/higher.apk')
    assert 'Success' in result
    assert h.shell('cat', h.settings) == snapshot, 'Update lost saved settings'
    assert h.private('cat', sentinel) == data, 'Update lost application data'
    assert h.private('cat', 'shared_prefs/storage.xml') == prefs, 'Update lost accepted configuration'
    after = h.shell('dumpsys', 'package', h.app)
    assert 'versionCode=' + str(record['higher']['version_code']) in after
    h.adb('logcat', '-c')
    h.launch()
    h.configured_system('update-higher-preserved')
    assert not any(r[0] == 'ConfiguratorActivity' for r in h.activity_records()[1]), 'Update requested reconfiguration'
    actual = h.launch_checks.settings_fragment(h.shell('cat', h.settings))
    assert actual.find("int[@name='ScreensaverTimer']").get('value') == '123456'
    assert h.private('cat', sentinel) == data
    h.evidence.joinpath('update-continuity.txt').write_text(
        'PASS: lower -> higher code, same in-run throwaway certificate; adb install -r only.\n'
        'No uninstall, data clear or downgrade flag between installs. Exact settings/preferences/data retained; '
        'higher build launches with preserved configuration and two ROMs.\n' +
        json.dumps({k: record[k]['version_code'] for k in record}) + '\n' +
        'Settings SHA256 before replacement=' + hashlib.sha256(snapshot.encode()).hexdigest() + '\n' +
        before + '\n' + result + '\n' + after)
    # End the independent fixture experiment before the ordinary regression
    # suite installs its own debug APK (the eligible leg uses the stable key).
    h.shell('am', 'force-stop', h.app)
    h.adb('uninstall', h.app)
