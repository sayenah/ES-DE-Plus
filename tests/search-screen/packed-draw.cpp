//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  packed-draw.cpp
//
//  Written for ES-DE-Plus. Execute production draw/font/attribute methods with
//  counted GL buffers, checking byte strides, shader switches and legacy fallback.
//
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <glm/glm.hpp>
#include <iostream>
#include <memory>
#include <vector>
#define GL_CHECK_ERROR(call) (call)
#define LOG(level) std::cerr
using GLint = int;
constexpr int GL_ARRAY_BUFFER {1}, GL_DYNAMIC_DRAW {2}, GL_TRIANGLE_STRIP {3};
constexpr int GL_FLOAT {4}, GL_UNSIGNED_BYTE {5}, GL_TRUE {1}, GL_FALSE {0};
std::vector<unsigned int> strides;
std::vector<uint8_t> uploaded;
unsigned int drawn {0};
void glBlendFunc(unsigned int, unsigned int) {}
void glBufferData(int, size_t size, const void* data, int)
{
    const auto* bytes = static_cast<const uint8_t*>(data);
    uploaded.assign(bytes, bytes + size);
}
void glDrawArrays(int mode, int first, unsigned int count)
{
    if (mode != GL_TRIANGLE_STRIP || first)
        std::abort();
    drawn = count;
}
void glVertexAttribPointer(
    int index, int count, int type, int normalized, unsigned int stride, const void* offset)
{
    const std::array<size_t, 3> offsets {0, 8, 16};
    if (index < 0 || index > 2 || count != (index == 2 ? 4 : 2) ||
        type != (index == 2 ? GL_UNSIGNED_BYTE : GL_FLOAT) ||
        normalized != (index == 2 ? GL_TRUE : GL_FALSE) ||
        reinterpret_cast<uintptr_t>(offset) != offsets[index])
        std::abort();
    strides.push_back(stride);
}
class Renderer
{
public:
#include "render-types.inc"
    virtual void drawTriangleStrips(const Vertex*,
                                    unsigned int,
                                    BlendFactor,
                                    BlendFactor,
                                    const VertexAttributes* = nullptr) = 0;
};
class ShaderOpenGL
{
public:
    int mShaderPosition {0}, mShaderTextureCoord {1}, mShaderColor {2};
    unsigned int flags {0};
    float opacity {0};
    void activateShaders() {}
    void setAttribPointers(unsigned int stride);
    void setModelViewProjectionMatrix(glm::mat4) {}
    void setTextureSamplers() {}
    void setTextureSize(std::array<float, 2>) {}
    void setClipRegion(glm::vec4) {}
    void setBrightness(float) {}
    void setOpacity(float value) { opacity = value; }
    void setSaturation(float) {}
    void setDimming(float) {}
    void setCornerRadius(float) {}
    void setReflectionsFalloff(float) {}
    void setBlurStrength(float) {}
    void setFlags(unsigned int value) { flags = value; }
};
#include "attribute-layout.inc"
class RendererOpenGL : public Renderer
{
public:
    std::shared_ptr<ShaderOpenGL> mCoreShader, mBlurHorizontalShader, mBlurVerticalShader,
        mScanlinelShader, mSearchShader, mLastShader;
    unsigned int mLastVertexStride {0};
    glm::mat4 mTrans {1};
    unsigned int boundTexture {0};
    std::shared_ptr<ShaderOpenGL> getShaderProgram(Shader)
    {
        return std::make_shared<ShaderOpenGL>();
    }
    unsigned int convertBlendFactor(BlendFactor value) { return static_cast<unsigned int>(value); }
    float getScreenWidth() { return 1920; }
    float getScreenHeight() { return 1080; }
    float getScreenResolutionModifier() { return 1; }
    void bindTexture(unsigned int value, unsigned int unit)
    {
        if (unit)
            std::abort();
        boundTexture = value;
    }
    void drawTriangleStrips(const Vertex*,
                            unsigned int,
                            BlendFactor,
                            BlendFactor,
                            const VertexAttributes* = nullptr) override;
};
#include "packed-draw.inc"
class Font;
#include "text-cache-class.inc"
class Font
{
public:
    RendererOpenGL* mRenderer;
    unsigned int flushes {0};
    void flushAtlas() { ++flushes; }
    void renderTextCache(TextCache* cache);
};
#include "font-render.inc"

int main()
{
    int checks {0};
    auto require = [&](bool condition) {
        if (!condition)
            std::abort();
        ++checks;
    };
    RendererOpenGL renderer;
    std::vector<Renderer::Vertex> vertices {{{0, 0}, {0, 0}, 0x12345678},
                                            {{0, 10}, {0, 1}, 0x12345678},
                                            {{20, 0}, {1, 0}, 0x12345678},
                                            {{20, 10}, {1, 1}, 0x12345678}};
    vertices[0].opacity = .37f;
    std::vector<Renderer::VertexAttributes> compact;
    for (const auto& vertex : vertices)
        compact.push_back({vertex.position, vertex.texcoord, vertex.color});
    require(sizeof(Renderer::VertexAttributes) < sizeof(Renderer::Vertex));
    for (auto shader : {Renderer::CORE, Renderer::BLUR_HORIZONTAL, Renderer::BLUR_VERTICAL,
                        Renderer::SCANLINES, Renderer::SEARCH}) {
        vertices[0].shaders = shader;
        renderer.mLastShader.reset();
        strides.clear();
        renderer.drawTriangleStrips(vertices.data(), 4, Renderer::BlendFactor::ONE,
                                    Renderer::BlendFactor::ZERO);
        require(uploaded.size() == vertices.size() * sizeof(Renderer::Vertex));
        require(drawn == 4 && strides.size() == 3 && strides.back() == sizeof(Renderer::Vertex));
        renderer.drawTriangleStrips(vertices.data(), 4, Renderer::BlendFactor::ONE,
                                    Renderer::BlendFactor::ZERO, compact.data());
        require(uploaded.size() == compact.size() * sizeof(Renderer::VertexAttributes));
        require(!std::memcmp(uploaded.data(), compact.data(), uploaded.size()));
        require(strides.size() == 6 && strides.back() == sizeof(Renderer::VertexAttributes));
        renderer.drawTriangleStrips(vertices.data(), 4, Renderer::BlendFactor::ONE,
                                    Renderer::BlendFactor::ZERO, compact.data());
        require(strides.size() == 6);
        renderer.drawTriangleStrips(vertices.data(), 4, Renderer::BlendFactor::ONE,
                                    Renderer::BlendFactor::ZERO);
        require(strides.size() == 9 && strides.back() == sizeof(Renderer::Vertex));
    }
    vertices[0].shaders = Renderer::CORE;
    vertices[0].shaderFlags = Renderer::FONT_TEXTURE;
    Font font {&renderer};
    unsigned int texture {42};
    TextCache cache;
    cache.setClipRegion({1, 2, 3, 4});
    cache.getVertexLists().push_back({vertices, &texture, compact});
    font.renderTextCache(&cache);
    require(font.flushes == 1 && renderer.boundTexture == 42);
    require(uploaded.size() == compact.size() * sizeof(Renderer::VertexAttributes));
    require(renderer.mCoreShader->flags == (Renderer::FONT_TEXTURE | Renderer::CLIPPING));
    require(renderer.mCoreShader->opacity == .37f);
    cache.getVertexLists()[0].attributes.pop_back();
    font.renderTextCache(&cache);
    require(font.flushes == 2 && uploaded.size() == vertices.size() * sizeof(Renderer::Vertex));
    cache.getVertexLists()[0].attributes.clear();
    font.renderTextCache(&cache);
    require(font.flushes == 3 && uploaded.size() == vertices.size() * sizeof(Renderer::Vertex));
    renderer.mSearchShader = renderer.mCoreShader;
    vertices[0].shaders = Renderer::SEARCH;
    renderer.drawTriangleStrips(vertices.data(), 4, Renderer::BlendFactor::ONE,
                                Renderer::BlendFactor::ZERO, compact.data());
    require(renderer.mLastShader == renderer.mCoreShader);
    require(renderer.mCoreShader->opacity == .37f);
    require(uploaded.size() == compact.size() * sizeof(Renderer::VertexAttributes));
    std::cout << "PASS: " << checks << " production packed/legacy draw checks\n";
}
