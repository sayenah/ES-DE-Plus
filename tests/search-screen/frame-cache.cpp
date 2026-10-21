//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  frame-cache.cpp
//
//  Written for ES-DE-Plus. Execute production frame capture/reuse/lifetime with
//  counted GL bindings, allocation failures, viewport changes and resource reloads.
//
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <set>
#include <string>
#include <vector>
#define GL_CHECK_ERROR(call) call
using GLint = int;
constexpr unsigned GL_READ_FRAMEBUFFER_BINDING = 1, GL_DRAW_FRAMEBUFFER_BINDING = 2,
                   GL_MAX_TEXTURE_SIZE = 3, GL_SAMPLES = 4, GL_READ_FRAMEBUFFER = 5,
                   GL_DRAW_FRAMEBUFFER = 6, GL_COLOR_ATTACHMENT0 = 7, GL_TEXTURE_2D = 8,
                   GL_FRAMEBUFFER_COMPLETE = 9, GL_COLOR_BUFFER_BIT = 10, GL_NEAREST = 11;
int readBinding {7}, drawBinding {11}, sizeLimit {4096}, samples {0};
bool complete {true}, allocateTexture {true};
unsigned nextName {20};
std::set<unsigned> textures, framebuffers;
std::vector<std::array<int, 10>> blits;
void glGetIntegerv(unsigned kind, int* value)
{
    *value = kind == GL_READ_FRAMEBUFFER_BINDING ? readBinding :
             kind == GL_DRAW_FRAMEBUFFER_BINDING ? drawBinding :
             kind == GL_SAMPLES                  ? samples :
                                                   sizeLimit;
}
void glGenFramebuffers(int, unsigned* id) { framebuffers.insert(*id = nextName++); }
void glBindFramebuffer(unsigned kind, unsigned id)
{
    (kind == GL_READ_FRAMEBUFFER ? readBinding : drawBinding) = id;
}
void glFramebufferTexture2D(unsigned kind, unsigned, unsigned, unsigned id, int)
{
    if (kind != GL_DRAW_FRAMEBUFFER || !textures.count(id) || !framebuffers.count(drawBinding))
        std::abort();
}
unsigned glCheckFramebufferStatus(unsigned) { return complete ? GL_FRAMEBUFFER_COMPLETE : 0; }
void glDeleteFramebuffers(int, const unsigned* id)
{
    if (!framebuffers.erase(*id))
        std::abort();
}
void glBlitFramebuffer(
    int a, int b, int c, int d, int e, int f, int g, int h, unsigned mask, unsigned filter)
{
    if (mask != GL_COLOR_BUFFER_BIT || filter != GL_NEAREST)
        std::abort();
    blits.push_back({a, b, c, d, e, f, g, h, readBinding, drawBinding});
}
struct IReloadable {
    virtual void unload(struct ResourceManager&) = 0;
    virtual void reload(struct ResourceManager&) = 0;
};
struct ResourceManager {
    std::vector<std::weak_ptr<IReloadable>> resources;
    static ResourceManager& getInstance()
    {
        static ResourceManager value;
        return value;
    }
    void addReloadable(std::shared_ptr<IReloadable> value) { resources.push_back(value); }
};
struct Renderer {
    struct FrameCache {
        unsigned texture {0}, framebuffer {0};
        int width {0}, height {0};
    };
    static Renderer* instance;
    static Renderer* getInstance() { return instance; }
    virtual bool captureFrame(FrameCache&) = 0;
    virtual bool drawFrameCache(const FrameCache&, unsigned int = 0) = 0;
    virtual void releaseFrameCache(FrameCache&) = 0;
    void beginErrorBatch() {}
    void endErrorBatch(const char*) {}
};
Renderer* Renderer::instance {nullptr};
class RendererOpenGL : public Renderer
{
public:
    enum class TextureType {
        RGBA
    };
    struct Rect {
        int x, y, w, h;
    };
    Rect mViewport {3, 5, 100, 80};
    int mWindowWidth {200}, mWindowHeight {200}, rotation {0};
    bool clipped {false};
    int getScreenRotation() { return rotation; }
    bool hasClipRect() { return clipped; }
    std::vector<unsigned int> cleared;
    void clearBackground(unsigned int color) { cleared.push_back(color); }
    unsigned createTexture(unsigned, TextureType, bool, bool, bool, bool, unsigned, unsigned, void*)
    {
        if (!allocateTexture)
            return 0;
        const auto id = nextName++;
        textures.insert(id);
        return id;
    }
    void destroyTexture(unsigned id)
    {
        if (!textures.erase(id))
            std::abort();
    }
    bool captureFrame(FrameCache&) override;
    bool drawFrameCache(const FrameCache&, unsigned int = 0) override;
    void releaseFrameCache(FrameCache&) override;
};
#include "error-batch.inc"
#include "frame-cache-methods.inc"
#include "frame-cache-owner.inc"
struct ImageComponent {
    bool linear {false};
    unsigned uploads {0};
    float opacity {0};
    ImageComponent(bool, bool) {}
    void setLinearInterpolation(bool value) { linear = value; }
    void setRawImage(unsigned char*, unsigned, unsigned) { ++uploads; }
    void setOpacity(float value) { opacity = value; }
};
struct GuiSearch {
    struct Cover {
        struct Handle {
            std::string id;
        } handle;
        std::unique_ptr<ImageComponent> image;
        float opacity {0};
    };
    struct Pixels {
        std::vector<unsigned char> rgba {255};
        unsigned width {1}, height {1};
    };
    struct Artwork {
        int gets {0};
        std::shared_ptr<Pixels> get(const std::string&)
        {
            ++gets;
            return std::make_shared<Pixels>();
        }
    } mArtwork;
    bool mMeasureFrame {false};
    Renderer* mRenderer {Renderer::getInstance()};
    std::vector<Cover> mCovers;
    std::shared_ptr<SearchFrameCache> mFrameCache;
    void updateArtwork(int deltaTime)
    {
        bool uploaded {false};
#include "frame-artwork.inc"
    }
};
int main()
{
    int checks {0};
    auto require = [&](bool value) {
        if (!value)
            std::abort();
        ++checks;
    };
    RendererOpenGL renderer;
    Renderer::instance = &renderer;
    Renderer::FrameCache frame;
    require(renderer.captureFrame(frame));
    require(frame.width == 100 && frame.height == 80 && textures.size() == 1 &&
            framebuffers.size() == 1);
    require(readBinding == 7 && drawBinding == 11);
    require(blits.back() == std::array<int, 10> {3, 115, 103, 195, 0, 0, 100, 80, 11,
                                                 static_cast<int>(frame.framebuffer)});
    const auto texture = frame.texture, buffer = frame.framebuffer;
    require(renderer.captureFrame(frame) && frame.texture == texture &&
            frame.framebuffer == buffer);
    require(renderer.drawFrameCache(frame));
    require(readBinding == 7 && drawBinding == 11);
    require(blits.back() ==
            std::array<int, 10> {0, 0, 100, 80, 3, 115, 103, 195, static_cast<int>(buffer), 11});
    renderer.rotation = 90;
    require(!renderer.captureFrame(frame) && !renderer.drawFrameCache(frame));
    renderer.rotation = 0;
    renderer.clipped = true;
    require(!renderer.captureFrame(frame) && !renderer.drawFrameCache(frame));
    renderer.clipped = false;
    renderer.mViewport.w = 120;
    require(!renderer.drawFrameCache(frame));
    require(renderer.captureFrame(frame));
    require(!textures.count(texture) && !framebuffers.count(buffer) && frame.width == 120);
    renderer.releaseFrameCache(frame);
    require(textures.empty() && framebuffers.empty() && !frame.texture && !frame.framebuffer);
    renderer.mViewport = {0, 0, 200, 200};
    const auto clears = renderer.cleared.size();
    require(renderer.captureFrame(frame) && renderer.drawFrameCache(frame, 0x12151CFF));
    require(renderer.cleared.size() == clears);
    renderer.mViewport = {3, 5, 120, 80};
    require(renderer.captureFrame(frame) && renderer.drawFrameCache(frame, 0x12151CFF));
    require(renderer.cleared.size() == clears + 1);
    require(renderer.cleared.back() == 0x12151CFF);
    renderer.releaseFrameCache(frame);
    require(textures.empty() && framebuffers.empty());
    renderer.mViewport.h = 0;
    require(!renderer.captureFrame(frame));
    renderer.mViewport.h = 80;
    samples = 4;
    require(!renderer.captureFrame(frame));
    samples = 0;
    sizeLimit = 10;
    require(!renderer.captureFrame(frame));
    sizeLimit = 4096;
    complete = false;
    require(!renderer.captureFrame(frame));
    require(readBinding == 7 && drawBinding == 11 && textures.empty() && framebuffers.empty());
    complete = true;
    allocateTexture = false;
    require(!renderer.captureFrame(frame));
    require(textures.empty() && framebuffers.empty());
    allocateTexture = true;
    auto owner = SearchFrameCache::create();
    require(!owner->valid() && !owner->draw());
    require(ResourceManager::getInstance().resources.size() == 1);
    owner->capture();
    require(owner->valid() && owner->draw());
    require(owner->savedFrames() == 1 && owner->reusedFrames() == 1 && !owner->unavailable());
    owner->invalidate();
    require(!owner->valid() && !owner->draw() && textures.size() == 1);
    owner->capture();
    require(owner->valid() && textures.size() == 1);
    owner->unload(ResourceManager::getInstance());
    require(textures.empty() && framebuffers.empty() && !owner->valid());
    owner->reload(ResourceManager::getInstance());
    owner->capture();
    require(owner->valid());
    owner->reset();
    require(owner->savedFrames() == 0 && owner->reusedFrames() == 0);
    renderer.clipped = true;
    owner->capture();
    require(!owner->valid());
    renderer.clipped = false;
    require(owner->unavailable());
    owner->capture();
    require(!owner->valid() && textures.empty());
    owner->reset();
    owner->capture();
    require(owner->valid());
    GuiSearch search;
    search.mFrameCache = owner;
    search.mCovers.push_back({{"one"}, nullptr, 0});
    search.mCovers.push_back({{"two"}, nullptr, 0});
    search.mMeasureFrame = true;
    search.updateArtwork(16);
    require(!search.mCovers[0].image && !search.mCovers[1].image && search.mArtwork.gets == 0);
    search.mMeasureFrame = false;
    search.updateArtwork(0);
    require(!owner->valid() && search.mCovers[0].image && !search.mCovers[1].image);
    require(search.mCovers[0].image->linear && search.mCovers[0].image->uploads == 1);
    owner->capture();
    search.updateArtwork(16);
    require(!owner->valid() && search.mCovers[1].image);
    owner->capture();
    search.updateArtwork(16);
    require(!owner->valid());
    search.mCovers[0].opacity = search.mCovers[1].opacity = 1;
    owner->capture();
    search.updateArtwork(16);
    require(owner->valid());
    require(search.mCovers[0].image->opacity == 1 && search.mCovers[1].image->opacity == 1);
    require(search.mArtwork.gets == 2);
    search.mFrameCache.reset();
    owner.reset();
    require(textures.empty() && framebuffers.empty());
    require(readBinding == 7 && drawBinding == 11);
    std::cout << "PASS: " << checks << " production frame cache/resource checks\n";
}
