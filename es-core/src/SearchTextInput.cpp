//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchTextInput.cpp
//
//  Written for ES-DE-Plus using public SDL2 text input APIs.
//

#include "SearchTextInput.h"

#include "GuiComponent.h"
#include "Window.h"

#include <SDL2/SDL.h>

#include <utility>

namespace
{
    bool searchKey(InputConfig* config, const Input& input)
    {
        return input.id >= SDLK_SPACE && input.id != SDLK_DELETE &&
               !(input.id & SDLK_SCANCODE_MASK) && config->getMappedTo(input).empty() &&
               !(input.modifiers & (KMOD_CTRL | KMOD_ALT | KMOD_GUI));
    }
} // namespace

SearchTextInput::~SearchTextInput()
{
#if !defined(__ANDROID__) && !defined(__IOS__)
    if (mEventThread)
        SDL_DelEventWatch(watchKey, this);
#endif
}

#if !defined(__ANDROID__) && !defined(__IOS__)
int SearchTextInput::watchKey(void* context, SDL_Event* event)
{
    auto& self = *static_cast<SearchTextInput*>(context);
    // SDL watches may run on other threads. Only the normal desktop event pump
    // may touch input state or activate the platform IME.
    if (SDL_ThreadID() != self.mEventThread || event->type != SDL_KEYDOWN || event->key.repeat ||
        !self.mOwner || Window::getInstance()->peekGui() != self.mOwner ||
        !self.mOwner->acceptsSearchText() || !self.mKeyboard)
        return 1;
    Input input {DEVICE_KEYBOARD, TYPE_KEY, event->key.keysym.sym, 1, false};
    input.modifiers = static_cast<SDL_Keymod>(event->key.keysym.mod);
    if (input.id != SDLK_SPACE && searchKey(self.mKeyboard, input))
        self.beginTemporaryText();
    return 1;
}

void SearchTextInput::beginTemporaryText()
{
    if (!SDL_IsTextInputActive()) {
        // Run when SDL queues key-down, before it translates that same key into
        // layout-aware text. Waiting until PollEvent returns loses the first key.
        SDL_StartTextInput();
        mTemporaryText = true;
    }
}

void SearchTextInput::endTemporaryText()
{
    if (mTemporaryText) {
        SDL_StopTextInput();
        mTemporaryText = false;
    }
}
#endif

void SearchTextInput::prepare(GuiComponent* gui, InputConfig* keyboard)
{
    if (gui != mOwner) {
#if !defined(__ANDROID__) && !defined(__IOS__)
        if (!gui || gui->acceptsSearchText())
            endTemporaryText();
        else
            mTemporaryText = false; // A newly opened field owns its text session.
#endif
        mText.clear();
        mKeyReady = false;
        mOwner = gui;
    }
#if defined(__ANDROID__) || defined(__IOS__)
    (void)keyboard;
    if (gui && gui->acceptsSearchText() && !SDL_IsTextInputActive()) {
        // Listen to physical keyboards without opening Android's screen keyboard.
        const char* previous {SDL_GetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD)};
        const bool hadHint {previous != nullptr};
        const std::string hint {previous ? previous : ""};
        SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, "0");
        SDL_StartTextInput();
        SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, hadHint ? hint.c_str() : nullptr);
    }
#else
    mKeyboard = keyboard;
    if (!mEventThread) {
        mEventThread = SDL_ThreadID();
        SDL_AddEventWatch(watchKey, this);
    }
    if (gui && gui->acceptsSearchText() && !mTemporaryText && SDL_IsTextInputActive())
        SDL_StopTextInput();
#endif
}

void SearchTextInput::keyDown(
    InputConfig* config, Input input, bool browsing, GuiComponent* before, GuiComponent* after)
{
    mSuppressText = false;
    mKeyReady = false;
    const bool printable {input.id >= SDLK_SPACE && input.id != SDLK_DELETE &&
                          !(input.id & SDLK_SCANCODE_MASK)};
    if (browsing && before == after && searchKey(config, input)) {
#if !defined(__ANDROID__) && !defined(__IOS__)
        if (input.id != SDLK_SPACE)
            beginTemporaryText();
#endif
        mOwner = before;
        mKeyReady = true;
        if (!mText.empty()) {
            const std::string value {std::move(mText)};
            mText.clear();
            text(value, before);
        }
    }
    else {
#if !defined(__ANDROID__) && !defined(__IOS__)
        endTemporaryText();
#endif
        // A mapped key owns its text even when it only navigates. Drop its
        // following desktop text event; Android already sent text into mText.
        mSuppressText = browsing && mText.empty() && printable;
        mText.clear();
    }
}

void SearchTextInput::keyUp()
{
#if !defined(__ANDROID__) && !defined(__IOS__)
    endTemporaryText();
#endif
    mText.clear();
    mKeyReady = false;
    mSuppressText = false;
}

void SearchTextInput::keyRepeat()
{
    // Browsing ignores repeat actions upstream. Discard their text too,
    // whether SDL already delivered it or will deliver it after this event.
    const bool follows {mText.empty()};
    keyUp();
    mSuppressText = follows;
}

bool SearchTextInput::text(const std::string& value, GuiComponent* gui)
{
    if (mSuppressText) {
        mSuppressText = false;
        return true;
    }
    if (!gui || !gui->acceptsSearchText())
        return false;
    if (!mKeyReady) {
        // Android commits text before the matching key-down; desktop SDL
        // normally sends it afterwards. Wait for the key to check mappings.
        mOwner = gui;
        mText = value;
        return true;
    }
    mKeyReady = false;
    if (gui == mOwner && !value.empty() && value != " " && value != "\b") {
#if !defined(__ANDROID__) && !defined(__IOS__)
        // The new field owns text input from here, including queued commits.
        mTemporaryText = false;
#endif
        gui->openSearch(value == "/" ? "" : value);
    }
    return true;
}

void SearchTextInput::editing(GuiComponent* gui)
{
#if !defined(__ANDROID__) && !defined(__IOS__)
    if (mTemporaryText && mKeyReady && gui == mOwner && gui && gui->acceptsSearchText()) {
        // A composing IME has no committed character yet. Move it into the field
        // before forwarding this editing event; releasing the key must not cancel it.
        mTemporaryText = false;
        mKeyReady = false;
        gui->openSearch("");
    }
#else
    (void)gui;
#endif
}
