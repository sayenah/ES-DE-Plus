//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchTextInput.h
//
//  Written for ES-DE-Plus. Pairs physical keys with layout-aware SDL text events.
//

#ifndef ES_CORE_SEARCH_TEXT_INPUT_H
#define ES_CORE_SEARCH_TEXT_INPUT_H

#include "InputConfig.h"

#include <SDL2/SDL_events.h>
#include <SDL2/SDL_thread.h>
#include <string>

class GuiComponent;

class SearchTextInput
{
public:
    ~SearchTextInput();
#if !defined(__ANDROID__) && !defined(__IOS__)
    void reset();
#endif
    void prepare(GuiComponent* gui, InputConfig* keyboard);
    void keyDown(
        InputConfig* config, Input input, bool browsing, GuiComponent* before, GuiComponent* after);
    void keyUp();
    void keyRepeat();
    bool text(const std::string& value, GuiComponent* gui);
    void editing(GuiComponent* gui);

private:
#if !defined(__ANDROID__) && !defined(__IOS__)
    static int watchKey(void* context, SDL_Event* event);
    void beginTemporaryText();
    void endTemporaryText();
    InputConfig* mKeyboard {nullptr};
    SDL_threadID mEventThread {0};
    bool mTemporaryText {false};
#endif
    GuiComponent* mOwner {nullptr};
    std::string mText;
    bool mKeyReady {false};
    bool mSuppressText {false};
};

#endif // ES_CORE_SEARCH_TEXT_INPUT_H
