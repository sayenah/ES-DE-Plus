//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ThemeRepositoryTrustDebug.h
//  Written for ES-DE-Plus. App-context controls, omitted from release builds.

#ifndef ES_APP_THEME_REPOSITORY_TRUST_DEBUG_H
#define ES_APP_THEME_REPOSITORY_TRUST_DEBUG_H
#if !defined(NDEBUG) && (defined(__ANDROID__) || defined(THEME_TRUST_TEST))
#include <cstdint>
#include <functional>
#include <map>
#include <string>
struct git_repository;

namespace ThemeRepositoryTrust::Testing
{
    enum class Fault {
        NONE,
        TEMPORARY,
        REPLACE,
        SEARCH,
        RETIRE_WRITE,
        RETIRE_RENAME,
        RETIRE_CLEANUP
    };
    extern Fault fault;
    extern bool retireEnabled;
    extern std::function<void(const std::string&, const std::string&)> barrier;
    void initialFailure(const std::string& path,
                        const std::map<std::string, std::string>& values,
                        bool parsed,
                        int descriptor,
                        int64_t firstSize);
    void runIfRequested(const std::string& themes, const std::string& privateDirectory);
    void afterAdmission(const std::string& themes, const std::string& privateDirectory);
    void preservingSession(const std::function<void()>& operation);
    void fuseIfRequested(
        const std::string& themes,
        const std::string& privateDirectory,
        const std::function<bool(const std::string&, const std::string&, int)>& operation);
    void changeBeforeLookup(git_repository* repository,
                            const std::string& path,
                            const std::string& privateDirectory,
                            bool worker);
} // namespace ThemeRepositoryTrust::Testing
#endif
#endif
