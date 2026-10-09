#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Shared smoke assertions and positive controls.
import pathlib


def no_generation(output):
    assert 'Generating ROM directory structure' not in output, output


def warm_entry(output, home):
    assert ('SDL entry reused via onNewIntent' in output or
            'Focused redirect forwarding' in output), output
    assert f'HOME={str(home).lower()}' in output, output


def grants(count, expected):
    assert count == expected, f'Persisted tree grants: {count}; expected {expected}'


def probe_passed(output, diagnostic):
    assert diagnostic in output, output


def onboarding_disabled(changed):
    assert changed, 'Cannot disable stock TV onboarding component'


def held_restored(records, nodes, pid, old_pid, app):
    assert pid.isdigit() and pid != old_pid, f'Host did not restart: {old_pid} -> {pid}'
    assert len(records) == 2 and len({r[1] for r in records}) == 1, records
    assert sum(r[0] == 'ConfiguratorActivity' for r in records) == 1, records
    assert any(n.get('package') == app and
               n.get('text', '').startswith('Configure ') for n in nodes), nodes


def positive_controls():
    rejected = []

    def reject(name, action):
        try:
            action()
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError('Positive control escaped: ' + name)

    # The generation line comes from the current upstream implementation,
    # so a spelling change cannot quietly make the absence check vacuous.
    source = pathlib.Path('es-app/src/SystemData.cpp').read_text()
    line = next(line for line in source.splitlines() if 'Generating ROM directory structure' in line)
    no_generation('Application startup time: 1s')
    reject('actual ROM-generation diagnostic', lambda: no_generation(line))
    for home in [False, True]:
        warm_entry(f'Focused redirect forwarding entry; HOME={str(home).lower()}', home)
        warm_entry(f'SDL entry reused via onNewIntent; HOME={str(home).lower()}', home)
        reject('missing entry diagnostic', lambda: warm_entry(f'HOME={str(home).lower()}', home))
        reject('wrong HOME state', lambda: warm_entry(f'Focused redirect forwarding; HOME={str(not home).lower()}', home))
    grants(1, 1)
    reject('cancel revoked selected grant', lambda: grants(0, 1))
    probe_passed('PASS: probe', 'PASS: probe')
    reject('failed runtime probe', lambda: probe_passed('FAIL: probe', 'PASS: probe'))
    onboarding_disabled(True)
    reject('onboarding control failed', lambda: onboarding_disabled(False))
    records = [('HomeEntry', '7'), ('ConfiguratorActivity', '7')]
    nodes = [{'package': 'smoke.app', 'text': 'Configure ES-DE Plus'}]
    held_restored(records, nodes, '200', '100', 'smoke.app')
    reject('dead relaunched host', lambda: held_restored(records, nodes, '', '100', 'smoke.app'))
    reject('old host survived', lambda: held_restored(records, nodes, '100', '100', 'smoke.app'))
    reject('missing configurator record', lambda: held_restored(records[:1], nodes, '200', '100', 'smoke.app'))
    reject('separate configurator task', lambda: held_restored([records[0], ('ConfiguratorActivity', '8')], nodes, '200', '100', 'smoke.app'))
    reject('two frontend records', lambda: held_restored([records[0], records[0]], nodes, '200', '100', 'smoke.app'))
    reject('stock launcher obscures configuration', lambda: held_restored(records, [], '200', '100', 'smoke.app'))
    return 'PASS: production smoke assertions reject: ' + ', '.join(rejected) + '.\n'


if __name__ == '__main__':
    print(positive_controls(), end='')
