//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  runtime.cpp
//  Written for ES-DE-Plus. Framework-free runner for the app-context Git controls.

#include "ThemeRepositoryTrust.h"

#include <filesystem>
#include <fstream>
#include <iostream>

int main(int argc, char** argv)
{
    if (argc != 2)
        return 2;
    const std::string root {argv[1]};
    std::filesystem::create_directories(root + "/private");
    std::filesystem::create_directories(root + "/data");
    std::ofstream(root + "/private/theme-trust.request") << "ES-DE-Plus theme trust controls\n";
    git_libgit2_init();
    ThemeRepositoryTrust::configure(root + "/data/themes", root + "/private");
    std::ifstream stream(root + "/private/theme-trust.result");
    const std::string result {std::istreambuf_iterator<char>(stream),
                              std::istreambuf_iterator<char>()};
    std::cout << result;
    ThemeRepositoryTrust::close();
    git_libgit2_shutdown();
    return result.find("PASS: app-context theme trust controls\n") != std::string::npos ? 0 : 1;
}
