//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  GuiSearch.h
//
//  Written for ES-DE-Plus. Full-screen live library search for controllers, keyboards and touch.
//

#ifndef ES_APP_GUIS_GUI_SEARCH_H
#define ES_APP_GUIS_GUI_SEARCH_H

#include "GuiComponent.h"
#include "components/ImageComponent.h"
#include "components/TextComponent.h"
#include "search/LibrarySearch.h"
#include "search/SearchArtwork.h"

class SystemData;

class GuiSearch : public GuiComponent
{
public:
    GuiSearch(const std::string& initialText = "", SystemData* scopeSystem = nullptr);
    ~GuiSearch();
    bool input(InputConfig* config, Input input) override;
    void textInput(const std::string& text, bool pasting = false) override;
    void textEditing(const std::string& text, int start, int length) override;
    void update(int deltaTime) override;
    void render(const glm::mat4& parentTrans) override;
    std::vector<HelpPrompt> getHelpPrompts() override;
#if defined(__ANDROID__)
    bool ownsTouch(float, float) override { return true; }
    bool nativeTouch(int type, int64_t finger, float x, float y) override;
    void cancelNativeTouch() override;
#endif

private:
    enum class Area {
        Field,
        Scope,
        Suggestions,
        Keys,
        Filters,
        History,
        Games,
        Close
    };
    struct Target {
        glm::vec4 rect;
        Area area;
        int index;
    };
    struct Label {
        std::unique_ptr<TextComponent> text;
        glm::vec4 rect;
        unsigned int background;
        bool border;
    };
    struct Cover {
        LibrarySearch::Handle handle;
        glm::vec4 rect;
        std::unique_ptr<ImageComponent> image;
        float opacity {0};
    };
    void refresh();
    void layout();
    void focus(Area area, int index = 0);
    void move(int x, int y);
    void activate();
    void typeKey();
    void cycleSystem(int direction);
    void applySuggestion();
    void openGame(bool play);
    void toggleFavorite();
    void record();
    void edit(const std::string& text);
    void startTextInput(bool touch);
    void close();
    void label(const std::string& value,
               const glm::vec4& rect,
               float fontSize,
               unsigned int color,
               unsigned int background = 0,
               bool border = false,
               Alignment align = ALIGN_LEFT);
    void target(
        const std::string& value, const glm::vec4& rect, Area area, int index, float fontSize);
    void title(const std::string& value,
               const std::vector<LibrarySearch::Span>& spans,
               const glm::vec4& rect,
               float fontSize);
    void cover(const LibrarySearch::Handle& handle, const glm::vec4& rect);
    void result(int index, const glm::vec4& rect, bool best);
    void requestArtwork();
    bool selected(Area area, int index) const;
    int count(Area area) const;
    std::vector<std::string> keys() const;
    LibrarySearch::Filter filter(bool system = true) const;

    Renderer* mRenderer;
    SearchArtwork mArtwork;
    std::vector<Label> mLabels;
    std::vector<Target> mTargets;
    std::vector<Cover> mCovers;
    std::vector<LibrarySearch::Match> mMatches;
    std::vector<LibrarySearch::Handle> mGames;
    std::vector<LibrarySearch::SystemCount> mSystems;
    std::vector<LibrarySearch::Suggestion> mSuggestions;
    std::vector<std::string> mHistory;
    std::vector<size_t> mRecent;
    std::vector<size_t> mFavorites;
    std::string mQuery;
    std::string mComposition;
    std::string mScopeName;
    std::string mScopeLabel;
    std::string mSystem;
    std::string mGenre;
    std::string mDeveloper;
    std::string mPublisher;
    std::string mMediaRoot;
    std::string mPreviousImeHint;
    std::string mPreviousKeyboardHint;
    size_t mCursor {0};
    size_t mTotal {0};
    size_t mLibraryCount {0};
    uint64_t mGeneration {0};
    Area mArea {Area::Keys};
    int mIndex {0};
    int mFirstGame {0};
    int mSuggestionOffset {0};
    bool mFavouritesOnly {false};
    bool mSymbols {false};
    bool mUppercase {false};
    bool mTouch {false};
    bool mPortrait {false};
    bool mNoResults {false};
    bool mDirty {true};
    int mBlink {0};
    float mUnit {0};
    float mContentBottom {0};
    int mVisibleRows {5};
    glm::vec4 mFieldRect {};
    glm::vec4 mResultsRect {};
#if defined(__ANDROID__)
    int64_t mFinger {-1};
    glm::vec2 mTouchStart {};
    glm::vec2 mTouchLast {};
    Target mTouchTarget {{}, Area::Field, -1};
    uint32_t mTouchTime {0};
    bool mTouchMoved {false};
#endif
};
#endif
