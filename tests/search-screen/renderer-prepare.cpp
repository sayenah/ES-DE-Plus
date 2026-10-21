//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  renderer-prepare.cpp
//
//  Written for ES-DE-Plus. Executes the production startup preparation against
//  counted materials, asserting that no search opening repeats or presents it.
//

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <glm/glm.hpp>
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

std::ostringstream messages;
#define LOG(level) messages
class Renderer
{
public:
#include "render-types.inc"
    inline static float width {1920}, height {1080};
    int panels {0}, finishes {0}, clears {0}, swaps {0};
    glm::mat4 matrix {0};
    static Renderer* getInstance()
    {
        static Renderer value;
        return &value;
    }
    static float getScreenWidth() { return width; }
    static float getScreenHeight() { return height; }
    void setMatrix(glm::mat4 value) { matrix = value; }
    void bindTexture(unsigned int value, unsigned int unit)
    {
        if (value || unit)
            std::abort();
    }
    void drawTriangleStrips(const Vertex* vertices,
                            unsigned int count,
                            BlendFactor source,
                            BlendFactor destination,
                            const VertexAttributes* attributes)
    {
        if (count != 4 || !attributes || vertices[0].shaders != Shader::SEARCH ||
            source != BlendFactor::ONE || destination != BlendFactor::ZERO)
            std::abort();
        ++panels;
    }
    void finishRendering() { ++finishes; }
    void clearBackground(unsigned int color)
    {
        if (finishes != 1 || color != 0x000000FF)
            std::abort();
        ++clears;
    }
    void swapBuffers() { ++swaps; }
};
struct TextCache {
    struct VertexList {
        std::vector<Renderer::Vertex> verts;
        std::vector<Renderer::VertexAttributes> attributes;
    };
    std::vector<VertexList> lists;
    auto& getVertexLists() { return lists; }
    glm::vec4 clip {1};
    void setClipRegion(glm::vec4 value) { clip = value; }
};
enum Alignment {
    ALIGN_LEFT
};

struct Font {
    inline static int warmups {0};
    TextCache* buildTextCache(const std::string& text,
                              float,
                              float,
                              float,
                              float,
                              float,
                              int,
                              unsigned int,
                              bool,
                              bool,
                              bool)
    {
        ++warmups;
        if (text.find("ABC") != 0 || text.find("xyz") == std::string::npos ||
            text.find("fi fl ff ffi ffl") == std::string::npos ||
            text.find("á") == std::string::npos)
            std::abort();
        return new TextCache {};
    }
    inline static int allocations {0}, draws {0};
    static std::string getDefaultPath() { return "menu.ttf"; }
    static std::shared_ptr<Font> get(float size, const std::string& path, int atlas)
    {
        if (size != 40 || path != "menu.ttf" || atlas != 1024)
            std::abort();
        ++allocations;
        return std::make_shared<Font>();
    }
    void renderTextCache(TextCache* cache)
    {
        if (cache->clip != glm::vec4 {0} || cache->lists.size() != 1 ||
            cache->lists[0].attributes.size() != 4 ||
            cache->lists[0].verts[0].shaders != Renderer::Shader::SEARCH)
            std::abort();
        ++draws;
    }
};
struct TextComponent {
    TextCache cache;
    TextComponent(const std::string& text, std::shared_ptr<Font> font, unsigned int color)
    {
        if (text == "A") {
            if (color != 0xFFFFFF80)
                std::abort();
            cache.lists.push_back({std::vector<Renderer::Vertex>(4), {}});
        }
        else {
            if (color != 0xFFFFFFFF)
                std::abort();
            delete font->buildTextCache(text, 0, 0, 0, 0, 1.15f, 0, color, false, false, false);
        }
    }
    const TextCache* getTextCache() { return &cache; }
};
struct ImageComponent {
    inline static std::vector<size_t> dimensions;
    inline static int draws {0};
    ImageComponent(bool dynamic, bool force)
    {
        if (dynamic || !force)
            std::abort();
    }
    void setLinearInterpolation(bool linear)
    {
        if (!linear)
            std::abort();
    }
    void setRawImage(const unsigned char* pixels, size_t width, size_t height)
    {
        if (!pixels || width != height || pixels[width * height * 4 - 1] != 255)
            std::abort();
        dimensions.push_back(width);
    }
    void setResize(size_t width, size_t height)
    {
        if (width != height)
            std::abort();
    }
    void setOpacity(float value)
    {
        if (value != 0.5f)
            std::abort();
    }
    void render(glm::mat4 matrix)
    {
        if (matrix != glm::mat4 {1})
            std::abort();
        ++draws;
        Renderer::getInstance()->matrix = glm::mat4 {0};
    }
};
#include "prepare-drawing.inc"

#include "search-alphabet.inc"
#include "search-glyph-prepare.inc"

struct SearchFonts {
    glm::vec2 screen;
    std::shared_ptr<Font> atlas;
    std::map<float, std::shared_ptr<Font>> fonts;
};
std::shared_ptr<SearchFonts> searchFonts()
{
    static auto owner = std::make_shared<SearchFonts>();
    return owner;
}
struct SearchArtwork {
    static constexpr size_t MAX_DIMENSION {384};
};
struct GuiSearch {
    static void prepareRenderer();
};
#include "renderer-prepare.inc"

int main()
{
    int checks {0};
    auto require = [&](bool condition) {
        if (!condition)
            std::abort();
        ++checks;
    };
    GuiSearch::prepareRenderer();
    auto* renderer = Renderer::getInstance();
    require(Font::allocations == 1 && Font::draws == 1);
    require(Font::warmups == 1);
    require(searchFonts()->atlas == searchFonts()->fonts.at(40));
    require(searchFonts()->screen == glm::vec2(1920, 1080));
    require(renderer->panels == 1 && ImageComponent::draws == 2);
    require(ImageComponent::dimensions == std::vector<size_t>({256, 384}));
    require(renderer->finishes == 1 && renderer->clears == 1 && renderer->swaps == 0);
    require(renderer->matrix == glm::mat4 {1});
    const auto log = messages.str();
    require(log.find("Search renderer prepared once: ms=") == 0);
    GuiSearch::prepareRenderer();
    require(renderer->finishes == 1 && renderer->clears == 1 && renderer->panels == 1);
    require(Font::allocations == 1 && Font::draws == 1 && ImageComponent::draws == 2);
    require(messages.str() == log);
    require(Font::warmups == 1);
    searchFonts()->fonts.clear();
    searchFonts()->atlas.reset();
    Renderer::width = 2560;
    Renderer::height = 1600;
    GuiSearch::prepareRenderer();
    require(!searchFonts()->atlas && Font::allocations == 1);
    require(renderer->finishes == 1 && renderer->clears == 1 && ImageComponent::draws == 2);
    require(renderer->swaps == 0 && messages.str() == log);
    require(Font::warmups == 1);
    std::printf("PASS: %d production once-per-process material preparation checks\n", checks);
}
