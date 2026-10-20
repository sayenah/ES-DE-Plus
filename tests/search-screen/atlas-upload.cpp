//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  atlas-upload.cpp
//
//  Written for ES-DE-Plus. Exercises production search-atlas staging, publishing,
//  shared cache pointers and context lifetime with counted GPU resource seams.
//

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <glm/glm.hpp>
#include <map>
#include <memory>
#include <vector>

class Renderer
{
public:
    enum class TextureType {
        RED
    };
    static Renderer* getInstance()
    {
        static Renderer value;
        return &value;
    }
    unsigned int next {1}, creates {0}, updates {0}, destroys {0};
    std::map<unsigned int, std::vector<uint8_t>> textures;
    std::map<unsigned int, glm::ivec2> sizes;
    unsigned int createTexture(unsigned int unit,
                               TextureType type,
                               bool minify,
                               bool magnify,
                               bool mipmap,
                               bool repeat,
                               unsigned int width,
                               unsigned int height,
                               void* data)
    {
        assert(unit == 0 && type == TextureType::RED && minify && magnify && !mipmap && !repeat);
        const auto id = next++;
        auto* pixels = static_cast<uint8_t*>(data);
        textures[id] = std::vector<uint8_t>(pixels, pixels + width * height);
        sizes[id] = {width, height};
        ++creates;
        return id;
    }
    void updateTexture(unsigned int id,
                       unsigned int,
                       TextureType,
                       unsigned int x,
                       unsigned int y,
                       unsigned int width,
                       unsigned int height,
                       void* data)
    {
        auto* pixels = static_cast<uint8_t*>(data);
        for (unsigned int row {0}; row < height; ++row)
            std::copy_n(pixels + row * width, width,
                        textures.at(id).data() + (y + row) * sizes.at(id).x + x);
        ++updates;
    }
    void destroyTexture(unsigned int id)
    {
        assert(textures.erase(id) == 1);
        sizes.erase(id);
        ++destroys;
    }
};
#include "search-atlas.inc"
class Font
{
public:
#include "font-texture-struct.inc"
    std::shared_ptr<Font> mAtlasOwner;
    std::vector<std::unique_ptr<FontTexture>> mTextures;
    void flushAtlas();
};
#include "font-atlas.inc"
#include "font-flush.inc"
#include "font-texture-deinit.inc"
#include "font-texture-destroy.inc"
#include "font-texture-init.inc"
#include "font-texture-update.inc"

int main()
{
    int checks {0};
    auto require = [&](bool condition, const char* message) {
        if (!condition) {
            std::fprintf(stderr, "FAIL: atlas upload %s\n", message);
            std::exit(1);
        }
        ++checks;
    };
    auto* renderer = Renderer::getInstance();
    {
        auto owner = std::make_shared<Font>();
        owner->mTextures.emplace_back(std::make_unique<Font::FontTexture>(10, 128));
        auto& texture = *owner->mTextures.front();
        texture.initTexture();
        require(texture.textureId == 0 && renderer->creates == 0 && renderer->updates == 0,
                "search allocation does not submit GPU work during entry/layout");
        unsigned int* cachedId = &texture.textureId;
        unsigned char glyph[] {1, 2, 3, 4, 5, 6};
        texture.update({3, 5}, {3, 2}, glyph);
        unsigned char white {255};
        for (int i {0}; i < 100; ++i)
            texture.update({i, 20}, {1, 1}, &white);
        require(renderer->creates == 0 && renderer->updates == 0,
                "all new glyphs remain CPU-only until the first draw");
        Font child;
        child.mAtlasOwner = owner;
        child.flushAtlas();
        require(renderer->creates == 1 && renderer->updates == 0 && child.mTextures.empty(),
                "a shared size publishes its owner's atlas once");
        require(*cachedId == 1 && renderer->textures.size() == 1,
                "existing shaped caches follow the first texture ID");
        auto expected = std::vector<uint8_t>(128 * 128, 0);
        std::copy_n(glyph, 3, expected.data() + 5 * 128 + 3);
        std::copy_n(glyph + 3, 3, expected.data() + 6 * 128 + 3);
        std::fill_n(expected.data() + 20 * 128, 100, 255);
        require(renderer->textures.at(*cachedId) == expected,
                "glyph rows, offsets and transparent margins survive the combined upload");
        child.flushAtlas();
        require(renderer->creates == 1 && renderer->destroys == 0,
                "unchanged frames reuse the same atlas");
        const auto previous = *cachedId;
        texture.update({100, 20}, {1, 1}, &white);
        expected[20 * 128 + 100] = 255;
        child.flushAtlas();
        require(*cachedId != previous && renderer->creates == 2 && renderer->destroys == 1,
                "new glyphs replace rather than update an in-flight texture");
        require(renderer->textures.at(*cachedId) == expected && renderer->updates == 0,
                "replacement retains earlier glyphs and never calls subimage upload");
        texture.deinitTexture();
        require(*cachedId == 0 && renderer->textures.empty(),
                "context unload releases the GPU texture");
        texture.initTexture();
        require(*cachedId == 0 && renderer->creates == 2,
                "context reload also defers GPU work until drawing");
        child.flushAtlas();
        require(*cachedId == 3 && renderer->textures.at(*cachedId) == expected,
                "unchanged CPU pixels restore a lost context without rerasterizing");
        owner->mTextures.emplace_back(std::make_unique<Font::FontTexture>(10, 128));
        owner->mTextures.back()->initTexture();
        owner->mTextures.back()->update({1, 1}, {1, 1}, &white);
        child.flushAtlas();
        require(renderer->creates == 4 && renderer->textures.size() == 2,
                "each overflow page publishes independently without replacing a clean page");
    }
    require(renderer->textures.empty() && renderer->destroys == 4,
            "all atlas pages are released with their owner");
    {
        Font::FontTexture ordinary {10};
        ordinary.initTexture();
        require(ordinary.textureId == 5 && renderer->creates == 5 && !ordinary.searchAtlas,
                "ordinary font allocation retains its immediate upload path");
        unsigned char white {255};
        ordinary.update({2, 3}, {1, 1}, &white);
        require(renderer->updates == 1 && renderer->textures.at(5)[3 * 60 + 2] == 255,
                "ordinary glyph updates retain their existing subimage behavior");
    }
    require(renderer->textures.empty() && renderer->destroys == 5,
            "ordinary fonts retain their existing destruction behavior");
    std::printf("PASS: %d production atlas upload/lifetime checks\n", checks);
}
