// SPDX-License-Identifier: MIT
// ES-DE-Plus — adapted from ES-DE-Plus QA search-q1/fuzz.cpp (MIT).
#include "search/SearchCore.h"
#include <cstdio>
#include <random>
using namespace LibrarySearch;
int main()
{
    std::mt19937 rng(7);
    const std::vector<std::string> atoms = {
        "the ", "The ",  "a ",     ", The", ",",     " ",         "Ⅱ",  "II",      "ii",
        "x",    "X",     "2",      "10",    "é",     "e\xcc\x81", "ß",  "Æ",       "ﬁ",
        "İ",    "ǅ",     "ゼルダ", "伝説",  "\xff",  "\xc3",      "&",  "'",       "’",
        ":",    "-",     ".",      "Mario", "zelda", "of",        "to", "i",       "v",
        "xx",   "xviii", "🔒",     "ＡＢ",  "Ω",     "ﬀ",         "ŉ",  "\xe2\x80"};
    auto gen = [&](int maxAtoms) {
        std::string s;
        int n = rng() % maxAtoms;
        for (int i = 0; i < n; ++i)
            s += atoms[rng() % atoms.size()];
        return s;
    };
    for (int round = 0; round < 300; ++round) {
        std::vector<Game> corpus;
        int n = rng() % 60;
        for (int i = 0; i < n; ++i) {
            Game g;
            g.id = std::to_string(rng() % 70);
            g.title = gen(8);
            g.sortName = rng() % 2 ? g.title : gen(6);
            g.fileStem = gen(6);
            g.developer = gen(3);
            g.publisher = gen(3);
            g.genre = gen(3);
            g.system = "s" + std::to_string(rng() % 4);
            g.systemName = gen(3);
            g.lastPlayed = rng() % 3 ? "0" : gen(4);
            g.favourite = rng() % 5 == 0;
            g.hidden = rng() % 7 == 0;
            g.kid = rng() % 2;
            g.collection = rng() % 9 == 0;
            corpus.push_back(g);
        }
        Core core;
        core.rebuild(corpus);
        for (int q = 0; q < 40; ++q) {
            auto query = gen(5);
            Filter f;
            f.showHidden = rng() % 2;
            f.kidMode = rng() % 3 == 0;
            auto r = core.search(query, 1 + rng() % 50, f);
            for (auto& m : r)
                for (auto& s : m.spans) {
                    const auto& t = core.game(m.index).title;
                    if (s.begin >= s.end || s.end > t.size()) {
                        std::printf("BAD SPAN q=[%s] t=[%s] %zu-%zu\n", query.c_str(), t.c_str(),
                                    s.begin, s.end);
                        return 1;
                    }
                }
            auto sg = core.suggest(query, 1 + rng() % 10, f);
            for (auto& s : sg)
                if (core.search(s.text, 1000, f).empty()) {
                    std::printf("ZERO-RESULT SUGGESTION q=[%s] s=[%s]\n", query.c_str(),
                                s.text.c_str());
                    return 1;
                }
            core.recentlyPlayed(5, f);
        }
    }
    std::printf("fuzz done\n");
}
