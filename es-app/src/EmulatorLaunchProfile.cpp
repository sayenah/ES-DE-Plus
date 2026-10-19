//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  EmulatorLaunchProfile.cpp
//
//  Written for ES-DE-Plus from the public C++ caller and documented Android grammar.
//

#include "EmulatorLaunchProfile.h"

#include "utils/LocalizationUtil.h"

#include <algorithm>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>

namespace
{
    std::string value(const std::string& text)
    {
        if (text.find('"') != std::string::npos ||
            std::any_of(text.begin(), text.end(),
                        [](unsigned char c) { return c < 0x20 || c == 0x7f; }))
            throw std::runtime_error(_("This field cannot contain quotes or control characters"));
        for (const std::string marker :
             {"%EMULATOR_", "%EXTRA", "%ACTION%", "%CATEGORY%", "%MIMETYPE%", "%DATA%",
              "%ACTIVITY_", "%INJECT%", "%PRECOMMAND_"})
            if (text.find(marker) != std::string::npos)
                throw std::runtime_error(
                    _("A field value cannot contain launch controls or file injection"));
        return text.find(' ') == std::string::npos ? text : "\"" + text + "\"";
    }

    std::vector<std::string> tokens(const std::string& text)
    {
        std::vector<std::string> result;
        std::string token;
        bool quoted {false};
        for (char c : text) {
            if (c == '"')
                quoted = !quoted;
            else if (c == ' ' && !quoted) {
                if (!token.empty()) {
                    result.push_back(token);
                    token.clear();
                }
                continue;
            }
            token += c;
        }
        if (quoted)
            throw std::runtime_error(_("Unclosed quote in launch profile"));
        if (!token.empty())
            result.push_back(token);
        return result;
    }
} // namespace

std::vector<std::string> EmulatorLaunchProfile::receivers(const std::string& source,
                                                          const std::string& package)
{
    const auto slash = source.find('/');
    if (slash == std::string::npos)
        return {};
    const auto sourcePackage = source.substr(0, slash);
    auto original = source.substr(slash + 1);
    if (original.empty())
        return {};
    if (original.front() == '.')
        original = sourcePackage + original;
    std::vector<std::string> result;
    if (original.find(sourcePackage + ".") == 0)
        result.push_back(package + original.substr(sourcePackage.size()));
    if (std::find(result.begin(), result.end(), original) == result.end())
        result.push_back(original);
    return result;
}

EmulatorLaunchProfile EmulatorLaunchProfile::fromCommand(const std::string& command)
{
    EmulatorLaunchProfile profile;
    profile.data.clear();
    bool found {false};
    std::set<std::string> fields;
    for (const auto& token : tokens(command)) {
        if (token.find("%EMULATOR_") == 0 && token.back() == '%') {
            if (found)
                throw std::runtime_error(_("Multiple emulator rules in launch profile"));
            found = true;
            continue;
        }
        if (token == "%ACTIVITY_CLEAR_TASK%") {
            profile.clearTask = true;
            continue;
        }
        if (token == "%ACTIVITY_CLEAR_TOP%") {
            profile.clearTop = true;
            continue;
        }
        if (token == "%ACTIVITY_NO_HISTORY%") {
            profile.noHistory = true;
            continue;
        }
        auto equal = token.find('=');
        if (equal == std::string::npos)
            throw std::runtime_error(_("This profile uses unsupported controls; choose another "
                                       "profile or configure structured fields"));
        auto key = token.substr(0, equal);
        if (!fields.insert(key).second)
            throw std::runtime_error(_("Repeated launch-profile fields are ambiguous; configure "
                                       "structured fields instead"));
        auto val = token.substr(equal + 1);
        if (val.size() >= 2 && val.front() == '"' && val.back() == '"')
            val = val.substr(1, val.size() - 2);
        if (key == "%ACTION%")
            profile.action = val;
        else if (key == "%CATEGORY%")
            profile.category = val;
        else if (key == "%MIMETYPE%")
            profile.mime = val;
        else if (key == "%DATA%")
            profile.data = val;
        else {
            bool supported {false};
            for (const std::string type : {"EXTRA", "EXTRAARRAY", "EXTRAINTEGER", "EXTRABOOL"}) {
                const std::string prefix {"%" + type + "_"};
                if (key.find(prefix) == 0 && key.back() == '%') {
                    profile.extras.push_back(
                        {type, key.substr(prefix.size(), key.size() - prefix.size() - 1), val});
                    supported = true;
                    break;
                }
            }
            if (!supported)
                throw std::runtime_error(_("Unsupported launch-profile field"));
        }
    }
    if (!found)
        throw std::runtime_error(
            _("This entry has no emulator find rule; configure structured fields instead"));
    profile.command("VALIDATE");
    return profile;
}

std::string EmulatorLaunchProfile::command(const std::string& rule) const
{
    std::string result {"%EMULATOR_" + rule + "%"};
    auto field = [&](const std::string& key, const std::string& text) {
        if (!text.empty())
            result += " " + key + "=" + value(text);
    };
    field("%ACTION%", action);
    field("%CATEGORY%", category);
    field("%MIMETYPE%", mime);
    field("%DATA%", data);
    std::vector<std::string> keys;
    for (const auto& extra : extras) {
        if (!std::regex_match(extra.name, std::regex("[A-Za-z0-9_.$:-]+")) || extra.value.empty())
            throw std::runtime_error(_("Extras need a valid name and a nonempty value"));
        if (std::find(keys.begin(), keys.end(), extra.name) != keys.end())
            throw std::runtime_error(_("Extra names must be unique across types"));
        keys.push_back(extra.name);
        if (extra.type == "EXTRAINTEGER") {
            if (!std::regex_match(extra.value, std::regex("[+-]?[0-9]+")))
                throw std::runtime_error(_("Invalid integer extra"));
            size_t used {0};
            try {
                std::stoi(extra.value, &used);
            }
            catch (const std::exception&) {
                throw std::runtime_error(_("Integer extras must fit a signed 32-bit integer"));
            }
            if (used != extra.value.size())
                throw std::runtime_error(_("Invalid integer extra"));
        }
        else if (extra.type == "EXTRABOOL") {
            if (extra.value != "true" && extra.value != "false" && extra.value != "1" &&
                extra.value != "0")
                throw std::runtime_error(_("Boolean extras must be true, false, 1 or 0"));
        }
        else if (extra.type != "EXTRA" && extra.type != "EXTRAARRAY")
            throw std::runtime_error(_("Unsupported extra type"));
        if (extra.type == "EXTRAARRAY" && (extra.value.find("%ROM%") != std::string::npos ||
                                           extra.value.find("%ROMSAF%") != std::string::npos))
            throw std::runtime_error(_("String arrays cannot carry a ROM transport"));
        if (extra.value.find("%ROMPROVIDER%") != std::string::npos)
            throw std::runtime_error(_("The ROM provider can only be used as Intent data"));
        field("%" + extra.type + "_" + extra.name + "%", extra.value);
    }
    if (data.find("%ROMPROVIDER%") != std::string::npos && data != "%ROMPROVIDER%")
        throw std::runtime_error(_("The provider must be the complete Intent data value"));
    if (clearTask)
        result += " %ACTIVITY_CLEAR_TASK%";
    if (clearTop)
        result += " %ACTIVITY_CLEAR_TOP%";
    if (noHistory)
        result += " %ACTIVITY_NO_HISTORY%";
    return result;
}

void EmulatorLaunchProfile::rom(const std::string& token, const std::string& extraName)
{
    extras.erase(std::remove_if(extras.begin(), extras.end(),
                                [&](const Extra& extra) {
                                    return extra.name != extraName &&
                                           (extra.value == "%ROM%" || extra.value == "%ROMSAF%");
                                }),
                 extras.end());
    if (extraName.empty())
        data = token;
    else {
        if (token == "%ROMPROVIDER%")
            throw std::runtime_error(_("The ROM provider can only be used as Intent data"));
        bool replaced {false};
        for (auto& extra : extras)
            if (extra.name == extraName) {
                extra.type = "EXTRA";
                extra.value = token;
                replaced = true;
            }
        if (!replaced)
            extras.push_back({"EXTRA", extraName, token});
        data.clear();
    }
}
