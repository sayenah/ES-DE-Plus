<!-- SPDX-License-Identifier: MIT. ES-DE-Plus front page; the upstream ES-DE README stays untouched at the repository root. -->

<p align="center">
  <img src="/.github/assets/banner.svg" alt="ES-DE Plus — an open-source Android home for your game collection" width="100%">
</p>

<p align="center">
  <a href="https://github.com/sayenah/ES-DE-Plus/actions/workflows/build-android.yml"><img alt="Android build" src="https://github.com/sayenah/ES-DE-Plus/actions/workflows/build-android.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/sayenah/ES-DE-Plus/actions/workflows/build-linux.yml"><img alt="Linux build" src="https://github.com/sayenah/ES-DE-Plus/actions/workflows/build-linux.yml/badge.svg?branch=main"></a>
  <a href="/LICENSE"><img alt="Source licence: MIT" src="https://img.shields.io/badge/source-MIT-8b7bff"></a>
  <img alt="Android 10 and later" src="https://img.shields.io/badge/Android-10%2B-2ee6c5">
  <img alt="Phone, TV and home screen" src="https://img.shields.io/badge/phone%20%C2%B7%20TV%20%C2%B7%20home%20screen-ff6fa8">
</p>

<p align="center"><b>Your whole game library, one beautiful controller-friendly front end — on Android, open source, top to bottom.</b></p>

---

## ✨ What is ES-DE Plus?

[ES-DE](https://es-de.org) (EmulationStation Desktop Edition) is a much-loved front end for browsing and launching games from your multi-platform collection. Its C++ core is open source, but its Android app is a closed, paid product.

**ES-DE Plus is an independent fork that builds the missing piece in the open:** a clean-room, fully open-source Android app around the ES-DE core, under its own name and identity — and then adds the features upstream won't take.

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>📱 Truly open Android</h3>
      A new Android host and native bridge written from public documentation and the open C++ call sites — nothing copied from the proprietary app.
    </td>
    <td width="33%" valign="top">
      <h3>🔎 Search every system</h3>
      Type once and find a game across your entire collection, with a controller-friendly on-screen keyboard. Press <kbd>A</kbd> to play.
    </td>
    <td width="33%" valign="top">
      <h3>🎮 Launch into your emulators</h3>
      Finds the emulators you have installed and hands each game over the way its emulator expects — file path, storage link or a temporary read-only share.
    </td>
  </tr>
  <tr>
    <td width="33%" valign="top">
      <h3>📺 Phone, TV or home screen</h3>
      Runs as a normal app, as your Android TV app, or as your device's home screen — one instance, whichever way you enter.
    </td>
    <td width="33%" valign="top">
      <h3>🗂️ Your storage, your choice</h3>
      A first-run setup lets you keep games in the app's own folder or, explicitly, in a shared folder you pick — with real access checks, never silent fallbacks.
    </td>
    <td width="33%" valign="top">
      <h3>📖 Game manuals</h3>
      PDF manuals open right in the front end, drawn by Android's own built-in renderer.
    </td>
  </tr>
</table>

<p align="center">
  <img src="/.github/assets/tv-global-search.png" alt="Global search results on an Android TV emulator" width="70%"><br>
  <sub>Global search running on an Android TV emulator in our automated test suite (the "smoke" games are test fixtures).</sub>
</p>

## 🗺️ Where we are

| Status | Milestone |
|:-:|---|
| ✅ | **Android build pipeline** — the open C++ frontend, the native bridge and every dependency built in CI from pinned, checksum-verified sources, for `arm64-v8a` and `x86_64` |
| ✅ | **First-run setup** — storage choice, permissions, phone / TV / home-screen entry points |
| ✅ | **Game launching** — emulator discovery, Intent launching, Android-app importer, optional RetroArch core check |
| ✅ | **PDF manuals** through Android's built-in renderer |
| ✅ | **Downloadable test APKs** from every green build on `main`, each with a matching source bundle |
| 🧭 | **[ES-DE Companion](https://github.com/RobZombie9043/es-de-companion) features** — second-screen artwork, app drawer, per-game display targeting and more — *[planned (#3)](https://github.com/sayenah/ES-DE-Plus/issues/3)* |
| 🧭 | **Signed releases** — *planned* |

Every Android change is built and tested on three emulator images — **Android 10**, **Android 14** and **Android TV** — driving the real screens, before it can merge.

## 📦 Get it

**Android.** For now you need a controller, gamepad-style handheld controls or a keyboard: the on-screen touch controls are not built yet, so a touch-only phone cannot get past the first screens. Download the latest test APK from **[Releases](https://github.com/sayenah/ES-DE-Plus/releases)**, next to the source bundle it was built from and its licence notices. Newer builds between releases are on **[Actions → Build Android](https://github.com/sayenah/ES-DE-Plus/actions/workflows/build-android.yml?query=branch%3Amain)** as `es-de-plus-debug-apk-…` artifacts (signed-in GitHub users only; kept 7 days). These are test builds signed with a throwaway key per build, so installing a newer one means uninstalling the old one first — back up first, because uninstalling deletes the app's own data.

**Desktop.** ES-DE Plus keeps upstream's Linux, macOS and Windows builds (with global search added). Build from source with [INSTALL.md](/INSTALL.md); Linux is built on every change in CI.

## ⚖️ Clean room and licensing

- **Clean room.** Nothing in this repository comes from the proprietary ES-DE Android app or from decompiling it; its observable behaviour is documented in [`docs/ANDROID-CLEAN-ROOM.md`](/docs/ANDROID-CLEAN-ROOM.md) and everything is implemented from public sources. No payment or licence check is bypassed.
- **Source.** ES-DE Plus's own source is **MIT**, like upstream ES-DE.
- **Android app.** Apart from libgit2 (which carries a linking exception) and one RetroArch-derived scanline shader shipped as its own source under GPL-2.0-or-later, the APK's code contains no GPL code; it includes LGPL-2.1 libraries (FFmpeg built without GPL parts, libiconv, libintl, and LibRaw inside FreeImage, under LGPL-2.1 or CDDL-1.0) plus permissive, Apache-2.0, FreeImage (FIPL) and CImg (CeCILL-C) components. Bundled fonts, sounds, themes and certificates keep their own licences — for example the GNU FreeFont font (Debian's patched build) is GPL-3.0, and its source is in the matching source bundle. Every licence text ships with each download, and the full inventory is in [`android/DEPENDENCY-LICENSES.md`](/android/DEPENDENCY-LICENSES.md).
- **Identity.** ES-DE Plus uses its own application ID (`org.esdeplus.frontend`), name and icon, and is **not affiliated with or endorsed by the ES-DE project**. If you want the official ES-DE for Android, please support its developer via [es-de.org](https://es-de.org).

## 💜 Thanks

ES-DE Plus stands on the shoulders of [ES-DE](https://gitlab.com/es-de/emulationstation-de) by Leon Styhre and its contributors, [SDL](https://www.libsdl.org), and everyone listed in [CREDITS.md](/CREDITS.md). Upstream's own README — with its full feature tour — is kept unchanged at [`README.md`](/README.md).

## 📚 Learn more

| For | Read |
|---|---|
| Using the front end | [User guide](/USERGUIDE.md) · [FAQ](/FAQ.md) |
| The Android app | [`android/README.md`](/android/README.md) · [clean-room design](/docs/ANDROID-CLEAN-ROOM.md) |
| Building from source | [INSTALL.md](/INSTALL.md) |
| Themes | [THEMES.md](/THEMES.md) |
