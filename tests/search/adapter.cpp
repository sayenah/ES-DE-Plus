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
    const auto& first {engine()};
    require(first.size() == 1, "adapter never duplicates collection aliases or real game handles");
    const auto original {handle(first.search("before")[0].index)};
    require(resolve(original) == file.get(), "adapter resolves a live handle");
    const auto generation {currentGeneration()};
    require(engine().size() == 1 && currentGeneration() == generation,
            "query/open reuses the built snapshot");
    file->metadata.set("name", "After"); // Real MetaDataList::set, used by editor and scraper.
    require(!original.current() && !resolve(original),
            "actual metadata edit invalidates previously issued handles");
    const auto& edited {engine()};
    require(edited.search("before").empty() && edited.search("after").size() == 1,
            "next adapter search reflects actual metadata edit");
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
    const auto old {handle(0)};
    real.root.files.clear();
    collection.root.files.clear();
    file.reset(); // Destructive reload at the frontend seam; sanitizer checks stale resolution.
    require(!resolve(old) && engine().size() == 0,
            "deleted library rejects handles before rebuilding");
    SystemData::sSystemVector.clear();
    std::filesystem::remove_all(path);
    std::cout << "PASS: " << checks << " adapter checks\n";
}
