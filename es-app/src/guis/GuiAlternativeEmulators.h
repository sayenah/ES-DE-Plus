//  SPDX-License-Identifier: MIT
//
//  ES-DE Frontend
//  GuiAlternativeEmulators.h
//
//  User interface to select between alternative emulators per system
//  based on configuration entries in es_systems.xml.
//

#ifndef ES_APP_GUIS_GUI_ALTERNATIVE_EMULATORS_H
#define ES_APP_GUIS_GUI_ALTERNATIVE_EMULATORS_H

#if defined(__ANDROID__)
#include "EmulatorManagerTouch.h"
#endif
#include "GuiComponent.h"
#include "guis/GuiSettings.h"

template <typename T> class OptionListComponent;

class GuiAlternativeEmulators : public GuiComponent
{
public:
    GuiAlternativeEmulators();

#if defined(__ANDROID__)
    void update(int deltaTime) override
    {
        GuiComponent::update(deltaTime);
        mManagerTouch.updateTargets(*this, _("EMULATOR MANAGER"));
    }
    bool nativeTouch(int type, int64_t finger, float x, float y) override
    {
        return mManagerTouch.handle(*this, type, finger, x, y, _("EMULATOR MANAGER"));
    }
#endif

private:
#if defined(__ANDROID__)
    EmulatorManagerTouch mManagerTouch;
#endif
    void updateMenu(const std::string& systemName, const std::string& label, bool defaultEmulator);
    void selectorWindow(SystemData* system);

    bool input(InputConfig* config, Input input) override;
    std::vector<HelpPrompt> getHelpPrompts() override;

    MenuComponent mMenu;
    bool mHasSystems;

    std::map<std::string, std::shared_ptr<TextComponent>> mCommandRows;
    std::shared_ptr<OptionListComponent<std::string>> mCommandSelection;
};

#endif // ES_APP_GUIS_GUI_ALTERNATIVE_EMULATORS_H
