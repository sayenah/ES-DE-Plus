//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  GuiSearch.cpp
//
//  Written for ES-DE-Plus. Implements the Founder-approved D-028 search screen using
//  upstream rendering, game-list navigation and normal game launching.
//

#include "guis/GuiSearch.h"

#include "CollectionSystemsManager.h"
#include "FileData.h"
#include "FileFilterIndex.h"
#include "InputManager.h"
#include "Log.h"
#include "Settings.h"
#include "SystemData.h"
#include "Window.h"
#include "guis/GuiMsgBox.h"
#include "guis/SearchEntry.h"
#include "search/SearchDrawing.h"
#include "search/SearchPresentation.h"
#include "utils/FileSystemUtil.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"
#include "utils/TimeUtil.h"
#include "views/GamelistView.h"
#include "views/ViewController.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <set>
#include <sstream>
#if defined(__ANDROID__)
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>
#endif

namespace
{
    using PreparationClock = std::chrono::steady_clock;
    constexpr std::array<float, 3> searchRoles {40, 32, 26};
    constexpr char searchAlphabet[] {
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 "
        "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ fi fl ff ffi ffl "
        "áàâäãåæçéèêëíìîïñóòôöõøœúùûüßÁÀÂÄÃÅÆÇÉÈÊËÍÌÎÏÑÓÒÔÖÕØŒÚÙÛÜẞ ★ · › … ‘ ’"};

    void prepareSearchGlyphs(const std::shared_ptr<Font>& font,
                             const std::string& text,
                             TextCache& samples)
    {
        // Use the real title shaping path without changing the font's line height.
        TextComponent glyphs {text, font, 0xFFFFFFFF};
        if (const auto* cache = glyphs.getTextCache())
            SearchDrawing::atlasSamples(samples, *cache);
    }

    // ResourceManager unloads this owner before the GL context is destroyed. Keep
    // fonts (and their shared atlas) alive between screens, never across a reload.
    struct SearchFonts final : IReloadable {
        std::map<float, std::shared_ptr<Font>> fonts;
        std::shared_ptr<Font> atlas;
        glm::vec2 screen {};
        bool rolesPrepared {false};
        size_t role {0};
        size_t glyph {0};
        TextCache samples {};
        void unload(ResourceManager&) override
        {
            samples = {};
            fonts.clear();
            atlas.reset();
            rolesPrepared = false;
            role = 0;
            glyph = 0;
        }
        void reload(ResourceManager&) override {}
        void step();
    };
    std::shared_ptr<SearchFonts> searchFonts()
    {
        static auto owner = [] {
            auto value = std::make_shared<SearchFonts>();
            ResourceManager::getInstance().addReloadable(value);
            return value;
        }();
        return owner;
    }
#if defined(__ANDROID__)
    class SearchOptions : public GuiMsgBox
    {
    public:
        using GuiMsgBox::GuiMsgBox;
        // Search owns the entire surface, including the area outside its modal.
        bool ownsTouch(float, float) override { return true; }
    };
#endif
    std::array<long, 4> threadSchedule()
    {
#if defined(__ANDROID__)
        // Per-thread switches/faults need no filesystem reads on the UI thread.
        rusage value {};
        if (Log::getReportingLevel() >= LogDebug && getrusage(RUSAGE_THREAD, &value) == 0)
            return {value.ru_nvcsw, value.ru_nivcsw, value.ru_minflt, value.ru_majflt};
#endif
        return {-1, -1, -1, -1};
    }
    std::array<long, 4> scheduleDelta(const std::array<long, 4>& start)
    {
        auto end = threadSchedule();
        for (size_t i {0}; i < end.size(); ++i)
            end[i] = start[i] < 0 || end[i] < 0 ? -1 : end[i] - start[i];
        return end;
    }
    int64_t traceNanoseconds(std::chrono::steady_clock::time_point value)
    {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(value.time_since_epoch())
            .count();
    }
    double threadCpuMilliseconds()
    {
#if defined(__ANDROID__)
        timespec value {};
        if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &value) == 0)
            return value.tv_sec * 1000.0 + value.tv_nsec / 1000000.0;
#endif
        return -1.0;
    }
    double elapsedThreadCpu(double start)
    {
        const auto end = threadCpuMilliseconds();
        return start < 0 || end < 0 ? -1.0 : end - start;
    }
    [[maybe_unused]] bool contains(const glm::vec4& rect, float x, float y)
    {
        return x >= rect.x && y >= rect.y && x < rect.x + rect.z && y < rect.y + rect.w;
    }
    size_t previousCharacter(const std::string& text, size_t cursor)
    {
        if (cursor)
            --cursor;
        while (cursor && (static_cast<unsigned char>(text[cursor]) & 0xC0) == 0x80)
            --cursor;
        return cursor;
    }
    size_t nextCharacter(const std::string& text, size_t cursor)
    {
        if (cursor < text.size())
            ++cursor;
        while (cursor < text.size() && (static_cast<unsigned char>(text[cursor]) & 0xC0) == 0x80)
            ++cursor;
        return cursor;
    }
    void SearchFonts::step()
    {
        const float unit = std::min(screen.x, screen.y) / 1080;
        const float key = std::max(2.0f, std::round(searchRoles[role] * unit / 2) * 2);
        auto& font = fonts[key];
        if (!font) {
            if (!atlas)
                atlas = Font::get(key, Font::getDefaultPath(), 1024);
            const float atlasKey = std::max(2.0f, std::round(40 * unit / 2) * 2);
            font = key == atlasKey ? atlas : Font::get(key, Font::getDefaultPath(), 1024, atlas);
            return;
        }
        const std::string alphabet {searchAlphabet};
        if (glyph < alphabet.size()) {
            const auto end = nextCharacter(alphabet, glyph);
            prepareSearchGlyphs(font, alphabet.substr(glyph, end - glyph), samples);
            glyph = end;
        }
        else {
            // Individual UTF-8 codepoints keep each idle task small; also shape the
            // contextual Latin ligatures that occur in result titles.
            prepareSearchGlyphs(font, "fi fl ff ffi ffl", samples);
            glyph = 0;
            rolesPrepared = ++role == searchRoles.size();
        }
    }
    std::string kindLabel(LibrarySearch::SuggestionKind kind)
    {
        using Kind = LibrarySearch::SuggestionKind;
        switch (kind) {
            case Kind::Word:
                return _("word");
            case Kind::Title:
                return _("title");
            case Kind::Series:
                return _("series");
            case Kind::Developer:
                return _("developer");
            case Kind::Publisher:
                return _("publisher");
            case Kind::Genre:
                return _("genre");
            case Kind::System:
                return _("system");
        }
        return {};
    }
} // namespace

void GuiSearch::prepareRenderer(bool opening)
{
    // Idle preparation pauses while a modal/search/viewer owns the surface or
    // new input is waiting. All GL work stays on the existing rendering thread.
    if (!opening && (Window::getInstance()->peekGui() != ViewController::getInstance() ||
                     Window::getInstance()->isScreensaverActive() ||
                     Window::getInstance()->isMediaViewerActive() ||
                     Window::getInstance()->isPDFViewerActive() ||
                     SDL_HasEvents(SDL_FIRSTEVENT, SDL_LASTEVENT)))
        return;
    const glm::vec2 screen {Renderer::getScreenWidth(), Renderer::getScreenHeight()};
    auto owner = searchFonts();
    if (owner->screen != screen) {
        owner->unload(ResourceManager::getInstance());
        owner->screen = screen;
    }
    if (owner->rolesPrepared && !opening)
        return;
    const auto start = PreparationClock::now();
    const auto cpuStart = threadCpuMilliseconds();
    size_t tasks {0};
    do {
        if (owner->rolesPrepared)
            break;
        owner->step();
        ++tasks;
    } while (opening || PreparationClock::now() - start < std::chrono::milliseconds {2});
    if (owner->atlas && owner->samples.getBatchCount()) {
        auto* renderer = Renderer::getInstance();
        renderer->setMatrix(glm::mat4 {1});
        // Actually sample every prepared atlas so deferred driver/upload work is
        // paid before typing. No synthetic textures, fences or app-wide GL changes.
        owner->atlas->renderTextCache(&owner->samples);
        // swapBuffers() has just cleared the back buffer. Restore its one pixel;
        // opening also runs before the screen's first normal full-surface render.
        renderer->drawRect(0, 0, 1, 1, 0x000000FF, 0x000000FF, false, 1, 1,
                           Renderer::BlendFactor::ONE, Renderer::BlendFactor::ZERO);
    }
    const double milliseconds =
        std::chrono::duration<double, std::milli>(PreparationClock::now() - start).count();
    LOG(LogDebug) << "Search preparation chunk: phase=" << (opening ? "opening" : "idle")
                  << " work_ms=" << milliseconds << " cpu_ms=" << elapsedThreadCpu(cpuStart)
                  << " tasks=" << tasks << " ready=" << owner->rolesPrepared
                  << " atlases=" << owner->samples.getBatchCount();
    static bool reported {false};
    if (owner->rolesPrepared && !reported) {
        reported = true;
        LOG(LogDebug) << "Search renderer prepared once: chunked=1";
    }
}

GuiSearch::GuiSearch(const std::string& initialText, SystemData* scopeSystem)
    : mRenderer {Renderer::getInstance()}
    , mQuery {initialText}
    , mMediaRoot {FileData::getMediaDirectory()}
    , mCursor {initialText.size()}
{
    const auto scheme = Settings::getInstance()->getString("MenuColorScheme");
    if (scheme == "light") {
        mBackground = mMenuColorFrame;
        mPanel = 0xFFFFFFFF;
        mRaised = 0xE3E6EEFF;
        mForeground = 0x171A22FF;
        mMuted = 0x5A6072FF;
        mAccent = 0xB86A12FF;
        mFocusInk = 0xFFFFFFFF;
    }
    else if (scheme == "darkred") {
        mAccent = mMenuColorKeyboardModifier;
        mFocusInk = 0xFFFFFFFF;
    }
    if (const auto value = SDL_GetHint(SDL_HINT_IME_SHOW_UI))
        mPreviousImeHint = value;
    if (const auto value = SDL_GetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD))
        mPreviousKeyboardHint = value;
    setSize(Renderer::getScreenWidth(), Renderer::getScreenHeight());
    if (scopeSystem && !scopeSystem->isCollection()) {
        mScopeName = scopeSystem->getName();
        mScopeLabel = scopeSystem->getFullName();
    }
    // Opening from a game list offers its scope, while the initial scope is always global.
    mTouch = InputManager::getInstance().lastInputWasTouch();
#if defined(__ANDROID__)
    LOG(LogDebug) << "Search timing thread: tid=" << gettid();
#endif
    // Android commits text on its UI thread, even while this thread loads fonts/layout.
    // Enable events first so a quick keystroke after Y is retained in SDL's queue.
    // Browsing may already have queued text after the event that opened search.
    // Do not stop text input here: doing so would flush those later commits.
    SDL_SetHint(SDL_HINT_IME_SHOW_UI, "1");
    SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, "0");
    SDL_StartTextInput();
    refresh();
    layout();
    // Even an empty/private zero state prepares the best-card and row-title
    // glyphs and samples their atlases before SDL can deliver the first edit.
    SearchDrawing::atlasSamples(searchFonts()->samples, mTextBatch);
    prepareRenderer(true);
    const SDL_Rect rect {static_cast<int>(mFieldRect.x), static_cast<int>(mFieldRect.y),
                         static_cast<int>(mFieldRect.z), static_cast<int>(mFieldRect.w)};
    // Updating the IME rectangle must not stop text input and flush pending commits.
    SDL_SetTextInputRect(&rect);
    SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, mTouch ? "1" : "0");
    SDL_StartTextInput();
    LOG(LogDebug) << "Search screen opened: query=" << queryForLog() << " scope=" << mScopeName;
    if (Log::getReportingLevel() >= LogDebug)
        SearchPresentation::observe([this](double interval, double swap) {
            if (mMeasurePresentation) {
                LOG(LogDebug) << "Search presented: query=" << mPresentedQuery
                              << " interval_ms=" << interval << " swap_ms=" << swap
                              << " cause=" << (mPresentedKeystroke ? "keystroke" : "refresh");
                mMeasurePresentation = false;
            }
        });
}

GuiSearch::~GuiSearch()
{
    SearchPresentation::observe({});
    SDL_StopTextInput();
    if (mPreviousImeHint.empty())
        SDL_ResetHint(SDL_HINT_IME_SHOW_UI);
    else
        SDL_SetHint(SDL_HINT_IME_SHOW_UI, mPreviousImeHint.c_str());
    if (mPreviousKeyboardHint.empty())
        SDL_ResetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD);
    else
        SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, mPreviousKeyboardHint.c_str());
    LOG(LogDebug) << "Search screen closed";
}

LibrarySearch::Filter GuiSearch::filter(bool system) const
{
    auto value = LibrarySearch::currentFilter();
    if (system)
        value.system = mSystem;
    value.genre = mGenre;
    value.developer = mDeveloper;
    value.publisher = mPublisher;
    value.favouritesOnly = mFavouritesOnly;
    return value;
}

bool GuiSearch::zeroState() const
{
    return mQuery.empty() && mSystem.empty() && mGenre.empty() && mDeveloper.empty() &&
           mPublisher.empty() && !mFavouritesOnly;
}

void GuiSearch::refresh(bool preserveFocus)
{
    if (mUnit > 0 && !mMeasureFrame) {
        mQueryWorkMs = 0;
        mMeasureFrame = true;
    }
    const auto start = std::chrono::steady_clock::now();
    const auto cpuStart = threadCpuMilliseconds();
    const auto scheduleStart = threadSchedule();
    const std::string oldGame =
        preserveFocus && mArea == Area::Games ?
            (mIndex >= 0 && mIndex < static_cast<int>(mGames.size()) ? mGames[mIndex].id :
                                                                       mPendingGame) :
            "";
    if (mArea != Area::Games) {
        mFirstGame = 0;
        mOffset = 0;
    }
    const auto& engine = LibrarySearch::engine();
    const auto engineReady = std::chrono::steady_clock::now();
    const bool changed = mGeneration != LibrarySearch::currentGeneration();
    mGeneration = LibrarySearch::currentGeneration();
    mLoading = !LibrarySearch::ready();
    mPendingGame = mLoading ? oldGame : "";
    mHistory = LibrarySearch::history().queries();
    const auto historyReady = std::chrono::steady_clock::now();
    mSuggestions = engine.suggest(mQuery, 6, filter());
    const auto suggestionsReady = std::chrono::steady_clock::now();
    mSuggestionOffset =
        std::min(mSuggestionOffset, std::max(0, static_cast<int>(mSuggestions.size()) - 1));
    if (changed)
        mLibraryCount = engine.query("", 1, LibrarySearch::currentFilter()).total;
    const auto response =
        engine.query(mQuery, mSystem.empty() ? mResultLimit : 0, filter(false),
                     mSystem.empty() ? mOffset : 0, mSystem.empty() ? oldGame : "");
    mTotal = response.total;
    mSystems = response.systems;
    if (mSystem.empty()) {
        mMatches = response.matches;
        mMatchTotal = response.total;
        mOffset = response.offset;
    }
    else {
        const auto scoped = engine.query(mQuery, mResultLimit, filter(), mOffset, oldGame);
        mMatches = scoped.matches;
        mMatchTotal = scoped.total;
        mOffset = scoped.offset;
    }
    const auto matchesReady = std::chrono::steady_clock::now();
    mGames.clear();
    mRecent.clear();
    mFavorites.clear();
    mNoResults = !mLoading && mMatches.empty() &&
                 (!mQuery.empty() || !mSystem.empty() || !mGenre.empty() || !mDeveloper.empty() ||
                  !mPublisher.empty() || mFavouritesOnly);
    if (zeroState()) {
        mOffset = 0;
        const bool remember =
            Settings::getInstance()->getBool("SearchHistory") && !filter().kidMode;
        if (remember)
            mRecent = engine.recentlyPlayed(5, filter());
        auto favorites = filter();
        favorites.favouritesOnly = true;
        mFavorites = engine.browse(5, favorites);
        for (size_t i : mRecent)
            mGames.push_back(LibrarySearch::handle(i, mGeneration));
        for (size_t i : mFavorites)
            mGames.push_back(LibrarySearch::handle(i, mGeneration));
        mMatches.clear();
    }
    else {
        if (mNoResults) {
            mOffset = 0;
            mMatches = engine.closest(mQuery, 3, filter());
            if (mSuggestions.empty())
                for (const auto& match : mMatches)
                    mSuggestions.push_back(
                        {LibrarySearch::SuggestionKind::Title, engine.game(match.index).title});
        }
        for (const auto& match : mMatches)
            mGames.push_back(LibrarySearch::handle(match.index, mGeneration));
    }
    const auto old = std::find_if(mGames.begin(), mGames.end(),
                                  [&](const auto& handle) { return handle.id == oldGame; });
    if (old != mGames.end())
        mIndex = static_cast<int>(old - mGames.begin());
    else if (mArea == Area::Games) {
        mIndex = 0;
        mFirstGame = 0;
        if (mGames.empty() && !mLoading) {
            mArea = mTouch ? Area::Field : Area::Keys;
            updateHelpPrompts();
        }
    }
    else
        mIndex = std::max(0, std::min(mIndex, count(mArea) - 1));
    mDirty = true;
    const auto schedule = scheduleDelta(scheduleStart);
    const double cpuMilliseconds = elapsedThreadCpu(cpuStart);
    const auto end = std::chrono::steady_clock::now();
    const double milliseconds = std::chrono::duration<double, std::milli>(end - start).count();
    if (mMeasureFrame)
        mQueryWorkMs += milliseconds;
    else
        mQueryWorkMs = milliseconds;
    LOG(LogDebug)
        << "Search keystroke: query=" << queryForLog() << " results=" << mTotal
        << " query_bytes=" << mQuery.size() << " search_ms=" << milliseconds
        << " search_cpu_ms=" << cpuMilliseconds
        << " engine_ms=" << std::chrono::duration<double, std::milli>(engineReady - start).count()
        << " history_ms="
        << std::chrono::duration<double, std::milli>(historyReady - engineReady).count()
        << " suggest_ms="
        << std::chrono::duration<double, std::milli>(suggestionsReady - historyReady).count()
        << " matches_ms="
        << std::chrono::duration<double, std::milli>(matchesReady - suggestionsReady).count()
        << " start_ns=" << traceNanoseconds(start) << " end_ns=" << traceNanoseconds(end)
        << " voluntary_switches=" << schedule[0] << " involuntary_switches=" << schedule[1]
        << " minor_faults=" << schedule[2] << " major_faults=" << schedule[3];
}

std::shared_ptr<Font> GuiSearch::searchFont(float size)
{
    // Retain the small set of font sizes across layouts. Font's upstream map holds weak
    // references; destroying every label would otherwise reload fonts on each keystroke.
    // Preserve each size's glyph metrics while sharing one atlas/draw batch. Keep
    // smaller fitted fonts available when a translated control needs them.
    const float nominal = size / mUnit;
    const float grouped = nominal < 24 ? size :
                          nominal < 30 ? 26 * mUnit :
                          nominal < 36 ? 32 * mUnit :
                                         40 * mUnit;
    const float key = std::max(2.0f, std::round(grouped / 2) * 2);
    const float atlasKey = std::max(2.0f, std::round(40 * mUnit / 2) * 2);
    auto owner = searchFonts();
    if (owner->screen != mSize) {
        owner->unload(ResourceManager::getInstance());
        owner->screen = mSize;
    }
    if (!owner->atlas)
        owner->atlas = Font::get(atlasKey, Font::getDefaultPath(), 1024);
    mFontAtlas = owner->atlas;
    auto& font = owner->fonts[key];
    if (!font) {
        font =
            key == atlasKey ? mFontAtlas : Font::get(key, Font::getDefaultPath(), 1024, mFontAtlas);
    }
    mFonts[key] = font;
    return font;
}

void GuiSearch::releaseFonts() { searchFonts()->unload(ResourceManager::getInstance()); }

glm::vec2 GuiSearch::textSize(const std::string& value, float size)
{
    const auto key = std::make_pair(value, size);
    const auto found = mSizeCache.find(key);
    if (found != mSizeCache.end())
        return found->second;
    if (mSizeCache.size() >= 1024)
        mSizeCache.clear();
    return mSizeCache.emplace(key, searchFont(size)->sizeText(value)).first->second;
}

void GuiSearch::label(const std::string& value,
                      const glm::vec4& rect,
                      float fontSize,
                      unsigned int color,
                      unsigned int background,
                      bool border,
                      Alignment align,
                      std::shared_ptr<TextComponent> text)
{
    if (!value.empty()) {
        const glm::vec3 position {rect.x + 12 * mUnit, rect.y, 0};
        const glm::vec2 size {std::max(1.0f, rect.z - 24 * mUnit), rect.w};
        if (!text) {
            const auto key = std::make_tuple(value, fontSize, size.x, size.y, align);
            if (mLabelCache.size() >= 512)
                mLabelCache.clear();
            auto& cached = mLabelCache[key];
            if (!cached)
                cached = std::make_shared<TextComponent>(value, searchFont(fontSize), color, align,
                                                         ALIGN_CENTER, glm::ivec2 {0, 0}, position,
                                                         size, 0, 1.15f);
            text = cached;
            text->setPosition(position);
            text->setColor(color);
        }
        else {
            text->setFont(searchFont(fontSize));
            text->setColor(color);
            text->setHorizontalAlignment(align);
            text->setPosition(position);
            text->setSize(size);
            text->setText(value);
        }
    }
    const glm::vec2 position = text ? glm::vec2 {text->getPosition()} : glm::vec2 {};
    mLabels.push_back({std::move(text), rect, background, border, color, position});
}

bool GuiSearch::selected(Area area, int index) const { return mArea == area && mIndex == index; }

void GuiSearch::target(
    const std::string& value, const glm::vec4& rect, Area area, int index, float fontSize)
{
    const bool active = selected(area, index);
    // Preserve shaped control text across query/focus changes. The keyboard and
    // unchanged chips must not shape and allocate their text again on every keystroke.
    auto& control = mControls[{area, index}];
    const float available = rect.z - 24 * mUnit;
    if (control.value != value || control.size != fontSize || control.width != available) {
        control.value = value;
        control.size = fontSize;
        control.width = available;
        const float width = textSize(value, fontSize).x;
        control.fittedSize =
            width > available ?
                std::max(2.0f, std::floor(fontSize * std::max(0.65f, available / width) / 2) * 2) :
                fontSize;
        while (control.fittedSize > 2 && textSize(value, control.fittedSize).x > available)
            control.fittedSize = std::max(2.0f, control.fittedSize - 2);
    }
    label(value, rect, control.fittedSize, active ? mFocusInk : mForeground,
          active ? mAccent : (area == Area::Keys ? mPanel : mRaised), active,
          area == Area::Suggestions ? ALIGN_LEFT : ALIGN_CENTER, control.text);
    control.text = mLabels.back().text;
    mTargets.push_back({rect, area, index});
}

void GuiSearch::title(const std::string& value,
                      const std::vector<LibrarySearch::Span>& spans,
                      const glm::vec4& rect,
                      float fontSize)
{
    label(value, rect, fontSize, mForeground);
    // Render the complete shaped title once. Overlay matching ranges using clipping of
    // the same shaped run, so accent/ligature expansion never changes letter positions.
    const Label shaped {mLabels.back()};
    for (const auto& span : spans) {
        if (span.begin >= span.end || span.end > value.size())
            continue;
        const float begin = textSize(value.substr(0, span.begin), fontSize).x;
        const float end = textSize(value.substr(0, span.end), fontSize).x;
        if (begin >= rect.z - 24 * mUnit)
            continue;
        // Recolor a clipped copy of the same glyph run; do not shape the title again.
        mLabels.push_back(shaped);
        mLabels.back().textColor = mAccent;
        // Clip the highlight overlay to its matched range in the complete shaped run.
        mLabels.back().rect = {rect.x + 12 * mUnit + begin, rect.y,
                               std::min(end, rect.z - 24 * mUnit) - begin, rect.w};
    }
}

void GuiSearch::cover(const LibrarySearch::Handle& handle, const glm::vec4& rect)
{
    auto old = std::find_if(mCovers.begin(), mCovers.end(),
                            [&](const Cover& c) { return c.handle.id == handle.id && c.image; });
    Cover image {handle, rect, nullptr, 0};
    if (old != mCovers.end()) {
        image.image = std::move(old->image);
        image.opacity = old->opacity;
    }
    // Layout collects placeholders; update() attaches already-decoded pixels later.
    mCovers.push_back(std::move(image));
}

void GuiSearch::result(int index, const glm::vec4& rect, bool best)
{
    auto* game = LibrarySearch::resolve(mGames[index]);
    if (!game)
        return;
    label("", rect, 1, mForeground, selected(Area::Games, index) ? mRaised : mPanel,
          selected(Area::Games, index));
    mTargets.push_back({rect, Area::Games, index});
    const float inset = 14 * mUnit;
    const float imageWidth = best ? rect.w * 0.64f : rect.w * 0.60f;
    const glm::vec4 image {rect.x + inset, rect.y + inset, imageWidth, rect.w - inset * 2};
    cover(mGames[index], image);
    const float x = image.x + image.z + inset;
    const float width = rect.x + rect.z - x - inset;
    const float titleHeight = (best ? 60 : 44) * mUnit;
    const float titleY = best ? rect.y + rect.w * 0.24f : rect.y + (rect.w - titleHeight) / 2;
    const float badgeWidth = best ? 0 : std::min(150 * mUnit, width * 0.25f);
    if (best)
        label(_("Best match"), {x, rect.y + inset, width, 34 * mUnit}, 26 * mUnit, mMuted);
    const std::vector<LibrarySearch::Span> empty;
    title(game->getName(),
          index < static_cast<int>(mMatches.size()) ? mMatches[index].spans : empty,
          {x, titleY, width - (best ? 0 : badgeWidth + inset), titleHeight},
          (best ? 42 : 32) * mUnit);
    if (!best) {
        const auto badge =
            Utils::String::toUpper(game->getSystemName()) + (game->getFavorite() ? " ★" : "");
        label(badge,
              {rect.x + rect.z - inset - badgeWidth, rect.y + (rect.w - 40 * mUnit) / 2, badgeWidth,
               40 * mUnit},
              24 * mUnit, mMuted, mRaised, false, ALIGN_CENTER);
        return;
    }
    std::string metadata = game->getSystem()->getFullName();
    if (best) {
        const auto date = game->metadata.get("releasedate");
        if (date.size() >= 4 && date.substr(0, 4) != "0000" && date.substr(0, 4) != "1970")
            metadata += " · " + date.substr(0, 4);
        const auto genre = game->metadata.get("genre");
        if (!genre.empty() && genre != "unknown")
            metadata += " · " + genre;
    }
    if (game->getFavorite())
        metadata += " · ★ " + _("favorite");
    label(metadata, {x, titleY + titleHeight, width, 36 * mUnit}, 26 * mUnit, mMuted);
    if (best) {
        const auto last = game->metadata.get("lastplayed");
        std::string played;
        if (last.size() >= 8 && last > "19700101T000000") {
            const auto now = Utils::Time::now();
            // Compare calendar dates at local noon, so crossing a daylight-saving
            // boundary does not turn yesterday into today (or two days ago).
            const auto today = Utils::Time::timeToString(now, "%Y%m%d");
            const auto noon = Utils::Time::stringToTime(today + "T120000");
            const auto then = Utils::Time::stringToTime(last.substr(0, 8) + "T120000");
            const auto days = static_cast<int>(std::round(std::difftime(noon, then) / 86400));
            const std::string date =
                days == 0 ? _("today") :
                days == 1 ? _("yesterday") :
                days >= 2 && days < 7 ?
                            Utils::String::format(_n("%d day ago", "%d days ago", days), days) :
                            last.substr(0, 4) + "-" + last.substr(4, 2) + "-" + last.substr(6, 2);
            played = _("Last played") + " " + date;
        }
        const auto seconds = game->metadata.getInt("playtime");
        if (seconds > 0) {
            const int duration = seconds >= 3600 ? seconds / 3600 : std::max(1, seconds / 60);
            played +=
                (played.empty() ? "" : " · ") +
                Utils::String::format(seconds >= 3600 ? _n("%d hour", "%d hours", duration) :
                                                        _n("%d minute", "%d minutes", duration),
                                      duration);
        }
        label(played, {x, titleY + titleHeight + 40 * mUnit, width, 36 * mUnit}, 25 * mUnit,
              mMuted);
    }
}

std::vector<std::string> GuiSearch::keys() const
{
    std::vector<std::string> values;
    if (mSymbols) {
        values = {"!", "?", "@", "#", "$", "%", "&", "*", "(", ")", "á", "à", "â", "ä",
                  "ã", "å", "æ", "ç", "é", "è", "ê", "ë", "í", "ì", "î", "ï", "ñ", "ó",
                  "ò", "ô", "ö", "õ", "ø", "œ", "ú", "ù", "û", "ü", "ß", "+"};
    }
    else {
        const std::string characters = "1234567890qwertyuiopasdfghjkl'zxcvbnm-:.";
        for (char character : characters)
            values.push_back(mUppercase ? Utils::String::toUpper(std::string(1, character)) :
                                          std::string(1, character));
    }
    if (mSymbols && mUppercase)
        for (auto& value : values)
            value = Utils::String::toUpper(value);
    values.insert(values.end(), {_("space"), _("delete"), _("clear"), _("results ›"), _("Shift"),
                                 mSymbols ? _("ABC") : _("Symbols / accents")});
    return values;
}

void GuiSearch::layout()
{
    const auto start = std::chrono::steady_clock::now();
    const auto cpuStart = threadCpuMilliseconds();
    const auto scheduleStart = threadSchedule();
    mDirty = false;
    mLabels.clear();
    mTargets.clear();
    const size_t oldCovers = mCovers.size();
    mUnit = std::min(mSize.x, mSize.y) / 1080.0f;
    mPortrait = mSize.y > mSize.x;
    const float gap = 20 * mUnit;
    const float margin = 54 * mUnit;
    const float usable = mSize.x - margin * 2;
    const float left = mPortrait ? usable : (usable - gap * 2) * 0.38f;
    const float right = mPortrait ? usable : usable - left - gap * 2;
    const float rightX = mPortrait ? margin : margin + left + gap * 2;
    const float fieldHeight = 92 * mUnit;
    const float scopeWidth = mScopeName.empty() ? 0 : std::min(left * 0.40f, 260 * mUnit);
    const float closeWidth = mTouch ? 140 * mUnit : 0;
    const float closeSpace = mTouch ? closeWidth + gap : 0;
    mFieldRect = {margin, margin, left - scopeWidth - gap * 0.5f - closeSpace, fieldHeight};
    // The field keeps the caret visible by displaying a suffix around the insertion point.
    std::string field = mQuery;
    const auto font = searchFont(38 * mUnit);
    size_t visibleBegin {0};
    while (visibleBegin < mCursor &&
           font->sizeText(field.substr(visibleBegin, mCursor - visibleBegin)).x >
               mFieldRect.z - 60 * mUnit)
        visibleBegin = nextCharacter(field, visibleBegin);
    field = field.substr(visibleBegin);
    mCaretX = std::min(font->sizeText(field.substr(0, mCursor - visibleBegin) + mComposition).x,
                       mFieldRect.z - 60 * mUnit);
    if (!mComposition.empty())
        field.insert(mCursor - visibleBegin, mComposition);
    if (field.empty() && mLoading)
        field = _("Searching for games...");
    else if (field.empty())
        field = Utils::String::format(_n("Search %s game", "Search %s games", mLibraryCount),
                                      std::to_string(mLibraryCount).c_str());
    // Keep the editor on one line even when the caret is in the middle of a long query.
    // The background/hit area remains tall enough for touch.
    const float lineHeight = font->getHeight(1.15f);
    label(field,
          {mFieldRect.x, mFieldRect.y + (mFieldRect.w - lineHeight) / 2, mFieldRect.z, lineHeight},
          38 * mUnit, mQuery.empty() ? mMuted : mForeground, mPanel, mArea == Area::Field);
    mLabels.back().rect = mFieldRect;
    mTargets.push_back({mFieldRect, Area::Field, 0});
    std::string scope = _("All systems");
    if (!mSystem.empty()) {
        const auto found = std::find_if(mSystems.begin(), mSystems.end(), [&](const auto& system) {
            return system.system == mSystem;
        });
        scope = _("In:") + " " +
                (found != mSystems.end() ? found->name :
                 mSystem == mScopeName   ? mScopeLabel :
                                           mSystem);
    }
    if (!mScopeName.empty())
        target(scope, {margin + left - scopeWidth - closeSpace, margin, scopeWidth, fieldHeight},
               Area::Scope, 0, 27 * mUnit);
    if (mTouch)
        target(_("Close"), {margin + left - closeWidth, margin, closeWidth, fieldHeight},
               Area::Close, 0, 30 * mUnit);
    const float suggestionY = margin + fieldHeight + gap;
    float sx = margin;
    const float chipHeight = 48 * mUnit;
    float sy = suggestionY;
    for (int i = mSuggestionOffset; i < static_cast<int>(mSuggestions.size()); ++i) {
        const auto& suggestion = mSuggestions[i];
        const std::string display = kindLabel(suggestion.kind) + " · " + suggestion.text;
        const float width = std::min(left, textSize(display, 27 * mUnit).x + 32 * mUnit);
        if (sx + width > margin + left) {
            if (mPortrait || sy > suggestionY)
                break;
            sx = margin;
            sy += chipHeight + gap * 0.5f;
        }
        target(display, {sx, sy, width, chipHeight}, Area::Suggestions, i, 27 * mUnit);
        // Underline only the completion suffix, using original UTF-8 byte boundaries.
        const auto chipFont = mLabels.back().text->getFont();
        const auto query = LibrarySearch::normalize(mQuery);
        size_t matchedBytes {0};
        if (!query.empty() &&
            LibrarySearch::normalize(suggestion.text).compare(0, query.size(), query) == 0) {
            while (matchedBytes < suggestion.text.size() &&
                   LibrarySearch::normalize(suggestion.text.substr(0, matchedBytes)).size() <
                       query.size())
                matchedBytes = nextCharacter(suggestion.text, matchedBytes);
        }
        const auto prefix =
            kindLabel(suggestion.kind) + " · " + suggestion.text.substr(0, matchedBytes);
        const float begin = textSize(prefix, chipFont->getSize()).x;
        const float end = std::min(width - 24 * mUnit, textSize(display, chipFont->getSize()).x);
        if (end > begin)
            label("",
                  {sx + 12 * mUnit + begin, sy + chipHeight - 4 * mUnit, end - begin, 2 * mUnit}, 1,
                  mForeground, mAccent);
        sx += width + gap * 0.5f;
    }
    const bool grid = !mTouch;
    const float keyboardRow = 76 * mUnit;
    const float keyboardHeight = keyboardRow * 5 + 68 * mUnit;
    const float keyboardBottom = mSize.y - 115 * mUnit;
    const float keyboardY = keyboardBottom - keyboardHeight;
    mContentBottom = mPortrait && grid ? keyboardY - gap : mSize.y - 120 * mUnit;
    if (mTouch && SDL_IsScreenKeyboardShown(mRenderer->getSDLWindow()))
        mContentBottom = std::min(mContentBottom, mSize.y * 0.50f - gap);
    const auto keyboardLayout =
        std::make_tuple(mSize, grid, mSymbols, mUppercase, mArea == Area::Keys ? mIndex : -1);
    if (grid && keyboardLayout == mKeyboardLayout && !mKeyboardLabels.empty()) {
        mLabels.insert(mLabels.end(), mKeyboardLabels.begin(), mKeyboardLabels.end());
        mTargets.insert(mTargets.end(), mKeyboardTargets.begin(), mKeyboardTargets.end());
    }
    else if (grid) {
        const size_t firstLabel = mLabels.size(), firstTarget = mTargets.size();
        const auto values = keys();
        target(values[44], {margin, keyboardY, left * 0.33f, 50 * mUnit}, Area::Keys, 44,
               26 * mUnit);
        target(values[45], {margin + left * 0.33f + gap, keyboardY, left * 0.67f - gap, 50 * mUnit},
               Area::Keys, 45, 26 * mUnit);
        const float cell = left / 10;
        for (int i {0}; i < 40; ++i)
            target(values[i],
                   {margin + (i % 10) * cell, keyboardY + 68 * mUnit + (i / 10) * keyboardRow,
                    cell - 6 * mUnit, keyboardRow - 6 * mUnit},
                   Area::Keys, i, 34 * mUnit);
        const int columns[] = {0, 4, 6, 8};
        const int widths[] = {4, 2, 2, 2};
        for (int i {0}; i < 4; ++i)
            target(values[40 + i],
                   {margin + columns[i] * cell, keyboardY + 68 * mUnit + 4 * keyboardRow,
                    widths[i] * cell - 6 * mUnit, keyboardRow - 6 * mUnit},
                   Area::Keys, 40 + i, 27 * mUnit);
        mKeyboardLabels.assign(mLabels.begin() + firstLabel, mLabels.end());
        mKeyboardTargets.assign(mTargets.begin() + firstTarget, mTargets.end());
        mKeyboardLayout = keyboardLayout;
    }
    float top = mPortrait ? suggestionY + chipHeight + gap : margin;
    int metadataIndex = static_cast<int>(mSystems.size()) + 2;
    float chipX = rightX;
    for (const auto& value : {mGenre, mDeveloper, mPublisher}) {
        if (value.empty())
            continue;
        const auto display = value + " ×";
        const float width = std::min(right, textSize(display, 28 * mUnit).x + 32 * mUnit);
        if (chipX + width > rightX + right) {
            top += 60 * mUnit;
            chipX = rightX;
        }
        target(display, {chipX, top, width, 48 * mUnit}, Area::Filters, metadataIndex++,
               28 * mUnit);
        chipX += width + gap;
    }
    if (metadataIndex > static_cast<int>(mSystems.size()) + 2)
        top += 60 * mUnit;
    const bool zero = zeroState();
    mZeroPaged = false;
    if (!zero)
        mZeroShelf = -1;
    mResultsRect = {rightX, top, right, mContentBottom - top};
    if (mLoading) {
        label(_("Searching for games..."), {rightX, top, right, 100 * mUnit}, 36 * mUnit, mMuted);
    }
    else if (zero) {
        const float zeroTop = top;
        const auto labelsBeforeHistory = mLabels.size();
        const auto targetsBeforeHistory = mTargets.size();
        if (!mHistory.empty()) {
            label(_("Recent searches"), {rightX, top, right, 40 * mUnit}, 28 * mUnit, mMuted);
            top += 52 * mUnit;
            float x = rightX;
            int first = mArea == Area::History ? std::max(0, mIndex - 2) : 0;
            for (int i = first; i <= static_cast<int>(mHistory.size()); ++i) {
                const std::string value =
                    i == static_cast<int>(mHistory.size()) ? _("Clear history") : mHistory[i];
                const float width = std::min(right, textSize(value, 30 * mUnit).x + 34 * mUnit);
                if (x + width > rightX + right) {
                    x = rightX;
                    top += 58 * mUnit;
                }
                if (top > mResultsRect.y + 180 * mUnit)
                    break;
                target(value, {x, top, width, 48 * mUnit}, Area::History, i, 30 * mUnit);
                x += width + gap;
            }
            top += 80 * mUnit;
        }
        int gameIndex {0};
        int shelves = !mRecent.empty() + !mFavorites.empty();
        // Each shelf needs its heading, a 90-unit cover, and caption/gap.
        mZeroPaged = shelves > 0 && mContentBottom - top < shelves * 240 * mUnit;
        if (!mZeroPaged)
            mZeroShelf = -1;
        else if (mArea == Area::Games)
            mZeroShelf = mIndex < static_cast<int>(mRecent.size()) ? 0 : 1;
        else if (mArea == Area::History)
            mZeroShelf = -1;
        if ((mZeroShelf == 0 && mRecent.empty()) || (mZeroShelf == 1 && mFavorites.empty()))
            mZeroShelf = -1;
        if (mZeroShelf >= 0) {
            // Scroll a constrained zero state to the selected shelf. History and
            // the other shelf remain reachable with a vertical gesture or focus.
            mLabels.resize(labelsBeforeHistory);
            mTargets.resize(targetsBeforeHistory);
            top = zeroTop;
            shelves = 1;
        }
        const float shelfImageHeight =
            shelves ? std::max(90 * mUnit, (mContentBottom - top) / shelves - 150 * mUnit) : 0;
        auto shelf = [&](const std::string& heading, const std::vector<size_t>& games) {
            if (games.empty())
                return;
            label(heading, {rightX, top, right, 40 * mUnit}, 28 * mUnit, mMuted);
            top += 50 * mUnit;
            const int columns = mPortrait ? 3 : 5;
            const float width = (right - gap * (columns - 1)) / columns;
            const float height = std::min({width * 1.32f, 215 * mUnit, shelfImageHeight});
            const int shelfStart = gameIndex;
            const int first = mArea == Area::Games && mIndex >= shelfStart &&
                                      mIndex < shelfStart + static_cast<int>(games.size()) ?
                                  std::max(0, mIndex - shelfStart - columns + 1) :
                                  0;
            for (int i {0}; i < static_cast<int>(games.size()); ++i, ++gameIndex) {
                if (i < first || i >= first + columns || top + height + 60 * mUnit > mContentBottom)
                    continue;
                const float x = rightX + (i - first) * (width + gap);
                cover(mGames[gameIndex], {x, top, width, height});
                label("", {x, top, width, height}, 1, mForeground, mPanel,
                      selected(Area::Games, gameIndex));
                const auto game = LibrarySearch::resolve(mGames[gameIndex]);
                label(game ? game->getName() : "", {x, top + height + 4 * mUnit, width, 56 * mUnit},
                      27 * mUnit, mForeground);
                if (game) {
                    const std::string badge = Utils::String::toUpper(game->getSystemName()) +
                                              (game->getFavorite() ? " ★" : "");
                    const float badgeWidth =
                        std::min(width, textSize(badge, 24 * mUnit).x + 24 * mUnit);
                    label(
                        badge,
                        {x + width - badgeWidth, top + height - 40 * mUnit, badgeWidth, 40 * mUnit},
                        24 * mUnit, mForeground, mRaised, false, ALIGN_CENTER);
                    mLabels.back().overlay = true;
                }
                mTargets.push_back({{x, top, width, height + 60 * mUnit}, Area::Games, gameIndex});
            }
            top += height + 100 * mUnit;
        };
        if (mZeroShelf != 1)
            shelf(_("Jump back in"), mRecent);
        else
            gameIndex = static_cast<int>(mRecent.size());
        if (mZeroShelf != 0)
            shelf(_("Favorites"), mFavorites);
        if (mGames.empty() && mHistory.empty())
            label(_("Start typing to search your library."), {rightX, top, right, 100 * mUnit},
                  36 * mUnit, mMuted);
    }
    else {
        const int count = static_cast<int>(mSystems.size()) + 2;
        const int first = mArea == Area::Filters ? std::max(0, std::min(count - 4, mIndex - 1)) : 0;
        float x = rightX;
        for (int i = first; i < count; ++i) {
            std::string value;
            bool active {false};
            if (i == 0) {
                value = _("All") + " " + std::to_string(mTotal);
                active = mSystem.empty() && !mFavouritesOnly;
            }
            else if (i == count - 1) {
                value = "★ " + _("Favorites");
                active = mFavouritesOnly;
            }
            else {
                const auto& system = mSystems[i - 1];
                value = Utils::String::toUpper(system.system) + " " + std::to_string(system.count);
                active = mSystem == system.system;
            }
            const float width = std::min(right, textSize(value, 27 * mUnit).x + 32 * mUnit);
            if (x + width > rightX + right)
                break;
            target(value, {x, top, width, 48 * mUnit}, Area::Filters, i, 27 * mUnit);
            if (active)
                label("", {x, top + 46 * mUnit, width, 3 * mUnit}, 1, mForeground, mAccent);
            x += width + gap * 0.5f;
        }
        top += 70 * mUnit;
        if (mNoResults) {
            label(mQuery.empty() ? _("Try another system or remove a filter.") :
                                   Utils::String::format(_("No games match ‘%s’."), mQuery.c_str()),
                  {rightX, top, right, 90 * mUnit}, 36 * mUnit, mForeground);
            top += 100 * mUnit;
            if (!mGames.empty()) {
                label(_("Did you mean"), {rightX, top, right, 45 * mUnit}, 30 * mUnit, mMuted);
                top += 55 * mUnit;
            }
            else if (!mQuery.empty())
                label(_("Try another system or remove a filter."),
                      {rightX, top, right, 100 * mUnit}, 32 * mUnit, mMuted);
        }
        const float bestHeight = mNoResults || mOffset ? 118 * mUnit : 252 * mUnit;
        const float rowHeight = 118 * mUnit;
        mVisibleRows =
            std::max(1, static_cast<int>((mContentBottom - top - bestHeight) / rowHeight) + 1);
        if (mArea == Area::Games) {
            if (mIndex < mFirstGame)
                mFirstGame = mIndex;
            if (mIndex >= mFirstGame + mVisibleRows)
                mFirstGame = mIndex - mVisibleRows + 1;
        }
        mFirstGame = std::max(0, std::min(mFirstGame, static_cast<int>(mGames.size()) - 1));
        for (int i = mFirstGame; i < static_cast<int>(mGames.size()); ++i) {
            const bool best = mOffset + i == 0 && !mNoResults;
            const float height = best ? bestHeight : rowHeight - 10 * mUnit;
            if (top + height > mContentBottom)
                break;
            result(i, {rightX, top, right, height}, best);
            top += height + 10 * mUnit;
        }
        if (!mNoResults && mOffset + mFirstGame + mVisibleRows < mMatchTotal)
            label(_("More results below"), {rightX, mContentBottom, right, 32 * mUnit}, 24 * mUnit,
                  mMuted);
    }
    if (!mTouch) {
        float x = margin;
        float y = mSize.y - 90 * mUnit;
        for (const auto& prompt : getHelpPrompts()) {
            const std::string button =
                prompt.first == "lr" ? "L/R" : Utils::String::toUpper(prompt.first);
            const std::string hint = button + "  " + prompt.second;
            const float width = textSize(hint, 26 * mUnit).x + 30 * mUnit;
            if (x + width > mSize.x - margin) {
                x = margin;
                y += 40 * mUnit;
            }
            label(hint, {x, y, std::min(width, usable), 36 * mUnit}, 26 * mUnit, mMuted);
            x += width;
        }
    }
    mCovers.erase(mCovers.begin(), mCovers.begin() + oldCovers);
    requestArtwork();
    prepareDraw();
    const auto schedule = scheduleDelta(scheduleStart);
    const double cpuMilliseconds = elapsedThreadCpu(cpuStart);
    const auto end = std::chrono::steady_clock::now();
    const double milliseconds = std::chrono::duration<double, std::milli>(end - start).count();
    if (mMeasureFrame)
        mQueryWorkMs += milliseconds;
    LOG(LogDebug) << "Search layout: ms=" << milliseconds << " covers=" << mCovers.size()
                  << " focus=" << static_cast<int>(mArea) << ":" << mIndex
                  << " layout_cpu_ms=" << cpuMilliseconds << " start_ns=" << traceNanoseconds(start)
                  << " end_ns=" << traceNanoseconds(end) << " voluntary_switches=" << schedule[0]
                  << " involuntary_switches=" << schedule[1] << " minor_faults=" << schedule[2]
                  << " major_faults=" << schedule[3];
#if defined(__ANDROID__)
    if (Log::getReportingLevel() >= LogDebug) {
        // Short batched records preserve every hit target in both diagnostic logs.
        std::ostringstream targets;
        int lines {0};
        for (const auto& target : mTargets) {
            const auto point = mRenderer->getTouchGeometry().toNormalized(
                {target.rect.x + target.rect.z / 2, target.rect.y + target.rect.w / 2});
            if (lines)
                targets << '\n';
            targets << "Search touch target: area=" << static_cast<int>(target.area)
                    << " index=" << target.index << " norm=" << point.x << "," << point.y;
            if (++lines == 24) {
                LOG(LogDebug) << targets.str();
                targets.str("");
                targets.clear();
                lines = 0;
            }
        }
        if (lines) {
            LOG(LogDebug) << targets.str();
        }
    }
#endif
    if (mMeasureFrame)
        mQueryWorkMs +=
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - end)
                .count();
}

void GuiSearch::requestArtwork()
{
    std::vector<SearchArtwork::Request> requests;
    for (const auto& cover : mCovers) {
        auto* game = LibrarySearch::resolve(cover.handle);
        if (!game)
            continue;
        requests.push_back({cover.handle.id, game->getPath(), game->getSystemName(),
                            game->getSystem()->getStartPath(), mMediaRoot});
    }
    mArtwork.request(std::move(requests));
}

int GuiSearch::count(Area area) const
{
    switch (area) {
        case Area::Close:
        case Area::Field:
            return 1;
        case Area::Scope:
            return mScopeName.empty() ? 0 : 1;
        case Area::Keys:
            return 46;
        case Area::Suggestions:
            return static_cast<int>(mSuggestions.size());
        case Area::Filters:
            return static_cast<int>(mSystems.size()) + 2 + (!mGenre.empty()) +
                   (!mDeveloper.empty()) + (!mPublisher.empty());
        case Area::History:
            return mHistory.empty() ? 0 : static_cast<int>(mHistory.size()) + 1;
        case Area::Games:
            return static_cast<int>(mGames.size());
    }
    return 0;
}

void GuiSearch::focus(Area area, int index)
{
    if (area == Area::Scope && mScopeName.empty())
        area = Area::Field;
    // Keep a bounded result page. Only visible titles/artwork need materializing,
    // including when a focused game moves far down the ranking after a favorite change.
    if (area == Area::Games && !mNoResults && !mMatches.empty() && mMatchTotal) {
        const int64_t wanted =
            std::max<int64_t>(0, std::min<int64_t>(static_cast<int64_t>(mOffset) + index,
                                                   static_cast<int64_t>(mMatchTotal) - 1));
        if (wanted < static_cast<int64_t>(mOffset) ||
            wanted >= static_cast<int64_t>(mOffset + mGames.size())) {
            const int64_t first = static_cast<int64_t>(mOffset) + mFirstGame;
            mOffset = wanted > static_cast<int64_t>(mOffset) ?
                          std::max<int64_t>(0, wanted - mVisibleRows + 1) :
                          std::max<int64_t>(0, wanted - static_cast<int64_t>(mResultLimit) + 1);
            refresh(false);
            index = wanted - static_cast<int64_t>(mOffset);
            mFirstGame = std::max<int64_t>(0, first + (wanted >= first ? 1 : -1) -
                                                  static_cast<int64_t>(mOffset));
        }
    }
    mArea = area;
    mIndex = std::max(0, std::min(index, count(area) - 1));
    if (area == Area::Suggestions)
        mSuggestionOffset = mIndex;
    else if (area == Area::Keys || area == Area::Field)
        mSuggestionOffset = 0;
    mDirty = true;
    updateHelpPrompts();
    LOG(LogDebug) << "Search focus: area=" << static_cast<int>(area) << " index="
                  << (area == Area::Games && !zeroState() && !mNoResults ? mOffset + mIndex :
                                                                           mIndex);
}

void GuiSearch::focusResults()
{
    const bool zero = zeroState();
    if (mGames.empty())
        focus(zero && !mHistory.empty() ? Area::History : (mTouch ? Area::Field : Area::Keys));
    else
        focus(Area::Games);
}

void GuiSearch::move(int x, int y)
{
    const Area header =
        zeroState() ? (mHistory.empty() ? Area::Scope : Area::History) : Area::Filters;
    if (mArea == Area::Keys) {
        if (mIndex >= 44) {
            if (x)
                focus(Area::Keys, mIndex == 44 ? 45 : 44);
            else if (y < 0)
                focus(Area::Keys, 40);
            else if (y > 0)
                focus(Area::Keys, 0);
        }
        else if (mIndex >= 40) {
            if (x > 0 && mIndex == 43)
                focusResults();
            else if (x)
                focus(Area::Keys, 40 + (mIndex - 40 + x + 4) % 4);
            else if (y < 0) {
                const int columns[] = {0, 4, 6, 8};
                focus(Area::Keys, 30 + columns[mIndex - 40]);
            }
            else if (y > 0)
                focus(Area::Keys, 44);
        }
        else {
            const int row = mIndex / 10;
            const int column = mIndex % 10;
            if (x > 0 && column == 9)
                focusResults();
            else if (x)
                focus(Area::Keys, row * 10 + (column + x + 10) % 10);
            else if (y < 0 && row == 0)
                focus(mSuggestions.empty() ? Area::Scope : Area::Suggestions);
            else if (y > 0 && row == 3)
                focus(Area::Keys, 40 + (column < 4 ? 0 : column < 6 ? 1 : column < 8 ? 2 : 3));
            else if (y)
                focus(Area::Keys, mIndex + y * 10);
        }
    }
    else if (mArea == Area::Games) {
        if (x < 0)
            focus(Area::Keys, 9);
        else if (y < 0 && mIndex == 0 && !mOffset)
            focus(header);
        else if (y)
            focus(Area::Games, mIndex + y);
    }
    else if (mArea == Area::Suggestions) {
        if (x)
            focus(Area::Suggestions, (mIndex + x + count(mArea)) % std::max(1, count(mArea)));
        else if (y > 0)
            focus(Area::Keys);
        else if (y < 0)
            focus(Area::Scope);
    }
    else if (mArea == Area::History || mArea == Area::Filters) {
        if (x < 0 && mIndex == 0)
            focus(Area::Keys, 9);
        else if (x)
            focus(mArea, (mIndex + x + count(mArea)) % std::max(1, count(mArea)));
        else if (y > 0)
            focus(Area::Games);
        else if (y < 0)
            focus(mSuggestions.empty() ? Area::Scope : Area::Suggestions);
    }
    else if (mArea == Area::Scope) {
        if (x < 0)
            focus(Area::Field);
        else if (x > 0) {
            if (header == Area::Scope)
                focusResults();
            else
                focus(header);
        }
        else if (y > 0)
            focus(mSuggestions.empty() ? Area::Keys : Area::Suggestions);
        else if (y < 0)
            focus(Area::Keys, 44);
    }
    else if (mArea == Area::Field) {
        if (x)
            mCursor = x < 0 ? previousCharacter(mQuery, mCursor) : nextCharacter(mQuery, mCursor);
        else if (y)
            focus(Area::Games, y < 0 ? static_cast<int>(mGames.size()) - 1 : 0);
        mDirty = true;
    }
}

void GuiSearch::beginKeystroke()
{
    if (!mKeystrokeFrame)
        mQueryWorkMs = 0;
    mKeystrokeFrame = true;
    mMeasureFrame = true;
}

void GuiSearch::edit(const std::string& text)
{
    beginKeystroke();
    if (text == "\b") {
        const size_t previous = previousCharacter(mQuery, mCursor);
        mQuery.erase(previous, mCursor - previous);
        mCursor = previous;
    }
    else if (mQuery.size() + text.size() <= 512) {
        mQuery.insert(mCursor, text);
        mCursor += text.size();
    }
    mComposition.clear();
    mBlink = 0;
    refresh();
}

void GuiSearch::textInput(const std::string& text, bool)
{
    if (text.empty() || text == "\n" || text == "\r" || (text == "\b" && !mComposition.empty()))
        return;
    // SDL_TEXTINPUT is the only physical/IME character source. KEYDOWN never inserts text.
    edit(text);
}

void GuiSearch::textEditing(const std::string& text, int, int)
{
    mComposition = text;
    mDirty = true;
}

void GuiSearch::startTextInput(bool touch, bool requestKeyboard)
{
    const bool changed = mTouch != touch;
    mTouch = touch;
    mComposition.clear();
    SDL_StopTextInput();
    SDL_SetHint(SDL_HINT_IME_SHOW_UI, "1");
    // Android's screen keyboard is requested only after a touch. Controller/keyboard input
    // still receives SDL text events without opening an unwanted IME over the grid.
    SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, touch && requestKeyboard ? "1" : "0");
    if (changed)
        layout();
    const SDL_Rect rect {static_cast<int>(mFieldRect.x), static_cast<int>(mFieldRect.y),
                         static_cast<int>(mFieldRect.z), static_cast<int>(mFieldRect.w)};
    SDL_SetTextInputRect(&rect);
    SDL_StartTextInput();
    mDirty = true;
}

void GuiSearch::typeKey()
{
    if (mIndex < 40)
        edit(keys()[mIndex]);
    else if (mIndex == 40)
        edit(" ");
    else if (mIndex == 41)
        edit("\b");
    else if (mIndex == 42) {
        beginKeystroke();
        mQuery.clear();
        mCursor = 0;
        refresh();
    }
    else if (mIndex == 43)
        focusResults();
    else if (mIndex == 44) {
        mUppercase = !mUppercase;
        mDirty = true;
    }
    else if (mIndex == 45) {
        mSymbols = !mSymbols;
        mDirty = true;
    }
}

void GuiSearch::cycleSystem(int direction)
{
    auto current = std::find_if(mSystems.begin(), mSystems.end(),
                                [&](const auto& system) { return system.system == mSystem; });
    const int index =
        current == mSystems.end() ? 0 : static_cast<int>(current - mSystems.begin()) + 1;
    const int next = (index + direction + static_cast<int>(mSystems.size()) + 1) %
                     (static_cast<int>(mSystems.size()) + 1);
    mSystem = next == 0 ? "" : mSystems[next - 1].system;
    refresh();
    LOG(LogDebug) << "Search system filter: system=" << (mSystem.empty() ? "all" : mSystem)
                  << " results=" << mMatchTotal;
}

void GuiSearch::applySuggestion()
{
    if (mIndex >= static_cast<int>(mSuggestions.size()))
        return;
    const auto suggestion = mSuggestions[mIndex];
    using Kind = LibrarySearch::SuggestionKind;
    if (suggestion.kind == Kind::System) {
        const auto& engine = LibrarySearch::engine();
        for (size_t i {0}; i < engine.size(); ++i) {
            const auto& game = engine.game(i);
            if (LibrarySearch::normalize(game.systemName) ==
                    LibrarySearch::normalize(suggestion.text) ||
                game.system == suggestion.text) {
                mSystem = game.system;
                break;
            }
        }
    }
    else if (suggestion.kind == Kind::Genre)
        mGenre = suggestion.text;
    else if (suggestion.kind == Kind::Developer)
        mDeveloper = suggestion.text;
    else if (suggestion.kind == Kind::Publisher)
        mPublisher = suggestion.text;
    else {
        mQuery = suggestion.text;
        mCursor = mQuery.size();
    }
    if (suggestion.kind == Kind::System || suggestion.kind == Kind::Genre ||
        suggestion.kind == Kind::Developer || suggestion.kind == Kind::Publisher) {
        mQuery.clear();
        mCursor = 0;
    }
    refresh();
    LOG(LogDebug) << "Search suggestion applied: query=" << queryForLog() << " system=" << mSystem
                  << " results=" << mMatchTotal;
    focus(Area::Keys);
}

void GuiSearch::activate()
{
    if (mArea == Area::Close)
        close();
    else if (mArea == Area::Keys)
        typeKey();
    else if (mArea == Area::Field) {
        startTextInput(mTouch);
        focus(Area::Field);
    }
    else if (mArea == Area::Scope) {
        mSystem = mSystem.empty() ? mScopeName : "";
        refresh();
    }
    else if (mArea == Area::Suggestions)
        applySuggestion();
    else if (mArea == Area::Games)
        openGame(false);
    else if (mArea == Area::History) {
        if (mIndex == static_cast<int>(mHistory.size())) {
            LibrarySearch::history().clear();
            refresh();
            focus(Area::Keys);
        }
        else if (mIndex < static_cast<int>(mHistory.size())) {
            mQuery = mHistory[mIndex];
            mCursor = mQuery.size();
            refresh();
            focus(Area::Games);
        }
    }
    else if (mArea == Area::Filters) {
        if (mIndex == 0) {
            mSystem.clear();
            mFavouritesOnly = false;
        }
        else if (mIndex == static_cast<int>(mSystems.size()) + 1)
            mFavouritesOnly = !mFavouritesOnly;
        else if (mIndex > static_cast<int>(mSystems.size()) + 1) {
            int remove = mIndex - static_cast<int>(mSystems.size()) - 2;
            for (auto* value : {&mGenre, &mDeveloper, &mPublisher}) {
                if (value->empty())
                    continue;
                if (remove-- == 0) {
                    value->clear();
                    break;
                }
            }
        }
        else {
            const auto value = mSystems[mIndex - 1].system;
            mSystem = mSystem == value ? "" : value;
        }
        refresh();
    }
}

void GuiSearch::record() { LibrarySearch::history().addQuery(mQuery); }

std::string GuiSearch::queryForLog() const
{
    return mQuery.empty() ||
                   (Settings::getInstance()->getBool("SearchHistory") && !filter().kidMode) ?
               mQuery :
               "<private>";
}

void GuiSearch::close() { delete this; }

void GuiSearch::openGame(bool play)
{
    if (mIndex < 0 || mIndex >= static_cast<int>(mGames.size()))
        return;
    auto* game = LibrarySearch::resolve(mGames[mIndex]);
    if (!game) {
        refresh();
        return;
    }
    record();
    LibrarySearch::recordOpened(game);
    auto* controller = ViewController::getInstance();
    auto* window = mWindow;
    if (play)
        controller->triggerGameLaunch(game);
    else {
        // Respect folder links in exactly the way Screensaver::goToGame does.
        FileData* entry = game;
        FileData* folder = nullptr;
        while ((entry = entry->getParent()))
            if (!entry->metadata.get("folderlink").empty())
                folder = entry;
        if (folder)
            game = folder;
        auto* index = game->getSystem()->getIndex();
        if (index && index->isFiltered() && !index->showFile(game)) {
            index->resetFilters();
            index->setKidModeFilters();
            controller->onFileChanged(game, true);
            window->queueInfoPopup(_("Game list filters cleared to show the selected game."), 4000);
        }
        controller->goToGamelist(game->getSystem());
        auto view = controller->getGamelistView(game->getSystem());
        view->setCursor(game);
        view->stopListScrolling();
        controller->cancelViewTransitions();
        SearchPresentation::afterFrame([] { SearchEntry::observeGamelistCursor(); });
        LOG(LogDebug) << "Search show game: " << game->getSystem()->getName() << "/"
                      << game->getName();
    }
    // Close the screen and any main menu below it; leave the normal launch/view controller.
    while (window->peekGui() && window->peekGui() != controller)
        delete window->peekGui();
}

void GuiSearch::toggleFavorite()
{
    if (mIndex < 0 || mIndex >= static_cast<int>(mGames.size()))
        return;
    auto* game = LibrarySearch::resolve(mGames[mIndex]);
    if (!game)
        return;
    CollectionSystemsManager::getInstance()->toggleGameInCollection(game, true);
    refresh();
}

bool GuiSearch::input(InputConfig* config, Input input)
{
    if (!input.value)
        return true;
    const bool keyboard = input.type == TYPE_KEY;
    // The configured Insert/PageUp/PageDown actions also work on a keyboard.
    if (keyboard &&
        (config->isMappedTo("leftshoulder", input) || config->isMappedTo("rightshoulder", input) ||
         config->isMappedTo("y", input))) {
        if (config->isMappedTo("y", input)) {
            if (mArea == Area::Games)
                toggleFavorite();
            else
                edit(" ");
        }
        else
            cycleSystem(config->isMappedTo("leftshoulder", input) ? -1 : 1);
        return true;
    }
    if (keyboard) {
        LOG(LogDebug) << "Search keyboard: text_active="
                      << static_cast<bool>(SDL_IsTextInputActive());
        // Android normally hides the IME when a hardware keyboard is attached. Keep
        // software-keyboard commits in touch mode, but expose the grid for hardware keys.
        if (mTouch && !SDL_IsScreenKeyboardShown(mRenderer->getSDLWindow()))
            startTextInput(false);
        if (input.id == SDLK_ESCAPE || input.id == SDLK_AC_BACK) {
            close();
            return true;
        }
        if (input.id == SDLK_RETURN || input.id == SDLK_KP_ENTER) {
            if (!mComposition.empty())
                return true;
            record();
            if (mArea == Area::Games)
                openGame((input.modifiers & KMOD_CTRL) != 0);
            else if (mArea == Area::History || mArea == Area::Filters ||
                     mArea == Area::Suggestions || mArea == Area::Scope || mArea == Area::Close)
                activate();
            else
                focusResults();
            return true;
        }
        if (input.id == SDLK_TAB) {
            const std::vector<Area> areas {Area::Field,   Area::Scope,   Area::Suggestions,
                                           Area::History, Area::Filters, Area::Games,
                                           Area::Keys,    Area::Close};
            const auto current = std::find(areas.begin(), areas.end(), mArea);
            const int direction = input.modifiers & KMOD_SHIFT ? -1 : 1;
            const int index = static_cast<int>(current - areas.begin());
            for (int offset {1}; offset <= static_cast<int>(areas.size()); ++offset) {
                const auto candidate =
                    areas[(index + direction * offset + areas.size() * 2) % areas.size()];
                if (std::any_of(mTargets.begin(), mTargets.end(),
                                [&](const Target& target) { return target.area == candidate; })) {
                    focus(candidate);
                    break;
                }
            }
            return true;
        }
        if (input.id == SDLK_HOME || input.id == SDLK_END) {
            mCursor = input.id == SDLK_HOME ? 0 : mQuery.size();
            focus(Area::Field);
            return true;
        }
        if (input.id == SDLK_DELETE) {
            beginKeystroke();
            mQuery.erase(mCursor, nextCharacter(mQuery, mCursor) - mCursor);
            refresh();
            return true;
        }
        if (input.id == SDLK_BACKSPACE)
            return true; // InputManager already delivered exactly one textInput("\b").
        if (input.id == SDLK_UP || input.id == SDLK_DOWN) {
            if (mTouch)
                startTextInput(false);
            if (mArea == Area::Games)
                focus(Area::Games, mIndex + (input.id == SDLK_UP ? -1 : 1));
            else
                focus(Area::Games, 0);
            return true;
        }
        if (input.id == SDLK_LEFT || input.id == SDLK_RIGHT) {
            if (mArea == Area::Games && input.id == SDLK_LEFT)
                focus(Area::Field);
            else if (mArea == Area::Field || mArea == Area::Keys) {
                focus(Area::Field);
                move(input.id == SDLK_LEFT ? -1 : 1, 0);
            }
            else
                move(input.id == SDLK_LEFT ? -1 : 1, 0);
            return true;
        }
        // Printable keys are exclusively handled by SDL_TEXTINPUT, including space.
        return true;
    }
    if (mTouch && input.type != TYPE_TOUCH)
        startTextInput(false);
    if (config->isMappedTo("b", input)) {
        if (mArea == Area::Games || mArea == Area::Filters || mArea == Area::History)
            focus(Area::Keys);
        else
            close();
        return true;
    }
    if (config->isMappedTo("a", input)) {
        activate();
        return true;
    }
    if (config->isMappedTo("x", input)) {
        if (mArea == Area::Games)
            openGame(true);
        else if (mArea == Area::History && mIndex < static_cast<int>(mHistory.size())) {
            LibrarySearch::history().removeQuery(mHistory[mIndex]);
            refresh();
            if (mHistory.empty())
                focus(Area::Keys);
        }
        else
            edit("\b");
        return true;
    }
    if (config->isMappedTo("y", input)) {
        if (mArea == Area::Games)
            toggleFavorite();
        else
            edit(" ");
        return true;
    }
    if (config->isMappedTo("leftshoulder", input) || config->isMappedTo("rightshoulder", input)) {
        cycleSystem(config->isMappedTo("leftshoulder", input) ? -1 : 1);
        return true;
    }
    if (config->isMappedTo("start", input)) {
        focusResults();
        return true;
    }
    if (config->isMappedTo("back", input)) {
        mSymbols = !mSymbols;
        mDirty = true;
        return true;
    }
    if (config->isMappedLike("left", input))
        move(-1, 0);
    else if (config->isMappedLike("right", input))
        move(1, 0);
    else if (config->isMappedLike("up", input))
        move(0, -1);
    else if (config->isMappedLike("down", input))
        move(0, 1);
    return true;
}

void GuiSearch::update(int deltaTime)
{
    GuiComponent::update(deltaTime);
    const glm::vec2 screen {Renderer::getScreenWidth(), Renderer::getScreenHeight()};
    if (mSize != screen) {
        mLabels.clear();
        mControls.clear();
        mLabelCache.clear();
        mSizeCache.clear();
        mKeyboardLabels.clear();
        mDrawing.clear();
        mFonts.clear();
        mFontAtlas.reset();
        releaseFonts();
        setSize(screen);
        setPosition(mOrigin.x * screen.x, mOrigin.y * screen.y);
        mDirty = true;
    }
    if (mWindow->peekGui() == this && !SDL_IsTextInputActive()) {
        LOG(LogDebug) << "Search text input resumed after focus loss";
        // SDL stops text input before Android's Back-driven IME hide has finished.
        // Recover text events without reversing that hide; a field tap requests the IME.
        startTextInput(mTouch, false);
    }
    const bool caretWasVisible {mBlink < 550};
    mBlink = (mBlink + deltaTime) % 1100;
    const auto pumpStart = std::chrono::steady_clock::now();
    LibrarySearch::engine();
    const double pumpMs =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - pumpStart)
            .count();
    if (mGeneration != LibrarySearch::currentGeneration() || mLoading != !LibrarySearch::ready())
        refresh();
    if (mMeasureFrame)
        mQueryWorkMs += pumpMs;
    const bool keyboardShown = SDL_IsScreenKeyboardShown(mRenderer->getSDLWindow());
    if (keyboardShown != mKeyboardShown) {
        mKeyboardShown = keyboardShown;
        mDirty = true;
    }
    if (mDirty)
        layout();
    else if (caretWasVisible != (mBlink < 550)) {
        const auto start = std::chrono::steady_clock::now();
        prepareDraw();
        if (mMeasureFrame)
            mQueryWorkMs +=
                std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start)
                    .count();
    }
    // At most one bounded upload per frame. No path lookup, stat or decode on this thread.
    const auto artworkStart = std::chrono::steady_clock::now();
    mArtwork.pump();
    bool uploaded {false};
    for (auto& cover : mCovers) {
        // Publish decoded artwork on an idle frame so text edits never wait on an upload.
        if (!cover.image && !uploaded && !mMeasureFrame) {
            const auto pixels = mArtwork.get(cover.handle.id);
            if (pixels && !pixels->rgba.empty()) {
                cover.image = std::make_unique<ImageComponent>(false, true);
                cover.image->setLinearInterpolation(true);
                cover.image->setRawImage(pixels->rgba.data(), pixels->width, pixels->height);
                uploaded = true;
            }
        }
        if (cover.image) {
            const float previous = cover.opacity;
            cover.opacity = std::min(1.0f, cover.opacity + deltaTime / 180.0f);
            if (previous != cover.opacity)
                cover.image->setOpacity(cover.opacity);
        }
    }
    if (mMeasureFrame)
        mQueryWorkMs += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() -
                                                                  artworkStart)
                            .count();
}

void GuiSearch::prepareDraw()
{
    mTextBatch = TextCache {};
    mBorderBatch = TextCache {};
    mBorderBatch.setClipRegion({0, 0, 0, 0});
    mTextBatch.setClipRegion({0, 0, 0, 0});
    mPanelBatch.clear();
    std::vector<Renderer::Vertex> borders;
    for (const auto& label : mLabels) {
        if (label.background) {
            const auto& r = label.rect;
            const float radius = std::min({10 * mUnit, r.z / 2, r.w / 2});
            mDrawing.panel(label.overlay ? borders : mPanelBatch, r, radius, label.background);
        }
        if (label.border) {
            const auto& r = label.rect;
            const float line = 3 * mUnit;
            for (const auto& edge : {glm::vec4 {r.x, r.y, r.z, line},
                                     {r.x, r.y + r.w - line, r.z, line},
                                     {r.x, r.y, line, r.w},
                                     {r.x + r.z - line, r.y, line, r.w}})
                SearchDrawing::rectangle(borders, edge, mAccent);
        }
    }
    // Only small overlays/caret use the font atlas. Opaque panels are drawn
    // separately, without sampling and alpha-blending a full-screen glyph texture.
    auto panelFont = searchFont(40 * mUnit);
    panelFont->appendSolid(&mBorderBatch, borders);
    for (const auto& label : mLabels) {
        if (!label.text)
            continue;
        const auto* cache = label.text->getTextCache();
        if (!cache)
            continue;
        const glm::vec2 offset {
            label.position.x,
            label.position.y +
                std::round(std::max(0.0f, (label.text->getSize().y - cache->metrics.size.y) / 2))};
        mDrawing.append(label.overlay ? mBorderBatch : mTextBatch, *cache, label.text->getValue(),
                        label.text->getFont().get(), label.text->getSize(),
                        label.text->getHorizontalAlignment(), offset, label.rect,
                        label.textColor.value_or(mForeground));
    }
    if (mBlink < 550) {
        std::vector<Renderer::Vertex> caret;
        SearchDrawing::rectangle(caret,
                                 {mFieldRect.x + 14 * mUnit + mCaretX, mFieldRect.y + 20 * mUnit,
                                  3 * mUnit, mFieldRect.w - 40 * mUnit},
                                 mAccent);
        panelFont->appendSolid(&mTextBatch, caret);
    }
}

void GuiSearch::render(const glm::mat4& parentTrans)
{
    const auto renderStart = std::chrono::steady_clock::now();
    const auto cpuStart = mMeasureFrame ? threadCpuMilliseconds() : -1.0;
    const auto scheduleStart =
        mMeasureFrame ? threadSchedule() : std::array<long, 4> {-1, -1, -1, -1};
    if (mDirty)
        layout();
    const glm::mat4 transform = parentTrans * getTransform();
    mRenderer->setMatrix(transform);
    mRenderer->drawRect(0, 0, mSize.x, mSize.y, mBackground, mBackground, false, 1, 1,
                        Renderer::BlendFactor::ONE, Renderer::BlendFactor::ZERO);
    if (!mPanelBatch.empty()) {
        mRenderer->bindTexture(0, 0);
        mRenderer->drawTriangleStrips(mPanelBatch.data(),
                                      static_cast<unsigned int>(mPanelBatch.size()),
                                      Renderer::BlendFactor::ONE, Renderer::BlendFactor::ZERO);
    }
    if (!mFonts.empty())
        mFonts.begin()->second->renderTextCache(&mTextBatch);
    const auto textDrawn = std::chrono::steady_clock::now();
    const auto batchCpu = mMeasureFrame ? elapsedThreadCpu(cpuStart) : -1.0;
    for (auto& cover : mCovers) {
        if (!cover.image)
            continue;
        cover.image->setMaxSize(cover.rect.z, cover.rect.w);
        cover.image->setPosition(cover.rect.x + (cover.rect.z - cover.image->getSize().x) / 2,
                                 cover.rect.y + (cover.rect.w - cover.image->getSize().y) / 2);
        cover.image->render(transform);
    }
    mRenderer->setMatrix(transform);
    if (!mFonts.empty())
        mFonts.begin()->second->renderTextCache(&mBorderBatch);
    const auto submitted = std::chrono::steady_clock::now();
    if (mMeasureFrame) {
        const auto schedule = scheduleDelta(scheduleStart);
        const auto renderCpu = elapsedThreadCpu(cpuStart);
        const auto renderEnd = std::chrono::steady_clock::now();
        const double renderMs =
            std::chrono::duration<double, std::milli>(renderEnd - renderStart).count();
        LOG(LogDebug) << "Search frame: query=" << queryForLog()
                      << " work_ms=" << mQueryWorkMs + renderMs << " render_ms=" << renderMs
                      << " batch_ms="
                      << std::chrono::duration<double, std::milli>(textDrawn - renderStart).count()
                      << " covers_ms="
                      << std::chrono::duration<double, std::milli>(submitted - textDrawn).count()
                      << " diagnostics_ms="
                      << std::chrono::duration<double, std::milli>(renderEnd - submitted).count()
                      << " batches=" << mTextBatch.getBatchCount()
                      << " panel_vertices=" << mPanelBatch.size() << " render_cpu_ms=" << renderCpu
                      << " batch_cpu_ms=" << batchCpu
                      << " start_ns=" << traceNanoseconds(renderStart)
                      << " end_ns=" << traceNanoseconds(renderEnd)
                      << " voluntary_switches=" << schedule[0]
                      << " involuntary_switches=" << schedule[1] << " minor_faults=" << schedule[2]
                      << " major_faults=" << schedule[3]
                      << " cause=" << (mKeystrokeFrame ? "keystroke" : "refresh")
                      << " first=" << (mKeystrokeFrame && mFirstKeystroke);
        if (mKeystrokeFrame)
            mFirstKeystroke = false;
        mPresentedKeystroke = mKeystrokeFrame;
        mKeystrokeFrame = false;
        mMeasureFrame = false;
        mPresentedQuery = queryForLog();
        mMeasurePresentation = true;
    }
}

std::vector<HelpPrompt> GuiSearch::getHelpPrompts()
{
    if (mArea == Area::Games)
        return {{"up/down", _("choose")},
                {"a", _("show in game list")},
                {"x", _("play now")},
                {"y", _("favorite")},
                {"b", _("keyboard")}};
    if (mArea == Area::History)
        return {{"left/right", _("choose")},
                {"a", _("search")},
                {"x", _("remove")},
                {"b", _("keyboard")}};
    if (mArea == Area::Suggestions || mArea == Area::Filters || mArea == Area::Scope)
        return {{"left/right", _("choose")}, {"a", _("apply")}, {"b", _("close")}};
    return {{"a", _("type")},           {"x", _("delete")},      {"y", _("space")},
            {"lr", _("filter system")}, {"start", _("results")}, {"b", _("close")}};
}

#if defined(__ANDROID__)
void GuiSearch::cancelNativeTouch()
{
    mFinger = -1;
    mTouchGame.clear();
}

bool GuiSearch::nativeTouch(int type, int64_t finger, float x, float y)
{
    TouchOverlay::Point point;
    if (!mRenderer->getTouchGeometry().toLogical({x, y}, point))
        return false;
    const auto local = glm::inverse(getTransform()) * glm::vec4 {point.x, point.y, 0, 1};
    point = {local.x, local.y};
    if (mDirty)
        layout();
    if (type == SDL_FINGERDOWN) {
        if (mFinger != -1)
            return true;
        mFinger = finger;
        mTouchStart = mTouchLast = {point.x, point.y};
        mTouchTime = SDL_GetTicks();
        mTouchMoved = false;
        mZeroSwipeHandled = false;
        mTouchGame.clear();
        mTouchTarget.index = -1;
        for (const auto& target : mTargets)
            if (contains(target.rect, point.x, point.y)) {
                mTouchTarget = target;
                break;
            }
        if (mTouchTarget.area == Area::Games && mTouchTarget.index >= 0 &&
            mTouchTarget.index < static_cast<int>(mGames.size()))
            mTouchGame = mGames[mTouchTarget.index].id;
        return true;
    }
    if (finger != mFinger || mFinger == -1)
        return true;
    if (type == SDL_FINGERMOTION) {
        if (glm::distance(mTouchStart, glm::vec2 {point.x, point.y}) > 16 * mUnit)
            mTouchMoved = true;
        if (mTouchMoved) {
            if (mTouchTarget.area == Area::Suggestions &&
                std::abs(point.x - mTouchLast.x) > 60 * mUnit) {
                mSuggestionOffset =
                    std::max(0, std::min(static_cast<int>(mSuggestions.size()) - 1,
                                         mSuggestionOffset + (point.x < mTouchLast.x ? 1 : -1)));
                mTouchLast = {point.x, point.y};
                mDirty = true;
            }
            else if (mTouchTarget.area == Area::Filters &&
                     std::abs(point.x - mTouchLast.x) > 60 * mUnit) {
                const int index = mArea == Area::Filters ? mIndex : mTouchTarget.index;
                focus(Area::Filters, index + (point.x < mTouchLast.x ? 1 : -1));
                mTouchLast = {point.x, point.y};
            }
            else if (mTouchTarget.area == Area::History &&
                     std::abs(point.x - mTouchLast.x) > 60 * mUnit) {
                const int index = mArea == Area::History ? mIndex : mTouchTarget.index;
                focus(Area::History, index + (point.x < mTouchLast.x ? 1 : -1));
                mTouchLast = {point.x, point.y};
            }
            else if (mTouchTarget.area == Area::Games && mQuery.empty() && mSystem.empty() &&
                     mGenre.empty() && mDeveloper.empty() && mPublisher.empty() &&
                     !mFavouritesOnly && std::abs(point.x - mTouchLast.x) > 60 * mUnit) {
                const int index = mArea == Area::Games ? mIndex : mTouchTarget.index;
                const int first = mTouchTarget.index < static_cast<int>(mRecent.size()) ?
                                      0 :
                                      static_cast<int>(mRecent.size());
                const int end = first == 0 && !mRecent.empty() ? static_cast<int>(mRecent.size()) :
                                                                 static_cast<int>(mGames.size());
                focus(
                    Area::Games,
                    std::max(first, std::min(index + (point.x < mTouchLast.x ? 1 : -1), end - 1)));
                mTouchLast = {point.x, point.y};
            }
            else if (contains(mResultsRect, point.x, point.y) &&
                     std::abs(point.y - mTouchLast.y) > 70 * mUnit) {
                const int direction = point.y < mTouchLast.y ? 1 : -1;
                if (zeroState() && mZeroPaged) {
                    if (!mZeroSwipeHandled) {
                        if (direction > 0)
                            focus(Area::Games,
                                  mFavorites.empty() ? 0 : static_cast<int>(mRecent.size()));
                        else if (mZeroShelf == 1 && !mRecent.empty())
                            focus(Area::Games);
                        else {
                            mZeroShelf = -1;
                            focus(mHistory.empty() ? Area::Scope : Area::History);
                        }
                        mZeroSwipeHandled = true;
                    }
                    mTouchLast = {point.x, point.y};
                    return true;
                }
                if (!mNoResults && ((direction < 0 && !mFirstGame && mOffset) ||
                                    (direction > 0 &&
                                     mFirstGame + mVisibleRows >= static_cast<int>(mGames.size()) &&
                                     mOffset + mGames.size() < mMatchTotal))) {
                    focus(Area::Games, direction < 0 ? -1 : static_cast<int>(mGames.size()));
                    focus(Area::Games, mFirstGame);
                }
                else
                    mFirstGame =
                        std::max(0, std::min(mFirstGame + direction,
                                             static_cast<int>(mGames.size()) - mVisibleRows));
                const int selected =
                    std::max(mFirstGame, std::min(mIndex, mFirstGame + mVisibleRows - 1));
                focus(Area::Games, selected);
                mTouchLast = {point.x, point.y};
            }
        }
        return true;
    }
    if (type != SDL_FINGERUP)
        return true;
    mFinger = -1;
    if (mTouchMoved || mTouchTarget.index == -1 || !contains(mTouchTarget.rect, point.x, point.y))
        return true;
    auto target = mTouchTarget;
    if (target.area == Area::Games) {
        // Text commits and metadata refreshes can reorder results during a press.
        const auto game = std::find_if(mGames.begin(), mGames.end(),
                                       [&](const auto& handle) { return handle.id == mTouchGame; });
        if (game == mGames.end())
            return true;
        target.index = static_cast<int>(game - mGames.begin());
    }
    focus(target.area, target.index);
    if (target.area == Area::Games && SDL_GetTicks() - mTouchTime >= 500) {
        SDL_StopTextInput();
        mWindow->pushGui(new SearchOptions(
            _("Game options"), _("Play now"), [this] { openGame(true); }, _("Favorite"),
            [this] { toggleFavorite(); }, _("Cancel")));
    }
    else if (target.area == Area::Field)
        startTextInput(true);
    else
        activate();
    return true;
}
#endif
