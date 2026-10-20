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
#include "guis/GuiGlobalSearch.h"
#include "guis/GuiTextEditKeyboardPopup.h"
#include "guis/GuiTextEditPopup.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"
#include "views/GamelistView.h"

#include <memory>
#include <utility>

namespace
{
    std::weak_ptr<int> activeSearch;

    // Both the popup and the results own the session. Cancel, Back and closing
    // all GUIs release it naturally, without a cached pointer into the GUI stack.
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

void SearchEntry::open(const std::string& initialText,
                       SystemData* scopeSystem,
                       float verticalPosition)
{
    if (!activeSearch.expired())
        return;
    auto session {std::make_shared<int>(0)};
    activeSearch = session;
    auto* window {Window::getInstance()};
    const auto searchCallback = [window, session, scopeSystem](const std::string& value) {
        const std::string query {Utils::String::trim(value)};
        LOG(LogDebug) << "SearchEntry: submit query=" << query
                      << " scope=" << (scopeSystem ? scopeSystem->getName() : "all");
        if (!query.empty())
            window->pushGui(new SearchGui<GuiGlobalSearch>(session, query));
    };
    LOG(LogDebug) << "SearchEntry: open initial=" << initialText
                  << " scope=" << (scopeSystem ? scopeSystem->getName() : "all");
    if (Settings::getInstance()->getBool("VirtualKeyboard"))
        window->pushGui(new SearchGui<GuiTextEditKeyboardPopup>(
            session, verticalPosition, _("SEARCH ALL GAMES"), initialText, searchCallback, false,
            _("SEARCH"), _("START SEARCH?")));
    else
        window->pushGui(new SearchGui<GuiTextEditPopup>(session, _("SEARCH ALL GAMES"), initialText,
                                                        searchCallback, false, _("SEARCH"),
                                                        _("START SEARCH?")));
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
