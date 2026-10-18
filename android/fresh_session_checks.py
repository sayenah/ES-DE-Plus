#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Forced-relaunch assertions and CI controls.
import datetime
import re

import smoke_checks


ASSETS_PATHS = 0x80000000


def startup_preemption(capture, app, stock_package):
    # Inspect live focus, never last-ANR snapshots. The caller supplies the
    # complete log since this start and since the guard's completed dismissal.
    window = smoke_checks.live_window(capture['focus'])
    focus = next((line.split('mCurrentFocus=', 1)[1].strip()
                  for line in window.splitlines() if 'mCurrentFocus=' in line), '')
    # Splash/starting windows also belong to the frontend. Missing focus is
    # not proof that another window preempted it.
    frontend_focused = not focus or bool(re.search(r'\bnull\b', focus)) or bool(
        re.search(r'(?<![\w.])' + re.escape(app) + r'(?![\w.])', focus))
    stock_focused = smoke_checks.package_window_focused(window, stock_package)
    output = capture['logcat']
    created = any(
        ('ES-DE-Plus' in line and 'Creating sole SDL activity' in line) or
        ('wm_on_create_called' in line and app + '.' in line)
        for line in output.splitlines())
    died = bool(re.search(r'Process ' + re.escape(app) + r' \(pid \d+\) has died', output) or
                re.search(r'am_proc_died.*\[\d+,\s*\d+,\s*' + re.escape(app) + r'[,\]]', output))
    finishing = any('ES-DE-Plus' in line and 'Destroying SDL activity' in line and
                    'finishing=true' in line for line in output.splitlines())
    after = capture['after_dismissal']
    allowed = (not frontend_focused and not died and not finishing and
               (stock_focused or (after is not None and not created)))
    return dict(preemption_proven=allowed, frontend_focused=frontend_focused,
                stock_home_focused=stock_focused, activity_created_since_start=created,
                frontend_process_died=died, frontend_finishing=finishing,
                dismissal_marker_present=after is not None)


class ReadinessTimeout(AssertionError):
    pass


class HostStartupFailure(AssertionError):
    pass


def startup_trace(kept, snapshot, marker):
    source = kept if marker in kept else snapshot
    assert marker and marker in source, 'Startup marker missing; cannot classify timeout'
    marker_line = next(line for line in source.splitlines() if marker in line)
    assert re.match(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{6} ', marker_line), 'Startup timestamp format missing'
    cutoff = marker_line[:26]
    # A reconnected observer backfills buffers, including duplicate markers.
    # Keep earlier captured events even if that later dump lost those events.
    lines = dict.fromkeys((kept + '\n' + snapshot).splitlines())
    # UTC/year timestamps retain causal order across buffer clears/evictions;
    # stable sorting preserves the stream's order for equal timestamps.
    return '\n'.join(sorted((line for line in lines if re.match(r'\d{4}-\d\d-\d\d ', line)
                             and line[:26] >= cutoff), key=lambda line: line[:26]))


def startup_host_created(output, pid):
    if not pid.isdigit():
        return None
    thread = r'^\S+\s+\S+\s+(?:[+-]\d{4}\s+)?' + re.escape(pid) + r'\s+\d+\s'
    return max((' '.join(line.split()[:2]) for line in output.splitlines()
                if re.match(thread, line) and 'Creating sole SDL activity' in line), default=None)


def startup_log_fresh(native, before, after, created):
    if (not created or before != after or
            'Application startup time:' not in native or 'Error:' in native):
        return False
    try:
        # Log::init rotates the old logfile before a new process writes. A
        # stable file written after replacement creation cannot be the old
        # PID's leftover readiness marker. No native log is modified here.
        modified = datetime.datetime.fromisoformat(before.split('|')[2].replace(' +', '+').replace(' -', '-'))
        created = datetime.datetime.fromisoformat(created).replace(tzinfo=datetime.timezone.utc)
        return modified.tzinfo is not None and modified >= created
    except (IndexError, KeyError, ValueError):
        return False


def startup_native_ready(chains, native, pid, before, after):
    return bool(chains and all(row['complete'] for row in chains) and
                pid == chains[-1]['new_pid'] and
                startup_log_fresh(native, before, after, chains[-1]['new_host_created']))


def startup_restart(output, app, current_pid='', ready=None):
    lines = output.splitlines()
    # UTC logcat adds an explicit timezone column on Android; ordinary
    # threadtime captures omit it. Both carry the same PID/TID fields.
    thread = r'\S+\s+\S+\s+(?:[+-]\d{4}\s+)?(\d+)\s'
    chains = []
    seen = set()
    for index, line in enumerate(lines):
        if 'Destroying SDL activity' not in line or 'changingConfigurations=true' not in line:
            continue
        pid = re.match(thread, line)[1]
        if pid in seen:
            continue
        seen.add(pid)
        later = lines[index + 1:]
        died = any(re.search(r'Process ' + re.escape(app) + r' \(pid ' + pid + r'\) has died', text) or
                   re.search(r'am_proc_died.*\[\d+,\s*' + pid + r',\s*' + re.escape(app) + r'[,\]]', text)
                   for text in later)
        helper = re.escape(app) + r'/(?:\.|' + re.escape(app) + r'\.)FrontendRestartActivity\b'
        requested = next((n for n, text in enumerate(later) if re.search(r'\bSTART u\d+ .*cmp=' + helper, text)), None)
        storage_before_destroy = False
        retirement_floor = -1
        if requested is None:
            # Explicit data re-selection requests the helper before retiring
            # the SDL host. Bind that earlier request to this old PID's marker;
            # ordinary configuration destroys still need their later request.
            storage = next((n for n in range(index - 1, -1, -1)
                            if re.search(r'\bI ES-DE-Plus: Storage selection requires a fresh frontend start$', lines[n]) and
                            (actor := re.match(thread, lines[n])) and actor[1] == pid), None)
            prior = [n for n in range(storage + 1, index)
                     if re.search(r'\bSTART u\d+ .*cmp=' + helper, lines[n])] if storage is not None else []
            if len(prior) == 1:
                later = lines[storage + 1:]
                requested = prior[0] - storage - 1
                retirement_floor = index - storage - 1
                storage_before_destroy = True
        if died and requested is None:
            raise HostStartupFailure('G-30 CONFIGURATION_DESTROY_WITHOUT_HELPER: PID ' + pid + ': ' + line)
        started = next((n for n, text in enumerate(later) if requested is not None and n >= requested and
                        'FrontendRestartActivity' in text and any(token in text for token in
                        ('Start proc ', 'Displayed ', 'wm_on_create_called', 'wm_on_resume_called'))), None)
        retired = next((n for n, text in enumerate(later) if started is not None and n >= started and
                        n > retirement_floor and
                        'SDL process ' + pid + ' retired; restarting entry' in text), None)
        creation = next((text for n, text in enumerate(later)
                         if retired is not None and n > retired and 'Creating sole SDL activity' in text), None)
        new = re.match(thread, creation)[1] if creation else None
        complete = requested is not None and started is not None and retired is not None and new not in (None, pid)
        if ready is not None and (not complete or 'Application startup time:' not in ready or 'Error:' in ready):
            raise HostStartupFailure('G-30 INCOMPLETE_RESTART_CHAIN: PID ' + pid + ' -> ' + str(new))
        chains.append(dict(old_pid=pid, restart_requested=requested is not None,
                           storage_request_before_destroy=storage_before_destroy,
                           helper_started=started is not None, retired=retired is not None,
                           new_pid=new, new_host_created=' '.join(creation.split()[:2]) if creation else None,
                           complete=complete))
    if ready is not None and chains and current_pid != chains[-1]['new_pid']:
        raise HostStartupFailure('G-30 RESTART_PID_NOT_LIVE: ' + current_pid)
    return chains


def startup(attempt, dismissals, capture, stop, record, app, is_ready,
            stock_package='com.google.android.tvlauncher'):
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
        except (ReadinessTimeout, HostStartupFailure) as failure:
            # Always capture the live state before the caller can clean up.
            captured = capture(number)
            output = captured['logcat']
            after = dismissals()
            try:
                chains = startup_restart(output, app)
            except HostStartupFailure as host:
                record(dict(outcome='HARD_HOST_FAILURE', label=str(host), attempt=number + 1))
                raise
            if isinstance(failure, HostStartupFailure):
                record(dict(outcome='HARD_HOST_FAILURE', label=str(failure), attempt=number + 1))
                raise
            ready = ready or is_ready()
            crash = ('FATAL EXCEPTION' in output or 'Fatal signal' in output or
                     re.search(r'ANR in ' + re.escape(app) + r'\b', output))
            proof = startup_preemption(captured, app, stock_package)
            retry = (number == 0 and after > before and not ready and not crash and
                     proof['preemption_proven'] and not chains)
            record(dict(outcome='RELAUNCH_STOCK_ONBOARDING' if retry else 'HARD_TIMEOUT',
                        attempt=number + 1, reached_readiness=ready,
                        dismissals_before=before, dismissals_after=after,
                        relaunches=number, crash_or_anr=bool(crash), **proof))
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
    # Recovery must leave the replacement host alive as well. Classify its
    # destroy mask before rejecting a second relaunch (including G-29).
    second = font_outcome(output, after_pid, before_task)
    assert not second or second['outcome'] != 'ENVIRONMENTAL_ASSETS_PATHS_RELAUNCH', (
        'G-29 SECOND_ASSETS_PATHS_RELAUNCH: replacement SDL host destroyed', second)


def font_in_place(output, pid, task):
    final = font_outcome(output, pid, task)
    assert final and final['outcome'] == 'IN_PLACE', (
        'G-29 LATE_ASSETS_PATHS_RELAUNCH: SDL host destroyed after in-place handling', final)


def font_subsequent_destroys(output, before_pid, task):
    for line in output.splitlines():
        if 'Destroying SDL activity' not in line:
            continue
        match = re.match(r'\S+\s+\S+\s+(\d+)\s+\d+\s+[VDIWEF]\s', line)
        if match and match[1] != before_pid:
            second = font_outcome(line, match[1], task)
            raise AssertionError('G-29 SECOND_ASSETS_PATHS_RELAUNCH: replacement SDL host destroyed: ' + str(second))


def font_environmental_count(output):
    # Count each destroy, including one after the original host recovered.
    return sum(bool(int(match[1], 16) & ASSETS_PATHS) for line in output.splitlines()
               if 'Destroying SDL activity' in line
               for match in [re.search(r'configurationChanges=0x(-?[0-9a-fA-F]+)\b', line)] if match)


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
    forced = prefix + destruction.format('90000000')
    assert font_environmental_count(handled) == 0
    assert font_environmental_count(forced) == 1
    assert font_environmental_count(forced + '\n' + forced.replace('4970', '6629')) == 2
    font_in_place(handled, '4970', '12')
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
    for label, check in (
            ('G-29 LATE_ASSETS_PATHS_RELAUNCH', lambda: font_in_place(handled + '\n' + forced, '4970', '12')),
            ('G-29 SECOND_ASSETS_PATHS_RELAUNCH', lambda: font_recovery(
                *good[:6], forced + '\n' + forced.replace('4970', '6629'), app)),
            ('without ASSETS_PATHS', lambda: font_recovery(
                *good[:6], forced + '\n' + (prefix + destruction.format('10000000')).replace('4970', '6629'), app)),
            ('G-29 SECOND_ASSETS_PATHS_RELAUNCH', lambda: font_subsequent_destroys(
                forced + '\n' + forced.replace('4970', '6629'), '4970', '12')),
            ('without ASSETS_PATHS', lambda: font_subsequent_destroys(
                forced + '\n' + (prefix + destruction.format('10000000')).replace('4970', '6629'), '4970', '12'))):
        try:
            check()
        except AssertionError as error:
            assert label in str(error), str(error)
        else:
            raise AssertionError('A late/second destroy escaped: ' + label)
    startup_controls()
    startup_restart_controls()
    startup_readiness_controls()
    stock_banner_controls()
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
            'no relaunch without a new dismissal, no second relaunch, none after readiness or a crash/ANR; '
            'created/focused native hang and frontend-focused timeout stay HARD_TIMEOUT.\n'
            'PASS: MEDIUM-1: five QA self-exit/focus probes stay HARD_TIMEOUT; whole-start creation, '
            'finishing and event-buffer death veto recovery.\n'
            'PASS: LOW-1: no dismissal without action; historical/missing live window rejected; '
            'wm_on_create_called before dismissal prevents recovery.\n'
            'PASS: late/second G-29 destroys labelled and counted; replacement declared-bits destroy rejected.\n'
            'PASS: G-30 destroy/death without helper stays hard even after stock dismissal; '
            'restart needs request, helper start, retirement, new live PID and native startup; missing links rejected.\n'
            'PASS: explicit same-PID storage request may precede destruction; missing/wrong/stale/ambiguous evidence stays hard.\n'
            'PASS: kept startup trace survives circular-buffer eviction; stale/unstable native logfile '
            'cannot prove readiness for a replacement PID.\n'
            'PASS: actual startup predicate rejects the previous process log during bootstrap, '
            'empty/partial or changing files, missing creation and changed PID; fresh cold and known warm hosts qualify.\n'
            'PASS: late stock banner handled once inside the bounded clear condition; '
            'stuck/unknown controls stay hard without recording a dismissal or starting the frontend.\n'
            'PASS: copy probe binds its PID only to the actual font-copy event.\n')


def startup_controls():
    app = 'org.esdeplus.frontend'
    created = 'I ES-DE-Plus: Creating sole SDL activity task=12'
    stock = 'com.google.android.tvlauncher/.MainActivity'
    def exercise(dismiss=False, initial=0, reached=False, late_ready=False, fail_twice=False,
                 crash='', focus=stock, after='', logcat=None):
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
            return dict(logcat=crash + '\n' + (after or '') if logcat is None else logcat,
                        after_dismissal=after if dismiss else None,
                        focus='WINDOW MANAGER DISPLAY CONTENTS\n mCurrentFocus=Window{aa u0 ' + focus + '}')
        failed = False
        try:
            startup(attempt, lambda: count[0], capture, lambda: events.append('stop'), records.append,
                    'org.esdeplus.frontend', lambda: late_ready)
        except (ReadinessTimeout, HostStartupFailure):
            failed = True
        return events, records, failed
    events, records, failed = exercise(dismiss=True)
    assert not failed and events == ['start', 'capture', 'stop', 'start']
    assert [r['outcome'] for r in records] == ['RELAUNCH_STOCK_ONBOARDING', 'READY']
    assert records[-1]['relaunches'] == 1
    # Either live stock HOME focus or a complete whole-start log with no
    # activity creation proves preemption. Frontend focus always vetoes it.
    for options in (dict(dismiss=True, after=created),
                    dict(dismiss=True, focus='com.android.systemui/.Other', after='')):
        events, records, failed = exercise(**options)
        assert not failed and records[0]['preemption_proven']
    events, records, failed = exercise(dismiss=True, fail_twice=True)
    assert failed and events == ['start', 'capture', 'stop', 'start', 'capture']
    assert records[-1]['outcome'] == 'HARD_TIMEOUT'
    for options in (dict(), dict(initial=1), dict(dismiss=True, reached=True),
                    dict(dismiss=True, late_ready=True),
                    dict(dismiss=True, crash='FATAL EXCEPTION'),
                    dict(dismiss=True, crash='Fatal signal 11'),
                    dict(dismiss=True, crash='ANR in org.esdeplus.frontend'),
                    dict(dismiss=True, focus=app + '/.MainActivity', after=created),
                    dict(dismiss=True, focus=app + '/.MainActivity'),
                    dict(dismiss=True, focus='com.android.systemui/.Other', after=created),
                    dict(dismiss=True, focus='com.android.systemui/.Other', after=None)):
        events, records, failed = exercise(**options)
        assert failed and events == ['start', 'capture'] and records[0]['outcome'] == 'HARD_TIMEOUT'
    died = 'I ActivityManager: Process ' + app + ' (pid 3001) has died: cch+5 CEM'
    finishing = ('I ES-DE-Plus: Destroying SDL activity held=false finishing=true '
                 'changingConfigurations=false configurationChanges=0x0 task=12')
    # MEDIUM-1: the five independent QA self-exit probes must fail without
    # issuing any stop. Empty after_dismissal deliberately excludes creation.
    cases = {
        'created+finished+died, HOME focused': dict(logcat='\n'.join((created, finishing, died))),
        'created+died, HOME focused': dict(logcat=created + '\n' + died),
        'died before creation, systemui focus': dict(logcat=died, focus='com.android.systemui/.Other'),
        'created before dismissal, frontend splash': dict(logcat=created, focus='Splash Screen ' + app),
        'created before dismissal, null focus': dict(logcat=created, focus='null'),
        'finishing without death, HOME focused': dict(logcat=finishing),
        'event-buffer process death, HOME focused': dict(logcat='I am_proc_died: [0,3001,' + app + ',900,17]'),
        'created before dismissal, systemui focus': dict(logcat=created, focus='com.android.systemui/.Other'),
        'wm creation before dismissal, systemui focus': dict(
            logcat='I wm_on_create_called: [0,123,' + app + '.MainActivity,performCreate]',
            focus='com.android.systemui/.Other'),
    }
    for name, options in cases.items():
        events, records, failed = exercise(dismiss=True, **options)
        assert failed and events == ['start', 'capture'] and records[0]['outcome'] == 'HARD_TIMEOUT', name
        if 'splash' in name or 'null focus' in name:
            assert records[0]['frontend_focused'], name
    assert startup_preemption(dict(focus='WINDOW MANAGER DISPLAY CONTENTS\n mCurrentFocus=null',
                                   logcat='', after_dismissal=''), app,
                              'com.google.android.tvlauncher')['frontend_focused']
    assert startup_preemption(dict(focus='WINDOW MANAGER DISPLAY CONTENTS',
                                   logcat='', after_dismissal=''), app,
                              'com.google.android.tvlauncher')['frontend_focused']
    for invalid in ('WINDOW MANAGER LAST ANR\n mCurrentFocus=Window{aa u0 ' + stock + '}',
                    'mCurrentFocus=Window{aa u0 ' + stock + '}'):
        try:
            startup_preemption(dict(focus=invalid, logcat='', after_dismissal=''), app,
                               'com.google.android.tvlauncher')
        except AssertionError:
            pass
        else:
            raise AssertionError('Non-live focus authorised a startup relaunch')
    g30 = ('10-16 10:00:00.000 2001 2001 I ES-DE-Plus: Destroying SDL activity '
           'held=false finishing=false changingConfigurations=true configurationChanges=0x-80000000 task=8\n'
           '10-16 10:00:00.100 551 551 I ActivityManager: Process org.esdeplus.frontend (pid 2001) has died: fg TOP')
    events, records, failed = exercise(dismiss=True, crash=g30)
    assert failed and events == ['start', 'capture']
    assert records[0]['outcome'] == 'HARD_HOST_FAILURE' and 'G-30' in records[0]['label']
    events, records, failed = exercise(dismiss=True, crash=g30.splitlines()[0])
    assert failed and events == ['start', 'capture'] and records[0]['outcome'] == 'HARD_TIMEOUT'


def startup_restart_controls(zone=''):
    app = 'org.esdeplus.frontend'
    prefix = '2026-10-16 10:00:00.000000 ' + zone
    lines = [prefix + '2001 2001 I ES-DE-Plus: Destroying SDL activity changingConfigurations=true',
             prefix + '551 551 I ActivityTaskManager: START u0 {cmp=' + app + '/.FrontendRestartActivity}',
             prefix + '551 551 I ActivityManager: Process ' + app + ' (pid 2001) has died: fg TOP',
             prefix + '551 551 I ActivityTaskManager: Displayed ' + app + '/.FrontendRestartActivity',
             prefix + '2002 2002 I ES-DE-Plus: SDL process 2001 retired; restarting entry',
             prefix + '2003 2003 I ES-DE-Plus: Creating sole SDL activity task=8']
    native = 'Application startup time: 0.5s'
    chains = startup_restart('\n'.join(lines), app, '2003', native)
    assert chains[0]['complete']
    assert len(startup_restart('\n'.join(lines[:2] + [lines[0]] + lines[2:]), app, '2003', native)) == 1
    stamp = '123|100|2026-10-16 10:00:00.100000000 +0000'
    assert startup_native_ready(chains, native, '2003', stamp, stamp)
    old = '122|100|2026-10-16 09:59:59.900000000 +0000'
    assert not startup_native_ready(chains, native, '2003', old, old)
    assert not startup_native_ready(chains, native, '2003', old, stamp)
    assert not startup_native_ready(chains, native, '2001', stamp, stamp)
    assert not startup_native_ready(chains, native, '2003', '', '')
    malformed = '123|100|2026-10-16 10:00:00.100000000'
    assert not startup_native_ready(chains, native, '2003', malformed, malformed)
    assert not startup_native_ready(chains, '', '2003', stamp, stamp)
    assert not startup_native_ready(chains, native + '\nError: failed', '2003', stamp, stamp)
    bad = [(lines[:index] + lines[index + 1:], '2003', native) for index in (1, 3, 4, 5)]
    bad.extend((lines, pid, text) for pid, text in [('2001', native), ('', native),
                                                  ('2003', ''), ('2003', native + '\nError: failed')])
    for log, pid, text in bad:
        try:
            startup_restart('\n'.join(log), app, pid, text)
        except HostStartupFailure as failure:
            assert 'G-30' in str(failure)
        else:
            raise AssertionError('Incomplete host restart escaped')
    # PR15 run39102636049: the valid storage-reselection helper request
    # precedes the old host's destruction. Every other restart link is needed.
    storage = [prefix + '2001 2001 I ES-DE-Plus: Storage selection requires a fresh frontend start',
               lines[1], prefix + '2002 2002 I wm_on_create_called: [.FrontendRestartActivity]',
               lines[0], lines[2], lines[4], lines[5]]
    for log in (storage, storage[:2] + [storage[3], storage[2]] + storage[4:]):
        rows = startup_restart('\n'.join(log), app, '2003', native)
        assert rows[0]['complete'] and rows[0]['storage_request_before_destroy']
        assert startup_native_ready(rows, native, '2003', stamp, stamp)
        assert not startup_native_ready(rows, native, '2003', old, old)
    storage_bad = [storage[:n] + storage[n + 1:] for n in (0, 1, 2, 5, 6)]
    storage_bad.extend([
        [storage[0].replace('2001 2001', '2099 2099')] + storage[1:],
        [storage[0].replace('I ES-DE-Plus:', 'I OtherLog:')] + storage[1:],
        [storage[1], storage[0]] + storage[2:],  # A request before this marker is stale.
        storage[:2] + [storage[1]] + storage[2:],  # Ambiguous helper requests.
        storage[:3] + [storage[5]] + storage[3:5] + storage[6:],  # Retirement before destruction.
        storage[:5] + [storage[5].replace('process 2001', 'process 2099')] + storage[6:],
        storage[:6] + [storage[6].replace('2003 2003', '2001 2001')],
    ])
    for log in storage_bad:
        try:
            startup_restart('\n'.join(log), app, '2003', native)
        except HostStartupFailure:
            pass
        else:
            raise AssertionError('Unproven pre-destruction storage restart escaped')
    marker = prefix + '551 551 I ESDE-Smoke: control-marker\n'
    trace = startup_trace(marker + '\n'.join(lines), marker + '\n'.join(lines), 'control-marker')
    assert startup_restart(trace, app, '2003', native)[0]['complete']
    dead = [lines[0], lines[2]]
    # Buffer eviction may retain the shell marker while losing app lines.
    trace = startup_trace(marker + '\n'.join(dead), marker + dead[-1], 'control-marker')
    try:
        startup_restart(trace, app)
    except HostStartupFailure as failure:
        assert 'CONFIGURATION_DESTROY_WITHOUT_HELPER' in str(failure)
    else:
        raise AssertionError('Kept G-30 destroy was lost to buffer eviction')
    trace = startup_trace(marker + '\n'.join(dead), dead[-1], 'control-marker')
    assert 'Destroying SDL activity' in trace
    backfill = marker + dead[-1]
    trace = startup_trace(marker + '\n'.join(dead) + '\n' + backfill, backfill, 'control-marker')
    try:
        startup_restart(trace, app)
    except HostStartupFailure as failure:
        assert 'CONFIGURATION_DESTROY_WITHOUT_HELPER' in str(failure)
    else:
        raise AssertionError('Duplicate marker backfill concealed the kept G-30 destroy')
    trace = startup_trace(marker + '\n'.join(lines) + '\n' + marker + lines[-1],
                          marker + lines[-1], 'control-marker')
    assert len(startup_restart(trace, app, '2003', native)) == 1
    later = '2026-10-16 10:00:10.000000 551 551 I ESDE-Smoke: later-marker\n'
    trace = startup_trace(marker + '\n'.join(dead) + '\n' + later,
                          marker + '\n'.join(dead) + '\n' + later, 'later-marker')
    assert startup_restart(trace, app) == []
    if not zone:
        startup_restart_controls('+0000 ')


def startup_readiness_controls(source=None):
    # Exercise the real device-facing predicate without importing smoke.py's
    # command-line/device setup. Replay the bootstrap/log-rotation race from
    # run 39032722833, API 31 assets-configurator (also reachable on other SDKs).
    import ast
    from pathlib import Path
    import sys
    path = Path(__file__).with_name('smoke.py')
    node = next(node for node in ast.parse(path.read_text() if source is None else source).body
                if isinstance(node, ast.FunctionDef) and node.name == 'current_startup_ready')
    code = compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec')
    created = ('2026-10-17 14:56:13.133869 +0000 8817 8817 I ES-DE-Plus: '
               'Creating sole SDL activity task=18')
    native = 'Total game count: 2\nApplication startup time: 1960 ms\n'
    old = '122|100|2026-10-17 14:55:52.000000000 +0000'
    fresh = '123|100|2026-10-17 14:56:14.000000000 +0000'
    def evaluate(text, stamp, trace=created, known='8581', after=None, final_pid='8817', session=None):
        values = iter(text if isinstance(text, list) else [text, text])
        stamps = iter([stamp, stamp if after is None else after])
        pids = iter(['8817', final_pid])
        namespace = dict(startup_ready_pid=known, startup_baseline='previous baseline',
                         startup_monitoring=True, startup_log_marker='control', app='org.esdeplus.frontend',
                         logpath='/control/es_log.txt', log=lambda: next(values),
                         shell=lambda *args, **kwargs: next(stamps) if args[0] == 'stat' else next(pids),
                         adb=lambda *args: trace, startup_trace=lambda *args: trace,
                         session_logcat=lambda *args: trace if session is None else session,
                         fresh_session_checks=sys.modules[__name__])
        exec(code, namespace)
        return namespace['current_startup_ready'](), namespace['startup_ready_pid']
    assert evaluate(native, old)[0] is False, 'Previous native log accepted for a new bootstrap PID'
    assert evaluate([native, ''], old, after=fresh)[0] is False
    assert evaluate('Total game count: 2\n', fresh)[0] is False
    assert evaluate(native, fresh, trace='')[0] is False
    assert evaluate(native, fresh, after=old)[0] is False
    assert evaluate(native, fresh, final_pid='9000')[0] is False
    assert evaluate(native, fresh, trace=created.replace('8817 8817', '1001 8817'))[0] is False
    assert evaluate(native, fresh) == (True, '8817')
    assert evaluate(native, fresh, trace=created.replace(' +0000', '')) == (True, '8817')
    # First configuration creates the held SDL host before the Save marker.
    # Its session creation still proves freshness; restart chains stay scoped.
    assert evaluate(native, fresh, trace='', session=created) == (True, '8817'), \
        'Held host created before the Save marker was rejected'
    assert evaluate(native, old, trace='', session=created)[0] is False
    older_creation = created.replace('14:56:13.133869', '14:55:13.133869')
    assert evaluate(native, old, trace='', session=created + '\n' + older_creation)[0] is False
    assert evaluate(native, old, trace='', known='8817') == (True, '8817')


def stock_banner_controls(source=None):
    import ast
    from pathlib import Path
    import sys
    import tempfile
    import types
    import xml.etree.ElementTree as ET
    path = Path(__file__).with_name('smoke.py')
    nodes = [node for node in ast.parse(path.read_text() if source is None else source).body
             if isinstance(node, ast.FunctionDef) and node.name in ('dismiss_stock_onboarding', 'stock_ui_clear')]
    code = compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec')
    package = 'com.google.android.tvlauncher'
    def exercise(arrives=3, stuck=False, resource='tray_dismiss', vanished=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = dict(tutorial=True, homes=0, dismissed=False)
            actions = []
            def hierarchy():
                if state['tutorial']:
                    result = [ET.Element('node', {'package': package, 'resource-id': package + ':id/tutorial_negative_action',
                        'text': 'Dismiss', 'clickable': 'true', 'focused': 'true', 'bounds': '[0,0][10,10]'})]
                else:
                    state['homes'] += 1
                    result = [ET.Element('node', {'package': package, 'text': 'Home'})]
                    if not state['dismissed'] and state['homes'] >= arrives:
                        result.append(ET.Element('node', {'package': package, 'text': 'Dismiss',
                            'resource-id': package + ':id/' + resource, 'clickable': 'true', 'focused': 'true'}))
                (root / 'latest-ui.txt').write_text(''.join(ET.tostring(n, encoding='unicode') for n in result))
                return result
            def shell(*args):
                assert args[:2] == ('input', 'tap') or args[0] == 'log', ('Frontend action in stock guard', args)
                if args[0] == 'input':
                    actions.append('tutorial')
                    state['tutorial'] = False
            def ui(label):
                assert label == 'Dismiss' and resource == 'tray_dismiss'
                actions.append('banner')
                state['dismissed'] = not stuck
            def key(value):
                assert value == 'KEYCODE_DPAD_CENTER'
                actions.append('center')
            def wait_for(condition, description):
                for _ in range(8):
                    if condition(): return
                raise ReadinessTimeout(description)
            namespace = dict(onboarding_guard=True, dismissing_onboarding=False, last_onboarding_check=0,
                onboarding_dismissals=0, onboarding_dismissal_marker='', startup_number=5,
                stock_package=package, app='org.esdeplus.frontend', evidence=root, re=re,
                time=types.SimpleNamespace(monotonic=lambda: 100, monotonic_ns=lambda: 1000, sleep=lambda _: None),
                focused_window=lambda: 'mCurrentFocus=Window{x u0 ' + package + '/' + package +
                    ('.dialog.ShowDialogsActivity}' if state['tutorial'] else '.MainActivity}'),
                hierarchy=hierarchy, shell=shell, ui=ui, key=key, wait_for=wait_for,
                adb=lambda *args, **kwargs: b'control', screenshot=lambda *args: None,
                smoke_checks=smoke_checks, fresh_session_checks=sys.modules[__name__])
            if vanished:
                focus_reads = [0]
                original_focus = namespace['focused_window']
                def focus():
                    focus_reads[0] += 1
                    if focus_reads[0] > 1:
                        state['tutorial'] = False
                    return original_focus()
                namespace['focused_window'] = focus
            exec(code, namespace)
            failed = False
            try:
                namespace['dismiss_stock_onboarding']()
            except ReadinessTimeout:
                failed = True
            assert not namespace['dismissing_onboarding']
            return failed, namespace['onboarding_dismissals'], actions
    for arrival in (1, 3):
        assert exercise(arrives=arrival) == (False, 1, ['tutorial', 'banner']), \
            'A late supported banner prevented recording the completed dismissal'
    assert exercise(arrives=99) == (False, 1, ['tutorial'])
    assert exercise(arrives=99, vanished=True) == (False, 0, []), \
        'Tutorial vanished before the harness acted; a dismissal was incorrectly recorded'
    assert exercise(stuck=True) == (True, 0, ['tutorial', 'banner', 'center'])
    assert exercise(resource='unrecognised_dismiss') == (True, 0, ['tutorial'])


if __name__ == '__main__':
    print(controls(), end='')
