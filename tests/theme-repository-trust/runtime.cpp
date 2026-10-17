//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  runtime.cpp
//  Written for ES-DE-Plus. Framework-free runner for the app-context Git controls.

#include "ThemeRepositoryFuse.h"
#include "ThemeRepositoryTrust.h"
#include "ThemeRepositoryTrustDebug.h"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <unistd.h>

int main(int argc, char** argv)
{
    if (argc != 2)
        return 2;
    const std::string root {argv[1]};
    std::filesystem::create_directories(root + "/private");
    std::filesystem::create_directories(root + "/data");
    std::ofstream(root + "/private/theme-trust.request") << "ES-DE-Plus theme trust controls\n";
    git_libgit2_init();
    std::string probe {root + "/init-key-table.XXXXXX"};
    if (!mkdtemp(probe.data()))
        return 1;
    git_repository* initialized {nullptr};
    git_repository_init_options options {};
    git_repository_init_options_init(&options, GIT_REPOSITORY_INIT_OPTIONS_VERSION);
    options.flags = GIT_REPOSITORY_INIT_MKDIR | GIT_REPOSITORY_INIT_NO_REINIT;
    ThemeRepositoryFuse::Values actual;
    const bool pinned {git_repository_init_ext(&initialized, probe.c_str(), &options) == 0 &&
                       ThemeRepositoryFuse::readConfig(probe + "/.git/config", actual) &&
                       ThemeRepositoryFuse::initKeys(actual)};
    git_repository_free(initialized);
    if (!pinned) {
        std::cerr << "FAIL: libgit2 init output differs from ES-DE-Plus key table\n";
        return 1;
    }
    std::cout << "PASS: init-key table pinned against actual libgit2 init output\n";
    ThemeRepositoryTrust::configure(root + "/data/themes", root + "/private");
    std::ifstream stream(root + "/private/theme-trust.result");
    const std::string result {std::istreambuf_iterator<char>(stream),
                              std::istreambuf_iterator<char>()};
    std::cout << result;
    if (result.find("PASS: app-context theme trust controls\n") == std::string::npos)
        return 1;
    std::string diagnosticRoot {root + "/diagnostic-boundary.XXXXXX"};
    if (!mkdtemp(diagnosticRoot.data()))
        return 1;
    std::filesystem::create_directories(diagnosticRoot + "/private");
    std::filesystem::create_directories(diagnosticRoot + "/data");
    std::ofstream(diagnosticRoot + "/private/theme-trust.request")
        << "ES-DE-Plus theme trust controls\n";
    ThemeRepositoryTrust::Testing::barrier = [](const std::string& stage, const std::string& path) {
        if (stage == "clone-after-init")
            std::ofstream(path + "/.git/config")
                << "[core]\n bare=false\n repositoryformatversion=0\n"
                   " secret=diagnostic-sentinel-not-a-secret\n";
    };
    ThemeRepositoryTrust::configure(diagnosticRoot + "/data/themes", diagnosticRoot + "/private");
    ThemeRepositoryTrust::Testing::barrier = {};
    std::ifstream captured(diagnosticRoot + "/private/theme-trust.result");
    const std::string diagnostic {std::istreambuf_iterator<char>(captured),
                                  std::istreambuf_iterator<char>()};
    if (diagnostic.find("INIT-FAIL parsed=0") == std::string::npos ||
        diagnostic.find("METADATA path=") == std::string::npos ||
        diagnostic.find("blob-sha1=") == std::string::npos ||
        diagnostic.find("FAIL:") == std::string::npos ||
        diagnostic.find("diagnostic-sentinel-not-a-secret") != std::string::npos) {
        std::cerr << "FAIL: init refusal diagnostic did not preserve redacted evidence\n";
        return 1;
    }
    std::cout << "PASS: expected init refusal retains metadata/hash evidence and redacts values\n";
    std::string cleanupRoot {root + "/cleanup-boundary.XXXXXX"};
    if (!mkdtemp(cleanupRoot.data()))
        return 1;
    std::filesystem::create_directories(cleanupRoot + "/private");
    std::filesystem::create_directories(cleanupRoot + "/data");
    const std::string candidate {cleanupRoot + "/data/themes/themes-list"};
    ThemeRepositoryTrust::configure(cleanupRoot + "/data/themes", cleanupRoot + "/private");
    if (!ThemeRepositoryTrust::expectList("file://" + probe))
        return 1;
    ThemeRepositoryTrust::Testing::barrier = [&](const std::string& stage,
                                                 const std::string& path) {
        if (stage == "clone-retire-written")
            std::filesystem::rename(path + "/.git", path + "/.git-moved");
    };
    git_repository* interrupted {nullptr};
    const int refused {ThemeRepositoryTrust::create(&interrupted, candidate.c_str(), 0, nullptr)};
    ThemeRepositoryTrust::Testing::barrier = {};
    git_repository_free(interrupted);
    if (refused == 0 || !std::filesystem::is_regular_file(candidate + "/.git-moved/" +
                                                          ThemeRepositoryFuse::temporaryName)) {
        std::cerr << "FAIL: lost identity did not block retirement cleanup\n";
        return 1;
    }
    std::cout << "PASS: lost gitdir identity blocks retirement cleanup; leftover is not promoted\n";
    ThemeRepositoryTrust::close();
    git_libgit2_shutdown();
    return result.find("PASS: app-context theme trust controls\n") != std::string::npos ? 0 : 1;
}
