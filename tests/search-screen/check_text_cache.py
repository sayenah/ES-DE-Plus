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
    methods = {'glyph-cache': 'Font::Glyph* Font::getGlyphByIndex(',
               'font-get': 'std::shared_ptr<Font> Font::get(',
               'font-atlas': 'Font::FontTexture::FontTexture(',
               'font-allocate': 'void Font::getTextureForNewGlyph(',
               'font-find-empty': 'bool Font::FontTexture::findEmpty(',
               'font-solid-upload': 'void Font::uploadSolidPixel(',
               'font-solid': 'void Font::appendSolid('}
    methods.update({
        'font-texture-init': 'void Font::FontTexture::initTexture(',
        'font-texture-update': 'void Font::FontTexture::update(',
        'font-texture-deinit': 'void Font::FontTexture::deinitTexture(',
        'font-texture-destroy': 'Font::FontTexture::~FontTexture(',
        'font-flush': 'void Font::flushAtlas('})
    header = (root / 'es-core/src/resources/Font.h').read_text()
    (build / 'font-texture-struct.inc').write_text(method('struct FontTexture', header) + ';\n')
    atlas = (root / 'es-core/src/resources/SearchFontAtlas.h').read_text()
    (build / 'search-atlas.inc').write_text(method('class SearchFontAtlas\n', atlas) + ';\n')
    for name, marker in methods.items():
        (build / (name + '.inc')).write_text(method(marker))
    artwork = (root / 'es-app/src/search/SearchArtwork.cpp').read_text()
    for name in ['request', 'pump', 'get']:
        marker = ('std::shared_ptr<const SearchArtwork::Pixels> ' if name == 'get' else 'void ')
        (build / ('artwork-' + name + '.inc')).write_text(
            method(marker + 'SearchArtwork::' + name + '(', artwork))
    search = (root / 'es-app/src/guis/GuiSearch.cpp').read_text()
    (build / 'search-font-owner.inc').write_text(
        method('struct SearchFonts final', search) + ';\n' +
        method('std::shared_ptr<SearchFonts> searchFonts()', search))
    for name, marker in [('font', 'std::shared_ptr<Font> GuiSearch::searchFont('),
                         ('font-release', 'void GuiSearch::releaseFonts('),
                         ('label', 'void GuiSearch::label('),
                         ('size', 'glm::vec2 GuiSearch::textSize(')]:
        (build / ('search-' + name + '.inc')).write_text(method(marker, search))
    (build / 'search-glyph-prepare.inc').write_text(method('void prepareSearchGlyphs(', search))
    (build / 'search-alphabet.inc').write_text(method('constexpr char searchAlphabet', search) + ';\n')
    (build / 'renderer-prepare.inc').write_text(method('void GuiSearch::prepareRenderer(', search))
    (build / 'search-render.inc').write_text(method('void GuiSearch::render(', search))
    renderer = (root / 'es-core/src/renderers/RendererOpenGL.cpp').read_text()
    (build / 'search-clear.inc').write_text(method('void RendererOpenGL::clearBackground(', renderer))
    (build / 'search-text-input.inc').write_text(method('void GuiSearch::startTextInput(', search))
    (build / 'search-text-resume.inc').write_text(
        method('if (mWindow->peekGui() == this && !SDL_IsTextInputActive())', search))
    shader = (root / 'es-core/src/renderers/ShaderOpenGL.cpp').read_text()
    shader_header = (root / 'es-core/src/renderers/ShaderOpenGL.h').read_text()
    (build / 'shader-class.inc').write_text(
        method('class ShaderOpenGL\n', shader_header).replace('private:', 'public:') + ';\n')
    start = shader.index('ShaderOpenGL::ShaderOpenGL(')
    constructor = shader[start:shader.index('\n}\n', start) + 3]
    shader_methods = ['ShaderOpenGL::~ShaderOpenGL(', 'bool ShaderOpenGL::createProgram(',
                     'void ShaderOpenGL::deleteProgram(', 'void ShaderOpenGL::getVariableLocations(',
                     'void ShaderOpenGL::activateShaders(']
    shader_methods += ['void ShaderOpenGL::' + name + '(' for name in [
        'setModelViewProjectionMatrix', 'setTextureSamplers', 'setTextureSize', 'setClipRegion',
        'setBrightness', 'setOpacity', 'setSaturation', 'setDimming', 'setCornerRadius',
        'setReflectionsFalloff', 'setBlurStrength', 'setFlags']]
    (build / 'shader-methods.inc').write_text(constructor + '\n' +
        '\n'.join(method(marker, shader) for marker in shader_methods))
    batch = (root / 'es-core/src/renderers/RenderErrorBatch.h').read_text()
    (build / 'error-batch.inc').write_text(method('class RenderErrorBatch\n', batch) + ';\n')
    (build / 'error-backend.inc').write_text(
        method('void RendererOpenGL::beginErrorBatch(', renderer) +
        method('void RendererOpenGL::endErrorBatch(', renderer))
    start = shader_header.index('#if !defined(NDEBUG)\n#define GL_CHECK_ERROR')
    (build / 'error-check.inc').write_text(shader_header[start:shader_header.index('\nclass ShaderOpenGL', start)])
    renderer_header = (root / 'es-core/src/renderers/Renderer.h').read_text()
    types = ['enum class BlendFactor', 'enum Shader {', 'enum ShaderFlags {',
             'struct VertexAttributes {', 'struct Vertex {']
    (build / 'render-types.inc').write_text('\n'.join(method(marker, renderer_header) + ';' for marker in types))
    (build / 'text-cache-class.inc').write_text(method('class TextCache\n', header) + ';\n')
    (build / 'packed-draw.inc').write_text(method('void RendererOpenGL::drawTriangleStrips(', renderer))
    (build / 'attribute-layout.inc').write_text(method('void ShaderOpenGL::setAttribPointers(', shader))
    (build / 'font-render.inc').write_text(method('void Font::renderTextCache('))
    (build / 'font-cache-color.inc').write_text(method('void TextCache::setColor('))
    drawing = (root / 'es-app/src/search/SearchDrawing.h').read_text()
    drawing_methods = ['inline std::vector<Renderer::VertexAttributes> attributes(',
                       'inline void pack(', 'inline void polygon(', 'inline void rectangle(']
    (build / 'prepare-drawing.inc').write_text('namespace SearchDrawing {\n' +
        '\n'.join(method(marker, drawing) for marker in drawing_methods) + '\n}\n')
    (build / 'shader-loader.inc').write_text(method('bool RendererOpenGL::loadShaders(', renderer))
    frame_source = (root / 'es-core/src/renderers/SearchFrame.cpp').read_text()
    frame_header = (root / 'es-app/src/search/SearchFrameCache.h').read_text()
    (build / 'frame-cache-methods.inc').write_text('\n'.join(method(marker, frame_source) for marker in [
        'bool RendererOpenGL::captureFrame(', 'bool RendererOpenGL::drawFrameCache(',
        'void RendererOpenGL::releaseFrameCache(']))
    (build / 'frame-cache-owner.inc').write_text(method('class SearchFrameCache final', frame_header) + ';\n')
    update = search[search.index('void GuiSearch::update('):]
    (build / 'frame-artwork.inc').write_text(method('for (auto& cover : mCovers)', update))

    flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', 'sdl2', 'freetype2', 'harfbuzz'], text=True))
    includes = ['es-core/src', 'es-app/src', 'external/glm', 'external/rapidjson/include',
                'external/rlottie/inc', 'external/utfcpp']
    command = ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-parameter', '-Wno-ignored-qualifiers']
    command += ['-I' + str(root / path) for path in includes]
    command += ['-I' + str(build), *flags]
    for name in ['text-cache', 'glyph-cache', 'panel-cache', 'render-cache', 'artwork-cache', 'text-input', 'font-owner', 'render-state', 'atlas-upload', 'renderer-prepare', 'shader-state', 'error-batch', 'geometry-cache', 'packed-draw', 'shader-loader', 'frame-cache']:
        subprocess.run(command + ['-pthread', str(root / ('tests/search-screen/' + name + '.cpp')),
                                  '-o', str(build / name)], check=True)
        subprocess.run([str(build / name)], check=True)
        if name == 'error-batch':
            for variant in ['USE_OPENGLES', 'NDEBUG']:
                subprocess.run(command + ['-D' + variant, '-pthread',
                    str(root / 'tests/search-screen/error-batch.cpp'), '-o', str(build / variant)], check=True)
                subprocess.run([str(build / variant)], check=True)
