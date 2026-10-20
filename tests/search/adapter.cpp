//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  adapter.cpp
//
//  Written for ES-DE-Plus. Real adapter/metadata integration with a frontend seam.
//

#include "Frontend.h"
#include "search/LibrarySearch.h"
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <thread>

static int checks {0};
static void require(bool value, const char* message)
{
    ++checks;
    if (!value) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}
int main()
{
    using namespace LibrarySearch;
    const auto path {std::filesystem::temp_directory_path() /
                     ("esde-search-adapter-" +
                      std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()))};
    Utils::FileSystem::appData = path.string();
    SystemData real, collection;
    collection.collection = true;
    auto file = std::make_unique<FileData>(&real);
    file->metadata.set("name", "Before");
    file->metadata.set("kidgame", "true");
    real.root.files = {file.get(), file.get()};
    collection.root.files = {file.get()};
    SystemData::sSystemVector = {&real, &collection};
    auto complete = []() -> const Core& {
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        do {
            engine();
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        } while (!ready() && std::chrono::steady_clock::now() < deadline);
        require(ready(), "asynchronous index becomes ready");
        return engine();
    };
    const auto& first {complete()};
    require(first.size() == 1, "adapter never duplicates collection aliases or real game handles");
    const auto original {handle(first.search("before")[0].index, currentGeneration())};
    require(resolve(original) == file.get(), "adapter resolves a live handle");
    const auto generation {currentGeneration()};
    require(engine().size() == 1 && currentGeneration() == generation,
            "query/open reuses the built snapshot");
    file->metadata.set("name", "Before");
    require(currentGeneration() == generation && resolve(original) == file.get(),
            "saving unchanged metadata preserves the snapshot and its handles");
    file->metadata.set("name", "After"); // Real MetaDataList::set, used by editor and scraper.
    require(!original.current() && !resolve(original),
            "actual metadata edit invalidates previously issued handles");
    const auto& edited {complete()};
    require(edited.search("before").empty() && edited.search("after").size() == 1,
            "next adapter search reflects actual metadata edit");
    require(!resolve(handle(0, original.generation)),
            "an old query index cannot rebind after the adapter rebuilds");
    const auto textEpoch = textGeneration.load();
    const auto builds = buildCount();
    const auto resultVersion = currentGeneration();
    file->metadata.set("favorite", "true");
    file->metadata.set("lastplayed", "20261019T120000");
    file->metadata.set("playcount", "7");
    file->metadata.set("playtime", "100");
    const auto& ranked = engine();
    require(textGeneration.load() == textEpoch && buildCount() == builds && ready(),
            "real favourite and launch metadata setters never rebuild text index");
    require(ranked.game(0).favourite && ranked.game(0).playCount == 7 &&
                ranked.recentlyPlayed() == std::vector<size_t> {0} &&
                currentGeneration() > resultVersion,
            "ranking state and public result version change in place");
    MetaDataList copy {GAME_METADATA};
    copy.set("name", "Collection alias");
    require(textGeneration.load() == textEpoch && buildCount() == builds,
            "collection metadata copies do not invalidate real library text");
    file->metadata.set("hidden", "true");
    Settings::getInstance()->values["ShowHiddenGames"] = false;
    require(engine().search("after", 200, currentFilter()).empty(),
            "hidden metadata + current settings");
    Settings::getInstance()->values["ShowHiddenGames"] = true;
    require(engine().search("after", 200, currentFilter()).size() == 1,
            "visibility setting immediately updates without rescanning");
    file->metadata.set("kidgame", "false");
    UIModeController::getInstance()->kid = true;
    require(engine().search("after", 200, currentFilter()).empty(),
            "kid-mode change filters current snapshot");
    require(!history().addQuery("private"), "adapter applies kid-mode history policy");
    UIModeController::getInstance()->kid = false;
    history().addQuery("committed");
    recordOpened(file.get());
    require(history().games().size() == 1 && history().games()[0].path == "game.zip",
            "adapter records ROM-relative game identity");
    Settings::getInstance()->values["SearchHistory"] = false;
    require(history().queries().empty() && !history().addQuery("disabled"),
            "adapter applies setting policy");
    Settings::getInstance()->values["SearchHistory"] = true;
    require(history().queries().size() == 1, "adapter preserves disabled history");
    require(buildCount() == builds && textGeneration.load() == textEpoch,
            "hidden/kid/settings changes never rebuild index");
    file->metadata.set("nogamecount", "true");
    require(complete().size() == 0, "real count-as-game edit removes the game");
    file->metadata.set("nogamecount", "false");
    require(complete().size() == 1,
            "excluded real game's metadata remains observed for re-inclusion");
    const auto old {handle(0, currentGeneration())};
    real.root.files.clear();
    collection.root.files.clear();
    file.reset(); // Destructive reload at the frontend seam; sanitizer checks stale resolution.
    require(!resolve(old) && complete().size() == 0,
            "deleted library rejects handles before rebuilding");
    std::vector<std::unique_ptr<FileData>> large;
    large.reserve(50000);
    for (size_t n {0}; n < 50000; ++n) {
        auto item = std::make_unique<FileData>(&real);
        item->path = "/roms/snes/" + std::to_string(n) + ".zip";
        item->metadata.set("name", "Snapshot Adventure " + std::to_string(n));
        real.root.files.push_back(item.get());
        large.push_back(std::move(item));
    }
    invalidate();
    double maxPump {0};
    size_t pumps {0};
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    do {
        const auto start = std::chrono::steady_clock::now();
        engine();
        maxPump = std::max(maxPump, std::chrono::duration<double, std::milli>(
                                        std::chrono::steady_clock::now() - start)
                                        .count());
        ++pumps;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    } while (!ready() && std::chrono::steady_clock::now() < deadline);
    require(ready() && engine().size() == 50000 && pumps > 1,
            "large first search remains a time-sliced snapshot/background build");
    std::cout << "ADAPTER snapshot games=50000 pumps=" << pumps << " max_ui_pump_ms=" << maxPump
              << '\n';
#ifndef __SANITIZE_ADDRESS__
    // Sanitizers deliberately trade speed for instrumentation; Release is the frame budget.
#if !defined(__has_feature)
#define __has_feature(x) 0
#endif
    if (!__has_feature(address_sanitizer))
        require(maxPump <= 16.667, "no UI pump exceeds a frame");
#endif
    real.root.files.clear();
    large.clear();
    complete();
    SystemData::sSystemVector.clear();
    std::filesystem::remove_all(path);
    std::cout << "PASS: " << checks << " adapter checks\n";
}
