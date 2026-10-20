//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchEntry.cpp
//
//  Written for ES-DE-Plus using the upstream MIT text-entry components.
//

#include "guis/SearchEntry.h"

#include "FileData.h"
#include "Log.h"
#include "Settings.h"
#include "SystemData.h"
#include "UIModeController.h"
#include "Window.h"
#include "components/ComponentList.h"
#include "guis/GuiSearch.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"
#include "views/GamelistView.h"

#include <chrono>
#include <memory>
#include <utility>

namespace
{
    std::weak_ptr<int> activeSearch;

    // The screen owns the session. Closing it releases duplicate-entry protection
    // without a cached pointer into the GUI stack.
    template <typename Base> class SearchGui final : public Base
    {
    public:
        template <typename... Args>
        SearchGui(const std::shared_ptr<int>& session, Args&&... args)
            : Base(std::forward<Args>(args)...)
            , mSession {session}
        {
        }

    private:
        std::shared_ptr<int> mSession;
    };
} // namespace

void SearchEntry::open(const std::string& initialText, SystemData* scopeSystem, float)
{
    if (!activeSearch.expired())
        return;
    const auto started = std::chrono::steady_clock::now();
    auto session {std::make_shared<int>(0)};
    activeSearch = session;
    auto* window {Window::getInstance()};
    const bool remember {Settings::getInstance()->getBool("SearchHistory") &&
                         !UIModeController::getInstance()->isUIModeKid()};
    LOG(LogDebug) << "SearchEntry: open initial="
                  << (initialText.empty() || remember ? initialText : "<private>")
                  << " scope=" << (scopeSystem ? scopeSystem->getName() : "all");
    window->pushGui(new SearchGui<GuiSearch>(session, initialText, scopeSystem));
    LOG(LogDebug) << "Search entry ready: ms="
                  << std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() -
                                                               started)
                         .count();
}

void SearchEntry::observeOptionsFocus(ComponentList* list)
{
#if defined(__ANDROID__)
    // Let input-driven smoke checks observe actual focus before activating a row.
    const auto observeFocus = [list] {
        if (list->getTouchFocused() && list->size() > 0) {
            const auto& row {list->getTouchRowData(list->getCursorId())};
            if (!row.elements.empty()) {
                LOG(LogDebug) << "Gamelist options: focused="
                              << row.elements.front().component->getValue();
            }
        }
    };
    const auto previousCallback {list->getCursorChangedCallback()};
    list->setCursorChangedCallback([previousCallback, observeFocus](CursorState state) {
        if (previousCallback)
            previousCallback(state);
        observeFocus();
    });
    observeFocus();
#else
    (void)list;
#endif
}

void SearchEntry::observeGamelistCursor(GamelistView* view)
{
    if (Log::getReportingLevel() < LogDebug)
        return;
    const auto cursor = view->getCursor();
    LOG(LogDebug) << "Gamelist actual cursor: system=" << cursor->getSystem()->getName()
                  << " game=" << cursor->getName() << " path=" << cursor->getPath();
}

void SearchEntry::logFavoritesCollection(FileData* source, bool enabled, SystemData* favorites)
{
    LOG(LogDebug) << "Favorites collection: game=" << source->getName()
                  << " favorite=" << source->getFavorite() << " enabled=" << enabled
                  << " count=" << favorites->getRootFolder()->getChildren().size();
}

void SearchEntry::logFavoriteAction(FileData* source, bool editing, GamelistView* view)
{
    LOG(LogDebug) << "Gamelist favorite action: game=" << source->getName()
                  << " favorite=" << source->getFavorite() << " editing=" << editing
                  << " first=" << view->getFirstEntry()->getName()
                  << " cursor=" << view->getCursor()->getName();
}

bool SearchEntry::preservesPasskeyY()
{
    // Restricted modes keep upstream Y whenever their custom passkey uses it.
    return (UIModeController::getInstance()->isUIModeKid() ||
            UIModeController::getInstance()->isUIModeKiosk()) &&
           Settings::getInstance()->getString("UIMode_passkey").find('y') != std::string::npos;
}
