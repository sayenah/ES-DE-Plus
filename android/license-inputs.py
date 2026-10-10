#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Actual compiler/header/link and APK licence closure.
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path.cwd().resolve()
SOURCES = {'icu', 'libpng', 'harfbuzz', 'freetype', 'libgit2', 'pugixml', 'SDL', 'ogg',
           'dav1d', 'ffmpeg', 'libiconv', 'gettext', 'openssl', 'curl', 'freeimage'}
SHARED = {'libmain.so', 'libes-pdf-convert.so', 'libSDL2.so', 'libavcodec.so', 'libavfilter.so',
          'libavformat.so', 'libavutil.so', 'libswresample.so', 'libswscale.so', 'libiconv.so',
          'libintl.so', 'libfreeimage.so', 'libfreetype.so', 'libharfbuzz.so', 'libgit2.so',
          'libcurl.so', 'libcrypto.so', 'libssl.so', 'libpng16.so', 'libdav1d.so', 'libc++_shared.so'}
STATIC = {'libicudata.a', 'libicui18n.a', 'libicuuc.a', 'libpugixml.a', 'liblunasvg.a',
          'libplutovg.a', 'librlottie.a', 'libSDL2main.a', 'libes-core.a', 'libgnu.a',
          'libcommon.a', 'libdefault.a', 'liblegacy.a', 'libtemplate.a'}
BUILD_ONLY = {'libogg.so', 'libcharset.so', 'libharfbuzz-gpu.so', 'libharfbuzz-raster.so',
              'libharfbuzz-vector.so', 'libcrypto.a', 'libssl.a', 'libicutu.a', 'libicutest.a'}
SYSTEM = {'libc.so', 'libm.so', 'libdl.so', 'liblog.so', 'libandroid.so', 'libGLESv1_CM.so',
          'libGLESv2.so', 'libGLESv3.so', 'libEGL.so', 'libOpenSLES.so', 'libaaudio.so',
          'libcamera2ndk.so', 'libmediandk.so', 'libz.so'}


def library_name(path):
    return re.sub(r'(\.so)(?:\.\d+)+$', r'\1', pathlib.PurePosixPath(path).name)


def permitted(path):
    path = path.replace('\\ ', ' ')
    assert not re.search(r'poppler|es-pdf-converter/src|lib(?:jpeg|tiff|openjp2|zstd)\.', path, re.I), path
    assert not re.search(r'libiconv/(?:src|srclib)/', path), ('Unused GPL libiconv utility input', path)
    if path.startswith('NDK/'):
        return
    parts = pathlib.PurePosixPath(path).parts
    if parts[:3] == ('android', '.deps', 'sources'):
        assert len(parts) > 3 and parts[3] in SOURCES, ('Unknown source input', path)
    elif parts[:3] == ('android', '.deps', 'build'):
        assert len(parts) > 4 and parts[4] in SOURCES | {'freeimage-project'}, ('Unknown generated input', path)
    elif parts[:2] == ('android', 'libs'):
        assert len(parts) == 4, path
    elif parts and re.fullmatch('android_(arm64-v8a|x86_64)', parts[0]):
        assert len(parts) == 2, path
    elif parts[:3] == ('android', '.deps', 'install'):
        assert len(parts) > 4 and parts[4] in {'include', 'lib'}, path
    elif parts and parts[0] == 'external':
        assert len(parts) > 1 and parts[1] in {'CImg', 'glm', 'lunasvg', 'rapidjson', 'rlottie', 'utfcpp'}, path
    else:
        assert parts and (parts[0] in {'es-app', 'es-core'} or parts[:2] == ('android', 'pdf') or
                          parts[:3] == ('android', 'app', '.cxx')), ('Unknown input', path)
    if re.search(r'\.(?:a|so(?:\.\d+)*)$', path):
        name = library_name(path)
        assert name in SHARED | STATIC | SYSTEM | BUILD_ONLY, ('Unknown linked library', path)


def normalise(path, cwd, ndk):
    p = pathlib.Path(path)
    p = (cwd / p).resolve() if not p.is_absolute() else p.resolve()
    try:
        return 'NDK/' + str(p.relative_to(ndk.resolve()))
    except ValueError:
        return str(p.relative_to(ROOT))


def collect(directory, ndk):
    compiled, headers, links = set(), set(), set()
    problems = []
    dependency_origins = {}
    def arguments(tokens, cwd):
        expanded = [value for token in tokens for value in
                    (token[4:].split(',') if token.startswith('-Wl,') else [token])]
        skip_value = False
        for token in expanded:
            if skip_value:
                skip_value = False
                continue
            if token in {'-soname', '--soname', '-rpath', '-rpath-link'}:
                skip_value = True
                continue
            if re.search(r'\.(?:a|so(?:\.\d+)*|o)$', token) and not token.startswith('-'):
                links.add(normalise(token, cwd, ndk))
            if token.startswith('-l') and len(token) > 2:
                names = {'lib' + token[2:] + '.so', 'lib' + token[2:] + '.a'}
                if not names & (SYSTEM | SHARED | STATIC | BUILD_ONLY | {'libatomic.so'}):
                    problems.append(('Unknown -l input', token))
    for recorded in directory.rglob('compiler-commands.jsonl'):
        records = [json.loads(line) for line in recorded.read_text().splitlines()]
        assert records, ('Empty actual compiler/archive calls', recorded)
        for record in records:
            cwd = pathlib.Path(record['directory'])
            if 'dependency' in record:
                dependency_origins[pathlib.Path(record['dependency']).resolve()] = cwd
            tokens = record['arguments'][1:]
            for token in tokens:
                if re.search(r'\.(?:c|cc|cpp|cxx|S|s)$', token) and not token.startswith('-'):
                    compiled.add(normalise(token, cwd, ndk))
            arguments(tokens, cwd)
    for database in directory.rglob('compile_commands.json'):
        for command in json.loads(database.read_text()):
            compiled.add(normalise(command['file'], pathlib.Path(command['directory']), ndk))
    for ninja in directory.rglob('build.ninja'):
        cwd = ninja.parent
        deps = subprocess.check_output(['ninja', '-C', str(cwd), '-t', 'deps'], text=True)
        for line in deps.splitlines():
            if line.startswith('    '):
                headers.add(normalise(line.strip(), cwd, ndk))
        # Actual commands include transitive static/shared link arguments. Response
        # files are expanded by Ninja, not inferred from CMake source text.
        commands = json.loads(subprocess.check_output(['ninja', '-C', str(cwd), '-t', 'compdb', '-x'], text=True))
        for entry in commands:
            line = entry['command']
            arguments(shlex.split(line), cwd)
    # Autoconf, FFmpeg and Meson retain compiler-produced dependency files.
    for dep in [*directory.rglob('*.d'), *directory.rglob('*.Plo'), *directory.rglob('*.Po')]:
        text = dep.read_text(errors='replace').replace('\\\n', ' ')
        for token in re.findall(r'(?:[^\s\\]|\\.)+', text):
            token = token.rstrip(':')
            if token.endswith(('.h', '.hpp', '.inc', '.c', '.cpp', '.cc', '.S', '.s')):
                # Autoconf depfiles are in .deps, relative to the containing build dir.
                cwd = dep.parent.parent if dep.parent.name == '.deps' else dep.parent
                build_root = next((parent for parent in dep.parents if parent.parent == directory), directory)
                # Recursive Make stores depfiles under a source subdirectory,
                # while the compiler can run from its enclosing Make directory.
                candidates = [dependency_origins.get(dep.resolve(), cwd), cwd] + [parent for parent in dep.parents
                                      if parent == build_root or build_root in parent.parents]
                origin = next((base for base in candidates if (base / token).exists()), None)
                if origin is None and not pathlib.Path(token).is_absolute():
                    problems.append(('Unresolved compiler dependency', str(dep), token))
                    continue
                headers.add(normalise(token, origin or cwd, ndk))
    result = {'compiled': sorted(compiled), 'headers': sorted(headers), 'links': sorted(links)}
    for paths in result.values():
        for path in paths:
            try:
                permitted(path)
            except AssertionError as error:
                problems.append(str(error))
    assert not problems, ('Rejected actual compiler/header/link inputs', problems)
    return result


def controls():
    for path in ['external/poppler/cpp/poppler-document.h', 'es-pdf-converter/src/ConvertPDF.h',
                 'android/libs/x86_64/libpoppler.so', 'external/unknown/unknown.h',
                 'android/.deps/install/x86_64/lib/libunknown.a',
                 'android/.deps/install/x86_64/lib/libunknown.so.1',
                 'android/.deps/sources/libiconv/src/iconv.c']:
        try:
            permitted(path)
        except AssertionError:
            print('PASS: licence graph positive control rejected: ' + path)
        else:
            raise AssertionError('Input control escaped: ' + path)


def native_controls(ndk):
    parent = ROOT / 'android/app/.cxx/LicenseControls'
    parent.mkdir(parents=True, exist_ok=True)
    for abi in ['arm64-v8a', 'x86_64']:
        for kind in ['header', 'library']:
            with tempfile.TemporaryDirectory(dir=parent) as temporary:
                source = pathlib.Path(temporary)
                forbidden = kind == 'header'
                (source / 'poppler-control.h').write_text('// SPDX-License-Identifier: MIT; synthetic ES-DE-Plus rejection control\n')
                (source / 'probe.cpp').write_text('// SPDX-License-Identifier: MIT; written for ES-DE-Plus\n' +
                    ('#include "poppler-control.h"\n' if forbidden else '') + 'int probe() { return 0; }\n')
                (source / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.13)\nproject(Control LANGUAGES CXX)\n' +
                    'set(CMAKE_EXPORT_COMPILE_COMMANDS ON)\nadd_library(' + ('safe' if forbidden else 'poppler') + ' STATIC probe.cpp)\n')
                build = source / 'build'
                subprocess.check_call(['cmake', '-S', str(source), '-B', str(build), '-G', 'Ninja',
                    '-DCMAKE_TOOLCHAIN_FILE=' + str(ndk / 'build/cmake/android.toolchain.cmake'),
                    '-DANDROID_ABI=' + abi, '-DANDROID_PLATFORM=android-29', '-DANDROID_STL=c++_shared'])
                subprocess.check_call(['cmake', '--build', str(build)])
                try:
                    collect(source, ndk)
                except AssertionError as error:
                    assert 'poppler' in str(error), ('Control failed for unrelated reason', error)
                    print(f'PASS: {abi} real NDK {kind} graph positive control rejected: {error}')
                else:
                    raise AssertionError('Actual compiler/link positive control escaped')


def reviewed_entries(entries):
    assert entries == SHARED, ('Unreviewed APK closure', entries ^ SHARED)


def apk_closure(apk):
    with zipfile.ZipFile(apk) as archive:
        for abi in ['arm64-v8a', 'x86_64']:
            entries = {pathlib.PurePosixPath(n).name for n in archive.namelist() if n.startswith('lib/' + abi + '/')}
            reviewed_entries(entries)
            for changed in [entries | {'libpoppler.so'}, entries | {'libunknown.so'}, entries - {'libSDL2.so'}]:
                try:
                    reviewed_entries(changed)
                except AssertionError:
                    print(f'PASS: {abi} APK closure positive control rejected: {changed ^ entries}')
                else:
                    raise AssertionError('APK closure positive control escaped')
            print(f'PASS: {apk.name} {abi} reviewed closure: ' + ', '.join(sorted(entries)))
        for name in archive.namelist():
            assert 'poppler' not in name.lower(), name
    # apkanalyzer reports defined classes before R8 naming. Gradle's resolved
    # runtime graph below identifies minified dependencies independent of names.


if __name__ == '__main__':
    controls()
    mode = sys.argv[1]
    ndk = pathlib.Path(sys.argv[-1])
    if mode == 'capture':
        abi = sys.argv[2]
        data = collect(ROOT / 'android/.deps/build' / abi, ndk)
        assert data['compiled'] and data['headers'] and data['links'], 'Empty dependency graph'
        for component in ['icu', 'openssl', 'gettext', 'libiconv', 'ffmpeg']:
            assert any(p.startswith('android/.deps/sources/' + component + '/') or
                       p.startswith('android/.deps/build/' + abi + '/' + component + '/')
                       for p in data['compiled']), ('Missing actual compiler calls', component)
        # Reject enabling a GPL or nonfree FFmpeg component in the actual configuration.
        config = (ROOT / 'android/.deps/build' / abi / 'ffmpeg/config.h').read_text()
        assert '#define CONFIG_GPL 0' in config and '#define CONFIG_NONFREE 0' in config, config
        (ROOT / 'android/.deps/install' / abi / 'license-inputs.json').write_text(json.dumps(data, indent=2))
        print(f'PASS: captured {abi} actual dependency compile/header/link graph')
    elif mode == 'probe':
        native_controls(ndk)
    elif mode == 'audit':
        for abi in ['arm64-v8a', 'x86_64']:
            data = json.loads((ROOT / 'android/.deps/install' / abi / 'license-inputs.json').read_text())
            for paths in data.values():
                assert paths, ('Empty cached graph', abi)
                for path in paths:
                    permitted(path)
            print(f'PASS: {abi} cached actual dependency graph ({len(data["headers"])} headers)')
        data = collect(ROOT / 'android/app/.cxx', ndk)
        for variant in ['Debug', 'Release']:
            for abi in ['arm64-v8a', 'x86_64']:
                databases = list((ROOT / 'android/app/.cxx' / variant).glob('*/' + abi + '/compile_commands.json'))
                assert databases, ('Missing variant/ABI compilation graph', variant, abi)
        assert 'android/pdf/ConvertPDF.cpp' in data['compiled'] and data['headers'] and data['links']
        print('PASS: both variants and ABIs actual native source, header and static/shared link inputs')
        for apk in map(pathlib.Path, sys.argv[2:-1]):
            apk_closure(apk)
        (ROOT / 'android/evidence/license-native-inputs.txt').write_text(json.dumps(data, indent=2))
    else:
        assert mode == 'controls', mode
