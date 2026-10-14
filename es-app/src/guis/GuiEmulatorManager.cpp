//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  GuiEmulatorManager.cpp
//
//  Written for ES-DE-Plus using the upstream MenuComponent and text keyboard patterns.
//

#include "guis/GuiEmulatorManager.h"

#if defined(__ANDROID__)
#include "EmulatorManagerRuntime.h"
#include "FileData.h"
#include "Log.h"
#include "Settings.h"
#include "SystemData.h"
#include "Window.h"
#include "guis/GuiMsgBox.h"
#include "guis/GuiTextEditKeyboardPopup.h"
#include "utils/FileSystemUtil.h"
#include "utils/LocalizationUtil.h"
#include "utils/StringUtil.h"

#include <thread>

namespace
{
    std::string extraTypeName(const std::string& type)
    {
        if (type == "EXTRA")
            return _("STRING");
        if (type == "EXTRAARRAY")
            return _("STRING ARRAY");
        if (type == "EXTRAINTEGER")
            return _("INTEGER");
        return _("BOOLEAN");
    }
} // namespace

GuiEmulatorManager::GuiEmulatorManager(const std::string& systemName)
    : mSystemName {systemName}
{
    if (!systemName.empty())
        mNext = Page::SYSTEM;
    mMenu = std::make_unique<MenuComponent>(_("EMULATOR MANAGER"));
    addChild(mMenu.get());
    row(_("LOADING CONFIGURATION"));
    setSize(mMenu->getSize());
    setPosition((Renderer::getScreenWidth() - mSize.x) / 2.0f, Renderer::getScreenHeight() * 0.08f);
}

void GuiEmulatorManager::page(Page next)
{
    mNext = next;
    mRebuild = true;
}

void GuiEmulatorManager::row(const std::string& text, const std::function<void()>& action)
{
    ComponentListRow entry;
    entry.addElement(
        std::make_shared<TextComponent>(text, Font::get(FONT_SIZE_MEDIUM), mMenuColorPrimary),
        true);
    if (action) {
        entry.addElement(mMenu->makeArrow(), false);
        entry.makeAcceptInputHandler(action);
    }
    mMenu->addRow(entry);
}

void GuiEmulatorManager::error(const std::string& message)
{
    LOG(LogWarning) << "Emulator manager notice: " << message;
    mWindow->pushGui(new GuiEmulatorManagerMsgBox(message, _("OK"), nullptr));
}

void GuiEmulatorManager::confirm(const std::string& message, const std::function<void()>& action)
{
    mWindow->pushGui(
        new GuiEmulatorManagerMsgBox(message, _("CONTINUE"), action, _("CANCEL"), nullptr));
}

void GuiEmulatorManager::invalidateDraft() { mSave.reset(); }

void GuiEmulatorManager::edit(const std::string& title, std::string& value)
{
    auto field = &value;
    row(title + ": " + (value.empty() ? _("NONE") : value), [this, title, field] {
        mWindow->pushGui(new GuiEmulatorManagerKeyboard(
            0.0f, title, *field,
            [this, field](const std::string& text) {
                *field = Utils::String::trim(text);
                invalidateDraft();
                page(mPage);
            },
            false));
    });
}

void GuiEmulatorManager::discover()
{
    auto state = std::make_shared<Discovery>();
    mDiscovery = state;
    mAppFilter.clear();
    auto definition = mConfig->system(mSystemName);
    auto types =
        Utils::String::delimitedStringToVector(definition.extensions + " " + mExtensions, " ");
    std::vector<std::string> probes;
    for (const auto& type : types)
        if (!type.empty() && probes.size() < 127)
            probes.push_back(EmulatorManagerRuntime::path(definition) + "/ESDEPlusProbe" + type);
    if (!mTestPath.empty())
        probes.push_back(mTestPath);
    // The worker retains only result state. Closing/cancelling never joins PackageManager
    // or leaves a callback referencing the GUI, a system pointer or its configuration.
    std::thread([state, probes] {
        std::vector<Utils::Platform::Android::EmulatorActivity> activities;
        bool success {false};
        try {
            success = Utils::Platform::Android::getEmulatorActivities(probes, activities);
        }
        catch (const std::exception&) {
        }
        std::lock_guard<std::mutex> lock {state->mutex};
        state->activities = std::move(activities);
        state->success = success;
        state->done = true;
    }).detach();
    page(Page::APPS);
}

void GuiEmulatorManager::rebuild()
{
    mPage = mNext;
    const char* pages[] {"systems", "system", "draft", "apps",    "profiles",
                         "extras",  "extra",  "files", "defaults"};
    LOG(LogDebug) << "Emulator manager page: " << pages[static_cast<int>(mPage)]
                  << "; system: " << mSystemName;
    mRebuild = false;
    mTouch.invalidate();
    if (mMenu)
        removeChild(mMenu.get());
    mMenu = std::make_unique<MenuComponent>(_("EMULATOR MANAGER"));
    addChild(mMenu.get());
    mMenu->addButton(_("BACK"), _("back"), [this] { back(); });
    try {
        if (!mConfig)
            mConfig =
                std::make_unique<EmulatorManagerConfig>(EmulatorManagerRuntime::configuration());
        if (mPage == Page::SYSTEMS) {
            edit(_("FIND SYSTEM"), mFilter);
            for (const auto& system : mConfig->systems()) {
                if (!mFilter.empty() &&
                    Utils::String::toUpper(system.name + " " + system.fullName)
                            .find(Utils::String::toUpper(mFilter)) == std::string::npos)
                    continue;
                row(system.name + " — " + system.fullName, [this, name = system.name] {
                    mSystemName = name;
                    page(Page::SYSTEM);
                });
            }
        }
        else {
            const auto system = mConfig->system(mSystemName);
            mMenu->setTitle(Utils::String::toUpper(system.name) + " — " + _("EMULATORS"),
                            Font::get(FONT_SIZE_LARGE));
            if (mPage == Page::SYSTEM) {
                row(_("ADD EMULATOR"), [this] {
                    mLabel.clear();
                    mComponent.clear();
                    mExtensions.clear();
                    mTestPath.clear();
                    mRomExtra.clear();
                    mTransport = "%ROM%";
                    mProfile = EmulatorLaunchProfile {};
                    mProfile.action = "android.intent.action.VIEW";
                    invalidateDraft();
                    page(Page::DRAFT);
                });
                row(_("SET SYSTEM DEFAULT"), [this] { page(Page::DEFAULTS); });
                for (const auto& command : system.commands) {
                    row((command.label.empty() ? _("UNLABELLED ORIGINAL EMULATOR") :
                                                 command.label) +
                            (command.addition.empty() ? "" : " [" + _("MANAGER ADDITION") + "]"),
                        [this, command] {
                            if (!command.addition.empty())
                                confirm(_("Remove this manager addition? Its accepted file types "
                                          "and find rule are retained. Hand-edited commands are "
                                          "preserved."),
                                        [this, command] { remove(command); });
                            else
                                error(_("Existing and hand-edited emulators are preserved. Add a "
                                        "new emulator using this entry's launch settings."));
                        });
                }
                if (system.stale)
                    row(_("SNAPSHOT DIFFERS FROM CURRENT BUNDLE"), [this] {
                        confirm(_("Refresh this system's snapshot from the current bundled "
                                  "definition? Manager additions and accepted file types are kept. "
                                  "Other hand edits cause refresh to be refused."),
                                [this] { refresh(); });
                    });
                if (system.custom)
                    row(_("RESET WHOLE SYSTEM OVERRIDE TO BUNDLED"), [this, system] {
                        confirm(_("Remove the entire custom_systems/es_systems.xml override for "
                                  "this system, including hand edits and every custom command? "
                                  "Under loadExclusive, a fresh bundled snapshot is retained so "
                                  "the system stays defined.") +
                                    "\n\n" + system.name + " — " + system.fullName,
                                [this] { reset(); });
                    });
            }
            else if (mPage == Page::DRAFT) {
                edit(_("EMULATOR LABEL"), mLabel);
                row(_("RECEIVING APP AND ACTIVITY") + ": " + mComponent, [this] { discover(); });
                row(_("RECEIVING ACTIVITY") + ": " +
                        (mComponent.find('/') == std::string::npos ?
                             _("SELECT APP FIRST") :
                             mComponent.substr(mComponent.find('/') + 1)),
                    [this] {
                        const auto slash = mComponent.find('/');
                        if (slash == std::string::npos) {
                            error(_("Select an installed app first"));
                            return;
                        }
                        const auto package = mComponent.substr(0, slash);
                        mWindow->pushGui(new GuiEmulatorManagerKeyboard(
                            0.0f, _("RECEIVING ACTIVITY: RELATIVE OR FULL NAME"),
                            mComponent.substr(slash + 1),
                            [this, package](const std::string& value) {
                                auto activity = Utils::String::trim(value);
                                if (!activity.empty() && activity.front() == '.')
                                    activity = package + activity;
                                else if (activity.find('.') == std::string::npos)
                                    activity = package + "." + activity;
                                if (!Utils::Platform::Android::checkEmulatorInstalled(package,
                                                                                      activity)) {
                                    error(_("That activity is unavailable, private, disabled or "
                                            "permission-protected"));
                                    return;
                                }
                                mComponent = package + "/" + activity;
                                invalidateDraft();
                                page(Page::DRAFT);
                            },
                            false));
                    });
                row(_("USE AN EXISTING EMULATOR'S LAUNCH SETTINGS"),
                    [this] { page(Page::PROFILES); });
                edit(_("ADDITIONAL FILE TYPES (E.G. .zip .ZIP)"), mExtensions);
                row(_("ROM TRANSPORT") + ": " +
                        (mTransport == "%ROM%"    ? _("FILE PATH") :
                         mTransport == "%ROMSAF%" ? _("DOCUMENT URI") :
                                                    _("ES-DE PLUS PROVIDER")),
                    [this] {
                        const std::string transport {mTransport == "%ROM%"    ? "%ROMSAF%" :
                                                     mTransport == "%ROMSAF%" ? "%ROMPROVIDER%" :
                                                                                "%ROM%"};
                        try {
                            auto profile = mProfile;
                            profile.rom(transport, mRomExtra);
                            mProfile = std::move(profile);
                            mTransport = transport;
                            invalidateDraft();
                        }
                        catch (const std::exception& failure) {
                            error(failure.what());
                        }
                        page(Page::DRAFT);
                    });
                row(_("ROM IN DATA OR NAMED EXTRA") + ": " +
                        (mRomExtra.empty() ? _("INTENT DATA") : mRomExtra),
                    [this] {
                        mWindow->pushGui(new GuiEmulatorManagerKeyboard(
                            0.0f, _("ROM EXTRA NAME (EMPTY FOR INTENT DATA)"), mRomExtra,
                            [this](const std::string& value) {
                                try {
                                    auto next = mProfile;
                                    next.rom(mTransport, Utils::String::trim(value));
                                    next.command("VALIDATE");
                                    mProfile = next;
                                    mRomExtra = Utils::String::trim(value);
                                    invalidateDraft();
                                }
                                catch (const std::exception& failure) {
                                    error(failure.what());
                                }
                                page(Page::DRAFT);
                            },
                            false));
                    });
                edit(_("ACTION"), mProfile.action);
                edit(_("CATEGORY"), mProfile.category);
                edit(_("MIME TYPE (EMPTY USES UPSTREAM DEFAULT)"), mProfile.mime);
                edit(_("INTENT DATA"), mProfile.data);
                row(_("TYPED EXTRAS"), [this] { page(Page::EXTRAS); });
                row(_("CLEAR TASK") + ": " + (mProfile.clearTask ? _("YES") : _("NO")), [this] {
                    mProfile.clearTask = !mProfile.clearTask;
                    invalidateDraft();
                    page(Page::DRAFT);
                });
                row(_("CLEAR TOP") + ": " + (mProfile.clearTop ? _("YES") : _("NO")), [this] {
                    mProfile.clearTop = !mProfile.clearTop;
                    invalidateDraft();
                    page(Page::DRAFT);
                });
                row(_("NO HISTORY") + ": " + (mProfile.noHistory ? _("YES") : _("NO")), [this] {
                    mProfile.noHistory = !mProfile.noHistory;
                    invalidateDraft();
                    page(Page::DRAFT);
                });
                row(_("SELECT DRAFT TEST FILE") + ": " + mTestPath, [this, system] {
                    mBrowsePath = EmulatorManagerRuntime::path(system);
                    page(Page::FILES);
                });
                row(_("TEST UNSAVED LAUNCH"), [this] { mTest = true; });
                row(_("SAVE AND APPLY"), [this, system] {
                    bool unlabelled {false};
                    for (auto cmd : system.commands)
                        unlabelled |= cmd.label.empty();
                    if (unlabelled)
                        confirm(_("The original unlabelled command must receive a unique label to "
                                  "keep it selectable alongside alternatives. Continue?"),
                                [this] { save(); });
                    else
                        save();
                });
            }
            else if (mPage == Page::APPS) {
                edit(_("FIND APP OR ACTIVITY"), mAppFilter);
                if (!mDiscovery)
                    throw std::runtime_error(
                        _("Discovery was cancelled; select the receiving app again"));
                std::lock_guard<std::mutex> lock {mDiscovery->mutex};
                if (!mDiscovery->done)
                    row(_("DISCOVERING APPS: BACK TO CANCEL"));
                else if (!mDiscovery->success)
                    row(_("APP DISCOVERY FAILED: BACK TO RETRY"));
                else {
                    LOG(LogDebug) << "Emulator manager discovery complete: "
                                  << mDiscovery->activities.size() << " activities";
                    for (const auto& app : mDiscovery->activities) {
                        const auto component = app.packageName + "/" + app.activityName;
                        if (!mAppFilter.empty() &&
                            Utils::String::toUpper(app.label + " " + component)
                                    .find(Utils::String::toUpper(mAppFilter)) == std::string::npos)
                            continue;
                        const auto shortActivity =
                            app.activityName.substr(app.activityName.find_last_of('.') + 1);
                        row(shortActivity + " — " + app.packageName + " — " + app.label +
                                (app.declaredHandler ?
                                     " [" + _("DECLARES IT OPENS THESE FILES") + "]" :
                                     ""),
                            [this, app, component] {
                                confirm(_("Use this receiving activity?") + "\n\n" + app.label +
                                            "\n" + component +
                                            (app.declaredHandler ?
                                                 "\n\n" + _("Declares it opens these files. Game "
                                                            "compatibility is not verified.") :
                                                 ""),
                                        [this, app, component] {
                                            mComponent = component;
                                            if (mLabel.empty())
                                                mLabel = app.label;
                                            invalidateDraft();
                                            page(Page::DRAFT);
                                        });
                            });
                    }
                    if (mDiscovery->activities.empty())
                        row(_("NO ACCESSIBLE APPS FOUND"));
                }
            }
            else if (mPage == Page::PROFILES) {
                for (const auto& source : mConfig->systems())
                    for (const auto& command : source.commands)
                        row(source.name + " — " +
                                (command.label.empty() ? _("ORIGINAL EMULATOR") : command.label),
                            [this, command] {
                                try {
                                    auto profile =
                                        EmulatorLaunchProfile::fromCommand(command.value);
                                    mProfile = profile;
                                    const auto slash = mComponent.find('/');
                                    if (slash != std::string::npos) {
                                        const auto package = mComponent.substr(0, slash);
                                        bool offered {false};
                                        for (const auto& source :
                                             mConfig->profileTargets(command.value)) {
                                            for (const auto& activity :
                                                 EmulatorLaunchProfile::receivers(source,
                                                                                  package)) {
                                                if (Utils::Platform::Android::
                                                        checkEmulatorInstalled(package, activity)) {
                                                    const auto receiver = package + "/" + activity;
                                                    if (receiver != mComponent)
                                                        confirm(
                                                            _("Use this profile's receiving "
                                                              "activity with the selected app? It "
                                                              "is installed and accessible; game "
                                                              "compatibility is not verified.") +
                                                                "\n\n" + receiver,
                                                            [this, receiver] {
                                                                mComponent = receiver;
                                                                invalidateDraft();
                                                                page(Page::DRAFT);
                                                            });
                                                    offered = true;
                                                    break;
                                                }
                                            }
                                            if (offered)
                                                break;
                                        }
                                    }
                                    // Controls reflect the copied profile; no conversion happens
                                    // until requested.
                                    mRomExtra.clear();
                                    mTransport = "%ROM%";
                                    auto inspect = [this](const std::string& value) {
                                        for (const std::string token :
                                             {"%ROM%", "%ROMSAF%", "%ROMPROVIDER%"})
                                            if (value.find(token) != std::string::npos)
                                                mTransport = token;
                                    };
                                    inspect(profile.data);
                                    for (const auto& extra : profile.extras)
                                        if (extra.value == "%ROM%" || extra.value == "%ROMSAF%") {
                                            mRomExtra = extra.name;
                                            inspect(extra.value);
                                        }
                                    invalidateDraft();
                                    page(Page::DRAFT);
                                }
                                catch (const std::exception& failure) {
                                    error(failure.what());
                                }
                            });
            }
            else if (mPage == Page::EXTRAS) {
                row(_("ADD EXTRA"), [this] {
                    mProfile.extras.push_back({"EXTRA", "", ""});
                    mExtra = mProfile.extras.size() - 1;
                    invalidateDraft();
                    page(Page::EXTRA);
                });
                for (size_t i {0}; i < mProfile.extras.size(); ++i)
                    row(extraTypeName(mProfile.extras[i].type) + " — " + mProfile.extras[i].name,
                        [this, i] {
                            mExtra = i;
                            page(Page::EXTRA);
                        });
            }
            else if (mPage == Page::EXTRA) {
                auto& extra = mProfile.extras.at(mExtra);
                row(_("TYPE") + ": " + extraTypeName(extra.type), [this] {
                    auto& extra = mProfile.extras.at(mExtra);
                    extra.type = extra.type == "EXTRA"        ? "EXTRAARRAY" :
                                 extra.type == "EXTRAARRAY"   ? "EXTRAINTEGER" :
                                 extra.type == "EXTRAINTEGER" ? "EXTRABOOL" :
                                                                "EXTRA";
                    invalidateDraft();
                    page(Page::EXTRA);
                });
                edit(_("EXTRA NAME"), extra.name);
                edit(_("EXTRA VALUE"), extra.value);
                row(_("REMOVE EXTRA"), [this] {
                    mProfile.extras.erase(mProfile.extras.begin() + mExtra);
                    invalidateDraft();
                    page(Page::EXTRAS);
                });
            }
            else if (mPage == Page::FILES) {
                row(_("ENTER TEST FILE PATH"), [this] {
                    mWindow->pushGui(new GuiEmulatorManagerKeyboard(
                        0.0f, _("TEST FILE PATH"), mTestPath,
                        [this](const std::string& path) {
                            mTestPath = Utils::String::trim(path);
                            page(Page::DRAFT);
                        },
                        false));
                });
                row(_("PARENT DIRECTORY"), [this] {
                    mBrowsePath = Utils::FileSystem::getParent(mBrowsePath);
                    page(Page::FILES);
                });
                const auto types = Utils::String::delimitedStringToVector(
                    system.extensions + " " + mExtensions, " ");
                auto files = Utils::FileSystem::getDirContent(mBrowsePath);
                files.sort();
                size_t shown {0};
                for (const auto& file : files) {
                    if (shown >= 200) {
                        row(_("MORE FILES: ENTER THE TEST FILE PATH"));
                        break;
                    }
                    if (Utils::FileSystem::isDirectory(file)) {
                        ++shown;
                        row("[" + Utils::FileSystem::getFileName(file) + "]", [this, file] {
                            mBrowsePath = file;
                            page(Page::FILES);
                        });
                    }
                    else if (std::find(types.begin(), types.end(),
                                       Utils::FileSystem::getExtension(file)) != types.end()) {
                        ++shown;
                        row(Utils::FileSystem::getFileName(file), [this, file] {
                            mTestPath = file;
                            page(Page::DRAFT);
                        });
                    }
                }
            }
            else if (mPage == Page::DEFAULTS) {
                for (const auto& command : system.commands)
                    row(command.label.empty() ? _("ORIGINAL EMULATOR") : command.label,
                        [this, system, command] {
                            try {
                                mConfig->verifyCurrent();
                                EmulatorManagerRuntime::setDefault(system, command.label);
                                page(Page::SYSTEM);
                            }
                            catch (const std::exception& failure) {
                                error(failure.what());
                            }
                        });
            }
        }
    }
    catch (const std::exception& failure) {
        row(_("CONFIGURATION CANNOT BE EDITED"));
        error(failure.what());
    }
    setSize(mMenu->getSize());
    setPosition((Renderer::getScreenWidth() - mSize.x) / 2.0f, Renderer::getScreenHeight() * 0.08f);
}

void GuiEmulatorManager::save()
{
    try {
        const auto slash = mComponent.find('/');
        if (slash == std::string::npos ||
            !Utils::Platform::Android::checkEmulatorInstalled(mComponent.substr(0, slash),
                                                              mComponent.substr(slash + 1)))
            throw std::runtime_error(
                _("The receiving activity is unavailable. Select an installed app again"));
        if (!mSave) {
            mConfig->verifyCurrent();
            auto candidate = std::make_unique<EmulatorManagerConfig>(*mConfig);
            candidate->add(mSystemName, mLabel, mComponent, mProfile.command("DRAFT"), mExtensions,
                           true);
            mSave = std::move(candidate);
        }
        mSave->save();
        LOG(LogInfo) << "Emulator manager saved: " << mSystemName << "; label: " << mLabel;
        mApply = true;
    }
    catch (const std::exception& failure) {
        error(_("NOT APPLIED. The draft is kept; retry or reopen after an external edit.") +
              "\n\n" + failure.what());
    }
}

void GuiEmulatorManager::test()
{
    try {
        auto definition = mConfig->system(mSystemName);
        auto types =
            Utils::String::delimitedStringToVector(definition.extensions + " " + mExtensions, " ");
        if (mTestPath.empty() ||
            std::find(types.begin(), types.end(), Utils::FileSystem::getExtension(mTestPath)) ==
                types.end())
            throw std::runtime_error(
                _("Select a test file matching the draft's accepted file types"));
        const auto slash = mComponent.find('/');
        if (slash == std::string::npos ||
            !Utils::Platform::Android::checkEmulatorInstalled(mComponent.substr(0, slash),
                                                              mComponent.substr(slash + 1)))
            throw std::runtime_error(
                _("The receiving activity is unavailable. Select an installed app again"));
        const bool accepted = EmulatorManagerRuntime::test(definition, mTestPath,
                                                           mProfile.command("DRAFT"), mComponent);
        LOG(LogInfo) << "Emulator manager test: " << (accepted ? "accepted" : "refused")
                     << "; system: " << mSystemName;
        error(accepted ?
                  _("LAUNCH REQUEST ACCEPTED. Check the receiving app to verify operation. No "
                    "configuration, default or play statistics were saved; your draft is kept.") :
                  _("LAUNCH REQUEST REFUSED. Check the ROM transport, file access and receiving "
                    "activity. No configuration, default or play statistics were saved; your draft "
                    "is kept."));
    }
    catch (const std::exception& failure) {
        error(failure.what());
    }
}

void GuiEmulatorManager::remove(const EmulatorManagerConfig::Command& command)
{
    try {
        mConfig->verifyCurrent();
        auto config = *mConfig;
        const auto system = config.system(mSystemName);
        std::vector<std::string> retained;
        for (const auto& candidate : system.commands)
            if (candidate.addition != command.addition)
                retained.push_back(candidate.label);
        EmulatorManagerRuntime::checkSelections(system, retained);
        config.remove(mSystemName, command.addition);
        config.save();
        mApply = true;
    }
    catch (const EmulatorManagerRuntime::SelectionConflict& conflict) {
        repair(conflict.labels, [this, command] { remove(command); });
    }
    catch (const std::exception& failure) {
        error(failure.what());
    }
}

void GuiEmulatorManager::reset()
{
    try {
        mConfig->verifyCurrent();
        auto config = *mConfig;
        const auto previous = config.system(mSystemName);
        config.reset(mSystemName);
        std::vector<std::string> retained;
        for (const auto& command : config.system(mSystemName).commands)
            retained.push_back(command.label);
        EmulatorManagerRuntime::checkSelections(previous, retained);
        config.save();
        mApply = true;
    }
    catch (const EmulatorManagerRuntime::SelectionConflict& conflict) {
        repair(conflict.labels, [this] { reset(); });
    }
    catch (const std::exception& failure) {
        error(failure.what());
    }
}

void GuiEmulatorManager::refresh()
{
    try {
        mConfig->verifyCurrent();
        auto config = *mConfig;
        const auto previous = config.system(mSystemName);
        config.refresh(mSystemName);
        std::vector<std::string> retained;
        for (const auto& command : config.system(mSystemName).commands)
            retained.push_back(command.label);
        EmulatorManagerRuntime::checkSelections(previous, retained);
        config.save();
        mApply = true;
    }
    catch (const EmulatorManagerRuntime::SelectionConflict& conflict) {
        repair(conflict.labels, [this] { refresh(); });
    }
    catch (const std::exception& failure) {
        error(failure.what());
    }
}

void GuiEmulatorManager::repair(const std::vector<std::string>& labels,
                                const std::function<void()>& retry)
{
    std::string affected;
    for (const auto& label : labels)
        affected += "\n" + label;
    confirm(_("Clear only system and game emulator selections using the entries below, so they "
              "inherit the default? Other games' choices are preserved. The selections are saved "
              "before the configuration change.") +
                affected,
            [this, labels, retry] {
                try {
                    mConfig->verifyCurrent();
                    EmulatorManagerRuntime::clearSelections(mConfig->system(mSystemName), labels);
                    retry();
                }
                catch (const std::exception& failure) {
                    error(failure.what());
                }
            });
}

void GuiEmulatorManager::back()
{
    if (mPage == Page::SYSTEMS)
        mClose = true;
    else if (mPage == Page::SYSTEM)
        page(Page::SYSTEMS);
    else if (mPage == Page::DRAFT)
        confirm(_("Discard this unsaved emulator draft?"), [this] {
            mSave.reset();
            page(Page::SYSTEM);
        });
    else if (mPage == Page::EXTRA)
        page(Page::EXTRAS);
    else if (mPage == Page::DEFAULTS)
        page(Page::SYSTEM);
    else {
        if (mPage == Page::APPS)
            mDiscovery.reset();
        page(Page::DRAFT);
    }
}

bool GuiEmulatorManager::input(InputConfig* config, Input input)
{
    mTouch.invalidate();
    if (input.value && config->isMappedTo("b", input)) {
        back();
        return true;
    }
    return GuiComponent::input(config, input);
}

void GuiEmulatorManager::update(int deltaTime)
{
    if (mClose) {
        delete this;
        return;
    }
    if (mApply) {
        const auto name = mSystemName;
        EmulatorManagerRuntime::apply(name);
        return;
    }
    if (mPage == Page::APPS && mDiscovery) {
        std::lock_guard<std::mutex> lock {mDiscovery->mutex};
        if (mDiscovery->done && !mDiscovery->presented) {
            mDiscovery->presented = true;
            page(Page::APPS);
        }
    }
    if (mRebuild)
        rebuild();
    if (mTest) {
        mTest = false;
        test();
    }
    GuiComponent::update(deltaTime);
    mTouch.updateTargets(*this);
}

std::vector<HelpPrompt> GuiEmulatorManager::getHelpPrompts()
{
    auto prompts = mMenu->getHelpPrompts();
    prompts.push_back({"b", _("back")});
    return prompts;
}
#endif
