#!/usr/bin/env python3
#  SPDX-License-Identifier: MIT
#
#  ES-DE-Plus
#  run.py
#
#  Written for ES-DE-Plus. Real frontend input smoke and framebuffer evidence.
#

import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[2]


def png(path, required_pixel=None):
    # Lossless framebuffer conversion, no image or testing dependency.
    with path.open('rb') as stream:
        assert stream.readline() == b'P6\n'
        width, height = map(int, stream.readline().split())
        assert stream.readline() == b'255\n'
        pixels = stream.read()
    assert len(pixels) == width * height * 3
    if required_pixel:
        x, y, color = required_pixel
        offset = (y * width + x) * 3
        assert tuple(pixels[offset:offset + 3]) == color, 'Focused key interior fill was clipped'
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    data = b''.join(b'\0' + pixels[row * width * 3:(row + 1) * width * 3] for row in range(height))
    path.with_suffix('.png').write_bytes(b'\x89PNG\r\n\x1a\n' +
        chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
        chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b''))
    path.unlink()


def fixture(home, remember=True, kid=False, scheme='dark', language='en_US', large=False):
    appdata = home / 'ES-DE'
    for folder in ['settings', 'custom_systems', 'logs', 'themes']:
        (appdata / folder).mkdir(parents=True, exist_ok=True)
    roms = home / 'ROMs'
    roms.mkdir(parents=True, exist_ok=True)
    (roms / 'systems.txt').write_text('snes: Super Nintendo\npsx: PlayStation\n')
    for system in ['snes', 'psx']:
        (roms / system).mkdir(exist_ok=True)
        (roms / system / 'systeminfo.txt').write_text('.rom\n')
    subprocess.run(['bash', str(ROOT / 'tools/create_dummy_game_files.sh')], cwd=roms, check=True,
                   stdout=subprocess.DEVNULL)
    systems = ET.Element('systemList')
    ET.SubElement(systems, 'loadExclusive')
    titles = ['Final Fantasy VII', 'Final Fantasy VI', 'Final Fight', 'Finding Nemo',
              'Super Metroid', 'Chrono Trigger', 'F-Zero', 'Pokémon', 'Tetris']
    if large:
        titles.extend(f'Final Fixture {index:03d}' for index in range(300))
    media = home / 'media'
    for system in ['snes', 'psx']:
        node = ET.SubElement(systems, 'system')
        for name, value in [('name', system), ('fullname', 'Super Nintendo' if system == 'snes' else 'PlayStation'),
                            ('path', str(roms / system)), ('extension', '.rom'),
                            ('command', 'touch ' + str(home / 'game-launched')), ('platform', system), ('theme', system)]:
            ET.SubElement(node, name).text = value
        gamelist = ET.Element('gameList')
        for index, title in enumerate(titles):
            stem = f'game-{index}'
            (roms / system / (stem + '.rom')).write_bytes(b'')
            game = ET.SubElement(gamelist, 'game')
            for name, value in [('path', './' + stem + '.rom'), ('name', title), ('genre', 'Action'),
                                ('developer', 'Nintendo'), ('kidgame', 'true'), ('favorite', str(index in [0, 5, 6, 7, 8]).lower()),
                                ('releasedate', '19970101T000000'), ('lastplayed', '20261018T120000'), ('playtime', '7200')]:
                ET.SubElement(game, name).text = value
            # Original generated color artwork, deliberately independent of any product assets.
            directory = media / system / 'covers'
            directory.mkdir(parents=True, exist_ok=True)
            width, height = 120, 160
            color = bytes([(30 + index * 20) % 256, (60 + index * 12) % 256, (100 + index * 10) % 256])
            raw = b''.join(b'\0' + color * width for _ in range(height))
            def chunk(kind, payload):
                return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
            (directory / (stem + '.png')).write_bytes(b'\x89PNG\r\n\x1a\n' +
                chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
                chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
        (appdata / 'gamelists' / system).mkdir(parents=True, exist_ok=True)
        ET.ElementTree(gamelist).write(appdata / 'gamelists' / system / 'gamelist.xml')
    ET.ElementTree(systems).write(appdata / 'custom_systems/es_systems.xml')
    (appdata / 'settings/search_history.xml').write_text('<searchHistory><query>zelda</query><query>ff7</query></searchHistory>')
    (appdata / 'settings/es_input.xml').write_text(
        '<inputList><inputConfig type="keyboard" deviceName="Keyboard" deviceGUID="-1">' +
        ''.join(f'<input name="{name}" type="key" id="{key}" value="1"/>' for name, key in
                [('a', 13), ('b', 8), ('up', 1073741906), ('down', 1073741905),
                 ('left', 1073741904), ('right', 1073741903), ('start', 27)]) +
        '</inputConfig></inputList>')
    (appdata / 'settings/es_settings.xml').write_text(
        '<bool name="SplashScreen" value="false"/>\n'
        '<bool name="ApplicationUpdaterCheckForUpdates" value="false"/>\n'
        '<bool name="InputDeviceNotifications" value="false"/>\n'
        '<string name="MenuOpeningEffect" value="none"/>\n'
        '<bool name="SearchHistory" value="' + str(remember).lower() + '"/>\n'
        '<string name="UIMode" value="' + ('kid' if kid else 'full') + '"/>\n'
        '<string name="MenuColorScheme" value="' + scheme + '"/>\n'
        '<string name="ApplicationLanguage" value="' + language + '"/>\n'
        '<string name="MediaDirectory" value="' + str(media) + '"/>\n'
        '<string name="ROMDirectory" value="' + str(roms) + '"/>\n')
    return appdata


def run(binary, probe, destination, width, height, variant='dark'):
    destination = Path(destination).resolve() / f'{width}x{height}-{variant}'
    destination.mkdir(parents=True, exist_ok=True)
    home = destination / 'home'
    appdata = fixture(home, remember=variant != 'history-off', kid=variant == 'kid',
                      scheme='light' if variant == 'light' else 'dark',
                      language='de_DE' if variant == 'german' else 'en_US', large=variant == 'large')
    sequence = 0
    for name in ['command', 'ack']:
        (destination / name).unlink(missing_ok=True)
    env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='offscreen', LIBGL_ALWAYS_SOFTWARE='1',
               ESDE_SEARCH_PROBE=str(destination), LD_PRELOAD=str(Path(probe).resolve()))
    output = (destination / 'frontend.txt').open('w')
    process = subprocess.Popen([str(Path(binary).resolve()), '--home', str(home), '--resolution',
                                str(width), str(height), '--debug'], cwd=ROOT, env=env,
                               stdout=output, stderr=subprocess.STDOUT)
    logpath = appdata / 'logs/es_log.txt'
    def log():
        return logpath.read_text() if logpath.exists() else ''
    def query_seen(value, since=0):
        current = log()[since:]
        if variant in ['kid', 'history-off'] and value:
            return re.search(r'Search keystroke: query=<private> results=\d+ query_bytes=' +
                             str(len(value.encode())) + r'\b', current)
        return 'Search keystroke: query=' + value + ' results=' in current
    def wait(condition, label, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert process.poll() is None, f'Frontend exited: {label}\n{log()}'
            if condition():
                return
            time.sleep(.05)
        raise AssertionError(f'Timeout: {label}\n{log()}')
    def command(action, value=''):
        nonlocal sequence
        sequence += 1
        path = destination / 'command.new'
        path.write_text(f'{sequence} {action} {value}\n')
        path.replace(destination / 'command')
        wait(lambda: (destination / 'ack').exists() and (destination / 'ack').read_text().strip() == str(sequence), action)
        time.sleep(.2)
    def shot(name):
        if name == 'zero':
            time.sleep(1.5)  # Let visible async covers finish their independent fades.
        command('capture', name)
        unit = min(width, height) / 1080
        required = (round(66 * unit), round(height - 483 * unit),
                    (184, 106, 18) if variant == 'light' else (240, 166, 58)) if name == 'zero' else None
        png(destination / (name + '.ppm'), required)
    def search():
        command('pad', '3')  # Y, the actual SDL controller entry point.
        wait(lambda: 'Search screen opened:' in log(), 'search opened')
    try:
        wait(lambda: 'Application startup time:' in log(), 'real frontend startup')
        time.sleep(2)
        opening_start = time.monotonic()
        search()
        opening_ms = (time.monotonic() - opening_start) * 1000
        shot('zero')
        for character in 'fin':
            before = len(log())
            command('text', character)
            wait(lambda: query_seen('fin'[:'fin'.index(character) + 1], before), 'live ' + character)
        shot('typing-fin')
        command('pad', '10')  # R changes the system filter.
        shot('filter')
        command('pad', '6')  # Start focuses results.
        before = len(log())
        command('pad', '11')  # Up reaches visible filters even with saved history.
        wait(lambda: 'Search focus: area=4 index=0' in log()[before:], 'visible filter row above results')
        command('pad', '12')
        if variant == 'large':
            for _ in range(205):
                command('key', '1073741905')
            wait(lambda: 'Search focus: area=6 index=205' in log(), 'navigation beyond first 200 results')
            shot('page-two')
            command('pad', '1')  # B returns to typing after scrolling deeply.
            command('key', '8')
            command('text', 'n')
            before = len(log())
            command('pad', '6')
            wait(lambda: 'Search focus: area=6 index=0' in log()[before:], 'edited query returns to best match')
        shot('results-focused')
        command('key', '13')  # Enter shows the actual game list.
        wait(lambda: 'Search show game:' in log(), 'game-list cursor navigation')
        history = (appdata / 'settings/search_history.xml').read_text()
        if variant in ['kid', 'history-off']:
            assert '<query>fin</query>' not in history
        else:
            assert '<query>fin</query>' in history and '<game ' in history
        command('pad', '3')
        command('text', 'qqqqqqqqqq')
        shot('no-results')
        command('key', '27')
        command('pad', '3')
        command('text', 'Poké')
        before = len(log())
        command('key', '8')
        wait(lambda: query_seen('Pok', before), 'Unicode backspace once')
        before = len(log())
        command('compose', 'が')
        assert not query_seen('Pokが', before), 'provisional composition was committed'
        command('text', 'が')
        wait(lambda: query_seen('Pokが', before), 'composition commit')
        if variant == 'dark' and width == 1280:
            tail = ' long query' * 8
            for _ in range(8):
                command('text', ' long query')
            shot('long-query')
            command('key', '1073741898')  # Home, then insert at the beginning of the field.
            before = len(log())
            command('text', 'X')
            wait(lambda: query_seen('XPokが' + tail, before), 'caret insertion in a long UTF-8 query')
        command('key', '27')
        before = len(log())
        command('key', '109')  # SDL key-up can precede the same opening character's commit.
        wait(lambda: query_seen('m', before), 'physical typing seeds search')
        command('text', 'm')
        assert not query_seen('mm', before), 'Opening key-up cleared duplicate suppression'
        command('key', '27')
        before = len(log())
        command('pad-typing', '3')
        wait(lambda: query_seen('f', before), 'platform text arriving while search opens')
        assert (destination / 'opening-text-state').read_text().strip() == '1', 'Opening lost SDL text input'
        command('key', '27')
        command('pad', '3')
        command('text', 'Final Fantasy VII')
        command('key', '1073741905')
        command('key', '13 64')  # Ctrl+Enter follows the normal launch path.
        wait(lambda: (home / 'game-launched').exists(), 'Ctrl+Enter game command')
        if variant in ['kid', 'history-off']:
            assert 'query=fin ' not in log(), 'Private query leaked into search diagnostics'
        command('quit')
        assert process.wait(timeout=30) == 0
        entry_work = re.findall(r'Search entry ready: ms=([0-9.]+)', log())
        assert entry_work, 'Missing actual search-entry timing'
        summary = dict(resolution=[width, height], variant=variant, opening_ms=opening_ms,
                       entry_work_ms=float(entry_work[0]), checks=['live strokes', 'scope filter', 'result focus', 'show game',
                               'history privacy', 'no results', 'UTF-8 deletion', 'IME commit', 'Ctrl+Enter launch'])
        (destination / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        output.close()


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]),
        sys.argv[6] if len(sys.argv) > 6 else 'dark')
