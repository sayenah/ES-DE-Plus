#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Execute actual timing checks and deferral blocks.
import ast
import importlib.util
from pathlib import Path
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
capture = next(node for node in journey.body if isinstance(node, ast.Try) and
               'search_screen_smoke.run(' in ast.unparse(node))
trailer = next(node for node in journey.body if isinstance(node, ast.If) and
               ast.unparse(node.test) == 'search_timing_failure is not None')
summary_writer = next(node for node in journey.body if isinstance(node, ast.Expr) and
                      "'touch-summary.txt'" in ast.unparse(node))
assert journey.body.index(capture) < journey.body.index(trailer) < journey.body.index(summary_writer)
flow = compile_nodes([capture, ast.Expr(ast.Call(ast.Name('baseline', ast.Load()), [], [])),
                      trailer, ast.Expr(ast.Call(ast.Name('passed', ast.Load()), [], []))])
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
    for mode in ['pass', 'budget', 'functional', 'budget-and-baseline']:
        (evidence / 'search-screen-timing-failure-deferred.txt').unlink(missing_ok=True)
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
        env = dict(search_timing_failure=None, h=SimpleNamespace(evidence=evidence),
                   search_screen_smoke=SimpleNamespace(run=search,
                       TimingBudgetExceeded=subject.TimingBudgetExceeded),
                   start=None, touch_control=None, shot=None, record=None,
                   baseline=baseline, passed=lambda: events.append('PASS'))
        caught = None
        try:
            exec(flow, env)
        except AssertionError as error:
            caught = error
        if mode == 'pass':
            assert caught is None and events == ['search', 'baseline', 'PASS']
        elif mode == 'functional':
            assert caught is functional and events == ['search']
        else:
            assert caught is (baseline_error if mode.endswith('baseline') else budget)
            assert events == ['search', 'baseline']
            assert env['search_timing_failure'] is budget
            assert str(budget) in (evidence / 'search-screen-timing-failure-deferred.txt').read_text()
        checks += 1
print(f'PASS: {checks} actual timing boundary/deferral checks; failures cannot become overall PASS')
