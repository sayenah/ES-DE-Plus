#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Runner-only historical ownership control.
import hashlib
import os
import pathlib
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import test_signing

BASELINE = '438bf59271619737c510aac75f4a48eb668d2e91'


def build():
    root = pathlib.Path.cwd()
    destination = root / 'android/.deps/theme-owner/prefix.apk'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    version = test_signing.public_version(BASELINE)
    with tempfile.TemporaryDirectory(prefix='build-', dir=destination.parent) as directory:
        temporary = pathlib.Path(directory)
        archive = temporary / 'source.tar'
        subprocess.run(['git', 'archive', '--format=tar', '--output=' + str(archive), BASELINE], check=True)
        source = temporary / 'source'
        source.mkdir()
        with tarfile.open(archive) as contents:
            contents.extractall(source, filter='data')
        # Only generated, ignored dependency layouts are shared, read-only inputs
        # to this build. All product code/resources/Gradle inputs come from BASELINE.
        for relative in ['android/libs', 'external/curl', 'external/ffmpeg-kit/src/ffmpeg',
                         'external/freeimage', 'external/freetype', 'external/gettext',
                         'external/harfbuzz', 'external/icu', 'external/libgit2',
                         'external/pugixml', 'external/SDL_Android']:
            target = source / relative
            assert not target.exists() and not target.is_symlink(), relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(root / relative, target_is_directory=True)
        subprocess.run(['./gradlew', '--no-daemon', *shlex.split(os.environ.get('GRADLE_NETWORK_ARGS', '')),
                        '-Pesde.versionCode=' + str(version['version_code']),
                        '-Pesde.versionName=' + version['version_name'], ':app:assembleDebug'],
                       cwd=source / 'android', check=True)
        shutil.copyfile(source / 'android/app/build/outputs/apk/debug/app-debug.apk', destination)
        native = source / 'es-app/src/guis/GuiThemeDownloader.cpp'
        expected = subprocess.check_output(['git', 'show', BASELINE + ':es-app/src/guis/GuiThemeDownloader.cpp'])
        assert native.read_bytes() == expected
    evidence = root / 'android/evidence/theme-owner-control-build.txt'
    evidence.write_text('Runner-only pre-fix control, exact git archive of ' + BASELINE + '\n' +
                        repr(version) + '\nunsigned APK sha256=' +
                        hashlib.sha256(destination.read_bytes()).hexdigest() + '\n' +
                        'Both native ABIs compiled from the archived source; dependency inputs shared.\n'
                        'No APK upload, release operation, or tracked source mutation.\n')


if __name__ == '__main__':
    build()
