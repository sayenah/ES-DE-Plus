//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  font-owner.cpp
//
//  Written for ES-DE-Plus. Exercises the production font owner and shaped-label cache.
//
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <glm/glm.hpp>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

struct PreparationClock {
    inline static std::chrono::steady_clock::time_point time {};
    static auto now() { return time; }
    static void work() { time += std::chrono::milliseconds {1}; }
};
struct Renderer {
    enum class BlendFactor {
        ONE,
        ZERO
    };
    static Renderer* getInstance()
    {
        static Renderer renderer;
        return &renderer;
    }
    static float getScreenWidth() { return 1920; }
    static float getScreenHeight() { return 1080; }
    void setMatrix(glm::mat4) {}
    void drawRect(int,
                  int,
                  int width,
                  int height,
                  unsigned int,
                  unsigned int,
                  bool,
                  int,
                  int,
                  BlendFactor,
                  BlendFactor)
    {
        if (width != 1 || height != 1)
            std::abort();
    }
};
struct ViewController {
    static void* getInstance() { return Renderer::getInstance(); }
};
struct Window {
    bool blocked {false};
    static Window* getInstance()
    {
        static Window window;
        return &window;
    }
    void* peekGui() { return blocked ? nullptr : ViewController::getInstance(); }
    bool isScreensaverActive() { return false; }
    bool isMediaViewerActive() { return false; }
    bool isPDFViewerActive() { return false; }
};
constexpr int SDL_FIRSTEVENT {0}, SDL_LASTEVENT {1};
bool inputWaiting {false};
bool SDL_HasEvents(int, int) { return inputWaiting; }
struct Output {
    template <typename T> Output& operator<<(T) { return *this; }
};
#define LOG(level)                                                                                 \
    Output {}
double threadCpuMilliseconds() { return -1; }
double elapsedThreadCpu(double) { return -1; }

struct ResourceManager;
struct IReloadable {
    virtual void unload(ResourceManager&) = 0;
    virtual void reload(ResourceManager&) = 0;
};
struct ResourceManager {
    std::weak_ptr<IReloadable> owner;
    static ResourceManager& getInstance()
    {
        static ResourceManager value;
        return value;
    }
    void addReloadable(std::weak_ptr<IReloadable> value) { owner = value; }
};
struct TextCache {
    size_t batches {0};
    size_t getBatchCount() const { return batches; }
};
namespace SearchDrawing
{
    void atlasSamples(TextCache& samples, const TextCache&) { samples.batches = 1; }
} // namespace SearchDrawing

struct Font {
    inline static int warmups {0};
    inline static int draws {0};
    std::string prepared;
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
        PreparationClock::work();
        prepared += text;
        return new TextCache {1};
    }
    float size;
    static std::string getDefaultPath() { return "menu.ttf"; }
    static std::shared_ptr<Font> get(float size,
                                     const std::string&,
                                     int,
                                     std::shared_ptr<Font> = {})
    {
        PreparationClock::work();
        auto font = std::make_shared<Font>();
        font->size = size;
        return font;
    }
    glm::vec2 sizeText(const std::string& text) { return {text.size() * size, size}; }
    void renderTextCache(TextCache* cache)
    {
        if (cache->getBatchCount() != 1)
            std::abort();
        ++draws;
        PreparationClock::work();
    }
};
enum Alignment {
    ALIGN_LEFT,
    ALIGN_CENTER
};
struct TextComponent {
    inline static int shaped {0};
    std::string value;
    std::shared_ptr<Font> font;
    glm::vec3 position;
    glm::vec2 size;
    TextCache cache {1};
    TextComponent(const std::string& text, std::shared_ptr<Font> f, unsigned int color)
        : font {f}
        , position {}
        , size {}
    {
        delete font->buildTextCache(text, 0, 0, 0, 0, 1.15f, 0, color, false, false, false);
    }
    TextComponent(const std::string& text,
                  std::shared_ptr<Font> f,
                  unsigned int,
                  Alignment,
                  Alignment,
                  glm::ivec2,
                  glm::vec3 p,
                  glm::vec2 s,
                  int,
                  float)
        : value {text}
        , font {f}
        , position {p}
        , size {s}
    {
        ++shaped;
    }
    void setFont(std::shared_ptr<Font> f) { font = f; }
    void setColor(unsigned int) {}
    void setHorizontalAlignment(Alignment) {}
    void setPosition(glm::vec3 p) { position = p; }
    void setSize(glm::vec2 s) { size = s; }
    void setText(const std::string& text) { value = text; }
    glm::vec3 getPosition() { return position; }
    const TextCache* getTextCache() { return &cache; }
};
// Extracted production definitions need their declarations in this order.
// clang-format off
#include "search-alphabet.inc"
#include "search-roles.inc"
#include "search-font-owner.inc"
#include "search-glyph-prepare.inc"
#include "search-next-character.inc"
#include "search-font-step.inc"
// clang-format on
class GuiSearch
{
public:
    struct Label {
        std::shared_ptr<TextComponent> text;
        glm::vec4 rect;
        unsigned int background;
        bool border;
        std::optional<unsigned int> textColor {};
        glm::vec2 position {};
        bool overlay {false};
    };
    glm::vec2 mSize {1920, 1080};
    float mUnit {1};
    std::map<float, std::shared_ptr<Font>> mFonts;
    std::shared_ptr<Font> mFontAtlas;
    std::map<std::pair<std::string, float>, glm::vec2> mSizeCache;
    std::map<std::tuple<std::string, float, float, float, Alignment>,
             std::shared_ptr<TextComponent>>
        mLabelCache;
    std::vector<Label> mLabels;
    std::shared_ptr<Font> searchFont(float size);
    static void releaseFonts();
    static void prepareRenderer(bool opening = false);
    glm::vec2 textSize(const std::string& text, float size);
    void label(const std::string&,
               const glm::vec4&,
               float,
               unsigned int,
               unsigned int = 0,
               bool = false,
               Alignment = ALIGN_LEFT,
               std::shared_ptr<TextComponent> = nullptr);
};
#include "search-font-release.inc"
#include "search-font.inc"
#include "search-label.inc"
#include "search-prepare.inc"
#include "search-size.inc"
int main()
{
    int checks {0};
    auto require = [&](bool condition) {
        if (!condition)
            std::abort();
        ++checks;
    };
    std::weak_ptr<Font> retained;
    int preparedWarmups {0};
    {
        GuiSearch first;
        retained = first.searchFont(32);
        require(first.searchFont(32) == retained.lock());
        require(searchFonts()->atlas == first.mFontAtlas);
        require(!searchFonts()->rolesPrepared && Font::warmups == 0);
        Window::getInstance()->blocked = true;
        GuiSearch::prepareRenderer();
        require(Font::warmups == 0);
        Window::getInstance()->blocked = false;
        inputWaiting = true;
        GuiSearch::prepareRenderer();
        require(Font::warmups == 0);
        inputWaiting = false;
        int chunks {0};
        while (!searchFonts()->rolesPrepared && chunks++ < 1000) {
            const auto start = PreparationClock::now();
            GuiSearch::prepareRenderer();
            // Two 1ms atomic tasks, then one real atlas sampling draw (also 1ms).
            require(PreparationClock::now() - start <= std::chrono::milliseconds {3});
        }
        require(chunks > 3 && chunks < 1000);
        require(searchFonts()->fonts.size() == 3 && searchFonts()->rolesPrepared);
        for (const auto& entry : searchFonts()->fonts) {
            require(entry.second->prepared.find("ABCDEFGHIJKLMNOPQRSTUVWXYZ") == 0);
            require(entry.second->prepared.find("á") != std::string::npos);
            require(entry.second->prepared.find("fi fl ff ffi ffl") != std::string::npos);
        }
        preparedWarmups = Font::warmups;
        const auto draws = Font::draws;
        GuiSearch::prepareRenderer();
        require(Font::draws == draws);
        GuiSearch::prepareRenderer(true);
        require(Font::draws == draws + 1 && Font::warmups == preparedWarmups);
    }
    require(!retained.expired());
    {
        GuiSearch second;
        require(second.searchFont(32) == retained.lock());
        require(Font::warmups == preparedWarmups);
        second.label("Final Fantasy VII", {0, 0, 600, 60}, 32, 0xFFFFFFFF);
        const int shaped = TextComponent::shaped;
        second.label("Final Fantasy VII", {300, 100, 600, 60}, 32, 0xFF0000FF);
        require(TextComponent::shaped == shaped);
        require(second.mLabels[0].position == glm::vec2(12, 0));
        require(second.mLabels[1].position == glm::vec2(312, 100));
        require(second.mLabels[0].textColor == 0xFFFFFFFF);
        require(second.mLabels[1].textColor == 0xFF0000FF);
        second.label("Final Fantasy VII", {0, 0, 600, 60}, 40, 0xFFFFFFFF);
        require(TextComponent::shaped == shaped + 1);
        require(Font::warmups == preparedWarmups);
        second.label("Final Fight", {0, 0, 600, 60}, 32, 0xFFFFFFFF);
        require(TextComponent::shaped == shaped + 2);
    }
    GuiSearch::releaseFonts();
    require(retained.expired());
    // Immediate opening completes unfinished title roles and samples before edit.
    GuiSearch::prepareRenderer(true);
    require(searchFonts()->rolesPrepared && searchFonts()->fonts.size() == 3);
    GuiSearch::releaseFonts();
    {
        GuiSearch first;
        retained = first.searchFont(32);
    }
    {
        GuiSearch resized;
        resized.mSize = {1280, 720};
        resized.mUnit = 720.0f / 1080;
        resized.searchFont(32 * resized.mUnit);
        require(retained.expired());
        retained = resized.mFontAtlas;
    }
    auto& manager = ResourceManager::getInstance();
    manager.owner.lock()->unload(manager);
    require(retained.expired() && searchFonts()->fonts.empty() && !searchFonts()->atlas);
    require(!searchFonts()->rolesPrepared);
    std::cout << "PASS: " << checks << " production font lifetime / shaped-label checks\n";
}
