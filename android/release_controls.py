#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Eligibility/version/outcome controls with no network.
import contextlib
import io
import itertools
import json
import os
import pathlib
import re
import subprocess
import tempfile
import textwrap
from unittest import mock

import distribution
import release_pipeline
import test_signing


def workflow_eligibility():
    # Read the real expressions, including anchored shared steps, without a YAML
    # dependency. actionlint separately validates the complete workflow syntax.
    workflow = pathlib.Path('.github/workflows/build-android.yml').read_text()
    expressions = {}
    job = step = ''
    for line in workflow.splitlines():
        if re.fullmatch(r'  [\w-]+:', line):
            job = line.strip()[:-1]
            step = ''
        if line.startswith('      - name:'):
            step = line.split('name:', 1)[1].strip()
        if 'github.repository ==' in line and job != 'rebuild-source':
            label = 'concurrency' if line.startswith('  group:') else job + ':' + step
            if 'PUBLICATION:' in line or 'ELIGIBLE:' in line:
                label = line.strip().split(':', 1)[0]
            expressions[label] = re.findall(r'\$\{\{ (.*?) \}\}', line)[-1]
    assert len(expressions) == 6, expressions
    assert re.search(r'      publish:\n.*\n        type: boolean\n        default: false\n', workflow)
    # All Python guards must receive the same input, including the writing job.
    assert len(re.findall(r'^      PUBLISH: \$\{\{ inputs.publish \|\| false \}\}$', workflow, re.M)) == 4
    assert len(re.findall(r"^      FAILURE: \$\{\{ inputs.failure \|\| 'none' \}\}$", workflow, re.M)) == 4
    assert len(re.findall(r'^      REBUILD_RUN: \$\{\{ inputs.rebuild_run \}\}$', workflow, re.M)) == 4
    assert '    name: ${{ matrix.image }} / ${{ matrix.session }}' in workflow
    assert '    continue-on-error: ${{ matrix.informational }}' in workflow
    assert '    needs: [selection, build-publish]' in workflow
    assert 'internal-publication-apks-' in workflow
    assert workflow.count('    environment: test-signing') == 1
    builder = workflow.split('\n  build-publish:\n', 1)[1].split('\n  sessions:\n', 1)[0]
    publisher = workflow.split('\n  publish-apk:\n', 1)[1].split('\n  release:\n', 1)[0]
    assert 'origin_attempt: ${{ github.run_attempt }}' in builder
    assert 'origin_attempt: ${{ needs.build-publish.outputs.origin_attempt }}' in publisher
    return expressions, workflow


def evaluate(expression, values, cancelled=False):
    # This evaluator covers only the operators/context lookups used by these
    # eligibility expressions. Unsupported syntax fails rather than being ignored.
    expression = re.sub(r'\b(?:github|inputs|matrix|env|steps|needs)\.[\w.-]+',
                        lambda match: repr(values[match[0]]), expression)
    expression = expression.replace('success()', 'True').replace('always()', 'True').replace('cancelled()', repr(cancelled))
    expression = re.sub(r'\bformat\(', 'str.format(', expression)

    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', ' not ', expression)
    return eval(expression.strip(), {'__builtins__': {}, 'str': str}, {})


def eligibility_controls():
    expressions, workflow = workflow_eligibility()
    accepted = []
    evaluated = 0
    for repository, event, ref, image, rebuild, failure, publish in itertools.product(
            (test_signing.REPOSITORY, 'someone/ES-DE-Plus'),
            ('push', 'workflow_dispatch', 'pull_request', 'pull_request_target'),
            ('refs/heads/main', 'refs/heads/fix/publish-on-demand', 'refs/pull/19/merge', 'refs/tags/main'),
            ('api33', 'api35', 'tv36', 'api34', 'publish'), ('', '123'),
            ('', 'none', 'android', 'linux', 'source-upload', 'source-validation', 'apk-upload'),
            ('', False, True)):
        evaluated += 1
        expected = (repository == test_signing.REPOSITORY and event == 'workflow_dispatch' and
                    ref == 'refs/heads/main' and publish is True and rebuild == '' and failure in ('', 'none'))
        values = {'github.repository': repository, 'github.event_name': event, 'github.ref': ref,
                  'github.run_id': '123456', 'github.event.pull_request.number': 29,
                  'needs.selection.result': 'success', 'needs.sessions.result': 'success',
                  'needs.build.result': 'success', 'inputs.publish': publish, 'inputs.rebuild_run': rebuild,
                  'inputs.failure': failure, 'matrix.image': image, 'env.EARLY_LEGS_RESULT': 'success',
                  'steps.source-validate.outcome': 'success'}
        case = (repository, event, ref, image, rebuild, failure, publish)
        for label, expression in expressions.items():
            result = evaluate(expression, values)
            if label != 'concurrency':
                result = bool(result)
            if label == 'concurrency':
                verdict = 'main-publication' if expected else ('pr-29' if event == 'pull_request' else '123456')
            elif label.startswith('build-publish:Sign both'):
                verdict = expected and image == 'publish'
            else:
                verdict = expected
            assert result == verdict, (label, case, result, verdict)
        assert test_signing.eligible(*case[:6], publish) == (expected and image == 'publish'), case

        assert distribution.permitted_publication(repository, event, ref, publish, rebuild, failure) == expected, case
        environment = {'GITHUB_REPOSITORY': repository, 'GITHUB_EVENT_NAME': event, 'GITHUB_REF': ref,
                       'IMAGE': image, 'REBUILD_RUN': rebuild, 'FAILURE': failure,
                       'PUBLISH': str(publish).lower()}
        with mock.patch.dict(os.environ, environment), mock.patch.object(release_pipeline, 'GitHub') as transport:
            assert test_signing.stable_run() == (expected and image == 'publish'), case
            try:
                release_pipeline.publication_transport()
            except ValueError:
                assert not (expected and image == 'publish'), case
                transport.assert_not_called()
            else:
                assert expected and image == 'publish', case
                transport.assert_called_once_with()
        if expected and image == 'publish':
            accepted.append(case)
    assert len(accepted) == 2
    print(f'PASS: eligibility truth table, {evaluated} combinations across {len(expressions)} workflow expressions, '
          'eligible/stable_run, distribution and release transport; only:', json.dumps(accepted))
    # Run the final APK outcome guard itself for the newly dry-run main paths.
    for event, publish in [('push', ''), ('push', 'true'), ('workflow_dispatch', ''),
                           ('workflow_dispatch', 'false'), ('workflow_dispatch', 'true')]:
        eligible = event == 'workflow_dispatch' and publish == 'true'
        environment = dict(GITHUB_REPOSITORY=test_signing.REPOSITORY, GITHUB_EVENT_NAME=event,
                           GITHUB_REF='refs/heads/main', REBUILD_RUN='', PUBLISH=publish,
                           APK_UPLOAD_OUTCOME='success' if eligible else 'skipped',
                           APK_ARTIFACT_ID='123' if eligible else '')
        with mock.patch.dict(os.environ, environment), contextlib.redirect_stdout(io.StringIO()):
            distribution.verify_publication('none')
            for failure in ('android', 'linux', 'source-upload', 'source-validation', 'apk-upload'):
                try:
                    distribution.validate_injection(failure)
                except ValueError as error:
                    assert 'Failure injection is forbidden on main' in str(error)
                else:
                    raise AssertionError('Main failure-control prohibition changed')
            with mock.patch.dict(os.environ, {'APK_UPLOAD_OUTCOME': 'skipped' if eligible else 'success',
                                             'APK_ARTIFACT_ID': '' if eligible else '123'}):
                try:
                    distribution.verify_publication('none')
                except ValueError:
                    pass
                else:
                    raise AssertionError('Missed/forbidden APK upload escaped')
    print('PASS: main pushes/default/false dispatches dry-run; explicit dispatch requires APK; main failure controls forbidden')
    # Execute the workflow's actual required-outcome script for all possible job
    # results: only complete publication or complete dry-run outcomes may pass.
    block = workflow.split('  publication-result:\n', 1)[1].split('  rebuild-source:\n', 1)[0]
    script = textwrap.dedent(block.split("          python3 - <<'PYCODE'\n", 1)[1].split('          PYCODE', 1)[0])
    script = compile(script.replace("print('PASS: all API 33 sessions gate; API 35 results retained; publication complete or no APK uploaded')", ''),
                     'publication-result', 'exec')
    for eligible, selection, sessions, build, apk, release in itertools.product(
            (True, False), *([('success', 'failure', 'skipped', 'cancelled')] * 5)):
        environment = dict(ELIGIBLE=str(eligible).lower(), SELECTION=selection, SESSIONS=sessions,
                           BUILD=build, APK=apk, RELEASE=release)
        required = 'success' if eligible else 'skipped'
        expected = selection == sessions == 'success' and build == apk == release == required

        with mock.patch.dict(os.environ, environment):
            try:
                exec(script, {})
            except AssertionError:
                assert not expected, environment
            else:
                assert expected, environment
    print('PASS: actual parallel publication-result script, 2048 job-outcome combinations')



def check():
    eligibility_controls()
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
