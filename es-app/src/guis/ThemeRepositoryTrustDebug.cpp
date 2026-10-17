//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ThemeRepositoryTrustDebug.cpp
//  Written for ES-DE-Plus. Original Git/XML/JSON fixtures; public libgit2 APIs only.
//  These app-context controls and fault/barrier hooks are absent from release builds.

#include "ThemeRepositoryTrustDebug.h"

#if !defined(NDEBUG) && (defined(__ANDROID__) || defined(THEME_TRUST_TEST))
#include "ThemeRepositoryTrust.h"
#include "rapidjson/stringbuffer.h"
#include "rapidjson/writer.h"

#include <cerrno>
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
    std::function<void(const std::string&, const std::string&)> barrier;
} // namespace ThemeRepositoryTrust::Testing

namespace
{
    namespace fs = std::filesystem;
    using Repository = std::unique_ptr<git_repository, decltype(&git_repository_free)>;
    using Remote = std::unique_ptr<git_remote, decltype(&git_remote_free)>;
    std::ostringstream evidence;
    bool running {false};
    int fetches {0};
    struct CloneTrace {
        std::string initialized;
        std::string remote;
        std::string completed;
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
        const int result {git_clone(&repository, url.c_str(), path.c_str(), &options)};
        if (result != 0)
            ThemeRepositoryTrust::diagnoseCloneFailure(path, result);
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

void ThemeRepositoryTrust::Testing::runIfRequested(const std::string& themes,
                                                   const std::string& privateDirectory)
{
    const std::string request {privateDirectory + "/theme-trust.request"};
    if (running)
        return;
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
#endif
