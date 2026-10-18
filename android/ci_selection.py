#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. CI tier planning, without APK or emulator changes.
import argparse
import fnmatch
import json
import itertools
import os
from pathlib import Path
import subprocess
import tomllib
import textwrap
from unittest import mock

from smoke_phases import PHASES

IMAGES = {
    'api33': dict(image='api33', api=33, target='google_apis', profile='pixel_2'),
    'tv36': dict(image='tv36', api=36, target='android-tv', profile='tv_1080p'),
    'api34': dict(image='api34', api=34, target='google_apis', profile='pixel_2'),
}
FULL_JOB = 'Full Android matrix evidence'


def values(raw, allowed):
    if raw == 'all':
        return list(allowed)
    result = [part.strip() for part in raw.split(',')]
    if not result or any(part not in allowed for part in result) or len(set(result)) != len(result):
        raise ValueError(f'Invalid selection {raw!r}; use all or unique comma-separated values from {list(allowed)}')
    return result


def path_plan(paths):
    plan = {'api33': {'core'}}
    reasons = ['api33/core: mandatory PR gate']
    with Path('android/ci-sessions.toml').open('rb') as source:
        rules = tomllib.load(source)['rule']
    for rule in rules:
        assert rule['reason'] and set(rule['sessions']) <= set(PHASES)
        assert set(rule.get('images', ['api33'])) <= set(IMAGES)
        for path in paths:
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in rule['paths']):
                for image in rule.get('images', ['api33']):
                    plan.setdefault(image, set()).update(rule['sessions'])
                reasons.append(f'{path}: {rule["reason"]}; images={rule.get("images", ["api33"])} sessions={rule["sessions"]}')
    return {image: [s for s in PHASES if s in sessions] for image, sessions in plan.items()}, reasons


def dispatch_plan(images, sessions, publish=False):
    chosen_images, chosen_sessions = values(images, IMAGES), values(sessions, PHASES)
    # Default means the literal defaults, so even an explicit partial spelling
    # cannot accidentally use a writing job or stable signing environment.
    if publish and (images != 'all' or sessions != 'all'):
        raise ValueError('publish=true requires default images=all and sessions=all')
    return {image: chosen_sessions for image in chosen_images}


def api_pages(endpoint, _key):
    return json.loads(subprocess.check_output(
        ['gh', 'api', '--paginate', '--slurp', endpoint], text=True))


def full_success(sha, repository, pages=api_pages):
    endpoint = f'repos/{repository}/actions/workflows/build-android.yml/runs?head_sha={sha}&status=success&per_page=100'
    for page in pages(endpoint, 'workflow_runs'):
        for run in page['workflow_runs']:
            # A successful targeted/PR/merge smoke never counts as full proof.
            if run['head_sha'] != sha or run['conclusion'] != 'success':
                continue
            jobs = pages(f'repos/{repository}/actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs?per_page=100', 'jobs')
            if any(job['name'] == FULL_JOB and job['conclusion'] == 'success'
                   for page in jobs for job in page['jobs']):
                return run['html_url']
    return ''


def outputs(plan, full=False):
    early = [dict(IMAGES[image], sessions=plan[image]) for image in IMAGES if image != 'api34' and image in plan]
    return dict(early=json.dumps({'include': early or [dict(IMAGES['api33'], sessions=[])]}),
                run_early=str(bool(early)).lower(), run_api34=str('api34' in plan).lower(),
                api34=json.dumps({'include': [dict(IMAGES['api34'], sessions=plan.get('api34', []))]}),
                full=str(full).lower(), skip=str(not plan).lower())


def select():
    event = os.environ['GITHUB_EVENT_NAME']
    payload = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    reasons = []
    full = False
    if event == 'pull_request':
        # NUL delimiting covers spaces/newlines; include both old and new names
        # of renames by disabling rename detection. Compare actual PR head/base.
        base, head = payload['pull_request']['base']['sha'], payload['pull_request']['head']['sha']
        paths = subprocess.check_output(['git', 'diff', '--no-renames', '--name-only', '-z',
                                         base + '...' + head]).decode().rstrip('\0').split('\0')
        plan, reasons = path_plan(paths)
    elif event == 'push':
        plan = {'api33': ['core']}
        reasons = ['main push: API 33 core merge smoke']
    elif event == 'workflow_dispatch':
        inputs = payload.get('inputs', {})
        images, sessions = inputs.get('images', 'all'), inputs.get('sessions', 'all')
        plan = dispatch_plan(images, sessions, inputs.get('publish') in (True, 'true'))
        full = images == sessions == 'all'
        reasons = [f'manual dispatch: images={images}; sessions={sessions}; full={full}']
    elif event == 'schedule':
        proof = full_success(os.environ['GITHUB_SHA'], os.environ['GITHUB_REPOSITORY'])
        plan = {} if proof else dispatch_plan('all', 'all')
        full = not proof
        reasons = [f'nightly: exact-head successful full matrix already present: {proof}' if proof
                   else 'nightly: no successful full matrix at this main SHA; run all sessions/images']
    else:
        raise ValueError(f'Unsupported event: {event}')
    report = json.dumps(dict(event=event, sha=os.environ['GITHUB_SHA'], plan=plan, reasons=reasons), indent=2)
    print(report, flush=True)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('Android CI selection\n```json\n' + report + '\n```\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
        for key, value in outputs(plan, full).items():
            out.write(f'{key}={value}\n')


def self_test():
    assert path_plan(['docs/protocol.md'])[0] == {'api33': ['core']}
    own = ['.github/workflows/build-android.yml', '.github/workflows/build-linux.yml',
           'android/ci_selection.py', 'android/ci-sessions.toml', 'android/README.md',
           'android/release_controls.py', 'android/distribution.py']
    assert path_plan(own)[0] == {'api33': ['core']}
    host = path_plan(['android/app/src/main/kotlin/org/esdeplus/frontend/MainActivity.kt'])[0]
    assert host == {'api33': ['core', 'lifecycle', 'assets']}
    assert path_plan(['android/app/src/main/java/org/libsdl/app/SDLActivity.java'])[0] == host
    for path, sessions in [('android/lifecycle_smoke.py', ['core', 'lifecycle']),
                           ('android/pdf_smoke.py', ['core', 'pdf-direct', 'pdf-scoped']),
                           ('android/forced_relaunch_smoke.py', ['core', 'assets'])]:
        assert path_plan([path])[0] == {'api33': sessions}
    assert path_plan(['es-core/src/HttpReq.cpp'])[0] == {'api33': ['core', 'integration'], 'api34': ['integration']}
    assert path_plan(['es-app/src/ApplicationUpdater.cpp'])[0] == {'api33': ['core', 'integration'], 'api34': ['integration']}
    assert path_plan(['android/app/src/main/kotlin/org/esdeplus/frontend/bridge/PdfManual.kt'])[0] == {
        'api33': ['core', 'lifecycle', 'pdf-direct', 'pdf-scoped', 'assets']}
    assert path_plan(['android/predictive_back_smoke.py'])[0] == {'api33': ['core', 'assets'], 'api34': ['assets']}
    # Bind fixture/probe cases to real files so a misspelled module path does
    # not silently turn a dedicated regression surface into core-only evidence.
    cases = {
        'es-core/src/utils/PlatformUtilAndroid.cpp': {'api33': list(PHASES)},
        '.github/workflows/forced-relaunch.yml': {'api33': ['core', 'assets']},
        'android/pdf-fixtures.py': {'api33': ['core', 'pdf-direct', 'pdf-scoped']},
        'es-pdf-converter/CMakeLists.txt': {'api33': ['core', 'pdf-direct', 'pdf-scoped']},
        'android/forced-relaunch-overlay/src/main/res/values/probe.xml': {'api33': ['core', 'assets']},
        'android/app/src/debug/kotlin/org/esdeplus/frontend/RuntimeSmoke.kt': {
            'api33': ['core', 'pdf-direct', 'pdf-scoped']},
        'android/stub-emulator/src/main/kotlin/org/esdeplus/stub/RecipientActivity.kt': {
            'api33': list(PHASES)},
        'android/app/src/main/AndroidManifest.xml': {'api33': list(PHASES), 'api34': ['integration']},
    }
    for path, expected in cases.items():
        assert Path(path).is_file(), path
        assert path_plan([path])[0] == expected, (path, path_plan([path])[0])
    assert path_plan(['android/smoke_session.py'])[0] == {'api33': list(PHASES)}
    assert path_plan(['android/smoke.py'])[0] == {'api33': list(PHASES)}
    assert path_plan(['android/network_smoke.py'])[0] == {'api33': ['core', 'integration'], 'api34': ['integration']}
    assert path_plan(['android/app/src/main/res/drawable/tv_banner.xml'])[0] == {'api33': ['core'], 'tv36': ['core']}
    assert dispatch_plan('api34,tv36', 'lifecycle,assets') == {i: ['lifecycle', 'assets'] for i in ('api34', 'tv36')}
    assert outputs(dispatch_plan('api34', 'assets'))['run_early'] == 'false'
    assert outputs({})['skip'] == 'true'
    for images, sessions, publish in [('api33', 'core', True), ('all', 'core', True),
                                      ('api35', 'all', False), ('all', '', False),
                                      ('api33,api33', 'all', False), ('all', 'core,typo', False),
                                      ('all', 'core,', False), ('', 'all', False)]:
        try:
            dispatch_plan(images, sessions, publish)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid or partial publication selection escaped')
    assert len(dispatch_plan('all', 'all', True)) == 3
    # Exact-head, completed full-marker and pagination controls; targeted green,
    # previous head and failed full proof cannot suppress nightly regression.
    for sha, conclusion, name, result, expected in [
            ('a', 'success', FULL_JOB, 'success', 'proof'),
            ('a', 'success', FULL_JOB, 'skipped', ''),
            ('a', 'success', 'publication-result', 'success', ''),
            ('b', 'success', FULL_JOB, 'success', ''),
            ('a', 'failure', FULL_JOB, 'success', '')]:
        def pages(endpoint, key):
            if key == 'workflow_runs':
                return [{'workflow_runs': []}, {'workflow_runs': [dict(head_sha=sha, conclusion=conclusion,
                        id=1, run_attempt=2, html_url='proof')]}]
            assert '/attempts/2/jobs?' in endpoint
            return [{'jobs': []}, {'jobs': [dict(name=name, conclusion=result)]}]
        assert full_success('a', 'test/repo', pages) == expected
    # Exercise the actual workflow result guard: selected jobs may not be
    # silently skipped; unselected jobs may not accidentally execute.
    workflow = Path('.github/workflows/build-android.yml').read_text()
    block = workflow.split('  tier-result:\n', 1)[1].split('  full-matrix-evidence:\n', 1)[0]
    script = textwrap.dedent(block.split("          python3 - <<'PYCODE'\n", 1)[1].split('          PYCODE', 1)[0])
    script = compile(script.replace("print('PASS: every selected image completed; unselected images skipped')", ''),
                     'tier-result', 'exec')
    states = ('success', 'failure', 'skipped', 'cancelled')
    for selection, early, api34, dry, early_selected, api34_selected, skip in itertools.product(
            states, states, states, states, (True, False), (True, False), (True, False)):
        expected = (selection == 'success' and early == ('success' if early_selected else 'skipped') and
                    (api34, dry) in ([('success', 'skipped'), ('skipped', 'success')] if api34_selected
                                    else [('skipped', 'skipped')]) and (skip or early_selected or api34_selected))
        environment = dict(SELECTION=selection, EARLY=early, API34=api34, DRY=dry,
                           EARLY_SELECTED=str(early_selected).lower(), API34_SELECTED=str(api34_selected).lower(),
                           SKIP=str(skip).lower())
        with mock.patch.dict(os.environ, environment):
            try:
                exec(script, {})
            except AssertionError:
                assert not expected, environment
            else:
                assert expected, environment
    # GitHub's implicit success() can suppress a terminal job after skipped
    # publication ancestors. Use an explicit status function and then require
    # all three immediate proof gates; no failed/partial run may mark full proof.
    import release_controls
    marker = workflow.split('  full-matrix-evidence:\n', 1)[1].split('  publication-result:\n', 1)[0]
    condition = marker.split('    if: ${{ ', 1)[1].split(' }}', 1)[0]
    assert 'always()' in condition and '!cancelled()' in condition
    for selected, selection, tier, publication in itertools.product((True, False), states, states, states):
        value = release_controls.evaluate(condition, {
            'needs.selection.outputs.full': str(selected).lower(), 'needs.selection.result': selection,
            'needs.tier-result.result': tier, 'needs.publication-result.result': publication})
        assert bool(value) == (selected and selection == tier == publication == 'success')
    print('PASS: actual full-proof marker guard, 128 full-selection/job-outcome combinations; explicit cancellation/status checks')
    print('PASS: actual tier-result guard, 2048 selection/job-outcome combinations')
    print('PASS: CI map representative cases (including this workflow-only PR → api33/core), targeted validation, publication refusal and exact-SHA nightly full-proof controls')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['select', 'self-test'])
    args = parser.parse_args()
    self_test() if args.mode == 'self-test' else select()
