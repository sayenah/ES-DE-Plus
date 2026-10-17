<!-- SPDX-License-Identifier: MIT; ES-DE-Plus — written for ES-DE-Plus. D-011 notes template. -->
Test build of the open-source ES-DE-Plus Android app from `main` at `@SHA@`,
[CI run @RUN@, originating attempt @ATTEMPT@](https://github.com/sayenah/ES-DE-Plus/actions/runs/@RUN@/attempts/@ATTEMPT@).
Version: `@VERSION@`, Android version code **@CODE@**.

**Install:** download `@APK@` on Android 12 / API 31 or newer (arm64 phones,
tablets and TV boxes; x86_64 emulators). Published test builds now use one stable
**test** key. When moving from the older throwaway-key builds, back up and
uninstall once: uninstall deletes app-owned ROMs, settings, collections, media
and logs. ROMs in a selected shared folder survive. Subsequent higher-version
stable-key test builds install in place and keep app data. A build signed with
your own key requires a separate uninstall. This is a debug test build; release
signing requires a separate Founder decision.

**What works:** first-run storage setup, system and game views, global search,
Intent/RetroArch launching, Android-app import, PDF manuals, TV and HOME entry.

**Untested/limitations:** game launching has CI emulator evidence, not real
hardware coverage. Bluetooth/Wi-Fi/cellular/battery indicators are placeholders;
other-screen launching and SAF import into app-owned ROMs are deferred. PDF
rendering runs in process and visited-page memory is unbounded until close.
Consult the originating run and open issues for device or lifecycle limitations.

**Licences and source:** ES-DE-Plus's own source is MIT. The APK includes
permissive, Apache-2.0 and LGPL-2.1 components, libgit2 (GPL-2.0 with linking
exception), and the GPL-2.0-or-later scanline shader shipped as source.
FreeImage FIPL, FreeType FTL and CImg CeCILL-C are selected; LibRaw's LGPL-2.1
option is selected. Fonts, sounds, themes and certificates retain their own
licences, including Debian's patched GNU FreeFont (GPL-3.0) and the MPL-2.0
Mozilla CA bundle. `@LICENCES@` carries the preserved notices and manifest;
`@SOURCE@` carries the exact repository snapshot, third-party source archives,
Debian font patches and build/relink recipes. GitHub's generated source ZIP/tar
snapshots omit those archives and do not replace this source bundle. CI never
prunes releases, tags or source bundles; this is a pre-release, never latest.

**Verification:** `SHA256SUMS.txt` lists the three downloadable payload hashes.
APK SHA-256: `@HASH@`.
Single signer certificate SHA-256: `@CERT@`.
Verify using SDK `apksigner verify --verbose --print-certs @APK@`.
