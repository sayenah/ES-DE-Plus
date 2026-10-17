//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ThemeRepositoryFuse.cpp
//  Written for ES-DE-Plus. Original init-key policy and clone-only FUSE retirement;
//  no libgit2 or platform implementation copied. D-012 amendments 6 and 7.

#include "ThemeRepositoryFuse.h"

bool ThemeRepositoryFuse::initKeys(const Values& values)
{
    // Public libgit2 init output, pinned independently by the Linux init test.
    // Supported symlinks and case sensitivity are represented by absent keys.
    const Values fixed {{"core.repositoryformatversion", "0"},
                        {"core.bare", "false"},
                        {"core.logallrefupdates", "true"}};
    for (const auto& entry : fixed)
        if (!values.count(entry.first) || values.at(entry.first) != entry.second)
            return false;
    if (!values.count("core.filemode"))
        return false;
    for (const auto& entry : values) {
        if (fixed.count(entry.first))
            continue;
        if (entry.first == "core.symlinks" && entry.second == "false")
            continue;
        if (entry.first == "core.ignorecase" && entry.second == "true")
            continue;
        // libgit2's optional iconv build records its Unicode filesystem probe.
        if ((entry.first == "core.filemode" || entry.first == "core.precomposeunicode") &&
            (entry.second == "true" || entry.second == "false"))
            continue;
        return false;
    }
    return true;
}

bool ThemeRepositoryFuse::missingOrigin(
    int api, bool prerequisites, bool identity, bool notFound, bool originRefs)
{
    return (api == 31 || api == 32) && prerequisites && identity && notFound && originRefs;
}

#if defined(__ANDROID__) || defined(THEME_TRUST_TEST)
#include "ThemeRepositoryTrust.h"
#include "ThemeRepositoryTrustDebug.h"
#if __has_include(<git2/sys/errors.h>)
#include <git2/sys/errors.h>
#endif

#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__ANDROID__)
#include "Log.h"
#include "Window.h"
#include "guis/GuiMsgBox.h"
#include <android/api-level.h>
#endif

namespace
{
    class Descriptor
    {
    public:
        explicit Descriptor(int fd)
            : value {fd}
        {
        }
        ~Descriptor()
        {
            if (value >= 0)
                close(value);
        }
        int value;
    };

    bool failed(const char* message)
    {
        git_error_set_str(GIT_ERROR_REPOSITORY, message);
        return false;
    }

    void barrier(const char* stage, const std::string& path)
    {
#ifndef NDEBUG
        ThemeRepositoryTrust::Testing::interruptIfRequested(stage, path);
        if (ThemeRepositoryTrust::Testing::barrier)
            ThemeRepositoryTrust::Testing::barrier(stage, path);
#else
        static_cast<void>(stage);
        static_cast<void>(path);
#endif
    }

    bool configValues(int fd, ThemeRepositoryFuse::Values& values, struct stat* first = nullptr)
    {
        struct stat info {
        };
        if (fd < 0 || fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || lseek(fd, 0, SEEK_SET) < 0)
            return failed("Clone init config is not a readable regular file");
        if (first)
            *first = info;
#if defined(__APPLE__)
        const std::string descriptor {"/dev/fd/" + std::to_string(fd)};
#else
        const std::string descriptor {"/proc/self/fd/" + std::to_string(fd)};
#endif
        git_config* config {nullptr};
        if (git_config_open_ondisk(&config, descriptor.c_str()) != 0)
            return false;
        values.clear();
        const int result {git_config_foreach(
            config,
            [](const git_config_entry* entry, void* data) {
                auto& output {*static_cast<ThemeRepositoryFuse::Values*>(data)};
                if (!entry->name || !entry->value || output.count(entry->name))
                    return -1;
                std::string value {entry->value};
                if (std::string(entry->name) == "core.repositoryformatversion") {
                    int64_t number;
                    if (git_config_parse_int64(&number, entry->value) != 0)
                        return -1;
                    value = std::to_string(number);
                }
                else if (std::string(entry->name).compare(0, 5, "core.") == 0) {
                    int boolean;
                    if (git_config_parse_bool(&boolean, entry->value) != 0)
                        return -1;
                    value = boolean ? "true" : "false";
                }
                output.emplace(entry->name, value);
                return 0;
            },
            &values)};
        git_config_free(config);
        return result == 0 || failed("Clone config cannot be read by meaning");
    }
} // namespace

bool ThemeRepositoryFuse::readConfig(const std::string& path, Values& values)
{
    Descriptor fd {open(path.c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC)};
    return configValues(fd.value, values);
}

bool ThemeRepositoryFuse::installed(const std::string& path, const Values& initial)
{
    Values actual;
    return (readConfig(path + "/.git/config", actual) && actual == initial && initKeys(actual)) ||
           failed("Installed clone init config does not match the expected meaning");
}

bool ThemeRepositoryFuse::retire(const std::string& path,
                                 const std::function<bool()>& identity,
                                 Values& initial)
{
    if (!identity())
        return failed("Clone identity is unavailable before config retirement");
    {
        Descriptor source {
            open((path + "/.git/config").c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC)};
        struct stat first {
        };
        first.st_size = -1;
        const bool parsed {configValues(source.value, initial, &first)};
        if (!parsed || !initKeys(initial)) {
#ifndef NDEBUG
            ThemeRepositoryTrust::Testing::initialFailure(path, initial, parsed, source.value,
                                                          first.st_size);
#endif
            return failed("Clone init keys differ from the ES-DE-Plus init-key table");
        }
    }
    Descriptor parent {open(path.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)};
    Descriptor directory {
        parent.value < 0 ?
            -1 :
            openat(parent.value, ".git", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)};
    auto currentIdentity = [&] {
        struct stat heldParent {
        }, namedParent {}, heldDirectory {}, namedDirectory {};
        return identity() && fstat(parent.value, &heldParent) == 0 &&
               lstat(path.c_str(), &namedParent) == 0 && S_ISDIR(namedParent.st_mode) &&
               heldParent.st_dev == namedParent.st_dev && heldParent.st_ino == namedParent.st_ino &&
               fstat(directory.value, &heldDirectory) == 0 &&
               lstat((path + "/.git").c_str(), &namedDirectory) == 0 &&
               S_ISDIR(namedDirectory.st_mode) && heldDirectory.st_dev == namedDirectory.st_dev &&
               heldDirectory.st_ino == namedDirectory.st_ino;
    };
    if (directory.value < 0 || !currentIdentity())
        return failed("Clone gitdir is unavailable before retirement");
    barrier("clone-retire-before-create", path);
    Descriptor temporary {openat(directory.value, temporaryName,
                                 O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600)};
    if (temporary.value < 0)
        return failed("Clone retirement temporary name is occupied or inaccessible");
    auto refuse = [&](const char* message) {
        // A held directory descriptor does not preserve admission after a
        // parent was moved. Failed identity also blocks temporary cleanup.
        struct stat held {
        }, named {};
        const bool owned {
            currentIdentity() && fstat(temporary.value, &held) == 0 &&
            fstatat(directory.value, temporaryName, &named, AT_SYMLINK_NOFOLLOW) == 0 &&
            S_ISREG(named.st_mode) && held.st_dev == named.st_dev && held.st_ino == named.st_ino};
#ifndef NDEBUG
        if (ThemeRepositoryTrust::Testing::fault !=
                ThemeRepositoryTrust::Testing::Fault::RETIRE_CLEANUP &&
            owned)
#else
        if (owned)
#endif
            unlinkat(directory.value, temporaryName, 0);
        return failed(message);
    };
    barrier("clone-retire-created", path);
    std::string text {"[core]\n"};
    for (const auto& entry : initial)
        text += "\t" + entry.first.substr(5) + " = " + entry.second + "\n";
    size_t offset {0};
    while (offset < text.size()) {
#ifndef NDEBUG
        if (ThemeRepositoryTrust::Testing::fault ==
            ThemeRepositoryTrust::Testing::Fault::RETIRE_WRITE)
            return refuse("Injected clone retirement write failure");
#endif
        const ssize_t count {write(temporary.value, text.data() + offset, text.size() - offset)};
        if (count < 0 && errno == EINTR)
            continue;
        if (count <= 0)
            return refuse("Clone retirement write failed");
        offset += count;
    }
    if (fsync(temporary.value) != 0)
        return refuse("Clone retirement synchronization failed");
    barrier("clone-retire-written", path);
    struct stat held {
    }, named {};
    Values written;
    auto sameSource = [&] {
        return fstat(temporary.value, &held) == 0 &&
               fstatat(directory.value, temporaryName, &named, AT_SYMLINK_NOFOLLOW) == 0 &&
               S_ISREG(named.st_mode) && held.st_dev == named.st_dev &&
               held.st_ino == named.st_ino && configValues(temporary.value, written) &&
               written == initial;
    };
    if (!currentIdentity() || !sameSource())
        return refuse("Clone retirement source changed");
    if (unlinkat(directory.value, "config", 0) != 0)
        return refuse("Clone retirement unlink failed");
    barrier("clone-retire-unlinked", path);
#ifndef NDEBUG
    if (ThemeRepositoryTrust::Testing::fault ==
            ThemeRepositoryTrust::Testing::Fault::RETIRE_RENAME ||
        ThemeRepositoryTrust::Testing::fault ==
            ThemeRepositoryTrust::Testing::Fault::RETIRE_CLEANUP)
        return refuse("Injected clone retirement rename failure after unlink");
#endif
    // This check blocks deterministic planted destinations, not a writer in
    // the check/rename gap. Destination replacement cannot prove retirement.
    errno = 0;
    if (!currentIdentity() || !sameSource())
        return refuse("Clone retirement source or identity changed after unlink");
    errno = 0;
    if (fstatat(directory.value, "config", &named, AT_SYMLINK_NOFOLLOW) == 0 || errno != ENOENT)
        return refuse("Clone retirement destination is no longer absent");
    if (renameat(directory.value, temporaryName, directory.value, "config") != 0)
        return refuse("Clone retirement rename failed");
    barrier("clone-retire-renamed", path);
    return currentIdentity() && installed(path, initial);
}

bool ThemeRepositoryFuse::complete(git_repository* repository,
                                   const Values& initial,
                                   const std::string& url)
{
    Values values;
    const char* directory {git_repository_path(repository)};
    if (!directory || !readConfig(std::string(directory) + "config", values))
        return false;
    for (const auto& entry : initial)
        if (!values.count(entry.first) || values.at(entry.first) != entry.second)
            return failed("Completed clone lost an init key");
    git_reference* head {nullptr};
    if (git_repository_head(&head, repository) != 0)
        return failed("Completed clone has no branch");
    const std::string branch {git_reference_shorthand(head)};
    const std::string full {git_reference_name(head)};
    git_reference_free(head);
    const Values expected {{"remote.origin.url", url},
                           {"remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"},
                           {"branch." + branch + ".remote", "origin"},
                           {"branch." + branch + ".merge", full}};
    for (const auto& entry : expected)
        if (!values.count(entry.first) || values.at(entry.first) != entry.second)
            return failed("Completed clone lost its origin, fetch refspec or tracking branch");
    return true;
}

bool ThemeRepositoryFuse::originReferences(git_repository* repository)
{
    git_reference_iterator* iterator {nullptr};
    if (git_reference_iterator_glob_new(&iterator, repository, "refs/remotes/origin/*") != 0)
        return false;
    git_reference* reference {nullptr};
    const bool found {git_reference_next(&reference, iterator) == 0};
    git_reference_free(reference);
    git_reference_iterator_free(iterator);
    return found;
}

bool ThemeRepositoryFuse::missingOrigin(git_repository* repository,
                                        const std::string& path,
                                        int lookup)
{
    if ((deviceApi() != 31 && deviceApi() != 32) || lookup != GIT_ENOTFOUND ||
        !ThemeRepositoryTrust::permit(path) || !ThemeRepositoryTrust::verify(repository, path))
        return false;
    // Preserve the remote-lookup diagnostic across the read-only refs query.
    // Iterator exhaustion must not turn a missing local config key into a
    // different class of error or make it eligible for corrupt recovery.
    const git_error* original {git_error_last()};
    const int errorClass {original ? original->klass : GIT_ERROR_CONFIG};
    const std::string message {original && original->message ? original->message :
                                                               "Repository origin is missing"};
    // An unreadable, symlinked or unparseable local config is not this class.
    Values values;
    if (!readConfig(path + "/.git/config", values))
        return false;
    const bool result {missingOrigin(deviceApi(), true, true, true, originReferences(repository))};
#if defined(__ANDROID__) && !defined(NDEBUG)
    if (result)
        LOG(LogDebug) << "Android 12 missing-origin classification; no automatic mutation: "
                      << path;
#endif
    git_error_set_str(errorClass, message.c_str());
    return result;
}

bool ThemeRepositoryFuse::recheckListRecovery(const std::string& path)
{
    if (path.substr(path.find_last_of('/') + 1) != "themes-list" ||
        !ThemeRepositoryTrust::permit(path))
        return false;
    git_repository* repository {nullptr};
    git_remote* origin {nullptr};
    const int opened {git_repository_open(&repository, path.c_str())};
    const bool identity {opened == 0 && ThemeRepositoryTrust::verify(repository, path)};
    const int lookup {identity ? git_remote_lookup(&origin, repository, "origin") : GIT_ERROR};
    const bool result {identity && missingOrigin(repository, path, lookup)};
    git_remote_free(origin);
    git_repository_free(repository);
    return result;
}

#if defined(__ANDROID__)
void ThemeRepositoryFuse::offerListRecovery(const std::string& path,
                                            const std::function<void()>& proceed,
                                            const std::function<void()>& cancel)
{
    Window::getInstance()->pushGui(new GuiMsgBox(
        _("ANDROID 12 COULD NOT READ THE THEMES LIST REPOSITORY'S ORIGIN. A FRESH DOWNLOAD IS "
          "REQUIRED. THE OLD DIRECTORY \"themes-list\" WILL BE RENAMED TO "
          "\"themes-list_CORRUPT_DISABLED\" AND REMOVED ON A LATER DOWNLOADER VISIT."),
        _("PROCEED"),
        [path, proceed] {
            if (!recheckListRecovery(path)) {
#ifndef NDEBUG
                LOG(LogDebug) << "Theme list recovery confirmation refused: " << path;
#endif
                ThemeRepositoryTrust::reportFailure();
                return;
            }
#ifndef NDEBUG
            LOG(LogDebug) << "Theme list recovery confirmation accepted: " << path;
#endif
            proceed();
        },
        _("CANCEL"),
        [=] {
#ifndef NDEBUG
            LOG(LogDebug) << "Theme list recovery cancelled: " << path;
#endif
            cancel();
        },
        "", nullptr, "", nullptr, nullptr, true));
}
#endif

int ThemeRepositoryFuse::deviceApi()
{
#if defined(__ANDROID__)
    return android_get_device_api_level();
#else
    return 0;
#endif
}
#endif
