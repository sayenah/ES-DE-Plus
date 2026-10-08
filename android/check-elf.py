#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Audits the actual packaged ELF closure.
import hashlib
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
print((ndk / 'source.properties').read_text())
system = {'libc.so', 'libm.so', 'libdl.so', 'liblog.so', 'libandroid.so', 'libcamera2ndk.so', 'libmediandk.so', 'libEGL.so',
          'libGLESv1_CM.so', 'libGLESv2.so', 'libGLESv3.so', 'libOpenSLES.so', 'libaaudio.so', 'libz.so'}
required = {'libmain.so', 'libSDL2.so', 'libes-pdf-convert.so', 'libc++_shared.so', 'libpoppler-cpp.so'}
failures = []

def require(condition, detail):
    # Report every ABI/library even when one check fails. The audit still exits
    # unsuccessfully; complete evidence must not hide failures later in the closure.
    if not condition:
        failures.append(detail)

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
    # AGP strips packaged libraries with --strip-unneeded. Hash the NDK's own
    # file and its identically stripped form; neither filename nor build ID alone
    # establishes that an APK entry is the supplied prebuilt (D-001(b) am. 2).
    prebuilt_hashes = {}
    for abi, triple in [('arm64-v8a', 'aarch64-linux-android'), ('x86_64', 'x86_64-linux-android')]:
        supplied = readelf.parent.parent / 'sysroot/usr/lib' / triple / 'libc++_shared.so'
        stripped = pathlib.Path(temporary) / f'ndk-{abi}.so'
        subprocess.check_call([str(readelf.parent / 'llvm-strip'), '--strip-unneeded', '-o', str(stripped), str(supplied)])
        original_hash = hashlib.sha256(supplied.read_bytes()).hexdigest()
        stripped_hash = hashlib.sha256(stripped.read_bytes()).hexdigest()
        prebuilt_hashes[abi] = {original_hash, stripped_hash}
        print(f'NDK REFERENCE {abi}: original SHA256={original_hash} stripped SHA256={stripped_hash}')
    # The vendor-prebuilt rule includes the APK alignment result, not only LOAD
    # alignment. Execute the published command so this audit also stands alone.
    zipalign = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0/zipalign'
    alignment = subprocess.run([str(zipalign), '-c', '-P', '16', '4', str(apk)], capture_output=True, text=True)
    print(f'APK zipalign -c -P 16 4: {"PASS" if alignment.returncode == 0 else "FAIL"}')
    print(alignment.stdout + alignment.stderr)
    require(alignment.returncode == 0, ('APK', 'zipalign 16 KiB failed'))
    with zipfile.ZipFile(apk) as package:
        package.extractall(temporary)
    for abi, machine in [('arm64-v8a', 'AArch64'), ('x86_64', 'Advanced Micro Devices X86-64')]:
        previous_failures = len(failures)
        libraries = {p.name: p for p in (pathlib.Path(temporary) / 'lib' / abi).glob('*.so')}
        assert required <= libraries.keys(), (abi, 'Missing libraries', required - libraries.keys())
        sonames = {}
        dependencies = {}
        for name, file in sorted(libraries.items()):
            output = subprocess.check_output([str(readelf), '-W', '-h', '-l', '-d', '-n', str(file)], text=True)
            print(f'=== {abi}/{name} ===\n{output}')
            require(machine in output, (abi, name, 'Wrong architecture'))
            data = file.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            prebuilt = digest in prebuilt_hashes[abi]
            print(f'{"NDK PREBUILT" if prebuilt else "STRICT"} {abi}/{name}: SHA256={digest}')
            api = android_api(data)
            require(api <= 29, (abi, name, 'API too high', api))
            for line in output.splitlines():
                fields = line.split()
                if fields and fields[0] == 'LOAD':
                    require(int(fields[-1], 16) >= 16384, (abi, name, 'Unaligned LOAD', line))
                if fields and fields[0] == 'GNU_RELRO':
                    end = int(fields[2], 16) + int(fields[5], 16)
                    if prebuilt:
                        print(f'NDK PREBUILT measured RELRO: {line.strip()} end={end:#x} remainder={end % 16384:#x}')
                    else:
                        require(end % 16384 == 0, (abi, name, 'Unaligned RELRO', line))
            matches = re.findall(r'\(SONAME\).*?\[(.*?)\]', output)
            # Upstream builds main as a MODULE loaded explicitly by SDL, not a
            # link dependency. Modules may omit SONAME; shared consumers may not.
            require(matches == [name] or (name == 'libmain.so' and not matches),
                    (abi, name, 'SONAME does not match APK entry', matches))
            assert name not in sonames
            sonames[name] = file
            dependencies[name] = re.findall(r'\(NEEDED\).*?\[(.*?)\]', output)
        if not re.findall(r'\(SONAME\).*?\[(.*?)\]', subprocess.check_output([str(readelf), '-d', str(libraries['libmain.so'])], text=True)):
            assert all('libmain.so' not in needed for needed in dependencies.values()), 'MODULE without SONAME used as dependency'
        for name, needed in dependencies.items():
            require(set(needed) <= system | sonames.keys(), (abi, name, 'Unresolved DT_NEEDED', needed))
            print(f'CLOSURE {abi}/{name}: {", ".join(needed)}')
        reachable = set()
        pending = list(required)
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            reachable.add(name)
            pending.extend(dependency for dependency in dependencies.get(name, []) if dependency not in system)
        require(reachable == libraries.keys(), (abi, 'Unreachable packaged libraries', sorted(libraries.keys() - reachable)))
        result = 'PASS' if len(failures) == previous_failures and alignment.returncode == 0 else 'FAIL'
        print(f'{result} {abi}: architecture, API <=29, SONAME closure, LOAD 16 KiB; strict built-library RELRO; hash-verified NDK prebuilt + APK zipalign')
for failure in failures:
    print(f'FAIL: {failure}')
sys.exit(bool(failures))
