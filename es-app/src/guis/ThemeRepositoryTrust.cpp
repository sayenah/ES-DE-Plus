//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ThemeRepositoryTrust.cpp
//  Written for ES-DE-Plus using public libgit2 APIs; no libgit2 source copied.

#include "ThemeRepositoryTrust.h"

#include <algorithm>
#include <map>

namespace
{
    std::string folded(std::string value)
    {
        for (auto& c : value)
            if (c >= 'A' && c <= 'Z')
                c += 'a' - 'A';
        return value;
    }

    bool quoted(const std::string& value, std::string& result)
    {
        result = "\"";
        for (unsigned char c : value) {
            if (c < 32 || c == 127)
                return false;
            if (c == '\\' || c == '"')
                result += '\\';
            result += c;
        }
        result += '"';
        return true;
    }
} // namespace

bool ThemeRepositoryTrust::validName(const std::string& name)
{
    // Leave room for the longest manual-install + numbered recovery suffix.
    if (name.empty() || name.front() == '.' ||
        name.size() > 255 - std::string("-master_9_WRONG_URL_DISABLED").size())
        return false;
    for (unsigned char c : name)
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
              c == '.' || c == '_' || c == '-'))
            return false;
    const std::string lower {folded(name)};
    return lower.size() < 9 || lower.substr(lower.size() - 9) != "_disabled";
}

std::set<std::string> ThemeRepositoryTrust::filesystemNames(const std::string& name)
{
    std::set<std::string> names;
    for (const std::string manual : {"", "-main", "-master"}) {
        names.insert(name + manual);
        for (const std::string suffix :
             {"_DISABLED", "_CORRUPT_DISABLED", "_DIVERGED_DISABLED", "_WRONG_URL_DISABLED"}) {
            names.insert(name + manual + suffix);
            for (int i {1}; i < 10; ++i)
                names.insert(name + manual + "_" + std::to_string(i) + suffix);
        }
    }
    return names;
}

std::vector<bool> ThemeRepositoryTrust::admission(const std::vector<Entry>& entries)
{
    std::vector<bool> accepted(entries.size(), true);
    std::map<std::string, std::vector<size_t>> owners;
    std::set<std::string> reserved;
    for (const auto& name : filesystemNames("themes-list"))
        reserved.insert(folded(name));
    for (size_t i {0}; i < entries.size(); ++i) {
        const auto& entry = entries[i];
        std::string escaped;
        if (!validName(entry.first)) {
            accepted[i] = false;
            continue;
        }
        if (entry.second.empty() || !quoted(entry.second, escaped))
            accepted[i] = false;
        for (const auto& name : filesystemNames(entry.first)) {
            const std::string key {folded(name)};
            if (reserved.count(key))
                accepted[i] = false;
            owners[key].push_back(i);
        }
    }
    // Reject every ambiguous entry, independently of JSON ordering.
    for (const auto& item : owners)
        if (item.second.size() > 1)
            for (size_t index : item.second)
                accepted[index] = false;
    return accepted;
}

bool ThemeRepositoryTrust::configText(const std::string& root,
                                      const std::vector<std::string>& names,
                                      std::string& result)
{
    result.clear();
    if (root.empty() || root.front() != '/' || root.back() == '/')
        return false;
    std::string candidate {"[safe]\n"};
    for (const auto& name : names) {
        std::string escaped;
        if (!validName(name) || !quoted(root + "/" + name, escaped))
            return false;
        candidate += "\tdirectory = " + escaped + "\n";
    }
    result = candidate;
    return true;
}

std::vector<ThemeRepositoryTrust::Entry> ThemeRepositoryTrust::jsonEntries(
    const rapidjson::Document& doc)
{
    std::vector<ThemeRepositoryTrust::Entry> result;
    if (!doc.IsObject())
        return result;
    for (const char* key : {"themes", "themesAndroid"}) {
        if (!doc.HasMember(key) || !doc[key].IsArray())
            continue;
        for (const auto& entry : doc[key].GetArray()) {
            if (!entry.IsObject() || !entry.HasMember("reponame") || !entry["reponame"].IsString())
                continue;
            result.emplace_back(
                std::string(entry["reponame"].GetString(), entry["reponame"].GetStringLength()),
                entry.HasMember("url") && entry["url"].IsString() ?
                    std::string(entry["url"].GetString(), entry["url"].GetStringLength()) :
                    "");
        }
    }
    return result;
}

#if defined(__ANDROID__) || defined(THEME_TRUST_TEST)
#include "ThemeRepositoryTrustDebug.h"
#ifndef NDEBUG
#include <thread>
#endif
#include <iostream>
#if defined(__ANDROID__)
#include "Log.h"
#endif

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <limits.h>
#include <sys/stat.h>
#include <unistd.h>

namespace
{
    struct Session {
        bool configured {false};
        std::function<void()> report;
        std::string suppliedRoot;
        std::string root;
        std::string privateDirectory;
        std::string filesDirectory;
        std::map<std::string, std::string> repositories;
        std::set<std::string> paths;
        std::set<std::string> retained;
        std::set<std::string> measured;
#ifndef NDEBUG
        std::thread::id ownerThread;
#endif
    } session;

    std::string canonical(const char* path)
    {
        char result[PATH_MAX];
        return path && realpath(path, result) ? result : "";
    }

    void diagnostic(const std::string& detail)
    {
#if defined(__ANDROID__)
        LOG(LogInfo) << "ThemeRepositoryTrust: " << detail;
#else
        std::cerr << "ThemeRepositoryTrust: " << detail << '\n';
#endif
    }

    bool failure(const std::string& detail)
    {
        diagnostic(detail);
        git_error_set_str(GIT_ERROR_REPOSITORY,
                          "Theme repository trust check failed; reopen the downloader after "
                          "checking access to the application-data folder");
        return false;
    }

    bool realDirectory(const std::string& path)
    {
        struct stat info {
        };
        return lstat(path.c_str(), &info) == 0 && S_ISDIR(info.st_mode);
    }

    void measure(const std::string& path)
    {
        struct stat info {
        };
        if (session.measured.insert(path).second && stat(path.c_str(), &info) == 0)
            diagnostic("app-context euid=" + std::to_string(geteuid()) + " path=" + path + " uid=" +
                       std::to_string(info.st_uid) + " gid=" + std::to_string(info.st_gid) +
                       " mode=" + std::to_string(info.st_mode));
    }

    bool replaceConfig(const std::map<std::string, std::string>& repositories)
    {
        // A stale on-disk allowlist never satisfies this explicit prerequisite.
        session.configured = false;
        std::vector<std::string> names;
        for (const auto& entry : repositories)
            names.push_back(entry.first);
        std::string contents;
        if (!ThemeRepositoryTrust::configText(session.root, names, contents))
            return failure("Cannot represent the selected folder in the private Git config");
        std::string temporary {session.privateDirectory + "/.gitconfig.XXXXXX"};
#ifndef NDEBUG
        if (ThemeRepositoryTrust::Testing::fault == ThemeRepositoryTrust::Testing::Fault::TEMPORARY)
            return failure("Injected temporary config creation failure");
#endif
        int fd {mkstemp(temporary.data())};
        if (fd < 0)
            return failure("Cannot create the private Git config temporary file");
        bool success {fchmod(fd, 0600) == 0};
        size_t offset {0};
        while (success && offset < contents.size()) {
            const ssize_t written {write(fd, contents.data() + offset, contents.size() - offset)};
            if (written < 0 && errno == EINTR)
                continue;
            if (written <= 0)
                success = false;
            else
                offset += written;
        }
        if (fsync(fd) != 0)
            success = false;
        if (::close(fd) != 0)
            success = false;
#ifndef NDEBUG
        if (ThemeRepositoryTrust::Testing::fault == ThemeRepositoryTrust::Testing::Fault::REPLACE)
            success = false;
#endif
        if (success)
            success =
                rename(temporary.c_str(), (session.privateDirectory + "/.gitconfig").c_str()) == 0;
        if (!success) {
            unlink(temporary.c_str());
            return failure("Cannot atomically replace the private Git config");
        }
        session.repositories = repositories;
        session.paths.clear();
        for (const auto& entry : repositories)
            for (const auto& path : ThemeRepositoryTrust::filesystemNames(entry.first))
                session.paths.insert(path);
        session.configured = true;
        diagnostic("owner validation=1; config=" + session.privateDirectory +
                   "/.gitconfig; exact entries=" + std::to_string(names.size()));
        return true;
    }

    std::string nameOf(const std::string& path)
    {
        const size_t slash {path.find_last_of('/')};
        return slash == std::string::npos ? "" : path.substr(slash + 1);
    }

} // namespace

void ThemeRepositoryTrust::configure(const std::string& themeDirectory,
                                     const std::string& privateDirectory,
                                     std::function<void()> report)
{
#ifndef NDEBUG
    Testing::runIfRequested(themeDirectory, privateDirectory);
#endif
    session = {};
    session.report = std::move(report);
#ifndef NDEBUG
    session.ownerThread = std::this_thread::get_id();
#endif
    session.suppliedRoot = themeDirectory;
    while (!session.suppliedRoot.empty() && session.suppliedRoot.back() == '/')
        session.suppliedRoot.pop_back();
    const size_t slash {session.suppliedRoot.find_last_of('/')};
    const std::string data {session.suppliedRoot.substr(0, slash)};
    if (canonical(data.c_str()).empty() || access(data.c_str(), R_OK | W_OK | X_OK) != 0) {
        failure("Selected data folder is unavailable; it will not be recreated");
        return;
    }
    session.root = canonical(data.c_str()) + "/" + nameOf(session.suppliedRoot);
    struct stat themeInfo {
    };
    if (lstat(session.suppliedRoot.c_str(), &themeInfo) == 0 ?
            !S_ISDIR(themeInfo.st_mode) || canonical(session.suppliedRoot.c_str()) != session.root :
            errno != ENOENT) {
        failure("Themes path must be a direct directory beneath the selected data folder");
        return;
    }
    measure(data);
    session.privateDirectory = privateDirectory + "/libgit2";
    session.filesDirectory = privateDirectory;
    struct stat info {
    };
    if ((mkdir(session.privateDirectory.c_str(), 0700) != 0 && errno != EEXIST) ||
        lstat(session.privateDirectory.c_str(), &info) != 0 || !S_ISDIR(info.st_mode) ||
        info.st_uid != geteuid() || chmod(session.privateDirectory.c_str(), 0700) != 0) {
        failure("Cannot prepare the app-private libgit2 directory");
        return;
    }
    int ownerValidation {0};
    if (git_libgit2_opts(GIT_OPT_GET_OWNER_VALIDATION, &ownerValidation) != 0 ||
        ownerValidation != 1) {
        failure("libgit2 owner validation is not enabled");
        return;
    }
#ifndef NDEBUG
    if (Testing::fault == Testing::Fault::SEARCH) {
        failure("Injected search-path setup failure");
        return;
    }
#endif
    for (int level :
         {GIT_CONFIG_LEVEL_SYSTEM, GIT_CONFIG_LEVEL_XDG, GIT_CONFIG_LEVEL_PROGRAMDATA}) {
        if (git_libgit2_opts(GIT_OPT_SET_SEARCH_PATH, level, "") != 0) {
            failure("Cannot clear an external libgit2 config search path");
            return;
        }
    }
    if (git_libgit2_opts(GIT_OPT_SET_SEARCH_PATH, GIT_CONFIG_LEVEL_GLOBAL,
                         session.privateDirectory.c_str()) != 0) {
        failure("Cannot set the private libgit2 config search path");
        return;
    }
    if (!replaceConfig({{"themes-list", ""}}))
        return;
    // Bootstrap the data-side directory only after the private configuration
    // prerequisite succeeds; never create a missing selected data root.
    if ((mkdir(session.suppliedRoot.c_str(), 0755) != 0 && errno != EEXIST) ||
        !realDirectory(session.suppliedRoot) ||
        canonical(session.suppliedRoot.c_str()) != session.root ||
        access(session.suppliedRoot.c_str(), R_OK | W_OK | X_OK) != 0) {
        session.configured = false;
        failure("Cannot prepare writable theme storage; restore access and reopen the downloader");
        return;
    }
    measure(session.root);
}

void ThemeRepositoryTrust::close() { session = {}; }

bool ThemeRepositoryTrust::ready()
{
    if (!session.configured)
        return false;
    if (canonical(session.suppliedRoot.c_str()) != session.root ||
        access(session.suppliedRoot.c_str(), R_OK | W_OK | X_OK) != 0) {
        session.configured = false;
        return failure("Theme storage is no longer accessible; reselect it in the configurator");
    }
    return true;
}

void ThemeRepositoryTrust::reportFailure()
{
    if (session.report)
        session.report();
}

bool ThemeRepositoryTrust::expectList(const std::string& url)
{
    if (!ready())
        return false;
    session.repositories["themes-list"] = url;
    return true;
}

bool ThemeRepositoryTrust::admit(const rapidjson::Document& document)
{
    if (!ready())
        return false;
    if (!document.IsObject()) {
        session.configured = false;
        return failure("Theme list is not a JSON object");
    }
    const auto entries {jsonEntries(document)};
    const auto accepted {admission(entries)};
    std::map<std::string, std::string> repositories {
        {"themes-list", session.repositories["themes-list"]}};
    for (size_t i {0}; i < entries.size(); ++i) {
        if (accepted[i])
            repositories.insert(entries[i]);
        else
            diagnostic("Rejected ambiguous or invalid JSON entry " + std::to_string(i));
    }
    const bool success {replaceConfig(repositories)};
#ifndef NDEBUG
    if (success)
        Testing::afterAdmission(session.root, session.filesDirectory);
#endif
    return success;
}

bool ThemeRepositoryTrust::admitted(const rapidjson::Value& entry)
{
    if (!ready() || !entry.IsObject() || !entry.HasMember("reponame") ||
        !entry["reponame"].IsString() || !entry.HasMember("url") || !entry["url"].IsString())
        return false;
    const std::string name {entry["reponame"].GetString(), entry["reponame"].GetStringLength()};
    const auto found {session.repositories.find(name)};
    return name != "themes-list" && found != session.repositories.end() &&
           found->second == std::string(entry["url"].GetString(), entry["url"].GetStringLength());
}

bool ThemeRepositoryTrust::permit(const std::string& path)
{
    if (!ready() || !session.paths.count(nameOf(path)))
        return failure("Operation on an unadmitted repository path refused");
    const size_t slash {path.find_last_of('/')};
    if (canonical(path.substr(0, slash).c_str()) != session.root)
        return failure("Repository parent does not match the selected themes directory");
    struct stat info {
    };
    if (lstat(path.c_str(), &info) != 0)
        return errno == ENOENT || failure("Cannot inspect the admitted repository path");
    if (!S_ISDIR(info.st_mode))
        return failure("Repository path is not a direct directory beneath the themes directory");
    if (access(path.c_str(), R_OK | W_OK | X_OK) != 0)
        return failure("Admitted repository storage is inaccessible or read-only");
    return (canonical(path.c_str()) == session.root + "/" + nameOf(path)) ||
           failure("Repository path is not a direct directory beneath the themes directory");
}

bool ThemeRepositoryTrust::disabled(const std::string& path)
{
    const std::string name {nameOf(path)};
    return !session.retained.count(name) && name.size() > 9 &&
           name.substr(name.size() - 9) == "_DISABLED" && permit(path);
}

void ThemeRepositoryTrust::retainUntilNextVisit(const std::string& path)
{
    session.retained.insert(nameOf(path));
}

bool ThemeRepositoryTrust::verify(git_repository* repository, const std::string& path)
{
    if (!permit(path) || !repository || !session.repositories.count(nameOf(path)))
        return failure("Repository identity has no admission");
    const std::string expected {session.root + "/" + nameOf(path)};
    struct stat info {
    };
    errno = 0;
    const bool noCommonFile {lstat((expected + "/.git/commondir").c_str(), &info) != 0 &&
                             errno == ENOENT};
    if (!realDirectory(expected + "/.git") || !noCommonFile || git_repository_is_bare(repository) ||
        git_repository_is_worktree(repository) ||
        canonical(git_repository_workdir(repository)) != expected ||
        canonical(git_repository_path(repository)) != expected + "/.git" ||
        canonical(git_repository_commondir(repository)) != expected + "/.git")
        return failure("Repository workdir/gitdir/commondir identity mismatch");
    measure(expected + "/.git");
#ifndef NDEBUG
    try {
        Testing::changeBeforeLookup(repository, expected, session.filesDirectory,
                                    std::this_thread::get_id() != session.ownerThread);
    }
    catch (const std::exception& error) {
        return failure(std::string("Debug remote barrier failed: ") + error.what());
    }
#endif
    return true;
}

bool ThemeRepositoryTrust::verify(git_repository* repository)
{
    const char* workdir {repository ? git_repository_workdir(repository) : nullptr};
    std::string path {workdir ? workdir : ""};
    while (!path.empty() && path.back() == '/')
        path.pop_back();
    return verify(repository, path);
}

bool ThemeRepositoryTrust::remote(git_remote* remote, const std::string& path)
{
    if (!permit(path))
        return false;
    const auto found {session.repositories.find(nameOf(path))};
    const char* url {remote ? git_remote_url(remote) : nullptr};
    return (found != session.repositories.end() && !found->second.empty() && url &&
            found->second == url) ||
           failure("Actual fetch remote differs from the admitted URL");
}

bool ThemeRepositoryTrust::corrupt(int error, const std::string& path)
{
    const git_error* detail {git_error_last()};
    const bool accessFailure {detail &&
                              (detail->klass == GIT_ERROR_OS || detail->klass == GIT_ERROR_CONFIG)};
    if (error == GIT_EOWNER || accessFailure || !permit(path))
        return false;
    if (realDirectory(path + "/.git") && access((path + "/.git").c_str(), R_OK | W_OK | X_OK) != 0)
        return false;
    return true;
}

int ThemeRepositoryTrust::create(git_repository** out, const char* path, int bare, void*)
{
    *out = nullptr;
    if (!path || bare || !permit(path))
        return -1;
#ifndef NDEBUG
    if (Testing::barrier)
        Testing::barrier("clone-before-init", path);
#endif
    struct stat info {
    };
    // libgit2 may already have created an empty workdir. Never reinitialize metadata.
    if (lstat((std::string(path) + "/.git").c_str(), &info) == 0 || errno != ENOENT) {
        failure("Clone refused unexpected pre-existing repository metadata");
        return -1;
    }
    git_repository_init_options options {};
    if (git_repository_init_options_init(&options, GIT_REPOSITORY_INIT_OPTIONS_VERSION) != 0)
        return -1;
    options.flags = GIT_REPOSITORY_INIT_NO_REINIT | GIT_REPOSITORY_INIT_MKDIR;
#ifndef NDEBUG
    if (Testing::barrier)
        Testing::barrier("clone-after-precheck", path);
#endif
    git_repository* repository {nullptr};
    int result {git_repository_init_ext(&repository, path, &options)};
#ifndef NDEBUG
    if (result == 0 && Testing::barrier)
        Testing::barrier("clone-after-init", path);
#endif
    if (result == 0 && !verify(repository, path))
        result = -1;
    if (result != 0) {
        git_repository_free(repository);
        return result;
    }
    *out = repository;
    return 0;
}

int ThemeRepositoryTrust::createRemote(
    git_remote** out, git_repository* repository, const char* name, const char* url, void*)
{
    *out = nullptr;
    const char* workdir {repository ? git_repository_workdir(repository) : nullptr};
    std::string path {workdir ? workdir : ""};
    while (!path.empty() && path.back() == '/')
        path.pop_back();
#ifndef NDEBUG
    if (Testing::barrier)
        Testing::barrier("clone-before-remote", path);
#endif
    if (!verify(repository, path))
        return -1;
    const int result {git_remote_create(out, repository, name, url)};
    if (result != 0)
        return result;
    if (remote(*out, path))
        return 0;
    git_remote_free(*out);
    *out = nullptr;
    return -1;
}
#endif
