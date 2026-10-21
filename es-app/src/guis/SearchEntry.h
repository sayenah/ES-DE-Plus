//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchEntry.h
//
//  Written for ES-DE-Plus. Shared entry seam for all search entry points.
//

#ifndef ES_APP_GUIS_SEARCH_ENTRY_H
#define ES_APP_GUIS_SEARCH_ENTRY_H

#include <string>

class SystemData;
class FileData;
class ComponentList;
class GamelistView;

namespace SearchEntry
{
    // WO-S2 replaces the legacy popup/results flow behind this single entry point.
    void open(const std::string& initialText,
              SystemData* scopeSystem,
              float verticalPosition = 0.0f);
    bool preservesPasskeyY();
    void observeOptionsFocus(ComponentList* list);
    void observeGamelistCursor();
    void logFavoritesCollection(FileData* source, bool enabled, SystemData* favorites);
    void logFavoriteAction(FileData* source, bool editing, GamelistView* view);
} // namespace SearchEntry

#endif // ES_APP_GUIS_SEARCH_ENTRY_H
