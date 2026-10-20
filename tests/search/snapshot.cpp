//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  snapshot.cpp
//
//  Written for ES-DE-Plus; pause/re-sort regression adapted from the MIT
//  ES-DE-Plus QA search-q2/stress/pause.cpp probe.
//

#include "Frontend.h"
#include "search/LibrarySearch.h"
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <future>
#include <memory>
#include <unordered_set>

namespace
{
    unsigned checks {0};
    void require(bool value, const char* message)
    {
        ++checks;
        if (!value) {
            std::cerr << "FAIL snapshot: " << message << '\n';
            std::exit(1);
        }
    }
    template <typename Predicate> void pumpUntil(Predicate done)
    {
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(120);
        while (!done() && std::chrono::steady_clock::now() < deadline) {
            LibrarySearch::engine();
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        require(done(), "snapshot/worker reached the test checkpoint");
    }
} // namespace

int main()
{
    using namespace LibrarySearch;
    SystemData first, second, collection;
    first.name = "snes";
    second.name = "nes";
    second.fullName = "Nintendo Entertainment System";
    collection.collection = true;
    std::vector<std::unique_ptr<FileData>> folders, games;
    for (size_t n {0}; n < 4; ++n) {
        auto folder = std::make_unique<FileData>(n < 2 ? &first : &second);
        folder->type = FOLDER;
        folders.push_back(std::move(folder));
    }
    first.root.files = {folders[0].get()};
    folders[0]->files.push_back(folders[1].get()); // Include a nested folder cursor.
    second.root.files = {folders[2].get(), folders[3].get()};
    std::unordered_set<std::string> expected;
    games.reserve(40000);
    for (size_t n {0}; n < 40000; ++n) {
        auto* folder = folders[n % folders.size()].get();
        auto file = std::make_unique<FileData>(folder->system);
        file->path = "/roms/" + file->system->name + "/g" + std::to_string(n) + ".zip";
        file->metadata.set("name", "Snapshot " + std::to_string(n));
        expected.insert(file->system->name + "\n" + file->path);
        folder->files.push_back(file.get());
        games.push_back(std::move(file));
    }
    collection.root.files = {games.front().get(), games.back().get()};
    SystemData::sSystemVector = {&collection, &first, &second};
    const auto epoch = textGeneration.load();
    for (unsigned pause {0}; pause < 3; ++pause) {
        const auto before = FileData::snapshotReads;
        pumpUntil([&] { return FileData::snapshotReads > before; });
        require(!ready() && FileData::snapshotReads < games.size(),
                "search closed while record copying is incomplete");
        // Search is closed: real UI sorting changes child order without invalidation.
        for (auto& folder : folders)
            std::reverse(folder->files.begin(), folder->files.end());
        std::reverse(second.root.files.begin(), second.root.files.end());
        // Toggling a collection can shrink, grow and reorder sSystemVector.
        SystemData::sSystemVector = pause % 2 ?
                                        std::vector<SystemData*> {&second, &collection, &first} :
                                        std::vector<SystemData*> {&first, &second};
        require(textGeneration.load() == epoch, "re-sort/collection toggle has no text hook");
    }
    pumpUntil([] { return ready(); });
    const auto& indexed = engine();
    std::cout << "SNAPSHOT observed games=" << games.size() << " indexed=" << indexed.size()
              << '\n';
    require(indexed.size() == games.size(), "every real game indexed after pause/re-sort/toggle");
    bool unique {true};
    for (size_t n {0}; n < indexed.size(); ++n)
        unique = expected.erase(indexed.game(n).id) == 1 && unique;
    require(unique && expected.empty(), "every original identity appears exactly once");
    std::cout << "SNAPSHOT pause_resort_collection games=" << games.size()
              << " indexed=" << indexed.size() << " missing=" << expected.size()
              << " duplicates=" << !unique << " pauses=3\n";

    // Hold the actual build log sink so shutdown's join can be proved without a
    // timing race against the worker's normal completion.
    FrontendLog::hold.store(true);
    games.front()->metadata.set("name", "Rebuild At Shutdown");
    pumpUntil([] { return FrontendLog::waiting.load(); });
    require(!ready(), "worker is active and its result has not been published");
    auto stopping = std::async(std::launch::async, [] { shutdown(); });
    const bool joined =
        stopping.wait_for(std::chrono::milliseconds(20)) != std::future_status::ready;
    FrontendLog::hold.store(false);
    stopping.get();
    require(joined, "shutdown waited for the active worker before closing the log");
    FrontendLog::closed.store(true);
    require(FrontendLog::lateWrites.load() == 0, "no log writes after worker shutdown");
    require(!ready() && engine().size() == 0, "shutdown rejects further pumps and results");
    shutdown();
    require(!ready(), "repeated shutdown is harmless");
    std::cout << "SHUTDOWN worker_joined=1 late_logs=" << FrontendLog::lateWrites.load() << '\n';
    SystemData::sSystemVector.clear();
    std::cout << "PASS: " << checks << " snapshot/shutdown checks\n";
}
