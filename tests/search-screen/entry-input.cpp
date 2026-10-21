//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  entry-input.cpp
//
//  Written for ES-DE-Plus. Exercise production search entry at counted SDL boundaries.
//
#define SDL_MAIN_HANDLED
#include <SDL2/SDL.h>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

namespace
{
    bool active {false};
    int starts {0}, stops {0}, watches {0}, checks {0};
    SDL_EventFilter watch {nullptr};
    void* watchContext {nullptr};
    std::string hint;
    void require(bool condition)
    {
        if (!condition)
            std::abort();
        ++checks;
    }
} // namespace
extern "C" SDL_bool SDLCALL SDL_IsTextInputActive() { return active ? SDL_TRUE : SDL_FALSE; }
extern "C" void SDLCALL SDL_StartTextInput()
{
    active = true;
    ++starts;
}
extern "C" void SDLCALL SDL_StopTextInput()
{
    active = false;
    ++stops;
}
extern "C" const char* SDLCALL SDL_GetHint(const char*)
{
    return hint.empty() ? nullptr : hint.c_str();
}
extern "C" SDL_bool SDLCALL SDL_SetHint(const char*, const char* value)
{
    hint = value ? value : "";
    return SDL_TRUE;
}
extern "C" SDL_threadID SDLCALL SDL_ThreadID()
{
    return std::hash<std::thread::id> {}(std::this_thread::get_id());
}
extern "C" void SDLCALL SDL_AddEventWatch(SDL_EventFilter filter, void* context)
{
    watch = filter;
    watchContext = context;
    ++watches;
}
extern "C" void SDLCALL SDL_DelEventWatch(SDL_EventFilter filter, void* context)
{
    require(filter == watch && context == watchContext);
    watch = nullptr;
    watchContext = nullptr;
    --watches;
}
constexpr int DEVICE_KEYBOARD {-1}, TYPE_KEY {2};
struct Input {
    int device, type, id, value;
    bool configured;
    SDL_Keymod modifiers {KMOD_NONE};
};
struct InputConfig {
    int mapped {SDLK_y};
    std::vector<std::string> getMappedTo(const Input& input)
    {
        return input.id == mapped ? std::vector<std::string> {"y"} : std::vector<std::string> {};
    }
};
class GuiComponent
{
public:
    bool browsing {true};
    std::vector<std::string> opened;
    bool acceptsSearchText() const { return browsing; }
    void openSearch(const std::string& text)
    {
        opened.push_back(text);
        browsing = false;
        SDL_StartTextInput();
    }
};
#include "search-entry-declaration.inc"
#include "search-entry-implementation.inc"

int main()
{
    InputConfig keyboard;
    GuiComponent view, modal;
    modal.browsing = false;
    {
        SearchTextInput input;
        input.prepare(&view, &keyboard);
#if defined(__ANDROID__)
        require(active && starts == 1 && watches == 0 && hint.empty());
        // Android commits before key-down; retain layout spelling and queued text.
        require(input.text("É", &view));
        input.keyDown(&keyboard, {DEVICE_KEYBOARD, TYPE_KEY, SDLK_e, 1, false}, true, &view, &view);
        require(view.opened == std::vector<std::string> {"É"} && active);
        input.keyUp();
        require(active && stops == 0);
#else
        require(!active && starts == 0 && watches == 1);
        SDL_Event event {};
        event.type = SDL_KEYDOWN;
        event.key.keysym.sym = SDLK_q; // Physical layout can commit an AZERTY "A".
        event.key.keysym.mod = KMOD_SHIFT;
        watch(watchContext, &event);
        require(active && starts == 1); // Before PollEvent/keyDown returns.
        Input key {DEVICE_KEYBOARD, TYPE_KEY, SDLK_q, 1, false};
        key.modifiers = KMOD_SHIFT;
        input.keyDown(&keyboard, key, true, &view, &view);
        require(input.text("A", &view));
        input.keyUp();
        require(active && view.opened == std::vector<std::string> {"A"});
        SDL_StopTextInput();
        view.browsing = true;
        input.prepare(&view, &keyboard);
        require(!active);
        for (const auto& ignored :
             std::vector<std::pair<int, SDL_Keymod>> {{SDLK_y, KMOD_NONE},
                                                      {SDLK_SPACE, KMOD_NONE},
                                                      {SDLK_INSERT, KMOD_SHIFT},
                                                      {SDLK_f, KMOD_CTRL},
                                                      {SDLK_f, KMOD_ALT},
                                                      {SDLK_f, KMOD_GUI}}) {
            event.key.keysym.sym = ignored.first;
            event.key.keysym.mod = ignored.second;
            watch(watchContext, &event);
            require(!active);
        }
        event.key.keysym.sym = SDLK_f;
        event.key.keysym.mod = KMOD_NONE;
        std::thread foreign([&] { watch(watchContext, &event); });
        foreign.join();
        require(!active);
        event.key.repeat = 1;
        watch(watchContext, &event);
        require(!active);
        event.key.repeat = 0;
        watch(watchContext, &event);
        require(active);
        input.prepare(nullptr, nullptr); // Keyboard input disabled while browsing.
        require(!active);
        watch(watchContext, &event);
        require(!active);
        input.prepare(&view, &keyboard);
        watch(watchContext, &event);
        require(active);
        input.keyDown(&keyboard, {DEVICE_KEYBOARD, TYPE_KEY, SDLK_f, 1, false}, true, &view, &view);
        input.keyUp(); // Dead key/no commit: the temporary IME must stop.
        require(!active);
        watch(watchContext, &event);
        input.keyRepeat();
        require(!active);
        watch(watchContext, &event);
        input.keyDown(&keyboard, {DEVICE_KEYBOARD, TYPE_KEY, SDLK_f, 1, false}, true, &view, &view);
        require(input.text("/", &view));
        require(view.opened.size() == 2 && view.opened.back().empty());
        input.keyUp();
        require(active);
        SDL_StopTextInput();
        view.browsing = true;
        input.prepare(&view, &keyboard);
        watch(watchContext, &event);
        input.keyDown(&keyboard, {DEVICE_KEYBOARD, TYPE_KEY, SDLK_f, 1, false}, true, &view, &view);
        input.editing(&view);
        require(active && view.opened.size() == 3 && view.opened.back().empty());
        input.keyUp();
        require(active); // The field owns CJK composition across key release.
        // An actual modal field keeps its own text session.
        input.prepare(&modal, &keyboard);
        require(active);
        watch(watchContext, &event);
        require(active && view.opened.size() == 3);
#endif
    }
    require(watches == 0);
    std::cout << "PASS: " << checks << " production search-entry input checks\n";
    return 0;
}
