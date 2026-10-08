# Build log

Material completed build facts (protocol §6). One line each.

`YYYY-MM-DD | PR/commit | Built/changed | Validation`

2026-10-08 | PR #4 / 7645fd5e7 | Android arm64-v8a + x86_64 dependencies and debug APK: NDK 27.3.13750724/API29, JDK17, SDK36, CMake3.31.5, AGP8.13.2, Gradle wrapper8.13, Kotlin2.2.21, OpenSSL3.5.9 LTS, curl8.22.0; clang-format18.1.3 (Ubuntu 1:18.1.3-1ubuntu1). All GPL/LGPL switches and common configure templates are recorded verbatim in [the dependency inventory](../android/DEPENDENCY-LICENSES.md); Poppler/ConvertPDF remain GPL-2.0 in process, FFmpeg has `--disable-gpl --disable-nonfree`. | [Both dependency ABI builds](https://github.com/sayenah/ES-DE-Plus/actions/runs/37753405763) passed; [APK assembly, native warnings, zip/identity audit](https://github.com/sayenah/ES-DE-Plus/actions/runs/37760868837) passed, ELF audit fails the pinned NDK libc++ RELRO check on both ABIs; [Linux build/format gate](https://github.com/sayenah/ES-DE-Plus/actions/runs/37760862905) passed. Runtime/cache evidence incomplete; no APK uploaded.
