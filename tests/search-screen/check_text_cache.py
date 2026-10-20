#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Compile production rendering/artwork methods in isolation.
import pathlib
import shlex
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[2]
source = (root / 'es-core/src/resources/Font.cpp').read_text()
def method(marker, source=source):
    start = source.index(marker)
    opening = source.index('{', start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if not depth:
            return source[start:end + 1] + '\n'
    raise RuntimeError('Production method is not balanced')

with tempfile.TemporaryDirectory(prefix='esde-search-text-') as temporary:
    build = pathlib.Path(temporary)
    methods = {'text-cache': 'void TextCache::appendClipped(',
               'glyph-cache': 'Font::Glyph* Font::getGlyphByIndex(',
               'font-get': 'std::shared_ptr<Font> Font::get(',
               'font-atlas': 'Font::FontTexture::FontTexture(',
               'font-allocate': 'void Font::getTextureForNewGlyph(',
               'font-find-empty': 'bool Font::FontTexture::findEmpty(',
               'font-solid-upload': 'void Font::uploadSolidPixel(',
               'font-solid': 'void Font::appendSolid('}
    for name, marker in methods.items():
        (build / (name + '.inc')).write_text(method(marker))
    artwork = (root / 'es-app/src/search/SearchArtwork.cpp').read_text()
    for name in ['request', 'pump', 'get']:
        marker = ('std::shared_ptr<const SearchArtwork::Pixels> ' if name == 'get' else 'void ')
        (build / ('artwork-' + name + '.inc')).write_text(
            method(marker + 'SearchArtwork::' + name + '(', artwork))
    search = (root / 'es-app/src/guis/GuiSearch.cpp').read_text()
    (build / 'search-text-input.inc').write_text(method('void GuiSearch::startTextInput(', search))
    (build / 'search-text-resume.inc').write_text(
        method('if (mWindow->peekGui() == this && !SDL_IsTextInputActive())', search))
    flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', 'sdl2', 'freetype2', 'harfbuzz'], text=True))
    includes = ['es-core/src', 'es-app/src', 'external/glm', 'external/rapidjson/include',
                'external/rlottie/inc', 'external/utfcpp']
    command = ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-parameter', '-Wno-ignored-qualifiers']
    command += ['-I' + str(root / path) for path in includes]
    command += ['-I' + str(build), *flags]
    for name in ['text-cache', 'glyph-cache', 'panel-cache', 'render-cache', 'artwork-cache', 'text-input']:
        subprocess.run(command + ['-pthread', str(root / ('tests/search-screen/' + name + '.cpp')),
                                  '-o', str(build / name)], check=True)
        subprocess.run([str(build / name)], check=True)
