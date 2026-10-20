//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  text-input.cpp
//
//  Written for ES-DE-Plus. Exercises production text-input activation and recovery
//  against counted SDL boundaries, including Android's pending IME hide.
//

#include <SDL2/SDL.h>
#include <cstdlib>
#include <glm/glm.hpp>
#include <iostream>
#include <string>
#include <vector>

#define LOG(level) std::cerr

namespace
{
    SDL_bool active {SDL_FALSE};
    bool keyboardShown {true};
    std::string keyboardHint;
    std::vector<bool> requests;
    SDL_Rect rectangle {};
    int stops {0};
    int checks {0};
    void require(bool condition)
    {
        if (!condition)
            std::abort();
        ++checks;
    }
} // namespace

extern "C" SDL_bool SDLCALL SDL_SetHint(const char* name, const char* value)
{
    if (std::string(name) == SDL_HINT_ENABLE_SCREEN_KEYBOARD)
        keyboardHint = value;
    return SDL_TRUE;
}
extern "C" void SDLCALL SDL_StopTextInput()
{
    active = SDL_FALSE;
    ++stops;
    // The OS still reports the visible keyboard until its hide animation finishes.
}
extern "C" void SDLCALL SDL_StartTextInput()
{
    requests.push_back(keyboardHint == "1");
    active = SDL_TRUE;
}
extern "C" SDL_bool SDLCALL SDL_IsTextInputActive() { return active; }
extern "C" SDL_bool SDLCALL SDL_IsScreenKeyboardShown(SDL_Window*)
{
    return keyboardShown ? SDL_TRUE : SDL_FALSE;
}
extern "C" void SDLCALL SDL_SetTextInputRect(const SDL_Rect* rect) { rectangle = *rect; }

struct Window {
    void* current {nullptr};
    void* peekGui() { return current; }
};
struct Renderer {
    SDL_Window* getSDLWindow() { return nullptr; }
};
class GuiSearch
{
public:
    void startTextInput(bool touch, bool requestKeyboard = true);
    void recover();
    void layout() { ++layouts; }
    Window* mWindow;
    Renderer* mRenderer;
    bool mTouch {true};
    bool mDirty {false};
    std::string mComposition {"pending"};
    glm::vec4 mFieldRect {12, 13, 100, 20};
    int layouts {0};
};

#include "search-text-input.inc"
void GuiSearch::recover()
{
#include "search-text-resume.inc"
}

int main()
{
    Window window;
    Renderer renderer;
    GuiSearch search;
    search.mWindow = &window;
    search.mRenderer = &renderer;
    window.current = &search;
    search.recover();
    require(active && search.mTouch && requests == std::vector<bool> {false});
    require(keyboardShown && keyboardHint == "0" && stops == 1 && search.layouts == 0);
    search.recover();
    require(requests.size() == 1 && stops == 1);
    search.startTextInput(true);
    require(active && search.mTouch && requests.back() && keyboardHint == "1");
    search.startTextInput(false);
    require(active && !search.mTouch && !requests.back() && search.layouts == 1);
    window.current = nullptr;
    active = SDL_FALSE;
    search.recover();
    require(!active && requests.size() == 3);
    window.current = &search;
    search.recover();
    require(active && !search.mTouch && !requests.back() && requests.size() == 4);
    require(rectangle.x == 12 && rectangle.y == 13 && rectangle.w == 100 && rectangle.h == 20 &&
            search.mComposition.empty() && search.mDirty);
    std::cout
        << "PASS: " << checks
        << " production text-input recovery checks; pending IME hide stays hidden; field requests "
           "show; active and covered screens stay unchanged\n";
}
