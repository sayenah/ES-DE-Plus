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
#include <sstream>
#include <string>
#if !defined(_WIN64)
#include <sys/stat.h>
#endif

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
        match(core, "acmepublishing", MatchClass::Metadata);
        match(core, "actionadventure", MatchClass::Metadata);
        match(core, "supernintendo mario", MatchClass::OrderedWords);
        match(core, "adventure", MatchClass::Metadata);
        match(core, "snes mario", MatchClass::OrderedWords);
        match(core, "mario snes", MatchClass::OrderedWords);
        match(core, "super nintendo mario", MatchClass::OrderedWords);
        core.rebuild({game("Super Mario 64")});
        match(core, "sm64", MatchClass::Acronym);
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
        std::string optionalWords;
        for (int n {0}; n < 1000; ++n)
            optionalWords += "the ";
        core.rebuild({game(optionalWords + "Mortal Kombat II")});
        match(core, "mk2", MatchClass::Acronym);
        auto alias = game("Unrelated");
        alias.sortName = "Hidden Sort Alias";
        alias.fileStem = "filename";
        core.rebuild({alias});
        match(core, "hidden sort alias", MatchClass::Exact);
        match(core, "filename", MatchClass::Exact);
        auto articleSystem = game("Mario", "article");
        articleSystem.systemName = "The Super Nintendo";
        auto otherSystem = game("Mario", "other");
        otherSystem.system = "nes";
        otherSystem.systemName = "Nintendo Entertainment System";
        core.rebuild({articleSystem, otherSystem});
        match(core, "the super nintendo mario", MatchClass::Exact, "article");
        require(core.search("the super nintendo mario").size() == 1,
                "system restriction ignores the full name's leading article");
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
        auto alias = game("Super Mario World");
        alias.fileStem = "smw";
        core.rebuild({alias});
        found = core.search("smw");
        require(found[0].kind == MatchClass::Exact && found[0].spans.size() == 3,
                "display highlights survive a stronger file-stem match");
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
            const size_t expected = std::vector<size_t> {0, 5, 1, 2, 3, 4, 6, 7, 8}[i];
            require(core.game(orderedClasses[i].index).id == std::to_string(expected) &&
                        static_cast<size_t>(orderedClasses[i].kind) == expected,
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
        require(core.game(core.search("mario")[0].index).id == "a", "system tie break");
        match(core, "snes mario", MatchClass::Exact, "b");
        match(core, "mario nes", MatchClass::Exact, "a");
        Filter f;
        f.system = "nes";
        require(core.search("mario", 200, f).size() == 1, "explicit system filter");
        f.favouritesOnly = true;
        require(core.search("mario", 200, f).empty(), "favourites filter");
        auto accented = game("Élan", "accented");
        accented.sortName = "a";
        auto plain = game("Elan", "plain");
        plain.sortName = "z";
        core.rebuild({plain, accented});
        require(core.game(core.search("elan")[0].index).id == "accented",
                "title length counts Unicode characters before sort-name tie break");
        accented.lastPlayed = "TTTTTTTTTTTTTTT";
        core.rebuild({accented});
        require(core.recentlyPlayed().empty(), "malformed lastplayed never enters the recent list");
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
        require(
            std::any_of(complete.begin(), complete.end(),
                        [](const Suggestion& s) { return normalize(s.text) == "final fantasy"; }),
            "complete current token preserving preceding words");
        const auto tokenOnly {core.suggest("fant v", 100)};
        require(std::any_of(tokenOnly.begin(), tokenOnly.end(),
                            [](const Suggestion& s) {
                                return s.kind == SuggestionKind::Word &&
                                       normalize(s.text) == "fant vii";
                            }),
                "word insertion preserves the preceding query token");
        has("finalfantasy v", SuggestionKind::Title, "Final Fantasy VII");
        has("acmep", SuggestionKind::Publisher, "Acme Publishing");
        require(core.suggest("unrelated fant").empty(),
                "preceding words cannot produce zero-result insertions");
        core.rebuild({game("The Legend of Zelda")});
        const auto articleCompletions {core.suggest("legend", 100)};
        require(std::any_of(articleCompletions.begin(), articleCompletions.end(),
                            [](const Suggestion& s) {
                                return s.kind == SuggestionKind::Title &&
                                       s.text == "The Legend of Zelda";
                            }),
                "whole-title completion ignores leading article");
        auto older = game("Metal Adventure", "old");
        older.lastPlayed = "20010101T120000";
        auto newer = game("Metroid Prime", "new");
        newer.lastPlayed = "20261019T120000";
        std::vector<Game> weighted {older, newer};
        for (int n {0}; n < 30; ++n) {
            auto filler = game("Other Quest", "other" + std::to_string(n));
            filler.lastPlayed = "20260101T120000";
            weighted.push_back(filler);
        }
        auto wordPosition = [&](const std::string& word) {
            const auto values = core.suggest("met", 100);
            auto it = std::find_if(values.begin(), values.end(), [&](const Suggestion& s) {
                return s.kind == SuggestionKind::Word && normalize(s.text) == word;
            });
            require(it != values.end(), "weighted word is suggested");
            return std::distance(values.begin(), it);
        };
        core.rebuild(weighted);
        require(wordPosition("metroid") < wordPosition("metal"),
                "recent zero-state games boost vocabulary words");
        weighted[0].favourite = true;
        core.rebuild(weighted);
        require(wordPosition("metal") < wordPosition("metroid"),
                "favourites boost vocabulary words");
        weighted[0].favourite = false;
        for (int n {0}; n < 3; ++n)
            weighted.push_back(game("Metal Adventure", "metal" + std::to_string(n)));
        core.rebuild(weighted);
        require(wordPosition("metal") < wordPosition("metroid"),
                "vocabulary frequency counts distinct games");
        a.hidden = true;
        b.hidden = true;
        core.rebuild({a, b});
        Filter f;
        f.showHidden = false;
        require(core.suggest("fant", 8, f).empty(), "suggestions hide filtered titles");
        core.rebuild({game("Unknown")});
        has("unk", SuggestionKind::Title, "Unknown");

        std::vector<Game> equivalent;
        for (int n {1}; n <= 2; ++n) {
            for (bool hidden : {true, false}) {
                const std::string separator {hidden ? "🔒" : "-"};
                auto g = game("Poke" + separator + "mon " + std::to_string(n),
                              std::to_string(n) + (hidden ? "hidden" : "visible"));
                g.hidden = hidden;
                g.kid = !hidden;
                g.favourite = hidden;
                g.developer = "Nin" + separator + "tendo";
                g.publisher = "Ac" + separator + "me";
                g.genre = "Act" + separator + "ion";
                g.system = hidden ? "hidden" : "visible";
                g.systemName = "Super" + separator + "Nintendo";
                equivalent.push_back(g);
            }
        }
        core.rebuild(equivalent);
        f.kidMode = true;
        for (const auto& example : {std::make_pair("poke m", SuggestionKind::Title),
                                    {"poke m", SuggestionKind::Series},
                                    {"nin", SuggestionKind::Developer},
                                    {"ac", SuggestionKind::Publisher},
                                    {"act", SuggestionKind::Genre},
                                    {"super n", SuggestionKind::System}}) {
            const auto values {core.suggest(example.first, 100, f)};
            require(std::any_of(values.begin(), values.end(),
                                [&](const Suggestion& s) { return s.kind == example.second; }),
                    "filtered equivalent suggestion retains its kind");
            for (const auto& s : values) {
                require(s.text.find("🔒") == std::string::npos,
                        "suggestion spelling comes from a visible game");
                require(!core.search(s.text, 200, f).empty(),
                        "visible suggestion spelling yields visible results");
            }
        }
    }
    void roundTwo()
    {
        std::vector<Game> games;
        std::ifstream input(SEARCH_REAL_TITLES);
        std::string line;
        while (std::getline(input, line)) {
            if (line.empty() || line.front() == '#')
                continue;
            std::stringstream fields(line);
            auto g = game("", "real" + std::to_string(games.size()));
            std::getline(fields, g.system, '|');
            std::getline(fields, g.systemName, '|');
            std::getline(fields, g.title);
            g.sortName = g.title;
            g.fileStem = g.title + " (USA)";
            g.favourite = g.title == "Street Fighter Alpha 2" || g.title == "Mega Man X3";
            games.push_back(g);
        }
        require(games.size() == 307, "307 QA real titles loaded");
        for (const auto& title : {"Street Fighter II", "Mega Man 10", "Switch", "Quake"})
            games.push_back(game(title, title));
        Core core;
        core.rebuild({game("Mega Man X")});
        require(core.search("mega man 10").empty(), "standalone X series brand is not Roman ten");
        core.rebuild(games);
        auto includes = [&](const std::string& query, const std::string& title) {
            const auto matches = core.search(query, 1000);
            return std::any_of(matches.begin(), matches.end(), [&](const auto& row) {
                return core.game(row.index).title == title;
            });
        };
        for (const auto& example :
             {std::make_pair("doom 64", "Doom 64"),
              {"doom", "Doom"},
              {"doom", "Final Doom"},
              {"doom", "Doom II"},
              {"tmnt arcade", "Teenage Mutant Ninja Turtles II: The Arcade Game"},
              {"arcade's greatest hits", "Arcade's Greatest Hits: The Atari Collection 1"},
              {"quake", "Quake"},
              {"switch", "Switch"},
              {"ff 7", "Final Fantasy VII"},
              {"ff 2", "Final Fantasy II"},
              {"mk 2", "Mortal Kombat II"},
              {"gta 3", "Grand Theft Auto III"},
              {"sf 2", "Street Fighter II"}})
            require(includes(example.first, example.second),
                    std::string("round-two real title: ") + example.first + "/" + example.second);
        require(core.game(core.search("street fighter 2")[0].index).title == "Street Fighter II",
                "whole numeral-equivalent title outranks 2010 and favourite Alpha 2");
        require(core.game(core.search("sonic 3")[0].index).title == "Sonic the Hedgehog 3",
                "whole number outranks Sonic 3D Blast");
        require(includes("mega man 10", "Mega Man 10") && !includes("mega man 10", "Mega Man X"),
                "X subseries is a letter, not ten");
        core.rebuild({game("1942")});
        require(core.search("1943").empty(), "numbers never typo matched");
        core.rebuild({game("Sons")});
        require(core.search("sonc").empty(), "four-letter tokens never typo matched");
        core.rebuild({game("Metroid")});
        require(!core.search("metriod").empty(), "five-plus character typo tolerance");
        auto before = core.version();
        auto changed = core.game(0);
        changed.favourite = true;
        changed.lastPlayed = "20261019T120000";
        changed.playCount = 7;
        core.update(0, changed);
        require(core.version() > before && core.game(0).favourite &&
                    core.recentlyPlayed().size() == 1,
                "in-place ranking update advances result version");
        core.rebuild({game("The Legend of Zelda: A Link to the Past", "a"),
                      game("The Legend of Zelda: Link's Awakening", "b"),
                      game("Streets of Rage", "c"), game("Streets of Fire", "d"),
                      game("King of Fighters", "e"), game("King of Dragons", "f"),
                      game("Theft", "g")});
        for (const auto& query : {"legend", "streets", "king"})
            for (const auto& suggestion : core.suggest(query, 100))
                require(
                    suggestion.kind != SuggestionKind::Series ||
                        (normalize(suggestion.text).size() < 3 ||
                         normalize(suggestion.text).substr(normalize(suggestion.text).size() - 3) !=
                             " of"),
                    "series never ends in a stopword");
        const auto the = core.suggest("the", 100);
        require(std::any_of(the.begin(), the.end(),
                            [](const auto& s) {
                                return s.kind == SuggestionKind::Title &&
                                       s.text.find("The Legend") == 0;
                            }),
                "the completes article-bearing titles");
        auto plain = game("Legend of Zelda", "plain");
        plain.favourite = true;
        std::vector<Game> crowded {plain, game("The Legend of Zelda", "article")};
        for (size_t n {0}; n < 100; ++n)
            crowded.push_back(game("Theft", "theft" + std::to_string(n)));
        core.rebuild(crowded);
        const auto firstArticle = core.suggest("the", 1);
        require(firstArticle.size() == 1 && firstArticle[0].kind == SuggestionKind::Title &&
                    firstArticle[0].text == "The Legend of Zelda",
                "a frequent theft completion and favourite non-article alias cannot crowd out The "
                "titles");
        core.rebuild({game("Mega Man X2", "x2"), game("Mega Man X3", "x3")});
        const auto subseries = core.suggest("mega man", 100);
        require(std::any_of(subseries.begin(), subseries.end(),
                            [](const auto& s) {
                                return s.kind == SuggestionKind::Series && s.text == "Mega Man X";
                            }),
                "series supports attached sequel numbers");
        core.rebuild({game("Sonic the Hedgehog 3", "3"), game("Sonic 3D Blast", "3d")});
        const auto sonic = core.search("sonic 3");
        require(sonic.size() == 2 && core.game(sonic[0].index).title == "Sonic the Hedgehog 3" &&
                    sonic[1].kind == MatchClass::Substring,
                "whole number outranks the final typed alphanumeric prefix");
        core.rebuild({game("Metroid II")});
        require(core.search("metriod 2").size() == 1,
                "a fuzzy word can accompany a whole equivalent numeral");
        core.rebuild({game("Pokémon", "a"), game("Pokémon Yellow", "b")});
        const auto accents = core.suggest("pok", 100);
        require(std::any_of(accents.begin(), accents.end(),
                            [](const auto& s) {
                                return s.kind == SuggestionKind::Word && s.text == "Pokémon";
                            }),
                "word suggestions retain original spelling/case/accents");
        auto dos = game("Doom");
        dos.system = "dos";
        dos.systemName = "DOS (PC)";
        core.rebuild({dos});
        const auto systems = core.suggest("do", 100);
        require(std::count_if(systems.begin(), systems.end(),
                              [](const auto& s) { return s.kind == SuggestionKind::System; }) == 1,
                "one suggestion per system");
        require(!systems.empty() && (systems.front().kind == SuggestionKind::Title ||
                                     systems.front().kind == SuggestionKind::Word),
                "short prefixes prefer titles/words");
        auto owned = game("Super Mario", "owned");
        auto titled = game("SNES Doom", "titled");
        titled.system = "md";
        titled.systemName = "Sega Genesis";
        core.rebuild({owned, titled});
        const auto shortSystem = core.search("snes");
        require(shortSystem.size() == 2 && core.game(shortSystem[0].index).id == "titled" &&
                    shortSystem[1].kind == MatchClass::Metadata,
                "short system fields match alongside titles without swallowing the query");
        const auto shortSuggestions = core.suggest("sne", 100);
        require(std::any_of(shortSuggestions.begin(), shortSuggestions.end(),
                            [](const auto& s) {
                                return s.kind == SuggestionKind::System &&
                                       s.text == "Super Nintendo";
                            }),
                "system short-name completion inserts one original full-name label");
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
        require(h.addGame({"snes", "folder/Game: Special.zip"}),
                "relative POSIX filename may contain a colon");
        require(!h.addGame({"snes", "C:/outside.zip"}) && !h.addGame({"snes", "content://outside"}),
                "drive and URI identities are not relative ROM paths");
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
#if !defined(_WIN64)
        require(::mkfifo((path + ".tmp").c_str(), 0600) == 0,
                "create non-regular temporary fixture");
        require(!restored.addQuery("pipe failure"),
                "a non-regular temporary file never blocks a history write");
        std::filesystem::remove(path + ".tmp");
        const auto pipePath {(directory / "pipe.xml").string()};
        require(::mkfifo(pipePath.c_str(), 0600) == 0, "create non-regular history fixture");
        History pipe(pipePath);
        require(pipe.queries().empty() && pipe.addQuery("repaired"),
                "a non-regular history file is ignored and replaced");
        require(std::filesystem::is_regular_file(pipePath),
                "history repair replaces the special file atomically");
#endif
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
    void performance(bool diverse = false)
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
        const std::vector<std::string> adjectives {
            "Crystal", "Shadow",  "Golden", "Mystic", "Silver", "Crimson", "Neon",
            "Lost",    "Ancient", "Cosmic", "Wild",   "Brave",  "Emerald", "Cyber",
            "Royal",   "Dark",    "Frozen", "Hidden", "Iron",   "Scarlet"};
        const std::vector<std::string> nouns {
            "Quest",   "Warriors", "Legends", "Racer",     "Adventure", "World", "Tactics",
            "Knights", "Odyssey",  "Valley",  "Hearts",    "Arena",     "Stars", "Frontier",
            "Island",  "Empire",   "Heroes",  "Chronicle", "Dreams",    "Forest"};
        auto independentTitle = [&](int n) {
            std::string result = adjectives[n % 20] + " " + nouns[n / 20 % 20] + " " +
                                 std::to_string(1980 + n / 400 % 40);
            if (n % 5 == 0) {
                result += " A";
                int value = n / 5;
                for (int letter {0}; letter < 3; ++letter) {
                    result += static_cast<char>('a' + value % 26);
                    value /= 26;
                }
                result += "ia";
            }
            return result;
        };
        std::set<std::string> uniqueTitles;
        for (int n {0}; n < 50000; ++n) {
            const auto title {diverse && n >= 25000 ? independentTitle(n) :
                                                      series[n % series.size()] + " " +
                                                          std::to_string(1 + n / 200 % 20) +
                                                          subtitles[n / 20 % subtitles.size()]};
            uniqueTitles.insert(title);
            auto g = game(title, std::to_string(n));
            g.fileStem =
                diverse ? title + (n % 4 == 0 ? " (USA)" : "") : "rom_" + std::to_string(n);
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
            if (diverse && n >= 100)
                query = independentTitle(25000 + (n - 100) * 97);
            else {
                if (n % 10 == 0)
                    query = "smb" + std::to_string(1 + n / 10);
                if (n % 10 == 1)
                    query = "metriod " + std::to_string(1 + n / 10);
                if (n % 10 == 2)
                    query =
                        "system" + std::to_string(n % 32) + " zelda " + std::to_string(1 + n / 10);
                if (n % 10 == 3)
                    query = "square enix publisher " + std::to_string(n / 10);
            }
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
        std::printf(
            "PERF corpus=%s games=%zu titles=%zu systems=32 queries=200 prefixes=%zu build_ms=%.3f "
            "search_suggest_p95_ms=%.3f max_ms=%.3f checksum=%zu\n",
            diverse ? "varied-titles" : "unique-stems", core.size(), uniqueTitles.size(),
            times.size(), buildMs, p95, maximum, checksum);
        require(uniqueQueries.size() == 200, "200 distinct representative queries");
        // D-028 amendment 2 sets the 50k build budget to 400 ms.
        require(buildMs <= 400, "50k index build <= 400ms");
        require(p95 <= 5, "per-keystroke search + suggest p95 <= 5ms");
        require(maximum <= 20, "per-keystroke search + suggest max <= 20ms");
    }
} // namespace
static void runChecks(const char* name, void (*test)())
{
    const int before {checks};
    test();
    std::printf("PASS: %s checks=%d\n", name, checks - before);
}
int main(int argc, char** argv)
{
    if (argc > 1 && std::string(argv[1]) == "--performance") {
        performance();
        performance(true);
    }
    else {
        runChecks("normalization", normalization);
        runChecks("matching", matching);
        runChecks("UTF-8 spans", spans);
        runChecks("ranking and filters", rankingAndFilters);
        runChecks("suggestions", suggestions);
        runChecks("round two", roundTwo);
        runChecks("history", history);
        runChecks("lifecycle", lifecycle);
    }
    std::printf("PASS: %d search checks\n", checks);
}
