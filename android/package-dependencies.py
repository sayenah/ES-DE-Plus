#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus from upstream CMake link inputs and ELF metadata.
import pathlib
import re
import shutil
import subprocess
import sys

source, target, ndk = map(pathlib.Path, sys.argv[1:4])
host, triple = sys.argv[4:6]
toolchain = ndk / 'toolchains/llvm/prebuilt' / host
readelf = toolchain / 'bin/llvm-readelf'
sysroot = toolchain / 'sysroot/usr/lib' / triple
cmake = pathlib.Path('CMakeLists.txt').read_text()
link_list = re.search(r'elseif\(ANDROID\)\s+set\(COMMON_LIBRARIES(.*?)elseif\(EMSCRIPTEN\)', cmake, re.S).group(1)
inputs = set(re.findall(r'/android/libs/\$\{ANDROID_CPU_ARCH\}/(lib[^\s)]+)', link_list))
pdf = pathlib.Path('es-pdf-converter/CMakeLists.txt').read_text()
inputs.update(re.findall(r'/android/libs/\$\{ANDROID_CPU_ARCH\}/(lib[^\s)]+)', pdf))
shared = {name for name in inputs if name.endswith('.so')} | {'libc++_shared.so'}
static = {name for name in inputs if name.endswith('.a')}
assert shared and static, 'No upstream Android link inputs found'
closure = {}
pending = sorted(shared)
while pending:
    name = pending.pop()
    if name in closure:
        continue
    library = sysroot / name if name == 'libc++_shared.so' else source / name
    assert library.is_file(), ('Missing non-system dependency', name)
    metadata = subprocess.check_output([str(readelf), '-d', str(library)], text=True)
    assert re.findall(r'\(SONAME\).*?\[(.*?)\]', metadata) == [name], (name, 'Unexpected SONAME')
    closure[name] = library
    needed = re.findall(r'\(NEEDED\).*?\[(.*?)\]', metadata)
    print(f'PACKAGE CLOSURE {name}: {", ".join(needed)}')
    for dependency in needed:
        if dependency == 'libc++_shared.so' or not (sysroot / '29' / dependency).is_file():
            pending.append(dependency)
# This directory is this script's APK-input output, not the install prefix. Remove
# stale outputs after narrowing the closure (including an old libpng linker alias).
target.mkdir(parents=True, exist_ok=True)
for old in target.glob('*.so*'):
    if old.name not in closure:
        old.unlink()
for name, library in sorted(closure.items()):
    shutil.copyfile(library, target / name)
    print(f'PACKAGE SHARED {name}')
for name in sorted(static):
    shutil.copyfile(source / name, target / name)
    print(f'PACKAGE STATIC {name}')
print(f'PASS: packaged {len(closure)} shared dependencies from upstream link inputs and DT_NEEDED closure')
