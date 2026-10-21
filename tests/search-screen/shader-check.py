#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Actual shader compilation/framebuffer parity.
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'sdl2'], text=True))
with tempfile.TemporaryDirectory(prefix='esde-search-shaders-') as temporary:
    binary = Path(temporary) / 'shader-pixels'
    graphics = ['-framework', 'OpenGL'] if sys.platform == 'darwin' else ['-lGL']
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    str(root / 'tests/search-screen/shader-pixels.cpp'), '-I' + temporary, *flags, *graphics,
                    '-o', str(binary)], check=True)
    env = dict(os.environ)
    if sys.platform != 'darwin':
        env.update(SDL_VIDEODRIVER='offscreen', SDL_AUDIODRIVER='dummy', LIBGL_ALWAYS_SOFTWARE='1')
    command = [str(binary), str(root / 'resources/shaders/glsl/core.glsl'),
               str(root / 'tests/search-screen/reference-material.glsl')]
    bad = Path(temporary) / 'wrong-colors.glsl'
    reference = (root / 'tests/search-screen/reference-material.glsl').read_text()
    assert 'FragColor = color;' in reference
    bad.write_text(reference.replace('FragColor = color;', 'FragColor = color.bgra;'))
    profiles = [[]] if sys.platform == 'darwin' else [[], ['gles']]
    for profile in profiles:
        subprocess.run(command + profile, env=env, check=True)
        control = subprocess.run([str(binary), command[1], str(bad), *profile],
                                 env=env, capture_output=True, text=True)
        assert control.returncode != 0 and 'pixel mismatch' in control.stderr, control
        print('PASS: actual GPU rejects wrong-color material oracle', profile or ['desktop'])
