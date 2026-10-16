#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real extracted-Gradle version controls (PR-E M-1).
import os
import pathlib
import subprocess
import tarfile
import tempfile

import test_signing


def check(directory, parent_history):
    source = directory / 'source'
    source.mkdir()
    archive = directory / 'repository.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', 'HEAD'], stdout=stream, check=True)
    with tarfile.open(archive) as snapshot:
        snapshot.extractall(source, filter='data')
    assert not (source / '.git').exists()
    version = test_signing.public_version()
    init = directory / 'verify-version.gradle'
    init.write_text('''gradle.afterProject { project ->
    if (project.path == ':app' && project.state.failure == null) {
        def config = project.extensions.getByName('android').defaultConfig
        println "ESDEPLUS_VERSION=${config.versionCode},${config.versionName}"
    }
}
''')
    arguments = [str(source / 'android/gradlew'), '--no-daemon', '--init-script', str(init), 'help']
    if os.getenv('GRADLE_NETWORK_ARGS'):
        arguments.append(os.environ['GRADLE_NETWORK_ARGS'])
    for properties in ([], ['-Pesde.versionCode=' + str(version['version_code'])]):
        result = subprocess.run(arguments + properties, cwd=source / 'android', capture_output=True, text=True)
        output = result.stdout + result.stderr
        assert result.returncode != 0 and 'Repository history unavailable: pass -Pesde.versionCode' in output, output
        print('PASS: extracted Gradle rejects missing explicit version' +
              (' inside parent work tree' if parent_history else ' without any Git history'))
    result = subprocess.run(arguments + ['-Pesde.versionCode=' + str(version['version_code']),
                            '-Pesde.versionName=' + version['version_name']],
                            cwd=source / 'android', capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'ESDEPLUS_VERSION={version["version_code"]},{version["version_name"]}' in result.stdout, result.stdout
    print('PASS: extracted Gradle configures with exact explicit manifest-version properties' +
          (' inside parent work tree' if parent_history else ' without any Git history'))


if __name__ == '__main__':
    # Both are this project's own archived source. The nested case reproduces
    # Git's upward discovery without reading or creating another project.
    for parent, nested in [(os.environ['RUNNER_TEMP'], False), ('android/.deps', True)]:
        with tempfile.TemporaryDirectory(prefix='esdeplus-version-', dir=parent) as temporary:
            check(pathlib.Path(temporary).resolve(), nested)
