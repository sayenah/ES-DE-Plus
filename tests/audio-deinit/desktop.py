#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Actual DEINIT_ON_LAUNCH frontend smoke, no framework.
import os
import pathlib
import subprocess
import sys
import time


def run(binary, probe, destination):
    root = pathlib.Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'android'))
    from audio_smoke import video_fixture
    destination = pathlib.Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for name in ['game-launched', 'command', 'ack']:
        (destination / name).unlink(missing_ok=True)
    home = destination / 'home'
    appdata = home / 'ES-DE'
    for directory in ['settings', 'custom_systems', 'logs', 'themes']:
        (appdata / directory).mkdir(parents=True, exist_ok=True)
    roms = home / 'ROMs'
    (roms / 'nes').mkdir(parents=True, exist_ok=True)
    # Exercise the upstream fixture tool, using its documented systems/info inputs.
    (roms / 'systems.txt').write_text('nes: Nintendo Entertainment System\n')
    (roms / 'nes/systeminfo.txt').write_text('.nes\n')
    subprocess.run(['bash', str(root / 'tools/create_dummy_game_files.sh')], cwd=roms, check=True)
    (roms / 'nes/second.nes').write_bytes(b'')
    media = home / 'media'
    (media / 'nes/videos').mkdir(parents=True, exist_ok=True)
    for stem in ['dummy', 'second']:
        video_fixture(media / ('nes/videos/' + stem + '.avi'))
    marker = destination / 'game-launched'
    (appdata / 'custom_systems/es_systems.xml').write_text(
        f'<systemList><loadExclusive/><system><name>nes</name><fullname>Audio smoke</fullname>'
        f'<path>{roms}/nes</path><extension>.nes</extension>'
        f'<command>touch {marker}</command><platform>nes</platform><theme>nes</theme></system></systemList>')
    # Preserve the normal keyboard mapping, bypass only the first-use controller dialog.
    (appdata / 'settings/es_input.xml').write_text(
        '<inputList><inputConfig type="keyboard" deviceName="Keyboard" deviceGUID="-1">' +
        ''.join(f'<input name="{name}" type="key" id="{key}" value="1"/>' for name, key in
                [('a', 13), ('b', 8), ('up', 1073741906), ('down', 1073741905),
                 ('left', 1073741904), ('right', 1073741903), ('start', 27)]) +
        '</inputConfig></inputList>')
    (appdata / 'settings/es_settings.xml').write_text(
        '<?xml version="1.0"?>\n<bool name="SplashScreen" value="false"/>\n'
        '<bool name="ApplicationUpdaterCheckForUpdates" value="false"/>\n'
        '<bool name="NavigationSounds" value="true"/>\n'
        '<bool name="ViewsVideoAudio" value="true"/>\n'
        '<string name="ThemeVariant" value="textlistWithVideos"/>\n'
        '<string name="MediaDirectory" value="' + str(media) + '"/>\n'
        '<string name="ROMDirectory" value="' + str(roms) + '"/>\n')
    env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='offscreen',
               LIBGL_ALWAYS_SOFTWARE='1', ESDE_AUDIO_PROBE=str(destination), LD_PRELOAD=str(pathlib.Path(probe).resolve()))
    sequence = 0
    output = (destination / 'frontend.txt').open('w')
    process = subprocess.Popen([str(pathlib.Path(binary).resolve()), '--home', str(home),
                                '--resolution', '640', '480', '--debug'], env=env, cwd=root,
                               stdout=output, stderr=subprocess.STDOUT)
    logpath = appdata / 'logs/es_log.txt'

    def log():
        return logpath.read_text() if logpath.exists() else ''

    def wait(condition, label, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert process.poll() is None, f'Frontend exited during {label}: {log()}'
            if condition():
                return
            time.sleep(.1)
        raise AssertionError(f'Timeout: {label}\n{log()}')

    def command(action):
        nonlocal sequence
        sequence += 1
        temporary = destination / 'command.new'
        temporary.write_text(f'{sequence} {action}\n')
        temporary.replace(destination / 'command')
        ack = destination / 'ack'
        wait(lambda: ack.exists() and ack.read_text().split()[:1] == [str(sequence)], action)
        return tuple(map(int, ack.read_text().split()[1:]))

    try:
        wait(lambda: 'Application startup time:' in log(), 'actual system view')
        time.sleep(2)
        command('enter')
        time.sleep(2)
        command('enter')
        wait(marker.exists, 'real game command ran')
        wait(lambda: log().count('Setting up AudioManager...') == 2, 'audio reinitialised after game launch')
        time.sleep(2)
        before = command('status')
        command('down')
        time.sleep(1)
        after = command('status')
        assert after[0] > before[0], 'No nonzero navigation PCM after DEINIT_ON_LAUNCH return'
        time.sleep(4)
        video = command('status')
        assert video[0] > after[0] and video[1] > after[1], 'No decoded video audio after return'
        command('quit')
        assert process.wait(timeout=30) == 0
        assert 'cleanly shutting down' in log()
        assert 'Error:' not in log(), log()
        (destination / 'summary.txt').write_text(
            f'PASS: real dummy-ROM game command; audio setup twice; nonzero navigation mixes '
            f'after return {before[0]} -> {after[0]}; decoded-video reads {after[1]} -> {video[1]}, '
            f'nonzero mixes {after[0]} -> {video[0]}; SDL quit/desktop exit status 0.\n')
        print((destination / 'summary.txt').read_text(), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        output.close()


if __name__ == '__main__':
    run(*sys.argv[1:])
