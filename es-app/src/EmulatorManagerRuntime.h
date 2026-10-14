//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  EmulatorManagerRuntime.h
//
//  Written for ES-DE-Plus. Android-only integration with upstream readers and launch parser.
//

#ifndef ES_APP_EMULATOR_MANAGER_RUNTIME_H
#define ES_APP_EMULATOR_MANAGER_RUNTIME_H

#if defined(__ANDROID__)
#include "EmulatorManagerConfig.h"
#include <stdexcept>

class EmulatorManagerRuntime
{
public:
    struct SelectionConflict : public std::runtime_error {
        SelectionConflict(const std::string& message, const std::vector<std::string>& values)
            : std::runtime_error {message}
            , labels {values}
        {
        }
        std::vector<std::string> labels;
    };
    static void clearSelections(const EmulatorManagerConfig::System& system,
                                const std::vector<std::string>& labels);
    static EmulatorManagerConfig configuration();
    static std::string path(const EmulatorManagerConfig::System& system);
    static bool test(const EmulatorManagerConfig::System& system,
                     const std::string& file,
                     const std::string& profile,
                     const std::string& component);
    static void setDefault(const EmulatorManagerConfig::System& system, const std::string& label);
    static void checkSelections(const EmulatorManagerConfig::System& system,
                                const std::vector<std::string>& retainedLabels);
    static void apply(const std::string& systemName);

    // Only active during the synchronous transient test on the frontend thread.
    static inline bool testing {false};
    static inline std::string testCommand;
    static inline int testResult {-1};
};
#endif

#endif
