// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from open callers and upstream MIT overlay SVGs.
#include "InputOverlay.h"
#if defined(__ANDROID__)
#include "InputManager.h"
#include "Log.h"
#include "Settings.h"
#include "components/ImageComponent.h"
#include "renderers/Renderer.h"
#include "resources/ResourceManager.h"
#include "resources/TextureResource.h"

#include <SDL2/SDL_system.h>
#include <algorithm>
#include <cmath>
#include <glm/gtc/matrix_transform.hpp>

namespace
{
    const std::array<const char*, 14> ART {
        "button_dpad.svg",      "button_dpad.svg",       "button_dpad.svg",
        "button_dpad.svg",      "button_a.svg",          "button_b.svg",
        "button_x.svg",         "button_y.svg",          "button_back.svg",
        "button_start.svg",     "button_shoulder_l.svg", "button_shoulder_r.svg",
        "button_trigger_l.svg", "button_trigger_r.svg"};
}

InputOverlay& InputOverlay::getInstance()
{
    static InputOverlay instance;
    return instance;
}
InputOverlay::~InputOverlay() = default;
void InputOverlay::init() { rebuild(false); }
void InputOverlay::createButtons() { rebuild(true); }

void InputOverlay::rebuild(bool explicitWake)
{
    InputManager::getInstance().cancelTouchInput();
    auto* settings {Settings::getInstance()};
    mOptions = TouchOverlay::Options::parse(settings->getString("InputTouchOverlaySize"),
                                            settings->getString("InputTouchOverlayOpacity"),
                                            settings->getInt("InputTouchOverlayFadeTime"),
                                            SDL_IsAndroidTV());
    if (mOptions.invalidSize) {
        LOG(LogWarning) << "InputOverlay: unknown size; using medium";
    }
    if (mOptions.invalidOpacity) {
        LOG(LogWarning) << "InputOverlay: unknown opacity; using normal";
    }
    if (mOptions.clampedFade) {
        LOG(LogWarning) << "InputOverlay: fade time clamped to " << mOptions.fadeSeconds;
    }
    float dpi {0};
    auto* renderer {Renderer::getInstance()};
    if (SDL_GetDisplayDPI(renderer->getDisplayIndex(), &dpi, nullptr, nullptr) != 0)
        dpi = 0;
    mModel.rebuild(renderer->getTouchGeometry(), mOptions, dpi);
    mModel.wake(explicitWake);
    mInitialized = true;
    mDirty = true;
    mFullWarning = false;
    if (mModel.densityFallback()) {
        LOG(LogWarning) << "InputOverlay: logical density unavailable; estimating S/411";
    }
    if (!mModel.supported()) {
        LOG(LogError) << "InputOverlay: unsupported viewport; no invalid hit regions published";
    }
    logLayout();
    LOG(LogDebug) << "InputOverlay: restored (" << (explicitWake ? "menu" : "rebuild") << ")";
}

void InputOverlay::refreshGeometry()
{
    if (!mInitialized)
        return;
    const auto geometry {Renderer::getInstance()->getTouchGeometry()};
    if (!(geometry == mModel.geometry())) {
        // Publish one mapping/layout generation, cancelling its predecessor first.
        InputManager::getInstance().cancelTouchInput();
        float dpi {0};
        if (SDL_GetDisplayDPI(Renderer::getInstance()->getDisplayIndex(), &dpi, nullptr, nullptr))
            dpi = 0;
        mModel.rebuild(geometry, mOptions, dpi);
        mDirty = true;
        mFullWarning = false;
        logLayout();
    }
}

void InputOverlay::clearButtons()
{
    InputManager::getInstance().cancelTouchInput();
    mModel.clear();
    for (auto& image : mImages)
        image.reset();
    mInitialized = false;
    mDirty = true;
    LOG(LogDebug) << "InputOverlay: cleared";
}
void InputOverlay::cancelTouches() { mModel.cancel(); }
void InputOverlay::onResume()
{
    refreshGeometry();
    mModel.wake(false);
    LOG(LogDebug) << "InputOverlay: restored (resume)";
}
void InputOverlay::resetFadeTimer()
{
    const int seconds {Settings::getInstance()->getInt("InputTouchOverlayFadeTime")};
    mOptions.fadeSeconds = std::clamp(seconds, 0, 20);
    if (seconds != mOptions.fadeSeconds) {
        LOG(LogWarning) << "InputOverlay: fade time clamped to " << mOptions.fadeSeconds;
    }
    mModel.setFadeSeconds(seconds);
    mModel.wake(true);
    LOG(LogDebug) << "InputOverlay: restored (menu)";
}
void InputOverlay::unselectAllButtons() { mModel.suppress(); }
void InputOverlay::update(int deltaTime)
{
    refreshGeometry();
    const auto before {mModel.fade()};
    mModel.update(deltaTime);
    if (before != TouchOverlay::Fade::HIDDEN && mModel.fade() == TouchOverlay::Fade::HIDDEN) {
        LOG(LogDebug) << "InputOverlay: faded";
    }
}

TouchOverlay::Transitions InputOverlay::processEvent(int type, int finger, float x, float y)
{
    if (type != SDL_FINGERDOWN && type != SDL_FINGERUP && type != SDL_FINGERMOTION)
        return {};
    refreshGeometry();
    const bool hidden {mModel.fade() == TouchOverlay::Fade::HIDDEN};
    const auto result {mModel.input(type == SDL_FINGERDOWN ? TouchOverlay::Event::DOWN :
                                    type == SDL_FINGERUP   ? TouchOverlay::Event::UP :
                                                             TouchOverlay::Event::MOTION,
                                    finger, {x, y})};
    if (hidden && type == SDL_FINGERDOWN) {
        LOG(LogDebug) << "InputOverlay: restored (touch)";
    }
    if (mModel.tableFull() && !mFullWarning) {
        mFullWarning = true;
        LOG(LogWarning) << "InputOverlay: finger table full";
    }
    for (int i {0}; i < result.count; ++i) {
        LOG(LogDebug) << "InputOverlay: transition epoch=" << epoch()
                      << " id=" << result.entries[i].id << " value=" << result.entries[i].value;
    }
    return result;
}
int InputOverlay::getButtonId(int type, int finger, float x, float y, bool* released)
{
    if (released)
        *released = false;
    // Original single-transition compatibility interface. The integrated caller uses
    // processEvent; legacy callers must supply the flag to accept a motion release.
    if (type == SDL_FINGERMOTION && !released)
        return TouchOverlay::NO_BUTTON;
    if (type != SDL_FINGERDOWN && type != SDL_FINGERUP && type != SDL_FINGERMOTION)
        return TouchOverlay::NO_BUTTON;
    refreshGeometry();
    const auto result {mModel.input(type == SDL_FINGERDOWN ? TouchOverlay::Event::DOWN :
                                    type == SDL_FINGERUP   ? TouchOverlay::Event::UP :
                                                             TouchOverlay::Event::MOTION,
                                    finger, {x, y}, true)};
    if (!result.count)
        return TouchOverlay::NO_BUTTON;
    if (released && type == SDL_FINGERMOTION)
        *released = result.entries[0].value == 0;
    return result.entries[0].id;
}
void InputOverlay::logLayout() const
{
    const auto& g {mModel.geometry()};
    const auto v {g.visible()};
    LOG(LogDebug) << "InputOverlay: layout WxH=" << g.width << "x" << g.height
                  << " rot=" << g.rotation << " surface=" << g.drawableWidth << "x"
                  << g.drawableHeight << " visible=" << v.x << "," << v.y << "," << v.w << ","
                  << v.h << " ppd=" << mModel.density()
                  << " dpiFallback=" << mModel.densityFallback()
                  << " class=" << (v.w >= v.h ? "landscape" : "portrait")
                  << " size=" << mOptions.size << " opacity=" << mOptions.opacity
                  << " D=" << mModel.diameter() << " fit="
                  << (mModel.compact() ? 2 :
                      mModel.diameter() + 0.01f < std::clamp(0.12f * std::min(v.w, v.h),
                                                             56 * mModel.density(),
                                                             84 * mModel.density()) *
                                                      mOptions.size ?
                                         1 :
                                         0)
                  << " supported=" << mModel.supported() << " epoch=" << epoch();
    if (!mModel.supported())
        return;
    for (const auto& b : mModel.buttons()) {
        const auto n {g.toNormalized(b.centre)};
        LOG(LogDebug) << "InputOverlay: button id=" << b.id << " hit=" << b.hit.x << "," << b.hit.y
                      << "," << b.hit.w << "," << b.hit.h << " centre=" << b.centre.x << ","
                      << b.centre.y << " norm=" << n.x << "," << n.y;
    }
}
void InputOverlay::buildTextures()
{
    for (int i {0}; i < 14; ++i) {
        mImages[i].reset();
        const auto& b {mModel.buttons()[i]};
        const std::string path {ResourceManager::getInstance().getResourcePath(
            std::string {":/graphics/overlay/"} + ART[i], false)};
        if (!path.empty()) {
            const auto texture {TextureResource::get(path, false, true, true, false, false,
                                                     static_cast<size_t>(std::round(b.width)),
                                                     static_cast<size_t>(std::round(b.height)))};
            if (!texture->getIsInvalidSVGFile() && texture->getSize().x > 0 &&
                texture->getSize().y > 0) {
                auto image {std::make_unique<ImageComponent>(true, true)};
                image->setResize(b.width, b.height);
                image->setImage(texture);
                image->setOrigin(0.5f, 0.5f);
                image->setPosition(b.centre.x, b.centre.y);
                image->setRotationDegrees(b.rotation);
                mImages[i] = std::move(image);
            }
        }
        if (!mImages[i]) {
            LOG(LogError) << "InputOverlay: unavailable art id=" << b.id << "; primitive fallback";
        }
    }
    mDirty = false;
    LOG(LogDebug) << "InputOverlay: textures built";
}
void InputOverlay::render(const glm::mat4& parentTrans)
{
    refreshGeometry();
    if (!mModel.supported() || mModel.fade() == TouchOverlay::Fade::HIDDEN)
        return;
    if (mDirty)
        buildTextures();
    auto* renderer {Renderer::getInstance()};
    const float alpha {mModel.alpha()};
    for (int i {0}; i < 14; ++i) {
        const auto& b {mModel.buttons()[i]};
        const bool pressed {mModel.highlighted(i)};
        const float w {b.width * (pressed ? 0.94f : 1.0f)};
        const float h {b.height * (pressed ? 0.94f : 1.0f)};
        auto* image {mImages[i].get()};
        const auto shape = [&](float scale, unsigned int color, float opacity) {
            const float width {w * scale};
            const float height {h * scale};
            // The rounded-corner shader uses local vertex positions and the
            // rectangle's dimensions. Placement belongs in its transform.
            renderer->setMatrix(glm::translate(
                parentTrans, glm::vec3 {b.centre.x - width / 2, b.centre.y - height / 2, 0}));
            const float radius {std::min(width, height) * (b.circle ? 0.5f : 0.2f)};
            renderer->drawRect(0, 0, width, height, color, color, false, opacity, 1.0f,
                               Renderer::BlendFactor::SRC_ALPHA,
                               Renderer::BlendFactor::ONE_MINUS_SRC_ALPHA, radius);
        };
        renderer->setMatrix(parentTrans);
        if (image) {
            image->setScale(pressed ? 0.94f * 1.08f : 1.08f);
            image->setColorShift(0x000000FF);
            image->setOpacity(0.35f * alpha);
            image->render(parentTrans);
        }
        else {
            shape(1.08f, 0x000000FF, 0.35f * alpha);
        }
        if (!image || pressed) {
            shape(1.0f, 0xFFFFFFFF, pressed ? 0.45f : 0.35f * alpha);
        }
        if (image) {
            image->setScale(pressed ? 0.94f : 1.0f);
            image->setColorShift(0xFFFFFFFF);
            image->setOpacity(pressed ? std::max(alpha, 0.8f) : alpha);
            image->render(parentTrans);
        }
    }
}
#endif
