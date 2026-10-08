// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from the open touch-overlay call surface.
#ifndef ES_CORE_INPUT_OVERLAY_H
#define ES_CORE_INPUT_OVERLAY_H
#if defined(__ANDROID__)
// The open Android menu uses SDL keyboard hints beside the overlay settings.
#include <SDL2/SDL_hints.h>
#include <glm/mat4x4.hpp>
class InputOverlay
{
public:
    enum TriggerButtons {
        TRIGGER_LEFT = 100,
        TRIGGER_RIGHT = 101
    };
    static InputOverlay& getInstance();
    void init() {}
    void update(int) {}
    void render(const glm::mat4&) {}
    void createButtons() {}
    void clearButtons() {}
    void resetFadeTimer() {}
    void unselectAllButtons() {}
    int getButtonId(int, int, float, float, bool* released = nullptr)
    {
        if (released != nullptr)
            *released = false;
        return -2;
    }
};
#endif
#endif
