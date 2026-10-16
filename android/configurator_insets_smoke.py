#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Phone layout checks on actual SDK insets.
import pathlib
import subprocess
import sys
import smoke_checks


def run(*args):
    return subprocess.run(['adb', *args], check=True, capture_output=True, text=True, timeout=90).stdout


def main():
    app = next(x.split('=', 1)[1] for x in pathlib.Path('android/gradle.properties').read_text().splitlines()
               if x.startswith('esde.applicationId='))
    assert int(run('shell', 'getprop', 'ro.build.version.sdk')) in (35, 36)
    root = pathlib.Path('android/evidence/configurator-insets')
    root.mkdir(parents=True, exist_ok=True)
    run('install', '-r', sys.argv[1])
    run('shell', 'cmd', 'overlay', 'enable', 'com.android.internal.display.cutout.emulation.tall')
    # SDK navigation overlays are real SystemUI modes, not mocked insets.
    for mode, overlay in [('gesture', 'gestural'), ('three-button', 'threebutton')]:
        run('shell', 'cmd', 'overlay', 'enable-exclusive', '--category',
            'com.android.internal.systemui.navbar.' + overlay)
        for orientation, rotation in [('portrait', '0'), ('landscape', '1')]:
            run('shell', 'am', 'force-stop', app)
            run('shell', 'pm', 'clear', app)
            run('shell', 'appops', 'set', '--uid', app, 'MANAGE_EXTERNAL_STORAGE', 'allow')
            result = run('shell', 'am', 'instrument', '-w', '-e', 'mode', 'configurator-insets', '-e', 'rotation', rotation,
                         app + '/org.esdeplus.frontend.RuntimeSmoke')
            overlay_state = run('shell', 'cmd', 'overlay', 'list')
            # Preserve the actual failure report before any assertion: this
            # probe gates and its evidence must survive later session loss.
            (root / (mode + '-' + orientation + '.txt')).write_text(result + '\n' + overlay_state)
            print(mode, orientation, result, flush=True)
            assert '[x] com.android.internal.systemui.navbar.' + overlay in overlay_state, overlay_state
            smoke_checks.probe_passed(result, 'PASS: inset oracle rejects bar overlap positive controls')
            assert 'cutout=DisplayCutout' in result, result
            assert ('orientation=' + ('1' if rotation == '0' else '2')) in result, result



if __name__ == '__main__':
    main()
