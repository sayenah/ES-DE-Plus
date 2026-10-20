//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  Frontend.h
//
//  Written for ES-DE-Plus. Minimal frontend seam for the real adapter and MetaDataList.
//

#ifndef SEARCH_TEST_FRONTEND_H
#define SEARCH_TEST_FRONTEND_H
#include "MetaData.h"
#include "search/SearchGeneration.h"
#include <iostream>
#include <map>
#include <string>
#include <vector>

class FileData;
class RootFolder
{
public:
    std::vector<FileData*> files;
    const std::vector<FileData*>& getChildren() const { return files; }
};
class SystemData
{
public:
    inline static std::vector<SystemData*> sSystemVector;
    RootFolder root;
    bool collection {false};
    bool gameSystem {true};
    std::string name {"snes"};
    std::string fullName {"Super Nintendo"};
    std::string start {"/roms/snes"};
    bool isCollection() { return collection; }
    bool isGameSystem() { return gameSystem; }
    FileData* getRootFolder();
    const std::string& getName() { return name; }
    const std::string& getFullName() { return fullName; }
    const std::string& getStartPath() { return start; }
};
constexpr int GAME {1}, FOLDER {2};
class FileData
{
public:
    MetaDataList metadata {GAME_METADATA};
    SystemData* system;
    std::vector<FileData*> files;
    int type {GAME};
    const std::vector<FileData*>* sourceChildren {nullptr};
    const std::vector<FileData*>& getChildren() const
    {
        return sourceChildren ? *sourceChildren : files;
    }
    int getType() const { return type; }
    std::string path {"/roms/snes/game.zip"};
    explicit FileData(SystemData* s)
        : system {s}
    {
    }
    ~FileData() { LibrarySearch::invalidate(); }
    bool getCountAsGame() { return metadata.get("nogamecount") != "true"; }
    bool getFavorite() { return metadata.get("favorite") == "true"; }
    bool getHidden() { return metadata.get("hidden") == "true"; }
    bool getKidgame() { return metadata.get("kidgame") == "true"; }
    const std::string& getName() { return metadata.get("name"); }
    const std::string& getSortName()
    {
        return metadata.get("sortname").empty() ? getName() : metadata.get("sortname");
    }
    std::string getDisplayName() { return "game"; }
    const std::string& getPath() { return path; }
    SystemData* getSystem() { return system; }
};
inline FileData* SystemData::getRootFolder()
{
    // Keep the seam's root compatible with the real folder traversal API.
    static std::map<SystemData*, FileData> roots;
    auto it = roots.try_emplace(this, this).first;
    it->second.type = FOLDER;
    it->second.sourceChildren = &root.files;
    return &it->second;
}
class Settings
{
public:
    std::map<std::string, bool> values {{"ShowHiddenGames", true}, {"SearchHistory", true}};
    static Settings* getInstance()
    {
        static Settings s;
        return &s;
    }
    bool getBool(const std::string& key) { return values[key]; }
};
class UIModeController
{
public:
    bool kid {false};
    static UIModeController* getInstance()
    {
        static UIModeController s;
        return &s;
    }
    bool isUIModeKid() { return kid; }
};
namespace Utils
{
    namespace FileSystem
    {
        inline std::string appData;
        inline std::string getAppDataDirectory() { return appData; }
        inline std::string createRelativePath(const std::string& path,
                                              const std::string& root,
                                              bool)
        {
            return path.compare(0, root.size() + 1, root + "/") == 0 ?
                       "./" + path.substr(root.size() + 1) :
                       path;
        }
        inline std::string resolveRelativePath(const std::string& path, const std::string&, bool)
        {
            return path;
        }
    } // namespace FileSystem
} // namespace Utils
#define LOG(level) std::cout
#endif
