//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchHistory.h
//
//  Written for ES-DE-Plus. Additive per-user search history, independent of the frontend.
//

#ifndef ES_APP_SEARCH_HISTORY_H
#define ES_APP_SEARCH_HISTORY_H
#include <string>
#include <vector>

namespace LibrarySearch
{
    struct OpenedGame {
        std::string system;
        std::string path; // Relative to this system's ROM directory.
    };
    class History
    {
    public:
        explicit History(std::string path);
        void setAccess(bool enabled, bool kidMode);
        const std::vector<std::string>& queries() const;
        const std::vector<OpenedGame>& games() const;
        bool addQuery(const std::string& query);
        bool addGame(const OpenedGame& game);
        bool removeQuery(const std::string& query);
        bool removeGame(const OpenedGame& game);
        bool clear();

    private:
        void load();
        bool save() const;
        std::string mPath;
        bool mEnabled {true};
        bool mKidMode {false};
        std::vector<std::string> mQueries;
        std::vector<OpenedGame> mGames;
    };
} // namespace LibrarySearch
#endif
