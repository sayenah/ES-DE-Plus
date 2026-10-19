//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  LibrarySearch.h
//
//  Written for ES-DE-Plus. Frontend adapter and generation-checked game handles.
//

#ifndef ES_APP_LIBRARY_SEARCH_H
#define ES_APP_LIBRARY_SEARCH_H
#include "search/SearchCore.h"
#include "search/SearchGeneration.h"
#include "search/SearchHistory.h"

class FileData;
namespace LibrarySearch
{
    const Core& engine();
    Filter currentFilter();
    // Use the generation captured with the query; stale result indices never rebind.
    Handle handle(size_t index, uint64_t generation);
    FileData* resolve(const Handle& handle);
    History& history();
    void recordOpened(FileData* game);
} // namespace LibrarySearch
#endif
