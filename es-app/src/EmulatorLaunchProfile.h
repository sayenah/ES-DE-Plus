//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  EmulatorLaunchProfile.h
//
//  Written for ES-DE-Plus from INSTALL.md's Android launch grammar.
//

#ifndef ES_APP_EMULATOR_LAUNCH_PROFILE_H
#define ES_APP_EMULATOR_LAUNCH_PROFILE_H

#include <string>
#include <vector>

struct EmulatorLaunchProfile {
    struct Extra {
        std::string type;
        std::string name;
        std::string value;
    };
    std::string action;
    std::string category;
    std::string mime;
    std::string data {"%ROM%"};
    std::vector<Extra> extras;
    bool clearTask {false};
    bool clearTop {false};
    bool noHistory {false};

    static std::vector<std::string> receivers(const std::string& source,
                                              const std::string& package);
    static EmulatorLaunchProfile fromCommand(const std::string& command);
    std::string command(const std::string& rule) const;
    void rom(const std::string& token, const std::string& extraName);
};

#endif
