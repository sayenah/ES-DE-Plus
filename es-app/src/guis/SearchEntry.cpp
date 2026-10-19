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
#include "guis/GuiSearch.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"

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

void SearchEntry::open(const std::string& initialText, SystemData* scopeSystem)
{
    if (!activeSearch.expired())
        return;
    auto session {std::make_shared<int>(0)};
    activeSearch = session;
    auto* window {Window::getInstance()};
    LOG(LogDebug) << "SearchEntry: open initial=" << initialText
                  << " scope=" << (scopeSystem ? scopeSystem->getName() : "all");
    window->pushGui(new SearchGui<GuiSearch>(session, initialText, scopeSystem));
}
