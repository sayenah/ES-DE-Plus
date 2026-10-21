#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Execute actual timing checks and deferral blocks.
import ast
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
path = root / 'android/search_screen_smoke.py'
spec = importlib.util.spec_from_file_location('search_screen_budget_subject', path)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)

def run_body(path):
    tree = ast.parse(path.read_text())
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run')

def compile_nodes(nodes):
    return compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                   'actual search timing checks', 'exec')

body = next(node for node in run_body(path).body if isinstance(node, ast.Try)).body
check = next(node for node in body if isinstance(node, ast.Try) and
             any('TimingBudgetExceeded' in ast.unparse(handler) for handler in node.handlers))
policy = next(node for node in run_body(path).body if isinstance(node, ast.Assign) and
              ast.unparse(node.targets[0]) == 'work_gating')
gate = compile_nodes([check])
caller = run_body(root / 'android/touch_smoke.py')
journey = next(node for node in caller.body if isinstance(node, ast.Try) and
               'search_screen_smoke.run(' in ast.unparse(node))
search_branch = next(node for node in journey.body if isinstance(node, ast.If) and
                     ast.unparse(node.test) == "suite != 'overlay'")
capture = next(node for node in search_branch.body if isinstance(node, ast.Try) and
               'search_screen_smoke.run(' in ast.unparse(node))
trailer = next(node for node in journey.body if isinstance(node, ast.If) and
               ast.unparse(node.test) == 'search_timing_failure is not None')
summary_writer = next(node for node in journey.body if isinstance(node, ast.Expr) and
                      "'touch-summary.txt'" in ast.unparse(node))
assert journey.body.index(search_branch) < journey.body.index(trailer) < journey.body.index(summary_writer)
flow_nodes = [ast.Assign([ast.Name('search_timing_failure', ast.Store())], ast.Constant(None)),
              search_branch, ast.Expr(ast.Call(ast.Name('baseline', ast.Load()), [], [])),
              trailer, summary_writer]
flow_function = ast.FunctionDef(name='exercise', args=ast.arguments(posonlyargs=[], args=[],
    kwonlyargs=[], kw_defaults=[], defaults=[]), body=flow_nodes, decorator_list=[])
flow = compile_nodes([flow_function, ast.Expr(ast.Call(ast.Name('exercise', ast.Load()), [], []))])
checks = 1

for api in [33, 35, 36]:
    namespace = dict(h=SimpleNamespace(api=api))
    exec(compile_nodes([policy]), namespace)
    work_gating = namespace['work_gating']
    assert work_gating == (api != 35)
    checks += 1
    for p95, maximum, entry, presented, message in [
        (20, 33, 150, 50, None),
        (50, 100, 150, 1000, None),
        (50.001, 100, 150, 50, 'Search work exceeded p95 50ms / max 100ms'),
        (20, 100.001, 150, 50, 'Search work exceeded p95 50ms / max 100ms'),
        (19, 32, 150.001, 50, 'Search entry exceeded p95 150ms'),
        (20.001, 33.001, 149, 100000, None),
        (22.6001, 28.2229, 72.324, 87.043, None),
        (37.6403, 77.0527, 74.4614, 141.538, None),
        (19, 143.496, 149, 49, 'Search work exceeded p95 50ms / max 100ms')]:
        summary = dict(samples=64, p95_ms=p95, max_ms=maximum,
                       entry=dict(p95_ms=entry), presented=dict(max_ms=presented))
        if not work_gating and message and message.startswith('Search work exceeded'):
            message = None
        try:
            exec(gate, dict(summary=summary, work_gating=work_gating, TimingBudgetExceeded=subject.TimingBudgetExceeded))
        except subject.TimingBudgetExceeded as error:
            assert message and error.args == ((message, summary),)
        else:
            assert message is None
        checks += 1

# Execute Linux's actual reporting/assertion block against the same boundaries.
# Presentation and am. 6 targets must remain visible without failing either path.
linux_tree = ast.parse((root / 'tests/search-screen/run.py').read_text())
linux_body = next(node for node in ast.walk(linux_tree)
                  if isinstance(node, ast.Try) and any(isinstance(child, ast.Assert) and
                     'Every query frame must reach swap' in ast.unparse(child)
                     for child in node.body)).body
linux_start = next(i for i, node in enumerate(linux_body)
                   if isinstance(node, ast.Assert) and 'Every query frame must reach swap' in ast.unparse(node))
linux_end = next(i for i in range(linux_start, len(linux_body))
                 if isinstance(linux_body[i], ast.Assign))
linux_gate = compile_nodes(linux_body[linux_start:linux_end])
for p95, maximum, entry, presented, failure in [
    (50, 100, 150, 100000, None),
    (20.001, 33.001, 149, 267.599, None),
    (50.001, 100, 150, 16, 'Linux search work exceeded p95 50ms / max 100ms'),
    (20, 100.001, 150, 16, 'Linux search work exceeded p95 50ms / max 100ms'),
    (19, 32, 150.001, 16, 'Linux search entry exceeded p95 150ms')]:
    lines = []
    try:
        exec(linux_gate, dict(work=dict(samples=64, p95_ms=p95, max_ms=maximum),
             entry=dict(p95_ms=entry), presented=dict(samples=64, max_ms=presented),
             refresh_work=dict(samples=0), refresh_presented=dict(samples=0),
             first_keystroke=dict(samples=1, max_ms=maximum), preparation_chunks=dict(samples=0),
             json=subject.json, print=lambda *args, **kwargs: lines.append(' '.join(map(str, args)))))
    except AssertionError as error:
        assert failure and error.args[0][0] == failure
    else:
        assert failure is None
    assert any('INFORMATIONAL presented intervals' in line for line in lines)
    assert any('INFORMATIONAL D-028 am. 6' in line for line in lines)
    checks += 1

with tempfile.TemporaryDirectory(prefix='esde-search-budget-') as temporary:
    evidence = Path(temporary)
    for suite in ['all', 'search', 'overlay']:
        for mode in ['pass', 'budget', 'functional', 'budget-and-baseline']:
            for name in ['search-screen-timing-failure-deferred.txt', 'search-session-summary.txt', 'touch-summary.txt']:
                (evidence / name).unlink(missing_ok=True)
            events = []
            budget = subject.TimingBudgetExceeded(('Search work exceeded p95 50ms / max 100ms',
                                                   dict(samples=64, max_ms=143.496)))
            functional = AssertionError('Result did not update')
            baseline_error = AssertionError('Overlay did not release')
            def search(*args):
                events.append('search')
                if mode == 'functional':
                    raise functional
                if mode.startswith('budget'):
                    raise budget
            def baseline():
                events.append('baseline')
                if mode == 'budget-and-baseline':
                    raise baseline_error
            env = dict(suite=suite, h=SimpleNamespace(evidence=evidence),
                       search_screen_smoke=SimpleNamespace(run=search,
                           TimingBudgetExceeded=subject.TimingBudgetExceeded),
                       search_entry_smoke=SimpleNamespace(run=lambda *args: events.append('entry')),
                       start=lambda **kwargs: None, surface_bounds=lambda: None,
                       touch_control=None, shot=None, record=None, baseline=baseline)
            caught = None
            try:
                exec(flow, env)
            except AssertionError as error:
                caught = error
            if suite == 'overlay':
                expected_error = baseline_error if mode == 'budget-and-baseline' else None
                assert caught is expected_error and events == ['baseline']
            elif mode == 'pass':
                expected = ['search', 'entry'] + (['baseline'] if suite == 'all' else [])
                assert caught is None and events == expected
            elif mode == 'functional':
                assert caught is functional and events == ['search']
            else:
                expected_error = baseline_error if suite == 'all' and mode.endswith('baseline') else budget
                assert caught is expected_error
                assert events == ['search', 'entry'] + (['baseline'] if suite == 'all' else [])
                assert str(budget) in (evidence / 'search-screen-timing-failure-deferred.txt').read_text()
            assert (evidence / 'search-session-summary.txt').exists() == (suite == 'search' and mode == 'pass')
            assert (evidence / 'touch-summary.txt').exists() == (caught is None and suite != 'search')
            checks += 1

# Execute the entry helper's actual predicate: Y-space restoration must preserve
# exact seed assertions and kid-mode redaction, including multi-byte text.
entry_tree = ast.parse((root / 'android/search_entry_smoke.py').read_text())
predicate = next(node for node in ast.walk(entry_tree)
                 if isinstance(node, ast.FunctionDef) and node.name == 'query_is')
for logged, value, expected in [
    ('', 'm', False),
    ('query=m results=2 query_bytes=1', 'm', True),
    ('query=mm results=2 query_bytes=2', 'm', False),
    ('query=m   results=2 query_bytes=3', 'm  ', True),
    ('query=<private> results=2 query_bytes=2', '  ', True),
    ('query=<private> results=2 query_bytes=1', '  ', False),
    ('query=<private> results=2 query_bytes=3', '学', True),
    ('query=<private> results=2 query_bytes=2', '学', False)]:
    env = dict(re=re, h=SimpleNamespace(log=lambda: 'Search keystroke: ' + logged))
    exec(compile_nodes([predicate]), env)
    assert env['query_is'](value) == expected
    checks += 1

workflow = (root / '.github/workflows/build-android.yml').read_text()
overlay_step = workflow.split('      - name: Fresh-emulator overlay baseline\n', 1)[1].split('      - name:', 1)[0]
assert "steps.smoke-session.outcome == 'failure'" in overlay_step
assert '!cancelled()' in overlay_step and 'continue-on-error' not in overlay_step
assert 'force-avd-creation: true' in overlay_step and 'avd-name: esde-touch-overlay' in overlay_step
assert 'ESDE_TOUCH_SUITE: overlay' in overlay_step
assert 'smoke_session.py touch-overlay' in overlay_step
assert workflow.index('Upload search evidence before') < workflow.index('Fresh-emulator overlay baseline')
assert 'emulator-result touch-overlay "${{ steps.overlay-session.outcome }}"' in workflow
checks += 1

# Execute the actual checkpoint collector: startup work must appear exactly once,
# and every frame/entry sample remains in the reported distributions.
collector = next(node for node in run_body(path).body if isinstance(node, ast.FunctionDef) and
                 node.name == 'timing')
setup = ast.parse("timed_prefix = ''; measurements = []; presentations = []; entries = []; refresh_measurements = []; refresh_presentations = []; first_measurements = []; preparation_chunks = []").body
wrapper = ast.FunctionDef(name='collect', args=ast.arguments(posonlyargs=[], args=[],
    kwonlyargs=[], kw_defaults=[], defaults=[]), body=setup + [collector] +
    ast.parse("timing('checkpoint'); return measurements, presentations, entries, refresh_measurements, refresh_presentations, first_measurements, preparation_chunks").body,
    decorator_list=[])
collect_code = compile_nodes([wrapper])
for preparations in [0, 1, 2]:
    log = 'Search renderer prepared once: ms=250\n' * preparations + (
        'Search entry ready: ms=12\nSearch keystroke: query=f results=2\n'
        'Search preparation chunk: phase=idle work_ms=2.4 tasks=4 ready=0 atlases=1\n'
        'Search frame: query=f work_ms=7 cause=keystroke first=1\nSearch presented: query=f interval_ms=16 cause=keystroke\n'
        'Search frame: query=f work_ms=104.5 cause=refresh\nSearch presented: query=f interval_ms=999 cause=refresh\n')
    environment = dict(re=re, h=SimpleNamespace(log=lambda: log,
        wait_for=lambda predicate, message: (_ for _ in ()).throw(AssertionError(message))
                 if not predicate() else None), record=lambda name: None)
    exec(collect_code, environment)
    try:
        collected = environment['collect']()
    except AssertionError as error:
        assert preparations != 1 and str(error) == 'Renderer preparation must run once per process'
    else:
        assert preparations == 1 and collected == ([7.0], [16.0], [12.0], [104.5], [999.0], [7.0], [2.4])
    checks += 1

# Execute the shared entry journey's actual distribution/writer/gate, including
# a retained maximum above the target when its p95 still meets the stated limit.
entry_body = run_body(root / 'android/search_entry_smoke.py').body
start = next(i for i, node in enumerate(entry_body)
             if ast.unparse(node) == 'entry_times.sort()')
entry_gate = compile_nodes(entry_body[start:-1])
with tempfile.TemporaryDirectory(prefix='esde-entry-budget-') as temporary:
    evidence = Path(temporary)
    for values, failure in [([], 'Missing entry-point timing samples'),
                            ([12, 14, 150], None),
                            ([12, 14, 150.001], 'Search entry points exceeded p95 150ms'),
                            ([10] * 20 + [999], None)]:
        try:
            namespace = dict(entry_times=list(values), math=subject.math, json=subject.json,
                             h=SimpleNamespace(evidence=evidence))
            exec(entry_gate, namespace)
        except AssertionError as error:
            assert failure and (error.args[0] == failure or error.args[0][0] == failure)
        else:
            assert failure is None
            actual = subject.json.loads((evidence / 'search-entry-timing.txt').read_text())
            assert actual['samples'] == len(values) and actual['max_ms'] == max(values)
        checks += 1

scripts = re.findall(r'^          script: \|\n((?:            .*\n)+)', workflow, re.M)
assert len(scripts) == 2, 'Check both emulator actions'
for script in scripts:
    # The pinned emulator action starts a new shell for each line, not one shell
    # for the YAML block. This rejects a multiline if before spending CI builds.
    for line in script.splitlines():
        command = re.sub(r'\$\{\{.*?\}\}', 'touch', line.strip())
        subprocess.run(['sh', '-n', '-c', command], check=True, capture_output=True, text=True)
assert "ESDE_TOUCH_SUITE: ${{ matrix.session == 'touch' && 'search' || 'all' }}" in workflow
checks += 1
# Round 4: execute the actual overlay re-enable marker and XML assertion in order.
touch_tree = run_body(root / 'android/touch_smoke.py')
block = next(node.body for node in ast.walk(touch_tree) if isinstance(node, ast.Try) and
             any(isinstance(child, ast.Assert) and 'InputTouchOverlay' in ast.unparse(child)
                 and 'true' in ast.unparse(child) for child in node.body))
saved = next(node for node in block if isinstance(node, ast.Assert) and
             'InputTouchOverlay' in ast.unparse(node) and 'true' in ast.unparse(node))
marker = next(node for node in block if isinstance(node, ast.Expr) and
              'fresh menu enable rebuild and render' in ast.unparse(node))
assert block.index(marker) < block.index(saved), 'Observe the save/render before reading XML'
for rendered, persisted in [(True, True), (False, False), (True, False)]:
    state = dict(ready=False, reads=0)
    def log():
        return 'before' + ('InputOverlay: restored (menu)\nInputOverlay: textures built' if state['ready'] else '')
    def wait_for(predicate, message):
        assert not predicate(), 'Marker must not be accepted early'
        state['ready'] = rendered
        assert predicate(), message
    def shell(*args):
        assert state['ready'], 'Settings read before the marker'
        state['reads'] += 1
        return '<bool name="InputTouchOverlay" value="' + str(persisted).lower() + '"/>'
    try:
        exec(compile_nodes([marker, saved]), dict(re=re, enable_before='before',
             h=SimpleNamespace(log=log, wait_for=wait_for, shell=shell, settings='settings')))
    except AssertionError:
        assert not rendered or not persisted
    else:
        assert rendered and persisted
    assert state['reads'] == int(rendered)
    checks += 1

# D-030 changes the receipt policy, retaining the actual capture/raise branch.
launch_spec = importlib.util.spec_from_file_location('receipt_policy', root / 'android/launch_checks.py')
launch = importlib.util.module_from_spec(launch_spec)
launch_spec.loader.exec_module(launch)
smoke_tree = ast.parse((root / 'android/smoke.py').read_text())
label = next(node for node in smoke_tree.body if isinstance(node, ast.FunctionDef) and
             node.name == 'record_retroarch_receipt')
for api in [33, 35]:
    with tempfile.TemporaryDirectory(prefix='esde-receipt-label-') as temporary:
        messages = []
        environment = dict(device_api=api, television=False, evidence=Path(temporary),
            retroarch_receipt_gating=launch.retroarch_receipt_gates(False, api),
            os=SimpleNamespace(environ={}), print=lambda text, **kwargs: messages.append(text))
        exec(compile_nodes([label]), environment)
        environment['record_retroarch_receipt']('RECEIPT PASSED')
        assert messages[0].startswith(('D-030' if api == 35 else 'D-010') + ' real-RetroArch receipt:')
        assert ('NON-GATING DIAGNOSTIC' in messages[0]) == (api == 35)
        checks += 1
receipt = next(node for node in ast.walk(smoke_tree) if isinstance(node, ast.Try) and
               any(isinstance(child, ast.Expr) and 'wait_for(receipt_ready,' in ast.unparse(child)
                   for child in node.body))
for api in [33, 35]:
    events = []
    failure = AssertionError('real RetroArch processes Intent and exact ROM argument')
    def fail_wait(*args, **kwargs):
        raise failure
    env = dict(wait_for=fail_wait, receipt_ready=lambda: False, launch_checks=launch,
               recipient_pid='123', recipient_log='', rom_argument='/rom.nes',
               retroarch_receipt_gating=launch.retroarch_receipt_gates(False, api),
               retroarch_stacks=lambda *args: events.append('stack'),
               record_retroarch_receipt=lambda *args: events.append('record'),
               capture_retroarch_failure=lambda: events.append('capture'))
    try:
        exec(compile_nodes([receipt]), env)
    except AssertionError as error:
        assert api == 33 and error is failure
    else:
        assert api == 35
    assert events == (['stack', 'record'] if api == 33 else ['stack', 'record', 'capture'])
    checks += 1

# An immediate post-A frame is valid evidence; the probe must snapshot before A,
# rather than wait for an unrelated Shift key to produce another cursor record.
for nodes, label, activation in [(body, 'A closes search into game list', 'pad(0)'),
                                 (linux_body, 'search closes to game list', "command('key', '13')")]:
    shown = next(i for i, node in enumerate(nodes) if isinstance(node, ast.Expr) and
                 label in ast.unparse(node))
    assert ast.unparse(nodes[shown - 1]) == activation
    before = nodes[shown - 2]
    assert isinstance(before, ast.Assign) and ast.unparse(before.targets[0]) == 'before'
    actual = next(node for node in nodes[shown + 1:] if isinstance(node, ast.Expr) and
                  'actual game-list cursor' in ast.unparse(node))
    state = dict(log='before')
    def log(): return state['log']
    def act(*args):
        state['log'] += ('Search show game: nes/Final Fantasy VII\n'
                         'Gamelist actual cursor: system=nes game=Final Fantasy VII path=/roms/Smoke Alpha.nes')
    def wait(predicate, message): assert predicate(), message
    env = dict(re=re, log=log, command=act, pad=act, wait=wait,
               h=SimpleNamespace(log=log, wait_for=wait))
    exec(compile_nodes([before, nodes[shown - 1], nodes[shown], actual]), env)
    checks += 1

print(f'PASS: {checks} actual timing/phase controls; API 33 work and both opening gates stay hard; API 35 work informational; fresh overlay runs after failed search')
