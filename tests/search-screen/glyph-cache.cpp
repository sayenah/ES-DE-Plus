//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  glyph-cache.cpp
//
//  Written for ES-DE-Plus. Executes the production glyph-cache method against
//  deterministic font metrics and a counted texture-upload seam, without OpenGL.
//

#include <cstdio>
#include <cstdlib>
#include <glm/glm.hpp>
#include <iostream>
#include <map>
#include <string>
#include <tuple>

using hb_font_t = int;
constexpr int FT_LOAD_RENDER {0};
struct Slot {
    struct {
        unsigned int width {5}, rows {8};
        unsigned char* buffer {nullptr};
    } bitmap;
    struct {
        int vertAdvance {640}, horiBearingX {64}, horiBearingY {512};
    } metrics;
};
using FT_GlyphSlot = Slot*;
struct Face {
    Slot slot;
    FT_GlyphSlot glyph {&slot};
};
using FT_Face = Face*;
int FT_Load_Glyph(FT_Face, unsigned int, int) { return 0; }
#define LOG(level) std::cerr

class Renderer
{
public:
    enum class TextureType {
        RED
    };
    unsigned int uploads {0};
    void updateTexture(unsigned int, int, TextureType, int, int, int, int, unsigned char*)
    {
        ++uploads;
    }
};
class Font
{
public:
    struct FontTexture {
        unsigned int textureId {1};
        glm::ivec2 textureSize {128, 128};
        Renderer* renderer {nullptr};
        void update(const glm::ivec2& cursor, const glm::ivec2& size, unsigned char* pixels)
        {
            renderer->updateTexture(textureId, 0, Renderer::TextureType::RED, cursor.x, cursor.y,
                                    size.x, size.y, pixels);
        }
    } texture;
    struct Glyph {
        FontTexture* texture;
        hb_font_t* fontHB;
        glm::vec2 texPos, texSize;
        glm::ivec2 advance, bearing;
        int rows;
    };
    struct GlyphTexture {
        FontTexture* texture;
        glm::ivec2 cursor;
    };
    Font(Renderer* renderer)
        : mRenderer {renderer}
    {
        texture.renderer = renderer;
    }
    Glyph* getGlyphByIndex(unsigned int id, hb_font_t* fontArg, int xAdvance);
    FT_Face* getFaceForGlyphIndex(unsigned int, hb_font_t* fontArg, hb_font_t** returned)
    {
        *returned = fontArg;
        return &face;
    }
    void getTextureForNewGlyph(const glm::ivec2&, FontTexture*& result, glm::ivec2& cursor)
    {
        result = &texture;
        cursor = {allocations++ * 8, 0};
    }
    Renderer* mRenderer;
    std::string mPath {"test font"};
    float mFontSize {20};
    Face storage;
    FT_Face face {&storage};
    int allocations {0};
    std::map<std::tuple<unsigned int, hb_font_t*, int>, Glyph> mGlyphMapByIndex;
    std::map<std::pair<unsigned int, hb_font_t*>, GlyphTexture> mGlyphTextureMap;
};

#include "glyph-cache.inc"

void require(bool condition, const char* message)
{
    if (!condition) {
        std::fprintf(stderr, "FAIL: glyph cache %s\n", message);
        std::exit(1);
    }
}
int main()
{
    Renderer renderer;
    hb_font_t primary {1}, fallback {2};
    Font font {&renderer};
    const auto first = font.getGlyphByIndex(1, &primary, 10);
    require(renderer.uploads == 1 && first->advance.x == 10, "first bitmap is uploaded");
    const auto kerned = font.getGlyphByIndex(1, &primary, 12);
    require(first != kerned && kerned->advance.x == 12 && first->advance.x == 10,
            "kerning retains independent advance records");
    require(renderer.uploads == 1 && font.allocations == 1,
            "kerning reuses existing pixels without another GPU upload");
    require(first->texture == kerned->texture && first->texPos == kerned->texPos &&
                first->texSize == kerned->texSize,
            "kerning shares the same atlas region");
    require(font.getGlyphByIndex(1, &primary, 12) == kerned && renderer.uploads == 1,
            "identical request remains cached");
    font.getGlyphByIndex(2, &primary, 10);
    require(renderer.uploads == 2, "a different glyph still uploads its bitmap");
    font.getGlyphByIndex(1, &fallback, 10);
    require(renderer.uploads == 3, "fallback font keeps a distinct bitmap");
    Font otherSize {&renderer};
    otherSize.mFontSize = 30;
    otherSize.getGlyphByIndex(1, &primary, 12);
    require(renderer.uploads == 4, "another font size keeps its own atlas");
    std::puts("PASS: 8 production glyph-cache upload/advance checks");
}
