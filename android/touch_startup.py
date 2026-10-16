#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Bounded debug startup ownership and self-tests.
import re
import time


class StartupOwnership:
    def __init__(self, harness, process, deadline, name):
        self.h = harness
        self.process = process
        self.deadline = deadline
        self.name = name
        self.events = harness.evidence / 'tv-onboarding-events.txt'
        self.previous_events = self.events.stat().st_size if self.events.exists() else 0
        self.recoveries = 0

    def finished(self):
        if time.monotonic() > self.deadline:
            return False
        if self.process.poll() is not None:
            return True
        # The shared guard runs first. Only its new, recorded stock-tutorial
        # dismissal may recover ownership, before the SDK can inject any gesture.
        if not self.recoveries and self.events.exists() and self.events.stat().st_size > self.previous_events:
            h = self.h
            owner = h.private('cat', 'cache/touch-startup-owner', check=False).strip()
            if re.fullmatch(r'\d+ \d+', owner) and h.smoke_checks.package_window_focused(
                    h.focused_window(), h.stock_package):
                pid, task = owner.split()
                assert h.shell('pidof', h.app).strip() == pid, 'Startup owner process changed'
                self.recoveries = 1
                outcome = 'failed'
                try:
                    h.shell('am', 'start', '-n', h.activity, '-f', '0x10020000')
                    assert h.shell('pidof', h.app).strip() == pid, 'Recovery restarted the native process'
                    observed = h.shell('am', 'broadcast', '-n',
                                       h.app + '/org.esdeplus.frontend.TouchSmoke$SurfaceGeometry',
                                       '--ez', 'startupTask', 'true')
                    assert 'PASS: startup task recorded' in observed, observed
                    current = h.private('cat', 'cache/touch-startup-task').strip()
                    assert current == owner, ('Recovery changed the native process or task', owner, current)
                    outcome = 'verified'
                finally:
                    with (h.evidence / 'touch-startup-ownership.txt').open('a') as proof:
                        proof.write(f'{self.name}: existing pid={pid} task={task}; before stream; '
                                    f'external tutorial dismissed; {outcome}\n')
        return False

    def report(self):
        line = f'TOUCH STARTUP OWNERSHIP: session={self.name} recoveries={self.recoveries}'
        print(line, flush=True)
        with (self.h.evidence / 'touch-startup-session-counts.txt').open('a') as proof:
            proof.write(line + '\n')


def self_test():
    import contextlib
    import io
    from pathlib import Path
    import tempfile
    from types import SimpleNamespace

    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
        evidence = Path(directory)
        events = evidence / 'tv-onboarding-events.txt'
        events.write_text('old session dismissal\n')
        calls = []
        owner, current = '123 7', '123 7'
        focus = 'stock.launcher'
        pids = ['123', '123']
        process = SimpleNamespace(poll=lambda: None)

        def shell(*args):
            calls.append(args)
            if args[0] == 'pidof':
                return pids.pop(0)
            if args[:2] == ('am', 'broadcast'):
                return 'PASS: startup task recorded'
            return ''

        def private(*args, **kwargs):
            return owner if args[-1] == 'cache/touch-startup-owner' else current

        h = SimpleNamespace(evidence=evidence, app='fixture.frontend', activity='frontend/activity',
                            stock_package='stock.launcher', shell=shell, private=private,
                            focused_window=lambda: focus,
                            smoke_checks=SimpleNamespace(package_window_focused=lambda w, p: w == p))

        def session(name):
            return StartupOwnership(h, process, time.monotonic() + 90, name)

        no_dismissal = session('no-dismissal')
        assert no_dismissal.finished() is False and not calls
        missing_marker = session('marker-deleted')
        events.write_text(events.read_text() + 'new dismissal\n')
        owner = ''
        assert missing_marker.finished() is False and not calls
        owner = '123 7'
        focus = 'frontend'
        assert missing_marker.finished() is False and not calls
        focus = h.stock_package
        expired = session('expired')
        expired.previous_events = 0
        expired.deadline = time.monotonic() - 1
        assert expired.finished() is False and not calls
        once = session('eligible')
        events.write_text(events.read_text() + 'next dismissal\n')
        assert once.finished() is False and once.recoveries == 1
        assert calls == [('pidof', h.app),
                         ('am', 'start', '-n', h.activity, '-f', '0x10020000'),
                         ('pidof', h.app),
                         ('am', 'broadcast', '-n',
                          h.app + '/org.esdeplus.frontend.TouchSmoke$SurfaceGeometry',
                          '--ez', 'startupTask', 'true')]
        assert once.finished() is False and len(calls) == 4
        assert 'task=7' in (evidence / 'touch-startup-ownership.txt').read_text()

        for name, process_ids, observed, message in [
                ('pid-before', ['456'], '123 7', 'Startup owner process changed'),
                ('pid-after', ['123', '456'], '123 7', 'Recovery restarted the native process'),
                ('task-after', ['123', '123'], '123 8', 'Recovery changed the native process or task')]:
            calls.clear()
            pids, current = process_ids, observed
            check = session(name)
            events.write_text(events.read_text() + 'new dismissal\n')
            try:
                check.finished()
            except AssertionError as error:
                assert message in str(error), (name, error)
            else:
                raise AssertionError(name + ' mismatch escaped')
            assert sum(c[:2] == ('am', 'start') for c in calls) == (0 if name == 'pid-before' else 1)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            no_dismissal.report()
            missing_marker.report()
            once.report()
        assert output.getvalue() == (evidence / 'touch-startup-session-counts.txt').read_text()
        assert 'session=no-dismissal recoveries=0' in output.getvalue()
        assert 'session=marker-deleted recoveries=0' in output.getvalue()
        assert 'session=eligible recoveries=1' in output.getvalue()
    return ('PASS: no dismissal/no marker do not recover; eligible recovery occurs once; '
            'PID/task mismatches fail; per-session counts logged\n')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['self-test'])
    parser.parse_args()
    print(self_test(), end='')
