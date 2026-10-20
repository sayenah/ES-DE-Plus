#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Phone CI selection and parallel session planning.
import argparse
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import tomllib

from smoke_phases import PHASES

# API 35 first full session set green: dispatch 39161875992 (8fc9afde7).
# Newly added sessions gate too.
API35_GATING = True
IMAGES = {
    'api33': dict(image='api33', api=33, target='google_apis', profile='pixel_2'),
    'api35': dict(image='api35', api=35, target='google_apis', profile='pixel_2'),
    'api34': dict(image='api34', api=34, target='google_apis', profile='pixel_2'),
    'tv36': dict(image='tv36', api=36, target='android-tv', profile='tv_1080p'),
}
CAPS = {'core': 60, 'lifecycle': 40, 'clear-task': 40, 'integration': 60,
        'pdf-direct': 35, 'pdf-scoped': 60, 'assets': 20, 'app-data': 60, 'manager-direct': 180, 'manager-scoped': 180, 'touch': 60}


def values(raw, allowed):
    result = list(allowed) if raw == 'all' else [part.strip() for part in raw.split(',')]
    if not result or any(part not in allowed for part in result) or len(set(result)) != len(result):
        raise ValueError(f'Invalid selection {raw!r}; use unique comma-separated values from {list(allowed)}')
    return result


def path_plan(paths):
    plan = {'api33': {'core'}}
    reasons = ['api33/core: mandatory PR gate']
    with Path('android/ci-sessions.toml').open('rb') as source:
        rules = tomllib.load(source)['rule']
    for rule in rules:
        assert rule['reason'] and set(rule['sessions']) <= set(PHASES)
        for path in paths:
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in rule['paths']):
                plan['api33'].update(rule['sessions'])
                if rule.get('android15', False):
                    plan.setdefault('api35', set()).add('core')
                    if 'touch' in rule['sessions']:
                        plan['api35'].add('touch')
                reasons.append(f'{path}: {rule["reason"]}; sessions={rule["sessions"]}; android15={rule.get("android15", False)}')
    return {image: [s for s in PHASES if s in sessions] for image, sessions in plan.items()}, reasons


def dispatch_plan(images, sessions, publish=False):
    # 'all' means supported default phones, never implicit TV/API 34 opt-in.
    selected_images = ['api33', 'api35'] if images == 'all' else values(images, IMAGES)
    selected_sessions = values(sessions, PHASES)
    if publish and (selected_images != ['api33', 'api35'] or sessions != 'all'):
        raise ValueError('Publication requires default phones and every session; legacy images are opt-in dry runs only')
    return {image: selected_sessions for image in selected_images}


def matrix(plan):
    return {'include': [dict(IMAGES[image], session=session,
                             cap=80 if image == 'api34' and session == 'core' else CAPS[session],
                             job_cap=180 if session.startswith('manager-') else 300, informational=image == 'api35' and not API35_GATING)
                        for image, sessions in plan.items() for session in sessions]}


def select():
    event = os.environ['GITHUB_EVENT_NAME']
    payload = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    publish = False
    if event == 'pull_request':
        base, head = payload['pull_request']['base']['sha'], payload['pull_request']['head']['sha']
        paths = subprocess.check_output(['git', 'diff', '--no-renames', '--name-only', '-z', base + '...' + head]).decode().rstrip('\0').split('\0')
        plan, reasons = path_plan(paths)
    elif event == 'push':
        plan = dispatch_plan('all', 'all')
        reasons = ['main: every API 33 session gates; every API 35 session is reported']
    elif event == 'workflow_dispatch':
        inputs = payload.get('inputs', {})
        publish = inputs.get('publish') in (True, 'true')
        if publish and (os.environ['GITHUB_REF'] != 'refs/heads/main' or os.environ['GITHUB_REPOSITORY'] != 'sayenah/ES-DE-Plus'):
            raise ValueError('Publication is restricted to an explicit main dispatch in the canonical repository')
        plan = dispatch_plan(inputs.get('images', 'all'), inputs.get('sessions', 'all'), publish)
        reasons = [f'manual: {plan}; publish={publish}']
    else:
        raise ValueError(f'Unsupported event: {event}')
    report = json.dumps(dict(plan=plan, reasons=reasons, api35_gating=API35_GATING), indent=2)
    print(report, flush=True)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('Android sessions\n```json\n' + report + '\n```\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
        out.write('matrix=' + json.dumps(matrix(plan)) + '\n')
        out.write('publish=' + str(publish).lower() + '\n')


def self_test():
    own = ['.github/workflows/build-android.yml', '.github/workflows/build-linux.yml',
           'android/ci_selection.py', 'android/ci-sessions.toml', 'android/README.md',
           'android/release_controls.py', 'android/distribution.py', 'android/ci_apks.py', 'android/test_signing.py']
    assert path_plan(['docs/protocol.md'])[0] == {'api33': ['core']}
    assert path_plan(own)[0] == {'api33': list(PHASES), 'api35': ['core', 'touch']}
    assert path_plan(['android/app/src/main/kotlin/org/esdeplus/frontend/MainActivity.kt'])[0] == {
        'api33': ['core', 'lifecycle', 'assets', 'app-data', 'clear-task', 'manager-direct', 'manager-scoped'], 'api35': ['core']}
    assert path_plan(['android/pdf_smoke.py'])[0] == {'api33': ['core', 'pdf-direct', 'pdf-scoped']}
    assert path_plan(['android/SmokeMenuFocus.java'])[0] == {'api33': list(PHASES), 'api35': ['core', 'touch']}
    assert path_plan(['android/app/src/debug/kotlin/org/esdeplus/frontend/RuntimeSmoke.kt'])[0] == {'api33': list(PHASES), 'api35': ['core', 'touch']}
    assert path_plan(['android/smoke_session.py'])[0] == {'api33': list(PHASES), 'api35': ['core', 'touch']}
    assert path_plan(['android/clear_task_smoke.py'])[0] == {'api33': ['core', 'clear-task']}
    assert path_plan(['android/network_navigation.py'])[0] == {'api33': ['core', 'integration', 'pdf-scoped']}
    assert path_plan(['es-app/src/guis/ThemeRepositoryTrust.cpp'])[0] == {'api33': ['core', 'integration', 'pdf-scoped']}
    assert path_plan(['android/app/src/main/kotlin/org/esdeplus/frontend/NativeBridge.kt'])[0] == {'api33': list(PHASES), 'api35': ['core', 'touch']}
    assert path_plan(['android/emulator_manager_smoke.py'])[0] == {'api33': ['core', 'manager-direct', 'manager-scoped']}
    assert path_plan(['es-app/src/guis/GuiEmulatorManager.cpp'])[0] == {'api33': ['core', 'manager-direct', 'manager-scoped']}
    assert path_plan(['android/app_data_smoke.py'])[0] == {'api33': ['core', 'app-data']}
    assert path_plan(['android/audio_smoke.py'])[0] == {'api33': ['core', 'integration']}
    for path in ['es-core/src/InputOverlay.cpp', 'es-core/src/InputOverlayModel.h',
                 'es-core/src/TouchOverlayReset.h', 'android/touch_smoke.py',
                 'android/app/src/debug/kotlin/org/esdeplus/frontend/TouchSmoke.kt',
                 'resources/graphics/overlay/button_a.svg']:
        assert path_plan([path])[0] == {'api33': ['core', 'touch'], 'api35': ['core', 'touch']}
    touch_callers = ['es-core/src/GuiComponent.h', 'es-app/src/main.cpp',
                     'es-core/src/TouchOverlayReset.h', 'es-core/src/Settings.cpp',
                     'android/app/src/main/kotlin/org/esdeplus/frontend/ConfiguratorSession.kt',
                     'android/app/src/main/kotlin/org/esdeplus/frontend/ConfiguratorActivity.kt']
    for stem in ['es-core/src/Window', 'es-core/src/renderers/Renderer',
                 'es-core/src/guis/GuiDetectDevice', 'es-app/src/guis/GuiMenu',
                 'es-app/src/EmulatorManagerTouch', 'es-app/src/views/ViewController',
                 'es-app/src/CollectionSystemsManager', 'es-core/src/SearchTextInput',
                 'es-app/src/guis/SearchEntry', 'es-app/src/views/GamelistBase',
                 'es-app/src/guis/GuiGamelistOptions']:
        touch_callers.extend(stem + suffix for suffix in ('.h', '.cpp'))
    for path in touch_callers:
        plan, _ = path_plan([path])
        assert 'touch' in plan['api33'] and 'touch' in plan['api35'], path
    assert set(dispatch_plan('all', 'all')) == {'api33', 'api35'}
    assert set(dispatch_plan('api34,tv36', 'assets')) == {'api34', 'tv36'}
    rows = matrix(dispatch_plan('all', 'all'))['include']
    assert len(rows) == len(PHASES) * 2
    assert all(row['informational'] == (row['image'] == 'api35' and not API35_GATING)
               for row in rows), 'API 35 gating applies to every session, including touch'
    for images, sessions, publish in [('api35', 'core', True), ('api33,api35,api34', 'all', True),
                                      ('api99', 'all', False), ('all', '', False),
                                      ('api33,api33', 'all', False), ('all', 'core,', False)]:
        try:
            dispatch_plan(images, sessions, publish)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid selection escaped')
    dispatch_plan('all', 'all', True)
    assert set(CAPS) == set(PHASES), 'Register caps for every checked-in session'
    print('PASS: phone-only defaults; legacy explicit opt-in; additive PR/Android-15 map; validated publication/full selection; API35 gating includes touch; overlay caller coverage; one fresh job per session')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['select', 'self-test'])
    args = parser.parse_args()
    self_test() if args.mode == 'self-test' else select()
