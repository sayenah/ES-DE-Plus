#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus from the public upstream dependency pins.
# Run from the repository root. Downloads never overwrite tracked external subtrees.
set -euo pipefail
[[ -f .clang-format && -d external/utfcpp ]] || { echo 'Run from the repository root'; exit 1; }
root=$PWD
sources=$root/android/.deps/sources
archives=$root/android/.deps/downloads
mkdir -p "$sources" "$archives"
verify_archive() {
    python3 - "$1" "$2" <<'PYVERIFY'
import hashlib, pathlib, sys
archive = pathlib.Path(sys.argv[1])
with archive.open('rb') as stream:
    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
if actual != sys.argv[2]:
    sys.exit(f'SHA256 mismatch: {archive.name}: expected {sys.argv[2]}, got {actual}')
print(f'Verified source archive: {archive.name} SHA256={actual}')
PYVERIFY
}
# SHA256 pins below were measured from these public publisher/archive URLs.
# Their containing script is included in both CI cache keys.
fetch() {
    local name=$1 url=$2 expected=$3 archive=$archives/$1.archive
    if [[ ! -f $archive ]]; then
        curl --fail --location --retry 3 "$url" -o "$archive.part"
        verify_archive "$archive.part" "$expected"
        mv "$archive.part" "$archive"
    fi
    verify_archive "$archive" "$expected"
    if [[ ! -f $sources/$name/.ready || $(cat "$sources/$name/.ready") != "$expected" ]]; then
        mkdir -p "$sources/$name"
        tar -xf "$archive" -C "$sources/$name" --strip-components=1
        printf '%s\n' "$expected" > "$sources/$name/.ready"
    fi
}
fetch icu https://github.com/unicode-org/icu/releases/download/release-78.3/icu4c-78.3-sources.tgz 3a2e7a47604ba702f345878308e6fefeca612ee895cf4a5f222e7955fabfe0c0
fetch libpng https://download.sourceforge.net/libpng/libpng-1.6.58.tar.xz 28eb403f51f0f7405249132cecfe82ea5c0ef97f1b32c5a65828814ae0d34775
fetch harfbuzz https://github.com/harfbuzz/harfbuzz/releases/download/14.2.1/harfbuzz-14.2.1.tar.xz a54a5d8e9380a41fbb762ce367bcbf7704792dfca0d93f1bbca86c5a57902e0e
fetch freetype https://download.savannah.gnu.org/releases/freetype/freetype-2.14.3.tar.xz 36bc4f1cc413335368ee656c42afca65c5a3987e8768cc28cf11ba775e785a5f
fetch libgit2 https://github.com/libgit2/libgit2/archive/refs/tags/v1.9.4.tar.gz 824b73bd13647800fe4b566a1008ae77fea0e3e3424edab632fcfd8c0b14ba8b
fetch pugixml https://github.com/zeux/pugixml/releases/download/v1.15/pugixml-1.15.tar.gz 655ade57fa703fb421c2eb9a0113b5064bddb145d415dd1f88c79353d90d511a
fetch SDL https://github.com/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-2.32.10.tar.gz 5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165
fetch ogg https://downloads.xiph.org/releases/ogg/libogg-1.3.6.tar.xz 5c8253428e181840cd20d41f3ca16557a9cc04bad4a3d04cce84808677fa1061
fetch dav1d https://downloads.videolan.org/pub/videolan/dav1d/1.5.3/dav1d-1.5.3.tar.xz 732010aa5ef461fa93355ed2c6c5fedb48ddc4b74e697eaabe8907eaeb943011
fetch ffmpeg https://ffmpeg.org/releases/ffmpeg-8.1.1.tar.xz b6863adde98898f42602017462871b5f6333e65aec803fdd7a6308639c52edf3
fetch libiconv https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.19.tar.gz 88dd96a8c0464eca144fc791ae60cd31cd8ee78321e67397e25fc095c4a19aa6
fetch gettext https://ftp.gnu.org/pub/gnu/gettext/gettext-1.0.tar.gz 85d99b79c981a404874c02e0342176cf75c7698e2b51fe41031cf6526d974f1a
fetch openssl https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz 603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a
fetch curl https://curl.se/download/curl-8.22.0.tar.xz f7ef3ae8a22e521f289803fe93543eb64c329b58aa73a9e224dfd915a2a5f4f7
archive=$archives/freeimage.zip
expected=f41379682f9ada94ea7b34fe86bf9ee00935a3147be41b6569c9605a53e438fd
if [[ ! -f $archive ]]; then
    curl --fail --location --retry 3 https://downloads.sourceforge.net/project/freeimage/Source%20Distribution/3.18.0/FreeImage3180.zip -o "$archive.part"
    verify_archive "$archive.part" "$expected"
    mv "$archive.part" "$archive"
fi
verify_archive "$archive" "$expected"
if [[ ! -f $sources/freeimage/.ready || $(cat "$sources/freeimage/.ready") != "$expected" ]]; then
    mkdir -p "$sources/freeimage"
    unzip -q -o "$archive" -d "$sources/freeimage"
    printf '%s\n' "$expected" > "$sources/freeimage/.ready"
fi
# Adapt the include layout expected by the unchanged upstream CMake.
link() {
    local target=$1 destination=$2
    if git ls-files --error-unmatch "$destination" >/dev/null 2>&1 || [[ -d $destination && ! -L $destination ]]; then
        echo "Refusing to replace existing directory: $destination" >&2; exit 1
    fi
    ln -sfn "$target" "$destination"
}
link "$sources/curl" external/curl
mkdir -p external/ffmpeg-kit/src
link "$sources/ffmpeg" external/ffmpeg-kit/src/ffmpeg
link "$sources/freeimage" external/freeimage
link "$sources/freetype" external/freetype
link "$sources/gettext" external/gettext
link "$sources/harfbuzz" external/harfbuzz
mkdir -p "$root/android/.deps/layout/icu" external/ffmpeg-kit/src
link "$sources/icu" "$root/android/.deps/layout/icu/icu4c"
link "$root/android/.deps/layout/icu" external/icu
link "$sources/libgit2" external/libgit2
link "$sources/pugixml" external/pugixml
link "$sources/SDL/include" "$sources/SDL/SDL2"
link "$sources/SDL" external/SDL_Android
# Public generated headers missing from the source archives. Both selected ABIs
# must agree before these ABI-neutral include links are used by upstream CMake.
for entry in 'libintl.h:gettext/gettext-runtime/intl/libintl.h' 'libavutil/avconfig.h:ffmpeg/libavutil/avconfig.h'; do
    installed=${entry%%:*}
    exposed=${entry#*:}
    neutral="$root/android/.deps/layout/generated/$installed"
    mkdir -p "$(dirname "$neutral")"
    for abi in arm64-v8a x86_64; do
        header="$root/android/.deps/install/$abi/include/$installed"
        [[ ! -f $header ]] || cp "$header" "$neutral"
    done
    left="$root/android/.deps/install/arm64-v8a/include/$installed"
    right="$root/android/.deps/install/x86_64/include/$installed"
    if [[ -f $left && -f $right ]]; then cmp "$left" "$right"; fi
    link "$neutral" "$sources/$exposed"
done
printf 'Dependency sources prepared without touching tracked subtrees.\n'
