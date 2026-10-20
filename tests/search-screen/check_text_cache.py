#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Compile the actual CPU clipping method in isolation.
import pathlib
import shlex
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[2]
source = (root / 'es-core/src/resources/Font.cpp').read_text()
start = source.index('void TextCache::appendClipped(')
opening = source.index('{', start)
depth = 0
for end in range(opening, len(source)):
    depth += (source[end] == '{') - (source[end] == '}')
    if not depth:
        break
else:
    raise RuntimeError('Production text-cache method is not balanced')
with tempfile.TemporaryDirectory(prefix='esde-search-text-') as temporary:
    build = pathlib.Path(temporary)
    (build / 'text-cache.inc').write_text(source[start:end + 1] + '\n')
    flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', 'sdl2', 'freetype2', 'harfbuzz'], text=True))
    includes = ['es-core/src', 'external/glm', 'external/rapidjson/include',
                'external/rlottie/inc', 'external/utfcpp']
    command = ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-parameter', '-Wno-ignored-qualifiers']
    command += ['-I' + str(root / path) for path in includes]
    command += ['-I' + str(build), *flags, str(root / 'tests/search-screen/text-cache.cpp'),
                '-o', str(build / 'check')]
    subprocess.run(command, check=True)
    subprocess.run([str(build / 'check')], check=True)
