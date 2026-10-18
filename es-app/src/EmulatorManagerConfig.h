//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  EmulatorManagerConfig.h
//
//  Written for ES-DE-Plus. Preservation-aware edits of upstream override grammar.
//

#ifndef ES_APP_EMULATOR_MANAGER_CONFIG_H
#define ES_APP_EMULATOR_MANAGER_CONFIG_H

#include <functional>
#include <pugixml.hpp>
#include <string>
#include <vector>

class EmulatorManagerConfig
{
public:
    struct Command {
        std::string label;
        std::string value;
        std::string addition;
    };
    struct System {
        std::string name;
        std::string fullName;
        std::string path;
        std::string extensions;
        std::vector<Command> commands;
        bool custom;
        bool stale;
    };

    EmulatorManagerConfig(const std::string& directory,
                          const std::string& bundledSystems,
                          const std::string& bundledRules);
    EmulatorManagerConfig(const EmulatorManagerConfig& other);
    std::vector<System> systems() const;
    System system(const std::string& name) const;
    std::vector<std::string> profileTargets(const std::string& command) const;
    std::string add(const std::string& name,
                    const std::string& label,
                    const std::string& component,
                    const std::string& profile,
                    const std::string& extensions,
                    bool nameUnlabelled);
    void remove(const std::string& name, const std::string& addition);
    void reset(const std::string& name);
    void refresh(const std::string& name);
    void save();
    void verifyCurrent() const;

    // Fault injection uses the production transaction, without a fixture-path special case.
    void setSaveCheckpoint(std::function<void(int)> checkpoint) { mCheckpoint = checkpoint; }
    static void clearSelections(const std::string& path, const std::vector<std::string>& labels);
    static std::string fingerprint(const std::string& bytes);
    static std::string replaceEmulator(const std::string& profile, const std::string& rule);

private:
    pugi::xml_node effective(const std::string& name) const;
    pugi::xml_node editable(const std::string& name);
    void markSnapshot(pugi::xml_node node);
    std::string mDirectory;
    std::string mBundledSystems;
    std::string mSystemsBytes;
    std::string mRulesBytes;
    pugi::xml_document mSystems;
    pugi::xml_document mRules;
    pugi::xml_document mBundle;
    pugi::xml_document mBundleRules;
    std::function<void(int)> mCheckpoint;
};

#endif
