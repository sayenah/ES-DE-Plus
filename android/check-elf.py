#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Audits the actual packaged ELF closure.
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

apk = pathlib.Path(sys.argv[1])
ndk = pathlib.Path(os.environ['ANDROID_NDK_HOME'])
readelf = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf'
system = {'libc.so', 'libm.so', 'libdl.so', 'liblog.so', 'libandroid.so', 'libEGL.so',
          'libGLESv1_CM.so', 'libGLESv2.so', 'libGLESv3.so', 'libOpenSLES.so', 'libaaudio.so', 'libz.so'}
required = {'libmain.so', 'libSDL2.so', 'libes-pdf-convert.so', 'libc++_shared.so', 'libpoppler-cpp.so'}

def android_api(data):
    # ELF64 little endian .note.android.ident; the descriptor starts with min API.
    section_offset = struct.unpack_from('<Q', data, 40)[0]
    section_size, count, strings_index = struct.unpack_from('<HHH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, section_offset + i * section_size)
                for i in range(count)]
    strings = sections[strings_index]
    names = data[strings[4]:strings[4] + strings[5]]
    for section in sections:
        name = names[section[0]:].split(b'\0', 1)[0]
        if name == b'.note.android.ident':
            offset = section[4]
            name_size, desc_size, kind = struct.unpack_from('<III', data, offset)
            assert kind == 1 and desc_size >= 4
            return struct.unpack_from('<I', data, offset + 12 + ((name_size + 3) & ~3))[0]
    raise AssertionError('Missing Android API note')

with tempfile.TemporaryDirectory() as temporary:
    with zipfile.ZipFile(apk) as package:
        package.extractall(temporary)
    for abi, machine in [('arm64-v8a', 'AArch64'), ('x86_64', 'Advanced Micro Devices X86-64')]:
        libraries = {p.name: p for p in (pathlib.Path(temporary) / 'lib' / abi).glob('*.so')}
        assert required <= libraries.keys(), (abi, 'Missing libraries', required - libraries.keys())
        sonames = {}
        dependencies = {}
        for name, file in sorted(libraries.items()):
            output = subprocess.check_output([str(readelf), '-W', '-h', '-l', '-d', '-n', str(file)], text=True)
            print(f'=== {abi}/{name} ===\n{output}')
            assert machine in output, (abi, name, 'Wrong architecture')
            api = android_api(file.read_bytes())
            assert api <= 29, (name, 'API too high', api)
            for line in output.splitlines():
                fields = line.split()
                if fields and fields[0] == 'LOAD':
                    assert int(fields[-1], 16) >= 16384, (name, 'Unaligned LOAD', line)
                if fields and fields[0] == 'GNU_RELRO':
                    assert (int(fields[2], 16) + int(fields[5], 16)) % 16384 == 0, (name, 'Unaligned RELRO', line)
            matches = re.findall(r'\(SONAME\).*?\[(.*?)\]', output)
            # Upstream builds main as a MODULE loaded explicitly by SDL, not a
            # link dependency. Modules may omit SONAME; shared consumers may not.
            assert matches == [name] or (name == 'libmain.so' and not matches), (name, 'SONAME does not match APK entry', matches)
            assert name not in sonames
            sonames[name] = file
            dependencies[name] = re.findall(r'\(NEEDED\).*?\[(.*?)\]', output)
        if not re.findall(r'\(SONAME\).*?\[(.*?)\]', subprocess.check_output([str(readelf), '-d', str(libraries['libmain.so'])], text=True)):
            assert all('libmain.so' not in needed for needed in dependencies.values()), 'MODULE without SONAME used as dependency'
        for name, needed in dependencies.items():
            assert set(needed) <= system | sonames.keys(), (abi, name, 'Unresolved DT_NEEDED', needed)
            print(f'CLOSURE {abi}/{name}: {", ".join(needed)}')
        print(f'PASS {abi}: architecture, API <=29, SONAME closure, LOAD/RELRO 16 KiB alignment')
