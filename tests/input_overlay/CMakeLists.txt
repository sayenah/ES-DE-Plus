# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Framework-free overlay model checks.
cmake_minimum_required(VERSION 3.13)
project(input_overlay_tests LANGUAGES CXX)
enable_testing()
add_executable(input_overlay_tests main.cpp ../../es-core/src/InputOverlayModel.cpp)
target_include_directories(input_overlay_tests PRIVATE ../../es-core/src)
target_compile_features(input_overlay_tests PRIVATE cxx_std_17)
target_compile_options(input_overlay_tests PRIVATE -Wall -Wextra -Werror)
add_test(NAME input_overlay_model COMMAND input_overlay_tests)
