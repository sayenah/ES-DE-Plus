//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ThemeRepositoryFuse.h
//  Written for ES-DE-Plus using public libgit2 and POSIX interfaces.

#ifndef ES_APP_THEME_REPOSITORY_FUSE_H
#define ES_APP_THEME_REPOSITORY_FUSE_H

#include <map>
#include <string>

namespace ThemeRepositoryFuse
{
    using Values = std::map<std::string, std::string>;
    bool initKeys(const Values& values);
    bool missingOrigin(int api, bool prerequisites, bool identity, bool notFound, bool originRefs);
} // namespace ThemeRepositoryFuse

#if defined(__ANDROID__) || defined(THEME_TRUST_TEST)
#include <functional>
#include <git2.h>

namespace ThemeRepositoryFuse
{
    constexpr const char* temporaryName {"esde-plus-init-config"};
    bool readConfig(const std::string& path, Values& values);
    bool retire(const std::string& path, const std::function<bool()>& identity, Values& initial);
    bool installed(const std::string& path, const Values& initial);
    bool complete(git_repository* repository, const Values& initial, const std::string& url);
    bool originReferences(git_repository* repository);
    int deviceApi();
} // namespace ThemeRepositoryFuse
#endif
#endif
