#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. CI-only APK missing INTERNET, never uploaded.
import hashlib
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import signal
import sys
import tempfile
import time
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_digest(root, entries=None):
    if entries is None:
        entries = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=root)
    hashed = hashlib.sha256()
    for entry in filter(None, entries.split(b'\0')):
        reference, name = entry.split(b'\t', 1)
        mode, _, stage = reference.split()
        assert stage == b'0', 'Unmerged tracked entry: ' + os.fsdecode(name)
        path = root / os.fsdecode(name)
        # A Gitlink records a commit, not a file; CI leaves inherited upstream
        # test submodules uninitialised. Symlinks record their target, never an
        # arbitrary file outside this checkout. Ordinary files hash live bytes.
        if mode == b'160000':
            content = reference
        elif mode == b'120000':
            content = os.fsencode(os.readlink(path))
        else:
            content = path.read_bytes()
        hashed.update(reference + b'\0' + name + b'\0' + content + b'\0')
    return hashed.hexdigest()


def build(root):
    manifest = root / 'android/app/src/main/AndroidManifest.xml'
    original = manifest.read_bytes()
    declaration = b'    <uses-permission android:name="android.permission.INTERNET" />\n'
    assert original.count(declaration) == 1
    destination = root / 'android/.deps/network/no-internet.apk'
    destination.parent.mkdir(parents=True, exist_ok=True)
    evidence = root / 'android/evidence/network-control-build.txt'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    apk = root / 'android/app/build/outputs/apk/debug/app-debug.apk'
    fixed_hash = digest(apk)
    manifest_hash = digest(manifest)
    tracked_hash = tracked_digest(root)
    # Copy all inputs, including the normal build intermediates and JNI libraries,
    # but no caches, prior controls or evidence. Native tasks remain excluded below.
    # There is no write-and-restore window in the source tree, even on SIGKILL.
    def ignore(directory, names):
        excluded = {'.git', '.deps', '.gradle', '.kotlin', '__pycache__'}
        if pathlib.Path(directory) == root:
            excluded.add('build')
        if pathlib.Path(directory) == root / 'android':
            excluded.add('evidence')
        return excluded.intersection(names)
    with tempfile.TemporaryDirectory(prefix='control-', dir=destination.parent) as temporary:
        copied = pathlib.Path(temporary) / 'source'
        shutil.copytree(root, copied, ignore=ignore)
        copied_manifest = copied / manifest.relative_to(root)
        copied_apk = copied / apk.relative_to(root)
        copied_manifest.write_bytes(original.replace(declaration, b''))
        print('Control uses isolated copy: ' + str(copied), flush=True)
        assemble(copied, copied_apk)
        # Validate before publishing the control path. The normal APK is read only.
        payload, badging = validate(apk, copied_apk)
        shutil.copyfile(copied_apk, destination)
    assert digest(manifest) == manifest_hash, 'Source manifest changed'
    assert digest(apk) == fixed_hash, 'Normally-built APK changed'
    after_tracked = tracked_digest(root)
    assert after_tracked == tracked_hash, 'Tracked tree changed'
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    evidence.write_text(f'CI-only positive control built from isolated copy of {sha}; only INTERNET removed.\n'
                        f'Manifest SHA256 before={manifest_hash} after={digest(manifest)}\n'
                        f'Fixed APK SHA256 before={fixed_hash} after={digest(apk)}\n'
                        f'Tracked tree SHA256 before={tracked_hash} after={after_tracked}\n'
                        f'Control APK SHA256={digest(destination)}\n'
                        f'PASS: {len(payload)} executable/asset entries byte-identical; normal native builds retained.\n' + badging)
    print('PASS: isolated control has exactly the original three permissions; source and normal APK untouched')


def assemble(copied, copied_apk):
    # Relocating the project changes AGP's CMake model hash. Keep the copied
    # normal build's merged/stripped JNI outputs as well as its compiled code;
    # otherwise a fresh merge drops the native targets whose tasks are excluded.
    exclusions = ['--exclude-task', ':app:mergeDebugNativeLibs',
                  '--exclude-task', ':app:stripDebugDebugSymbols']
    # Only this manifest-only control reuses the native code already compiled by
    # normal assembleDebug on both ABIs. The ordinary debug/release builds and
    # every audit/smoke gate still run. Re-running native CMake here can link the
    # other ABI's upstream root-level libplutovg.a; no CMake/source workaround.
    for abi in ('arm64-v8a', 'x86_64'):
        for task in (f'configureCMakeDebug[{abi}]', f'buildCMakeDebug[{abi}][es-pdf-convert,main]'):
            exclusions += ['--exclude-task', ':app:' + task]
    subprocess.run(['./gradlew', '--no-daemon', *shlex.split(os.environ.get('GRADLE_NETWORK_ARGS', '')),
                    ':app:assembleDebug', *exclusions], cwd=copied / 'android', check=True)
    assert copied_apk.is_file()


def validate(apk, control):
    with zipfile.ZipFile(apk) as before, zipfile.ZipFile(control) as after:
        payload = {p for p in before.namelist() if p.startswith(('lib/', 'assets/', 'res/')) or
                   re.fullmatch(r'classes\d*\.dex|resources\.arsc', p)}
        assert payload and any(p.startswith('lib/arm64-v8a/') for p in payload)
        assert any(p.startswith('lib/x86_64/') for p in payload)
        actual = {p for p in after.namelist() if p.startswith(('lib/', 'assets/', 'res/')) or
                  re.fullmatch(r'classes\d*\.dex|resources\.arsc', p)}
        assert payload == actual, ('Control payload entries differ: '
                                   f'missing={sorted(payload - actual)}, extra={sorted(actual - payload)}')
        assert all(before.read(p) == after.read(p) for p in payload), 'Control changed executable/assets payload'
    aapt = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0/aapt'
    badging = subprocess.check_output([str(aapt), 'dump', 'badging', str(control)], text=True)
    actual = set(re.findall(r"^uses-permission(?:-sdk-\d+)?: name='([^']+)'", badging, re.M))
    expected = {'android.permission.' + name for name in
                ['READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE', 'MANAGE_EXTERNAL_STORAGE']}
    assert actual == expected, actual
    return payload, badging


def controls():
    # Kill the actual copy/build path while a fixture Gradle process is holding
    # the altered manifest. No SDK needed; real Gradle/APK validation runs in CI.
    parent = pathlib.Path('android/.deps/network')
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='kill-test-', dir=parent) as temporary:
        root = pathlib.Path(temporary).resolve()
        (root / 'gitlink').mkdir()
        tracked = root / 'tracked.txt'
        tracked.write_bytes(b'tracked contents')
        (root / 'tracked-link').symlink_to('tracked.txt')
        entries = (b'100644 aaaa 0\ttracked.txt\0' +
                   b'160000 bbbb 0\tgitlink\0' + b'120000 cccc 0\ttracked-link\0')
        reference_hash = tracked_digest(root, entries)
        tracked.write_bytes(b'changed contents')
        assert tracked_digest(root, entries) != reference_hash
        tracked.write_bytes(b'tracked contents')
        assert tracked_digest(root, entries.replace(b'bbbb', b'dddd')) != reference_hash
        assert tracked_digest(root, entries) == reference_hash
        manifest = root / 'android/app/src/main/AndroidManifest.xml'
        manifest.parent.mkdir(parents=True)
        manifest.write_text('<manifest>\n    <uses-permission android:name="android.permission.INTERNET" />\n</manifest>\n')
        apk = root / 'android/app/build/outputs/apk/debug/app-debug.apk'
        apk.parent.mkdir(parents=True)
        apk.write_bytes(b'normal APK fixture, must never be replaced')
        wrapper = root / 'android/gradlew'
        wrapper.write_text('#!/usr/bin/env python3\nimport pathlib, time\n'
                           'assert "android.permission.INTERNET" not in pathlib.Path("app/src/main/AndroidManifest.xml").read_text()\n'
                           'pathlib.Path("build-started").write_text("isolated manifest lacks INTERNET")\n'
                           'time.sleep(120)\n')
        wrapper.chmod(0o755)
        before = {str(p.relative_to(root)): digest(p) for p in root.rglob('*') if p.is_file()}
        with (root / 'kill-output.txt').open('w+') as output:
            process = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve())],
                                       cwd=root, stdout=output, stderr=output, start_new_session=True)
            try:
                deadline = time.monotonic() + 20
                while not list((root / 'android/.deps/network').glob('control-*/source/android/build-started')):
                    assert process.poll() is None, 'Control exited before kill fixture reached build'
                    assert time.monotonic() < deadline, 'Kill fixture did not reach isolated build'
                    time.sleep(0.05)
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
                assert process.returncode == -signal.SIGKILL
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            output.seek(0)
            transcript = output.read()
        after = {name: digest(root / name) for name in before}
        assert before == after, (before, after)
        assert not (root / 'android/.deps/network/no-internet.apk').exists()
        # No unexpected file outside the explicitly ignored runtime/evidence paths.
        actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and
                  '.deps' not in p.relative_to(root).parts and
                  'evidence' not in p.relative_to(root).parts and p.name != 'kill-output.txt'}
        assert actual == set(before), actual
        report = ('PASS: SIGKILL during isolated manifest/control build leaves all original fixture files unchanged; '
                  'normal APK and manifest hashes before/after below; no partial control APK published.\n' +
                  'PASS: tree fingerprint supports files, symlinks and uninitialised Gitlinks; file/reference changes detected.\n' +
                  '\n'.join(f'{name}: before={value} after={after[name]}' for name, value in before.items()) +
                  '\n' + transcript)
        evidence = pathlib.Path('android/evidence/network-control-kill-test.txt')
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(report)
        print(report, end='')


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        controls()
    else:
        assert not sys.argv[1:], 'Usage: network-control.py [--self-test]'
        build(pathlib.Path.cwd())
