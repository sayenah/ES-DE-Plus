#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Forced-relaunch assertions and CI controls.
import re


ASSETS_PATHS = 0x80000000


def font_draft(nodes, app):
    return sorted((n.get('text'), n.get('checked')) for n in nodes
                  if n.get('package') == app and n.get('checkable') == 'true')


def font_outcome(output, pid, task):
    lines = [line for line in output.splitlines()
             if re.match(r'\S+\s+\S+\s+' + re.escape(pid) + r'\s+\d+\s+[VDIWEF]\s', line)]
    destroys = [line for line in lines if 'Destroying SDL activity' in line]
    if destroys:
        for line in destroys:
            match = re.search(r'configurationChanges=0x(-?[0-9a-fA-F]+)\b', line)
            assert match, 'SDL relaunch has no configuration mask: ' + line
            mask = int(match[1], 16) & 0xffffffff
            assert mask & ASSETS_PATHS, 'SDL relaunch without ASSETS_PATHS is a hard failure: ' + line
            assert ('held=true' in line and 'finishing=false' in line and
                    'changingConfigurations=true' in line and
                    re.search(r'\btask=' + re.escape(task) + r'\b', line)), line
        return dict(outcome='ENVIRONMENTAL_ASSETS_PATHS_RELAUNCH', mask=f'0x{mask:08x}')
    if any('SDL activity configuration handled' in line for line in lines):
        return dict(outcome='IN_PLACE')
    return None


def font_recovery(before_pid, after_pid, before_task, records, configurator, draft, output, app):
    assert after_pid.isdigit() and after_pid != before_pid, 'Forced relaunch needs a new frontend PID'
    hosts = [r for r in records if r[0] != 'ConfiguratorActivity']
    assert len(hosts) == 1 and hosts[0][1] == before_task, ('Forced relaunch changed task', records)
    assert configurator and any(r[0] == 'ConfiguratorActivity' and r[1] == before_task
                               for r in records), 'Configurator did not return in the same task'
    assert draft, 'Forced relaunch lost the configurator draft'
    assert 'ANR in ' + app not in output, output
    frontend = '\n'.join(line for line in output.splitlines() if re.match(
        r'\S+\s+\S+\s+(?:' + re.escape(before_pid) + '|' + re.escape(after_pid) + r')\s+\d+\s', line))
    assert 'FATAL EXCEPTION' not in frontend and 'Fatal signal' not in frontend, frontend


def controls():
    prefix = '10-16 07:59:27.367  4970  4970 I ES-DE-Plus: '
    destruction = ('Destroying SDL activity held=true finishing=false changingConfigurations=true '
                   'configurationChanges=0x{} task=12 visibleForRestart=false')
    handled = prefix + 'SDL activity configuration handled'
    assert font_outcome(handled, '4970', '12') == dict(outcome='IN_PLACE')
    assert font_outcome(handled, '6629', '12') is None
    for mask in ('-70000000', '90000000', '-80000000', '80000000'):
        result = font_outcome(prefix + destruction.format(mask), '4970', '12')
        assert result['outcome'] == 'ENVIRONMENTAL_ASSETS_PATHS_RELAUNCH'
    records = [('MainActivity', '12', ''), ('ConfiguratorActivity', '12', '')]
    app = 'org.esdeplus.frontend'
    good = ['4970', '6629', '12', records, True, True, '', app]
    font_recovery(*good)
    bad = [
        lambda: font_outcome(handled + '\n' + prefix + destruction.format('10000000'), '4970', '12'),
        lambda: font_outcome(prefix + destruction.format('50007fff'), '4970', '12'),
        lambda: font_outcome(prefix + destruction.format('0'), '4970', '12'),
        lambda: font_outcome(prefix + destruction.format('90000000').replace('task=12', 'task=13'), '4970', '12'),
        lambda: font_outcome(prefix + destruction.format('90000000').replace('held=true', 'held=false'), '4970', '12'),
    ]
    for index, value in [(1, '4970'), (1, ''), (3, [('MainActivity', '13', '')]),
                         (4, False), (5, False), (6, 'ANR in ' + app), (6, prefix + 'FATAL EXCEPTION')]:
        arguments = list(good)
        arguments[index] = value
        bad.append(lambda arguments=arguments: font_recovery(*arguments))
    for check in bad:
        try:
            check()
        except AssertionError:
            continue
        raise AssertionError('A forced-relaunch positive control escaped')
    return ('PASS: negative controls: in-place handling; signed/unsigned ASSETS_PATHS masks; complete recovery.\n'
            'PASS: positive controls: declared-only/zero masks (even after handled), wrong task/hold; '
            'unchanged/missing PID, changed task, absent configurator, lost draft, ANR and crash rejected.\n')


if __name__ == '__main__':
    print(controls(), end='')
