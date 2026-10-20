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

#include <string>

class GuiComponent;

class SearchTextInput
{
public:
    void prepare(GuiComponent* gui);
    void keyDown(
        InputConfig* config, Input input, bool browsing, GuiComponent* before, GuiComponent* after);
    void keyUp();
    bool text(const std::string& value, GuiComponent* gui);

private:
    GuiComponent* mOwner {nullptr};
    std::string mText;
    bool mKeyReady {false};
    bool mSuppressText {false};
};

#endif // ES_CORE_SEARCH_TEXT_INPUT_H
