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
    // Result version includes ranking/visibility updates; text epoch controls rebuilds.
    inline std::atomic<uint64_t> generation {1};
    inline std::atomic<uint64_t> textGeneration {1};
    using MetadataObserver = bool (*)(const void*);
    inline std::atomic<MetadataObserver> metadataObserver {nullptr};
    inline void invalidate()
    {
        textGeneration.fetch_add(1, std::memory_order_relaxed);
        generation.fetch_add(1, std::memory_order_relaxed);
    }
    inline uint64_t currentGeneration() { return generation.load(std::memory_order_relaxed); }
    inline void metadataChanged(const void* metadata, const std::string& key)
    {
        // Collection copies and unrelated media fields are not part of the text index.
        auto observer = metadataObserver.load(std::memory_order_acquire);
        const bool indexed = !observer || observer(metadata);
        if (indexed && (key == "name" || key == "sortname" || key == "developer" ||
                        key == "publisher" || key == "genre" || key == "nogamecount"))
            textGeneration.fetch_add(1, std::memory_order_relaxed);
        generation.fetch_add(1, std::memory_order_relaxed);
    }

    struct Handle {
        uint64_t generation;
        std::string id;
        bool current() const { return generation == currentGeneration(); }
    };
} // namespace LibrarySearch
#endif
