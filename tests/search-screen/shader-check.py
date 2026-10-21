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
                    str(root / 'tests/search-screen/shader-pixels.cpp'), *flags, *graphics,
                    '-o', str(binary)], check=True)
    env = dict(os.environ)
    if sys.platform != 'darwin':
        env.update(SDL_VIDEODRIVER='offscreen', SDL_AUDIODRIVER='dummy', LIBGL_ALWAYS_SOFTWARE='1')
    command = [str(binary), str(root / 'resources/shaders/glsl/core.glsl'),
               str(root / 'resources/shaders/glsl/search.glsl')]
    subprocess.run(command, env=env, check=True)
    if sys.platform != 'darwin':
        subprocess.run(command + ['gles'], env=env, check=True)
