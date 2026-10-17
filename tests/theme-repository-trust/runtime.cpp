//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  runtime.cpp
//  Written for ES-DE-Plus. Framework-free runner for the app-context Git controls.

#include "ThemeRepositoryFuse.h"
#include "ThemeRepositoryTrust.h"

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
    ThemeRepositoryTrust::close();
    git_libgit2_shutdown();
    return result.find("PASS: app-context theme trust controls\n") != std::string::npos ? 0 : 1;
}
