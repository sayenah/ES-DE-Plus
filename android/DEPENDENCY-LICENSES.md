<!-- SPDX-License-Identifier: MIT; ES-DE-Plus — written for ES-DE-Plus. -->

Android slice 1 intended dependency inventory. The dependency pipeline and APK
closure are not yet verified; actual shipment must be reconciled with ELF evidence.
APKs remain inside CI pending G-1/G-2.
Poppler and the upstream `ConvertPDF` implementation are GPL-2.0-only and are linked
in process on Android. This inventory records that fact and does not decide G-2.
No proprietary Android package or code is used.

| Component | Pin | License | Android configuration / packaging |
| --- | --- | --- | --- |
| ES-DE-Plus native frontend, bridge, overlay, host | PR revision | MIT | Clean-room host; shared `libmain.so` |
| ConvertPDF / es-pdf-convert | upstream 3.5.0 | GPL-2.0-only | Shared, linked in process |
| Poppler / poppler-cpp | 26.06.0 | GPL-2.0-only | CPP on; utilities, tests, Qt5/6, GLib, Boost, NSS3, GPGME, LCMS, curl off; Android font backend; TIFF/OpenJPEG enabled |
| FFmpeg | 8.1.1 (`n8.1.1`) | LGPL-2.1-or-later plus permissive notices | `--disable-gpl --disable-nonfree --disable-autodetect --disable-lzma --disable-doc --disable-programs --enable-shared --disable-static --enable-pic --enable-libdav1d --enable-zlib`; no GPL components |
| libiconv | 1.19 | LGPL-2.1-or-later (runtime) | `--enable-shared --disable-static`; host GPL utilities are not packaged |
| gettext / libintl | 1.0 | LGPL-2.1-or-later (runtime) | Runtime intl only; `--disable-java --disable-csharp --disable-openmp --disable-curses --disable-libasprintf --with-included-libxml --enable-shared --disable-static`; host `msgfmt` is not packaged |
| ICU | 78.3 | Unicode-3.0 / ICU | Static uc/i18n/data; `--enable-static --disable-shared --with-data-packaging=static --disable-tests --disable-samples --disable-extras --disable-icuio` |
| SDL2 and vendored SDL Java | 2.32.10 (`release-2.32.10`) | zlib | Shared SDL2; test/static targets off; Java implementations unchanged, tag LICENSE.txt notice prepended intact |
| OpenSSL crypto/ssl | 3.5.9 LTS | Apache-2.0 | Android target, API29, shared, no-tests, no-apps |
| curl | 8.22.0 | curl (MIT-like) | Shared; OpenSSL on; CLI/tests, libpsl, SSH/SSH2, nghttp2, brotli, zstd, c-ares off |
| FreeImage and its bundled codecs | 3.18.0 | FreeImage Public License or GPL-2.0; FIPL selected | Shared; `FREEIMAGE_EXPORTS NO_LCMS __ANSI__ HAVE_UNISTD_H DISABLE_PERF_MEASUREMENT PNG_ARM_NEON_OPT=0`; bundled codec notices recorded in `licenses/FreeImage-bundled-codecs`; C++11, source-specific `_byteswap_ulong=__builtin_bswap32` for JPEG XR segdec.c and `-include wchar.h` for JXRGlueJxr.c |
| FreeImage bundled JPEG, PNG, TIFF, ZLib, OpenJPEG, OpenEXR, LibRawLite, LibWebP, LibJXR | JPEG 9c, PNG 1.6.35, TIFF 4.0.9, zlib 1.2.11, OpenJPEG 2.0.0, OpenEXR/IlmBase 2.2.0, LibRaw 0.19.0, WebP 1.0.0, JPEG XR 1.1 | IJG/BSD/zlib/MIT; LibRaw LGPL-2.1-or-later or CDDL-1.0 | Static within FreeImage; `licenses/FreeImage-bundled-codecs` preserves the codec notices; LibRaw LGPL-2.1 selected; no LCMS |
| libpng | 1.6.58 | libpng-2.0 | Shared; tests/tools off |
| HarfBuzz | 14.2.1 | MIT | Shared; subset, ICU, FreeType integration off |
| FreeType | 2.14.3 | FTL or GPL-2.0; FTL selected | Shared; HarfBuzz, bzip2, brotli off |
| zstd | 1.5.7 | BSD-3-Clause or GPL-2.0; BSD selected | Shared; programs/tests/static off |
| libjpeg-turbo | 3.1.4.1 | BSD-3-Clause / IJG / zlib | Shared; turbojpeg/static off |
| libtiff | 4.7.1 | libtiff (BSD-like) | Shared; tools/tests/docs/contrib/webp/lzma/jbig/lerc off |
| OpenJPEG | 2.5.4 | BSD-2-Clause | Shared; codec/tests off |
| libgit2 | 1.9.4 | GPL-2.0 with linking exception | Shared; tests/CLI/SSH off, HTTPS OpenSSL, NDK zlib; linking exception retained |
| pugixml | 1.15 | MIT | Static |
| Ogg | 1.3.6 | BSD-3-Clause | Shared; tests off |
| dav1d | 1.5.3 | BSD-2-Clause | Shared; tools/tests off |
| LunaSVG / plutovg | tracked subtree, LunaSVG 3.5.0 | MIT | Static; upstream CMake configuration |
| rlottie | tracked subtree | MIT | Static; threading/modules off by upstream CMake |
| GLM, RapidJSON, utfcpp, CImg | tracked subtree revisions | MIT; CImg CeCILL-C/CeCILL terms | Header-only native dependencies, existing notices |
| libc++_shared | NDK 27.3.13750724 | Apache-2.0 with LLVM exception | Shared; NDK copy, API29 |
| Kotlin stdlib | 2.2.21 | Apache-2.0 | Kotlin host compiler/runtime |
| Bundled fonts, theme, icons, sounds and CA certificates | tracked resources and linear-es-de | Existing per-asset licenses | Existing `licenses/` notices apply; Android placeholder splash/icon are original MIT assets |

Build-only: AGP **8.13.2**, Gradle wrapper **8.13**, Kotlin plugin **2.2.21**,
JDK **17**, NDK **27.3.13750724**, minSdk **29**, compile/targetSdk **36**,
SDK CMake **3.31.5**, clang-format **18.1.8**. Gradle's wrapper JAR is vendored from
`gradle/gradle` tag `v8.13.0`, Apache-2.0 (`licenses/Gradle`).
All non-CMake shared link commands pass both `-z max-page-size=16384` and
`-z common-page-size=16384`; CMake uses `ANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON`.
Android system libraries (bionic, zlib, log, Android, EGL/GLES, OpenSL ES/AAudio)
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
