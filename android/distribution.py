#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. D-009 source provenance and publication gates.
import argparse
import datetime
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import time
import zipfile

ROOT = pathlib.Path.cwd()
ABIS = ['arm64-v8a', 'x86_64']
REPOSITORY = 'sayenah/ES-DE-Plus'
LICENCES = {
    'icu': 'Unicode-3.0 / ICU', 'libpng': 'libpng-2.0', 'harfbuzz': 'MIT',
    'freetype': 'FTL selected', 'libgit2': 'GPL-2.0 with linking exception',
    'pugixml': 'MIT', 'SDL': 'zlib', 'ogg': 'BSD-3-Clause', 'dav1d': 'BSD-2-Clause',
    'ffmpeg': 'LGPL-2.1-or-later and permissive notices; GPL/nonfree disabled',
    'libiconv': 'LGPL-2.1-or-later runtime', 'gettext': 'LGPL-2.1-or-later runtime',
    'openssl': 'Apache-2.0', 'curl': 'curl (MIT-like)',
    'freeimage': 'FIPL, GPL-2.0 or GPL-3.0; FIPL selected; bundled codec notices; LibRaw LGPL-2.1 or CDDL-1.0; LGPL-2.1 selected',
}
LIBRARIES = {
    **dict.fromkeys(['libmain.so', 'libes-core.a'], 'repository'),
    'libes-pdf-convert.so': 'repository', 'libc++_shared.so': 'NDK',
    **dict.fromkeys(['libSDL2.so', 'libSDL2main.a'], 'SDL'),
    **dict.fromkeys(['libavcodec.so', 'libavfilter.so', 'libavformat.so', 'libavutil.so',
                    'libswresample.so', 'libswscale.so', 'libavdevice.so'], 'ffmpeg'),
    'libiconv.so': 'libiconv', 'libcharset.so': 'libiconv',
    'libintl.so': 'gettext', 'libgnu.a': 'gettext', 'libfreeimage.so': 'freeimage',
    'libfreetype.so': 'freetype', 'libgit2.so': 'libgit2', 'libcurl.so': 'curl',
    **dict.fromkeys(['libcrypto.so', 'libssl.so', 'libcrypto.a', 'libssl.a', 'libcommon.a',
                    'libdefault.a', 'liblegacy.a', 'libtemplate.a', 'capi.so', 'dasync.so',
                    'loader_attic.so', 'ossltest.so', 'padlock.so', 'legacy.so'], 'openssl'),
    'libpng16.so': 'libpng', 'libpng16.a': 'libpng', 'libogg.so': 'ogg',
    **dict.fromkeys(['libharfbuzz.so', 'libharfbuzz-gpu.so', 'libharfbuzz-raster.so',
                    'libharfbuzz-vector.so'], 'harfbuzz'),
    **dict.fromkeys(['libdav1d.so', 'libdav1d_bitdepth_8.a', 'libdav1d_bitdepth_16.a',
                    'libdav1d_input.a'], 'dav1d'),
    **dict.fromkeys(['libicudata.a', 'libicui18n.a', 'libicuuc.a', 'libicutu.a',
                    'libicutest.a'], 'icu'), 'libpugixml.a': 'pugixml',
    'liblunasvg.a': 'external/lunasvg', 'libplutovg.a': 'external/lunasvg',
    'librlottie.a': 'external/rlottie',
}
CODECS = {
    'LibJPEG': 'IJG', 'LibPNG': 'libpng', 'LibTIFF4': 'BSD', 'ZLib': 'zlib',
    'LibOpenJPEG': 'BSD-2-Clause', 'OpenEXR': 'BSD', 'LibRawLite': 'LGPL-2.1 or CDDL-1.0; LGPL-2.1 selected',
    'LibWebP': 'BSD-3-Clause', 'LibJXR': 'BSD-2-Clause',
}
DEX_SOURCES = {
    'org.jetbrains.kotlin:kotlin-stdlib:2.2.21': {
        'url': 'https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/2.2.21/kotlin-stdlib-2.2.21-sources.jar',
        'sha256': '664f515359444a92267a13266101431a630f99d6b8d04407a92b1a0e558d33ee',
        'file': 'archives/kotlin-stdlib-sources.jar', 'licence': 'Apache-2.0; licenses/Kotlin'},
    'org.jetbrains:annotations:13.0': {
        'url': 'https://repo.maven.apache.org/maven2/org/jetbrains/annotations/13.0/annotations-13.0-sources.jar',
        'sha256': '42a5e144b8e81d50d6913d1007b695e62e614705268d8cf9f13dbdc478c2c68e',
        'file': 'archives/annotations-sources.jar', 'licence': 'Apache-2.0; licenses/Kotlin'},
}
FONT_PATH = 'resources/fonts/FreeMono.ttf'
FONT_SOURCES = {
    'original': {
        'url': 'https://deb.debian.org/debian/pool/main/f/fonts-freefont/fonts-freefont_20120503.orig.tar.xz',
        'sha256': 'b3850d562f2e227720b4cd67f44490bdcb7abd6482714945b9b65cdcfe8ce0d8',
        'file': 'archives/fonts-freefont_20120503.orig.tar.xz'},
    'debian': {
        'url': 'https://deb.debian.org/debian/pool/main/f/fonts-freefont/fonts-freefont_20120503-10.debian.tar.xz',
        'sha256': '1798c185de175d881a5d5bc7f69c0e0abe050e1294d6f12dac6f08d0dd2cc557',
        'file': 'archives/fonts-freefont_20120503-10.debian.tar.xz'},
}
FONT_BINARY = {
    'url': 'https://deb.debian.org/debian/pool/main/f/fonts-freefont/fonts-freefont-ttf_20120503-10_all.deb',
    'sha256': '4ca1c21ebc479198a3a5879d236c8317d6f7b2f1c403f7890e24c02eead05615',
    'file': 'archives/fonts-freefont-ttf_20120503-10_all.deb',
    'purpose': 'Pinned binary reference for offline font/source binding; not a dependency',
}
FONT_DOWNLOADS = {**FONT_SOURCES, 'binary_reference': FONT_BINARY}
FONT_SHA256 = 'fb1fc7fbdfaf524841d2a6d57d9b0c9add87f6bdcfdde7fc2b27821d7ae0b454'
FONT_PACKAGE_VERSION = '20120503-10'
FONT_TOLERANCES = ['head.checkSumAdjustment', 'head.created', 'head.modified',
                   'FFTM timestamps', 'derived directory checksums']
SHADER_PATH = 'resources/shaders/glsl/scanlines.glsl'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with pathlib.Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def font_tables(data):
    # OpenType directory offsets locate tables; compare their full contents below.
    require(data[:4] == b'\x00\x01\x00\x00' and len(data) >= 12, 'Expected TrueType font')
    count = struct.unpack_from('>H', data, 4)[0]
    require(12 + 16 * count <= len(data), 'Truncated font directory')
    tables = {}
    for i in range(count):
        tag, checksum, offset, length = struct.unpack_from('>4sIII', data, 12 + 16 * i)
        tag = tag.decode('ascii')
        require(tag not in tables and offset + length <= len(data), 'Invalid font table directory')
        tables[tag] = (offset, data[offset:offset + length])
    require({'head', 'FFTM', 'glyf'} <= set(tables), 'Missing required FreeMono tables')
    return tables


def normalized_tables(data):
    result = {}
    for tag, (offset, original) in font_tables(data).items():
        content = bytearray(original)
        if tag == 'head':
            require(len(content) == 54, 'Unexpected head table size')
            content[8:12] = b'\0' * 4  # checkSumAdjustment
            content[20:36] = b'\0' * 16  # created and modified timestamps
        elif tag == 'FFTM':
            require(len(content) == 28, 'Unexpected FFTM table size')
            content[4:28] = b'\0' * 24  # three FontForge timestamps; version preserved
        result[tag] = bytes(content)
    return result


def compare_font_tables(bundled, reference):
    left, right = normalized_tables(bundled), normalized_tables(reference)
    require(left.keys() == right.keys(), 'FreeMono table set mismatch')
    for tag in sorted(left):
        require(left[tag] == right[tag], f'FreeMono table mismatch: {tag}')
    return {tag: hashlib.sha256(left[tag]).hexdigest() for tag in sorted(left)}


def debian_binary_font(path):
    # Read the pinned .deb's ar/data tar without installing it or adding a tool.
    data = path.read_bytes()
    require(data.startswith(b'!<arch>\n'), 'Invalid Debian binary package')
    members, position = {}, 8
    while position < len(data):
        header = data[position:position + 60]
        require(len(header) == 60 and header[58:60] == b'`\n', 'Invalid ar header')
        name = header[:16].decode().strip().rstrip('/')
        size = int(header[48:58])
        position += 60
        require(name not in members and position + size <= len(data), 'Invalid ar member')
        members[name] = data[position:position + size]
        position += size + size % 2
    require(members.get('debian-binary') == b'2.0\n', 'Unexpected Debian package format')
    control = [v for k, v in members.items() if k.startswith('control.tar.')]
    payload = [v for k, v in members.items() if k.startswith('data.tar.')]
    require(len(control) == len(payload) == 1, 'Missing/ambiguous Debian payload')
    with tarfile.open(fileobj=io.BytesIO(control[0])) as archive:
        text = archive.extractfile('./control').read().decode()
        require(re.search(r'^Package: fonts-freefont-ttf$', text, re.M) and
                re.search(r'^Version: ' + re.escape(FONT_PACKAGE_VERSION) + r'$', text, re.M),
                'Wrong Debian binary package/version')
    with tarfile.open(fileobj=io.BytesIO(payload[0])) as archive:
        return archive.extractfile('./usr/share/fonts/truetype/freefont/FreeMono.ttf').read()


def font_mapping(directory, font):
    for pin in FONT_DOWNLOADS.values():
        require(digest(directory / pathlib.Path(pin['file']).name) == pin['sha256'],
                f'Debian font input checksum mismatch: {pin["file"]}')
    require(hashlib.sha256(font).hexdigest() == FONT_SHA256, 'Bundled FreeMono checksum mismatch')
    with tarfile.open(directory / pathlib.Path(FONT_SOURCES['original']['file']).name) as archive:
        sources = [m.name for m in archive if m.isfile() and m.name.endswith('/sfd/FreeMono.sfd')]
        require(len(sources) == 1, 'Missing/ambiguous original FreeMono source')
    with tarfile.open(directory / pathlib.Path(FONT_SOURCES['debian']['file']).name) as archive:
        changelog = archive.extractfile('debian/changelog').read().decode()
        require(changelog.startswith(f'fonts-freefont ({FONT_PACKAGE_VERSION})'), 'Wrong Debian source version')
        patches = archive.extractfile('debian/patches/series').read().decode().splitlines()
        patches = [p.split()[0] for p in patches if p.strip() and not p.lstrip().startswith('#')]
        require('drop_bad_braille.diff' in patches, 'Debian Braille patch missing from series')
        for patch in patches:
            require(archive.getmember('debian/patches/' + patch).isfile(), 'Missing Debian patch')
        require(archive.getmember('debian/rules').isfile(), 'Missing Debian build recipe')
    reference = debian_binary_font(directory / pathlib.Path(FONT_BINARY['file']).name)
    tables = compare_font_tables(font, reference)
    return {'source_package': 'fonts-freefont', 'version': FONT_PACKAGE_VERSION,
            'sources': FONT_SOURCES, 'source_path': sources[0], 'debian_patches': patches,
            'modifications': 'Debian modified build; Braille block removed by drop_bad_braille.diff',
            'binary_reference': FONT_BINARY, 'binary_font_sha256': hashlib.sha256(reference).hexdigest(),
            'font_sha256': FONT_SHA256, 'table_sha256': tables, 'tolerated_fields': FONT_TOLERANCES,
            'licence': 'GPL-3.0; licenses/GNUFreeFont'}


def font_controls(font):
    compare_font_tables(font, font)
    changed = bytearray(font)
    entries = font_tables(font)
    for tag, start, length in [('head', 8, 4), ('head', 20, 16), ('FFTM', 4, 24)]:
        offset = entries[tag][0]
        changed[offset + start:offset + start + length] = b'\1' * length
    for i in range(len(entries)):
        changed[12 + 16 * i + 4:12 + 16 * i + 8] = b'\1' * 4
    compare_font_tables(font, bytes(changed))
    print('PASS: allowed FontForge timestamps/head and directory checksum differences tolerated')
    for tag, byte in [('glyf', 0), ('head', 4), ('FFTM', 0)]:
        changed = bytearray(font)
        changed[entries[tag][0] + byte] ^= 1
        try:
            compare_font_tables(font, bytes(changed))
        except ValueError as error:
            print(f'PASS: modified font table rejected: {error}')
        else:
            raise ValueError('Modified font table control escaped')


def font_ci():
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'Debian font inputs are fetched in CI only')
    directory = ROOT / 'android/.deps/downloads'
    directory.mkdir(parents=True, exist_ok=True)
    for pin in FONT_DOWNLOADS.values():
        archive = directory / pathlib.Path(pin['file']).name
        if not archive.exists():
            print(f'FETCH: pinned Debian font input {pin["file"]}', flush=True)
            subprocess.check_call(['curl', '--fail', '--location', '--retry', '3', pin['url'], '-o', str(archive)])
        else:
            print(f'CACHE: pinned Debian font input {pin["file"]}', flush=True)
        require(digest(archive) == pin['sha256'], 'Debian font download checksum mismatch')
    font = (ROOT / FONT_PATH).read_bytes()
    record = font_mapping(directory, font)
    print(json.dumps(record, indent=2))
    font_controls(font)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        corrupt = pathlib.Path(temporary)
        for pin in FONT_DOWNLOADS.values():
            name = pathlib.Path(pin['file']).name
            for original in FONT_DOWNLOADS.values():
                original_name = pathlib.Path(original['file']).name
                (corrupt / original_name).symlink_to(directory / original_name)
            (corrupt / name).unlink()
            (corrupt / name).write_bytes(b'corrupt Debian font input control')
            try:
                font_mapping(corrupt, font)
            except ValueError as error:
                print(f'PASS: corrupt Debian font input rejected: {error}')
            else:
                raise ValueError('Font integrity control escaped')
            for item in corrupt.iterdir():
                item.unlink()
    print(f'PASS: every FreeMono table matches Debian fonts-freefont-ttf {FONT_PACKAGE_VERSION}; allowed fields {FONT_TOLERANCES}')


def shader_mapping(source):
    return {'repository_path': SHADER_PATH, 'sha256': hashlib.sha256(source).hexdigest(),
            'licence': 'GPL-2.0-or-later; RetroArch-derived; shipped source, compiled by GPU driver at runtime'}


def dependency_cache(key, hit):
    require(isinstance(key, str) and re.fullmatch(r'android-ndk28\.2\.13676358-api29-[a-f0-9]{64}', key),
            'Missing or invalid dependency-cache key')
    require(isinstance(hit, bool), 'Invalid dependency-cache hit state')
    return {'key': key, 'hit': hit}


def publication_result(eligible, outcome, artifact_id):
    if eligible:
        require(outcome == 'success' and str(artifact_id).isdecimal() and int(artifact_id) > 0,
                'Eligible main publication missed its APK upload')
    else:
        require(outcome == 'skipped' and not artifact_id, 'Unexpected APK upload outside main')


def verify_publication(injection):
    validate_injection(injection)
    eligible = permitted_publication(os.environ['GITHUB_REPOSITORY'],
                                     os.environ['GITHUB_EVENT_NAME'], os.environ['GITHUB_REF'])
    # Simulate only the eligible-main verdict; the actual upload guard stays main-only.
    if injection == 'apk-upload':
        eligible = True
    publication_result(eligible, os.environ['APK_UPLOAD_OUTCOME'], os.environ.get('APK_ARTIFACT_ID', ''))
    print('PASS: APK publication completed' if eligible else 'PASS: dry run uploaded no APK')


def audit_module():
    spec = importlib.util.spec_from_file_location('license_inputs', ROOT / 'android/license-inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pins(text):
    result = {name: {'url': url, 'sha256': sha, 'file': f'archives/{name}.archive',
                     'licence': LICENCES[name]}
              for name, url, sha in re.findall(r'^fetch (\w+) (\S+) ([a-f0-9]{64})$', text, re.M)}
    freeimage = re.search(r'archive=\$archives/freeimage.zip\nexpected=([a-f0-9]{64})', text)
    url = re.search(r'curl --fail --location --retry 3 (\S+FreeImage3180.zip)', text)
    require(freeimage and url, 'Missing FreeImage pin')
    result['freeimage'] = {'url': url[1], 'sha256': freeimage[1], 'file': 'archives/freeimage.zip',
                           'licence': LICENCES['freeimage']}
    require(set(result) == set(LICENCES), 'Archive component set changed without provenance review')
    return result


def provenance(path, tracked, audit):
    audit.permitted(path)
    parts = pathlib.PurePosixPath(path.replace('\\ ', ' ')).parts
    require('..' not in parts and not path.startswith('/'), f'Unsafe input: {path}')
    if path.startswith('NDK/'):
        return {'toolchain': 'NDK 28.2.13676358', 'path': path[4:],
                'licence': 'Apache-2.0 with LLVM exception; NDK sysroot/system notices',
                'source': 'https://android.googlesource.com/toolchain/llvm-project/'}
    if path in tracked:
        return {'repository_path': path,
                'licence': 'CeCILL-C selected' if path.startswith('external/CImg/') else
                           'Preserved repository licence and copyright notices'}
    if parts[:3] == ('android', '.deps', 'sources'):
        return {'archive': parts[3], 'source_path': '/'.join(parts[4:])}
    if parts[:3] == ('android', '.deps', 'build'):
        component = 'freeimage' if parts[4] == 'freeimage-project' else parts[4]
        return {'archive': component, 'generated_path': path,
                'recipe': 'tools/Android_dependencies_build.sh'}
    name = audit.library_name(path)
    if name in LIBRARIES:
        component = LIBRARIES[name]
        if component in LICENCES:
            return {'archive': component, 'library': name, 'recipe': 'tools/Android_dependencies_build.sh'}
        if component == 'NDK':
            abi = next((part for part in parts if part in ABIS), None)
            require(abi is not None, 'Unidentified NDK runtime ABI')
            triple = 'aarch64-linux-android' if abi == 'arm64-v8a' else 'x86_64-linux-android'
            return provenance('NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/' +
                              triple + '/' + name, tracked, audit)
        return {'repository_path': component if component != 'repository' else
                ('android/pdf/ConvertPDF.cpp' if name == 'libes-pdf-convert.so' else 'CMakeLists.txt'),
                'library': name, 'recipe': 'android/app/build.gradle.kts'}
    if parts[:3] == ('android', '.deps', 'install') and parts[4] == 'include':
        header = '/'.join(parts[5:])
        prefix = parts[5]
        component = {'unicode': 'icu', 'curl': 'curl', 'harfbuzz': 'harfbuzz', 'freetype2': 'freetype',
                     'openssl': 'openssl', 'git2': 'libgit2', 'git2.h': 'libgit2', 'SDL2': 'SDL',
                     'dav1d': 'dav1d', 'libpng16': 'libpng', 'png.h': 'libpng', 'pngconf.h': 'libpng',
                     'pnglibconf.h': 'libpng', 'iconv.h': 'libiconv', 'libcharset.h': 'libiconv',
                     'localcharset.h': 'libiconv', 'libintl.h': 'gettext', 'FreeImage.h': 'freeimage',
                     'pugixml.hpp': 'pugixml', 'pugiconfig.hpp': 'pugixml', 'ogg': 'ogg'}.get(prefix)
        if prefix in {'libavcodec', 'libavfilter', 'libavformat', 'libavutil', 'libswresample', 'libswscale'}:
            component = 'ffmpeg'
        require(component is not None, f'Unmapped installed header: {path}')
        return {'archive': component, 'installed_header': header, 'recipe': 'tools/Android_dependencies_build.sh'}
    if path == 'android/.deps/layout/generated/libintl.h':
        return {'archive': 'gettext', 'recipe': 'tools/Android_dependencies_build.sh'}
    if path == 'android/.deps/layout/generated/libavutil/avconfig.h':
        return {'archive': 'ffmpeg', 'recipe': 'tools/Android_dependencies_build.sh'}
    if parts[:3] == ('android', 'app', '.cxx'):
        return {'repository_path': 'android/app/build.gradle.kts', 'generated_path': path,
                'recipe': 'CMakeLists.txt; compiled graph in this manifest'}
    require(False, f'Unmapped input: {path}')


def permitted_publication(repository, event, ref):
    return repository == REPOSITORY and event in {'push', 'workflow_dispatch'} and ref == 'refs/heads/main'


def artifact_names(commit, run_id, attempt):
    require(re.fullmatch('[a-f0-9]{40}', commit) and str(run_id).isdecimal() and str(attempt).isdecimal(),
            'Invalid artefact identity')
    source = f'es-de-plus-source-{commit[:9]}-run{run_id}-attempt{attempt}'
    return source, source.replace('-source-', '-debug-apk-')


def validate_injection(injection):
    require(not injection or injection == 'none' or
            not permitted_publication(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_EVENT_NAME'],
                                      os.environ['GITHUB_REF']), 'Failure injection is forbidden on main')


def gate(android, linux, source):
    require(android == 'success', f'Publication suppressed: Android result {android}')
    require(linux == 'success', f'Publication suppressed: Linux result {linux}')
    require(source == 'success', f'Publication suppressed: source result {source}')


def api(endpoint):
    return json.loads(run('gh', 'api', endpoint))


def linux_gate(injection):
    validate_injection(injection)
    event = os.environ['GITHUB_EVENT_NAME']
    payload = json.loads(pathlib.Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    head = payload['pull_request']['head']['sha'] if event == 'pull_request' else os.environ['GITHUB_SHA']
    expected_event = 'pull_request' if event == 'pull_request' else 'push'
    commit = run('git', 'rev-parse', 'HEAD')
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        candidates = api(f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/workflows/build-linux.yml/runs'
                         f'?head_sha={head}&event={expected_event}&per_page=100')['workflow_runs']
        if candidates:
            selected = max(candidates, key=lambda r: r['id'])
            print(f'Linux gate: {selected["html_url"]} SHA={head} status={selected["status"]}', flush=True)
            if selected['status'] == 'completed':
                conclusion = 'failure' if injection == 'linux' else selected['conclusion']
                gate('success', conclusion, 'success')
                jobs = api(f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{selected["id"]}/jobs')['jobs']
                require(len(jobs) == 1 and jobs[0]['conclusion'] == 'success', 'Linux jobs incomplete')
                # New gh versions require explicit permission to read raw ANSI
                # log data. Parse it from a file, without replaying it to a terminal.
                arguments = ['gh', 'api', f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/jobs/{jobs[0]["id"]}/logs']
                if '--allow-escape-sequences' in run('gh', 'api', '--help'):
                    arguments.append('--allow-escape-sequences')
                with tempfile.TemporaryFile(mode='w+', dir=ROOT / 'android/evidence') as log:
                    subprocess.run(arguments, stdout=log, check=True)
                    log.seek(0)
                    logs = log.read()
                match = re.search(r'git log -1 --format=%H\n\S+ ([a-f0-9]{40})', logs)
                require(match and match[1] == commit, 'Linux checkout is not the exact Android-tested commit')
                (ROOT / 'android/evidence/distribution-linux.txt').write_text(
                    f'PASS: {selected["html_url"]} tested checkout {commit}; conclusion success\n')
                return
        time.sleep(20)
    raise ValueError('Publication suppressed: same-commit Linux success timed out after 30 minutes')


def identity(apk):
    tools = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0'
    certificate = run(str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(apk))
    badging = run(str(tools / 'aapt2'), 'dump', 'badging', str(apk))
    require('CN=Android Debug' in certificate and 'Number of signers: 1' in certificate,
            'Expected one Android Debug signer')
    fingerprint = re.search(r'Signer #1 certificate SHA-256 digest: ([a-f0-9]{64})', certificate)
    require(fingerprint is not None, 'Missing signer fingerprint')
    require("package: name='org.esdeplus.frontend'" in badging and
            "application-label:'ES-DE Plus'" in badging and 'application-debuggable' in badging,
            'Unexpected APK identity')
    with zipfile.ZipFile(apk) as archive:
        abis = sorted({name.split('/')[1] for name in archive.namelist() if name.startswith('lib/')})
        require(abis == ABIS, f'Unexpected ABIs: {abis}')
    record = {'sha256': digest(apk), 'signer_sha256': fingerprint[1], 'abis': abis,
              'certificate': certificate, 'badging': badging}
    path = ROOT / 'android/evidence/distribution-apk.txt'
    if path.exists():
        require(json.loads(path.read_text()) == record, 'APK changed after audit/smoke')
    path.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    return record


def source_tree_unmodified(archives):
    # Compare extracted source bytes against the verified originals, including cache restores.
    # Setup creates only .ready/include links and two ABI-neutral generated-header links.
    for component, pin in archives.items():
        source = ROOT / 'android/.deps/sources' / component
        require(source.resolve().is_relative_to(ROOT.resolve()), 'Source tree escapes checkout')
        archive = ROOT / 'android/.deps/downloads' / pathlib.Path(pin['file']).name
        require(digest(archive) == pin['sha256'], f'Corrupt source archive: {component}')
        expected_paths = set()
        if component == 'freeimage':
            with zipfile.ZipFile(archive) as entries:
                for entry in entries.infolist():
                    if not entry.is_dir():
                        expected_paths.add(entry.filename)
                        require(hashlib.sha256(entries.read(entry)).hexdigest() == digest(source / entry.filename),
                                f'Source patch detected: {component}/{entry.filename}')
        else:
            with tarfile.open(archive) as entries:
                for entry in entries:
                    relative = pathlib.PurePosixPath(entry.name).parts[1:]
                    if entry.isfile() or entry.issym() or entry.islnk():
                        expected_paths.add('/'.join(relative))
                    if entry.isfile():
                        require(relative and '..' not in relative, 'Unsafe source archive member')
                        with entries.extractfile(entry) as stream:
                            expected = hashlib.file_digest(stream, 'sha256').hexdigest()
                        require(expected == digest(source.joinpath(*relative)),
                                f'Source patch detected: {component}/{entry.name}')
        generated_links = {'gettext': {'gettext-runtime/intl/libintl.h'},
                           'ffmpeg': {'libavutil/avconfig.h'}}.get(component, set())
        actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
        # SDL2 is an include-directory alias created by setup, not additional source.
        allowed = expected_paths | {'.ready'} | generated_links | ({'SDL2'} if component == 'SDL' else set())
        require(actual <= allowed, f'Added/unmapped source files: {component}: {actual - allowed}')


def archive_members(bundle, archives):
    result = {}
    for component, pin in archives.items():
        archive = bundle / pin['file']
        if component == 'freeimage':
            with zipfile.ZipFile(archive) as entries:
                result[component] = {p for p in entries.namelist() if not p.endswith('/')}
        else:
            with tarfile.open(archive) as entries:
                result[component] = {'/'.join(pathlib.PurePosixPath(p.name).parts[1:])
                                     for p in entries if p.isfile() or p.issym() or p.islnk()}
        require(not any(re.search(r'\.(apk|jks|keystore)$', p, re.I) for p in result[component]),
                f'Forbidden APK/Android keystore in source archive: {component}')
    return result


def make_bundle(apk):
    record = identity(apk)
    audit = audit_module()
    commit = run('git', 'rev-parse', 'HEAD')
    require(commit == os.environ['GITHUB_SHA'], 'Checkout differs from workflow SHA')
    archives = pins((ROOT / 'tools/Android_dependencies_setup.sh').read_text())
    source_tree_unmodified(archives)
    destination = ROOT / 'android/.deps/distribution/source'
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'archives').mkdir()
    subprocess.check_call(['git', 'archive', '--format=tar.gz', '-o', str(destination / 'repository.tar.gz'), commit])
    with tarfile.open(destination / 'repository.tar.gz') as repository:
        tracked = {entry.name for entry in repository if entry.isfile()}
    require(not any(re.search(r'\.(apk|jks|keystore)$', p, re.I) for p in tracked), 'Forbidden tracked binary/key')
    for pin in archives.values():
        shutil.copyfile(ROOT / 'android/.deps/downloads' / pathlib.Path(pin['file']).name,
                        destination / pin['file'])
    # Corresponding sources for the two already-audited dex runtimes, not new dependencies.
    for pin in DEX_SOURCES.values():
        archive = ROOT / 'android/.deps/downloads' / pathlib.Path(pin['file']).name
        if not archive.exists():
            subprocess.check_call(['curl', '--fail', '--location', '--retry', '3', pin['url'], '-o', str(archive)])
        require(digest(archive) == pin['sha256'], 'Dex source archive checksum mismatch')
        shutil.copyfile(archive, destination / pin['file'])
    downloads = ROOT / 'android/.deps/downloads'
    shader = (ROOT / SHADER_PATH).read_bytes()
    asset_sources = {FONT_PATH: font_mapping(downloads, (ROOT / FONT_PATH).read_bytes()),
                    SHADER_PATH: shader_mapping(shader)}
    for pin in FONT_DOWNLOADS.values():
        shutil.copyfile(downloads / pathlib.Path(pin['file']).name, destination / pin['file'])
    graphs = {abi: json.loads((ROOT / f'android/.deps/install/{abi}/license-inputs.json').read_text()) for abi in ABIS}
    graphs['native'] = json.loads((ROOT / 'android/evidence/license-native-inputs.txt').read_text())
    inputs = {path: provenance(path, tracked, audit) for graph in graphs.values()
              for paths in graph.values() for path in paths}
    with zipfile.ZipFile(apk) as archive:
        require(hashlib.sha256(archive.read('assets/fonts/FreeMono.ttf')).hexdigest() == FONT_SHA256,
                'APK FreeMono differs from the mapped repository font')
        require(archive.read('assets/shaders/glsl/scanlines.glsl') == shader,
                'APK scanline shader differs from its mapped source')
        shared = {name: {'sha256': hashlib.sha256(archive.read(name)).hexdigest(),
                         **provenance(name.replace('lib/', 'android/libs/', 1), tracked, audit)}
                  for name in archive.namelist() if name.startswith('lib/') and name.endswith('.so')}
    tools = {
        'NDK': (pathlib.Path(os.environ['ANDROID_NDK_HOME']) / 'source.properties').read_text(),
        'java': subprocess.check_output(['java', '-version'], stderr=subprocess.STDOUT, text=True),
        'cmake': run('cmake', '--version'), 'ninja': run('ninja', '--version'),
        'meson': run('meson', '--version'), 'clang': run(str(pathlib.Path(os.environ['ANDROID_NDK_HOME']) /
            'toolchains/llvm/prebuilt/linux-x86_64/bin/clang'), '--version'),
        'Gradle': '8.13', 'AGP': '8.13.2', 'Kotlin': '2.2.21', 'SDK': '36',
        'SDK CMake': '3.31.5', 'build-tools': '36.0.0', 'minSdk': '29',
    }
    require('Pkg.Revision = 28.2.13676358' in tools['NDK'], 'Unexpected NDK provenance')
    require(os.environ.get('DEPENDENCY_CACHE_HIT') in {'true', 'false'}, 'Missing cache restore result')
    cache = dependency_cache(os.environ['DEPENDENCY_CACHE_KEY'], os.environ['DEPENDENCY_CACHE_HIT'] == 'true')
    manifest = {'schema': 3, 'commit': commit, 'run_id': os.environ['GITHUB_RUN_ID'],
                'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'repository': os.environ['GITHUB_REPOSITORY'],
                'apk': record, 'archives': archives, 'graphs': graphs, 'inputs': inputs, 'shared': shared,
                'bundled_codecs': {f'FreeImage/Source/{k}': {'archive': 'freeimage', 'licence': v} for k, v in CODECS.items()},
                'runtime_dex': DEX_SOURCES,
                'asset_sources': asset_sources, 'dependency_cache': cache,
                'toolchain': tools, 'recipes': ['tools/Android_dependencies_setup.sh',
                    'tools/Android_dependencies_build.sh', 'android/app/build.gradle.kts',
                    'CMakeLists.txt', 'android/rebuild-source.sh'],
                'no_patches': 'No source patches applied by ES-DE-Plus: every downloaded native source file was compared with its pinned archive; build flags and generated include layout are recorded in the recipes. The Debian font source package preserves Debian patches/build scripts for the already-modified bundled font.',
                'files': {'repository.tar.gz': digest(destination / 'repository.tar.gz'),
                          **{p['file']: p['sha256'] for p in archives.values()},
                          **{p['file']: p['sha256'] for p in DEX_SOURCES.values()},
                          **{p['file']: p['sha256'] for p in FONT_DOWNLOADS.values()}}}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    validate_bundle(destination)
    apk_dir = destination.parent / 'apk'
    apk_dir.mkdir()
    shutil.copyfile(apk, apk_dir / 'app-debug.apk')
    # Notices come from the exact source commit, never an incidental/untracked file.
    with tarfile.open(destination / 'repository.tar.gz') as repository:
        for path in sorted(tracked):
            if path == 'LICENSE' or path.startswith('licenses/'):
                notice = apk_dir / path
                notice.parent.mkdir(parents=True, exist_ok=True)
                notice.write_bytes(repository.extractfile(path).read())
        (apk_dir / 'DEPENDENCY-LICENSES.md').write_bytes(
            repository.extractfile('android/DEPENDENCY-LICENSES.md').read())
        text = repository.extractfile('android/DISTRIBUTION-README.md').read().decode()
    shutil.copyfile(destination / 'manifest.json', apk_dir / 'manifest.json')
    source_name, apk_name = artifact_names(commit, manifest['run_id'], manifest['run_attempt'])
    text = text.replace('@SOURCE_NAME@', source_name)
    text = text.replace('@RUN_URL@', f'https://github.com/{manifest["repository"]}/actions/runs/{manifest["run_id"]}')
    (apk_dir / 'README.md').write_text(text)
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a') as stream:
            stream.write(f'source_name={source_name}\napk_name={apk_name}\n')
    print(f'PASS: exact source bundle {source_name}; APK SHA256 {record["sha256"]}')


def validate_bundle(bundle):
    manifest = json.loads((bundle / 'manifest.json').read_text())
    require(manifest['schema'] == 3 and re.fullmatch('[a-f0-9]{40}', manifest['commit']), 'Invalid manifest commit')
    require(manifest['dependency_cache'] == dependency_cache(
        manifest['dependency_cache']['key'], manifest['dependency_cache']['hit']), 'Unexpected cache metadata')
    require(re.fullmatch('[a-f0-9]{64}', manifest['apk']['sha256']), 'Missing APK hash')
    for file, expected in manifest['files'].items():
        require(file == 'repository.tar.gz' or re.fullmatch(r'archives/[\w.-]+\.(archive|zip|jar|deb|tar\.xz)', file), 'Unsafe bundle path')
        require(digest(bundle / file) == expected, f'Bundle hash mismatch: {file}')
    with tarfile.open(bundle / 'repository.tar.gz') as repository:
        require(repository.pax_headers.get('comment') == manifest['commit'], 'git archive commit mismatch')
        tracked = {entry.name for entry in repository if entry.isfile()}
        actual_pins = pins(repository.extractfile('tools/Android_dependencies_setup.sh').read().decode())
        asset_sources = {FONT_PATH: font_mapping(bundle / 'archives', repository.extractfile(FONT_PATH).read()),
                         SHADER_PATH: shader_mapping(repository.extractfile(SHADER_PATH).read())}
    require(manifest['asset_sources'] == asset_sources, 'Font/shader source mapping mismatch')
    for pin in FONT_DOWNLOADS.values():
        require(manifest['files'][pin['file']] == pin['sha256'], 'Debian font input pin mismatch')
    require(manifest['archives'] == actual_pins, 'Source pins differ from the archived build recipe')
    for pin in actual_pins.values():
        require(manifest['files'][pin['file']] == pin['sha256'], 'Archive file hash differs from pin')
    require(manifest['runtime_dex'] == DEX_SOURCES, 'Unmapped dex runtime input')
    for pin in DEX_SOURCES.values():
        require(manifest['files'][pin['file']] == pin['sha256'], 'Dex source hash differs from pin')
    require(set(manifest['files']) == {'repository.tar.gz'} | {p['file'] for p in actual_pins.values()} |
            {p['file'] for p in DEX_SOURCES.values()} | {p['file'] for p in FONT_DOWNLOADS.values()},
            'Missing/extra source files')
    require(all(path in tracked for path in manifest['recipes']), 'Build recipe absent from exact source archive')
    require('No source patches' in manifest['no_patches'], 'Missing no-patches declaration')
    expected_files = {'manifest.json'} | set(manifest['files'])
    require({str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file()} == expected_files,
            'Incidental output in source bundle')
    audit = audit_module()
    members = archive_members(bundle, actual_pins)
    require(set(manifest['graphs']) == set(ABIS) | {'native'}, 'Missing actual input graph')
    expected_inputs = set()
    for graph in manifest['graphs'].values():
        require(set(graph) == {'compiled', 'headers', 'links'} and all(graph.values()), 'Incomplete input graph')
        for paths in graph.values():
            expected_inputs.update(paths)
    require(set(manifest['inputs']) == expected_inputs, 'Input manifest incomplete')
    for path, mapping in manifest['inputs'].items():
        require(mapping == provenance(path, tracked, audit), f'Unmapped/mismatched input: {path}')
        if 'source_path' in mapping:
            require(mapping['source_path'] in members[mapping['archive']], f'Input absent from source archive: {path}')
    for abi in ABIS:
        actual = {pathlib.PurePosixPath(p).name for p in manifest['shared'] if p.startswith(f'lib/{abi}/')}
        require(actual == audit.SHARED, f'Shared closure mismatch: {abi}')
    require(len(manifest['shared']) == len(ABIS) * len(audit.SHARED), 'Extra ABI/shared entries')
    for path, mapping in manifest['shared'].items():
        require(re.fullmatch('[a-f0-9]{64}', mapping['sha256']), 'Missing shared-input hash')
        require({k: v for k, v in mapping.items() if k != 'sha256'} ==
                provenance(path.replace('lib/', 'android/libs/', 1), tracked, audit), 'Shared input mapping mismatch')
    require(manifest['bundled_codecs'] == {f'FreeImage/Source/{k}': {'archive': 'freeimage', 'licence': v}
                                         for k, v in CODECS.items()}, 'Missing bundled codec provenance')
    print(f'PASS: validated source commit {manifest["commit"]}, run {manifest["run_id"]}, attempt {manifest["run_attempt"]}')
    return manifest


def uploaded_source(injection):
    validate_injection(injection)
    source = ROOT / 'android/.deps/distribution/source'
    downloaded = source.parent / 'downloaded-source'
    if injection == 'source-validation':
        (downloaded / 'repository.tar.gz').write_bytes(b'injected uploaded-source corruption')
    manifest = validate_bundle(downloaded)
    require((source / 'manifest.json').read_bytes() == (downloaded / 'manifest.json').read_bytes(),
            'Uploaded source differs from this runner source bundle')
    metadata = api(f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/artifacts/{os.environ["SOURCE_ID"]}')
    require(not metadata['expired'] and metadata['name'] == os.environ['SOURCE_NAME'] and
            str(metadata['workflow_run']['id']) == os.environ['GITHUB_RUN_ID'], 'Wrong uploaded source artefact')
    expiry = datetime.datetime.fromisoformat(metadata['expires_at'].replace('Z', '+00:00'))
    require(expiry > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=13),
            'Uploaded source retention is shorter than 14 days; APK publication suppressed')
    require(manifest['commit'] == os.environ['GITHUB_SHA'] and
            manifest['run_id'] == os.environ['GITHUB_RUN_ID'] and
            manifest['run_attempt'] == os.environ['GITHUB_RUN_ATTEMPT'], 'Wrong uploaded source identity')
    require(digest(source.parent / 'apk/app-debug.apk') == manifest['apk']['sha256'], 'Staged APK hash changed')
    print(f'PASS: uploaded source {metadata["id"]} independently downloaded/validated; expires {expiry}; APK retention 7 days')


def bundle_controls(bundle):
    validate_bundle(bundle)
    original = (bundle / 'manifest.json').read_text()
    manifest = json.loads(original)
    archive = bundle / next(iter(manifest['archives'].values()))['file']
    saved = archive.with_suffix('.saved')
    archive.rename(saved)
    try:
        for mode in ['missing', 'corrupt']:
            if mode == 'corrupt':
                archive.write_bytes(b'corrupt archive control')
            try:
                validate_bundle(bundle)
            except (ValueError, FileNotFoundError) as error:
                print(f'PASS: {mode} archive rejected: {error}')
            else:
                raise ValueError(f'{mode} source control escaped')
    finally:
        archive.unlink(missing_ok=True)
        saved.rename(archive)
    for path in ['android/.deps/install/x86_64/include/unmapped.h',
                 'android/.deps/sources/ffmpeg/unmapped-added-source.c']:
        try:
            manifest = json.loads(original)
            manifest['graphs']['native']['headers'].append(path)
            manifest['inputs'][path] = ({'archive': 'ffmpeg', 'source_path': 'unmapped-added-source.c'}
                                        if path.endswith('.c') else {'repository_path': path})
            (bundle / 'manifest.json').write_text(json.dumps(manifest))
            try:
                validate_bundle(bundle)
            except (ValueError, AssertionError) as error:
                print(f'PASS: unmapped input rejected: {error}')
            else:
                raise ValueError('Unmapped input control escaped')
        finally:
            (bundle / 'manifest.json').write_text(original)
    validate_bundle(bundle)


def gate_controls():
    require(permitted_publication(REPOSITORY, 'push', 'refs/heads/main'), 'Main push rejected')
    require(permitted_publication(REPOSITORY, 'workflow_dispatch', 'refs/heads/main'), 'Main dispatch rejected')
    for repository, event, ref in [(REPOSITORY, 'pull_request', 'refs/heads/main'),
                                   (REPOSITORY, 'push', 'refs/heads/feature/distribution-posture'),
                                   ('someone/ES-DE-Plus', 'push', 'refs/heads/main')]:
        require(not permitted_publication(repository, event, ref), 'Non-main publication escaped')
        print(f'PASS: dry-run only: {repository} {event} {ref}')
    gate('success', 'success', 'success')
    for position, label in enumerate(['Android', 'Linux', 'source upload/validation']):
        for failure in ['failure', 'skipped', 'cancelled', '']:
            values = ['success'] * 3
            values[position] = failure
            try:
                gate(*values)
            except ValueError as error:
                print(f'PASS: {label} {failure!r} rejected: {error}')
            else:
                raise ValueError('Gate control escaped')
    first = artifact_names('a' * 40, '123', '1')
    rerun = artifact_names('a' * 40, '123', '2')
    require(set(first).isdisjoint(rerun), 'Rerun artefacts would overwrite an earlier pair')
    print(f'PASS: attempt identities never overwrite: {first} versus {rerun}')
    print('PASS: green gates would publish; no overwrite or delete operation')
    publication_result(True, 'success', '123')
    publication_result(False, 'skipped', '')
    for eligible, outcome, artifact_id in [(True, outcome, '') for outcome in
                                           ['success', 'skipped', 'failure', 'cancelled', '']] + [
                                           (False, 'success', '123')]:
        try:
            publication_result(eligible, outcome, artifact_id)
        except ValueError as error:
            print(f'PASS: missed/forbidden APK upload rejected: {error}')
        else:
            raise ValueError('APK publication control escaped')
    key = 'android-ndk28.2.13676358-api29-' + 'a' * 64
    dependency_cache(key, True)
    dependency_cache(key, False)
    for invalid_key, invalid_hit in [('', False), (key, 'true')]:
        try:
            dependency_cache(invalid_key, invalid_hit)
        except ValueError as error:
            print(f'PASS: invalid cache provenance rejected: {error}')
        else:
            raise ValueError('Cache provenance control escaped')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['identity', 'bundle', 'validate', 'controls', 'gates', 'linux', 'inject', 'uploaded', 'font', 'publication'])
    parser.add_argument('path', nargs='?', default='none')
    args = parser.parse_args()
    if args.mode == 'identity':
        identity(pathlib.Path(args.path))
    elif args.mode == 'bundle':
        make_bundle(pathlib.Path(args.path))
    elif args.mode == 'validate':
        validate_bundle(pathlib.Path(args.path))
    elif args.mode == 'controls':
        bundle_controls(pathlib.Path(args.path))
    elif args.mode == 'gates':
        gate_controls()
    elif args.mode == 'linux':
        linux_gate(args.path)
    elif args.mode == 'uploaded':
        uploaded_source(args.path)
    elif args.mode == 'font':
        font_ci()
    elif args.mode == 'publication':
        verify_publication(args.path)
    else:
        validate_injection(args.path)
