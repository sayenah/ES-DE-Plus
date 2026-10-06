//  SPDX-License-Identifier: MIT
//
//  ES-DE Frontend
//  GuiGlobalSearch.h
//
//  Global game search for ES-DE-Plus.
//

#ifndef ES_APP_GUIS_GUI_GLOBAL_SEARCH_H
#define ES_APP_GUIS_GUI_GLOBAL_SEARCH_H

#include "GuiComponent.h"
#include "components/MenuComponent.h"

#include <string>
#include <vector>

class FileData;

class GuiGlobalSearch : public GuiComponent
{
public:
    explicit GuiGlobalSearch(const std::string& query);

    bool input(InputConfig* config, Input input) override;
    std::vector<HelpPrompt> getHelpPrompts() override;

private:
    struct SearchResult {
        FileData* game;
        int rank;
        std::string sortName;
        std::string systemName;
    };

    void populateResults();
    void launchGame(FileData* game);
    int getMatchRank(FileData* game) const;

    MenuComponent mMenu;
    std::string mQuery;
};

#endif // ES_APP_GUIS_GUI_GLOBAL_SEARCH_H
