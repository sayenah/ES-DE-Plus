//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  main.cpp
//
//  Written for ES-DE-Plus. Framework-free search correctness and measured performance gates.
//

#include "search/SearchCore.h"
#include "search/SearchGeneration.h"
#include "search/SearchHistory.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <set>
#include <string>

using namespace LibrarySearch;
namespace
{
    int checks {0};
    void require(bool value, const std::string& message)
    {
        ++checks;
        if (!value) {
            std::fprintf(stderr, "FAIL: %s\n", message.c_str());
            std::exit(1);
        }
    }
    Game game(std::string name, std::string id = "1")
    {
        Game g;
        g.id = std::move(id);
        g.title = std::move(name);
        g.sortName = g.title;
        g.fileStem = g.title;
        g.system = "snes";
        g.systemName = "Super Nintendo";
        g.developer = "Nintendo";
        g.publisher = "Acme Publishing";
        g.genre = "Action Adventure";
        g.kid = true;
        g.lastPlayed = "0";
        return g;
    }
    void match(Core& core,
               const std::string& query,
               MatchClass kind,
               const std::string& expected = "1")
    {
        const auto results {core.search(query)};
        require(!results.empty(), "match: " + query);
        require(core.game(results.front().index).id == expected, "identity: " + query);
        require(results.front().kind == kind,
                "rank: " + query +
                    " actual=" + std::to_string(static_cast<int>(results.front().kind)));
    }
    void normalization()
    {
        for (const auto& pair : {std::make_pair("Pokémon", "pokemon"),
                                 {"Straße", "strasse"},
                                 {"Æsir Øresund Œuvre Łódź", "aesir oresund oeuvre lodz"},
                                 {"Ｆｉｎａｌ　Ｆａｎｔａｓｙ", "final fantasy"},
                                 {"Rock & Roll", "rock and roll"},
                                 {"Kirby’s: Dream-Land.", "kirbys dream land"},
                                 {"ИГРА", "игра"},
                                 {"ΑΛΦΑ", "αλφα"},
                                 {"超级玛丽", "超级玛丽"}})
            require(normalize(pair.first) == pair.second, std::string("fold: ") + pair.first);
        require(normalize("e\xcc\x81") == "e", "decomposed Latin accent");
        require(normalize("が") != normalize("か"), "non-Latin marks preserved");
        Core core;
        core.rebuild({game("The Legend of Zelda")});
        match(core, "Legend of Zelda", MatchClass::Exact);
        match(core, "The Legend of Zelda", MatchClass::Exact);
        core.rebuild({game("Legend of Zelda, The")});
        match(core, "legend of zelda", MatchClass::Exact);
        core.rebuild({game("Metal-Gear")});
        match(core, "metalgear", MatchClass::Exact);
        match(core, "talgear", MatchClass::Substring);
        core.rebuild({game("Rock & Roll")});
        match(core, "rock and roll", MatchClass::Exact);
        core.rebuild({game("Rock and Roll")});
        match(core, "rock & roll", MatchClass::Exact);
    }
    void matching()
    {
        Core core;
        core.rebuild({game("Super Mario Bros. 3")});
        match(core, "super mario bros 3", MatchClass::Exact);
        match(core, "super mar", MatchClass::Prefix);
        match(core, "sup bro", MatchClass::OrderedWords);
        match(core, "bro sup", MatchClass::Words);
        match(core, "smb3", MatchClass::Acronym);
        match(core, "ario", MatchClass::Substring);
        match(core, "mraio", MatchClass::Typo);
        match(core, "nintendo", MatchClass::Metadata);
        match(core, "acme", MatchClass::Metadata);
        match(core, "adventure", MatchClass::Metadata);
        match(core, "snes mario", MatchClass::OrderedWords);
        match(core, "mario snes", MatchClass::OrderedWords);
        match(core, "super nintendo mario", MatchClass::OrderedWords);
        core.rebuild({game("Final Fantasy VII")});
        match(core, "ff7", MatchClass::Acronym);
        match(core, "ffvii", MatchClass::Acronym);
        match(core, "final fantasy 7", MatchClass::Number);
        core.rebuild({game("Final Fantasy 7")});
        match(core, "final fantasy vii", MatchClass::Number);
        core.rebuild({game("The Legend of Zelda: A Link to the Past")});
        match(core, "lttp", MatchClass::Acronym);
        match(core, "zelda lttp", MatchClass::Acronym);
        match(core, "zelad", MatchClass::Typo);
        core.rebuild({game("Mortal Kombat II")});
        match(core, "mk2", MatchClass::Acronym);
        core.rebuild({game("Castlevania: Symphony of the Night")});
        match(core, "sotn", MatchClass::Acronym);
        match(core, "sn", MatchClass::Acronym);
        match(core, "son", MatchClass::Acronym);
        match(core, "castelvania", MatchClass::Typo);
        match(core, "castxxvania", MatchClass::Typo);
        core.rebuild({game("Metroid")});
        match(core, "metriod", MatchClass::Typo);
        require(core.search("met").front().kind != MatchClass::Typo, "short tokens never fuzzy");
        core.rebuild({game("Street Fighter II")});
        match(core, "street fighter 2", MatchClass::Number);
        core.rebuild({game("Mario Maker")});
        match(core, "ma mario", MatchClass::Words);
        require(core.search("mario mario").empty(), "distinct title words required");
        for (const auto& numeral :
             {std::make_pair("I", "1"), {"IV", "4"}, {"IX", "9"}, {"XIV", "14"}, {"XX", "20"}}) {
            core.rebuild({game(std::string("Quest ") + numeral.first)});
            match(core, std::string("quest ") + numeral.second, MatchClass::Number);
        }
        auto alias = game("Unrelated");
        alias.sortName = "Hidden Sort Alias";
        alias.fileStem = "filename";
        core.rebuild({alias});
        match(core, "hidden sort alias", MatchClass::Exact);
        match(core, "filename", MatchClass::Exact);
    }
    void spans()
    {
        Core core;
        core.rebuild({game("The Pokémon: Straße & Æsir")});
        const auto results {core.search("pokemon")};
        require(results.size() == 1 && results[0].spans.size() == 1, "accent result spans");
        const auto span {results[0].spans[0]};
        require(core.game(0).title.substr(span.begin, span.end - span.begin) == "Pokémon",
                "UTF-8 original-byte mapping after article");
        auto found = core.search("strasse");
        const auto s {found[0].spans[0]};
        require(core.game(0).title.substr(s.begin, s.end - s.begin) == "Straße",
                "case expansion original-byte span");
        found = core.search("ae");
        const auto ae {found[0].spans[0]};
        require(core.game(0).title.substr(ae.begin, ae.end - ae.begin) == "Æ",
                "ligature byte span");
        core.rebuild({game("超级玛丽")});
        found = core.search("玛丽");
        require(!found.empty() && found[0].spans[0].begin == 6 && found[0].spans[0].end == 12,
                "CJK byte ranges");
        core.rebuild({game("Super Mario Bros. 3")});
        found = core.search("smb3");
        require(found[0].spans.size() == 4, "acronym spans only matching initials and numeral");
    }
    void rankingAndFilters()
    {
        Core core;
        const std::vector<std::string> rankedTitles {"Mario 2",
                                                     "Mario 2 Deluxe",
                                                     "Super Mario Bros 2",
                                                     "2 Mario",
                                                     "Mighty Alien Racing In Orbit 2",
                                                     "Mario II",
                                                     "Omario 2",
                                                     "Mraio 2",
                                                     "Other Adventure"};
        std::vector<Game> allClasses;
        for (size_t i {0}; i < rankedTitles.size(); ++i) {
            auto g = game(rankedTitles[i], std::to_string(i));
            if (i == 8) {
                g.developer = "Mario 2";
                g.favourite = true;
            }
            allClasses.push_back(g);
        }
        core.rebuild(allClasses);
        const auto orderedClasses {core.search("mario 2")};
        require(orderedClasses.size() == 9, "all nine classes match one query");
        for (size_t i {0}; i < orderedClasses.size(); ++i) {
            require(core.game(orderedClasses[i].index).id == std::to_string(i) &&
                        static_cast<size_t>(orderedClasses[i].kind) == i,
                    "all classes rank before lower-class favourites");
            if (i < 8)
                require(!orderedClasses[i].spans.empty(),
                        "every title class returns display spans");
        }
        std::vector<Game> corpus;
        for (const auto& p : {std::make_pair("Mario", "exact"),
                              {"Mario Kart", "prefix"},
                              {"Super Mario", "word"},
                              {"Mario's Castle", "substring"}})
            corpus.push_back(game(p.first, p.second));
        core.rebuild(corpus);
        const auto found {core.search("mario")};
        require(core.game(found[0].index).id == "exact", "exact before prefix");
        require(found[0].kind < found[1].kind && found[1].kind < found.back().kind,
                "class ordering");
        corpus.clear();
        auto g = game("Mario World", "plain");
        corpus.push_back(g);
        g.id = "count";
        g.playCount = 10;
        corpus.push_back(g);
        g.id = "recent";
        g.lastPlayed = "20261018T000000";
        corpus.push_back(g);
        g.id = "fav";
        g.favourite = true;
        corpus.push_back(g);
        core.rebuild(corpus);
        const auto tied {core.search("mario")};
        for (size_t i {0}; i < tied.size(); ++i)
            require(core.game(tied[i].index).id ==
                        std::vector<std::string> {"fav", "recent", "count", "plain"}[i],
                    "favourite/recent/count tie breaks");
        auto shortTitle = game("Mario", "short");
        auto longTitle = game("Mario Galaxy", "long");
        shortTitle.sortName = "z";
        longTitle.sortName = "a";
        core.rebuild({longTitle, shortTitle});
        require(core.game(core.search("mar")[0].index).id == "short",
                "shorter title before sort name");
        auto a = game("Mario AAA", "a");
        auto b = game("Mario BBB", "b");
        a.sortName = "z";
        b.sortName = "a";
        core.rebuild({a, b});
        require(core.game(core.search("mar")[0].index).id == "b", "sort-name tie break");
        a = game("Mario", "a");
        b = game("Mario", "b");
        a.system = "nes";
        a.systemName = "Nintendo Entertainment System";
        core.rebuild({a, b});
        match(core, "snes mario", MatchClass::Exact, "b");
        match(core, "mario nes", MatchClass::Exact, "a");
        Filter f;
        f.system = "nes";
        require(core.search("mario", 200, f).size() == 1, "explicit system filter");
        f.favouritesOnly = true;
        require(core.search("mario", 200, f).empty(), "favourites filter");
        a = game("Mario", "normal");
        b = a;
        b.collection = true;
        b.id = "collection";
        auto hidden = a;
        hidden.id = "hidden";
        hidden.hidden = true;
        auto adult = a;
        adult.id = "adult";
        adult.kid = false;
        auto excluded = a;
        excluded.id = "excluded";
        excluded.countAsGame = false;
        core.rebuild({a, a, b, hidden, adult, excluded});
        require(core.size() == 3, "duplicates, collections and uncounted excluded");
        f = {};
        f.showHidden = false;
        f.kidMode = true;
        require(core.search("mario", 200, f).size() == 1,
                "same hidden/kid/count/collection policy as frontend");
        require(core.recentlyPlayed().empty(), "unplayed excluded from zero state");
        a.lastPlayed = "20261018T000000";
        hidden.lastPlayed = "20261019T000000";
        core.rebuild({a, hidden});
        require(core.game(core.recentlyPlayed()[0]).id == "hidden",
                "recent sorted independently of collections");
        require(core.recentlyPlayed(30, f).size() == 1, "zero state respects visibility");
    }
    void suggestions()
    {
        Core core;
        auto a = game("Final Fantasy VII", "a");
        auto b = game("Final Fantasy VIII", "b");
        auto c = game("Mega Man X", "c");
        auto d = game("Mega Man X 2", "d");
        core.rebuild({a, b, c, d});
        auto has = [&](const std::string& q, SuggestionKind kind, const std::string& text) {
            const auto values {core.suggest(q, 100)};
            require(std::any_of(values.begin(), values.end(),
                                [&](const Suggestion& s) {
                                    return s.kind == kind && normalize(s.text) == normalize(text);
                                }),
                    "suggest kind/text: " + q + "/" + text);
            std::set<std::string> unique;
            for (const auto& s : values) {
                require(unique.insert(normalize(s.text)).second, "suggestions deduplicate");
                require(!core.search(s.text).empty(), "suggestion has results");
            }
            const auto repeated {core.suggest(q, 100)};
            require(values.size() == repeated.size(), "deterministic suggestion size");
            for (size_t i {0}; i < values.size(); ++i)
                require(values[i].kind == repeated[i].kind && values[i].text == repeated[i].text,
                        "deterministic suggestion ordering");
        };
        has("fant", SuggestionKind::Word, "fantasy");
        has("final fantasy v", SuggestionKind::Title, "Final Fantasy VII");
        has("final f", SuggestionKind::Series, "Final Fantasy");
        has("mega man", SuggestionKind::Series, "Mega Man X");
        has("nint", SuggestionKind::Developer, "Nintendo");
        has("acme", SuggestionKind::Publisher, "Acme Publishing");
        has("act", SuggestionKind::Genre, "Action Adventure");
        has("super n", SuggestionKind::System, "Super Nintendo");
        const auto complete {core.suggest("final fant", 100)};
        require(std::any_of(complete.begin(), complete.end(),
                            [](const Suggestion& s) { return s.text == "final fantasy"; }),
                "complete current token preserving preceding words");
        require(core.suggest("unrelated fant").empty(),
                "preceding words cannot produce zero-result insertions");
        a.hidden = true;
        b.hidden = true;
        core.rebuild({a, b});
        Filter f;
        f.showHidden = false;
        require(core.suggest("fant", 8, f).empty(), "suggestions hide filtered titles");
    }
    void history()
    {
        const auto directory {
            std::filesystem::temp_directory_path() /
            ("esde-search-test-" +
             std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()))};
        std::filesystem::create_directories(directory);
        const auto path {(directory / "search_history.xml").string()};
        History h(path);
        require(h.addQuery("Pokémon"), "history first write");
        require(h.addQuery("POKEMON"), "history accent dedup");
        require(h.queries().size() == 1 && h.queries()[0] == "POKEMON",
                "query MRU and original spelling");
        for (int i {0}; i < 40; ++i)
            require(h.addQuery("query " + std::to_string(i)), "history query write");
        require(h.queries().size() == 30 && h.queries()[0] == "query 39", "bounded MRU queries");
        for (int i {0}; i < 40; ++i)
            require(h.addGame({"snes", "folder/game" + std::to_string(i) + ".zip"}),
                    "history game write");
        require(h.games().size() == 30, "bounded opened games");
        require(h.addGame({"snes", "folder/game20.zip"}) &&
                    h.games()[0].path == "folder/game20.zip" && h.games().size() == 30,
                "game dedup MRU");
        require(!h.addGame({"snes", "../outside.zip"}) && !h.addGame({"snes", "/outside.zip"}),
                "relative history path boundary");
        History restored(path);
        require(restored.queries() == h.queries() && restored.games().size() == 30, "roundtrip");
        restored.setAccess(true, true);
        require(!restored.addQuery("kid") && !restored.addGame({"nes", "kid.nes"}) &&
                    restored.queries().empty() && restored.games().empty(),
                "kid mode never records or exposes history");
        restored.setAccess(false, false);
        require(!restored.addQuery("disabled") && !restored.addGame({"nes", "disabled.nes"}) &&
                    restored.queries().empty(),
                "disabled history never records or exposes");
        restored.setAccess(true, false);
        require(restored.queries() == h.queries(), "disabling preserves existing history");
        require(restored.removeQuery("QUERY 39") && restored.queries().size() == 29,
                "remove normalized query");
        require(restored.removeGame({"snes", "folder/game20.zip"}) && restored.games().size() == 29,
                "remove opened game");
        require(!std::filesystem::exists(path + ".tmp"),
                "atomic successful replacement removes temporary");
        std::filesystem::create_directory(path + ".tmp");
        require(!restored.addQuery("write failure"), "failed temp creation is nonfatal");
        History original(path);
        require(original.queries()[0] != "write failure",
                "failed write preserves complete old document");
        std::filesystem::remove(path + ".tmp");
        restored.setAccess(false, false);
        require(restored.clear(), "clear works while disabled");
        require(History(path).queries().empty() && History(path).games().empty(),
                "clear persists both lists");
        {
            std::ofstream out(path);
            out << "<searchHistory><query>bad";
        }
        History corrupt(path);
        require(corrupt.queries().empty() && corrupt.addQuery("recovered"),
                "corrupt-file recovery");
        require(History(path).queries() == std::vector<std::string> {"recovered"},
                "corrupt file replaced next write");
        History unreadable((directory / "missing" / "history.xml").string());
        require(unreadable.queries().empty() && unreadable.addQuery("created"),
                "missing file and settings directory recovery");
        std::filesystem::remove_all(directory);
    }
    void lifecycle()
    {
        Core core;
        auto a = game("Before");
        core.rebuild({a});
        Handle old {currentGeneration(), a.id};
        require(old.current() && !core.search("before").empty(), "initial generation");
        a.title = "After";
        a.sortName = a.title;
        a.fileStem = a.title;
        invalidate();
        require(!old.current(), "metadata mutation rejects old handle");
        core.rebuild({a});
        require(core.search("before").empty() && !core.search("after").empty(),
                "next snapshot reflects edit");
        Handle reloaded {currentGeneration(), a.id};
        invalidate();
        core.rebuild({});
        require(!reloaded.current() && core.search("after").empty(),
                "reload drops deleted records and rejects old handles");
        for (int n {0}; n < 100; ++n) {
            core.rebuild({game("Reallocated", std::to_string(n))});
            invalidate();
            core.rebuild({});
        }
    }
    void performance()
    {
        std::vector<Game> corpus;
        const std::vector<std::string> series {"Super Mario Bros",
                                               "Final Fantasy",
                                               "The Legend of Zelda",
                                               "Mega Man X",
                                               "Street Fighter",
                                               "Castlevania Symphony of the Night",
                                               "Metroid Prime",
                                               "Sonic the Hedgehog",
                                               "Dragon Quest",
                                               "Mortal Kombat",
                                               "Pokemon",
                                               "Donkey Kong Country",
                                               "Resident Evil",
                                               "Metal Gear Solid",
                                               "Gran Turismo",
                                               "Fire Emblem",
                                               "Kirby Dream Land",
                                               "Animal Crossing",
                                               "Tony Hawk Pro Skater",
                                               "Tales of Destiny"};
        const std::vector<std::string> subtitles {
            "",      " Deluxe",  " Championship", " The Lost Worlds", " Adventure",
            " Gold", " Origins", " Remastered",   " Special Edition", " Tournament"};
        for (int n {0}; n < 50000; ++n) {
            const auto title {series[n % series.size()] + " " + std::to_string(1 + n / 200 % 20) +
                              subtitles[n / 20 % subtitles.size()]};
            auto g = game(title, std::to_string(n));
            g.fileStem = "rom_" + std::to_string(n);
            g.system = "system" + std::to_string(n % 32);
            g.systemName = "Console " + std::to_string(n % 32);
            g.developer = std::vector<std::string> {"Nintendo", "Square Enix", "Capcom", "Sega",
                                                    "Konami"}[n % 5];
            g.publisher = "Publisher " + std::to_string(n % 25);
            g.genre = std::vector<std::string> {"Action", "Adventure", "Role Playing", "Sports",
                                                "Racing"}[n % 5];
            g.favourite = n % 17 == 0;
            g.playCount = n % 50;
            if (n % 3 == 0)
                g.lastPlayed = "202610" + std::to_string(10 + n % 19) + "T120000";
            corpus.push_back(std::move(g));
        }
        Core core;
        const auto start {std::chrono::steady_clock::now()};
        core.rebuild(std::move(corpus));
        const auto built {std::chrono::steady_clock::now()};
        const double buildMs {std::chrono::duration<double, std::milli>(built - start).count()};
        std::vector<double> times;
        std::vector<std::pair<double, std::string>> measurements;
        size_t checksum {0};
        std::set<std::string> uniqueQueries;
        for (int n {0}; n < 200; ++n) {
            std::string query {series[n % series.size()] + " " + std::to_string(1 + n / 20)};
            if (n % 10 == 0)
                query = "smb" + std::to_string(1 + n / 10);
            if (n % 10 == 1)
                query = "metriod " + std::to_string(1 + n / 10);
            if (n % 10 == 2)
                query = "system" + std::to_string(n % 32) + " zelda " + std::to_string(1 + n / 10);
            if (n % 10 == 3)
                query = "square enix publisher " + std::to_string(n / 10);
            uniqueQueries.insert(query);
            for (size_t len {1}; len <= query.size(); ++len) {
                const auto before {std::chrono::steady_clock::now()};
                const auto partial {query.substr(0, len)};
                checksum += core.search(partial).size();
                const auto searched {std::chrono::steady_clock::now()};
                checksum += core.suggest(partial).size();
                const auto after {std::chrono::steady_clock::now()};
                times.push_back(std::chrono::duration<double, std::milli>(after - before).count());
                measurements.push_back(
                    {times.back(),
                     partial + " search_ms=" +
                         std::to_string(std::chrono::duration<double, std::milli>(searched - before)
                                            .count())});
            }
        }
        std::sort(times.begin(), times.end());
        std::sort(measurements.rbegin(), measurements.rend());
        for (size_t i {0}; i < 5; ++i)
            std::printf("SLOW prefix=%s ms=%.3f\n", measurements[i].second.c_str(),
                        measurements[i].first);
        const auto p95 {times[static_cast<size_t>(times.size() * 0.95)]};
        const auto maximum {times.back()};
        std::printf("PERF games=%zu systems=32 queries=200 prefixes=%zu build_ms=%.3f "
                    "search_suggest_p95_ms=%.3f max_ms=%.3f checksum=%zu\n",
                    core.size(), times.size(), buildMs, p95, maximum, checksum);
        require(uniqueQueries.size() == 200, "200 distinct representative queries");
        require(buildMs <= 300, "50k index build <= 300ms");
        require(p95 <= 5, "per-keystroke search + suggest p95 <= 5ms");
        require(maximum <= 20, "per-keystroke search + suggest max <= 20ms");
    }
} // namespace
int main(int argc, char** argv)
{
    if (argc > 1 && std::string(argv[1]) == "--performance")
        performance();
    else {
        normalization();
        matching();
        spans();
        rankingAndFilters();
        suggestions();
        history();
        lifecycle();
    }
    std::printf("PASS: %d search checks\n", checks);
}
