//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchEntry.cpp
//
//  Written for ES-DE-Plus using the upstream MIT text-entry components.
//

#include "guis/SearchEntry.h"

#include "Log.h"
#include "Settings.h"
#include "SystemData.h"
#include "Window.h"
#include "guis/GuiGlobalSearch.h"
#include "guis/GuiTextEditKeyboardPopup.h"
#include "guis/GuiTextEditPopup.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"

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

void SearchEntry::open(const std::string& initialText, SystemData* scopeSystem)
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
            session, 0.0f, _("SEARCH ALL GAMES"), initialText, searchCallback, false, _("SEARCH"),
            _("START SEARCH?")));
    else
        window->pushGui(new SearchGui<GuiTextEditPopup>(session, _("SEARCH ALL GAMES"), initialText,
                                                        searchCallback, false, _("SEARCH"),
                                                        _("START SEARCH?")));
}
