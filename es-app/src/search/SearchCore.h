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
        std::string genre;
        std::string developer;
        std::string publisher;
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

    struct SystemCount {
        std::string system;
        std::string name;
        size_t count {0};
    };
    struct Results {
        std::vector<Match> matches;
        std::vector<SystemCount> systems;
        size_t total {0};
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
        // Counts include every matching game, independent of the display limit.
        Results query(const std::string& query,
                      size_t limit = 200,
                      const Filter& filter = {}) const;
        std::vector<Match> closest(const std::string& query,
                                   size_t limit = 3,
                                   const Filter& filter = {}) const;
        std::vector<size_t> browse(size_t limit = 30, const Filter& filter = {}) const;
        std::vector<Suggestion> suggest(const std::string& query,
                                        size_t limit = 8,
                                        const Filter& filter = {}) const;
        std::vector<size_t> recentlyPlayed(size_t limit = 30, const Filter& filter = {}) const;

    private:
        std::vector<Match> find(const std::string& query,
                                size_t limit,
                                const Filter& filter,
                                bool firstOnly,
                                const std::vector<size_t>* support = nullptr,
                                std::vector<uint8_t>* matchingGames = nullptr,
                                Results* counts = nullptr) const;
        struct Index;
        std::unique_ptr<Index> mIndex;
    };
} // namespace LibrarySearch
#endif
