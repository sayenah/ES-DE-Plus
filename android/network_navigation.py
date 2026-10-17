#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Verified network-menu navigation.
import importer_navigation as navigation


ROWS = ('SEARCH', 'SCRAPER', 'UI SETTINGS', 'SOUND SETTINGS',
        'INPUT DEVICE SETTINGS', 'GAME COLLECTION SETTINGS', 'OTHER SETTINGS', 'UTILITIES')


def open_menu(h, target, stem):
    assert target in ROWS
    pid = h.shell('pidof', h.app).strip()
    assert pid, 'Network navigation requires a live frontend'
    step = 0

    def read():
        nonlocal step
        assert h.shell('pidof', h.app, check=False).strip() == pid, 'Frontend changed during network navigation'
        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), 'Frontend lost focus'
        frame = h.evidence / f'{stem}-menu-{step}.png'
        frame.write_bytes(h.adb('exec-out', 'screencap', '-p', binary=True))
        result = navigation.read_label(frame)
        with h.evidence.joinpath(stem + '-navigation.txt').open('a') as output:
            output.write(f'{step}: code={result.returncode} label={result.stdout.strip()!r}\n')
        step += 1
        return result.stdout.strip() if result.returncode == 0 else None

    try:
        h.key('KEYCODE_ESCAPE')
        label = navigation.wait_selection(read)
        seen = set()
        while label != target:
            assert label in ROWS and label not in seen, 'Unexpected network-menu selection: ' + label
            seen.add(label)
            h.key('KEYCODE_DPAD_UP' if ROWS.index(label) > ROWS.index(target) else 'KEYCODE_DPAD_DOWN')
            label = navigation.wait_selection(read, previous=label)
        navigation.activate(label, target, h.key)
        if target == 'UI SETTINGS':
            # Observe the actual submenu before sending its activation key.
            label = navigation.wait_selection(read, previous=target)
            navigation.activate(label, 'THEME DOWNLOADER', h.key)
    except Exception:
        navigation.capture_failure(h, stem + '-navigation-failure')
        raise


def controls():
    import pathlib
    import tempfile
    from types import SimpleNamespace
    from unittest.mock import patch

    with tempfile.TemporaryDirectory(dir='android') as directory:
        actions = []
        h = SimpleNamespace(
            app='org.esdeplus.frontend', evidence=pathlib.Path(directory), logpath='/fixture/log',
            shell=lambda *args, **kwargs: '123', key=actions.append,
            focused_window=lambda: 'fixture frontend', log=lambda: 'fixture frontend log',
            adb=lambda *args, **kwargs: b'PNG' if kwargs.get('binary') else 'fixture logcat',
            smoke_checks=SimpleNamespace(package_window_focused=lambda *_: True))

        def check(frames, expected, failure=False):
            actions.clear()
            frames = iter(frames)
            def label(_):
                return SimpleNamespace(returncode=0, stdout=next(frames), stderr='')
            with patch.object(navigation, 'read_label', label):
                try:
                    open_menu(h, 'UI SETTINGS', 'control')
                except AssertionError:
                    assert failure
                else:
                    assert not failure
            assert actions == expected, actions

        check(['SEARCH', 'SEARCH', 'SCRAPER', 'UI SETTINGS', 'UI SETTINGS', 'THEME DOWNLOADER'],
              ['KEYCODE_ESCAPE', 'KEYCODE_DPAD_DOWN', 'KEYCODE_DPAD_DOWN',
               'KEYCODE_ENTER', 'KEYCODE_ENTER'])
        check(['SOUND SETTINGS', 'UI SETTINGS', 'THEME DOWNLOADER'],
              ['KEYCODE_ESCAPE', 'KEYCODE_DPAD_UP', 'KEYCODE_ENTER', 'KEYCODE_ENTER'])
        check(['UI SETTINGS', 'SOUND SETTINGS'], ['KEYCODE_ESCAPE', 'KEYCODE_ENTER'], True)
        check(['QUIT ES-DE'], ['KEYCODE_ESCAPE'], True)
    return ('PASS: network navigation observes delayed frames without action replay; '
            'remembered selection handled; wrong submenu and QUIT never activated.')


if __name__ == '__main__':
    print(controls())
