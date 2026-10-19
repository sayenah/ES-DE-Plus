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
#include "utils/FileSystemUtil.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"
#include "views/GamelistView.h"
#include "views/ViewController.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <set>

namespace
{
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
    refresh();
    layout();
    for (const float size :
         {24.0f, 25.0f, 26.0f, 27.0f, 28.0f, 30.0f, 32.0f, 34.0f, 36.0f, 38.0f, 42.0f})
        searchFont(size * mUnit);
    startTextInput(mTouch);
    LOG(LogDebug) << "Search screen opened: query=" << mQuery << " scope=" << mScopeName;
}

GuiSearch::~GuiSearch() { SDL_StopTextInput(); }

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

void GuiSearch::refresh()
{
    if (mUnit > 0 && !mMeasureFrame) {
        mQueryWorkMs = 0;
        mMeasureFrame = true;
    }
    const auto start = std::chrono::steady_clock::now();
    const std::string oldGame =
        mArea == Area::Games && mIndex >= 0 && mIndex < static_cast<int>(mGames.size()) ?
            mGames[mIndex].id :
            "";
    const auto& engine = LibrarySearch::engine();
    const bool changed = mGeneration != LibrarySearch::currentGeneration();
    mGeneration = LibrarySearch::currentGeneration();
    mHistory = LibrarySearch::history().queries();
    mSuggestions = engine.suggest(mQuery, 6, filter());
    mSuggestionOffset =
        std::min(mSuggestionOffset, std::max(0, static_cast<int>(mSuggestions.size()) - 1));
    if (changed)
        mLibraryCount = engine.query("", 1, LibrarySearch::currentFilter()).total;
    const auto response = engine.query(mQuery, 200, filter(false));
    mTotal = response.total;
    mSystems = response.systems;
    mMatches = mSystem.empty() ? response.matches : engine.query(mQuery, 200, filter()).matches;
    mGames.clear();
    mRecent.clear();
    mFavorites.clear();
    mNoResults = !mQuery.empty() && mMatches.empty();
    if (mQuery.empty() && mSystem.empty() && mGenre.empty() && mDeveloper.empty() &&
        mPublisher.empty() && !mFavouritesOnly) {
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
    else
        mIndex = std::max(0, std::min(mIndex, count(mArea) - 1));
    mDirty = true;
    const double milliseconds =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    if (mMeasureFrame)
        mQueryWorkMs += milliseconds;
    else
        mQueryWorkMs = milliseconds;
    LOG(LogDebug) << "Search keystroke: query=" << mQuery << " results=" << mTotal
                  << " search_ms=" << milliseconds;
}

std::shared_ptr<Font> GuiSearch::searchFont(float size)
{
    // Retain the small set of font sizes across layouts. Font's upstream map holds weak
    // references; destroying every label would otherwise reload fonts on each keystroke.
    const float key = std::max(2.0f, std::round(size / 2) * 2);
    auto& font = mFonts[key];
    if (!font)
        font = Font::get(key);
    return font;
}

void GuiSearch::label(const std::string& value,
                      const glm::vec4& rect,
                      float fontSize,
                      unsigned int color,
                      unsigned int background,
                      bool border,
                      Alignment align)
{
    auto text = std::make_unique<TextComponent>(value, searchFont(fontSize), color, align,
                                                ALIGN_CENTER, glm::ivec2 {0, 0});
    text->setLineSpacing(1.15f);
    text->setPosition(rect.x + 12 * mUnit, rect.y);
    text->setSize(std::max(1.0f, rect.z - 24 * mUnit), rect.w);
    mLabels.push_back({std::move(text), rect, background, border});
}

bool GuiSearch::selected(Area area, int index) const { return mArea == area && mIndex == index; }

void GuiSearch::target(
    const std::string& value, const glm::vec4& rect, Area area, int index, float fontSize)
{
    const bool active = selected(area, index);
    // Keep control labels legible with long translations, within a hard single-line box.
    auto font = searchFont(fontSize);
    const float width = font->sizeText(value).x;
    if (width > rect.z - 24 * mUnit)
        fontSize *= std::max(0.65f, (rect.z - 24 * mUnit) / width);
    label(value, rect, fontSize, active ? mFocusInk : mForeground,
          active ? mAccent : (area == Area::Keys ? mPanel : mRaised), active, ALIGN_CENTER);
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
    const auto font = searchFont(fontSize);
    for (const auto& span : spans) {
        if (span.begin >= span.end || span.end > value.size())
            continue;
        const float begin = font->sizeText(value.substr(0, span.begin)).x;
        const float end = font->sizeText(value.substr(0, span.end)).x;
        if (begin >= rect.z - 24 * mUnit)
            continue;
        auto text = std::make_unique<TextComponent>(value, font, mAccent, ALIGN_LEFT, ALIGN_CENTER,
                                                    glm::ivec2 {0, 0});
        text->setLineSpacing(1.15f);
        text->setPosition(rect.x + 12 * mUnit, rect.y);
        text->setSize(std::max(1.0f, rect.z - 24 * mUnit), rect.w);
        // Clip the highlight overlay to its matched range in the complete shaped run.
        const glm::vec4 clip {rect.x + 12 * mUnit + begin, rect.y,
                              std::min(end, rect.z - 24 * mUnit) - begin, rect.w};
        mLabels.push_back({std::move(text), clip, 0, false});
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
          best || selected(Area::Games, index));
    mTargets.push_back({rect, Area::Games, index});
    const float inset = 14 * mUnit;
    const float imageWidth = best ? rect.w * 0.64f : rect.w * 0.60f;
    const glm::vec4 image {rect.x + inset, rect.y + inset, imageWidth, rect.w - inset * 2};
    cover(mGames[index], image);
    const float x = image.x + image.z + inset;
    const float width = rect.x + rect.z - x - inset;
    const float titleHeight = (best ? 60 : 44) * mUnit;
    const float titleY = best ? rect.y + rect.w * 0.24f : rect.y + rect.w * 0.12f;
    if (best)
        label(_("Best match"), {x, rect.y + inset, width, 34 * mUnit}, 26 * mUnit, mMuted);
    const std::vector<LibrarySearch::Span> empty;
    title(game->getName(),
          index < static_cast<int>(mMatches.size()) ? mMatches[index].spans : empty,
          {x, titleY, width, titleHeight}, (best ? 42 : 32) * mUnit);
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
        if (last.size() >= 8 && last > "19700101T000000")
            played = _("Last played") + " " + last.substr(0, 4) + "-" + last.substr(4, 2) + "-" +
                     last.substr(6, 2);
        const auto seconds = game->metadata.getInt("playtime");
        if (seconds > 0)
            played += (played.empty() ? "" : " · ") +
                      Utils::String::format(_("%d minutes played"), seconds / 60);
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
    const float scopeWidth = std::min(left * 0.40f, 260 * mUnit);
    mFieldRect = {margin, margin, left - scopeWidth - gap * 0.5f, fieldHeight};
    // The field keeps the caret visible by displaying a suffix around the insertion point.
    std::string field = mQuery;
    const auto font = searchFont(38 * mUnit);
    size_t visibleBegin {0};
    while (visibleBegin < mCursor &&
           font->sizeText(field.substr(visibleBegin, mCursor - visibleBegin)).x >
               mFieldRect.z - 60 * mUnit)
        visibleBegin = nextCharacter(field, visibleBegin);
    field = field.substr(visibleBegin);
    if (!mComposition.empty())
        field.insert(mCursor - visibleBegin, mComposition);
    if (field.empty())
        field = Utils::String::format(_n("Search %s game", "Search %s games", mLibraryCount),
                                      std::to_string(mLibraryCount).c_str());
    label(field, mFieldRect, 38 * mUnit, mQuery.empty() ? mMuted : mForeground, mPanel,
          mArea == Area::Field);
    mTargets.push_back({mFieldRect, Area::Field, 0});
    std::string scope = _("All systems");
    if (!mSystem.empty()) {
        const auto found = std::find_if(mSystems.begin(), mSystems.end(), [&](const auto& system) {
            return system.system == mSystem;
        });
        scope = _("In:") + " " + (found == mSystems.end() ? mSystem : found->name);
    }
    target(scope, {margin + left - scopeWidth, margin, scopeWidth, fieldHeight}, Area::Scope, 0,
           27 * mUnit);
    const float suggestionY = margin + fieldHeight + gap;
    float sx = margin;
    const float chipHeight = 48 * mUnit;
    float sy = suggestionY;
    for (int i = mSuggestionOffset; i < static_cast<int>(mSuggestions.size()); ++i) {
        const auto& suggestion = mSuggestions[i];
        const std::string display = kindLabel(suggestion.kind) + " · " + suggestion.text;
        const float width =
            std::min(left, searchFont(27 * mUnit)->sizeText(display).x + 32 * mUnit);
        if (sx + width > margin + left) {
            if (mPortrait || sy > suggestionY)
                break;
            sx = margin;
            sy += chipHeight + gap * 0.5f;
        }
        target(display, {sx, sy, width, chipHeight}, Area::Suggestions, i, 27 * mUnit);
        // Underline only the completion suffix, using original UTF-8 byte boundaries.
        mLabels.back().text->setHorizontalAlignment(ALIGN_LEFT);
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
        const float begin = chipFont->sizeText(prefix).x;
        const float end = std::min(width - 24 * mUnit, chipFont->sizeText(display).x);
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
        mContentBottom = std::min(mContentBottom, mSize.y * 0.57f);
    if (grid) {
        const auto values = keys();
        target(values[44], {margin, keyboardY, left * 0.33f, 50 * mUnit}, Area::Keys, 44,
               26 * mUnit);
        target(values[45], {margin + left * 0.33f + gap, keyboardY, left * 0.67f - gap, 50 * mUnit},
               Area::Keys, 45, 26 * mUnit);
        const float cell = left / 10;
        for (int i {0}; i < 40; ++i)
            target(Utils::String::toUpper(values[i]),
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
    }
    float top = mPortrait ? suggestionY + chipHeight + gap : margin;
    int metadataIndex = static_cast<int>(mSystems.size()) + 2;
    float chipX = rightX;
    for (const auto& value : {mGenre, mDeveloper, mPublisher}) {
        if (value.empty())
            continue;
        const auto display = value + " ×";
        const float width =
            std::min(right, searchFont(28 * mUnit)->sizeText(display).x + 32 * mUnit);
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
    const bool zero = mMatches.empty() && mQuery.empty() && mSystem.empty() && mGenre.empty() &&
                      mDeveloper.empty() && mPublisher.empty() && !mFavouritesOnly;
    mResultsRect = {rightX, top, right, mContentBottom - top};
    if (zero) {
        if (!mHistory.empty()) {
            label(_("Recent searches"), {rightX, top, right, 40 * mUnit}, 28 * mUnit, mMuted);
            top += 52 * mUnit;
            float x = rightX;
            int first = mArea == Area::History ? std::max(0, mIndex - 2) : 0;
            for (int i = first; i <= static_cast<int>(mHistory.size()); ++i) {
                const std::string value =
                    i == static_cast<int>(mHistory.size()) ? _("Clear history") : mHistory[i];
                const float width =
                    std::min(right, searchFont(30 * mUnit)->sizeText(value).x + 34 * mUnit);
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
        const int shelves = !mRecent.empty() + !mFavorites.empty();
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
                mTargets.push_back({{x, top, width, height + 60 * mUnit}, Area::Games, gameIndex});
            }
            top += height + 100 * mUnit;
        };
        shelf(_("Jump back in"), mRecent);
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
            const float width =
                std::min(right, searchFont(27 * mUnit)->sizeText(value).x + 32 * mUnit);
            if (x + width > rightX + right)
                break;
            target(value, {x, top, width, 48 * mUnit}, Area::Filters, i, 27 * mUnit);
            if (active)
                label("", {x, top + 46 * mUnit, width, 3 * mUnit}, 1, mForeground, mAccent);
            x += width + gap * 0.5f;
        }
        top += 70 * mUnit;
        if (mNoResults) {
            label(Utils::String::format(_("No games match ‘%s’."), mQuery.c_str()),
                  {rightX, top, right, 90 * mUnit}, 36 * mUnit, mForeground);
            top += 100 * mUnit;
            label(_("Did you mean"), {rightX, top, right, 45 * mUnit}, 30 * mUnit, mMuted);
            top += 55 * mUnit;
            if (mGames.empty())
                label(_("Try another system or remove a filter."),
                      {rightX, top, right, 100 * mUnit}, 32 * mUnit, mMuted);
        }
        const float bestHeight = mNoResults ? 118 * mUnit : 252 * mUnit;
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
            const bool best = i == 0 && !mNoResults;
            const float height = best ? bestHeight : rowHeight - 10 * mUnit;
            if (top + height > mContentBottom)
                break;
            result(i, {rightX, top, right, height}, best);
            top += height + 10 * mUnit;
        }
        if (mFirstGame + mVisibleRows < static_cast<int>(mGames.size()))
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
            const float width = searchFont(26 * mUnit)->sizeText(hint).x + 30 * mUnit;
            if (x + width > mSize.x - margin) {
                x = margin;
                y += 40 * mUnit;
            }
            label(hint, {x, y, std::min(width, usable), 36 * mUnit}, 26 * mUnit, mMuted);
            x += width;
        }
    }
    if (mTouch)
        target(_("Close"),
               {mSize.x - margin - 160 * mUnit, mSize.y - 100 * mUnit, 160 * mUnit, 60 * mUnit},
               Area::Close, 0, 30 * mUnit);
    mCovers.erase(mCovers.begin(), mCovers.begin() + oldCovers);
    requestArtwork();
    const double milliseconds =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    if (mMeasureFrame)
        mQueryWorkMs += milliseconds;
    LOG(LogDebug) << "Search layout: ms=" << milliseconds << " covers=" << mCovers.size()
                  << " focus=" << static_cast<int>(mArea) << ":" << mIndex;
#if defined(__ANDROID__)
    if (Log::getReportingLevel() >= LogDebug) {
        for (const auto& target : mTargets) {
            const auto point = mRenderer->getTouchGeometry().toNormalized(
                {target.rect.x + target.rect.z / 2, target.rect.y + target.rect.w / 2});
            LOG(LogDebug) << "Search touch target: area=" << static_cast<int>(target.area)
                          << " index=" << target.index << " norm=" << point.x << "," << point.y;
        }
    }
#endif
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
        case Area::Scope:
            return 1;
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
    mArea = area;
    mIndex = std::max(0, std::min(index, count(area) - 1));
    if (area == Area::Suggestions)
        mSuggestionOffset = std::max(0, mIndex - (mPortrait ? 0 : 2));
    mDirty = true;
    updateHelpPrompts();
    LOG(LogDebug) << "Search focus: area=" << static_cast<int>(area) << " index=" << mIndex;
}

void GuiSearch::focusResults()
{
    const bool zero = mQuery.empty() && mSystem.empty() && mGenre.empty() && mDeveloper.empty() &&
                      mPublisher.empty() && !mFavouritesOnly;
    focus(zero && mGames.empty() && !mHistory.empty() ? Area::History : Area::Games);
}

void GuiSearch::move(int x, int y)
{
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
        else if (y < 0 && mIndex == 0)
            focus(mHistory.empty() ? Area::Filters : Area::History);
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
            focus(Area::Suggestions);
    }
    else if (mArea == Area::Scope) {
        if (x < 0)
            focus(Area::Field);
        else if (x > 0)
            focus(mHistory.empty() ? Area::Filters : Area::History);
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

void GuiSearch::edit(const std::string& text)
{
    if (!mMeasureFrame)
        mQueryWorkMs = 0;
    mMeasureFrame = true;
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

void GuiSearch::startTextInput(bool touch)
{
    mTouch = touch;
    mComposition.clear();
    SDL_StopTextInput();
    SDL_SetHint(SDL_HINT_IME_SHOW_UI, "1");
    // Android's screen keyboard is requested only after a touch. Controller/keyboard input
    // still receives SDL text events without opening an unwanted IME over the grid.
    SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, touch ? "1" : "0");
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
        if (index && !index->showFile(game)) {
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
    if (keyboard) {
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
        setSize(screen);
        setPosition(mOrigin.x * screen.x, mOrigin.y * screen.y);
        mDirty = true;
    }
    mBlink = (mBlink + deltaTime) % 1100;
    if (mGeneration != LibrarySearch::currentGeneration())
        refresh();
    const bool keyboardShown = SDL_IsScreenKeyboardShown(mRenderer->getSDLWindow());
    if (keyboardShown != mKeyboardShown) {
        mKeyboardShown = keyboardShown;
        mDirty = true;
    }
    if (mDirty)
        layout();
    // At most one bounded upload per frame. No path lookup, stat or decode on this thread.
    const auto artworkStart = std::chrono::steady_clock::now();
    bool uploaded {false};
    for (auto& cover : mCovers) {
        if (!cover.image && !uploaded) {
            const auto pixels = mArtwork.get(cover.handle.id);
            if (pixels && !pixels->rgba.empty()) {
                cover.image = std::make_unique<ImageComponent>(false, true);
                cover.image->setLinearInterpolation(true);
                cover.image->setRawImage(pixels->rgba.data(), pixels->width, pixels->height);
                uploaded = true;
            }
        }
        if (cover.image) {
            cover.opacity = std::min(1.0f, cover.opacity + deltaTime / 180.0f);
            cover.image->setOpacity(cover.opacity);
        }
    }
    if (mMeasureFrame)
        mQueryWorkMs += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() -
                                                                  artworkStart)
                            .count();
}

void GuiSearch::render(const glm::mat4& parentTrans)
{
    const auto renderStart = std::chrono::steady_clock::now();
    if (mDirty)
        layout();
    const glm::mat4 transform = parentTrans * getTransform();
    mRenderer->setMatrix(transform);
    mRenderer->drawRect(0, 0, mSize.x, mSize.y, mBackground, mBackground);
    for (auto& label : mLabels) {
        mRenderer->setMatrix(transform);
        if (label.background)
            mRenderer->drawRect(label.rect.x, label.rect.y, label.rect.z, label.rect.w,
                                label.background, label.background, false, 1, 1,
                                Renderer::BlendFactor::SRC_ALPHA,
                                Renderer::BlendFactor::ONE_MINUS_SRC_ALPHA, 10 * mUnit);
        if (label.border) {
            const float line = 3 * mUnit;
            for (const auto& edge :
                 {glm::vec4 {label.rect.x, label.rect.y, label.rect.z, line},
                  {label.rect.x, label.rect.y + label.rect.w - line, label.rect.z, line},
                  {label.rect.x, label.rect.y, line, label.rect.w},
                  {label.rect.x + label.rect.z - line, label.rect.y, line, label.rect.w}})
                mRenderer->drawRect(edge.x, edge.y, edge.z, edge.w, mAccent, mAccent);
        }
        const auto point = transform * glm::vec4 {label.rect.x, label.rect.y, 0, 1};
        const glm::vec2 scale {glm::length(glm::vec3(transform[0])),
                               glm::length(glm::vec3(transform[1]))};
        mRenderer->pushClipRect({point.x, point.y},
                                {label.rect.z * scale.x, label.rect.w * scale.y});
        label.text->render(transform);
        mRenderer->popClipRect();
    }
    for (auto& cover : mCovers) {
        if (!cover.image)
            continue;
        cover.image->setMaxSize(cover.rect.z, cover.rect.w);
        cover.image->setPosition(cover.rect.x + (cover.rect.z - cover.image->getSize().x) / 2,
                                 cover.rect.y + (cover.rect.w - cover.image->getSize().y) / 2);
        cover.image->render(transform);
    }
    if (mBlink < 550) {
        mRenderer->setMatrix(transform);
        const auto font = searchFont(38 * mUnit);
        float cursor = font->sizeText(mQuery.substr(0, mCursor)).x;
        cursor = std::min(cursor, mFieldRect.z - 60 * mUnit);
        mRenderer->drawRect(mFieldRect.x + 14 * mUnit + cursor, mFieldRect.y + 20 * mUnit,
                            3 * mUnit, mFieldRect.w - 40 * mUnit, mAccent, mAccent);
    }
    if (mMeasureFrame) {
        const double renderMs = std::chrono::duration<double, std::milli>(
                                    std::chrono::steady_clock::now() - renderStart)
                                    .count();
        LOG(LogDebug) << "Search frame: query=" << mQuery << " work_ms=" << mQueryWorkMs + renderMs
                      << " render_ms=" << renderMs;
        mMeasureFrame = false;
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
void GuiSearch::cancelNativeTouch() { mFinger = -1; }

bool GuiSearch::nativeTouch(int type, int64_t finger, float x, float y)
{
    TouchOverlay::Point point;
    if (!mRenderer->getTouchGeometry().toLogical({x, y}, point))
        return false;
    if (mDirty)
        layout();
    if (type == SDL_FINGERDOWN) {
        if (mFinger != -1)
            return true;
        mFinger = finger;
        mTouchStart = mTouchLast = {point.x, point.y};
        mTouchTime = SDL_GetTicks();
        mTouchMoved = false;
        mTouchTarget.index = -1;
        for (const auto& target : mTargets)
            if (contains(target.rect, point.x, point.y)) {
                mTouchTarget = target;
                break;
            }
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
                focus(Area::Filters, mIndex + (point.x < mTouchLast.x ? 1 : -1));
                mTouchLast = {point.x, point.y};
            }
            else if (contains(mResultsRect, point.x, point.y) &&
                     std::abs(point.y - mTouchLast.y) > 70 * mUnit) {
                const int direction = point.y < mTouchLast.y ? 1 : -1;
                mFirstGame = std::max(0, std::min(mFirstGame + direction,
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
    const auto target = mTouchTarget;
    focus(target.area, target.index);
    if (target.area == Area::Games && SDL_GetTicks() - mTouchTime >= 500) {
        SDL_StopTextInput();
        mWindow->pushGui(new GuiMsgBox(
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
