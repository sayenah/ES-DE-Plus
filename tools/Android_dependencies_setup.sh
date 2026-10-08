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
fetch() {
    local name=$1 url=$2 archive=$archives/$1.archive
    if [[ ! -f $archive ]]; then
        curl --fail --location --retry 3 "$url" -o "$archive.part"
        tar -tf "$archive.part" >/dev/null
        mv "$archive.part" "$archive"
    fi
    if [[ ! -f $sources/$name/.ready ]]; then
        mkdir -p "$sources/$name"
        tar -xf "$archive" -C "$sources/$name" --strip-components=1
        touch "$sources/$name/.ready"
    fi
}
fetch icu https://github.com/unicode-org/icu/releases/download/release-78.3/icu4c-78.3-sources.tgz
fetch libpng https://download.sourceforge.net/libpng/libpng-1.6.58.tar.xz
fetch harfbuzz https://github.com/harfbuzz/harfbuzz/releases/download/14.2.1/harfbuzz-14.2.1.tar.xz
fetch freetype https://download.savannah.gnu.org/releases/freetype/freetype-2.14.3.tar.xz
fetch zstd https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz
fetch jpeg https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/3.1.4.1/libjpeg-turbo-3.1.4.1.tar.gz
fetch tiff https://download.osgeo.org/libtiff/tiff-4.7.1.tar.xz
fetch openjpeg https://github.com/uclouvain/openjpeg/archive/refs/tags/v2.5.4.tar.gz
fetch poppler https://poppler.freedesktop.org/poppler-26.06.0.tar.xz
fetch libgit2 https://github.com/libgit2/libgit2/archive/refs/tags/v1.9.4.tar.gz
fetch pugixml https://github.com/zeux/pugixml/releases/download/v1.15/pugixml-1.15.tar.gz
fetch SDL https://github.com/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-2.32.10.tar.gz
fetch ogg https://downloads.xiph.org/releases/ogg/libogg-1.3.6.tar.xz
fetch dav1d https://downloads.videolan.org/pub/videolan/dav1d/1.5.3/dav1d-1.5.3.tar.xz
fetch ffmpeg https://ffmpeg.org/releases/ffmpeg-8.1.1.tar.xz
fetch libiconv https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.19.tar.gz
fetch gettext https://ftp.gnu.org/pub/gnu/gettext/gettext-1.0.tar.gz
fetch openssl https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz
fetch curl https://curl.se/download/curl-8.22.0.tar.xz
if [[ ! -f $sources/freeimage/.ready ]]; then
    archive=$archives/freeimage.zip
    [[ -f $archive ]] || curl --fail --location --retry 3 https://downloads.sourceforge.net/project/freeimage/Source%20Distribution/3.18.0/FreeImage3180.zip -o "$archive"
    mkdir -p "$sources/freeimage"
    unzip -q -o "$archive" -d "$sources/freeimage"
    touch "$sources/freeimage/.ready"
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
# Poppler's version header is generated during the per-ABI build.
link "$sources/poppler" external/poppler
printf 'Dependency sources prepared without touching tracked subtrees.\n'
