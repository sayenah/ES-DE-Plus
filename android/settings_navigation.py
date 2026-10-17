#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Verify SDL settings focus before inputs.
import importer_navigation


def change_navigation_volume(harness):
    h = type('Harness', (), harness)
    name = 'navigation-volume'
    pid = h.shell('pidof', h.app).strip()
    step = 0

    def record(message):
        with (h.evidence / (name + '-focus-trace.txt')).open('a') as output:
            output.write(message + '\n')

    def read():
        nonlocal step
        assert pid and h.shell('pidof', h.app, check=False).strip() == pid, 'Settings frontend process changed'
        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), 'Settings frontend lost focus'
        frame = h.evidence / f'{name}-step{step}.png'
        frame.write_bytes(h.adb('exec-out', 'screencap', '-p', binary=True))
        found = importer_navigation.read_label(frame)
        record(f'{step}: {frame.name}: exit={found.returncode} label={found.stdout.strip()!r} {found.stderr.strip()}')
        step += 1
        return found.stdout.strip() if found.returncode == 0 else None

    def observe(previous=None):
        return importer_navigation.wait_selection(read, previous)

    def act(expected, key):
        # A fresh capture immediately precedes every action inside a menu.
        actual = observe()
        assert actual == expected, f'Settings expected {expected!r}, focused {actual!r}; {key} was not sent'
        record(f'Verified {actual}; send {key}')
        h.key(key)

    try:
        assert pid and h.smoke_checks.package_window_focused(h.focused_window(), h.app)
        h.key('KEYCODE_ESCAPE')
        label = observe()
        visited = set()
        while label != 'SOUND SETTINGS':
            assert label in importer_navigation.MAIN_ROWS and label not in visited, 'Unexpected settings path: ' + label
            visited.add(label)
            direction = 'DOWN' if label in ('SEARCH', 'SCRAPER', 'UI SETTINGS') else 'UP'
            act(label, 'KEYCODE_DPAD_' + direction)
            label = observe(previous=label)
        act('SOUND SETTINGS', 'KEYCODE_ENTER')
        label = observe(previous='SOUND SETTINGS')
        assert label == 'AUDIO DRIVER (REQUIRES RESTART)', 'Unexpected sound settings: ' + label
        act(label, 'KEYCODE_DPAD_DOWN')
        label = observe(previous=label)
        assert label == 'NAVIGATION SOUNDS VOLUME', 'Wrong setting focused: ' + label
        act(label, 'KEYCODE_DPAD_LEFT')
        h.screenshot('changed-sound-setting')
        act(label, 'KEYCODE_DEL')  # Closing GuiSettings runs its save functions.
        label = observe(previous=label)
        assert label == 'SOUND SETTINGS', 'Settings Back did not return to the main menu: ' + label
        act(label, 'KEYCODE_DEL')
        record('PASS: verified settings path and one volume change; no action replay')
    except Exception as error:
        record('FAIL: ' + str(error))
        importer_navigation.capture_failure(h, name + '-failure')
        raise


def controls():
    import contextlib
    import io
    import smoke_checks
    import subprocess
    import tempfile
    import time
    from pathlib import Path
    from unittest.mock import patch

    def exercise(drop=False, wrong=False):
        with tempfile.TemporaryDirectory() as directory:
            state = dict(menu='game', row=1, changed=False, captured=False)
            actions = []
            rows = ['SEARCH', 'SCRAPER', 'UI SETTINGS', 'SOUND SETTINGS']
            def key(code):
                if state['menu'] != 'game':
                    assert state['captured'], 'Menu action without a fresh focus capture'
                state['captured'] = False
                actions.append(code)
                if code == 'KEYCODE_ESCAPE': state['menu'] = 'main'
                elif code == 'KEYCODE_DPAD_DOWN' and not drop: state['row'] += 1
                elif code == 'KEYCODE_ENTER': state.update(menu='wrong' if wrong else 'sound', row=0)
                elif code == 'KEYCODE_DPAD_LEFT': state['changed'] = True
                elif code == 'KEYCODE_DEL': state.update(menu='main' if state['menu'] == 'sound' else 'game', row=3)
            def label(frame):
                state['captured'] = True
                value = (rows[state['row']] if state['menu'] == 'main' else
                         'TOUCH OVERLAY SIZE' if state['menu'] == 'wrong' else
                         ['AUDIO DRIVER (REQUIRES RESTART)', 'NAVIGATION SOUNDS VOLUME'][state['row']])
                return subprocess.CompletedProcess([], 0, value, '')
            clock = [0]
            harness = dict(evidence=Path(directory), app='org.esdeplus.frontend', logpath='log',
                           shell=lambda *args, **kwargs: '123', log=lambda: 'native log', key=key,
                           screenshot=lambda name: None,
                           focused_window=lambda: 'mCurrentFocus=Window{x u0 org.esdeplus.frontend/.MainActivity}',
                           smoke_checks=smoke_checks, adb=lambda *args, **kwargs: b'PNG' if kwargs.get('binary') else '')
            with contextlib.redirect_stdout(io.StringIO()), patch.object(importer_navigation, 'read_label', label), \
                    patch.object(time, 'monotonic', lambda: clock[0]), \
                    patch.object(time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
                try:
                    change_navigation_volume(harness)
                except AssertionError:
                    assert drop or wrong
                    assert not state['changed']
                    if drop: assert actions == ['KEYCODE_ESCAPE', 'KEYCODE_DPAD_DOWN'], actions
                    if wrong: assert 'KEYCODE_DPAD_LEFT' not in actions
                else:
                    assert not drop and not wrong and state['changed'] and state['menu'] == 'game'
                    assert actions.count('KEYCODE_DPAD_DOWN') == 3  # Two menu rows, then the volume row.
    exercise()
    exercise(drop=True)
    exercise(wrong=True)
    return 'PASS: settings focus checked before each action; shifted initial selection handled; dropped key and wrong menu stay hard without replay.\n'
