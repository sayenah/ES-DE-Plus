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
check = next(node for node in body if isinstance(node, ast.Try) and node.body and
             isinstance(node.body[0], ast.Assert))
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

for p95, maximum, entry, presented, message in [
    (20, 33, 150, 50, None),
    (20.001, 33, 150, 50, 'Search work exceeded p95 20ms / max 33ms'),
    (20, 33.001, 150, 50, 'Search work exceeded p95 20ms / max 33ms'),
    (19, 32, 150.001, 50, 'Search entry exceeded p95 150ms'),
    (19, 32, 149, 50.001, 'Search presented frame exceeded 50ms'),
    (19, 143.496, 149, 49, 'Search work exceeded p95 20ms / max 33ms')]:
    summary = dict(samples=64, p95_ms=p95, max_ms=maximum,
                   entry=dict(p95_ms=entry), presented=dict(max_ms=presented))
    try:
        exec(gate, dict(summary=summary, TimingBudgetExceeded=subject.TimingBudgetExceeded))
    except subject.TimingBudgetExceeded as error:
        assert message and error.args == ((message, summary),)
    else:
        assert message is None
    checks += 1

with tempfile.TemporaryDirectory(prefix='esde-search-budget-') as temporary:
    evidence = Path(temporary)
    for suite in ['all', 'search', 'overlay']:
        for mode in ['pass', 'budget', 'functional', 'budget-and-baseline']:
            for name in ['search-screen-timing-failure-deferred.txt', 'search-session-summary.txt', 'touch-summary.txt']:
                (evidence / name).unlink(missing_ok=True)
            events = []
            budget = subject.TimingBudgetExceeded(('Search-attributable work exceeded 50ms',
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
setup = ast.parse("timed_prefix = ''; measurements = []; presentations = []; entries = []").body
wrapper = ast.FunctionDef(name='collect', args=ast.arguments(posonlyargs=[], args=[],
    kwonlyargs=[], kw_defaults=[], defaults=[]), body=setup + [collector] +
    ast.parse("timing('checkpoint'); return measurements, presentations, entries").body,
    decorator_list=[])
collect_code = compile_nodes([wrapper])
for preparations in [0, 1, 2]:
    log = 'Search renderer prepared once: ms=250\n' * preparations + (
        'Search entry ready: ms=12\nSearch keystroke: query=f results=2\n'
        'Search frame: query=f work_ms=7\nSearch presented: query=f interval_ms=16\n')
    environment = dict(re=re, h=SimpleNamespace(log=lambda: log,
        wait_for=lambda predicate, message: (_ for _ in ()).throw(AssertionError(message))
                 if not predicate() else None), record=lambda name: None)
    exec(collect_code, environment)
    try:
        collected = environment['collect']()
    except AssertionError as error:
        assert preparations != 1 and str(error) == 'Renderer preparation must run once per process'
    else:
        assert preparations == 1 and collected == ([7.0], [16.0], [12.0])
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
print(f'PASS: {checks} actual timing/phase controls; exact failures stay hard; fresh overlay runs after failed search')
