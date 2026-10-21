//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  render-state.cpp
//
//  Written for ES-DE-Plus. Executes the production search render pass and clear operation
//  with counted rendering seams; verifies transform, animation and GL-state ownership.
//

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <vector>

#define LOG(level) std::cerr
#define GL_CHECK_ERROR(call) call

namespace
{
    int checks {0};
    void require(bool condition)
    {
        if (!condition)
            std::abort();
        ++checks;
    }
    double threadCpuMilliseconds() { return 0; }
    double elapsedThreadCpu(double) { return 0; }
    std::array<long, 4> threadSchedule() { return {}; }
    std::array<long, 4> scheduleDelta(const std::array<long, 4>&) { return {}; }
    int64_t traceNanoseconds(std::chrono::steady_clock::time_point) { return 0; }
    std::vector<std::array<float, 4>> clearColors;
    std::vector<unsigned int> clearMasks;
    constexpr unsigned int GL_COLOR_BUFFER_BIT {0x4000};
    void glClearColor(float r, float g, float b, float a) { clearColors.push_back({r, g, b, a}); }
    void glClear(unsigned int mask) { clearMasks.push_back(mask); }
} // namespace

class RendererOpenGL
{
public:
    void clearBackground(unsigned int color);
};
#include "search-clear.inc"

struct TextCache {
    int identity;
    size_t getBatchCount() const { return 1; }
};
struct Renderer {
    enum class BlendFactor {
        ONE,
        ZERO
    };
    struct VertexAttributes {
    };
    struct Vertex {
        glm::vec2 position;
    };
    struct Event {
        std::string kind;
        glm::mat4 matrix;
    };
    glm::mat4 matrix {1};
    std::vector<Event> events;
    unsigned int texture {99};
    int rotation {0};
    int getScreenRotation() { return rotation; }
    void beginErrorBatch() {}
    void endErrorBatch(const char*) {}
    void setMatrix(const glm::mat4& value) { matrix = value; }
    void clearBackground(unsigned int color)
    {
        require(color == 0x12151CFF);
        events.push_back({"clear", matrix});
    }
    void bindTexture(unsigned int value, unsigned int unit)
    {
        require(unit == 0);
        texture = value;
    }
    void drawRect(float x,
                  float y,
                  float width,
                  float height,
                  unsigned int color,
                  unsigned int end,
                  bool gradient,
                  float opacity,
                  float dimming,
                  BlendFactor source,
                  BlendFactor destination)
    {
        require(x == 0 && y == 0 && width == 1920 && height == 1080);
        require(color == 0x12151CFF && end == color && !gradient && opacity == 1 && dimming == 1);
        require(source == BlendFactor::ONE && destination == BlendFactor::ZERO);
        events.push_back({"rectangle", matrix});
    }
    void drawTriangleStrips(const Vertex*,
                            unsigned int count,
                            BlendFactor source,
                            BlendFactor destination,
                            const VertexAttributes*)
    {
        require(count == 4 && texture == 0);
        require(source == BlendFactor::ONE && destination == BlendFactor::ZERO);
        events.push_back({"panels", matrix});
    }
};
#include "error-batch.inc"

struct Font {
    Renderer* renderer;
    void renderTextCache(TextCache* cache)
    {
        renderer->events.push_back({cache->identity == 1 ? "text" : "border", renderer->matrix});
    }
};
struct ImageComponent {
    Renderer* renderer;
    glm::vec2 size {60, 100};
    glm::vec3 position {};
    void setMaxSize(float, float) {}
    glm::vec2 getSize() { return size; }
    void setPosition(float x, float y) { position = {x, y, 0}; }
    void render(const glm::mat4& parent)
    {
        renderer->setMatrix(glm::translate(parent, position));
        renderer->events.push_back({"cover", renderer->matrix});
    }
};
struct FakeFrameCache {
    Renderer* renderer {nullptr};
    bool ready {false}, drawAllowed {true};
    int captures {0};
    unsigned int savedFrames() const { return captures; }
    unsigned int reusedFrames() const { return 0; }
    bool unavailable() const { return false; }
    bool valid() const { return ready; }
    void invalidate() { ready = false; }
    bool draw(unsigned int)
    {
        if (!ready || !drawAllowed)
            return false;
        renderer->events.push_back({"cached", renderer->matrix});
        return true;
    }
    void capture()
    {
        ++captures;
        ready = true;
    }
};
class GuiSearch
{
public:
    struct Cover {
        glm::vec4 rect;
        std::unique_ptr<ImageComponent> image;
        float opacity {1};
    };
    Renderer* mRenderer;
    std::shared_ptr<FakeFrameCache> mFrameCache {std::make_shared<FakeFrameCache>()};
    bool mDirty {false}, mMeasureFrame {false}, mMeasurePresentation {false};
    glm::mat4 transform {1};
    glm::vec2 mSize {1920, 1080};
    unsigned int mBackground {0x12151CFF};
    TextCache mTextBatch {1}, mBorderBatch {2};
    std::map<float, std::shared_ptr<Font>> mFonts;
    std::vector<Renderer::Vertex> mPanelBatch {4};
    std::vector<Renderer::VertexAttributes> mPanelAttributes {4};
    std::vector<Cover> mCovers;
    double mQueryWorkMs {0};
    std::string mPresentedQuery;
    glm::mat4 getTransform() { return transform; }
    void layout()
    {
        mDirty = false;
        mFrameCache->invalidate();
    }
    std::string queryForLog() { return "test"; }
    void render(const glm::mat4& parent);
};
#include "search-render.inc"

int main()
{
    RendererOpenGL backend;
    const std::vector<std::pair<unsigned int, std::array<float, 4>>> examples {
        {0x12151CFFU, {18 / 255.0f, 21 / 255.0f, 28 / 255.0f, 1}},
        {0xEFEFEFFFU, {239 / 255.0f, 239 / 255.0f, 239 / 255.0f, 1}},
        {0x12345678U, {18 / 255.0f, 52 / 255.0f, 86 / 255.0f, 120 / 255.0f}}};
    for (const auto& [color, expected] : examples) {
        clearColors.clear();
        clearMasks.clear();
        backend.clearBackground(color);
        require(clearColors.size() == 2 &&
                clearMasks == std::vector<unsigned int> {GL_COLOR_BUFFER_BIT});
        require(clearColors.front() == expected);
        require(clearColors.back() == std::array<float, 4> {0, 0, 0, 1});
    }
    for (bool animated : {false, true}) {
        Renderer renderer;
        GuiSearch search;
        search.mRenderer = &renderer;
        search.mFrameCache->renderer = &renderer;
        search.mFonts[26] = std::make_shared<Font>(Font {&renderer});
        search.mCovers.push_back({{20, 30, 120, 180}, std::make_unique<ImageComponent>()});
        search.mCovers.back().image->renderer = &renderer;
        if (animated)
            search.transform =
                glm::scale(glm::translate(glm::mat4 {1}, {100, 50, 0}), glm::vec3 {.75f});
        search.render(glm::mat4 {1});
        require(renderer.events.size() == 5);
        require(renderer.events[0].kind == (animated ? "rectangle" : "clear"));
        require(renderer.events[1].kind == "panels" && renderer.events[2].kind == "text");
        require(renderer.events[3].kind == "cover" && renderer.events[4].kind == "border");
        require(renderer.events[3].matrix != search.transform);
        require(renderer.events[4].matrix == search.transform);
        require(renderer.events[0].matrix == search.transform &&
                renderer.events[1].matrix == search.transform);
    }
    Renderer renderer;
    GuiSearch search;
    search.mRenderer = &renderer;
    search.mFrameCache->renderer = &renderer;
    search.mFonts[26] = std::make_shared<Font>(Font {&renderer});
    search.render(glm::mat4 {1});
    require(search.mFrameCache->captures == 1);
    renderer.events.clear();
    search.render(glm::mat4 {1});
    require(renderer.events.size() == 1 && renderer.events.back().kind == "cached");
    require(search.mFrameCache->captures == 1);
    renderer.events.clear();
    search.mMeasureFrame = true;
    search.render(glm::mat4 {1});
    require(renderer.events.size() == 4 && renderer.events.back().kind == "border");
    require(search.mFrameCache->captures == 1 && search.mMeasurePresentation);
    renderer.events.clear();
    search.mDirty = true;
    search.render(glm::mat4 {1});
    require(renderer.events.size() == 4 && renderer.events.back().kind == "border");
    require(search.mFrameCache->captures == 2);
    renderer.events.clear();
    renderer.rotation = 90;
    search.render(glm::mat4 {1});
    require(renderer.events.size() == 4 && search.mFrameCache->captures == 2);
    renderer.rotation = 0;
    search.mFrameCache->invalidate();
    search.mCovers.push_back({{20, 30, 120, 180}, std::make_unique<ImageComponent>(), .5f});
    search.mCovers.back().image->renderer = &renderer;
    renderer.events.clear();
    search.render(glm::mat4 {1});
    require(renderer.events.size() == 5 && search.mFrameCache->captures == 2);
    search.mCovers.back().opacity = 1;
    search.render(glm::mat4 {1});
    require(search.mFrameCache->captures == 3);
    renderer.events.clear();
    search.mFrameCache->drawAllowed = false;
    search.render(glm::mat4 {1});
    require(renderer.events.size() == 5 && renderer.events.back().kind == "border");
    std::cout << "PASS: " << checks << " production render/clear-state checks\n";
}
