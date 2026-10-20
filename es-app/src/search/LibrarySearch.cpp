//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  LibrarySearch.cpp
//
//  Written for ES-DE-Plus. Corpus snapshots from real systems, never collection aliases.
//

#include "search/LibrarySearch.h"
#include "FileData.h"
#include "Log.h"
#include "Settings.h"
#include "SystemData.h"
#include "UIModeController.h"
#include "utils/FileSystemUtil.h"

#include <chrono>
#include <deque>
#include <future>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <unordered_set>

namespace LibrarySearch
{
    namespace
    {
        using Clock = std::chrono::steady_clock;
        enum class Phase {
            Idle,
            Releasing,
            Snapshot,
            Building
        };
        struct Snapshot {
            Core core;
            uint64_t textEpoch {0}, builds {0};
            Phase phase {Phase::Idle};
            std::future<Core> worker;
            std::deque<Game> corpus;
            std::map<std::string, FileData*> files;
            std::map<const void*, size_t> metadata;
            std::deque<FileData*> byIndex;
            struct Cursor {
                FileData* folder;
                size_t next;
            };
            std::vector<Cursor> folders;
            size_t system {0};
        };
        Snapshot& snapshot()
        {
            static Snapshot value;
            return value;
        }
        std::mutex dirtyMutex;
        std::unordered_set<const void*> dirty;
        std::set<const void*> registered;
        bool metadataUpdate(const void* metadata)
        {
            std::lock_guard<std::mutex> lock {dirtyMutex};
            if (!registered.count(metadata))
                return false;
            dirty.insert(metadata);
            return true;
        }
        // Destroy payloads before a future becomes ready. Its callable itself may
        // otherwise survive until get() releases the shared state on the UI thread.
        template <typename... T> void releasePayload(T...) {}
        void retire(Snapshot& state, Core old)
        {
            std::set<const void*> oldRegistered;
            std::unordered_set<const void*> oldDirty;
            {
                std::lock_guard<std::mutex> lock {dirtyMutex};
                oldRegistered.swap(registered);
                oldDirty.swap(dirty);
            }
            state.phase = Phase::Releasing;
            state.worker = std::async(
                std::launch::async,
                [core = std::move(old), files = std::move(state.files),
                 metadata = std::move(state.metadata), byIndex = std::move(state.byIndex),
                 corpus = std::move(state.corpus), registrations = std::move(oldRegistered),
                 changes = std::move(oldDirty)]() mutable {
                    releasePayload(std::move(core), std::move(files), std::move(metadata),
                                   std::move(byIndex), std::move(corpus), std::move(registrations),
                                   std::move(changes));
                    return Core {};
                });
        }
        std::string identity(FileData* game)
        {
            return game->getSystem()->getName() + "\n" + game->getPath();
        }
        Game record(FileData* game, bool text)
        {
            Game value;
            value.lastPlayed = game->metadata.get("lastplayed");
            value.playCount = game->metadata.getInt("playcount");
            value.favourite = game->getFavorite();
            value.hidden = game->getHidden();
            value.kid = game->getKidgame();
            if (text) {
                value.id = identity(game);
                value.title = game->getName();
                value.sortName = game->getSortName();
                value.fileStem = game->getDisplayName();
                value.developer = game->metadata.get("developer");
                value.publisher = game->metadata.get("publisher");
                value.genre = game->metadata.get("genre");
                value.system = game->getSystem()->getName();
                value.systemName = game->getSystem()->getFullName();
            }
            return value;
        }
    } // namespace
    Filter currentFilter()
    {
        Filter result;
        result.showHidden = Settings::getInstance()->getBool("ShowHiddenGames");
        result.kidMode = UIModeController::getInstance()->isUIModeKid();
        return result;
    }
    bool ready()
    {
        const auto& state = snapshot();
        return state.phase == Phase::Idle && state.textEpoch == textGeneration.load();
    }
    uint64_t buildCount() { return snapshot().builds; }
    const Core& engine()
    {
        auto& state = snapshot();
        metadataObserver.store(metadataUpdate, std::memory_order_release);
        const auto epoch = textGeneration.load();
        static Filter lastFilter;
        const auto filter = currentFilter();
        if (lastFilter.showHidden != filter.showHidden || lastFilter.kidMode != filter.kidMode) {
            lastFilter = filter;
            generation.fetch_add(1);
        }
        const auto deadline = Clock::now() + std::chrono::milliseconds(3);
        if (state.phase == Phase::Building || state.phase == Phase::Releasing) {
            if (state.worker.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
                return state.core;
            auto built = state.worker.get();
            if (state.phase == Phase::Building && state.textEpoch == epoch) {
                state.core = std::move(built);
                ++state.builds;
                generation.fetch_add(1);
                state.phase = Phase::Idle;
            }
            else if (state.phase == Phase::Building) {
                retire(state, std::move(built));
                return state.core;
            }
            else {
                {
                    std::lock_guard<std::mutex> lock {dirtyMutex};
                    registered.clear();
                    dirty.clear();
                }
                state.phase = Phase::Snapshot;
                state.textEpoch = epoch;
                state.system = 0;
                state.folders.clear();
                state.corpus.clear();
                state.files.clear();
                state.metadata.clear();
                state.byIndex.clear();
            }
        }
        if (state.phase == Phase::Idle && state.textEpoch != epoch) {
            // Retire the previous index off-thread before collecting the next snapshot.
            // This avoids both a UI-thread destruction stall and two live full indexes.
            Core retired = std::move(state.core);
            state.core = Core {};
            retire(state, std::move(retired));
            return state.core;
        }
        if (state.phase == Phase::Snapshot) {
            if (state.textEpoch != epoch) {
                retire(state, Core {});
                return state.core;
            }
            while (Clock::now() < deadline) {
                if (state.folders.empty()) {
                    if (state.system == SystemData::sSystemVector.size()) {
                        state.phase = Phase::Building;
                        state.worker = std::async(
                            std::launch::async, [records = std::move(state.corpus)]() mutable {
                                Core built;
                                const auto start = Clock::now();
                                std::vector<Game> corpus;
                                corpus.reserve(records.size());
                                while (!records.empty()) {
                                    corpus.push_back(std::move(records.front()));
                                    records.pop_front();
                                }
                                releasePayload(std::move(records));
                                built.rebuild(std::move(corpus));
                                LOG(LogDebug) << "Library search index: games=" << built.size()
                                              << " build_ms="
                                              << std::chrono::duration<double, std::milli>(
                                                     Clock::now() - start)
                                                     .count();
                                return built;
                            });
                        break;
                    }
                    auto* system = SystemData::sSystemVector[state.system++];
                    if (!system || system->isCollection() || !system->isGameSystem())
                        continue;
                    state.folders.push_back({system->getRootFolder(), 0});
                }
                auto& cursor = state.folders.back();
                const auto& children = cursor.folder->getChildren();
                if (cursor.next == children.size()) {
                    state.folders.pop_back();
                    continue;
                }
                auto* file = children[cursor.next++];
                if (!file)
                    continue;
                if (file->getType() == FOLDER) {
                    state.folders.push_back({file, 0});
                    continue;
                }
                if (file->getType() != GAME)
                    continue;
                {
                    std::lock_guard<std::mutex> lock {dirtyMutex};
                    registered.insert(&file->metadata);
                }
                if (!file->getCountAsGame())
                    continue;
                auto value = record(file, true);
                if (!state.files.emplace(value.id, file).second)
                    continue;
                state.metadata.emplace(&file->metadata, state.corpus.size());
                {
                    std::lock_guard<std::mutex> lock {dirtyMutex};
                    registered.insert(&file->metadata);
                }
                state.byIndex.push_back(file);
                state.corpus.push_back(std::move(value));
            }
        }
        if (ready()) {
            std::unordered_set<const void*> changed;
            {
                std::lock_guard<std::mutex> lock {dirtyMutex};
                changed.swap(dirty);
            }
            for (const auto* metadata : changed) {
                auto it = state.metadata.find(metadata);
                if (it != state.metadata.end())
                    state.core.update(it->second, record(state.byIndex[it->second], false));
            }
        }
        return state.core;
    }
    Handle handle(size_t index, uint64_t generation)
    {
        const auto& state = snapshot();
        if (!ready() || currentGeneration() != generation || index >= state.core.size())
            return {0, {}};
        return {generation, state.core.game(index).id};
    }
    FileData* resolve(const Handle& handle)
    {
        if (!ready() || !handle.current())
            return nullptr;
        auto it = snapshot().files.find(handle.id);
        return it == snapshot().files.end() ? nullptr : it->second;
    }
    History& history()
    {
        static std::unique_ptr<History> store;
        static std::string path;
        const auto current {Utils::FileSystem::getAppDataDirectory() +
                            "/settings/search_history.xml"};
        if (!store || path != current) {
            store = std::make_unique<History>(current);
            path = current;
        }
        store->setAccess(Settings::getInstance()->getBool("SearchHistory"),
                         currentFilter().kidMode);
        return *store;
    }
    void recordOpened(FileData* game)
    {
        const auto relative {Utils::FileSystem::createRelativePath(
            game->getPath(), game->getSystem()->getStartPath(), false)};
        const auto path {relative.compare(0, 2, "./") == 0 ? relative.substr(2) : relative};
        history().addGame({game->getSystem()->getName(), path});
    }
} // namespace LibrarySearch
