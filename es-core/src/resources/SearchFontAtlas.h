//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchFontAtlas.h
//
//  Written for ES-DE-Plus. Stage search glyphs on the CPU and publish one
//  complete atlas before drawing, without modifying a texture still used by an
//  earlier frame.
//

#ifndef ES_CORE_RESOURCES_SEARCH_FONT_ATLAS_H
#define ES_CORE_RESOURCES_SEARCH_FONT_ATLAS_H

#include "renderers/Renderer.h"

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <vector>

class SearchFontAtlas
{
public:
    explicit SearchFontAtlas(glm::ivec2 size)
        : mSize {size}
        , mPixels(static_cast<size_t>(size.x) * size.y, 0)
    {
    }

    void update(glm::ivec2 cursor, glm::ivec2 size, const unsigned char* pixels)
    {
        assert(cursor.x >= 0 && cursor.y >= 0 && cursor.x + size.x <= mSize.x &&
               cursor.y + size.y <= mSize.y);
        for (int row {0}; row < size.y; ++row)
            std::copy_n(pixels + row * size.x, size.x,
                        mPixels.data() + (cursor.y + row) * mSize.x + cursor.x);
        mDirty = true;
    }

    void flush(unsigned int& textureId)
    {
        if (!mDirty && textureId)
            return;
        auto* renderer = Renderer::getInstance();
        const auto previous = textureId;
        // Cache geometry holds the address of textureId, so existing UVs and
        // shaped text follow the replacement without rebuilding their caches.
        textureId = renderer->createTexture(0, Renderer::TextureType::RED, true, true, false, false,
                                            mSize.x, mSize.y, mPixels.data());
        if (previous)
            renderer->destroyTexture(previous);
        mDirty = false;
    }

private:
    glm::ivec2 mSize;
    std::vector<uint8_t> mPixels;
    bool mDirty {true};
};

#endif // ES_CORE_RESOURCES_SEARCH_FONT_ATLAS_H
