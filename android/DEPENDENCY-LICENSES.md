<!-- SPDX-License-Identifier: MIT; ES-DE-Plus — written for ES-DE-Plus. -->

Android slice 1 dependency inventory, reconciled against the actual APK ELF list
for both ABIs at `7645fd5e7` in
[CI run 37760868837](https://github.com/sayenah/ES-DE-Plus/actions/runs/37760868837).
Architecture, API notes, SONAME closure and LOAD alignment pass; the RELRO check
fails on the unmodified NDK libc++ for both ABIs. This is not a green build report.
APKs remain inside CI pending G-1/G-2.
Poppler and the upstream `ConvertPDF` implementation are GPL-2.0-only and are linked
in process on Android. This inventory records that fact and does not decide G-2.
No proprietary Android package or code is used.

The APK contains these 34 shared-library entries for each ABI (the component table
below gives versions, licences and configuration). The `libpng.so` install-time
alias is excluded; every runtime consumer requests the packaged `libpng16.so`.

| Component | Packaged entries |
| --- | --- |
| Frontend | `libmain.so` |
| ConvertPDF | `libes-pdf-convert.so` |
| SDL2 | `libSDL2.so` |
| Poppler | `libpoppler.so`, `libpoppler-cpp.so` |
| FFmpeg | `libavcodec.so`, `libavdevice.so`, `libavfilter.so`, `libavformat.so`, `libavutil.so`, `libswresample.so`, `libswscale.so` |
| libiconv / bundled libcharset | `libiconv.so`, `libcharset.so` |
| gettext runtime | `libintl.so` |
| FreeImage | `libfreeimage.so` |
| FreeType | `libfreetype.so` |
| HarfBuzz | `libharfbuzz.so`, `libharfbuzz-gpu.so`, `libharfbuzz-raster.so`, `libharfbuzz-vector.so` |
| libgit2 | `libgit2.so` |
| curl | `libcurl.so` |
| OpenSSL | `libcrypto.so`, `libssl.so` |
| libjpeg-turbo | `libjpeg.so` |
| libpng | `libpng16.so` |
| libtiff | `libtiff.so`, `libtiffxx.so` |
| OpenJPEG | `libopenjp2.so` |
| zstd | `libzstd.so` |
| Ogg | `libogg.so` |
| dav1d | `libdav1d.so` |
| NDK C++ runtime | `libc++_shared.so` |

ICU, pugixml, LunaSVG/plutovg and rlottie are static consumer inputs, not separate
APK entries; the CI `native-outputs.txt` records the actual Ninja link commands.
Kotlin stdlib and its implicit JetBrains annotations dependency appear in dex;
the identity audit records their packaged classes.

Unresolved alignment evidence: NDK 27.3 libc++ has 16 KiB LOAD alignment, but its
RELRO end is `0x143000` (arm64-v8a) / `0x139000` (x86_64), neither divisible by
`0x4000`. The audit retains Android's documented RELRO check and exits with failure.
Changing the pinned toolchain or deciding an alternative runtime/audit requires
Fable's resolution; no binary is patched or substituted to manufacture a pass.

| Component | Pin | License | Android configuration / packaging |
| --- | --- | --- | --- |
| ES-DE-Plus native frontend, bridge, overlay, host | PR revision | MIT | Clean-room host; shared `libmain.so` |
| ConvertPDF / es-pdf-convert | upstream 3.5.0 | GPL-2.0-only | Shared, linked in process |
| Poppler / poppler-cpp | 26.06.0 | GPL-2.0-only | `-DENABLE_UNSTABLE_API_ABI_HEADERS=ON -DENABLE_CPP=ON -DENABLE_UTILS=OFF -DENABLE_QT5=OFF -DENABLE_QT6=OFF -DENABLE_GLIB=OFF -DENABLE_BOOST=OFF -DENABLE_NSS3=OFF -DENABLE_GPGME=OFF -DENABLE_LCMS=OFF -DENABLE_LIBCURL=OFF -DENABLE_LIBTIFF=ON -DENABLE_LIBOPENJPEG=openjpeg2 -DFONT_CONFIGURATION=android -DBUILD_CPP_TESTS=OFF -DBUILD_MANUAL_TESTS=OFF -DBUILD_GTK_TESTS=OFF -DRUN_GPERF_IF_PRESENT=OFF` |
| FFmpeg | 8.1.1 (`n8.1.1`) | LGPL-2.1-or-later plus permissive notices | `--disable-gpl --disable-nonfree --disable-autodetect --disable-lzma --disable-doc --disable-programs --enable-shared --disable-static --enable-pic --enable-libdav1d --enable-zlib`; no GPL components |
| libiconv | 1.19 | LGPL-2.1-or-later (runtime) | `--enable-shared --disable-static`; host GPL utilities are not packaged |
| libcharset (bundled with libiconv) | 1.5 within libiconv 1.19 | LGPL-2.1-or-later | Shared `libcharset.so`; same libiconv configure command and existing `licenses/libiconv` terms |
| gettext / libintl | 1.0 | LGPL-2.1-or-later (runtime) | Runtime intl only; `--disable-java --disable-csharp --disable-openmp --disable-curses --disable-libasprintf --with-included-libxml --with-libiconv-prefix=<ABI-prefix> --enable-shared --disable-static`; host `msgfmt` is not packaged |
| ICU | 78.3 | Unicode-3.0 / ICU | Static uc/i18n/data; `--with-cross-build=<host-ICU-build> --enable-static --disable-shared --with-data-packaging=static --disable-tests --disable-samples --disable-extras --disable-icuio` |
| SDL2 and vendored SDL Java | 2.32.10 (`release-2.32.10`) | zlib | Shared SDL2; test/static targets off; Java implementations unchanged, tag LICENSE.txt notice prepended intact |
| OpenSSL crypto/ssl | 3.5.9 LTS | Apache-2.0 | Android target, API29, shared, no-tests, no-apps |
| curl | 8.22.0 | curl (MIT-like) | Shared; OpenSSL on; CLI/tests, libpsl, SSH/SSH2, nghttp2, brotli, zstd, c-ares off |
| FreeImage and its bundled codecs | 3.18.0 | FreeImage Public License or GPL-2.0; FIPL selected | Shared; `FREEIMAGE_EXPORTS NO_LCMS __ANSI__ HAVE_UNISTD_H DISABLE_PERF_MEASUREMENT PNG_ARM_NEON_OPT=0`; bundled codec notices recorded in `licenses/FreeImage-bundled-codecs`; C++11, source-specific `_byteswap_ulong=__builtin_bswap32` for JPEG XR segdec.c and `-include wchar.h` for JXRGlueJxr.c |
| FreeImage bundled JPEG, PNG, TIFF, ZLib, OpenJPEG, OpenEXR, LibRawLite, LibWebP, LibJXR | JPEG 9c, PNG 1.6.35, TIFF 4.0.9, zlib 1.2.11, OpenJPEG 2.0.0, OpenEXR/IlmBase 2.2.0, LibRaw 0.19.0, WebP 1.0.0, JPEG XR 1.1 | IJG/BSD/zlib/MIT; LibRaw LGPL-2.1-or-later or CDDL-1.0 | Static within FreeImage; `licenses/FreeImage-bundled-codecs` preserves the codec notices; LibRaw LGPL-2.1 selected; no LCMS |
| libpng | 1.6.58 | libpng-2.0 | Shared; tests/tools off |
| HarfBuzz | 14.2.1 | MIT | Shared core, GPU, raster and vector libraries; subset, ICU, FreeType integration off |
| FreeType | 2.14.3 | FTL or GPL-2.0; FTL selected | Shared; HarfBuzz, bzip2, brotli off |
| zstd | 1.5.7 | BSD-3-Clause or GPL-2.0; BSD selected | Shared; programs/tests/static off |
| libjpeg-turbo | 3.1.4.1 | BSD-3-Clause / IJG / zlib | Shared; turbojpeg/static off |
| libtiff | 4.7.1 | libtiff (BSD-like) | Shared; tools/tests/docs/contrib/webp/lzma/jbig/lerc off |
| OpenJPEG | 2.5.4 | BSD-2-Clause | Shared; codec/tests off |
| libgit2 | 1.9.4 | GPL-2.0 with linking exception | `-DBUILD_SHARED_LIBS=ON -DBUILD_TESTS=OFF -DBUILD_CLI=OFF -DUSE_SSH=OFF -DUSE_HTTPS=OpenSSL -DUSE_BUNDLED_ZLIB=OFF -DUSE_THREADS=ON`; linking exception retained |
| pugixml | 1.15 | MIT | Static |
| Ogg | 1.3.6 | BSD-3-Clause | Shared; tests off |
| dav1d | 1.5.3 | BSD-2-Clause | Shared; tools/tests off |
| LunaSVG / plutovg | 3.5.0 / 1.3.2 (tracked subtree) | MIT | Static; upstream CMake configuration |
| rlottie | 0.2 (tracked subtree) | MIT | Static; threading/modules off by upstream CMake |
| GLM, RapidJSON, utfcpp, CImg | 1.0.0, 1.1.0, 4.0.6, 3.6.1 (tracked subtrees) | MIT; CImg CeCILL-C/CeCILL terms | Header-only native dependencies, existing notices; CImg’s CeCILL-C option applies |
| libc++_shared | NDK 27.3.13750724 | Apache-2.0 with LLVM exception | Shared; unmodified NDK copy, Android API note 21 (compatible with minSdk 29); RELRO alignment check fails on both ABIs, recorded below |
| Kotlin stdlib | 2.2.21 | Apache-2.0 | Kotlin host runtime; `licenses/Kotlin` |
| JetBrains annotations (implicit Kotlin stdlib runtime dependency) | 13.0 | Apache-2.0 | Provided by Kotlin’s published runtime dependency graph; no explicit dependency declaration; canonical terms in `licenses/Kotlin` |
| Bundled fonts, theme, icons, sounds and CA certificates | tracked resources and linear-es-de | Existing per-asset licenses | Existing `licenses/` notices apply; Android placeholder splash/icon are original MIT assets |

Build-only: AGP **8.13.2**, Gradle wrapper **8.13**, Kotlin plugin **2.2.21**,
JDK **17**, NDK **27.3.13750724**, minSdk **29**, compile/targetSdk **36**,
SDK CMake **3.31.5**, clang-format **18.1.3** (Ubuntu `1:18.1.3-1ubuntu1`). Gradle's wrapper JAR is vendored from
`gradle/gradle` tag `v8.13.0`, Apache-2.0 (`licenses/Gradle`).
All dependency shared link commands pass both `-z max-page-size=16384` and
`-z common-page-size=16384`; CMake additionally uses `ANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON`; the host also passes both
page-size linker flags for SHARED and MODULE targets (including RELRO alignment).
Android system libraries (bionic, zlib, log, Android, EGL/GLES, OpenSL ES/AAudio, NDK camera/media)
are device-provided and are not bundled.

Primary pin/toolchain sources:
[AGP compatibility table](https://developer.android.com/build/releases/agp-8-13-0-release-notes),
[Kotlin Gradle compatibility](https://kotlinlang.org/docs/gradle-configure-project.html),
[OpenSSL releases](https://openssl-library.org/source/),
[curl releases](https://curl.se/download.html),
[Android 16 KiB requirements](https://developer.android.com/guide/practices/page-sizes).
Dependency pins other than OpenSSL/curl come from D-001(d) and the public upstream
`tools/macOS_dependencies_setup.sh`. Only host downloads and per-ABI installs are
cached; tracked `external/` trees are never cache inputs or outputs.

Upstream interoperability literals (D-002 am. 1):
`es-app/src/guis/GuiGameImporter.cpp:814,893` use
`org.es_de.frontend.desktop` to exclude upstream's Linux desktop shortcut from
import. They remain unchanged and may appear in `libmain.so` read-only data;
they do not define the ES-DE-Plus application identity. The identifier audit
excludes only these upstream native literals, never manifest/resources/dex or
the host's own code.

Configuration templates used by the scripts: Autoconf commands also pass
`--host=<ABI-triple> --prefix=<ABI-prefix>`. FFmpeg additionally passes
`--prefix=<ABI-prefix> --target-os=android --arch=<aarch64|x86_64>`
`--cpu=<armv8-a|x86-64> --enable-cross-compile --cc=<API29-clang>`
`--cxx=<API29-clang++> --ar=<llvm-ar> --ranlib=<llvm-ranlib>`
`--strip=<llvm-strip> --pkg-config=pkg-config --extra-cflags=-I<ABI-prefix>/include`
and `--extra-ldflags=-L<ABI-prefix>/lib <16-KiB-linker-flags>`.
Every CMake dependency command uses the NDK toolchain, `ANDROID_PLATFORM=android-29`,
`ANDROID_STL=c++_shared`, `ANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON`, Release,
position-independent code, the per-ABI install prefix/root, and unversioned Android
SONAMEs. The scripts are the executable record of the complete commands.
