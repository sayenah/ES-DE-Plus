//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchTextInput.cpp
//
//  Written for ES-DE-Plus using public SDL2 text input APIs.
//

#include "SearchTextInput.h"

#include "GuiComponent.h"

#include <SDL2/SDL.h>

#include <utility>

void SearchTextInput::prepare(GuiComponent* gui)
{
    if (gui != mOwner) {
        mText.clear();
        mKeyReady = false;
        mOwner = gui;
    }
    if (gui && gui->acceptsSearchText() && !SDL_IsTextInputActive()) {
        // Listen to physical keyboards without opening Android's screen keyboard.
        const char* previous {SDL_GetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD)};
        const bool hadHint {previous != nullptr};
        const std::string hint {previous ? previous : ""};
        SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, "0");
        SDL_StartTextInput();
        SDL_SetHint(SDL_HINT_ENABLE_SCREEN_KEYBOARD, hadHint ? hint.c_str() : nullptr);
    }
}

void SearchTextInput::keyDown(
    InputConfig* config, Input input, bool browsing, GuiComponent* before, GuiComponent* after)
{
    mSuppressText = false;
    mKeyReady = false;
    const bool printable {input.id >= SDLK_SPACE && input.id < SDLK_DELETE};
    if (browsing && before == after && printable && config->getMappedTo(input).empty() &&
        !(input.modifiers & (KMOD_CTRL | KMOD_ALT | KMOD_GUI))) {
        mOwner = before;
        mKeyReady = true;
        if (!mText.empty()) {
            const std::string value {std::move(mText)};
            mText.clear();
            text(value, before);
        }
    }
    else {
        // A mapped key owns its text even when it only navigates. Drop its
        // following desktop text event; Android already sent text into mText.
        mSuppressText = browsing && mText.empty() && printable;
        mText.clear();
    }
}

void SearchTextInput::keyUp()
{
    mText.clear();
    mKeyReady = false;
    mSuppressText = false;
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
    if (gui == mOwner && !value.empty() && value != " " && value != "\b")
        gui->openSearch(value == "/" ? "" : value);
    return true;
}
