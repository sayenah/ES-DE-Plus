// SPDX-License-Identifier: MIT
// ES-DE-Plus
// Written for ES-DE-Plus; corpus/probe/memory measurements adapted from
// ES-DE-Plus QA search-q1/perf.cpp, probe.cpp and mem.cpp (MIT).
// Region outliers adapted from QA search-q2/probe/perf.cpp and region.cpp (MIT).
#include "search/SearchCore.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <numeric>
#include <pugixml.hpp>
#include <random>
#include <set>
#include <sstream>
#include <thread>
#if defined(__APPLE__)
#include <malloc/malloc.h>
#else
#include <malloc.h>
#endif
using namespace LibrarySearch;
namespace
{
    void require(bool condition, const char* reason)
    {
        if (!condition) {
            std::fprintf(stderr, "FAIL realistic: %s\n", reason);
            std::exit(1);
        }
    }
    double heapMB()
    {
#if defined(__APPLE__)
        malloc_statistics_t stats;
        malloc_zone_statistics(nullptr, &stats);
        return stats.size_in_use / 1048576.0;
#else
        const auto stats = mallinfo2();
        return (stats.uordblks + stats.hblkhd) / 1048576.0;
#endif
    }
    std::vector<Game> realTitles()
    {
        std::ifstream input(SEARCH_REAL_TITLES);
        std::vector<Game> result;
        std::string line;
        while (std::getline(input, line)) {
            if (line.empty() || line.front() == '#')
                continue;
            std::stringstream fields(line);
            Game g;
            std::getline(fields, g.system, '|');
            std::getline(fields, g.systemName, '|');
            std::getline(fields, g.title);
            require(!g.title.empty(), "real title fixture parsed");
            g.id = "real:" + std::to_string(result.size());
            g.sortName = g.title;
            g.fileStem = g.title + " (USA) [" + g.id + "]";
            g.developer = result.size() % 3 ? "Capcom" : "Nintendo";
            g.publisher = "Publisher";
            g.genre = result.size() % 2 ? "Action" : "Platform";
            g.lastPlayed = "0";
            g.kid = true;
            g.favourite = g.title == "Mega Man X3" || g.title == "Street Fighter Alpha 2" ||
                          g.title == "Final Fantasy Tactics";
            result.push_back(std::move(g));
        }
        require(result.size() == 307, "all 307 ES-DE-Plus QA titles loaded");
        return result;
    }
    std::vector<std::string> vocabulary()
    {
        // Existing upstream title facts provide varied word roots without another
        // downloaded dictionary/dependency. Inflections extend the synthetic lexicon;
        // the Zipf distribution and query selection follow QA's realistic generator.
        pugi::xml_document doc;
        require(doc.load_file(SEARCH_MAME_TITLES, pugi::parse_default | pugi::parse_fragment),
                "existing MAME title resource read");
        std::set<std::string> words;
        for (auto game : doc.children("game")) {
            const auto text = normalize(game.child_value("realname"));
            std::istringstream input(text);
            std::string word;
            while (input >> word)
                if (word.size() >= 3 && word.size() <= 10 &&
                    std::all_of(word.begin(), word.end(),
                                [](char c) { return c >= 'a' && c <= 'z'; }))
                    words.insert(word);
        }
        const std::vector<std::string> roots(words.begin(), words.end());
        for (const auto& root : roots)
            for (const std::string suffix : {"s", "er", "ing"})
                if (root.size() + suffix.size() <= 10)
                    words.insert(root + suffix);
        require(words.size() >= 25000, "25k-word varied synthetic vocabulary available");
        std::vector<std::string> result(words.begin(), words.end());
        std::mt19937 rng(42);
        std::shuffle(result.begin(), result.end(), rng);
        result.resize(25000);
        return result;
    }
    std::vector<Game> corpus(const std::vector<std::string>& dict)
    {
        auto result = realTitles();
        result.reserve(50000);
        std::mt19937 rng(42);
        std::vector<double> weights(dict.size());
        for (size_t i {0}; i < weights.size(); ++i)
            weights[i] = 1.0 / std::pow(i + 1, 0.9);
        std::discrete_distribution<size_t> pick(weights.begin(), weights.end());
        std::uniform_int_distribution<int> length(1, 5), number(0, 9), system(0, 39),
            entity(0, 799), genre(0, 39);
        const std::vector<std::string> romans {"II", "III", "IV", "2", "3", "X", "64"};
        const std::vector<std::string> regions {" (USA)",         " (Europe)",        " (Japan)",
                                                " (USA, Europe)", " (World) (Rev 1)", ""};
        for (size_t n {0}; result.size() < 50000; ++n) {
            Game g;
            const int count = length(rng);
            for (int word {0}; word < count; ++word) {
                auto value = dict[word == 0 && n < dict.size() ? n : pick(rng)];
                value[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(value[0])));
                if (word)
                    g.title += word == 2 && n % 3 == 0 ? ": " : " ";
                g.title += value;
            }
            if (number(rng) < 3)
                g.title += " " + romans[number(rng) % romans.size()];
            g.id = "synthetic:" + std::to_string(n);
            g.sortName = g.title;
            g.fileStem = g.title + regions[n % regions.size()] + " [" + std::to_string(n) + "]";
            g.system = "sys" + std::to_string(system(rng));
            g.systemName = "Console Number " + g.system.substr(3);
            g.developer = "Dev " + dict[entity(rng)];
            g.publisher = "Pub " + dict[entity(rng)];
            g.genre = "Genre " + dict[genre(rng)];
            g.lastPlayed = n % 20 == 0 ? "202610" + std::to_string(10 + n % 19) + "T120000" : "0";
            g.playCount = n % 7;
            g.favourite = n % 50 == 0;
            g.kid = true;
            result.push_back(std::move(g));
        }
        return result;
    }
    void performance()
    {
        const auto dict = vocabulary();
        auto games = corpus(dict);
        std::set<std::string> systems, words;
        for (const auto& g : games) {
            systems.insert(g.system);
            std::istringstream in(normalize(g.title));
            std::string word;
            while (in >> word)
                words.insert(word);
        }
        require(words.size() >= 20000 && systems.size() >= 30,
                "realistic vocabulary/system coverage");
        std::vector<std::string> queries;
        for (size_t i {0}; i < 200; ++i)
            queries.push_back(games[(i * 7919) % games.size()].title.substr(0, 24));
        for (const std::string q : {"zelad", "metriod", "castelvania", "a", "e", "s", "th", "the",
                                    "an", "sup", "ff 7", "doom 64", "europa", "japon", "usance s"})
            queries.push_back(q);
        require(std::set<std::string>(queries.begin(), queries.end()).size() >= 200,
                "at least 200 distinct representative queries");
        Core core;
        const auto start = std::chrono::steady_clock::now();
        core.rebuild(std::move(games));
        const auto built = std::chrono::steady_clock::now();
        const double build = std::chrono::duration<double, std::milli>(built - start).count();
        std::vector<std::pair<double, std::string>> times;
        size_t checksum {0};
        for (const auto& q : queries)
            for (size_t n {1}; n <= q.size(); ++n) {
                const auto partial = q.substr(0, n);
                const auto a = std::chrono::steady_clock::now();
                checksum += core.search(partial).size();
                const auto searched = std::chrono::steady_clock::now();
                checksum += core.suggest(partial).size();
                const double elapsed =
                    std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - a)
                        .count();
                if (std::getenv("SEARCH_PROFILE") && elapsed > 15)
                    std::fprintf(stderr, "profile %.3f search=%.3f [%s]\n", elapsed,
                                 std::chrono::duration<double, std::milli>(searched - a).count(),
                                 partial.c_str());
                times.emplace_back(
                    std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - a)
                        .count(),
                    partial);
            }
        for (const std::string query : {"europa", "japon", "usance s"}) {
            double maximum {0};
            for (const auto& sample : times)
                if (sample.second == query)
                    maximum = std::max(maximum, sample.first);
            const auto results = core.search(query);
            std::vector<Game> titleRecords;
            for (const auto& match : results) {
                auto original = core.game(match.index);
                original.fileStem = original.title;
                titleRecords.push_back(std::move(original));
            }
            Core titleOnly;
            titleOnly.rebuild(std::move(titleRecords));
            require(titleOnly.search(query, results.size() + 1).size() == results.size(),
                    "region outliers match titles/metadata rather than filename tags");
            const auto metadata = std::count_if(results.begin(), results.end(), [](const Match& m) {
                return m.kind == MatchClass::Metadata;
            });
            std::printf("REGION query=[%s] search_suggest_ms=%.3f results=%zu metadata=%zu "
                        "file_tag_only=0\n",
                        query.c_str(), maximum, results.size(), static_cast<size_t>(metadata));
        }
        std::sort(times.begin(), times.end());
        const double p95 = times[times.size() * 95 / 100].first;
        std::printf("PERF realistic games=%zu vocabulary=%zu systems=%zu queries=%zu prefixes=%zu "
                    "build_ms=%.3f search_suggest_p95_ms=%.3f max_ms=%.3f checksum=%zu\n",
                    core.size(), words.size(), systems.size(), queries.size(), times.size(), build,
                    p95, times.back().first, checksum);
        for (size_t i = times.size() - 5; i < times.size(); ++i)
            std::printf("SLOW realistic %.3f [%s]\n", times[i].first, times[i].second.c_str());
        std::fflush(stdout);
        require(build <= 400, "index build <=400ms");
        require(p95 <= 5, "combined p95 <=5ms");
        require(times.back().first <= 20, "combined max <=20ms");
    }
    void memory()
    {
        const auto dict = vocabulary();
        const double baseline = heapMB();
        std::atomic<bool> running {true};
        std::atomic<double> maximum {baseline};
        std::thread sampler([&] {
            while (running.load()) {
                maximum.store(std::max(maximum.load(), heapMB()));
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
        });
        Core core;
        core.rebuild(corpus(dict));
        const double steady = heapMB() - baseline;
        // Exercise the production replacement lifecycle: retire the old index before
        // snapshotting its replacement, rather than retaining two complete corpora.
        core.clear();
        core.rebuild(corpus(dict));
        running.store(false);
        sampler.join();
        const double peak = maximum.load() - baseline;
        std::printf(
            "MEMORY realistic games=%zu steady_mb=%.3f peak_mb=%.3f ratio=%.3f sample_us=100\n",
            core.size(), steady, peak, peak / steady);
        std::fflush(stdout);
        require(steady <= 40, "steady heap <=40MB");
        require(peak <= steady * 1.5, "peak heap <=1.5x steady");
    }
} // namespace
int main(int argc, char** argv)
{
    if (argc > 1 && std::string(argv[1]) == "--memory")
        memory();
    else
        performance();
}
