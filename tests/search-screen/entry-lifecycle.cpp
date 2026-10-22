//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  entry-lifecycle.cpp
//
//  Written for ES-DE-Plus. Real SDL event-watch teardown/reinitialization regression.
//
#define SDL_MAIN_HANDLED
#include <SDL2/SDL.h>
#include <cstdlib>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

constexpr int DEVICE_KEYBOARD {-1}, TYPE_KEY {2};
struct Input {
    int device, type, id, value;
    bool configured;
    SDL_Keymod modifiers {KMOD_NONE};
};
struct InputConfig {
    int keys {0};
    std::vector<std::string> getMappedTo(const Input&)
    {
        ++keys;
        // Dispatch observation only: do not start a native IME in this headless test.
        return {"navigation"};
    }
};
class GuiComponent
{
public:
    bool acceptsSearchText() const { return true; }
    void openSearch(const std::string&) {}
};
struct Window {
    GuiComponent gui;
    static Window* getInstance()
    {
        static Window window;
        return &window;
    }
    GuiComponent* peekGui() { return &gui; }
};
#include "search-entry-declaration.inc"
#include "search-entry-implementation.inc"

int main()
{
    SDL_SetHint(SDL_HINT_VIDEODRIVER, "dummy");
    if (SDL_Init(SDL_INIT_EVENTS) != 0)
        return 2;
    InputConfig keyboard;
    {
        SearchTextInput input;
        auto* view = Window::getInstance()->peekGui();
        SDL_Event event {};
        event.type = SDL_KEYDOWN;
        event.key.keysym.sym = SDLK_f;
        for (int cycle {0}; cycle < 3; ++cycle) {
            input.prepare(view, &keyboard);
            if (SDL_PushEvent(&event) != 1 || keyboard.keys != cycle + 1) {
                std::cerr << "FAIL: search key watch lost after SDL teardown, cycle=" << cycle
                          << '\n';
                std::exit(1);
            }
            // Actual InputManager teardown hook, before Renderer calls SDL_Quit.
#include "entry-deinit.inc"
            SDL_Quit();
            if (SDL_Init(SDL_INIT_EVENTS) != 0)
                return 2;
        }
    }
    SDL_Quit();
    std::cout << "PASS: production desktop key watch survives three real SDL event lifetimes\n";
    return 0;
}
