//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  entry-input.cpp
//
//  Written for ES-DE-Plus. Exercise production search entry at counted SDL boundaries.
//
#define SDL_MAIN_HANDLED
#include <SDL2/SDL.h>
#include <cstdio>
#include <cstdlib>
#include <deque>
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
    std::deque<SDL_Event> events;
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
    // SDL disables and flushes these event types when text input stops.
    for (auto event = events.begin(); event != events.end();) {
        if (event->type == SDL_TEXTINPUT || event->type == SDL_TEXTEDITING)
            event = events.erase(event);
        else
            ++event;
    }
}
extern "C" SDL_bool SDLCALL SDL_HasEvents(Uint32 first, Uint32 last)
{
    for (const auto& event : events) {
        if (event.type >= first && event.type <= last)
            return SDL_TRUE;
    }
    return SDL_FALSE;
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
    std::string composition;
    bool acceptsSearchText() const { return browsing; }
    void openSearch(const std::string& text)
    {
        opened.push_back(text);
        browsing = false;
        SDL_StartTextInput();
    }
    void textInput(const std::string& text) { opened.back() += text; }
    void textEditing(const std::string& text) { composition = text; }
};
struct Window {
    GuiComponent* gui {nullptr};
    static Window* getInstance()
    {
        static Window window;
        return &window;
    }
    GuiComponent* peekGui() { return gui; }
};
#include "search-entry-declaration.inc"
#include "search-entry-implementation.inc"

#if !defined(__ANDROID__) && !defined(__IOS__)
namespace
{
    // Model the SDL pump: watches run before key-down and translated text are
    // queued. InputManager then drains that entire queue in the same frame.
    void pushKey(Uint32 type, SDL_Keycode key, SDL_Keymod modifiers = KMOD_NONE)
    {
        SDL_Event event {};
        event.type = type;
        event.key.keysym.sym = key;
        event.key.keysym.mod = modifiers;
        watch(watchContext, &event);
        events.push_back(event);
    }
    void pushText(const char* text, Uint32 type = SDL_TEXTINPUT)
    {
        if (!active)
            return;
        SDL_Event event {};
        event.type = type;
        if (type == SDL_TEXTEDITING)
            std::snprintf(event.edit.text, sizeof(event.edit.text), "%s", text);
        else
            std::snprintf(event.text.text, sizeof(event.text.text), "%s", text);
        events.push_back(event);
    }
    void drain(SearchTextInput& input, InputConfig& keyboard, GuiComponent& view)
    {
        input.prepare(&view, &keyboard);
        while (!events.empty()) {
            const SDL_Event event {events.front()};
            events.pop_front();
            if (event.type == SDL_KEYDOWN) {
                Input key {DEVICE_KEYBOARD, TYPE_KEY, event.key.keysym.sym, 1, false};
                key.modifiers = static_cast<SDL_Keymod>(event.key.keysym.mod);
                input.keyDown(&keyboard, key, view.acceptsSearchText(), &view, &view);
            }
            else if (event.type == SDL_KEYUP)
                input.keyUp();
            else if (event.type == SDL_TEXTINPUT) {
                if (!input.text(event.text.text, &view))
                    view.textInput(event.text.text);
            }
            else if (event.type == SDL_TEXTEDITING) {
                input.editing(&view);
                view.textEditing(event.edit.text);
            }
        }
    }
    void queuedKeys()
    {
        SDL_StartTextInput();
        pushText("discarded");
        require(SDL_HasEvents(SDL_TEXTEDITING, SDL_TEXTINPUT));
        SDL_StopTextInput();
        require(events.empty()); // Positive control: stopping really loses queued text.
        for (int scenario {0}; scenario < 6; ++scenario) {
            InputConfig keyboard;
            keyboard.mapped = SDLK_w;
            GuiComponent view;
            Window::getInstance()->gui = &view;
            SearchTextInput input;
            input.prepare(&view, &keyboard);
            require(!active);
            if (scenario == 0 || scenario == 5)
                pushKey(SDL_KEYUP, SDLK_LEFT);
            else if (scenario == 1) {
                pushKey(SDL_KEYDOWN, SDLK_w);
                pushText("w"); // Mapped key while browsing: SDL drops this text.
            }
            else if (scenario == 2 || scenario == 4)
                pushKey(SDL_KEYDOWN, SDLK_LSHIFT);
            else {
                pushKey(SDL_KEYDOWN, SDLK_CARET);
                pushKey(SDL_KEYUP, SDLK_CARET);
            }
            const SDL_Keycode key {scenario == 2 ? SDLK_b : scenario == 3 ? SDLK_e : SDLK_m};
            const std::string expected {scenario == 2 ? "B" : scenario == 3 ? "ê" : "m"};
            pushKey(SDL_KEYDOWN, key, scenario == 2 ? KMOD_SHIFT : KMOD_NONE);
            if (scenario != 5)
                pushText(scenario == 4 ? "か" : expected.c_str(),
                         scenario == 4 ? SDL_TEXTEDITING : SDL_TEXTINPUT);
            pushKey(SDL_KEYUP, key);
            drain(input, keyboard, view);
            if (scenario == 5)
                require(view.opened.empty() && !active); // No commit leaves no listener.
            else {
                require(active &&
                        view.opened == std::vector<std::string> {scenario == 4 ? "" : expected});
                if (scenario == 4) {
                    require(view.composition == "か");
                    pushText("か");
                    drain(input, keyboard, view);
                    require(view.opened == std::vector<std::string> {"か"});
                }
                SDL_StopTextInput();
            }
            require(events.empty());
        }
        require(watches == 0);
        std::cout << "PASS: same-frame release/letter, mapped/letter, Shift/letter, dead key, "
                     "composition and no-commit SDL queue regressions\n";
    }
} // namespace
#endif

int main()
{
    InputConfig keyboard;
    GuiComponent view, modal;
    modal.browsing = false;
    Window::getInstance()->gui = &view;
    {
        SearchTextInput input;
        input.prepare(&view, &keyboard);
#if defined(__ANDROID__) || defined(__IOS__)
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
        Window::getInstance()->gui = &modal;
        input.prepare(&modal, &keyboard);
        require(active);
        watch(watchContext, &event);
        require(active && view.opened.size() == 3);
        // A GUI may be popped while the same event pump is still running, before
        // the next prepare(). The watch must compare live ownership before access.
        auto* closed = new GuiComponent;
        closed->browsing = false;
        Window::getInstance()->gui = closed;
        input.prepare(closed, &keyboard);
        delete closed;
        Window::getInstance()->gui = &view;
        SDL_StopTextInput();
        view.browsing = true;
        watch(watchContext, &event);
        require(!active);
        input.prepare(&view, &keyboard);
        watch(watchContext, &event);
        require(active);
        input.keyUp();
        require(!active);
#endif
    }
    require(watches == 0);
#if !defined(__ANDROID__) && !defined(__IOS__)
    queuedKeys();
#endif
    std::cout << "PASS: " << checks << " production search-entry input checks\n";
    return 0;
}
