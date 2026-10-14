#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Eligibility/version/outcome controls with no network.
import itertools
import json
import os
import pathlib
import subprocess
import tempfile

import release_pipeline
import test_signing


def check():
    accepted = []
    evaluated = 0
    for repository, event, ref, image, rebuild, failure in itertools.product(
            (test_signing.REPOSITORY, 'someone/ES-DE-Plus'),
            ('push', 'workflow_dispatch', 'pull_request', 'pull_request_target'),
            ('refs/heads/main', 'refs/heads/fix/release-pipeline', 'refs/pull/13/merge'),
            ('api29', 'tv36', 'api34'), ('', '123'), ('none', 'android')):
        evaluated += 1
        result = test_signing.eligible(repository, event, ref, image, rebuild, failure)
        expected = (repository == test_signing.REPOSITORY and event in ('push', 'workflow_dispatch') and
                    ref == 'refs/heads/main' and image == 'api34' and rebuild == '' and failure == 'none')
        assert result == expected
        if result:
            accepted.append((repository, event, ref, image, rebuild, failure))
    assert len(accepted) == 2
    print(f'PASS: eligibility truth table, {evaluated} combinations; only:', json.dumps(accepted))
    version = test_signing.public_version()
    assert version == test_signing.public_version(), 'Same SHA changed version on rerun/dispatch'
    previous = test_signing.public_version('HEAD^1')
    assert previous['version_code'] + 1 == version['version_code'], 'First-parent progression changed'
    print('PASS: full-history first-parent version; repeat/dispatch/rerun agree:', json.dumps(version))
    # Exercise the production release state machine locally. These are payload
    # fixtures; the API-34 dry-run separately packages and validates actual APK/source.
    with tempfile.TemporaryDirectory(dir='android/evidence') as temporary:
        directory = pathlib.Path(temporary)
        files = {}
        for name in ('es-de-plus-aaaaaaaaa-debug.apk', 'es-de-plus-aaaaaaaaa-source.tar',
                     'es-de-plus-aaaaaaaaa-licenses.zip', 'SHA256SUMS.txt'):
            data = ('non-distributable payload fixture ' + name).encode()
            (directory / name).write_bytes(data)
            files[name] = {'sha256': release_pipeline.bytes_hash(data), 'size': len(data)}
        origin = {'schema': 1, 'repository': test_signing.REPOSITORY, 'commit': 'a' * 40,
                  'run_id': '1', 'run_attempt': '1', 'source_id': '1', 'apk_id': '2',
                  'version_code': version['version_code'], 'version_name': 'test-aaaaaaaaa',
                  'signer_sha256': test_signing.TEST_CERT_SHA256,
                  'apk_sha256': files['es-de-plus-aaaaaaaaa-debug.apk']['sha256'], 'files': files}
        description = release_pipeline.description_for(origin)
        release_pipeline.controls(description, origin, directory)
    print('PASS: fixture controls; no release API transport constructed')


if __name__ == '__main__':
    pathlib.Path('android/evidence').mkdir(exist_ok=True)
    check()
