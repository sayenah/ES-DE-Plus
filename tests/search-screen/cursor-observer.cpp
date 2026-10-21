//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  cursor-observer.cpp
//
//  Written for ES-DE-Plus. Verify the observer reads the visible active game list,
//  after search closes, only while runtime Debug logging is enabled.
//
#include <cstdlib>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>

constexpr int LogDebug {1};
std::ostringstream output;
#define LOG(level) output
struct Log {
    inline static int level {LogDebug};
    static int getReportingLevel() { return level; }
};
struct SystemData {
    std::string getName() { return "nes"; }
};
struct FileData {
    std::string name;
    SystemData* system;
    SystemData* getSystem() { return system; }
    std::string getName() { return name; }
    std::string getPath() { return name + ".nes"; }
};
struct GamelistView {
    FileData* cursor;
    FileData* getCursor() { return cursor; }
};
struct ViewController {
    enum class ViewMode {
        GAMELIST,
        SYSTEM_SELECT
    };
    struct State {
        ViewMode viewing {ViewMode::GAMELIST};
        SystemData system;
        SystemData* getSystem() const { return const_cast<SystemData*>(&system); }
    } state;
    std::shared_ptr<GamelistView> view;
    static ViewController* getInstance()
    {
        static ViewController value;
        return &value;
    }
    const State& getState() { return state; }
    std::shared_ptr<GamelistView> getGamelistView(SystemData* system)
    {
        if (system != &state.system)
            std::abort();
        return view;
    }
};
struct Window {
    void* top {ViewController::getInstance()};
    static Window* getInstance()
    {
        static Window value;
        return &value;
    }
    void* peekGui() { return top; }
};
namespace SearchEntry
{
    void observeGamelistCursor();
}
#include "cursor-observer.inc"
int main()
{
    auto* controller = ViewController::getInstance();
    FileData selected {"Actual", &controller->state.system};
    FileData other {"Changed", &controller->state.system};
    controller->view = std::make_shared<GamelistView>(GamelistView {&selected});
    SearchEntry::observeGamelistCursor();
    if (output.str().find("system=nes game=Actual path=Actual.nes") == std::string::npos)
        return 1;
    controller->view->cursor = &other;
    output.str("");
    SearchEntry::observeGamelistCursor();
    if (output.str().find("game=Changed path=Changed.nes") == std::string::npos)
        return 1;
    for (int mode : {0, 1, 2}) {
        output.str("");
        Log::level = mode == 0 ? 0 : LogDebug;
        controller->state.viewing = mode == 1 ? ViewController::ViewMode::SYSTEM_SELECT :
                                                ViewController::ViewMode::GAMELIST;
        Window::getInstance()->top = mode == 2 ? nullptr : controller;
        SearchEntry::observeGamelistCursor();
        if (!output.str().empty())
            return 1;
    }
    std::cout << "PASS: actual active cursor, changed cursor, runtime Debug, game-list state and "
                 "top GUI ownership\n";
}
