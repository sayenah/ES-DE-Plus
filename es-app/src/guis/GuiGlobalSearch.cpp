//  SPDX-License-Identifier: MIT
//
//  ES-DE Frontend
//  GuiGlobalSearch.cpp
//
//  Global game search for ES-DE-Plus.
//

#include "guis/GuiGlobalSearch.h"

#include "FileData.h"
#include "Settings.h"
#include "SystemData.h"
#include "UIModeController.h"
#include "components/TextComponent.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"
#include "views/ViewController.h"

#include <algorithm>
#include <cmath>

namespace
{
constexpr size_t MAX_SEARCH_RESULTS {200};

bool startsWith(const std::string& value, const std::string& prefix)
{
    return value.size() >= prefix.size() && value.compare(0, prefix.size(), prefix) == 0;
}
} // namespace

GuiGlobalSearch::GuiGlobalSearch(const std::string& query)
    : mMenu {_("SEARCH RESULTS")}
    , mQuery {Utils::String::trim(query)}
{
    addChild(&mMenu);
    populateResults();

    mMenu.addButton(_("BACK"), _("back"), [this] { delete this; });

    setSize(mMenu.getSize());
    setPosition((Renderer::getScreenWidth() - mSize.x) / 2.0f,
                std::round(Renderer::getScreenHeight() * 0.08f));
}

int GuiGlobalSearch::getMatchRank(FileData* game) const
{
    const std::string query {Utils::String::toUpper(mQuery)};
    const std::string name {Utils::String::toUpper(game->getName())};
    const std::string fileName {Utils::String::toUpper(game->getDisplayName())};

    if (name == query)
        return 0;

    if (startsWith(name, query))
        return 1;

    if (name.find(query) != std::string::npos)
        return 2;

    if (startsWith(fileName, query))
        return 3;

    if (fileName.find(query) != std::string::npos)
        return 4;

    const std::string developer {Utils::String::toUpper(game->metadata.get("developer"))};
    const std::string publisher {Utils::String::toUpper(game->metadata.get("publisher"))};
    const std::string genre {Utils::String::toUpper(game->metadata.get("genre"))};

    if (developer.find(query) != std::string::npos ||
        publisher.find(query) != std::string::npos ||
        genre.find(query) != std::string::npos)
        return 5;

    return -1;
}

void GuiGlobalSearch::populateResults()
{
    ComponentListRow row;
    auto font {Font::get(FONT_SIZE_MEDIUM)};

    row.addElement(std::make_shared<TextComponent>(
                       Utils::String::toUpper(_("SEARCH:") + " " + mQuery), font,
                       mMenuColorTertiary),
                   true);
    mMenu.addRow(row);

    std::vector<SearchResult> results;

    for (SystemData* system : SystemData::sSystemVector) {
        if (system == nullptr || system->isCollection() || !system->isGameSystem())
            continue;

        const std::vector<FileData*> games {system->getRootFolder()->getFilesRecursive(GAME)};

        for (FileData* game : games) {
            if (game == nullptr || !game->getCountAsGame())
                continue;

            if (!Settings::getInstance()->getBool("ShowHiddenGames") && game->getHidden())
                continue;

            if (UIModeController::getInstance()->isUIModeKid() && !game->getKidgame())
                continue;

            const int rank {getMatchRank(game)};
            if (rank < 0)
                continue;

            results.push_back(
                {game, rank, Utils::String::toUpper(game->getName()),
                 Utils::String::toUpper(system->getFullName())});
        }
    }

    std::sort(results.begin(), results.end(), [](const SearchResult& lhs, const SearchResult& rhs) {
        if (lhs.rank != rhs.rank)
            return lhs.rank < rhs.rank;
        if (lhs.sortName != rhs.sortName)
            return lhs.sortName < rhs.sortName;
        return lhs.systemName < rhs.systemName;
    });

    if (results.empty()) {
        row.elements.clear();
        row.addElement(
            std::make_shared<TextComponent>(_("NO GAMES FOUND"), font, mMenuColorPrimary), true);
        mMenu.addRow(row);
        return;
    }

    const size_t resultCount {std::min(results.size(), MAX_SEARCH_RESULTS)};

    for (size_t i {0}; i < resultCount; ++i) {
        FileData* game {results[i].game};
        const std::string label {game->getName() + "  [" + game->getSystem()->getFullName() + "]"};

        row.elements.clear();
        auto gameEntry = std::make_shared<TextComponent>(
            Utils::String::toUpper(label), font, mMenuColorPrimary);
        gameEntry->setHorizontalScrolling(true);
        row.addElement(gameEntry, true);
        row.makeAcceptInputHandler([this, game] { launchGame(game); });
        mMenu.addRow(row);
    }

    if (results.size() > MAX_SEARCH_RESULTS) {
        row.elements.clear();
        row.addElement(std::make_shared<TextComponent>(
                           Utils::String::toUpper(
                               _("MORE RESULTS AVAILABLE - REFINE YOUR SEARCH")),
                           Font::get(FONT_SIZE_SMALL), mMenuColorTertiary),
                       true);
        mMenu.addRow(row);
    }
}

void GuiGlobalSearch::launchGame(FileData* game)
{
    Window* window {mWindow};
    ViewController::getInstance()->triggerGameLaunch(game);

    // Close the search results and the main menu before launching. ViewController remains
    // at the bottom of the GUI stack and handles the normal ES-DE launch flow.
    while (window->peekGui() != ViewController::getInstance())
        delete window->peekGui();
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
