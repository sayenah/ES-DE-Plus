#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Exercise close failures without a device.
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pdf_close_probe import CloseProbe, controls


class FakeHarness:
    app = 'org.esdeplus.frontend'

    def __init__(self, evidence):
        self.evidence = evidence
        self.events = []
        self.keys = 0
        self.stop_after = 1
        self.stopped = False
        self.open_frame = b'manual'
        self.key_errors = {}
        self.capture_errors = set()
        self.close_error = TimeoutError('original close timeout')

    def capture_stage(self, stage):
        self.events.append(stage)
        if stage in self.capture_errors:
            raise RuntimeError('capture failed: ' + stage)

    def shell(self, *args):
        if args[:2] == ('sh', '-c'):
            self.keys += 1
            self.events.append('key-' + str(self.keys))
            if self.keys in self.key_errors:
                raise self.key_errors[self.keys]
            self.stopped = self.keys == self.stop_after
            return '100.00 200.00\n100.01 200.01\n'
        if args[:2] == ('dumpsys', 'SurfaceFlinger'):
            if args[2:] == ('--list',):
                self.capture_stage('surface')
                return self.app + '/MainActivity\n'
            return 'frontend surface state\n'
        if args in [('dumpsys', 'input'), ('dumpsys', 'window')]:
            self.capture_stage(args[1])
            return args[1] + ' state\n'
        raise AssertionError(('Unexpected shell command', args))

    def adb(self, *args, binary=False):
        assert args == ('exec-out', 'screencap', '-p') and binary, args
        self.capture_stage('screen')
        return b'frontend' if self.stopped else self.open_frame

    def log(self):
        return 'PDF viewer stopped ticks=101\n' if self.stopped else ''

    def wait_for(self, predicate, description):
        self.events.append('wait-for-close')
        if not predicate():
            raise self.close_error

    def capture_frontend_stacks(self, name):
        self.capture_stage('stacks')
        (self.evidence / (name + '-stacks.txt')).write_text('frontend stacks\n')

    def save_logs(self, name):
        self.capture_stage('logs')
        (self.evidence / (name + '-logcat.txt')).write_text(self.log())


class CloseProbeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='esde-pdf-close-test-')
        self.addCleanup(temporary.cleanup)
        self.h = FakeHarness(Path(temporary.name))
        self.probe = CloseProbe(self.h, 'direct')
        sleeper = patch('pdf_close_probe.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def records(self):
        return [json.loads(line) for line in
                (self.h.evidence / 'pdf-direct-close-markers.txt').read_text().splitlines()]

    def close(self, diagnostic=False):
        return self.probe.close(lambda frame: frame == b'manual', diagnostic=diagnostic)

    def test_single_key_and_native_stop_pass(self):
        self.assertEqual(self.close(), 1)
        self.assertEqual(self.h.keys, 1)
        self.assertEqual(self.records()[-1]['event'], 'cycle-end')
        poll = next(x for x in self.records() if x['event'] == 'poll')
        self.assertTrue(poll['native_stopped'])
        self.assertFalse(poll['manual_visible'])

    def test_injection_failure_captures_before_propagating(self):
        original = RuntimeError('original injection failure')
        self.h.key_errors[1] = original
        with self.assertRaises(RuntimeError) as raised:
            self.close()
        self.assertIs(raised.exception, original)
        self.assertEqual(self.h.events, ['key-1', 'screen', 'input', 'window', 'surface', 'stacks', 'logs'])
        self.assertFalse(any(x['event'] == 'cycle-end' for x in self.records()))

    def test_each_capture_error_keeps_remaining_captures_and_original_failure(self):
        stages = ['screen', 'input', 'window', 'surface', 'stacks', 'logs']
        for stage in stages:
            with self.subTest(stage=stage):
                self.h.events.clear()
                self.h.keys = 0
                original = RuntimeError('original injection failure: ' + stage)
                self.h.key_errors[1] = original
                self.h.capture_errors = {stage}
                with self.assertRaises(RuntimeError) as raised:
                    self.close()
                self.assertIs(raised.exception, original)
                self.assertEqual(self.h.events, ['key-1'] + stages)
                captures = [x for x in self.records() if x['cycle'] == self.probe.sequence and
                            x['event'] in ('capture', 'capture-error')]
                self.assertEqual([x['stage'] for x in captures], stages)
                self.assertEqual([x['stage'] for x in captures if x['event'] == 'capture-error'], [stage])

    def test_black_frame_without_native_stop_is_rejected(self):
        self.h.stop_after = None
        self.h.open_frame = b'black'
        with self.assertRaises(TimeoutError) as raised:
            self.close()
        self.assertIs(raised.exception, self.h.close_error)
        poll = next(x for x in self.records() if x['event'] == 'poll')
        self.assertFalse(poll['manual_visible'])
        self.assertFalse(poll['native_stopped'])
        self.assertEqual(self.h.keys, 1)

    def test_successful_diagnostic_second_key_cannot_pass_failed_cycle(self):
        self.h.stop_after = 2
        with self.assertRaises(TimeoutError) as raised:
            self.close(diagnostic=True)
        self.assertIs(raised.exception, self.h.close_error)
        self.assertEqual(self.h.keys, 2)
        captures = ['screen', 'input', 'window', 'surface', 'stacks', 'logs']
        second = self.h.events.index('key-2')
        for stage in captures:
            self.assertIn(stage, self.h.events[:second])
        records = self.records()
        self.assertTrue(next(x for x in records if x['event'] == 'second-key-result')['closed'])
        self.assertEqual([x['purpose'] for x in records if x['event'] == 'key-begin'],
                         ['single-close', 'diagnostic-second-key'])
        self.assertFalse(any(x['event'] == 'cycle-end' for x in records))

    def test_failed_diagnostic_second_key_keeps_original_failure(self):
        self.h.stop_after = None
        self.h.key_errors[2] = RuntimeError('second injection failure')
        with self.assertRaises(TimeoutError) as raised:
            self.close(diagnostic=True)
        self.assertIs(raised.exception, self.h.close_error)
        self.assertEqual(self.h.keys, 2)
        self.assertTrue(any(x['event'] == 'second-key-error' for x in self.records()))
        self.assertFalse(any(x['event'] == 'cycle-end' for x in self.records()))

    def test_fresh_resume_release_controls(self):
        self.assertIn('wrong process', controls())


if __name__ == '__main__':
    unittest.main(verbosity=2)
