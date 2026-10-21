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
#include <ctime>
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
static double threadMilliseconds()
{
    timespec value {};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &value) != 0)
        std::abort();
    return value.tv_sec * 1000.0 + value.tv_nsec / 1000000.0;
}
int main()
{
    using namespace LibrarySearch;
    std::cout << std::unitbuf;
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
    require(first.game(0).fileStem == "game" && Utils::FileSystem::stemReads == 1 &&
                Utils::FileSystem::uiStemReads == 0 && FileData::displayNameReads == 0,
            "filename resolution runs only on the worker, not in the UI snapshot");
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
    double maxPump {0}, maxCpu {0};
    size_t pumps {0};
    auto collectLarge = [&] {
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(120);
        do {
            const auto cpu = threadMilliseconds();
            const auto beforeBuild = buildCount();
            const auto start = std::chrono::steady_clock::now();
            engine();
            const auto wall =
                std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start)
                    .count();
            const auto work = threadMilliseconds() - cpu;
            maxPump = std::max(maxPump, wall);
            maxCpu = std::max(maxCpu, work);
            if (wall > 10)
                std::cout << "SLOW UI "
                          << (buildCount() != beforeBuild ? "publish" : "snapshot/poll")
                          << " wall_ms=" << wall << " cpu_ms=" << work << '\n';
            ++pumps;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        } while (!ready() && std::chrono::steady_clock::now() < deadline);
        require(ready() && engine().size() == 50000 && pumps > 1,
                "large first search remains a time-sliced snapshot/background build");
    };
    collectLarge();
    const auto largeBuilds = buildCount();
    large.back()->metadata.set("favorite", "true");
    large.back()->metadata.set("lastplayed", "20261020T120000");
    const auto rankedCpu = threadMilliseconds();
    const auto rankedAt = std::chrono::steady_clock::now();
    engine();
    maxPump = std::max(maxPump, std::chrono::duration<double, std::milli>(
                                    std::chrono::steady_clock::now() - rankedAt)
                                    .count());
    maxCpu = std::max(maxCpu, threadMilliseconds() - rankedCpu);
    require(buildCount() == largeBuilds && ready(),
            "50k launch/favourite updates keep the existing index");
    const auto staleLarge = handle(0, currentGeneration());
    large[0]->metadata.set("name", "Metadata Changed");
    collectLarge();
    require(!resolve(staleLarge) && engine().search("metadata changed").size() == 1,
            "50k replacement invalidates handles and reflects real text edits");
    std::cout << "ADAPTER snapshot games=50000 pumps=" << pumps << " max_ui_pump_ms=" << maxPump
              << " max_ui_cpu_ms=" << maxCpu << '\n';
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
    const auto directory = path / "Directory Game.iso";
    std::filesystem::create_directory(directory);
    auto directoryGame = std::make_unique<FileData>(&real);
    directoryGame->path = directory.string();
    directoryGame->metadata.set("name", "Different metadata title");
    real.root.files = {directoryGame.get()};
    invalidate();
    require(complete().game(0).fileStem == "Directory Game.iso" &&
                engine().search("directory game iso").size() == 1,
            "worker retains the complete directory-ROM filename");
    require(Utils::FileSystem::uiStemReads == 0 && FileData::displayNameReads == 0,
            "initial and replacement indexes never resolve filenames on the UI thread");
    real.root.files.clear();
    directoryGame.reset();
    complete();
    SystemData::sSystemVector.clear();
    std::filesystem::remove_all(path);
    std::cout << "PASS: " << checks << " adapter checks\n";
}
