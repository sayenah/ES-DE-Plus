//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchGeneration.h
//
//  Written for ES-DE-Plus. Shared invalidation seam for library loading and metadata changes.
//

#ifndef ES_APP_SEARCH_GENERATION_H
#define ES_APP_SEARCH_GENERATION_H
#include <atomic>
#include <cstdint>
#include <string>

namespace LibrarySearch
{
    inline std::atomic<uint64_t> generation {1};
    inline void invalidate() { generation.fetch_add(1, std::memory_order_relaxed); }
    inline uint64_t currentGeneration() { return generation.load(std::memory_order_relaxed); }

    struct Handle {
        uint64_t generation;
        std::string id;
        bool current() const { return generation == currentGeneration(); }
    };
} // namespace LibrarySearch
#endif
