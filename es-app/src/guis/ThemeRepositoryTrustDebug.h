//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ThemeRepositoryTrustDebug.h
//  Written for ES-DE-Plus. App-context controls, omitted from release builds.

#ifndef ES_APP_THEME_REPOSITORY_TRUST_DEBUG_H
#define ES_APP_THEME_REPOSITORY_TRUST_DEBUG_H
#if !defined(NDEBUG) && (defined(__ANDROID__) || defined(THEME_TRUST_TEST))
#include <functional>
#include <string>
struct git_repository;

namespace ThemeRepositoryTrust::Testing
{
    enum class Fault {
        NONE,
        TEMPORARY,
        REPLACE,
        SEARCH
    };
    extern Fault fault;
    extern std::function<void(const std::string&, const std::string&)> barrier;
    void runIfRequested(const std::string& themes, const std::string& privateDirectory);
    void afterAdmission(const std::string& themes, const std::string& privateDirectory);
    void changeBeforeLookup(git_repository* repository,
                            const std::string& path,
                            const std::string& privateDirectory,
                            bool worker);
} // namespace ThemeRepositoryTrust::Testing
#endif
#endif
