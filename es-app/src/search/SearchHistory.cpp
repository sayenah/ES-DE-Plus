//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchHistory.cpp
//
//  Written for ES-DE-Plus. Bounded MRU history with atomic replacement and fail-safe reads.
//

#include "search/SearchHistory.h"
#include "search/SearchCore.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <pugixml.hpp>
#include <set>
#include <system_error>
#if defined(_WIN64)
#include <windows.h>
#endif

namespace LibrarySearch
{
    namespace
    {
        constexpr size_t LIMIT {30};
        bool valid(const OpenedGame& g)
        {
            if (g.system.empty() || g.system.size() > 256 || g.path.empty() ||
                g.path.size() > 4096 || g.path.front() == '/' ||
                g.path.find('\\') != std::string::npos || (g.path.size() > 1 && g.path[1] == ':') ||
                g.path.find("://") != std::string::npos)
                return false;
            try {
                for (const auto& part : std::filesystem::u8path(g.path))
                    if (part == ".." || part == ".")
                        return false;
            }
            catch (const std::filesystem::filesystem_error&) {
                return false;
            }
            return true;
        }
        bool same(const OpenedGame& a, const OpenedGame& b)
        {
            return a.system == b.system && a.path == b.path;
        }
    } // namespace
    History::History(std::string path)
        : mPath {std::move(path)}
    {
        try {
            load();
        }
        catch (const std::filesystem::filesystem_error&) {
        }
    }
    void History::setAccess(bool enabled, bool kidMode)
    {
        mEnabled = enabled;
        mKidMode = kidMode;
    }
    const std::vector<std::string>& History::queries() const
    {
        static const std::vector<std::string> empty;
        return mEnabled && !mKidMode ? mQueries : empty;
    }
    const std::vector<OpenedGame>& History::games() const
    {
        static const std::vector<OpenedGame> empty;
        return mEnabled && !mKidMode ? mGames : empty;
    }
    void History::load()
    {
        // Special files must never turn optional history into a blocking pipe read.
        const auto path {std::filesystem::u8path(mPath)};
        std::error_code error;
        const auto status {std::filesystem::symlink_status(path, error)};
        if (error || !std::filesystem::is_regular_file(status))
            return;
        // Treat the entire file as untrusted and bound allocation before asking pugixml to parse.
        std::ifstream input {path, std::ios::binary};
        if (!input)
            return;
        input.seekg(0, std::ios::end);
        const auto size {input.tellg()};
        if (size < 0 || size > 256 * 1024)
            return;
        input.seekg(0);
        std::string bytes(static_cast<size_t>(size), '\0');
        if (!input.read(bytes.data(), size))
            return;
        pugi::xml_document doc;
        if (!doc.load_buffer(bytes.data(), bytes.size()) || !doc.child("searchHistory"))
            return;
        std::set<std::string> seen;
        for (auto node : doc.child("searchHistory").children("query")) {
            const std::string query {node.text().as_string()};
            const auto key {normalize(query)};
            if (query.size() <= 1024 && !key.empty() && seen.insert(key).second &&
                mQueries.size() < LIMIT)
                mQueries.push_back(query);
        }
        for (auto node : doc.child("searchHistory").children("game")) {
            OpenedGame game {node.attribute("system").as_string(),
                             node.attribute("path").as_string()};
            if (valid(game) && mGames.size() < LIMIT &&
                std::none_of(mGames.begin(), mGames.end(),
                             [&](const OpenedGame& g) { return same(g, game); }))
                mGames.push_back(std::move(game));
        }
    }
    bool History::save() const
    {
        try {
            const auto path {std::filesystem::u8path(mPath)};
            auto temporary {path};
            temporary += ".tmp";
            std::error_code error;
            std::filesystem::create_directories(path.parent_path(), error);
            if (error)
                return false;
            const auto status {std::filesystem::symlink_status(temporary, error)};
            if ((error && error != std::errc::no_such_file_or_directory) ||
                (std::filesystem::exists(status) && !std::filesystem::is_regular_file(status)))
                return false;
            pugi::xml_document doc;
            auto root {doc.append_child("searchHistory")};
            for (const auto& query : mQueries)
                root.append_child("query").text().set(query.c_str());
            for (const auto& game : mGames) {
                auto node {root.append_child("game")};
                node.append_attribute("system").set_value(game.system.c_str());
                node.append_attribute("path").set_value(game.path.c_str());
            }
            // Close and check the stream before replacing the last complete history file.
            std::ofstream output {temporary, std::ios::binary | std::ios::trunc};
            if (!output)
                return false;
            doc.save(output);
            output.close();
            if (output.fail()) {
                std::filesystem::remove(temporary, error);
                return false;
            }
#if defined(_WIN64)
            const bool replaced {MoveFileExW(temporary.c_str(), path.c_str(),
                                             MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) !=
                                 0};
            if (!replaced)
                std::filesystem::remove(temporary, error);
            return replaced;
#else
            std::filesystem::rename(temporary, path, error);
            if (!error)
                return true;
            std::filesystem::remove(temporary, error);
            return false;
#endif
        }
        catch (const std::filesystem::filesystem_error&) {
            return false;
        }
    }
    bool History::addQuery(const std::string& query)
    {
        if (!mEnabled || mKidMode || query.size() > 1024 || normalize(query).empty())
            return false;
        const auto key {normalize(query)};
        mQueries.erase(std::remove_if(mQueries.begin(), mQueries.end(),
                                      [&](const std::string& q) { return normalize(q) == key; }),
                       mQueries.end());
        mQueries.insert(mQueries.begin(), query);
        if (mQueries.size() > LIMIT)
            mQueries.resize(LIMIT);
        return save();
    }
    bool History::addGame(const OpenedGame& game)
    {
        if (!mEnabled || mKidMode || !valid(game))
            return false;
        mGames.erase(std::remove_if(mGames.begin(), mGames.end(),
                                    [&](const OpenedGame& g) { return same(g, game); }),
                     mGames.end());
        mGames.insert(mGames.begin(), game);
        if (mGames.size() > LIMIT)
            mGames.resize(LIMIT);
        return save();
    }
    bool History::removeQuery(const std::string& query)
    {
        const auto key {normalize(query)};
        mQueries.erase(std::remove_if(mQueries.begin(), mQueries.end(),
                                      [&](const std::string& q) { return normalize(q) == key; }),
                       mQueries.end());
        return save();
    }
    bool History::removeGame(const OpenedGame& game)
    {
        mGames.erase(std::remove_if(mGames.begin(), mGames.end(),
                                    [&](const OpenedGame& g) { return same(g, game); }),
                     mGames.end());
        return save();
    }
    bool History::clear()
    {
        mQueries.clear();
        mGames.clear();
        return save();
    }
} // namespace LibrarySearch
