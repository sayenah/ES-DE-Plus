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

namespace SearchEntry
{
    // WO-S2 replaces the legacy popup/results flow behind this single entry point.
    void open(const std::string& initialText, SystemData* scopeSystem);
} // namespace SearchEntry

#endif // ES_APP_GUIS_SEARCH_ENTRY_H
