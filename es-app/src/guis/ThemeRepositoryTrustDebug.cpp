//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ThemeRepositoryTrustDebug.cpp
//  Written for ES-DE-Plus. Original Git/XML/JSON fixtures; public libgit2 APIs only.
//  These app-context controls and fault/barrier hooks are absent from release builds.

#include "ThemeRepositoryTrustDebug.h"

#if !defined(NDEBUG) && (defined(__ANDROID__) || defined(THEME_TRUST_TEST))
#include "ThemeRepositoryFuse.h"
#include "ThemeRepositoryTrust.h"
#include "rapidjson/stringbuffer.h"
#include "rapidjson/writer.h"

#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>

namespace ThemeRepositoryTrust::Testing
{
    Fault fault {Fault::NONE};
    bool retireEnabled {true};
    std::function<void(const std::string&, const std::string&)> barrier;
} // namespace ThemeRepositoryTrust::Testing

namespace
{
    namespace fs = std::filesystem;
    using Repository = std::unique_ptr<git_repository, decltype(&git_repository_free)>;
    using Remote = std::unique_ptr<git_remote, decltype(&git_remote_free)>;
    std::ostringstream evidence;
    bool running {false};
    std::string controlDirectory;
    int fetches {0};
    struct CloneTrace {
        std::string initialized;
        std::string remote;
        std::string completed;
        std::string config;
        std::vector<std::pair<std::string, std::string>> checkpoints;
    };
    std::map<std::string, CloneTrace> cloneTraces;

    void require(bool condition, const std::string& message)
    {
        if (!condition)
            throw std::runtime_error(message);
    }

    void git(int code, const std::string& operation)
    {
        const git_error* error {git_error_last()};
        require(code == 0, operation + ": " + std::to_string(code) + " " +
                               (error && error->message ? error->message : ""));
    }

    void write(const std::string& path, const std::string& contents)
    {
        std::ofstream stream(path, std::ios::binary | std::ios::trunc);
        stream << contents;
        stream.close();
        require(!stream.fail(), "write fixture " + path);
    }

    std::string read(const std::string& path)
    {
        struct stat info {
        };
        if (lstat(path.c_str(), &info) != 0 || !S_ISREG(info.st_mode))
            return ""; // Injections deliberately leave directories, links and FIFOs.
        std::ifstream stream(path, std::ios::binary);
        return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
    }

    std::string configState(const std::string& repository)
    {
        const std::string path {repository + "/.git/config"};
        struct stat info {
        };
        std::ostringstream state;
        if (stat(path.c_str(), &info) == 0) {
            state << "uid=" << info.st_uid << " inode=" << info.st_ino << " size=" << info.st_size
                  << '\n';
#if defined(__APPLE__)
            state << "mtime=" << info.st_mtimespec.tv_sec << '.' << info.st_mtimespec.tv_nsec
                  << " ctime=" << info.st_ctimespec.tv_sec << '.' << info.st_ctimespec.tv_nsec;
#else
            state << "mtime=" << info.st_mtim.tv_sec << '.' << info.st_mtim.tv_nsec
                  << " ctime=" << info.st_ctim.tv_sec << '.' << info.st_ctim.tv_nsec;
#endif
            state << " device=" << info.st_dev << " mode=" << std::oct << info.st_mode << std::dec
                  << '\n';
        }
        else
            state << "stat errno=" << errno << '\n';
        state << read(path);
        return state.str();
    }

    std::string temporary(const std::string& parent)
    {
        std::string pattern {parent + "/theme-trust.XXXXXX"};
        require(mkdtemp(pattern.data()) != nullptr, "create isolated app-context fixture root");
        return pattern;
    }

    uint64_t fingerprint(const std::string& root, const std::string& observedRepository = "")
    {
        std::string observed {observedRepository.empty() ? "" : configState(observedRepository)};
        auto observe = [&](const std::string& stage) {
            if (observedRepository.empty())
                return;
            const std::string current {configState(observedRepository)};
            if (current != observed) {
                cloneTraces.at(observedRepository).checkpoints.emplace_back(stage, current);
                evidence << "CONFIG CHANGED DURING " << stage << '\n' << current;
                observed = current;
            }
        };
        uint64_t hash {14695981039346656037ULL};
        std::set<std::string> paths;
        for (const auto& item : fs::recursive_directory_iterator(root))
            paths.insert(item.path().string());
        observe("TREE HASH AFTER DIRECTORY ENUMERATION");
        for (const auto& path : paths) {
            const std::string content {fs::is_regular_file(path) ? read(path) : "<directory>"};
            observe("TREE HASH AFTER READING " + path);
            for (unsigned char c : path.substr(root.size()) + content) {
                hash ^= c;
                hash *= 1099511628211ULL;
            }
        }
        return hash;
    }

    Repository open(const std::string& path)
    {
        git_repository* repository {nullptr};
        git(git_repository_open(&repository, path.c_str()), "open positive control " + path);
        return {repository, git_repository_free};
    }

    void setting(git_repository* repository, const char* key, const std::string* value)
    {
        git_config* config {nullptr};
        git(git_repository_config(&config, repository), "open fixture config");
        const int result {value ? git_config_set_string(config, key, value->c_str()) :
                                  git_config_delete_entry(config, key)};
        git_config_free(config);
        git(result, "change fixture config");
    }

    std::string head(git_repository* repository)
    {
        git_reference* reference {nullptr};
        git(git_repository_head(&reference, repository), "read HEAD");
        char hex[GIT_OID_HEXSZ + 1];
        git_oid_tostr(hex, sizeof(hex), git_reference_target(reference));
        git_reference_free(reference);
        return hex;
    }

    void commit(git_repository* repository, const std::string& root, const std::string& value)
    {
        write(root + "/theme.xml", "<theme><!-- ES-DE-Plus authored fixture " + value +
                                       " --><view name=\"system\"/></theme>\n");
        git_index* index {nullptr};
        git_tree* tree {nullptr};
        git_signature* signature {nullptr};
        git_oid treeId;
        git_oid commitId;
        git(git_repository_index(&index, repository), "fixture index");
        git(git_index_add_bypath(index, "theme.xml"), "fixture index add");
        git(git_index_write_tree(&treeId, index), "fixture tree");
        git(git_index_write(index), "fixture index write");
        git(git_tree_lookup(&tree, repository, &treeId), "fixture tree lookup");
        git(git_signature_new(&signature, "ES-DE-Plus test", "fixture@example.invalid", 1700000000,
                              0),
            "fixture author");
        git_reference* reference {nullptr};
        git_commit* parent {nullptr};
        if (git_repository_head(&reference, repository) == 0)
            git(git_commit_lookup(&parent, repository, git_reference_target(reference)),
                "fixture parent");
        git(git_commit_create_v(&commitId, repository, "HEAD", signature, signature, nullptr,
                                value.c_str(), tree, parent ? 1 : 0, parent),
            "fixture commit");
        git_commit_free(parent);
        git_reference_free(reference);
        git_signature_free(signature);
        git_tree_free(tree);
        git_index_free(index);
    }

    rapidjson::Document document(const std::string& url)
    {
        rapidjson::Document doc;
        doc.SetObject();
        auto& allocator = doc.GetAllocator();
        rapidjson::Value entries(rapidjson::kArrayType);
        for (const char* name : {"original", "second", "pending"}) {
            rapidjson::Value entry(rapidjson::kObjectType);
            entry.AddMember("reponame", rapidjson::Value(name, allocator), allocator);
            entry.AddMember("url", rapidjson::Value(url.c_str(), allocator), allocator);
            entries.PushBack(entry, allocator);
        }
        doc.AddMember("themes", entries, allocator);
        return doc;
    }

    int clone(const std::string& url, const std::string& path)
    {
        git_clone_options options {};
        git(git_clone_options_init(&options, GIT_CLONE_OPTIONS_VERSION), "clone options");
        CloneTrace trace;
        options.repository_cb = [](git_repository** out, const char* path, int bare,
                                   void* payload) {
            const int result {ThemeRepositoryTrust::create(out, path, bare, nullptr)};
            static_cast<CloneTrace*>(payload)->initialized = configState(path);
            return result;
        };
        options.repository_cb_payload = &trace;
        options.remote_cb = [](git_remote** out, git_repository* repository, const char* name,
                               const char* url, void* payload) {
            const int result {
                ThemeRepositoryTrust::createRemote(out, repository, name, url, nullptr)};
            static_cast<CloneTrace*>(payload)->remote =
                configState(git_repository_workdir(repository));
            return result;
        };
        options.remote_cb_payload = &trace;
        options.local = GIT_CLONE_NO_LOCAL;
        git_repository* repository {nullptr};
        int result {git_clone(&repository, url.c_str(), path.c_str(), &options)};
        if (result == 0 && !ThemeRepositoryTrust::cloneComplete(path))
            result = -1;
        if (result != 0)
            ThemeRepositoryTrust::diagnoseCloneFailure(path, result);
        trace.config = read(path + "/.git/config");
        trace.completed = configState(path);
        git_repository_free(repository);
        trace.checkpoints.emplace_back("AFTER CLONE HANDLE FREE", configState(path));
        cloneTraces[path] = std::move(trace);
        return result;
    }

    void checkpoint(const std::string& path, const std::string& stage)
    {
        cloneTraces.at(path).checkpoints.emplace_back(stage, configState(path));
    }

    void traceClone(const std::string& path)
    {
        const auto& trace = cloneTraces.at(path);
        evidence << "AFTER INITIALIZATION\n"
                 << trace.initialized << "AFTER REMOTE CREATION\n"
                 << trace.remote << "AFTER CLONE\n"
                 << trace.completed;
        for (const auto& point : trace.checkpoints)
            evidence << point.first << '\n' << point.second;
        evidence << "CURRENT CONFIG\n" << configState(path) << "END CLONE TRACE\n";
    }

    bool fetch(const std::string& path)
    {
        auto repository = open(path);
        if (!ThemeRepositoryTrust::verify(repository.get(), path))
            return false;
        git_remote* raw {nullptr};
        const int lookup {git_remote_lookup(&raw, repository.get(), "origin")};
        if (lookup != 0) {
            const git_error* error {git_error_last()};
            evidence << "FETCH remote lookup=" << lookup << " path=" << path
                     << " error=" << (error && error->message ? error->message : "<none>") << '\n'
                     << "FIXTURE CONFIG BEGIN\n"
                     << read(path + "/.git/config") << "FIXTURE CONFIG END\n";
            return false;
        }
        Remote remote(raw, git_remote_free);
        if (!ThemeRepositoryTrust::remote(remote.get(), path))
            return false;
        ++fetches;
        git(git_remote_fetch(remote.get(), nullptr, nullptr, nullptr), "positive actual fetch");
        return true;
    }

    void positive(const std::string& path)
    {
        auto repository = open(path);
        require(ThemeRepositoryTrust::verify(repository.get(), path), "identity positive control");
    }

    void deniedIdentity(const std::string& path, bool requireOpen = false)
    {
        git_repository* repository {nullptr};
        const int result {git_repository_open(&repository, path.c_str())};
        require(!requireOpen || result == 0,
                "ownership-positive identity negative control must open");
        require(result != 0 || !ThemeRepositoryTrust::verify(repository, path),
                "identity attack admitted");
        git_repository_free(repository);
        evidence << " raw-open=" << result;
    }

    void measurements(const std::string& data, const std::string& themes)
    {
        evidence << "APP CONTEXT euid=" << geteuid() << " storage=" << themes << '\n';
        for (const std::string& path : {data, themes, themes + "/themes-list/.git"}) {
            struct stat info {
            };
            require(stat(path.c_str(), &info) == 0, "app-context stat " + path);
            evidence << "STAT " << path << " uid=" << info.st_uid << " gid=" << info.st_gid
                     << " mode=" << std::oct << info.st_mode << std::dec << '\n';
        }
    }

    void retireBoundaries(const std::string& themes,
                          const std::string& privateRoot,
                          const std::string& url,
                          bool shared)
    {
        using namespace ThemeRepositoryTrust;
        const std::string path {themes + "/pending"};
        const std::string marker {privateRoot + "/retirement-canary"};
        write(marker, "ES-DE-Plus retirement canary");
        const std::string protectedConfig {read(privateRoot + "/libgit2/.gitconfig")};
        auto clear = [&] {
            Testing::barrier = {};
            Testing::fault = Testing::Fault::NONE;
            fs::remove_all(path);
            fs::remove_all(path + "-moved");
        };
        for (const std::string kind :
             {"file", "symlink", "directory", "fifo", "replace-temp", "modify-temp",
              "destination-file", "destination-symlink", "destination-directory", "gitdir-parent",
              "workdir-parent", "gitdir-replacement", "workdir-replacement", "installed-config"}) {
            clear();
            bool reached {false};
            bool unsupported {false};
            bool initialized {false};
            Testing::barrier = [&](const std::string& stage, const std::string& candidate) {
                const std::string temp {candidate + "/.git/" + ThemeRepositoryFuse::temporaryName};
                std::error_code error;
                if (stage == "clone-after-init") {
                    initialized = fs::is_regular_file(candidate + "/.git/config");
                    evidence << "RETIREMENT " << kind << " INITIALIZATION config=" << initialized
                             << "; temp=" << fs::exists(temp) << '\n';
                }
                if (stage == "clone-retirement-finished")
                    evidence << "RETIREMENT " << kind
                             << " AFTER R1 (before libgit2 cleanup) config="
                             << fs::exists(candidate + "/.git/config")
                             << "; temp=" << fs::exists(temp) << '\n';
                const bool occupied {kind == "file" || kind == "symlink" || kind == "directory" ||
                                     kind == "fifo"};
                if (occupied && stage == "clone-retire-before-create") {
                    reached = true;
                    if (kind == "file")
                        write(temp, "occupied");
                    else if (kind == "directory")
                        fs::create_directory(temp);
                    else if (kind == "symlink")
                        fs::create_symlink(marker, temp, error);
                    else if (mkfifo(temp.c_str(), 0600) != 0)
                        error = std::error_code(errno, std::generic_category());
                }
                if (stage == "clone-retire-written") {
                    if (kind == "replace-temp") {
                        reached = true;
                        const std::string contents {read(temp)};
                        fs::rename(temp, temp + ".held");
                        write(temp, contents); // Same meaning, different entry.
                    }
                    if (kind == "modify-temp") {
                        reached = true;
                        write(temp, "[core]\n bare=true\n");
                    }
                    if (kind == "gitdir-parent" || kind == "gitdir-replacement") {
                        reached = true;
                        fs::rename(candidate + "/.git", candidate + "/.git-moved");
                        if (kind == "gitdir-parent")
                            fs::create_directory_symlink(privateRoot, candidate + "/.git", error);
                        else
                            fs::create_directory(candidate + "/.git");
                    }
                    if (kind == "workdir-parent" || kind == "workdir-replacement") {
                        reached = true;
                        fs::rename(candidate, candidate + "-moved");
                        if (kind == "workdir-parent")
                            fs::create_directory_symlink(privateRoot, candidate, error);
                        else
                            fs::create_directory(candidate);
                    }
                }
                if (stage == "clone-retire-unlinked" && kind.compare(0, 12, "destination-") == 0) {
                    reached = true;
                    if (kind == "destination-file")
                        write(candidate + "/.git/config", "planted");
                    else if (kind == "destination-symlink")
                        fs::create_symlink(marker, candidate + "/.git/config", error);
                    else
                        fs::create_directory(candidate + "/.git/config");
                }
                if (stage == "clone-retire-renamed" && kind == "installed-config") {
                    reached = true;
                    write(candidate + "/.git/config", "[core]\n bare=true\n");
                }
                if (error) {
                    require(error == std::errc::operation_not_permitted ||
                                error == std::errc::operation_not_supported ||
                                error == std::errc::permission_denied,
                            "unexpected fixture object creation failure: " + error.message());
                    unsupported = true;
                    evidence << "CAPABILITY: retirement " << kind << " not representable on "
                             << themes << "; " << error.message() << '\n';
                }
            };
            const int result {clone(url, path)};
            require(reached && initialized, "retirement barrier and initialization fired");
            require(!unsupported || shared, "private filesystem must exercise every object type");
            require(unsupported || result != 0, "retirement injection refused: " + kind);
            require(read(marker) == "ES-DE-Plus retirement canary" &&
                        read(privateRoot + "/libgit2/.gitconfig") == protectedConfig,
                    "retirement preserves private canary and trust config");
            if (kind == "file")
                require(read(path + "/.git/" + ThemeRepositoryFuse::temporaryName) == "occupied",
                        "occupied temporary file not truncated or cleaned");
            if (kind == "destination-file")
                require(read(path + "/.git/config") == "planted", "planted destination unchanged");
            evidence << "RETIREMENT " << kind << ": init=target metadata only; result=" << result
                     << "; object-unavailable=" << unsupported
                     << "; AFTER LIBGIT2 CLEANUP config=" << fs::exists(path + "/.git/config")
                     << "; temp="
                     << fs::exists(path + "/.git/" + ThemeRepositoryFuse::temporaryName)
                     << "; checkout-present=" << fs::exists(path + "/theme.xml")
                     << "; protected data unchanged\n";
            clear();
            git(clone(url, path), "retirement restored actual clone positive control");
            positive(path);
        }
        clear();
        for (Testing::Fault injected : {Testing::Fault::RETIRE_WRITE, Testing::Fault::RETIRE_RENAME,
                                        Testing::Fault::RETIRE_CLEANUP}) {
            clear();
            Testing::fault = injected;
            require(clone(url, path) != 0,
                    "retirement write/rename/cleanup failure refused through actual clone");
            const bool leftover {fs::exists(path + "/.git/" + ThemeRepositoryFuse::temporaryName)};
            require(leftover == (injected == Testing::Fault::RETIRE_CLEANUP),
                    "retirement cleanup and failed-cleanup states measured");
            require(fs::exists(path + "/.git/config") == (injected == Testing::Fault::RETIRE_WRITE),
                    "write failure precedes unlink; rename failures follow unlink");
            require(read(marker) == "ES-DE-Plus retirement canary" &&
                        read(privateRoot + "/libgit2/.gitconfig") == protectedConfig,
                    "retirement failure preserves protected data");
            evidence << "RETIREMENT failure=" << static_cast<int>(injected)
                     << "; init=target metadata; cleanup-leftover=" << leftover
                     << "; remote/fetch/checkout=none; protected data unchanged\n";
            clear();
            git(clone(url, path), "retirement failure restored clone positive control");
        }
        clear();
        for (bool packed : {false, true}) {
            git(clone(url, path), "missing-origin fixture actual clone");
            {
                auto repository = open(path);
                if (packed) {
                    git_refdb* database {nullptr};
                    git(git_repository_refdb(&database, repository.get()), "classifier refdb");
                    git(git_refdb_compress(database), "classifier packed origin refs");
                    git_refdb_free(database);
                }
                setting(repository.get(), "remote.origin.url", nullptr);
                setting(repository.get(), "remote.origin.fetch", nullptr);
            }
            const uint64_t before {fingerprint(path)};
            {
                auto repository = open(path);
                git_remote* origin {nullptr};
                const int lookup {git_remote_lookup(&origin, repository.get(), "origin")};
                git_remote_free(origin);
                require(lookup == GIT_ENOTFOUND, "exact missing-origin fixture");
                const git_error* missing {git_error_last()};
                evidence << "CLASSIFIER lookup-class=" << (missing ? missing->klass : -1) << '\n';
                require(!corrupt(lookup, path), "missing origin is never general corrupt recovery");
                const int api {ThemeRepositoryFuse::deviceApi()};
                const bool applicable {api == 31 || api == 32};
                require(ThemeRepositoryFuse::missingOrigin(repository.get(), path, lookup) ==
                            applicable,
                        "actual platform classifier; no Android 12 class on TV");
                if (applicable)
                    require(!corrupt(lookup, path),
                            "classifier retains the non-corrupt error class");
                require(ThemeRepositoryFuse::originReferences(repository.get()),
                        "classifier retained origin refs positive control");
                require(!ThemeRepositoryFuse::recheckListRecovery(path),
                        "theme classification never authorizes list recovery");
                evidence << "CLASSIFIER api=" << api << "; packed=" << packed
                         << "; missing-origin=" << applicable << "; corrupt=0; no mutation\n";
            }
            require(fingerprint(path) == before, "classifier never mutates or deletes the theme");
            clear();
            git(clone(url, path), "classifier restored clone positive control");
            require(fetch(path), "classifier restored fetch positive control");
            clear();
        }
        evidence << "PASS: retirement boundaries and write/rename/cleanup controls; each restored "
                    "clone passed\n"
                 << "RESIDUAL: deterministic entry/content/parent checks block the observed "
                    "injections before later clone operations. Shared writers can still replace "
                    "entries or change contents after a check. No race-freedom, content freshness "
                    "or successful cache retirement follows from destination replacement.\n";
    }

    void suite(const std::string& data,
               const std::string& privateRoot,
               const std::string& source,
               bool shared)
    {
        using namespace ThemeRepositoryTrust;
        const std::string themes {data + "/themes"};
        const std::string original {themes + "/original"};
        const std::string url {"file://" + source};
        fs::create_directories(privateRoot);
        const auto doc = document(url);
        auto prepare = [&] {
            configure(themes, privateRoot);
            require(ready() && expectList(url) && admit(doc), "configure/admit positive control");
        };
        prepare();

        // Parse the actual protected file through libgit2, independently of
        // app-owned repositories passing ownership without an exception.
        git_config* protectedConfig {nullptr};
        git(git_config_open_ondisk(&protectedConfig, (privateRoot + "/libgit2/.gitconfig").c_str()),
            "read actual protected allowlist");
        std::vector<std::string> parsed;
        const int parsedResult {git_config_get_multivar_foreach(
            protectedConfig, "safe.directory", nullptr,
            [](const git_config_entry* entry, void* payload) {
                static_cast<std::vector<std::string>*>(payload)->emplace_back(entry->value);
                return 0;
            },
            &parsed)};
        git_config_free(protectedConfig);
        git(parsedResult, "parse actual safe.directory entries");
        const std::string canonicalThemes {fs::canonical(themes).string()};
        const std::set<std::string> expected {
            canonicalThemes + "/themes-list", canonicalThemes + "/original",
            canonicalThemes + "/second", canonicalThemes + "/pending"};
        require(parsed.size() == expected.size() &&
                    std::set<std::string>(parsed.begin(), parsed.end()) == expected,
                "actual allowlist preserves exact path bytes");

        git(clone(url, themes + "/themes-list"), "themes-list clone callback positive control");
        git(clone(url, original), "theme clone callback positive control");
        git(clone(url, themes + "/second"), "second admitted clone positive control");
        checkpoint(original, "AFTER SECOND REPOSITORY CLONE");
        positive(original);
        checkpoint(original, "AFTER INITIAL IDENTITY OPEN");
        measurements(data, themes);
        // Removing the protected allowlist proves the underlying ownership check still runs.
        fs::create_directory(privateRoot + "/empty");
        git(git_libgit2_opts(GIT_OPT_SET_SEARCH_PATH, GIT_CONFIG_LEVEL_GLOBAL,
                             (privateRoot + "/empty").c_str()),
            "raw owner control config");
        git_repository* raw {nullptr};
        const int ownerCode {git_repository_open(&raw, original.c_str())};
        git_repository_free(raw);
        checkpoint(original, "AFTER RAW OWNERSHIP OPEN/FREE");
        require(shared ? ownerCode == GIT_EOWNER : ownerCode == 0,
                "owner validation positive control");
        evidence << "PASS: raw owner control shared=" << shared << " code=" << ownerCode << '\n';
        prepare();
        checkpoint(original, "AFTER RAW CONTROL CONFIGURE/ADMIT");

        {
            auto hostile = document(url);
            const std::vector<std::string> names {
                "../escape",    std::string("original\0escape", 15),
                "control\x1f",  "THEMES-LIST",
                "duplicate",    "DUPLICATE",
                "foo",          "foo-main",
                "foo-master",   "foo_1",
                "foo_DISABLED", std::string(256, 'a')};
            for (const auto& name : names) {
                rapidjson::Value entry(rapidjson::kObjectType);
                auto& allocator = hostile.GetAllocator();
                entry.AddMember("reponame", rapidjson::Value(name.data(), name.size(), allocator),
                                allocator);
                entry.AddMember("url", rapidjson::Value(url.c_str(), allocator), allocator);
                hostile["themes"].PushBack(entry, allocator);
            }
            rapidjson::StringBuffer bytes;
            rapidjson::Writer<rapidjson::StringBuffer> writer(bytes);
            hostile.Accept(writer);
            rapidjson::Document parsed;
            parsed.Parse(bytes.GetString(), bytes.GetSize());
            require(!parsed.HasParseError(), "hostile fixture real JSON parse positive control");
            checkpoint(original, "BEFORE HOSTILE JSON TREE HASH");
            const uint64_t before {fingerprint(themes, original)};
            checkpoint(original, "AFTER HOSTILE JSON TREE HASH");
            Testing::barrier = [&](const std::string& stage, const std::string&) {
                if (stage.compare(0, 10, "admission-") == 0)
                    checkpoint(original, stage);
            };
            require(admit(parsed), "hostile list admits its unambiguous original entries");
            Testing::barrier = {};
            checkpoint(original, "AFTER HOSTILE JSON ADMISSION");
            for (rapidjson::SizeType i {0}; i < parsed["themes"].Size(); ++i) {
                require(admitted(parsed["themes"][i]) == (i < 3),
                        "full JSON admission before string conversion");
                if (i >= 3) {
                    const auto& value = parsed["themes"][i]["reponame"];
                    const std::string path {
                        themes + "/" + std::string(value.GetString(), value.GetStringLength())};
                    require(!permit(path), "invalid JSON name blocked at filesystem boundary");
                    git_repository* unexpected {nullptr};
                    require(create(&unexpected, path.c_str(), 0, nullptr) != 0 && !unexpected,
                            "invalid JSON name clone boundary rejected");
                }
            }
            require(fingerprint(themes) == before,
                    "hostile JSON preserves reserved and other repositories");
            checkpoint(original, "AFTER HOSTILE JSON FILESYSTEM CONTROLS");
            positive(original);
            checkpoint(original, "AFTER HOSTILE JSON IDENTITY OPEN");
            prepare();
            checkpoint(original, "AFTER HOSTILE JSON RESTORE CONFIGURE/ADMIT");
            evidence << "PASS: real JSON full strings; invalid, duplicate, case, manual/recovery "
                        "aliases "
                        "and overlength names blocked at filesystem boundaries; reserved/other "
                        "themes unchanged\n";
        }
        // Reproduce the API 31 metadata-persistence failure without retries:
        // every clone, rewind, fetch and forward reset must independently pass.
        for (int cycle {0}; cycle < 16; ++cycle) {
            if (cycle != 0) {
                fs::remove_all(original);
                prepare();
                git(clone(url, original), "repeated clone positive control");
            }
            // The diagnostic observer itself performs extra reads. Independently
            // require ordinary tree traversal to preserve each fresh clone's
            // metadata before any observer/open/reset can refresh its view.
            fingerprint(original);
            if (read(original + "/.git/config") != cloneTraces.at(original).config) {
                evidence << "METADATA path=" << original << '\n';
                traceClone(original);
                require(false, "T-4 config changed after unobserved read-only tree traversal");
            }
            std::string latest;
            {
                checkpoint(original, "BEFORE REWIND OPEN");
                auto repository = open(original);
                checkpoint(original, "AFTER REWIND OPEN");
                latest = head(repository.get());
                git_object* previous {nullptr};
                git(git_revparse_single(&previous, repository.get(), "HEAD~1"),
                    "previous fixture commit");
                checkpoint(original, "BEFORE HARD RESET");
                git(git_reset(repository.get(), previous, GIT_RESET_HARD, nullptr),
                    "set one commit behind");
                checkpoint(original, "AFTER HARD RESET");
                git_object_free(previous);
                evidence << "UPDATE cycle=" << cycle << " before=" << head(repository.get())
                         << " expected=" << latest << '\n';
            }
            checkpoint(original, "AFTER REWIND HANDLE FREE");
            if (!fetch(original)) {
                traceClone(original);
                require(false,
                        "actual update fetch positive control cycle=" + std::to_string(cycle));
            }
            {
                auto repository = open(original);
                git_reference* reference {nullptr};
                git(git_repository_head(&reference, repository.get()), "fixture branch name");
                const std::string branch {git_reference_shorthand(reference)};
                git_reference_free(reference);
                git_object* target {nullptr};
                git(git_revparse_single(&target, repository.get(), ("origin/" + branch).c_str()),
                    "fetched target");
                require(verify(repository.get(), original), "update reset identity");
                git(git_reset(repository.get(), target, GIT_RESET_HARD, nullptr),
                    "forward update reset");
                git_object_free(target);
                require(head(repository.get()) == latest, "update reaches original HEAD");
                evidence << "PASS: update after=" << head(repository.get()) << '\n';
            }
        }
        evidence << "PASS: 16 mandatory clone/rewind/fetch/reset cycles; no retries\n";
        evidence << "PASS: config bytes survive unobserved tree traversal in all 16 cycles\n";
        const std::string canonicalData {fs::canonical(data).string()};
        if (!shared && canonicalData.find('"') != std::string::npos &&
            canonicalData.find('\\') != std::string::npos)
            evidence << "PASS: actual quoted/backslash private Git paths; protected allowlist "
                        "parsed exactly; clone/fetch/reset succeeded; canonical path="
                     << canonicalData << '\n';

        const std::string canary {privateRoot + "/canary"};
        fs::copy(source, canary, fs::copy_options::recursive);
        const uint64_t canaryBefore {fingerprint(canary)};
        {
            const std::string original {themes + "/themes-list"};
            // Unguarded positive controls write only original, disposable fixtures.
            for (const std::string attack : {"worktree", "gitlink", "commondir"}) {
                // Ownership exceptions are keyed by the resolved workdir. An
                // outside/private workdir correctly fails ownership on FUSE;
                // another admitted workdir reaches the independent identity gate.
                const std::string target {attack == "worktree" ?
                                              themes + "/second" :
                                              privateRoot + "/unguarded-" + attack};
                if (attack != "worktree")
                    fs::copy(source, target, fs::copy_options::recursive);
                if (attack == "worktree") {
                    write(target + "/theme.xml", "ES-DE-Plus redirect write positive control");
                    auto repository = open(original);
                    setting(repository.get(), "core.worktree", &target);
                }
                else if (attack == "gitlink") {
                    fs::rename(original + "/.git", original + "/saved-git");
                    write(original + "/.git", "gitdir: " + target + "/.git\n");
                }
                else
                    write(original + "/.git/commondir", target + "/.git\n");
                const uint64_t before {fingerprint(target)};
                {
                    auto repository = open(original);
                    require(!verify(repository.get(), original),
                            "guard rejects the writable redirect");
                    if (attack == "worktree") {
                        git_object* object {nullptr};
                        git(git_revparse_single(&object, repository.get(), "HEAD"),
                            "unguarded positive HEAD");
                        git(git_reset(repository.get(), object, GIT_RESET_HARD, nullptr),
                            "unguarded positive reset");
                        git_object_free(object);
                    }
                    else {
                        git_index* index {nullptr};
                        git(git_repository_index(&index, repository.get()),
                            "unguarded positive index");
                        git_index_entry entry {};
                        entry.mode = GIT_FILEMODE_BLOB;
                        entry.path = "ES-DE-Plus-positive.txt";
                        const std::string contents {
                            "ES-DE-Plus original redirect positive control " + attack};
                        git(git_index_add_from_buffer(index, &entry, contents.data(),
                                                      contents.size()),
                            "unguarded positive object write");
                        git(git_index_write(index), "unguarded positive index write");
                        git_index_free(index);
                    }
                }
                require(fingerprint(target) != before,
                        "unguarded redirect mutates only its authored target");
                if (attack == "worktree") {
                    git_config* config {nullptr};
                    git(git_config_open_ondisk(&config, (original + "/.git/config").c_str()),
                        "positive restore config");
                    git(git_config_delete_entry(config, "core.worktree"),
                        "positive remove redirect");
                    git_config_free(config);
                }
                else if (attack == "gitlink") {
                    fs::remove(original + "/.git");
                    fs::rename(original + "/saved-git", original + "/.git");
                }
                else
                    fs::remove(original + "/.git/commondir");
                {
                    auto repository = open(original);
                    git_object* object {nullptr};
                    git(git_revparse_single(&object, repository.get(), "HEAD"),
                        "restored fixture HEAD");
                    git(git_reset(repository.get(), object, GIT_RESET_HARD, nullptr),
                        "restore fixture index");
                    git_object_free(object);
                }
                positive(original);
                evidence << "PASS: unguarded " << attack
                         << " positive control changed only its authored "
                         << (attack == "worktree" ? "admitted" : "private") << " target\n";
            }
            const uint64_t secondBefore {fingerprint(themes + "/second")};
            fs::create_directory(themes + "/unlisted");
            write(themes + "/unlisted/canary", "ES-DE-Plus untouched shared canary");
            const uint64_t unlistedBefore {fingerprint(themes + "/unlisted")};
            for (const std::string& target : {themes + "/unlisted", themes + "/second", canary}) {
                positive(original);
                {
                    auto repository = open(original);
                    setting(repository.get(), "core.worktree", &target);
                }
                evidence << "WORKTREE target=" << target;
                deniedIdentity(original, target == themes + "/second");
                evidence << '\n';
                // Restore without opening the redirected repository.
                const std::string config {original + "/.git/config"};
                git_config* rawConfig {nullptr};
                git(git_config_open_ondisk(&rawConfig, config.c_str()), "fixture config restore");
                git(git_config_delete_entry(rawConfig, "core.worktree"),
                    "remove worktree redirection");
                git_config_free(rawConfig);
                positive(original);
            }
            require(fingerprint(canary) == canaryBefore &&
                        fingerprint(themes + "/second") == secondBefore &&
                        fingerprint(themes + "/unlisted") == unlistedBefore,
                    "worktree canaries unchanged");
            evidence
                << "PASS: worktree outside, private and admitted targets unchanged; each restored "
                   "positive passed\n";

            fs::rename(original + "/.git", original + "/saved-git");
            write(original + "/.git", "gitdir: " + canary + "/.git\n");
            deniedIdentity(original);
            fs::remove(original + "/.git");
            fs::rename(original + "/saved-git", original + "/.git");
            positive(original);
            write(original + "/.git/commondir", canary + "/.git\n");
            deniedIdentity(original);
            fs::remove(original + "/.git/commondir");
            positive(original);
            require(fingerprint(canary) == canaryBefore, "gitlink/commondir canary unchanged");
            evidence
                << "\nPASS: gitlink and commondir blocked; restored identity positive controls "
                   "passed\n";

            fs::rename(original, themes + "/baseline");
            fs::create_directory(original);
            deniedIdentity(original);
            fs::remove(original);
            git_repository* bare {nullptr};
            git(git_repository_init(&bare, original.c_str(), 1), "create bare fixture");
            git_repository_free(bare);
            deniedIdentity(original);
            fs::remove_all(original);
            {
                auto repository = open(canary);
                git_worktree* worktree {nullptr};
                git(git_worktree_add(&worktree, repository.get(), "linked", original.c_str(),
                                     nullptr),
                    "linked fixture");
                git_worktree_free(worktree);
            }
            deniedIdentity(original);
            fs::remove_all(original);
            fs::rename(themes + "/baseline", original);
            positive(original);
            // The linked-worktree fixture deliberately added administrative metadata to its source.
            fs::remove_all(canary + "/.git/worktrees");
            fs::remove(canary + "/.git/refs/heads/linked");
            fs::remove(canary + "/.git/logs/refs/heads/linked");
            require(fingerprint(canary) == canaryBefore,
                    "worktree fixture cleanup restores source");
            evidence << "\nPASS: non-repository, bare and linked worktree rejected; ordinary clone "
                        "positive passed\n";
        }
        for (const std::string& path : {themes + "/themes-list", original}) {
            for (const std::string attack :
                 {"missing", "empty", "changed", "insteadOf", "between-precheck-fetch"}) {
                require(fetch(path), "actual remote fetch positive control before " + attack);
                const int count {fetches};
                {
                    auto repository = open(path);
                    const std::string bad {"http://127.0.0.1:9/ESDEPlus-substitute"};
                    const std::string empty;
                    if (attack == "missing")
                        setting(repository.get(), "remote.origin.url", nullptr);
                    else if (attack == "empty")
                        setting(repository.get(), "remote.origin.url", &empty);
                    else if (attack == "insteadOf")
                        setting(repository.get(),
                                "url.http://127.0.0.1:9/ESDEPlus-substitute.insteadOf", &url);
                    else
                        setting(repository.get(), "remote.origin.url", &bad);
                }
                // Reopen and look up the actual worker remote after the precheck above.
                require(!fetch(path) && fetches == count,
                        "substituted fetch never entered transport");
                {
                    auto repository = open(path);
                    if (attack == "insteadOf")
                        setting(repository.get(),
                                "url.http://127.0.0.1:9/ESDEPlus-substitute.insteadOf", nullptr);
                    else
                        setting(repository.get(), "remote.origin.url", &url);
                }
                require(fetch(path), "restored actual fetch positive control");
                evidence << "PASS: remote " << path << " " << attack
                         << "; substituted transport calls=0\n";
            }
        }

        for (const std::string& path : {themes + "/themes-list", original}) {
            require(fetch(path), "worker-race actual fetch positive control");
            const int count {fetches};
            write(privateRoot + "/theme-trust.remote-race",
                  fs::path(path).filename().string() +
                      "\nhttp://127.0.0.1:9/ESDEPlus-substitute\n");
            bool denied {false};
            std::string error;
            std::thread worker([&] {
                try {
                    denied = !fetch(path);
                }
                catch (const std::exception& failure) {
                    error = failure.what();
                }
            });
            worker.join();
            require(error.empty() && denied && fetches == count,
                    "actual worker barrier rejects substituted remote before transport: " + error);
            require(read(privateRoot + "/theme-trust.remote-race-result")
                            .find("PASS: worker changed origin after precheck and before lookup") !=
                        std::string::npos,
                    "actual worker barrier positive control fired");
            {
                auto repository = open(path);
                setting(repository.get(), "remote.origin.url", &url);
            }
            require(fetch(path), "restored worker-race actual fetch positive control");
            evidence << "PASS: actual worker remote barrier " << path
                     << "; substituted transport calls=0; restored fetch passed\n";
        }

        // Failed setup cannot inherit readiness from an older config, even when raw opens pass.
        for (bool prior : {false, true}) {
            for (Testing::Fault injected :
                 {Testing::Fault::TEMPORARY, Testing::Fault::REPLACE, Testing::Fault::SEARCH}) {
                const std::string configuration {temporary(privateRoot)};
                if (prior) {
                    configure(themes, configuration);
                    require(expectList(url) && admit(doc), "prior allowlist positive control");
                }
                else {
                    git(git_libgit2_opts(GIT_OPT_SET_SEARCH_PATH, GIT_CONFIG_LEVEL_GLOBAL,
                                         (privateRoot + "/empty").c_str()),
                        "no-prior protected config");
                }
                const uint64_t before {fingerprint(themes)};
                Testing::fault = injected;
                configure(themes, configuration);
                require(!ready() && !permit(original) && !disabled(original + "_DISABLED"),
                        "failed prerequisite blocks inventory and cleanup");
                require(clone(url, themes + "/pending") != 0 && !fs::exists(themes + "/pending"),
                        "failed prerequisite clone callback has no writes or cleanup");
                if (prior) {
                    auto repository = open(original);
                    require(!verify(repository.get(), original),
                            "stale allowlist does not imply readiness");
                }
                require(fingerprint(themes) == before, "failed setup has no shared mutations");
                Testing::fault = Testing::Fault::NONE;
                configure(themes, configuration);
                require(ready() && expectList(url) && admit(doc), "restored config permits retry");
                positive(original);
                evidence << "PASS: fail-closed mode=" << (shared ? "direct" : "scoped")
                         << " prior=" << prior << " fault=" << static_cast<int>(injected)
                         << "; tree unchanged, retry passed\n";
            }
        }
        for (bool prior : {false, true}) {
            for (Testing::Fault injected : {Testing::Fault::TEMPORARY, Testing::Fault::REPLACE}) {
                configure(themes, privateRoot);
                require(expectList(url), "admission setup positive control");
                if (prior)
                    require(admit(doc), "prior full admission positive control");
                const uint64_t admissionBefore {fingerprint(themes)};
                Testing::fault = injected;
                require(!admit(doc) && !ready() && !permit(original),
                        "failed admission blocks operations");
                require(fingerprint(themes) == admissionBefore,
                        "admission failure has no mutations");
                Testing::fault = Testing::Fault::NONE;
                prepare();
                positive(original);
                evidence << "PASS: admission failure "
                         << (prior ? "with prior allowlist" : "without prior theme allowlist")
                         << "; fault=" << static_cast<int>(injected)
                         << "; tree unchanged; restored retry passed\n";
            }
        }
        for (Testing::Fault injected :
             {Testing::Fault::TEMPORARY, Testing::Fault::REPLACE, Testing::Fault::SEARCH}) {
            const std::string fresh {temporary(data)};
            Testing::fault = injected;
            configure(fresh + "/themes", privateRoot);
            require(!ready() && !fs::exists(fresh + "/themes"),
                    "failed private prerequisite never creates the data-side themes directory");
            Testing::fault = Testing::Fault::NONE;
            prepare();
            positive(original);
        }
        evidence << "PASS: fresh themes-directory bootstrap failures leave data untouched; "
                    "restored positive controls passed\n";
        const uint64_t storageBefore {fingerprint(themes)};
        fs::rename(data, data + ".unavailable");
        require(!ready() && !corrupt(GIT_ERROR, original),
                "missing storage is not corrupt-repository recovery");
        configure(themes, privateRoot);
        require(!ready() && !fs::exists(data), "missing data root is never recreated");
        fs::rename(data + ".unavailable", data);
        prepare();
        positive(original);
        require(fingerprint(themes) == storageBefore,
                "missing storage leaves repository tree unchanged");
        if (!shared) {
            require(chmod(original.c_str(), 0555) == 0, "read-only fixture setup");
            require(!permit(original) && !corrupt(GIT_ERROR, original),
                    "read-only data is not corrupt recovery");
            require(chmod(original.c_str(), 0755) == 0, "restore read-only fixture");
            positive(original);
        }
        evidence << "PASS: missing storage blocks operations without recreation/corrupt recovery; "
                    "restored positive passed\n";

        // Inject state exactly at the public creation callback's boundaries.
        const std::string pending {themes + "/pending"};
        for (const std::string stage :
             {"clone-before-init", "clone-after-init", "clone-before-remote"}) {
            const uint64_t before {fingerprint(canary)};
            Testing::barrier = [&](const std::string& reached, const std::string& path) {
                if (stage != reached)
                    return;
                if (stage == "clone-before-init") {
                    git_repository* foreign {nullptr};
                    git(git_repository_init(&foreign, path.c_str(), 0),
                        "inject existing repository");
                    git_repository_free(foreign);
                    write(path + "/.git/foreign-marker", "ES-DE-Plus unexpected metadata");
                }
                else
                    write(path + "/.git/commondir", canary + "/.git\n");
            };
            require(clone(url, pending) != 0, "clone boundary injection blocked");
            Testing::barrier = {};
            require(fingerprint(canary) == before, "clone boundary canary unchanged");
            require(stage == "clone-before-remote" ? !fs::exists(pending) :
                                                     fs::exists(pending + "/.git"),
                    "cleanup is limited to the newly created target after the remote callback");
            require(!fs::exists(pending + "/theme.xml"), "callback failure precedes checkout");
            if (stage == "clone-before-init")
                require(read(pending + "/.git/foreign-marker") == "ES-DE-Plus unexpected metadata",
                        "unexpected repository not reinitialized or cleaned");
            evidence << "PASS: clone boundary " << stage
                     << "; init=" << (stage == "clone-before-init" ? "none" : "target .git only")
                     << "; cleanup="
                     << (stage == "clone-before-remote" ? "new target removed" : "none")
                     << "; remote/fetch/checkout=none; canary unchanged\n";
            fs::remove_all(pending); // Explicitly dispose only this test's injected fixture.
            git(clone(url, pending), "clone boundary restored positive control");
            positive(pending);
            fs::remove_all(pending);
        }
        for (const std::string attack : {"reinit", "commondir"}) {
            const uint64_t before {fingerprint(canary)};
            auto snapshot = [&] {
                std::map<std::string, std::string> files;
                for (const auto& item : fs::recursive_directory_iterator(canary))
                    files[item.path().string()] =
                        item.is_regular_file() ? read(item.path().string()) : "<directory>";
                return files;
            };
            const auto beforeFiles {snapshot()};
            auto afterInitFiles {beforeFiles};
            uint64_t injected {0};
            uint64_t afterInitTarget {0};
            bool measuredInit {false};
            bool initialized {false};
            bool remoteReached {false};
            Testing::barrier = [&](const std::string& stage, const std::string& path) {
                if (stage == "clone-init-finished") {
                    afterInitFiles = snapshot();
                    afterInitTarget = fingerprint(path);
                    measuredInit = true;
                }
                if (stage == "clone-after-init")
                    initialized = true;
                if (stage == "clone-before-remote")
                    remoteReached = true;
                if (stage != "clone-after-precheck")
                    return;
                if (attack == "reinit") {
                    git_repository* foreign {nullptr};
                    git(git_repository_init(&foreign, path.c_str(), 0),
                        "inject repository after precheck");
                    git_repository_free(foreign);
                }
                else {
                    fs::create_directories(path + "/.git");
                    write(path + "/.git/commondir", canary + "/.git\n");
                }
                injected = fingerprint(path);
            };
            require(clone(url, pending) != 0,
                    "during-init redirection cannot reach remote/fetch/checkout");
            Testing::barrier = {};
            require(measuredInit, "initialization and failure cleanup measured separately");
            require(!remoteReached, "creation callback failure precedes the remote callback");
            require(!fs::exists(pending + "/theme.xml"), "during-init boundary precedes checkout");
            const auto afterCleanupFiles {snapshot()};
            const bool initPrivateChanged {afterInitFiles != beforeFiles};
            const bool cleanupPrivateChanged {afterCleanupFiles != afterInitFiles};
            if (attack == "reinit")
                require(fingerprint(pending) == injected && fingerprint(canary) == before &&
                            !initPrivateChanged && !cleanupPrivateChanged,
                        "NO_REINIT leaves injected repository and private canary unchanged");
            const bool privateChanged {initPrivateChanged || cleanupPrivateChanged};
            evidence << (privateChanged ? "RESIDUAL: " : "PASS: ") << "clone after-precheck "
                     << attack << "; callback refused before remote/fetch/checkout; "
                     << "init-returned-success=" << initialized
                     << "; injected-tree-changed=" << (fingerprint(pending) != injected)
                     << "; private-canary-changed=" << privateChanged
                     << "; init-target-changed=" << (afterInitTarget != injected)
                     << "; cleanup-target-changed=" << (fingerprint(pending) != afterInitTarget)
                     << "; init-private-changed=" << initPrivateChanged
                     << "; cleanup-private-changed=" << cleanupPrivateChanged << '\n';
            auto changes = [&](const std::string& phase, const auto& beforeFiles,
                               const auto& afterFiles) {
                for (const auto& entry : beforeFiles)
                    if (!afterFiles.count(entry.first))
                        evidence << phase << " PRIVATE DELETE " << entry.first.substr(canary.size())
                                 << '\n';
                for (const auto& entry : afterFiles) {
                    const auto old {beforeFiles.find(entry.first)};
                    if (old == beforeFiles.end() || old->second != entry.second)
                        evidence << phase << " PRIVATE WRITE " << entry.first.substr(canary.size())
                                 << '\n';
                }
            };
            changes("INIT", beforeFiles, afterInitFiles);
            changes("CLEANUP", afterInitFiles, afterCleanupFiles);
            if (privateChanged) {
                evidence << "RESIDUAL: "
                         << (initPrivateChanged ? "initialization" : "failure cleanup")
                         << " wrote through a commondir inserted after the precheck; "
                            "the post-init gate stopped later clone operations (D-012 am. 4).\n";
            }
            fs::remove_all(pending);
            git(clone(url, pending), "during-init restored clone positive control");
            positive(pending);
            fs::remove_all(pending);
        }
        retireBoundaries(themes, privateRoot, url, shared);
        for (int i {0}; i < 3; ++i) {
            ThemeRepositoryTrust::close();
            git_libgit2_shutdown();
            require(git_libgit2_init() > 0, "libgit2 reinitializes");
            prepare();
            positive(original);
        }
        int validation {0};
        git(git_libgit2_opts(GIT_OPT_GET_OWNER_VALIDATION, &validation), "owner validation getter");
        require(validation == 1, "owner validation remains enabled");
        evidence << "PASS: three shutdown/reinitialize/open cycles; owner validation=1\n";
    }
} // namespace

void ThemeRepositoryTrust::Testing::initialFailure(const std::string& path,
                                                   const std::map<std::string, std::string>& values,
                                                   bool parsed,
                                                   int fd,
                                                   int64_t firstSize)
{
    // Only explicit, ES-DE-Plus-authored control suites collect this evidence.
    // Record interpretation and bytes without logging arbitrary config values.
    if (!running)
        return;
    const git_error* error {git_error_last()};
    evidence << "METADATA path=" << path << '\n'
             << "INIT-FAIL parsed=" << parsed << " error-class=" << (error ? error->klass : -1)
             << " keys=" << values.size() << " first-fstat-size=" << firstSize << '\n';
    for (const auto& entry : values) {
        if (entry.first.compare(0, 5, "core.") == 0 && entry.first.size() < 80 &&
            entry.first.find_first_not_of("abcdefghijklmnopqrstuvwxyz.-_") == std::string::npos)
            evidence << "INIT-KEY " << entry.first << "="
                     << (entry.second == "true" || entry.second == "false" || entry.second == "0" ?
                             entry.second :
                             "<other>")
                     << '\n';
        else
            evidence << "INIT-KEY non-core; value omitted\n";
    }
    struct stat info {
    };
    if (fd < 0 || fstat(fd, &info) != 0 || !S_ISREG(info.st_mode)) {
        evidence << "INIT-VIEW unavailable errno=" << errno << '\n';
        return;
    }
    // Observe the original held descriptor before its close can refresh a
    // cached view; this never reopens or retries the failed clone.
    if (lseek(fd, 0, SEEK_SET) < 0) {
        evidence << "INIT-VIEW seek failed errno=" << errno << '\n';
        return;
    }
    std::string bytes;
    char buffer[4096];
    ssize_t count;
    while ((count = ::read(fd, buffer, sizeof(buffer))) > 0 && bytes.size() < 65536)
        bytes.append(buffer, count);
    evidence << "INIT-VIEW dev=" << info.st_dev << " inode=" << info.st_ino
             << " size=" << info.st_size << " read=" << bytes.size() << " read-status=" << count;
    git_oid hash;
    if (count == 0 && git_odb_hash(&hash, bytes.data(), bytes.size(), GIT_OBJECT_BLOB) == 0) {
        char hex[GIT_OID_HEXSZ + 1];
        git_oid_tostr(hex, sizeof(hex), &hash);
        evidence << " blob-sha1=" << hex;
    }
    evidence << '\n';
}

void ThemeRepositoryTrust::Testing::runIfRequested(const std::string& themes,
                                                   const std::string& privateDirectory)
{
    const std::string request {privateDirectory + "/theme-trust.request"};
    if (running)
        return;
    controlDirectory = privateDirectory;
    fault = Fault::NONE;
    const std::string injection {privateDirectory + "/theme-trust.inject"};
    const std::string injected {read(injection)};
    if (!injected.empty()) {
        fs::rename(injection, injection + ".running");
        if (injected == "temporary\n")
            fault = Fault::TEMPORARY;
        else if (injected == "replace\n")
            fault = Fault::REPLACE;
        else if (injected == "search\n")
            fault = Fault::SEARCH;
        return;
    }
    if (read(request) != "ES-DE-Plus theme trust controls\n")
        return;
    running = true;
    fs::rename(request, request + ".running");
    evidence.str("");
    cloneTraces.clear();
    try {
        const std::string privateRoot {temporary(privateDirectory)};
        const std::string bootstrap {privateRoot + "/bootstrap"};
        fs::create_directory(bootstrap);
        write(bootstrap + "/.gitconfig", "[safe]\n");
        for (int level :
             {GIT_CONFIG_LEVEL_SYSTEM, GIT_CONFIG_LEVEL_XDG, GIT_CONFIG_LEVEL_PROGRAMDATA})
            git(git_libgit2_opts(GIT_OPT_SET_SEARCH_PATH, level, ""),
                "fixture protected config levels");
        git(git_libgit2_opts(GIT_OPT_SET_SEARCH_PATH, GIT_CONFIG_LEVEL_GLOBAL, bootstrap.c_str()),
            "fixture private global config");
        const std::string source {privateRoot + "/source"};
        git_repository* raw {nullptr};
        git(git_repository_init(&raw, source.c_str(), 0), "create original private fixture");
        {
            Repository repository(raw, git_repository_free);
            commit(repository.get(), source, "first");
            commit(repository.get(), source, "second");
        }
        std::string normalized {themes};
        while (!normalized.empty() && normalized.back() == '/')
            normalized.pop_back();
        const std::string temporaryRoot {temporary(fs::path(normalized).parent_path().string())};
        // D-012 am. 5: quotes are refused in shared data paths; actual quoted
        // Git paths and their protected allowlist are tested in private storage.
        const std::string sharedRoot {temporaryRoot + " # ; caf\xc3\xa9"};
        fs::rename(temporaryRoot, sharedRoot);
#if defined(__ANDROID__)
        suite(sharedRoot, privateRoot + "/direct-config", source, true);
#else
        // Host execution exercises the same gates with app-owned directories; FUSE
        // ownership evidence is mandatory separately on the Android runtime targets.
        suite(sharedRoot, privateRoot + "/direct-config", source, false);
#endif
        const std::string quotedPrivate {privateRoot + "/scoped # ; \" \\ caf\xc3\xa9"};
        fs::create_directory(quotedPrivate);
        const std::string scopedAlias {privateRoot + "/scoped-alias"};
        fs::create_directory_symlink(quotedPrivate, scopedAlias);
        suite(scopedAlias, privateRoot + "/scoped-config", source, false);
        evidence
            << "RESIDUAL: shared writers can race initialization and later filesystem operations. "
               "The callback gates remote/fetch/checkout; it is not storage isolation (D-012 am. "
               "4).\n";
        evidence << "PASS: app-context theme trust controls\n";
    }
    catch (const std::exception& error) {
        evidence << "FAIL: " << error.what() << '\n';
    }
    fault = Fault::NONE;
    barrier = {};
    ThemeRepositoryTrust::close();
    write(privateDirectory + "/theme-trust.result", evidence.str());
    running = false;
}

void ThemeRepositoryTrust::Testing::interruptIfRequested(const std::string& stage,
                                                         const std::string& path)
{
    if (controlDirectory.empty() ||
        (stage != "clone-retire-created" && stage != "clone-retire-unlinked" &&
         stage != "clone-retire-renamed" && stage != "clone-post-check"))
        return;
    const std::string name {fs::path(path).filename().string()};
    const std::string expected {stage + "\n" + name + "\n"};
    const std::string request {controlDirectory + "/theme-retire.interrupt"};
    if (read(request) != expected)
        return;
    require(validName(name) && ready() && permit(path), "interruption control is admitted");
    fs::rename(request, request + ".running");
    std::ostringstream state;
    state << expected << path << "\napp-uid=" << geteuid() << '\n';
    for (const std::string relative : {"config", ThemeRepositoryFuse::temporaryName}) {
        struct stat info {
        };
        const bool exists {lstat((path + "/.git/" + relative).c_str(), &info) == 0};
        require(exists || errno == ENOENT, "interruption state is observable");
        state << relative << " exists=" << exists
              << " regular=" << (exists && S_ISREG(info.st_mode))
              << " size=" << (exists ? info.st_size : 0) << '\n';
    }
    write(controlDirectory + "/theme-retire.reached.new", state.str());
    fs::rename(controlDirectory + "/theme-retire.reached.new",
               controlDirectory + "/theme-retire.reached");
    // The harness terminates this process. A missed termination fails instead
    // of allowing an incomplete control to look like a successful clone.
    for (int sample {0}; sample < 1200; ++sample)
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    throw std::runtime_error("Interruption control was not terminated within its bounded wait");
}

void ThemeRepositoryTrust::Testing::afterAdmission(const std::string& themes,
                                                   const std::string& privateDirectory)
{
    const std::string request {privateDirectory + "/theme-trust.rewind"};
    std::string name {read(request)};
    if (name.empty())
        return;
    fs::rename(request, request + ".running");
    std::ostringstream result;
    try {
        require(name.back() == '\n', "complete debug rewind request");
        name.pop_back();
        require(validName(name) && name != "themes-list" && permit(themes + "/" + name),
                "rewind request has an admitted theme name");
        result << "APP CONFIG BEFORE REWIND\n" << configState(themes + "/" + name);
        auto repository = open(themes + "/" + name);
        require(verify(repository.get(), themes + "/" + name), "rewind identity");
        result << "latest=" << head(repository.get()) << '\n';
        git_reference* reference {nullptr};
        git(git_repository_head(&reference, repository.get()), "rewind branch");
        result << "reference=" << git_reference_name(reference) << '\n';
        git_reference_free(reference);
        git_config* config {nullptr};
        git(git_repository_config(&config, repository.get()), "rewind config");
        int filemode {0};
        const int configured {git_config_get_bool(&filemode, config, "core.filemode")};
        git_config_free(config);
        require(configured == 0 || configured == GIT_ENOTFOUND, "filemode readable");
        result << "core.filemode=" << (configured == 0 ? std::to_string(filemode) : "unset")
               << '\n';
        git_object* previous {nullptr};
        git(git_revparse_single(&previous, repository.get(), "HEAD~1"), "rewind parent");
        git(git_reset(repository.get(), previous, GIT_RESET_HARD, nullptr), "rewind one commit");
        result << "APP CONFIG AFTER REWIND\n" << configState(themes + "/" + name);
        git_object_free(previous);
        result << "previous=" << head(repository.get()) << '\n' << "PASS: one commit behind\n";
    }
    catch (const std::exception& error) {
        result << "FAIL: " << error.what() << '\n';
    }
    write(privateDirectory + "/theme-trust.rewind-result", result.str());
}

void ThemeRepositoryTrust::Testing::changeBeforeLookup(git_repository* repository,
                                                       const std::string& path,
                                                       const std::string& privateDirectory,
                                                       bool worker)
{
    const std::string missingRequest {privateDirectory + "/theme-retire.missing-origin"};
    const std::string repositoryName {fs::path(path).filename().string()};
    if ((worker || repositoryName == "themes-list") &&
        read(missingRequest) == repositoryName + "\n") {
        fs::rename(missingRequest, missingRequest + ".running");
        const std::string previous {read(path + "/.git/config")};
        require(!previous.empty(), "missing-origin fixture has a complete backup");
        write(privateDirectory + "/theme-trust.remote-race-backup", previous);
        write(privateDirectory + "/theme-trust.remote-race-path", path + "/.git/config");
        setting(repository, "remote.origin.url", nullptr);
        setting(repository, "remote.origin.fetch", nullptr);
        write(privateDirectory + "/theme-retire.missing-origin-result",
              "PASS: real repository-local origin omitted after identity check\n" + path + "\n");
    }
    if (!worker)
        return;
    const std::string request {privateDirectory + "/theme-trust.remote-race"};
    std::istringstream input(read(request));
    std::string name;
    std::string replacement;
    if (!std::getline(input, name) || !std::getline(input, replacement) ||
        fs::path(path).filename().string() != name)
        return;
    fs::rename(request, request + ".running");
    git_remote* remote {nullptr};
    git(git_remote_lookup(&remote, repository, "origin"), "remote-race positive precheck");
    const char* raw {git_remote_url(remote)};
    const std::string previous {raw ? raw : ""};
    git_remote_free(remote);
    require(!previous.empty() && previous != replacement,
            "remote-race actually changes the origin");
    const std::string previousConfig {read(path + "/.git/config")};
    require(!previousConfig.empty(), "remote-race config backup is complete");
    write(privateDirectory + "/theme-trust.remote-race-backup", previousConfig);
    write(privateDirectory + "/theme-trust.remote-race-path", path + "/.git/config");
    setting(repository, "remote.origin.url", &replacement);
    write(privateDirectory + "/theme-trust.remote-race-result",
          "PASS: worker changed origin after precheck and before lookup\npath=" + path +
              "\nprevious=" + previous + "\nreplacement=" + replacement + "\n");
}

void ThemeRepositoryTrust::Testing::fuseIfRequested(
    const std::string& themes,
    const std::string& privateDirectory,
    const std::function<bool(const std::string&, const std::string&, int)>& operation)
{
    const std::string request {privateDirectory + "/theme-fuse.request"};
    if (read(request) != "ES-DE-Plus FUSE controls\n")
        return;
    fs::rename(request, request + ".running");
    if (!ThemeRepositoryTrust::ready()) {
        write(privateDirectory + "/theme-fuse.result",
              "FAIL: FUSE controls require trust prerequisites\n");
        return;
    }
    std::ostringstream output;
    size_t sequence {0};
    auto restoreRetirement =
        std::unique_ptr<bool, std::function<void(bool*)>>(&retireEnabled, [](bool* value) {
            *value = true;
            barrier = {};
            fault = Fault::NONE;
        });
    try {
        preservingSession([&] {
            const std::string privateRoot {temporary(privateDirectory)};
            fs::create_directory(privateRoot + "/config");
            const std::string source {privateRoot + "/source"};
            const std::string url {"file://" + source};
            git_repository* raw {nullptr};
            git(git_repository_init(&raw, source.c_str(), 0), "FUSE source init");
            Repository origin(raw, git_repository_free);
            auto advance = [&](const std::string& description) {
                rapidjson::StringBuffer buffer;
                rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
                writer.StartObject();
                writer.Key("themes");
                writer.StartArray();
                writer.StartObject();
                writer.Key("name");
                writer.String(("ES-DE-Plus " + description).c_str());
                writer.Key("author");
                writer.String("ES-DE-Plus");
                writer.Key("reponame");
                writer.String("original");
                writer.Key("url");
                writer.String(url.c_str());
                writer.EndObject();
                writer.EndArray();
                writer.EndObject();
                write(source + "/themes.json", buffer.GetString());
                git_index* index {nullptr};
                git(git_repository_index(&index, origin.get()), "FUSE list index");
                git(git_index_add_bypath(index, "themes.json"), "FUSE list content changed");
                git(git_index_write(index), "FUSE list index staged");
                git_index_free(index);
                commit(origin.get(), source, description);
            };
            advance("FUSE initial tracked content");
            advance("FUSE second tracked content");
            git_reference* sourceHead {nullptr};
            git(git_repository_head(&sourceHead, origin.get()), "FUSE source branch");
            const std::string branch {git_reference_shorthand(sourceHead)};
            git_reference_free(sourceHead);
            std::string normalized {themes};
            while (!normalized.empty() && normalized.back() == '/')
                normalized.pop_back();
            const std::string data {fs::path(normalized).parent_path().string()};
            const std::string base {temporary(data)};

            auto snapshot = [&](const std::string& path, const char* mode, const char* stage,
                                int cloneNumber, int cycle) {
                const std::string directory {path + "/.git"};
                std::set<std::string> names {"config",
                                             "HEAD",
                                             "index",
                                             "FETCH_HEAD",
                                             "packed-refs",
                                             "ORIG_HEAD",
                                             "refs/heads/" + branch,
                                             "refs/remotes/origin/" + branch,
                                             "refs/remotes/origin/retired"};
                if (fs::is_directory(directory)) {
                    for (auto it = fs::recursive_directory_iterator(directory);
                         it != fs::recursive_directory_iterator(); ++it) {
                        const std::string relative {
                            it->path().lexically_relative(directory).string()};
                        if (relative == "objects" || relative == "hooks" || relative == "info") {
                            it.disable_recursion_pending();
                            continue;
                        }
                        if (!it->is_directory())
                            names.insert(relative);
                    }
                }
                rapidjson::StringBuffer buffer;
                rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
                writer.StartObject();
                writer.Key("sequence");
                writer.Uint64(++sequence);
                writer.Key("mode");
                writer.String(mode);
                writer.Key("stage");
                writer.String(stage);
                writer.Key("clone");
                writer.Int(cloneNumber);
                writer.Key("cycle");
                writer.Int(cycle);
                writer.Key("directory");
                writer.String(directory.c_str());
                writer.Key("expectedHead");
                writer.String(head(origin.get()).c_str());
                writer.Key("files");
                writer.StartArray();
                for (const auto& name : names) {
                    struct stat info {
                    };
                    const bool exists {lstat((directory + "/" + name).c_str(), &info) == 0};
                    require(exists || errno == ENOENT, "FUSE metadata stat");
                    require(!exists || S_ISREG(info.st_mode), "FUSE metadata regular file");
                    writer.StartObject();
                    writer.Key("path");
                    writer.String(name.c_str());
                    writer.Key("exists");
                    writer.Bool(exists);
                    if (exists) {
                        const auto bytes {read(directory + "/" + name)};
                        git_oid hash;
                        git(git_odb_hash(&hash, bytes.data(), bytes.size(), GIT_OBJECT_BLOB),
                            "FUSE view hash");
                        char hex[GIT_OID_HEXSZ + 1];
                        git_oid_tostr(hex, sizeof(hex), &hash);
                        writer.Key("size");
                        writer.Uint64(info.st_size);
                        writer.Key("read");
                        writer.Uint64(bytes.size());
                        writer.Key("hash");
                        writer.String(hex);
                    }
                    writer.EndObject();
                }
                writer.EndArray();
                writer.EndObject();
                write(privateDirectory + "/theme-fuse.snapshot.new", buffer.GetString());
                fs::rename(privateDirectory + "/theme-fuse.snapshot.new",
                           privateDirectory + "/theme-fuse.snapshot");
                const std::string expected {std::to_string(sequence) + " CONTINUE\n"};
                bool acknowledged {false};
                for (int wait {0}; wait < 480; ++wait) {
                    const std::string reply {read(privateDirectory + "/theme-fuse.ack")};
                    require(reply != std::to_string(sequence) + " STOP\n",
                            "AC-3 view/lower mismatch: stop under protocol section 9");
                    if (reply == expected) {
                        acknowledged = true;
                        break;
                    }
                    std::this_thread::sleep_for(std::chrono::milliseconds(250));
                }
                require(acknowledged, "bounded FUSE readback rendezvous");
            };

            for (bool enabled : {false, true}) {
                retireEnabled = enabled;
                const char* mode {enabled ? "on" : "off"};
                const std::string root {base + "/fuse-" + mode};
                const std::string directory {root + "/themes"};
                fs::create_directories(root);
                configure(directory, privateRoot + "/config");
                require(ready() && expectList(url) && admit(document(url)), "FUSE spike admission");
                for (int number {0}; number < 20; ++number) {
                    const std::string path {directory +
                                            (number % 2 ? "/original" : "/themes-list")};
                    require(permit(path), "FUSE clone destination admission");
                    fs::remove_all(path);
                    git_reference* extra {nullptr};
                    git_oid latest;
                    git(git_oid_fromstr(&latest, head(origin.get()).c_str()), "FUSE source oid");
                    git(git_reference_create(&extra, origin.get(), "refs/heads/retired", &latest, 1,
                                             "ES-DE-Plus pruning fixture"),
                        "FUSE source extra ref");
                    git_reference_free(extra);
                    const bool cloned {operation(path, url, 0)};
                    snapshot(path, mode, "clone-after-listing", number, -1);
                    if (enabled)
                        require(cloned, "AC-3 mandatory actual downloader clone");
                    if (!enabled)
                        continue; // Fixed-size diagnostic; not a retry of a mandatory operation.
                    {
                        auto repository = open(path);
                        git_refdb* database {nullptr};
                        git(git_repository_refdb(&database, repository.get()), "FUSE refdb");
                        if ((number / 2) % 2)
                            git(git_refdb_compress(database), "FUSE pre-existing packed refs");
                        git_refdb_free(database);
                    }
                    for (int cycle {0}; cycle < 3; ++cycle) {
                        advance("FUSE tracked update " + std::to_string(number) + "/" +
                                std::to_string(cycle));
                        if (cycle == 0)
                            git(git_reference_remove(origin.get(), "refs/heads/retired"),
                                "FUSE source prune");
                        if (cycle == 2) {
                            auto repository = open(path);
                            git_oid previous;
                            git(git_oid_fromstr(&previous, head(repository.get()).c_str()),
                                "FUSE detached oid");
                            git(git_repository_set_head_detached(repository.get(), &previous),
                                "FUSE detached fixture");
                        }
                        // The callback invokes the production downloader methods,
                        // including resetRepository and fetchRepository.
                        snapshot(path, mode, "before-update", number, cycle);
                        const bool updated {operation(path, url, 2) && operation(path, url, 1)};
                        fingerprint(path);
                        snapshot(path, mode, "after-update-listing", number, cycle);
                        require(updated, "AC-3 mandatory actual downloader reset/update");
                        {
                            auto repository = open(path);
                            require(head(repository.get()) == head(origin.get()) &&
                                        read(path + "/theme.xml") == read(source + "/theme.xml"),
                                    "AC-3 actual tracked content and HEAD advance");
                            require(read(path + "/themes.json") == read(source + "/themes.json"),
                                    "AC-3 themes-list tracked content advances");
                        }
                    }
                    output << "PASS: R1 clone=" << number << " updates=3 actual downloader paths\n";
                }
            }
            const std::string directory {base + "/fuse-on/themes"};
            for (const std::string faultName : {"origin", "branch"}) {
                const std::string name {faultName == "origin" ? "original" : "themes-list"};
                const std::string path {directory + "/" + name};
                const std::string other {directory +
                                         (faultName == "origin" ? "/themes-list" : "/original")};
                const uint64_t otherBefore {fingerprint(other)};
                const std::string configBefore {read(privateRoot + "/config/libgit2/.gitconfig")};
                require(permit(path), "post-clone fault destination admitted");
                fs::remove_all(path); // This isolated control owns the disposable target.
                bool reached {false};
                barrier = [&](const std::string& stage, const std::string& candidate) {
                    if (stage != "clone-post-check" || candidate != path)
                        return;
                    reached = true;
                    auto repository = open(path);
                    if (faultName == "origin") {
                        setting(repository.get(), "remote.origin.url", nullptr);
                        setting(repository.get(), "remote.origin.fetch", nullptr);
                    }
                    else {
                        git_reference* head {nullptr};
                        git(git_repository_head(&head, repository.get()), "post-clone branch");
                        const std::string key {std::string("branch.") +
                                               git_reference_shorthand(head) + ".remote"};
                        git_reference_free(head);
                        setting(repository.get(), key.c_str(), nullptr);
                    }
                };
                bool cloned {false};
                try {
                    cloned = operation(path, url, 0);
                }
                catch (...) {
                    barrier = {};
                    throw;
                }
                barrier = {};
                require(reached && !cloned && !fs::exists(path),
                        "post-clone integrity failure uses admitted cleanup");
                require(fingerprint(other) == otherBefore &&
                            read(privateRoot + "/config/libgit2/.gitconfig") == configBefore,
                        "post-clone cleanup preserves the other repository and protected config");
                require(operation(path, url, 0),
                        "post-clone restored actual clone positive control");
                output << "PASS: post-clone missing-" << faultName
                       << " rejected; admitted cleanup; "
                          "other repository/private config unchanged; restored clone passed\n";
            }
        });
        output << "PASS: FUSE retirement controls; 20 mandatory clones x 3 changing updates\n";
    }
    catch (const std::exception& error) {
        output << "FAIL: " << error.what() << '\n';
    }
    write(privateDirectory + "/theme-fuse.result.new", output.str());
    fs::rename(privateDirectory + "/theme-fuse.result.new",
               privateDirectory + "/theme-fuse.result");
}
#endif
