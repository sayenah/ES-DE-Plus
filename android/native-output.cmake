# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus to isolate Gradle native outputs by ABI.
# Loaded after the NDK toolchain by CMAKE_PROJECT_TOP_LEVEL_INCLUDES.
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
