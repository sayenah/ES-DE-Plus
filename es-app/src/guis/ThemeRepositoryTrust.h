//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ThemeRepositoryTrust.h
//  Written for ES-DE-Plus using public libgit2 APIs; no libgit2 source copied.

#ifndef ES_APP_THEME_REPOSITORY_TRUST_H
#define ES_APP_THEME_REPOSITORY_TRUST_H

#include "rapidjson/document.h"

#include <functional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace ThemeRepositoryTrust
{
    using Entry = std::pair<std::string, std::string>;
    std::vector<Entry> jsonEntries(const rapidjson::Document& doc);
    bool validName(const std::string& name);
    std::set<std::string> filesystemNames(const std::string& name);
    std::vector<bool> admission(const std::vector<Entry>& entries);
    bool configText(const std::string& root,
                    const std::vector<std::string>& names,
                    std::string& result);
} // namespace ThemeRepositoryTrust

#if defined(__ANDROID__) || defined(THEME_TRUST_TEST)
#include <git2.h>
#if __has_include(<git2/sys/errors.h>)
#include <git2/sys/errors.h>
#endif

namespace ThemeRepositoryTrust
{
    void configure(const std::string& themeDirectory,
                   const std::string& privateDirectory,
                   std::function<void()> report = {});
    void close();
    bool ready();
    void reportFailure();
    bool expectList(const std::string& url);
    bool admit(const rapidjson::Document& document);
    bool admitted(const rapidjson::Value& entry);
    bool permit(const std::string& path);
    bool disabled(const std::string& path);
    void retainUntilNextVisit(const std::string& path);
    bool verify(git_repository* repository, const std::string& path);
    bool verify(git_repository* repository);
    bool remote(git_remote* remote, const std::string& path);
    bool corrupt(int error, const std::string& path);
    int create(git_repository** out, const char* path, int bare, void* payload);
    int createRemote(git_remote** out,
                     git_repository* repository,
                     const char* name,
                     const char* url,
                     void* payload);
} // namespace ThemeRepositoryTrust
#endif
#endif
