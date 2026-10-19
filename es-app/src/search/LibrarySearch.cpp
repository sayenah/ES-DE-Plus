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
#include <memory>
#include <unordered_map>

namespace LibrarySearch
{
    namespace
    {
        struct Snapshot {
            Core core;
            uint64_t generation {0};
            std::unordered_map<std::string, FileData*> files;
        };
        Snapshot& snapshot()
        {
            static Snapshot value;
            return value;
        }
        std::string identity(FileData* game)
        {
            return game->getSystem()->getName() + "\n" + game->getPath();
        }
    } // namespace
    Filter currentFilter()
    {
        Filter result;
        result.showHidden = Settings::getInstance()->getBool("ShowHiddenGames");
        result.kidMode = UIModeController::getInstance()->isUIModeKid();
        return result;
    }
    const Core& engine()
    {
        auto& state {snapshot()};
        const auto generation {currentGeneration()};
        if (state.generation == generation)
            return state.core;
        const auto start {std::chrono::steady_clock::now()};
        state.files.clear();
        std::vector<Game> corpus;
        for (auto* system : SystemData::sSystemVector) {
            if (!system || system->isCollection() || !system->isGameSystem())
                continue;
            for (auto* game : system->getRootFolder()->getFilesRecursive(GAME)) {
                if (!game || !game->getCountAsGame())
                    continue;
                Game entry;
                entry.id = identity(game);
                entry.title = game->getName();
                entry.sortName = game->getSortName();
                entry.fileStem = game->getDisplayName();
                entry.developer = game->metadata.get("developer");
                entry.publisher = game->metadata.get("publisher");
                entry.genre = game->metadata.get("genre");
                entry.system = system->getName();
                entry.systemName = system->getFullName();
                entry.lastPlayed = game->metadata.get("lastplayed");
                entry.playCount = game->metadata.getInt("playcount");
                entry.favourite = game->getFavorite();
                entry.hidden = game->getHidden();
                entry.kid = game->getKidgame();
                state.files.emplace(entry.id, game);
                corpus.push_back(std::move(entry));
            }
        }
        state.core.rebuild(std::move(corpus));
        state.generation = generation;
        const auto built {std::chrono::steady_clock::now()};
        // Real corpus measurement on desktop and Android, independent of auto-collections.
        const auto probe {state.core.size() ? state.core.game(0).title : std::string {}};
        state.core.search(probe, 200, currentFilter());
        state.core.suggest(probe.substr(0, probe.find(' ')), 8, currentFilter());
        const auto queried {std::chrono::steady_clock::now()};
        LOG(LogInfo) << "Library search index: games=" << state.core.size() << " build_ms="
                     << std::chrono::duration<double, std::milli>(built - start).count()
                     << " search_suggest_ms="
                     << std::chrono::duration<double, std::milli>(queried - built).count();
        return state.core;
    }
    Handle handle(size_t index)
    {
        const auto& core {engine()};
        return {snapshot().generation, core.game(index).id};
    }
    FileData* resolve(const Handle& handle)
    {
        // Check the epoch before even looking up a pointer. A reload may reuse an address.
        if (!handle.current() || snapshot().generation != handle.generation)
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
