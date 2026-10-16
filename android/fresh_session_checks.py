#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Forced-relaunch assertions and CI controls.
import re


ASSETS_PATHS = 0x80000000


class ReadinessTimeout(AssertionError):
    pass


def startup(attempt, dismissals, capture, stop, record, app, is_ready):
    # A dismissal from an earlier launch cannot authorise this start. Once
    # readiness is observed, every later timeout is a product/test failure.
    before = dismissals()
    ready = False
    def reached_readiness():
        nonlocal ready
        ready = True
    for number in range(2):
        try:
            attempt(reached_readiness)
        except ReadinessTimeout:
            # Always capture the live state before the caller can clean up.
            output = capture(number)
            ready = ready or is_ready()
            after = dismissals()
            crash = ('FATAL EXCEPTION' in output or 'Fatal signal' in output or
                     re.search(r'ANR in ' + re.escape(app) + r'\b', output))
            retry = number == 0 and after > before and not ready and not crash
            record(dict(outcome='RELAUNCH_STOCK_ONBOARDING' if retry else 'HARD_TIMEOUT',
                        attempt=number + 1, reached_readiness=ready,
                        dismissals_before=before, dismissals_after=after,
                        relaunches=number, crash_or_anr=bool(crash)))
            if not retry:
                raise
            stop()
        else:
            record(dict(outcome='READY', attempt=number + 1, reached_readiness=ready,
                        dismissals_before=before, dismissals_after=dismissals(), relaunches=number))
            return


def copy_pid(output):
    # Bind the interruption to the real font-copy event, after Android has
    # initialised the process, rather than two early process-name snapshots.
    copying = set()
    for line in output.splitlines():
        match = re.match(r'\S+\s+\S+\s+(\d+)\s+\d+\s+I\s+ES-DE-Plus\s*:\s+(.*)', line)
        if match:
            if match[2].startswith('Resource copy required=true'):
                copying.add(match[1])
            if match[1] in copying and match[2].startswith('Installed resource: fonts/'):
                return match[1]
    return None


def font_draft(nodes, app, scoped_path):
    fields = [(n.get('text'), n.get('checked')) for n in nodes
              if n.get('package') == app and n.get('checkable') == 'true']
    if any(n.get('package') == app and scoped_path in n.get('text', '') for n in nodes):
        fields.append(('scoped_path', scoped_path))
    return sorted(fields)


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
    nodes = [dict(package=app, text='Create system folders', checkable='true', checked='false'),
             dict(package=app, text='Put games in /owned/ROMs')]
    draft = font_draft(nodes, app, '/owned/ROMs')
    assert draft == [('Create system folders', 'false'), ('scoped_path', '/owned/ROMs')]
    assert font_draft(nodes[:1], app, '/owned/ROMs') != draft
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
    startup_controls()
    assert copy_pid(prefix + 'Resource copy required=true') is None
    assert copy_pid(prefix + 'Installed resource: locale/en_US') is None
    copying = prefix + 'Resource copy required=true\n'
    assert copy_pid(prefix + 'Installed resource: fonts/DejaVuSans.ttf') is None
    assert copy_pid(copying + prefix.replace('4970', '6629') + 'Installed resource: fonts/DejaVuSans.ttf') is None
    assert copy_pid(copying + prefix + 'Installed resource: fonts/DejaVuSans.ttf') == '4970'
    return ('PASS: negative controls: in-place handling; signed/unsigned ASSETS_PATHS masks; complete recovery.\n'
            'PASS: positive controls: declared-only/zero masks (even after handled), wrong task/hold; '
            'unchanged/missing PID, changed task, absent configurator, lost draft, ANR and crash rejected.\n'
            'PASS: startup controls: one relaunch after a dismissal during this start; live capture before stop; '
            'no relaunch without a new dismissal, no second relaunch, none after readiness or a crash/ANR.\n'
            'PASS: copy probe binds its PID only to the actual font-copy event.\n')


def startup_controls():
    def exercise(dismiss=False, initial=0, reached=False, late_ready=False, fail_twice=False, crash=''):
        count = [initial]
        events, records = [], []
        def attempt(ready):
            events.append('start')
            if events.count('start') == 2 and not fail_twice:
                ready()
                return
            if dismiss:
                count[0] += 1
            if reached:
                ready()
            raise ReadinessTimeout('control')
        def capture(number):
            events.append('capture')
            return crash
        failed = False
        try:
            startup(attempt, lambda: count[0], capture, lambda: events.append('stop'), records.append,
                    'org.esdeplus.frontend', lambda: late_ready)
        except ReadinessTimeout:
            failed = True
        return events, records, failed
    events, records, failed = exercise(dismiss=True)
    assert not failed and events == ['start', 'capture', 'stop', 'start']
    assert [r['outcome'] for r in records] == ['RELAUNCH_STOCK_ONBOARDING', 'READY']
    assert records[-1]['relaunches'] == 1
    events, records, failed = exercise(dismiss=True, fail_twice=True)
    assert failed and events == ['start', 'capture', 'stop', 'start', 'capture']
    assert records[-1]['outcome'] == 'HARD_TIMEOUT'
    for options in (dict(), dict(initial=1), dict(dismiss=True, reached=True),
                    dict(dismiss=True, late_ready=True),
                    dict(dismiss=True, crash='FATAL EXCEPTION'),
                    dict(dismiss=True, crash='Fatal signal 11'),
                    dict(dismiss=True, crash='ANR in org.esdeplus.frontend')):
        events, records, failed = exercise(**options)
        assert failed and events == ['start', 'capture'] and records[0]['outcome'] == 'HARD_TIMEOUT'


if __name__ == '__main__':
    print(controls(), end='')
