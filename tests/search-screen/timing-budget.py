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

for maximum, should_fail in [(49.999, False), (50, False), (50.0001, True), (143.496, True)]:
    summary = dict(samples=64, p95_ms=32.4266, max_ms=maximum)
    try:
        exec(gate, dict(summary=summary, TimingBudgetExceeded=subject.TimingBudgetExceeded))
    except subject.TimingBudgetExceeded as error:
        assert should_fail and error.args == (('Search-attributable work exceeded 50ms', summary),)
    else:
        assert not should_fail
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
