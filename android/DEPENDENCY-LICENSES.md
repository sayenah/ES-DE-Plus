<!-- SPDX-License-Identifier: MIT; ES-DE-Plus — written for ES-DE-Plus. -->

Android slice 1 dependency inventory. The APK ELF lists, actual static consumer
link inputs and final-toolchain CI evidence are attached to
[PR #4](https://github.com/sayenah/ES-DE-Plus/pull/4).
The toolchain remains NDK 28.2.13676358 under D-001(b) am. 2. Architecture,
API notes and SONAME closure are checked for every packaged library. Libraries
ES-DE-Plus builds retain strict 16 KiB LOAD alignment and the RELRO-end formula.
NDK-supplied prebuilts are identified by the NDK file's SHA256 (raw or identically
AGP-stripped), and checked by LOAD alignment plus actual APK zipalign; their
measured RELRO values are printed and recorded below. An unmatched file follows
the strict rule regardless of its filename.
D-007 and D-007 am. 1: the Android APK composition is MIT + permissive
(FreeImage FIPL, FreeType FTL and CImg CeCILL-C selections) + Apache-2.0 +
LGPL-2.1 shared libraries + libgit2 (GPL-2.0 with its linking exception).
No GPL code without a linking exception enters the Android build. PDF rendering
uses the Android platform; upstream's GPL converter and Poppler remain desktop/iOS
inputs only. APK publication and the accompanying exact third-party source
artefact belong to PR #6 after PR-D; PR-D uploads evidence only.
No proprietary Android package or code is used.

The APK contains these 21 shared-library entries for each ABI (the component table
below gives versions, licences and configuration). Packaging starts from the Android CMake link list plus the NDK runtime,
then follows recursive non-system DT_NEEDED entries. Unreachable libraries and
install-time aliases are excluded; every PNG consumer requests `libpng16.so`.
`libavdevice`, `libcharset`, HarfBuzz GPU/raster/vector and Ogg are
built under the same dependency configuration but are not packaged.

| Component | Packaged entries |
| --- | --- |
| Frontend | `libmain.so` |
| ConvertPDF | `libes-pdf-convert.so` |
| SDL2 | `libSDL2.so` |
| FFmpeg | `libavcodec.so`, `libavfilter.so`, `libavformat.so`, `libavutil.so`, `libswresample.so`, `libswscale.so` |
| libiconv | `libiconv.so` |
| gettext runtime | `libintl.so` |
| FreeImage | `libfreeimage.so` |
| FreeType | `libfreetype.so` |
| HarfBuzz | `libharfbuzz.so` |
| libgit2 | `libgit2.so` |
| curl | `libcurl.so` |
| OpenSSL | `libcrypto.so`, `libssl.so` |
| libpng | `libpng16.so` |
| dav1d | `libdav1d.so` |
| NDK C++ runtime | `libc++_shared.so` |

ICU, pugixml, LunaSVG/plutovg and rlottie are static consumer inputs, not separate
APK entries; NDK compiler support (including libatomic) comes from the same
Apache-2.0/LLVM-exception toolchain. The CI `native-outputs.txt` records the actual Ninja link commands.
`android/license-inputs.py` checks actual compile databases, Ninja header dependencies,
compiler depfiles and static/shared link commands, with actual compiler/archive
invocations from Make-based builds recorded by
`android/license-tool.py`; OpenSSL's full static libraries and ICU's `libicutu.a`
and `libicutest.a` tool-support archives are build-only, never packaged. OpenSSL's
provider convenience archives (`libcommon.a`, `libdefault.a`, `liblegacy.a`,
`libtemplate.a`) use the same Apache-2.0 terms; gettext's runtime convenience
archive `libgnu.a` uses the same LGPL runtime terms. libiconv's GPL CLI/src/srclib
targets are not built; the input audit rejects those paths.
The generated target graph also contains libpng's static `libpng16.a`, FFmpeg's
unused `libavdevice.so`, dav1d's `libdav1d_input.a` tool archive, and OpenSSL's
`capi.so`, `dasync.so`, `loader_attic.so`, `ossltest.so`, `padlock.so`, and
`legacy.so` modules. These are build-only inputs under their parent component's
reviewed licence and are excluded from the APK closure. dav1d's 8/16-bit static
convenience archives are internal BSD-2-Clause inputs to its shared library.
Graphs are retained with each ABI install and audited again on cache restores. Unknown source/header,
library, dex dependency or APK entries are rejected; forbidden-header/library and
unknown-input positive controls exercise the same gates. `auditRuntimeLicences`
checks Gradle's resolved debug/release runtime artifacts, and `check-identity.py`
checks actual dex classes using the R8 mapping for minified names.

Closure evidence from [PR-C's run](https://github.com/sayenah/ES-DE-Plus/actions/runs/38058077314):
only Poppler/TIFF consumed the standalone JPEG, TIFF, OpenJPEG and zstd libraries
(other than the explicit JPEG link removed with Poppler). They leave setup/build,
packaging and the inventory. FreeType still consumes libpng; FreeImage's bundled
JPEG/PNG/TIFF/OpenJPEG/etc. remain inside FreeImage under their reviewed notices.
Desktop `licenses/` is unchanged. The new cache key excludes old Poppler installs.

Kotlin stdlib and its implicit JetBrains annotations dependency appear in dex;
the identity audit records their packaged classes.

| Component | Pin | License | Android configuration / packaging |
| --- | --- | --- | --- |
| ES-DE-Plus native frontend, bridge, overlay, host | PR revision | MIT | Clean-room host; shared `libmain.so` |
| Android ConvertPDF / es-pdf-convert | PR-D revision | MIT | Written for ES-DE-Plus; platform PdfRenderer via two MainActivity JNI delegates, filesystem paths only, no renderer cache |
| FFmpeg | 8.1.1 (`n8.1.1`) | LGPL-2.1-or-later plus permissive notices | `--disable-gpl --disable-nonfree --disable-autodetect --disable-lzma --disable-doc --disable-programs --enable-shared --disable-static --enable-pic --enable-libdav1d --enable-zlib`; no GPL components |
| libiconv | 1.19 | LGPL-2.1-or-later (runtime) | `--enable-shared --disable-static`; only lib/libcharset library targets built and installed, generated iconv.h installed explicitly; unused GPL CLI/src/srclib targets are not built |
| libcharset (bundled with libiconv) | 1.5 within libiconv 1.19 | LGPL-2.1-or-later | Build-only `libcharset.so`, not packaged; same libiconv configure command and existing `licenses/libiconv` terms |
| gettext / libintl | 1.0 | LGPL-2.1-or-later (runtime) | Runtime intl only; `--disable-java --disable-csharp --disable-openmp --disable-curses --disable-libasprintf --with-included-libxml --with-libiconv-prefix=<ABI-prefix> --enable-shared --disable-static`; host `msgfmt` is not packaged |
| ICU | 78.3 | Unicode-3.0 / ICU | Static uc/i18n/data; `--with-cross-build=<host-ICU-build> --enable-static --disable-shared --with-data-packaging=static --disable-tests --disable-samples --disable-extras --disable-icuio` |
| SDL2 and vendored SDL Java | 2.32.10 (`release-2.32.10`) | zlib | Shared SDL2; test/static targets off; Java implementations unchanged, tag LICENSE.txt notice prepended intact |
| OpenSSL crypto/ssl | 3.5.9 LTS | Apache-2.0 | Android target, API29, shared, no-tests, no-apps |
| curl | 8.22.0 | curl (MIT-like) | Shared; OpenSSL on; CLI/tests, libpsl, SSH/SSH2, nghttp2, brotli, zstd, c-ares off |
| FreeImage and its bundled codecs | 3.18.0 | FreeImage Public License or GPL-2.0; FIPL selected | Shared; `FREEIMAGE_EXPORTS NO_LCMS __ANSI__ HAVE_UNISTD_H DISABLE_PERF_MEASUREMENT PNG_ARM_NEON_OPT=0`; bundled codec notices recorded in `licenses/FreeImage-bundled-codecs`; C++11, source-specific `_byteswap_ulong=__builtin_bswap32` for JPEG XR segdec.c and `-include wchar.h` for JXRGlueJxr.c |
| FreeImage bundled JPEG, PNG, TIFF, ZLib, OpenJPEG, OpenEXR, LibRawLite, LibWebP, LibJXR | JPEG 9c, PNG 1.6.35, TIFF 4.0.9, zlib 1.2.11, OpenJPEG 2.0.0, OpenEXR/IlmBase 2.2.0, LibRaw 0.19.0, WebP 1.0.0, JPEG XR 1.1 | IJG/BSD/zlib/MIT; LibRaw LGPL-2.1-or-later or CDDL-1.0 | Static within FreeImage; `licenses/FreeImage-bundled-codecs` preserves the codec notices; LibRaw LGPL-2.1 selected; no LCMS |
| libpng | 1.6.58 | libpng-2.0 | Shared; tests/tools off |
| HarfBuzz | 14.2.1 | MIT | Shared core packaged; GPU, raster and vector outputs are build-only; subset, ICU, FreeType integration off |
| FreeType | 2.14.3 | FTL or GPL-2.0; FTL selected | Shared; HarfBuzz, bzip2, brotli off |
| libgit2 | 1.9.4 | GPL-2.0 with linking exception | `-DBUILD_SHARED_LIBS=ON -DBUILD_TESTS=OFF -DBUILD_CLI=OFF -DUSE_SSH=OFF -DUSE_HTTPS=OpenSSL -DUSE_BUNDLED_ZLIB=OFF -DUSE_THREADS=ON`; linking exception retained |
| pugixml | 1.15 | MIT | Static |
| Ogg | 1.3.6 | BSD-3-Clause | Build-only shared output, not packaged; tests off |
| dav1d | 1.5.3 | BSD-2-Clause | Shared; tools/tests off |
| LunaSVG / plutovg | 3.5.0 / 1.3.2 (tracked subtree) | MIT | Static; upstream CMake configuration |
| rlottie | 0.2 (tracked subtree) | MIT | Static; threading/modules off by upstream CMake |
| GLM, RapidJSON, utfcpp, CImg | 1.0.0, 1.1.0, 4.0.6, 3.6.1 (tracked subtrees) | MIT; CImg CeCILL-C/CeCILL terms | Header-only native dependencies, existing notices; CImg’s CeCILL-C option applies |
| libc++_shared | NDK 28.2.13676358 (r28c) | Apache-2.0 with LLVM exception | Shared; hash-verified NDK copy; architecture/API/SONAME, LOAD alignment and APK zipalign checked; measured RELRO and build IDs below under D-001(b) am. 2; notice in `licenses/libcxx` |
| Kotlin stdlib | 2.2.21 | Apache-2.0 | Kotlin host runtime; `licenses/Kotlin` |
| JetBrains annotations (implicit Kotlin stdlib runtime dependency) | 13.0 | Apache-2.0 | Provided by Kotlin’s published runtime dependency graph; no explicit dependency declaration; canonical terms in `licenses/Kotlin` |
| Bundled fonts, theme, icons, sounds and CA certificates | tracked resources and linear-es-de | Existing per-asset licenses | Existing `licenses/` notices apply; Android placeholder splash/icon/TV banner are original MIT assets |

NDK prebuilt measurements (D-001(b) am. 2):

[The r29 CI measurement](https://github.com/sayenah/ES-DE-Plus/actions/runs/37779000596/job/113317027716)
ran `llvm-readelf -lW` on NDK **29.0.14206865**'s own runtimes. Both LOAD
alignments were `0x4000`, but strict RELRO failed on both ABIs: arm64
`0x148af8 + 0xa508 = 0x153000` (remainder `0x3000`), x86_64
`0x13fbe0 + 0xa420 = 0x14a000` (remainder `0x2000`). The ruled fallback therefore
keeps **28.2.13676358**. The shipped stock r28c measurements, independently
matched against Google's public archive and the CI output, are:

| NDK | ABI | GNU build ID | LOAD p_align | RELRO VirtAddr | RELRO MemSiz | End / remainder modulo 0x4000 |
| --- | --- | --- | --- | --- | --- | --- |
| 28.2.13676358 | arm64-v8a | `7befe631535aa853c4f4ac1293e49dcea34c9b6e` | `0x4000` (all LOADs) | `0x12f898` | `0xa768` | `0x13a000` / `0x2000` |
| 28.2.13676358 | x86_64 | `0f8f9b5a33c8898dc08ae1688f9b1d3d10ff68ab` | `0x4000` (all LOADs) | `0x129cc0` | `0xa340` | `0x134000` / `0x0` |

The unstripped NDK files' SHA256 values are
`ab4e6c71b96b851de45a8a9bd86369e7dbc2130a44b3b4520564be94847910f2`
(arm64) and `e4cd73c8a3607269f3be58d15c21f78bff112e27f9398d6261e5f965668f8746`
(x86_64). The auditor calculates these from the active NDK's own files, strips
reference copies with the same `llvm-strip --strip-unneeded` operation AGP uses,
and prints original, stripped-reference and actual packaged hashes. A match
selects Google's [LOAD plus zipalign criteria](https://developer.android.com/guide/practices/page-sizes);
all other libraries retain `(VirtAddr + MemSiz) % 0x4000 == 0`. CI also probes a
runtime with the same filename and changed bytes, requiring strict rejection.

Build-only: AGP **8.13.2**, Gradle wrapper **8.13**, Kotlin plugin **2.2.21**,
JDK **17**, NDK **28.2.13676358**, minSdk **29**, compile/targetSdk **36**,
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
[NDK r28 changelog](https://github.com/android/ndk/wiki/Changelog-r28),
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

Source archives are pinned and verified **before extraction**, including cache hits.
The checksum table lives in `tools/Android_dependencies_setup.sh`, whose content
hash participates in both download/install cache keys. `clean_cache=true` skips
both caches. Canonical public source-archive SHA256 values measured for this slice:

| Archive component | SHA256 |
| --- | --- |
| SDL | `5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165` |
| curl | `f7ef3ae8a22e521f289803fe93543eb64c329b58aa73a9e224dfd915a2a5f4f7` |
| dav1d | `732010aa5ef461fa93355ed2c6c5fedb48ddc4b74e697eaabe8907eaeb943011` |
| ffmpeg | `b6863adde98898f42602017462871b5f6333e65aec803fdd7a6308639c52edf3` |
| freeimage | `f41379682f9ada94ea7b34fe86bf9ee00935a3147be41b6569c9605a53e438fd` |
| freetype | `36bc4f1cc413335368ee656c42afca65c5a3987e8768cc28cf11ba775e785a5f` |
| gettext | `85d99b79c981a404874c02e0342176cf75c7698e2b51fe41031cf6526d974f1a` |
| harfbuzz | `a54a5d8e9380a41fbb762ce367bcbf7704792dfca0d93f1bbca86c5a57902e0e` |
| icu | `3a2e7a47604ba702f345878308e6fefeca612ee895cf4a5f222e7955fabfe0c0` |
| libgit2 | `824b73bd13647800fe4b566a1008ae77fea0e3e3424edab632fcfd8c0b14ba8b` |
| libiconv | `88dd96a8c0464eca144fc791ae60cd31cd8ee78321e67397e25fc095c4a19aa6` |
| libpng | `28eb403f51f0f7405249132cecfe82ea5c0ef97f1b32c5a65828814ae0d34775` |
| ogg | `5c8253428e181840cd20d41f3ca16557a9cc04bad4a3d04cce84808677fa1061` |
| openssl | `603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a` |
| pugixml | `655ade57fa703fb421c2eb9a0113b5064bddb145d415dd1f88c79353d90d511a` |
