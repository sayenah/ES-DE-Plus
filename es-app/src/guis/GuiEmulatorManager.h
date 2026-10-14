//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  GuiEmulatorManager.h
//
//  Written for ES-DE-Plus. Controller-friendly Android emulator configuration.
//

#ifndef ES_APP_GUIS_GUI_EMULATOR_MANAGER_H
#define ES_APP_GUIS_GUI_EMULATOR_MANAGER_H

#if defined(__ANDROID__)
#include "EmulatorLaunchProfile.h"
#include "EmulatorManagerConfig.h"
#include "GuiComponent.h"
#include "components/MenuComponent.h"
#include "utils/PlatformUtilAndroid.h"

#include <atomic>
#include <memory>
#include <mutex>

class GuiEmulatorManager : public GuiComponent
{
public:
    explicit GuiEmulatorManager(const std::string& systemName = "");
    bool input(InputConfig* config, Input input) override;
    void update(int deltaTime) override;
    std::vector<HelpPrompt> getHelpPrompts() override;

private:
    enum class Page {
        SYSTEMS,
        SYSTEM,
        DRAFT,
        APPS,
        PROFILES,
        EXTRAS,
        EXTRA,
        FILES,
        DEFAULTS
    };
    struct Discovery {
        std::mutex mutex;
        bool done {false};
        bool success {false};
        bool presented {false};
        std::vector<Utils::Platform::Android::EmulatorActivity> activities;
    };
    void page(Page page);
    void rebuild();
    void back();
    void row(const std::string& text, const std::function<void()>& action = {});
    void edit(const std::string& title, std::string& value);
    void error(const std::string& message);
    void confirm(const std::string& message, const std::function<void()>& action);
    void discover();
    void save();
    void test();
    void remove(const EmulatorManagerConfig::Command& command);
    void reset();
    void refresh();
    void invalidateDraft();

    std::unique_ptr<MenuComponent> mMenu;
    std::unique_ptr<EmulatorManagerConfig> mConfig;
    std::unique_ptr<EmulatorManagerConfig> mSave;
    std::shared_ptr<Discovery> mDiscovery;
    Page mPage {Page::SYSTEMS};
    Page mNext {Page::SYSTEMS};
    bool mRebuild {true};
    bool mApply {false};
    bool mTest {false};
    bool mClose {false};
    std::string mSystemName;
    std::string mFilter;
    std::string mAppFilter;
    std::string mLabel;
    std::string mComponent;
    std::string mExtensions;
    std::string mTestPath;
    std::string mBrowsePath;
    std::string mRomExtra;
    std::string mTransport {"%ROM%"};
    EmulatorLaunchProfile mProfile;
    size_t mExtra {0};
};
#endif

#endif
