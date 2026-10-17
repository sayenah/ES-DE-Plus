#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Exercises the readback driver's failure boundary.
import hashlib
import contextlib
import io
import json
import pathlib
import re
import shlex
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'android'))
import theme_fuse_smoke
import theme_recovery_smoke


class Guest:
    api = 31
    app = 'example.app'
    data_root = '/storage/emulated/0/Confirmed'

    def __init__(self, evidence, fault=None):
        self.evidence = evidence
        self.uid = '2000'
        self.position = 0
        self.stopped = False
        self.reads = []
        self.samples = []
        self.fault = fault
        for clone in range(20):
            for stage, cycle in [('clone-after-listing', -1)] + [
                    item for n in range(3) for item in [('before-update', n), ('after-update-listing', n)]]:
                version = cycle + (stage == 'after-update-listing')
                values = {name: (b'config' if name == 'config' else f'{name}:{version}'.encode())
                          for name in ('config', 'HEAD', 'FETCH_HEAD', 'packed-refs', 'index',
                                       'refs/heads/master', 'refs/remotes/origin/master')}
                if fault == 'config-write' and stage == 'after-update-listing':
                    values['config'] += b' changed'
                files = []
                for name, value in values.items():
                    files.append(dict(path=name, exists=True, size=len(value), read=len(value),
                                      hash=hashlib.sha1(b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()))
                directory = self.data_root + '/theme-trust.fixture/fuse-on/themes/original/.git'
                if fault == 'outside':
                    directory = '/data/data/other.app/files/.git'
                self.samples.append((dict(sequence=len(self.samples) + 1, mode='on', stage=stage,
                                          clone=clone, cycle=cycle, directory=directory, files=files), values))

    def wait_for(self, condition, description, timeout):
        for _ in range(1000):
            if condition():
                return
        raise AssertionError(description)

    def shell(self, *args, **kwargs):
        if args == ('id', '-u'):
            return self.uid
        if args[:2] == ('readlink', '-f'):
            return self.data_root
        if args[0] == 'pidof':
            return '1234'
        if args[:3] == ('run-as', self.app, 'cat'):
            if args[-1] == 'files/theme-fuse.result':
                return ('PASS: R1 updates=3 actual downloader paths\n' * 20 +
                        'PASS: FUSE retirement controls; complete\n') if self.position == len(self.samples) else ''
            return json.dumps(self.samples[self.position][0])
        if args[:3] == ('run-as', self.app, 'sh'):
            number, state = re.search(r'(\d+) (CONTINUE|STOP)', args[-1]).groups()
            assert int(number) == self.position + 1
            if state == 'STOP':
                self.stopped = True
            else:
                self.position += 1
            return ''
        if args[:2] == ('sh', '-c'):
            target = shlex.split(args[-1])[3]
            value = self.lower(target)
            return '81a4 ' + str(len(value))
        raise AssertionError(args)

    def lower(self, target):
        self.reads.append(target)
        record, values = self.samples[self.position]
        name = target.split('/.git/', 1)[1]
        if self.fault == 'index-view' and record['stage'] == 'after-update-listing' and name == 'index':
            return values[name] + b' lower'
        return values[name]

    def adb(self, *args, **kwargs):
        if args[0] in ('root', 'unroot'):
            self.uid = '0' if args[0] == 'root' else '2000'
            return ''
        if args[0] == 'wait-for-device':
            return ''
        if args[0] == 'exec-out':
            return self.lower(shlex.split(args[1])[1])
        raise AssertionError(args)


class ReadbackControls(unittest.TestCase):
    def test_confirmation_positive_uses_native_log_application_tag_and_current_pid(self):
        app = 'example.frontend'
        line = ('10-17 08:00:00.123 1234 1250 D ' + app +
                ': Oct 17 08:00:00 Debug: Theme list recovery confirmation refused: /fixture\n')
        self.assertTrue(theme_recovery_smoke.decision_seen(line, '1234', app, 'confirmation refused'))
        self.assertFalse(theme_recovery_smoke.decision_seen(line, '5678', app, 'confirmation refused'))
        self.assertFalse(theme_recovery_smoke.decision_seen(line, '1234', 'SDL-host', 'confirmation refused'))
        self.assertFalse(theme_recovery_smoke.decision_seen(line, '1234', app, 'cancelled'))

    def test_update_and_path_probe_review_invariants(self):
        gui = (ROOT / 'es-app/src/guis/GuiThemeDownloader.cpp').read_text()
        for function in ('fetchRepository', 'resetRepository'):
            body = re.search(r'(?:bool|void) GuiThemeDownloader::' + function +
                             r'\(.*?(?=\n(?:bool|void) GuiThemeDownloader::)', gui, re.S).group()
            self.assertNotRegex(body, r'git_config_(?:set|delete|lock|add)|git_repository_set_config')
        for name in ('ThemeRepositoryTrust.cpp', 'ThemeRepositoryFuse.cpp'):
            source = (ROOT / 'es-app/src/guis' / name).read_text()
            for literal in re.findall(r'"([^"\n]*)"', source):
                if literal.rsplit('/', 1)[-1].lower() == 'config':
                    self.assertEqual(literal.rsplit('/', 1)[-1], 'config')
        trust = (ROOT / 'es-app/src/guis/ThemeRepositoryTrust.cpp').read_text()
        before, creation = trust.split('int ThemeRepositoryTrust::create(', 1)
        creation, after = creation.split('void ThemeRepositoryTrust::Testing::preservingSession', 1)
        self.assertNotIn('ThemeRepositoryFuse::retire(', before + after)
        self.assertIn('ThemeRepositoryFuse::retire(', creation)

    def guest(self, fault=None):
        parent = ROOT / 'build/theme-trust/fuse-driver'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        return Guest(pathlib.Path(temporary.name), fault)

    def test_changing_metadata_positive(self):
        h = self.guest()
        with contextlib.redirect_stdout(io.StringIO()):
            theme_fuse_smoke.collect(h)
        self.assertEqual(h.position, 140)
        self.assertEqual(h.uid, '2000')
        self.assertEqual(len((h.evidence / 'theme-fuse-view-lower.txt').read_text().splitlines()), 140)
        coverage = json.loads((h.evidence / 'theme-fuse-coverage.txt').read_text())
        self.assertGreater(coverage['index']['replaced'], 0)

    def test_non_config_mismatch_stops_without_retry(self):
        h = self.guest('index-view')
        with self.assertRaisesRegex(AssertionError, 'AC-3 view/lower mismatch.*index'):
            theme_fuse_smoke.collect(h)
        self.assertTrue(h.stopped)
        self.assertEqual(h.uid, '2000')
        self.assertEqual(h.position, 2)
        records = [json.loads(row) for row in
                   (h.evidence / 'theme-fuse-view-lower.txt').read_text().splitlines()]
        self.assertEqual(records[-1]['mismatches'], ['index'])
        view = next(entry for entry in records[-1]['files'] if entry['path'] == 'index')
        self.assertNotEqual(view['hash'], records[-1]['lower']['index']['hash'])

    def test_config_write_is_hard_even_with_equal_views(self):
        h = self.guest('config-write')
        with self.assertRaisesRegex(AssertionError, 'AC-5 lower config changed'):
            theme_fuse_smoke.collect(h)
        self.assertTrue(h.stopped)
        self.assertEqual(h.uid, '2000')

    def test_manifest_cannot_read_another_root(self):
        h = self.guest('outside')
        with self.assertRaises(AssertionError):
            theme_fuse_smoke.collect(h)
        self.assertEqual(h.reads, [])
        self.assertEqual(h.uid, '2000')


if __name__ == '__main__':
    unittest.main()
