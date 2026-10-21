//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  font-owner.cpp
//
//  Written for ES-DE-Plus. Exercises the production font owner and shaped-label cache.
//
#include <algorithm>
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
    float size;
    static std::string getDefaultPath() { return "menu.ttf"; }
    static std::shared_ptr<Font> get(float size,
                                     const std::string&,
                                     int,
                                     std::shared_ptr<Font> = {})
    {
        return std::make_shared<Font>(Font {size});
    }
    glm::vec2 sizeText(const std::string& text) { return {text.size() * size, size}; }
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
};
#include "search-alphabet.inc"
#include "search-font-owner.inc"
#include "search-glyph-prepare.inc"
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
    {
        GuiSearch first;
        retained = first.searchFont(32);
        require(first.searchFont(32) == retained.lock());
        require(searchFonts()->atlas == first.mFontAtlas);
        require(searchFonts()->fonts.size() == 3 && searchFonts()->rolesPrepared);
        require(Font::warmups == 3);
    }
    require(!retained.expired());
    {
        GuiSearch second;
        require(second.searchFont(32) == retained.lock());
        require(Font::warmups == 3);
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
        require(Font::warmups == 3);
        second.label("Final Fight", {0, 0, 600, 60}, 32, 0xFFFFFFFF);
        require(TextComponent::shaped == shaped + 2);
    }
    GuiSearch::releaseFonts();
    require(retained.expired());
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
