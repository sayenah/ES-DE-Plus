// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from the open touch-overlay call surface.
#ifndef ES_CORE_INPUT_OVERLAY_H
#define ES_CORE_INPUT_OVERLAY_H
#if defined(__ANDROID__)
// The open Android menu uses SDL keyboard hints beside the overlay settings.
#include "InputOverlayModel.h"
#include <SDL2/SDL_hints.h>
#include <glm/mat4x4.hpp>
#include <memory>

class ImageComponent;
class TextComponent;
class InputOverlay
{
public:
    enum TriggerButtons {
        TRIGGER_LEFT = 100,
        TRIGGER_RIGHT = 101
    };
    static InputOverlay& getInstance();
    void init();
    void update(int);
    void render(const glm::mat4&);
    void createButtons();
    void clearButtons();
    void resetFadeTimer();
    void unselectAllButtons();
    int getButtonId(int, int, float, float, bool* released = nullptr);

    // SDL-thread integration drains release+press before the next external event.
    TouchOverlay::Transitions processEvent(int type, int finger, float x, float y);
    void cancelTouches();
    bool claimsTouch(float x, float y);
    void onResume();
    std::uint64_t epoch() const { return mModel.epoch(); }

private:
    InputOverlay() = default;
    ~InputOverlay();
    void rebuild(bool explicitWake);
    void refreshGeometry();
    void buildTextures();
    void logLayout() const;

    TouchOverlay::Model mModel;
    TouchOverlay::Options mOptions;
    std::array<std::unique_ptr<ImageComponent>, 14> mImages;
    std::array<std::unique_ptr<TextComponent>, 14> mLabels;
    bool mInitialized {false};
    bool mDirty {true};
    bool mFullWarning {false};
};
#endif
#endif
