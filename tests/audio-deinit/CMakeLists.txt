# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Framework-free real-SDL teardown detector.
cmake_minimum_required(VERSION 3.13)
project(audio_deinit_detector LANGUAGES CXX)

find_package(SDL2 REQUIRED)
get_filename_component(REPO "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(AUDIO_MANAGER_SOURCE "${REPO}/es-core/src/AudioManager.cpp" CACHE FILEPATH
    "Actual AudioManager source under test (base or fixed)")
add_executable(audio-deinit detector.cpp support.cpp
    "${AUDIO_MANAGER_SOURCE}" "${REPO}/es-core/src/Sound.cpp")
target_compile_features(audio-deinit PRIVATE cxx_std_17)
target_compile_options(audio-deinit PRIVATE -Wall -Werror -ffunction-sections -fdata-sections)
set_source_files_properties(detector.cpp support.cpp PROPERTIES COMPILE_OPTIONS -Wextra)
target_include_directories(audio-deinit PRIVATE "${REPO}/es-core/src" "${REPO}/external/glm"
    ${SDL2_INCLUDE_DIRS})
# Unused theme/resource-loading functions in Sound.cpp are outside this focused executable.
target_link_options(audio-deinit PRIVATE -Wl,--gc-sections -Wl,--export-dynamic-symbol=SDL_*)
target_link_libraries(audio-deinit PRIVATE ${SDL2_LIBRARIES} ${CMAKE_DL_LIBS})

add_library(audio-desktop-probe SHARED desktop.cpp)
target_compile_features(audio-desktop-probe PRIVATE cxx_std_17)
target_compile_options(audio-desktop-probe PRIVATE -Wall -Wextra -Werror)
target_include_directories(audio-desktop-probe PRIVATE ${SDL2_INCLUDE_DIRS})
target_link_libraries(audio-desktop-probe PRIVATE ${SDL2_LIBRARIES} ${CMAKE_DL_LIBS})
