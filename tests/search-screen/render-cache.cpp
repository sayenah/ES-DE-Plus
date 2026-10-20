//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  render-cache.cpp
//
//  Written for ES-DE-Plus. Exercises production font allocation and solid batching
//  with counted resource/texture seams, without an OpenGL context.
//

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <glm/glm.hpp>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <tuple>
#include <vector>

#define LOG(level) std::cerr

class Renderer
{
public:
    struct Vertex {
        glm::vec2 position, texcoord;
        unsigned int color;
    };
    enum class TextureType {
        RED
    };
    static int getScreenHeight() { return 1080; }
    static Renderer* getInstance()
    {
        static Renderer instance;
        return &instance;
    }
    void updateTexture(unsigned int texture,
                       int,
                       TextureType,
                       unsigned int x,
                       unsigned int y,
                       unsigned int width,
                       unsigned int height,
                       void* data)
    {
        ++uploads;
        lastTexture = texture;
        lastPosition = {x, y};
        validPixel = width == 1 && height == 1 && *static_cast<unsigned char*>(data) == 255;
    }
    int uploads {0};
    unsigned int lastTexture {0};
    glm::ivec2 lastPosition {};
    bool validPixel {false};
};
class Font;
class ResourceManager
{
public:
    static ResourceManager& getInstance()
    {
        static ResourceManager instance;
        return instance;
    }
    void addReloadable(const std::shared_ptr<Font>& font)
    {
        ++registrations;
        reloadables.emplace_back(font);
    }
    std::vector<std::weak_ptr<Font>> reloadables;
    int registrations {0};
};
namespace Utils::FileSystem
{
    std::string getCanonicalPath(const std::string& path)
    {
        return path == "missing.ttf" ? "" : path;
    }
} // namespace Utils::FileSystem
struct TextCache {
    struct VertexList {
        std::vector<Renderer::Vertex> verts;
        unsigned int* textureIdPtr;
    };
    std::vector<VertexList> vertexLists;
};
class Font
{
public:
    struct FontTexture {
        unsigned int textureId;
        int rowHeight;
        glm::ivec2 writePos, textureSize;
        FontTexture(int size, unsigned int atlasSize = 0);
        bool findEmpty(const glm::ivec2& size, glm::ivec2& cursorOut);
        void initTexture() { textureId = ++nextTexture; }
        static inline unsigned int nextTexture {0};
    };
    Font(float size,
         const std::string& path,
         unsigned int atlasSize,
         const std::shared_ptr<Font>& atlasOwner)
        : mAtlasSize {atlasSize}
        , mAtlasOwner {atlasOwner}
        , mPath {path}
        , mFontSize {size}
    {
    }
    static std::string getDefaultPath() { return "menu.ttf"; }
    static std::shared_ptr<Font> get(float size,
                                     const std::string& path = getDefaultPath(),
                                     unsigned int atlasSize = 0,
                                     const std::shared_ptr<Font>& atlasOwner = nullptr);
    void uploadSolidPixel();
    void appendSolid(TextCache* cache, const std::vector<Renderer::Vertex>& vertices);
    void getTextureForNewGlyph(const glm::ivec2&, FontTexture*& output, glm::ivec2& cursor);
    static inline std::map<std::tuple<float, std::string, unsigned int, const Font*>,
                           std::weak_ptr<Font>>
        sFontMap;
    Renderer* mRenderer {Renderer::getInstance()};
    const unsigned int mAtlasSize;
    const std::shared_ptr<Font> mAtlasOwner;
    std::vector<std::unique_ptr<FontTexture>> mTextures;
    FontTexture* mSolidTexture {nullptr};
    glm::ivec2 mSolidCursor {};
    std::string mPath;
    float mFontSize;
};

#include "font-allocate.inc"
#include "font-atlas.inc"
#include "font-find-empty.inc"
#include "font-get.inc"
#include "font-solid-upload.inc"
#include "font-solid.inc"

namespace
{
    int checks {0};
    void require(bool value, const char* reason)
    {
        ++checks;
        if (!value) {
            std::fprintf(stderr, "FAIL: render cache %s\n", reason);
            std::exit(1);
        }
    }
} // namespace
int main()
{
    auto ordinary = Font::get(26);
    auto search = Font::get(26, "menu.ttf", 1024);
    require(ordinary != search, "opt-in atlas never changes a cached ordinary font");
    require(Font::get(26) == ordinary && Font::get(26, "menu.ttf", 1024) == search,
            "both allocations cache independently");
    require(Font::FontTexture(26).textureSize == glm::ivec2 {156, 156},
            "ordinary texture dimensions are unchanged");
    require(Font::FontTexture(26, 1024).textureSize == glm::ivec2 {1024, 1024},
            "requested search atlas size");
    require(Font::FontTexture(300, 1024).textureSize == glm::ivec2 {1800, 1800},
            "an atlas request never reduces space for large glyphs");
    require(Font::get(26, "missing.ttf") == ordinary, "default font path fallback is unchanged");
    TextCache cache;
    search->appendSolid(&cache, {});
    require(cache.vertexLists.empty() && search->mTextures.empty(),
            "empty geometry does not allocate a texture");
    const std::vector<Renderer::Vertex> quad {{{0, 0}, {}, 0x123456FF},
                                              {{0, 10}, {}, 0x123456FF},
                                              {{10, 0}, {}, 0x123456FF},
                                              {{10, 10}, {}, 0x123456FF}};
    search->appendSolid(&cache, quad);
    auto* renderer = Renderer::getInstance();
    require(search->mTextures.size() == 1 && renderer->uploads == 1 && renderer->validPixel,
            "one opaque red texel allocated/uploaded");
    require(cache.vertexLists.size() == 1 && cache.vertexLists[0].verts.size() == 6,
            "solid quad uses one glyph-compatible strip");
    const auto expectedUV = glm::vec2 {1.5f / 1024, 1.5f / 1024};
    for (const auto& vertex : cache.vertexLists[0].verts)
        require(vertex.texcoord == expectedUV && vertex.color == 0x123456FF,
                "solid samples texel center and preserves color");
    require(cache.vertexLists[0].verts[1].position == quad.front().position &&
                cache.vertexLists[0].verts[4].position == quad.back().position,
            "solid preserves panel geometry");
    auto second = quad;
    for (auto& vertex : second) {
        vertex.position.x += 40;
        vertex.color = 0xABCDEF80;
    }
    search->appendSolid(&cache, second);
    require(search->mTextures.size() == 1 && renderer->uploads == 1 &&
                cache.vertexLists.size() == 1,
            "further panels reuse texel and draw batch");
    double area {0};
    const auto& vertices = cache.vertexLists.front().verts;
    for (size_t i {2}; i < vertices.size(); ++i) {
        const auto& a = vertices[i - 2];
        const auto& b = vertices[i - 1];
        const auto& c = vertices[i];
        const double triangle =
            std::abs((b.position.x - a.position.x) * (c.position.y - a.position.y) -
                     (b.position.y - a.position.y) * (c.position.x - a.position.x)) /
            2;
        if (triangle)
            require(a.color == b.color && b.color == c.color,
                    "no visible triangle joins unrelated panels");
        area += triangle;
    }
    require(area == 200, "two separated solids retain their exact total area");
    search->mTextures.front()->textureId = 99;
    search->uploadSolidPixel();
    require(renderer->uploads == 2 && renderer->lastTexture == 99 &&
                renderer->lastPosition == glm::ivec2 {1, 1} && renderer->validPixel &&
                *cache.vertexLists[0].textureIdPtr == 99,
            "context restoration rewrites the same texel and cache follows its new texture ID");
    auto child = Font::get(32, "menu.ttf", 1024, search);
    auto other = Font::get(40, "menu.ttf", 1024);
    require(child != Font::get(32, "menu.ttf", 1024),
            "shared fonts never alias an independent font of the same size");
    require(Font::get(32, "menu.ttf", 1024, search) == child &&
                Font::get(32, "menu.ttf", 1024, other) != child,
            "font cache distinguishes atlas owners");
    Font::FontTexture* texture {nullptr};
    glm::ivec2 cursor {};
    child->getTextureForNewGlyph({20, 30}, texture, cursor);
    require(texture == search->mTextures.front().get() && child->mTextures.empty() &&
                cursor == glm::ivec2 {3, 1},
            "different size glyphs allocate distinct regions in their owner's atlas");
    child->appendSolid(&cache, quad);
    require(cache.vertexLists.size() == 1 && child->mTextures.empty(),
            "shared font geometry merges into the same texture batch");
    auto& reloadables = ResourceManager::getInstance().reloadables;
    auto ownerPosition = std::find_if(reloadables.begin(), reloadables.end(),
                                      [&](const auto& font) { return font.lock() == search; });
    auto childPosition = std::find_if(reloadables.begin(), reloadables.end(),
                                      [&](const auto& font) { return font.lock() == child; });
    require(ownerPosition < childPosition,
            "owner texture initialization precedes child glyph restoration");
    std::weak_ptr<Font> lifetime = search;
    search.reset();
    require(!lifetime.expired(), "shared fonts retain their owner's texture lifetime");
    child.reset();
    require(lifetime.expired(), "atlas owner is released when its last child is released");
    std::printf("PASS: %d production render cache checks\n", checks);
}
