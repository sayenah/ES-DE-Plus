# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Framework-free repository policy checks.
cmake_minimum_required(VERSION 3.16)
project(ThemeRepositoryTrustTests LANGUAGES CXX)
enable_testing()
add_executable(theme-repository-trust policy.cpp ../../es-app/src/guis/ThemeRepositoryTrust.cpp)
target_compile_features(theme-repository-trust PRIVATE cxx_std_17)
target_include_directories(theme-repository-trust PRIVATE ../../es-app/src/guis
                           ../../external/rapidjson/include)
add_test(NAME theme-repository-trust COMMAND theme-repository-trust)

option(THEME_TRUST_RUNTIME "Run the Git operation controls with the installed libgit2" OFF)
if(THEME_TRUST_RUNTIME)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(GIT2 REQUIRED IMPORTED_TARGET libgit2)
    add_executable(theme-repository-trust-runtime runtime.cpp
                   ../../es-app/src/guis/ThemeRepositoryTrust.cpp
                   ../../es-app/src/guis/ThemeRepositoryTrustDebug.cpp)
    target_compile_features(theme-repository-trust-runtime PRIVATE cxx_std_17)
    target_compile_definitions(theme-repository-trust-runtime PRIVATE THEME_TRUST_TEST)
    target_compile_options(theme-repository-trust-runtime PRIVATE -UNDEBUG)
    target_include_directories(theme-repository-trust-runtime PRIVATE ../../es-app/src/guis
                               ../../external/rapidjson/include)
    target_link_libraries(theme-repository-trust-runtime PRIVATE PkgConfig::GIT2)
    add_test(NAME theme-repository-trust-runtime
             COMMAND theme-repository-trust-runtime ${CMAKE_CURRENT_BINARY_DIR}/runtime-fixtures)
endif()
