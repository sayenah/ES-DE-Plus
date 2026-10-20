// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Executes production hook bodies extracted
// at build time; these minimal collaborators replace the SDL frontend graph.
#include "search/SearchGeneration.h"
#include <cassert>
#include <iostream>
#include <map>
#include <string>
#include <vector>
class SystemData
{
public:
    static std::vector<SystemData*> sSystemVector;
    bool collection {false};
    bool isCollection() const { return collection; }
    bool getFlattenFolders() const { return false; }
    static void deleteSystems();
};
std::vector<SystemData*> SystemData::sSystemVector;
enum {
    GAME,
    FOLDER
};
class FileData
{
public:
    SystemData* mSystem;
    FileData* mParent {nullptr};
    int mType;
    std::string key;
    std::vector<FileData*> mChildren;
    std::map<std::string, FileData*> mChildrenByFilename;
    FileData(SystemData* system, int type, std::string name)
        : mSystem(system)
        , mType(type)
        , key(std::move(name))
    {
    }
    ~FileData();
    const std::string& getKey() const { return key; }
    FileData* getParent() const { return mParent; }
    void addChild(FileData* file);
    void removeChild(FileData* file);
};
#include "search_hooks.inc"
int main()
{
    unsigned checks {0};
    auto check = [&](bool value) {
        if (!value)
            std::abort();
        ++checks;
    };
    SystemData real, collection;
    collection.collection = true;
    {
        FileData folder(&real, FOLDER, "root");
        auto* game = new FileData(&real, GAME, "game");
        auto epoch = LibrarySearch::textGeneration.load();
        folder.addChild(game);
        check(LibrarySearch::textGeneration.load() > epoch);
        epoch = LibrarySearch::textGeneration.load();
        auto* duplicate = new FileData(&real, GAME, "game");
        folder.addChild(duplicate);
        check(LibrarySearch::textGeneration.load() == epoch);
        delete duplicate;
        epoch = LibrarySearch::textGeneration.load();
        folder.removeChild(game);
        check(LibrarySearch::textGeneration.load() > epoch);
        epoch = LibrarySearch::textGeneration.load();
        delete game;
        check(LibrarySearch::textGeneration.load() > epoch);
    }
    auto epoch = LibrarySearch::textGeneration.load();
    {
        FileData folder(&collection, FOLDER, "collection");
        folder.addChild(new FileData(&collection, GAME, "copy"));
    }
    check(LibrarySearch::textGeneration.load() == epoch);
    SystemData::sSystemVector.push_back(new SystemData);
    SystemData::deleteSystems();
    check(LibrarySearch::textGeneration.load() > epoch && SystemData::sSystemVector.empty());
    std::cout << "PASS: " << checks << " production FileData/SystemData hook checks\n";
}
