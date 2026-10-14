//  SPDX-License-Identifier: MIT
//
//  ES-DE Frontend
//  GuiMenu.h
//
//  Main menu.
//  Some submenus are covered in separate source files.
//

#ifndef ES_APP_GUIS_GUI_MENU_H
#define ES_APP_GUIS_GUI_MENU_H

#include "GuiComponent.h"
#if defined(__ANDROID__)
#include "EmulatorManagerTouch.h"
#endif
#include "components/MenuComponent.h"
#include "guis/GuiSettings.h"
#include "views/ViewController.h"

class GuiMenu : public GuiComponent
{
public:
    GuiMenu();
    ~GuiMenu();

    bool input(InputConfig* config, Input input) override;
    void onSizeChanged() override;
    std::vector<HelpPrompt> getHelpPrompts() override;

#if defined(__ANDROID__)
    void update(int deltaTime) override
    {
        GuiComponent::update(deltaTime);
        mManagerTouch.updateTargets(*this, _("OTHER SETTINGS"));
    }
    bool nativeTouch(int type, int64_t finger, float x, float y) override
    {
        return mManagerTouch.handle(*this, type, finger, x, y, _("OTHER SETTINGS"));
    }
#endif

private:
#if defined(__ANDROID__)
    EmulatorManagerTouch mManagerTouch;
#endif
    void close(bool closeAllWindows);
    void addEntry(const std::string& name,
                  unsigned int color,
                  bool add_arrow,
                  const std::function<void()>& func);
    void addVersionInfo();

    void openGlobalSearch();
    void openScraperOptions();
    void openUIOptions();
    void openThemeDownloader(GuiSettings* settings);
    void openSystemStatusOptions();
    void openMediaViewerOptions();
    void openScreensaverOptions();
    void openScreenLaunchOptions();
    void openSoundOptions();
    void openInputDeviceOptions();
    void openConfigInput(GuiSettings* settings);
    void openCollectionSystemOptions();
    void openOtherOptions();
    void openUtilities();
    void openQuitMenu();

    Renderer* mRenderer;
    MenuComponent mMenu;
    TextComponent mVersion;
    int mThemeDownloaderReloadCounter;
};

#endif // ES_APP_GUIS_GUI_MENU_H
