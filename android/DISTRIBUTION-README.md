<!-- SPDX-License-Identifier: MIT; ES-DE-Plus — written for ES-DE-Plus. -->
# ES-DE Plus CI debug distribution

This directory contains the exact debug APK built, audited and smoked on API 34.
`manifest.json` records its SHA256, Android Debug certificate fingerprint, full
source commit, run and attempt, both ABIs, the dependency-cache key/hit state
and the complete source-input mapping. Tool versions describe the current runner;
a cache hit identifies restored dependency outputs.
Verify the APK with SDK `apksigner verify --print-certs app-debug.apk` and
`aapt2 dump badging app-debug.apk`; its identity is `org.esdeplus.frontend`,
display name **ES-DE Plus**, with `arm64-v8a` and `x86_64` only.

Download **@SOURCE_NAME@** from [the same CI run](@RUN_URL@).
Save that source artefact alongside the APK: CI retains source for 14 days and
the APK for 7 days. Attempt-specific artefacts are never overwritten or deleted
by this workflow. If manually removing artefacts, remove the dependent APK
first; never delete its source while the APK remains available. The workflow
cannot prevent an administrator deleting an artefact independently.

ES-DE-Plus's own source is MIT. Apart from libgit2 under GPL-2.0 with its
linking exception and the RetroArch-derived scanline shader
`resources/shaders/glsl/scanlines.glsl` under GPL-2.0-or-later, the APK's code
contains no GPL code. The shader ships as its own source text and is compiled
by the GPU driver at runtime; that file is also in `repository.tar.gz`. The APK
also includes permissive and Apache-2.0 inputs and LGPL-2.1 shared libraries.
FreeImage offers FIPL, GPL-2.0 or GPL-3.0 (FIPL selected), FreeType's FTL and
CImg's CeCILL-C options are selected. LibRaw inside FreeImage offers LGPL-2.1 or
CDDL-1.0; LGPL-2.1 selected. Bundled fonts, sounds, themes and certificates keep
their own licences, including Debian's patched GNU FreeFont (patch series in the manifest; GPL-3.0). See
`DEPENDENCY-LICENSES.md`, `licenses/`, `CREDITS.md` and `LICENSE` for preserved notices.
FreeImage and its uncombined LibRaw source are in `archives/freeimage.zip`;
CImg and its licence are in `repository.tar.gz`. FreeMono.ttf is Debian's
patched GNU FreeFont 20120503 (fonts-freefont 20120503-10; patch series in the
manifest), including `drop_bad_braille.diff`. Its corresponding source is
`archives/fonts-freefont_20120503.orig.tar.xz` plus
`archives/fonts-freefont_20120503-10.debian.tar.xz`, including Debian patches
and build recipes, plus the preserved signed source descriptor
`archives/fonts-freefont_20120503-10.dsc` (SHA256-pinned; its source checksums
are checked offline, without claiming a fresh PGP trust verification).
The declared verification input
`archives/fonts-freefont-ttf_20120503-10_all.deb` allows offline table-by-table
comparison with Debian's binary FreeMono.ttf. The manifest pins the official
Debian pool and immutable `snapshot.debian.org` fallback URLs and SHA256 values,
and maps the bundled font to the sources;
only FontForge timestamp/checksum fields may differ, and a changed table fails.
These inputs use the pinned download cache and are fetched in CI only. ES-DE-Plus
applies no native source patches; the font already carries Debian's changes.
Their source and recipients' rights remain under those component terms.
The Mozilla-derived CA bundle `resources/certificates/curl-ca-bundle.crt` is
MPL-2.0; its unmodified PEM source is in `repository.tar.gz`. Attribution,
source locations and the MPL-2.0 text are in `licenses/Mozilla-CA-bundle`.
CeCILL-C's warranty and liability limitations in Articles 8 and 9 apply;
software is supplied without warranty.

To rebuild or relink with modified LGPL components, extract `repository.tar.gz`
into an empty directory. On Ubuntu 24.04 install JDK 17, Python 3.12+, Git,
build-essential, gettext, nasm, yasm, ninja-build, meson, pkg-config, autoconf,
automake and libtool. Install Android SDK platform 36, build-tools 36.0.0,
NDK **28.2.13676358** and SDK CMake **3.31.5** with `sdkmanager`. Set
`ANDROID_HOME`, `ANDROID_NDK_HOME` and put the SDK CMake bin directory on `PATH`.
The included wrapper selects Gradle 8.13, AGP 8.13.2 and Kotlin 2.2.21; it downloads
these build tools and their Maven inputs, which are not native dependency caches.
From the extracted repository run:

```sh
bash android/rebuild-source.sh /absolute/path/to/extracted-source-artefact
```

This verifies every source archive before extraction, rejects unknown inputs,
builds both ABIs without checkout or dependency caches, and produces debug and
unsigned release APKs locally. For a modified LGPL library, preserve an original
source bundle, run source verification first, then edit the extracted component
in `android/.deps/sources/`. Remove the generated `android/.deps/build/`,
`android/.deps/install/`, `android/libs/`, `android/app/.cxx/` and Android module
build directories, preserving `android/.deps/sources/` and the source archives.
Rebuild the complete audited dependency graph with
`tools/Android_dependencies_build.sh <ABI>` for each ABI. This rebuilds the shared
library and dependent native inputs; for LibRaw edits it rebuilds FreeImage with
the bundled uncombined LibRaw. Run setup again for generated include links, then
`cd android && ./gradlew --no-daemon clean :app:assembleRelease` to relink and
repackage. Source edits intentionally invalidate the original no-patches/hash
attestation; a modified binary is your own build. Full source and build recipes
are provided so recipients can modify and relink these components. Reverse
engineering for debugging such modifications is permitted.

Sign your rebuilt unsigned release APK with your own key using SDK `apksigner`
(after SDK `zipalign` if repackaging). Keep that key private and outside the
source/distribution directory. This workflow provides no signing key. The CI
debug key is throwaway and differs between runs: these APKs cannot update one
another. Back up before uninstalling: app-owned ROMs, settings, collections,
media and logs are deleted. ROM files in a selected shared directory survive;
application settings do not. Android may reject installing a build signed with
your key over the CI build, so back up and uninstall the CI build first.
