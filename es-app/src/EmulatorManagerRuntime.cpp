//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  EmulatorManagerRuntime.cpp
//
//  Written for ES-DE-Plus using upstream launch, settings and gamelist abstractions.
//

#include "EmulatorManagerRuntime.h"

#if defined(__ANDROID__)
#include "FileData.h"
#include "GamelistFileParser.h"
#include "Log.h"
#include "Settings.h"
#include "SystemData.h"
#include "Window.h"
#include "resources/ResourceManager.h"
#include "utils/FileSystemUtil.h"
#include "utils/LocalizationUtil.h"
#include "utils/PlatformUtilAndroid.h"
#include "utils/StringUtil.h"
#include "views/ViewController.h"

#include <stdexcept>

namespace
{
    std::unique_ptr<SystemData> shell(const EmulatorManagerConfig::System& definition)
    {
        auto env = new SystemEnvironmentData;
        env->mStartPath = EmulatorManagerRuntime::path(definition);
        env->mSearchExtensions = Utils::String::delimitedStringToVector(definition.extensions, " ");
        for (auto cmd : definition.commands)
            env->mLaunchCommands.emplace_back(cmd.value, cmd.label);
        // A virtual structure avoids scanning, parsing or saving a library for an unsaved test.
        auto system = std::make_unique<SystemData>(definition.name, definition.fullName,
                                                   definition.name, env, definition.name, true);
        return system;
    }

    pugi::xml_node alternative(pugi::xml_document& doc)
    {
        return doc.child("alternativeEmulator") ?
                   doc.child("alternativeEmulator") :
                   doc.child("gameList").child("alternativeEmulator");
    }
} // namespace

EmulatorManagerConfig EmulatorManagerRuntime::configuration()
{
    const auto paths = SystemData::getConfigPath();
    return EmulatorManagerConfig(Utils::FileSystem::getAppDataDirectory() + "/custom_systems",
                                 paths.back(),
                                 ResourceManager::getInstance().getResourcePath(
                                     ":/systems/android/es_find_rules.xml", true));
}

std::string EmulatorManagerRuntime::path(const EmulatorManagerConfig::System& system)
{
    auto expanded = Utils::String::replace(system.path, "%ROMPATH%", FileData::getROMDirectory());
    expanded = Utils::FileSystem::expandHomePath(expanded);
    return Utils::FileSystem::getCanonicalPath(expanded);
}

bool EmulatorManagerRuntime::test(const EmulatorManagerConfig::System& system,
                                  const std::string& file,
                                  const std::string& profile,
                                  const std::string& component)
{
    if (!Utils::FileSystem::isRegularFile(file))
        throw std::runtime_error(_("Select a readable game file for the draft test"));
    if (!SystemData::sFindRules)
        SystemData::sFindRules = std::make_unique<FindRules>();
    auto& rules = SystemData::sFindRules->mEmulators;
    const auto previous = rules;
    std::string rule {"ESDEPLUS_TRANSIENT_TEST"};
    while (rules.count(rule))
        rule += "_";
    const auto candidate = EmulatorManagerConfig::replaceEmulator(profile, rule);
    rules[rule].androidPackages = {component};
    testing = true;
    testCommand = candidate;
    testResult = -1;
    try {
        auto transient = shell(system);
        transient->getRootFolder()->mPath = path(system);
        FileData game {GAME, file, transient->getSystemEnvData(), transient.get()};
        game.launchGame();
    }
    catch (...) {
        rules = previous;
        testing = false;
        testCommand.clear();
        throw;
    }
    rules = previous;
    testing = false;
    testCommand.clear();
    return testResult == 0;
}

void EmulatorManagerRuntime::setDefault(const EmulatorManagerConfig::System& definition,
                                        const std::string& label)
{
    std::unique_ptr<SystemData> temporary;
    auto system = SystemData::getSystemByName(definition.name);
    if (!system) {
        temporary = shell(definition);
        system = temporary.get();
        system->getRootFolder()->mPath = path(definition);
    }
    bool found {false};
    for (const auto& command : definition.commands)
        if (command.label == label)
            found = true;
    if (!found)
        throw std::runtime_error(_("The selected emulator no longer exists"));
    const std::string previous {system->getAlternativeEmulator()};
    const std::string selected {definition.commands.front().label == label ? "" : label};
    system->setAlternativeEmulator(selected);
    GamelistFileParser::updateGamelist(system, true);
    pugi::xml_document doc;
    const auto result = doc.load_file(system->getGamelistPath(true).c_str());
    if (!result || std::string(alternative(doc).child("label").text().get()) != selected) {
        system->setAlternativeEmulator(previous);
        throw std::runtime_error(_("Could not save the default emulator to gamelist.xml. Check "
                                   "access and the Ignore gamelist setting"));
    }
    LOG(LogInfo) << "Emulator manager default saved: " << definition.name
                 << "; label: " << selected;
}

void EmulatorManagerRuntime::checkSelections(const EmulatorManagerConfig::System& definition,
                                             const std::vector<std::string>& retainedLabels)
{
    auto retained = [&](const std::string& label) {
        return label.empty() || std::find(retainedLabels.begin(), retainedLabels.end(), label) !=
                                    retainedLabels.end();
    };
    auto temporary = shell(definition);
    temporary->getRootFolder()->mPath = path(definition);
    auto loaded = SystemData::getSystemByName(definition.name);
    if (loaded) {
        if (!retained(loaded->getAlternativeEmulator()))
            throw std::runtime_error(
                _("Choose a replacement system default before removing this emulator"));
        for (auto game : loaded->getRootFolder()->getChildrenRecursive())
            if (!retained(game->metadata.get("altemulator")))
                throw std::runtime_error(
                    _("This emulator is selected for a game. Choose its replacement in the game's "
                      "metadata editor before removing it"));
    }
    const auto file = temporary->getGamelistPath(false);
    if (!Utils::FileSystem::exists(file))
        return;
    pugi::xml_document doc;
    if (!doc.load_file(file.c_str()))
        throw std::runtime_error(_("Cannot inspect emulator selections in gamelist.xml"));
    if (!retained(alternative(doc).child("label").text().get()))
        throw std::runtime_error(
            _("Choose a replacement system default before removing this emulator"));
    for (auto game : doc.child("gameList").children("game"))
        if (!retained(game.child("altemulator").text().get()))
            throw std::runtime_error(_("This emulator is selected in gamelist.xml. Repair the "
                                       "affected game's alternative emulator before removing it"));
}

void EmulatorManagerRuntime::apply(const std::string& systemName)
{
    auto window = Window::getInstance();
    // Dialogs and their save functions are destroyed while old system pointers are still valid.
    while (window->peekGui() && window->peekGui() != ViewController::getInstance())
        delete window->peekGui();
    SystemData::sFindRules = std::make_unique<FindRules>();
    ViewController::getInstance()->rescanROMDirectory();
    auto system = SystemData::getSystemByName(systemName);
    if (system)
        ViewController::getInstance()->goToSystemView(system, false);
}
#endif
