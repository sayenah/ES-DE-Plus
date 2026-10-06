# Android clean-room integration notes

This document describes the Android-facing behavior required by ES-DE-Plus. It is an
interoperability and reimplementation specification, not a copy of the proprietary Android
source used by the official ES-DE Android package.

## Reference package

Observed package: ES-DE 3.5.0-65 for Android.

The package reports the Android application ID `org.es_de.frontend` and contains the open-source
ES-DE C++ frontend as an SDL-based native library together with an Android host layer.

ES-DE-Plus must use its own application ID and branding before distributing APKs.

## Android host responsibilities

The clean-room host needs to provide these platform services to the native frontend:

- SDL activity lifecycle and native library startup.
- Persistent application-data and ROM directory settings.
- Storage Access Framework (SAF) document-tree selection and URI persistence.
- All-files-access handling where explicitly chosen by the user and supported by Android.
- Directory creation, enumeration and path/URI conversion used by ES-DE.
- Installed-package discovery for Android games, apps and emulators.
- Android Intent construction for launching standalone emulators and native apps.
- Launch-on-display selection for multi-display and dual-screen devices.
- Battery, Wi-Fi, cellular and Bluetooth status queries used by ES-DE.
- Window/display-size reporting.
- First-run configuration UI for permissions and data/ROM directory selection.
- Optional Android home/launcher and Android TV/Leanback entry points.
- A FileProvider-compatible mechanism for sharing launchable content URIs when required.

## Launcher entry points

The reference package exposes distinct entry behavior for:

- normal launcher startup;
- Android HOME/launcher operation;
- Android TV / Leanback startup.

ES-DE-Plus should implement these as first-party open-source Android components instead of
depending on the proprietary host.

## Storage

The reference behavior uses both direct filesystem access and Android SAF.

Relevant Android surfaces include:

- `ACTION_OPEN_DOCUMENT_TREE`;
- persisted document-tree URIs;
- `MANAGE_APP_ALL_FILES_ACCESS_PERMISSION` when the user explicitly chooses direct filesystem
  access;
- document-provider URIs under the external-storage provider.

The clean-room implementation should prefer scoped/SAF access where practical and keep direct
filesystem access as an explicit compatibility mode.

## Package and emulator discovery

The reference host exposes installed-package discovery to the native frontend and declares package
visibility sufficient to discover emulator packages.

ES-DE-Plus should build a small typed bridge rather than passing unstructured strings wherever
possible. Discovery should return package ID, label, launchability and activity metadata needed by
the frontend.

## RetroArch core discovery

The reference package interoperates with RetroArch using these broadcast action names:

- `com.retroarch.QUERY_INSTALLED_CORES`
- `com.retroarch.INSTALLED_CORES_RESULT`

ES-DE-Plus can implement this public interoperability behavior independently and should treat the
response as optional: failure to query must never prevent a normal game launch.

## Multi-display launching

The reference package can select a target display when launching another Android activity. The
clean-room host should expose a native-to-Android API that accepts an optional display ID and uses
Android activity launch options when supported.

This is also the integration point for ES-DE Companion-style per-app and per-game
"This screen / Other screen" preferences.

## Native bridge surface

APK inspection shows the Android host provides native-facing operations in these broad groups:

- storage permission and directory validation;
- app-data/ROM directory getters and setters;
- SAF URI generation and decoding;
- directory listing and directory creation;
- installed-app and emulator checks;
- RetroArch core checks;
- device/network/battery status;
- window sizing;
- game/app launching;
- resource/theme/localization setup;
- configurator startup.

Names observed in the package are useful only as compatibility clues. ES-DE-Plus is free to design
a cleaner JNI/Kotlin API as long as the open C++ caller is updated with it.

## ES-DE Companion integration

ES-DE Companion is separately published under the MIT license. Its functionality can therefore be
integrated with attribution rather than reconstructed from the proprietary ES-DE Android host.

Initial integration targets:

1. secondary-display game/system artwork;
2. app drawer with instant app-name search;
3. per-app and per-game display targeting;
4. video and configurable overlay widgets;
5. game manual/guide access.

Device-specific features should remain capability-gated and optional.

## Clean-room rules

Contributors should follow these rules:

- Do not copy proprietary Java/Kotlin source or reconstructed decompiler output.
- Do not bypass, disable or reproduce payment, entitlement, signature or DRM checks.
- Use the APK only to document externally observable Android behavior and interoperability.
- Prefer Android SDK documentation and open-source ES-DE/SDL code when implementing behavior.
- Preserve the MIT notices for ES-DE and all incorporated MIT-licensed Companion code.
- Keep proprietary reference-package artifacts out of the repository.
