#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Compile the actual glyph-cache methods in isolation.
import pathlib
import shlex
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[2]
source = (root / 'es-core/src/resources/Font.cpp').read_text()
def method(marker):
    start = source.index(marker)
    opening = source.index('{', start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if not depth:
            return source[start:end + 1] + '\n'
    raise RuntimeError('Production font method is not balanced')

with tempfile.TemporaryDirectory(prefix='esde-search-text-') as temporary:
    build = pathlib.Path(temporary)
    methods = {'text-cache': 'void TextCache::appendClipped(',
               'glyph-cache': 'Font::Glyph* Font::getGlyphByIndex('}
    for name, marker in methods.items():
        (build / (name + '.inc')).write_text(method(marker))
    flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', 'sdl2', 'freetype2', 'harfbuzz'], text=True))
    includes = ['es-core/src', 'external/glm', 'external/rapidjson/include',
                'external/rlottie/inc', 'external/utfcpp']
    command = ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-parameter', '-Wno-ignored-qualifiers']
    command += ['-I' + str(root / path) for path in includes]
    command += ['-I' + str(build), *flags]
    for name in methods:
        subprocess.run(command + [str(root / ('tests/search-screen/' + name + '.cpp')),
                                  '-o', str(build / name)], check=True)
        subprocess.run([str(build / name)], check=True)
