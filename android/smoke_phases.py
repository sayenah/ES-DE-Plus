#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Independent fresh-AVD regression sessions.
PHASES = ('core', 'lifecycle', 'integration', 'pdf-direct', 'pdf-scoped', 'assets', 'clear-task')


def prepare(harness, mode):
    h = type('Harness', (), harness)
    # A new emulator has neither configuration nor accepted grants. Use the
    # same real configurator and ordinary-shell ROM provisioning as core;
    # never transplant preferences, settings or grants from another session.
    h.clear_app()
    h.start_entry('HomeEntry', 'android.intent.category.HOME')
    if mode == 'direct':
        h.ui('Use direct filesystem compatibility', dpad=True)
        h.ui('Grant direct filesystem access', dpad=True)
        h.grant_from_settings()
    else:
        h.ui('Use app-owned storage', dpad=True)
    root = h.shared if mode == 'direct' else h.roms
    h.shell('mkdir', '-p', root + '/nes')
    dummy = h.evidence / 'session-dummy.nes'
    dummy.write_bytes(b'\0')
    for name in ('Smoke Alpha.nes', 'Smoke Beta.nes'):
        h.adb('push', str(dummy), root + '/nes/' + name)
    dummy.unlink()
    if mode == 'direct':
        h.ui('Absolute shared ROM folder path', dpad=h.television)
        h.shell('input', 'text', h.shared)
        h.key('KEYCODE_BACK')
        h.ui('Use typed folder path', dpad=True)
    h.ui('Create system folders', dpad=True)
    h.ui('Save and start frontend', dpad=True)
    h.configured_system('session-' + mode + '-configured')
    if mode == 'direct':
        # The PDF suite's existing direct recipient flow needs its own real
        # filesystem grant. Core still tests the complete launch contract.
        h.shell('am', 'start', '-n', 'org.esdeplus.stub/.RecipientActivity',
                '--es', 'queryMode', 'storage-permission')
        h.grant_from_settings('ES-DE Plus recipient', recipient=True)
        h.shell('am', 'force-stop', 'org.esdeplus.stub')
        h.start_entry('HomeEntry', 'android.intent.category.HOME')
        h.configured_system('session-direct-recipient-return')
    h.evidence.joinpath('session-configuration.txt').write_text(
        'PASS: fresh emulator configured through the real UI; two ordinary-shell ROMs; mode=' + mode + '\n' +
        h.shell('cat', h.settings))


def run(phase, harness):
    h = type('Harness', (), harness)
    assert phase in PHASES and phase != 'core', phase
    prepare(harness, 'scoped' if phase == 'pdf-scoped' else 'direct')
    if phase == 'assets':
        import forced_relaunch_smoke
        forced_relaunch_smoke.run(harness)
    elif phase == 'lifecycle':
        h.lifecycle_smoke.run(harness)
    elif phase == 'clear-task':
        import clear_task_smoke
        clear_task_smoke.run(harness)
    elif phase == 'integration':
        h.audio_smoke.run(harness)
        h.network_smoke.run(harness)
    else:
        h.pdf_smoke.run('scoped' if phase == 'pdf-scoped' else 'direct', harness)
        if phase == 'pdf-scoped':
            # The unchanged Unicode/minified probe consumes the real fixtures
            # created by the scoped PDF session, in the same selected storage.
            h.pdf_smoke.release(harness)
    h.evidence.joinpath('session-result.txt').write_text('PASS: ' + phase + '\n')
