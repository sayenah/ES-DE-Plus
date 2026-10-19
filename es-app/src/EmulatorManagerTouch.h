//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  EmulatorManagerTouch.h
//
//  Written for ES-DE-Plus. Direct touch inside emulator-manager dialogs.
//

#ifndef ES_APP_EMULATOR_MANAGER_TOUCH_H
#define ES_APP_EMULATOR_MANAGER_TOUCH_H

#if defined(__ANDROID__)
#include "GuiComponent.h"
#include "guis/GuiMsgBox.h"
#include "guis/GuiTextEditKeyboardPopup.h"

class EmulatorManagerTouch
{
public:
    bool handle(GuiComponent& gui, int type, int64_t finger, float x, float y);

    void updateTargets(GuiComponent& gui, bool reportButtonFocus = false);
    void invalidate()
    {
        mDirty = true;
        mFinger = -1;
        mTarget = nullptr;
    }

private:
    bool mDirty {true};
    GuiComponent* mTarget {nullptr};
    float mStartX {0.0f};
    int64_t mFinger {-1};
    float mStartY {0.0f};
    float mLastY {0.0f};
    bool mMoved {false};
};

class GuiEmulatorManagerMsgBox : public GuiMsgBox
{
public:
    using GuiMsgBox::GuiMsgBox;
    void update(int deltaTime) override
    {
        GuiMsgBox::update(deltaTime);
        mTouch.updateTargets(*this, true);
    }
    bool input(InputConfig* config, Input input) override
    {
        mTouch.invalidate();
        return GuiMsgBox::input(config, input);
    }
    void cancelNativeTouch() override { mTouch.invalidate(); }
    bool nativeTouch(int type, int64_t finger, float x, float y) override
    {
        return mTouch.handle(*this, type, finger, x, y);
    }

private:
    EmulatorManagerTouch mTouch;
};

class GuiEmulatorManagerKeyboard : public GuiTextEditKeyboardPopup
{
public:
    using GuiTextEditKeyboardPopup::GuiTextEditKeyboardPopup;
    void update(int deltaTime) override
    {
        GuiTextEditKeyboardPopup::update(deltaTime);
        mTouch.updateTargets(*this);
    }
    void cancelNativeTouch() override { mTouch.invalidate(); }
    bool nativeTouch(int type, int64_t finger, float x, float y) override
    {
        return mTouch.handle(*this, type, finger, x, y);
    }

private:
    EmulatorManagerTouch mTouch;
};
#endif

#endif
