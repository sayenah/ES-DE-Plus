//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  EmulatorManagerTouch.cpp
//
//  Written for ES-DE-Plus. Uses upstream component transforms, bounds and input callbacks.
//

#include "EmulatorManagerTouch.h"

#if defined(__ANDROID__)
#include "InputManager.h"
#include "Log.h"
#include "components/ButtonComponent.h"
#include "components/ComponentGrid.h"
#include "components/ComponentList.h"
#include "components/TextEditComponent.h"
#include "renderers/Renderer.h"

#include <cmath>

namespace
{
    struct Hit {
        GuiComponent* component {nullptr};
        float y {0.0f};
    };

    Hit hit(GuiComponent& component, const glm::mat4& parent, float x, float y)
    {
        if (!component.isVisible() || !component.getEnabled())
            return {};
        const auto transform = parent * component.getTransform();
        const auto local = glm::inverse(transform) * glm::vec4 {x, y, 0.0f, 1.0f};
        if (dynamic_cast<ComponentList*>(&component)) {
            if (local.x >= 0 && local.y >= 0 && local.x < component.getSize().x &&
                local.y < component.getSize().y)
                return {&component, local.y};
            return {};
        }
        // Hit the child drawn last first. Lists supply their own clipping/scroll coordinates.
        for (unsigned int i {component.getChildCount()}; i > 0; --i) {
            auto result = hit(*component.getChild(i - 1), transform, x, y);
            if (result.component)
                return result;
        }
        if ((dynamic_cast<ButtonComponent*>(&component) ||
             dynamic_cast<TextEditComponent*>(&component)) &&
            local.x >= 0 && local.y >= 0 && local.x < component.getSize().x &&
            local.y < component.getSize().y)
            return {&component, local.y};
        return {};
    }
} // namespace

bool EmulatorManagerTouch::handle(GuiComponent& gui, int type, int64_t finger, float x, float y)
{
    mDirty = true;
    TouchOverlay::Point point;
    if (!Renderer::getInstance()->getTouchGeometry().toLogical({x, y}, point)) {
        if (type == SDL_FINGERUP)
            invalidate();
        return false;
    }
    const float screenX {point.x};
    const float screenY {point.y};
    if (type == SDL_FINGERDOWN) {
        if (mFinger != -1)
            return finger == mFinger;
        const auto target = hit(gui, glm::mat4 {1.0f}, screenX, screenY);
        if (!target.component)
            return false;
        if (auto button = dynamic_cast<ButtonComponent*>(target.component))
            if (!button->getPressedFunc())
                return false;
        if (auto list = dynamic_cast<ComponentList*>(target.component)) {
            const int row = list->getTouchRow(target.y);
            if (row < 0 || row >= list->size() ||
                (!list->getTouchRowData(row).inputHandler && list->size() < 2))
                return false;
        }
        mTarget = target.component;
        mFinger = finger;
        mStartX = screenX;
        mStartY = mLastY = screenY;
        mMoved = false;
        return true;
    }
    if (finger != mFinger || mFinger == -1)
        return false;
    auto target = hit(gui, glm::mat4 {1.0f}, screenX, screenY);
    if (type == SDL_FINGERMOTION) {
        auto list = dynamic_cast<ComponentList*>(target.component);
        if (list && std::abs(screenY - mLastY) >= list->getRowHeight()) {
            list->moveCursor(screenY > mLastY ? -1 : 1);
            mLastY = screenY;
            mMoved = true;
        }
        if (std::abs(screenY - mStartY) > 12.0f * Renderer::getScreenHeightModifier() ||
            std::abs(screenX - mStartX) > 12.0f * Renderer::getScreenHeightModifier())
            mMoved = true;
        return true;
    }
    if (type != SDL_FINGERUP)
        return false;
    mFinger = -1;
    const bool sameTarget = target.component == mTarget;
    mTarget = nullptr;
    if (mMoved || !sameTarget || !target.component)
        return true;
    if (auto button = dynamic_cast<ButtonComponent*>(target.component)) {
        auto action = button->getPressedFunc();
        if (action)
            action();
        return true;
    }
    if (auto list = dynamic_cast<ComponentList*>(target.component)) {
        const int cursor = list->getTouchRow(target.y);
        if (cursor < 0 || cursor >= list->size())
            return true;
        list->moveCursor(cursor - list->getCursorId());
        list->onFocusGained();
        auto config = InputManager::getInstance().getInputConfigByDevice(DEVICE_TOUCH);
        list->input(config, Input(DEVICE_TOUCH, TYPE_TOUCH, SDL_CONTROLLER_BUTTON_A, 1, false));
        return true;
    }
    if (auto text = dynamic_cast<TextEditComponent*>(target.component))
        text->startEditing();
    return true;
}

void EmulatorManagerTouch::updateTargets(GuiComponent& gui, bool reportButtonFocus)
{
    if (!mDirty)
        return;
    mDirty = false;
    if (Log::getReportingLevel() < LogDebug)
        return;
    std::function<void(GuiComponent&, const glm::mat4&)> visit;
    auto report = [](const std::string& label, const glm::mat4& transform, float x, float y) {
        const auto point = transform * glm::vec4 {x, y, 0.0f, 1.0f};
        const auto normalized {
            Renderer::getInstance()->getTouchGeometry().toNormalized({point.x, point.y})};
        LOG(LogDebug) << "Emulator manager touch target: " << label << "\tx:" << point.x
                      << "\ty:" << point.y << "\tnorm:" << normalized.x << "," << normalized.y;
    };
    visit = [&](GuiComponent& component, const glm::mat4& parent) {
        if (!component.isVisible() || !component.getEnabled())
            return;
        const auto transform = parent * component.getTransform();
        if (reportButtonFocus) {
            if (auto grid = dynamic_cast<ComponentGrid*>(&component)) {
                auto selected = grid->getSelectedComponent();
                if (auto button = dynamic_cast<ButtonComponent*>(selected.get())) {
                    LOG(LogDebug) << "Emulator manager dialog focus: " << button->getText();
                }
            }
        }
        if (auto list = dynamic_cast<ComponentList*>(&component)) {
            for (int i {0}; i < list->size(); ++i) {
                const float y = (i + 0.5f) * list->getRowHeight() - list->getTouchOffset();
                if (y < 0 || y >= list->getSize().y)
                    continue;
                const auto& row = list->getTouchRowData(i);
                if (row.elements.empty())
                    continue;
                auto text = dynamic_cast<TextComponent*>(row.elements.front().component.get());
                if (text)
                    report(text->getValue(), transform, list->getSize().x / 2.0f, y);
            }
            return;
        }
        if (auto button = dynamic_cast<ButtonComponent*>(&component)) {
            report(button->getText(), transform, button->getSize().x / 2.0f,
                   button->getSize().y / 2.0f);
        }
        for (unsigned int i {0}; i < component.getChildCount(); ++i)
            visit(*component.getChild(i), transform);
    };
    visit(gui, glm::mat4 {1.0f});
}
#endif
