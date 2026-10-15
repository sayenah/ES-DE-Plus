#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Verified SDL app-importer smoke navigation.
import pathlib
import subprocess
import tempfile
import time


MAIN_ROWS = {'SEARCH', 'SCRAPER', 'UI SETTINGS', 'SOUND SETTINGS', 'INPUT DEVICE SETTINGS',
             'GAME COLLECTION SETTINGS', 'OTHER SETTINGS', 'UTILITIES'}


def activate(selected, expected, key):
    assert selected != 'QUIT ES-DE', 'Unsafe importer navigation: QUIT ES-DE is focused; A was not sent'
    assert selected == expected, f'Importer navigation expected {expected!r}, focused {selected!r}; A was not sent'
    key('KEYCODE_ENTER')


def read_label(frame):
    return subprocess.run(['java', '-Djava.awt.headless=true', 'android/SmokeMenuFocus.java', str(frame)],
                          capture_output=True, text=True, timeout=30)


def capture_failure(h, name):
    # Independent captures: one unavailable diagnostic must not prevent the rest
    # or replace the original assertion. Caller has not force-stopped the frontend.
    for suffix, action in [
            ('es_log.txt', h.log),
            ('es_log.txt.bak.txt', lambda: h.shell('cat', h.logpath + '.bak', check=False)),
            ('window.txt', h.focused_window),
            ('logcat.txt', lambda: h.adb('logcat', '-d', '-v', 'threadtime'))]:
        try:
            output = action()
            (h.evidence / (name + '-' + suffix)).write_text(output)
            if suffix == 'es_log.txt':
                tail = '\n'.join(output.splitlines()[-60:]) + '\n'
                (h.evidence / (name + '-last-frontend-lines.txt')).write_text(tail)
                print('IMPORTER FAILURE — last frontend lines:\n' + tail, flush=True)
        except Exception as error:
            (h.evidence / (name + '-' + suffix + '-capture-error.txt')).write_text(str(error))
    try:
        (h.evidence / (name + '.png')).write_bytes(h.adb('exec-out', 'screencap', '-p', binary=True))
    except Exception as error:
        (h.evidence / (name + '-screenshot-error.txt')).write_text(str(error))


def open_importer(harness, mode):
    h = type('Harness', (), harness)
    # Repeated PDF-launch checks call this flow too; retain each navigation trace.
    with (h.evidence / 'importer-navigation-sequence.txt').open('a+') as sequence:
        sequence.seek(0)
        number = len(sequence.readlines()) + 1
        name = f'importer-navigation-{mode}-{number}'
        sequence.write(name + '\n')
    trace = h.evidence / (name + '-focus-trace.txt')
    pid = h.shell('pidof', h.app).strip()
    assert pid, 'Importer navigation requires a running frontend'
    step = 0

    def record(message):
        print('IMPORTER: ' + message, flush=True)
        with trace.open('a') as output:
            output.write(message + '\n')

    def selected():
        nonlocal step
        assert h.shell('pidof', h.app, check=False).strip() == pid, 'Frontend process changed during importer navigation'
        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), 'Frontend lost focus during importer navigation'
        # Observe the completed menu animation without replaying an input.
        time.sleep(0.5)
        frame = h.evidence / f'{name}-step{step}.png'
        frame.write_bytes(h.adb('exec-out', 'screencap', '-p', binary=True))
        result = read_label(frame)
        record(f'{step}: {frame.name}: exit={result.returncode} label={result.stdout.strip()!r} {result.stderr.strip()}')
        step += 1
        assert result.returncode == 0, 'Cannot verify importer menu selection: ' + result.stderr
        return result.stdout.strip()

    try:
        record('Open MAIN MENU (Escape); frontend PID=' + pid)
        h.key('KEYCODE_ESCAPE')
        label = selected()
        assert label != 'QUIT ES-DE', 'Unsafe importer navigation: QUIT ES-DE is focused; A was not sent'
        assert label == 'SEARCH', 'Fresh main menu did not focus SEARCH: ' + label
        seen = set()
        while label != 'UTILITIES':
            assert label != 'QUIT ES-DE', 'Unsafe importer navigation: QUIT ES-DE is focused; A was not sent'
            assert label in MAIN_ROWS and label not in seen, 'Importer menu did not advance to a new known label: ' + label
            seen.add(label)
            record('Down from ' + label)
            h.key('KEYCODE_DPAD_DOWN')
            label = selected()
        record('Verified UTILITIES; send A')
        activate(label, 'UTILITIES', h.key)
        label = selected()
        record('Verify GAME IMPORTER before A: ' + label)
        activate(label, 'GAME IMPORTER', h.key)
        record('PASS: verified UTILITIES and GAME IMPORTER before each A')
    except Exception as error:
        record('FAIL: ' + str(error))
        capture_failure(h, name + '-failure')
        raise


def controls():
    actions = []
    activate('UTILITIES', 'UTILITIES', actions.append)
    activate('GAME IMPORTER', 'GAME IMPORTER', actions.append)
    assert actions == ['KEYCODE_ENTER', 'KEYCODE_ENTER']
    for focused in ['QUIT ES-DE', 'SEARCH', '', 'GAME IMPORTER EXTRA']:
        before = list(actions)
        try:
            activate(focused, 'UTILITIES', actions.append)
        except AssertionError as error:
            assert 'A was not sent' in str(error)
            if focused == 'QUIT ES-DE':
                assert 'QUIT ES-DE is focused' in str(error)
        else:
            raise AssertionError('Unsafe menu selection escaped: ' + focused)
        assert actions == before, 'Rejected label sent an input'
    with tempfile.TemporaryDirectory(dir='android') as temporary:
        result = subprocess.run(['java', '-Djava.awt.headless=true', 'android/SmokeMenuFocus.java',
                                 '--controls', temporary], capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        frames = list(pathlib.Path(temporary).glob('quit-*.png'))
        assert len(frames) == 3, 'Missing screenshot QUIT controls'
        for frame in frames:
            reading = read_label(frame)
            assert reading.returncode == 0 and reading.stdout.strip() == 'QUIT ES-DE', reading
            try:
                activate(reading.stdout.strip(), 'UTILITIES', actions.append)
            except AssertionError as error:
                assert 'QUIT ES-DE is focused; A was not sent' in str(error)
            else:
                raise AssertionError('Screenshot QUIT control sent A')
            assert actions == ['KEYCODE_ENTER', 'KEYCODE_ENTER']
    # Exercise all failure captures with a fake frontend, including a diagnostic
    # failure: both logs, screenshot and tail must precede the caller's cleanup.
    with tempfile.TemporaryDirectory(dir='android') as temporary:
        class Harness:
            evidence = pathlib.Path(temporary)
            logpath = '/frontend/es_log.txt'
            log = staticmethod(lambda: 'last frontend line\n')
            shell = staticmethod(lambda *args, **kwargs: 'previous run\n')
            focused_window = staticmethod(lambda: (_ for _ in ()).throw(RuntimeError('diagnostic unavailable')))
            adb = staticmethod(lambda *args, **kwargs: b'PNG' if kwargs.get('binary') else 'logcat')
        capture_failure(Harness, 'control')
        expected = {'control-es_log.txt', 'control-es_log.txt.bak.txt', 'control.png',
                    'control-last-frontend-lines.txt', 'control-window.txt-capture-error.txt', 'control-logcat.txt'}
        assert {p.name for p in Harness.evidence.iterdir()} == expected
        assert (Harness.evidence / 'control-es_log.txt.bak.txt').read_text() == 'previous run\n'
    return result.stdout + 'PASS: screenshot QUIT/wrong/unknown labels rejected without A; correct labels activate; failure captures survive a diagnostic error.\n'


if __name__ == '__main__':
    print(controls(), end='')
