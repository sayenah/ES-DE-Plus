//  SPDX-License-Identifier: MIT
//
//  ES-DE Frontend
//  GuiGlobalSearch.cpp
//
//  Global game search for ES-DE-Plus.
//

#include "guis/GuiGlobalSearch.h"

#include "FileData.h"
#include "Window.h"
#include "components/TextComponent.h"
#include "search/LibrarySearch.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"
#include "views/ViewController.h"

#include <algorithm>
#include <cmath>

namespace
{
    constexpr size_t MAX_SEARCH_RESULTS {200};
} // namespace

GuiGlobalSearch::GuiGlobalSearch(const std::string& query)
    : mMenu {_("SEARCH RESULTS")}
    , mQuery {Utils::String::trim(query)}
{
    addChild(&mMenu);
    LibrarySearch::history().addQuery(mQuery);
    populateResults();

    mMenu.addButton(_("BACK"), _("back"), [this] { delete this; });

    setSize(mMenu.getSize());
    setPosition((Renderer::getScreenWidth() - mSize.x) / 2.0f,
                std::round(Renderer::getScreenHeight() * 0.08f));
}

void GuiGlobalSearch::populateResults()
{
    mMenu.getList()->clear();
    ComponentListRow row;
    auto font {Font::get(FONT_SIZE_MEDIUM)};

    row.addElement(
        std::make_shared<TextComponent>(Utils::String::toUpper(_("SEARCH:") + " " + mQuery), font,
                                        mMenuColorTertiary),
        true);
    mMenu.addRow(row);

    const auto& engine {LibrarySearch::engine()};
    const auto generation {LibrarySearch::currentGeneration()};
    mVersion = generation;
    if (!LibrarySearch::ready()) {
        row.elements.clear();
        row.addElement(std::make_shared<TextComponent>(_("WORKING..."), font, mMenuColorPrimary),
                       true);
        mMenu.addRow(row);
        return;
    }
    const auto results {
        engine.search(mQuery, MAX_SEARCH_RESULTS + 1, LibrarySearch::currentFilter())};

    if (results.empty()) {
        row.elements.clear();
        row.addElement(
            std::make_shared<TextComponent>(_("NO GAMES FOUND"), font, mMenuColorPrimary), true);
        mMenu.addRow(row);
        return;
    }

    const size_t resultCount {std::min(results.size(), MAX_SEARCH_RESULTS)};

    for (size_t i {0}; i < resultCount; ++i) {
        const auto handle {LibrarySearch::handle(results[i].index, generation)};
        FileData* game {LibrarySearch::resolve(handle)};
        if (!game)
            continue;
        const std::string label {game->getName() + "  [" + game->getSystem()->getFullName() + "]"};

        row.elements.clear();
        auto gameEntry =
            std::make_shared<TextComponent>(Utils::String::toUpper(label), font, mMenuColorPrimary);
        gameEntry->setHorizontalScrolling(true);
        row.addElement(gameEntry, true);
        row.makeAcceptInputHandler([this, handle] { launchGame(handle); });
        mMenu.addRow(row);
    }

    if (results.size() > MAX_SEARCH_RESULTS) {
        row.elements.clear();
        row.addElement(std::make_shared<TextComponent>(
                           Utils::String::toUpper(_("MORE RESULTS AVAILABLE - REFINE YOUR SEARCH")),
                           Font::get(FONT_SIZE_SMALL), mMenuColorTertiary),
                       true);
        mMenu.addRow(row);
    }
}

void GuiGlobalSearch::launchGame(const LibrarySearch::Handle& handle)
{
    FileData* game {LibrarySearch::resolve(handle)};
    if (!game)
        return;
    LibrarySearch::recordOpened(game);
    Window* window {mWindow};
    ViewController::getInstance()->triggerGameLaunch(game);

    // Close the search results and the main menu before launching. ViewController remains
    // at the bottom of the GUI stack and handles the normal ES-DE launch flow.
    while (window->peekGui() != ViewController::getInstance())
        delete window->peekGui();
}

void GuiGlobalSearch::update(int deltaTime)
{
    LibrarySearch::engine();
    if (mVersion != LibrarySearch::currentGeneration())
        populateResults();
    GuiComponent::update(deltaTime);
}

bool GuiGlobalSearch::input(InputConfig* config, Input input)
{
    if (GuiComponent::input(config, input))
        return true;

    if (config->isMappedTo("b", input) && input.value != 0) {
        delete this;
        return true;
    }

    return false;
}

std::vector<HelpPrompt> GuiGlobalSearch::getHelpPrompts()
{
    std::vector<HelpPrompt> prompts;
    prompts.push_back(HelpPrompt("up/down", _("choose")));
    prompts.push_back(HelpPrompt("a", _("launch")));
    prompts.push_back(HelpPrompt("b", _("back")));
    return prompts;
}
