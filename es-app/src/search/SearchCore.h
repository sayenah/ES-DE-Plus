//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchCore.h
//
//  Written for ES-DE-Plus. Library search without frontend or SDL dependencies.
//

#ifndef ES_APP_SEARCH_CORE_H
#define ES_APP_SEARCH_CORE_H

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace LibrarySearch
{
    struct Span {
        size_t begin;
        size_t end; // Exclusive UTF-8 byte offsets in the original display name.
    };
    struct Game {
        std::string id; // Unique, stable identity within the corpus; never a frontend pointer.
        std::string title;
        std::string sortName;
        std::string fileStem;
        std::string developer;
        std::string publisher;
        std::string genre;
        std::string system;
        std::string systemName;
        std::string lastPlayed;
        int playCount {0};
        bool favourite {false};
        bool hidden {false};
        bool kid {false};
        bool countAsGame {true};
        bool collection {false};
    };
    struct Filter {
        std::string system;
        bool favouritesOnly {false};
        bool showHidden {true};
        bool kidMode {false};
    };
    enum class MatchClass {
        Exact,
        Prefix,
        OrderedWords,
        Words,
        Acronym,
        Number,
        Substring,
        Typo,
        Metadata
    };
    struct Match {
        size_t index;
        MatchClass kind;
        std::vector<Span> spans;
    };
    enum class SuggestionKind {
        Word,
        Title,
        Series,
        Developer,
        Publisher,
        Genre,
        System
    };
    struct Suggestion {
        SuggestionKind kind;
        std::string text;
    };

    // Case/accent folding for history as well as search. Articles are title semantics only.
    std::string normalize(const std::string& text);

    class Core
    {
    public:
        Core();
        ~Core();
        Core(Core&&) noexcept;
        Core& operator=(Core&&) noexcept;
        void rebuild(std::vector<Game> games);
        const Game& game(size_t index) const;
        size_t size() const;
        std::vector<Match> search(const std::string& query,
                                  size_t limit = 200,
                                  const Filter& filter = {}) const;
        std::vector<Suggestion> suggest(const std::string& query,
                                        size_t limit = 8,
                                        const Filter& filter = {}) const;
        std::vector<size_t> recentlyPlayed(size_t limit = 30, const Filter& filter = {}) const;

    private:
        struct Index;
        std::unique_ptr<Index> mIndex;
    };
} // namespace LibrarySearch
#endif
