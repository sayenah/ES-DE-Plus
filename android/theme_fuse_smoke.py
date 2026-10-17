#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. App-view/lower-file retirement controls.
import hashlib
import json
import pathlib
import re
import shlex
import stat


def media_provider(h):
    packages = h.shell('pm', 'list', 'packages', '--apex-only', '--show-versioncode')
    records = [line for line in packages.splitlines() if 'mediaprovider' in line.lower()]
    h.evidence.joinpath('media-provider-version.txt').write_text('\n'.join(records) + '\n')
    versions = [int(value) for line in records for value in re.findall(r'versionCode:(\d+)', line)]
    assert len(versions) == 1, ('MediaProvider APEX version is not uniquely recorded', records)
    if h.api == 31:
        assert versions[0] < 311112000, ('API31 requires the unfixed MediaProvider leg', records)
    return versions[0]


def request(h):
    if h.api not in (31, 34):
        return
    for name in ('result', 'snapshot', 'ack'):
        h.shell('run-as', h.app, 'rm', '-f', 'files/theme-fuse.' + name)
    h.shell('run-as', h.app, 'sh', '-c',
            'printf %s ' + shlex.quote('ES-DE-Plus FUSE controls\n') + ' > files/theme-fuse.request')


def transition(before, after, name):
    if not before['exists'] and after['exists']:
        return 'created'
    if before['exists'] and not after['exists']:
        return 'deleted'
    if before == after:
        return 'unchanged'
    return 'appended' if name.startswith('logs/') else 'replaced'


def collect(h):
    if h.api not in (31, 34):
        return
    root = h.shell('readlink', '-f', h.data_root).strip()
    assert root.startswith('/storage/emulated/0/'), root
    allowed = (re.escape(root) +
               r'/theme-trust\.[^/\n]+/fuse-(?:on|off)/themes/(?:themes-list|original)/\.git')
    observed = [0]
    negative = [0]
    baselines = {}
    previous = {}
    coverage = {}
    result_file = h.evidence / 'theme-fuse-controls.txt'
    samples = h.evidence / 'theme-fuse-view-lower.txt'
    samples.write_text('')

    def acknowledge(number, state):
        h.shell('run-as', h.app, 'sh', '-c', 'printf %s ' +
                shlex.quote(f'{number} {state}\n') + ' > files/theme-fuse.ack')

    def step():
        result = h.shell('run-as', h.app, 'cat', 'files/theme-fuse.result', check=False)
        if result:
            result_file.write_text(result)
            return True
        assert h.shell('pidof', h.app, check=False).strip(), 'FUSE control process crashed'
        raw = h.shell('run-as', h.app, 'cat', 'files/theme-fuse.snapshot', check=False)
        if not raw or not raw.endswith('}'):
            return False  # A snapshot is published before its bounded rendezvous.
        record = json.loads(raw)
        number = record['sequence']
        if number <= observed[0]:
            return False
        directory = record['directory']
        assert re.fullmatch(allowed, directory), directory
        lower = '/data/media/0/' + directory.removeprefix('/storage/emulated/0/')
        mismatches = []
        lower_files = {}
        for entry in record['files']:
            relative = pathlib.PurePosixPath(entry['path'])
            assert not relative.is_absolute() and '..' not in relative.parts, entry
            target = lower + '/' + str(relative)
            info = h.shell('sh', '-c', shlex.join(['stat', '-c', '%f %s', target]) +
                           ' 2>&1', check=False).strip()
            present = bool(re.fullmatch(r'[0-9a-fA-F]+ \d+', info))
            assert present or 'No such file or directory' in info, ('Lower readback unavailable', target, info)
            value = {'exists': present}
            if present:
                mode, size = info.split()
                assert stat.S_ISREG(int(mode, 16)), ('Lower metadata is not regular', target, info)
                data = h.adb('exec-out', shlex.join(['cat', target]), binary=True)
                assert len(data) == int(size), ('Lower readback length changed', target, info, len(data))
                value.update(size=int(size), read=len(data), hash=hashlib.sha1(
                    b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest())
            lower_files[str(relative)] = value
            view = {key: value for key, value in entry.items() if key != 'path'}
            if view != value:
                mismatches.append(str(relative))
        record['lower'] = lower_files
        record['mismatches'] = mismatches
        with samples.open('a') as output:
            output.write(json.dumps(record, ensure_ascii=False) + '\n')
        if record['mode'] == 'off':
            negative[0] += bool(mismatches)
        else:
            if mismatches:
                acknowledge(number, 'STOP')
                raise AssertionError(f'AC-3 view/lower mismatch {mismatches}; section 9, no rerun')
            key = (directory, record['clone'])
            config = lower_files['config']
            if record['stage'] == 'clone-after-listing':
                baselines[key] = config
            else:
                if config != baselines[key]:
                    acknowledge(number, 'STOP')
                    raise AssertionError('AC-5 lower config changed across update; section 9')
            if record['stage'] == 'after-update-listing':
                before = previous[key]
                for name in set(before) | set(lower_files):
                    kind = transition(before.get(name, {'exists': False}),
                                      lower_files.get(name, {'exists': False}), name)
                    coverage.setdefault(name, {}).setdefault(kind, 0)
                    coverage[name][kind] += 1
            previous[key] = lower_files
        observed[0] = number
        acknowledge(number, 'CONTINUE')
        return False

    rooted = False
    try:
        response = h.adb('root')
        assert 'cannot run as root' not in response, 'Required lower readback unavailable'
        rooted = True
        h.adb('wait-for-device')
        h.wait_for(lambda: h.shell('id', '-u').strip() == '0', 'lower readback shell', 10)
        h.wait_for(step, '20 real clones x 3 changing downloader updates; no operation retries', 900)
    finally:
        if rooted:
            h.adb('unroot', check=False)
            h.adb('wait-for-device')
            h.wait_for(lambda: h.shell('id', '-u', check=False).strip() == '2000',
                       'ordinary shell after FUSE controls', 10)
        h.evidence.joinpath('theme-fuse-coverage.txt').write_text(json.dumps(coverage, indent=2))
        h.evidence.joinpath('theme-fuse-retire-off.txt').write_text(
            f'API={h.api} snapshots_with_mismatch={negative[0]}; '
            'diagnostic only; no mandatory failure was retried\n')
    result = result_file.read_text()
    assert 'FAIL:' not in result and 'PASS: FUSE retirement controls;' in result, result
    assert result.count('updates=3 actual downloader paths\n') == 20, result
    for name in ('index', 'FETCH_HEAD', 'packed-refs', 'HEAD'):
        assert coverage.get(name, {}).get('replaced', 0) > 0, ('Missing replacement coverage', name, coverage)
    for prefix in ('refs/heads/', 'refs/remotes/'):
        assert any(name.startswith(prefix) and values.get('replaced', 0) > 0
                   for name, values in coverage.items()), (prefix, coverage)
    print('PASS: retirement on;20 changing clones x3 updates; lower config unchanged; '
          'metadata view/lower equal; required replacement coverage recorded', flush=True)
