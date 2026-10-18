#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Preserve logs across owned adbd resets.
import json
import os
from pathlib import Path
import subprocess
import time


_pending = None


def adb_completed(arguments, output, began, before_uid=None, status=0):
    global _pending
    if arguments in (('root',), ('unroot',)):
        target = '0' if arguments[0] == 'root' else '2000'
        _pending = (dict(operation=arguments[0], began=began, before_uid=before_uid,
                         target_uid=target, request_status=status, waited=False)
                    if before_uid in ('0', '2000') and before_uid != target else None)
    elif arguments == ('wait-for-device',) and _pending:
        _pending['waited'] = True
    elif (arguments in (('shell', 'id -u'), ('shell', 'id', '-u')) and _pending and
          _pending['waited'] and output.strip() == _pending['target_uid']):
        path = os.environ.get('ESDE_SMOKE_LOGCAT_RESETS')
        if path:
            with Path(path).open('a') as journal:
                journal.write(json.dumps(dict(operation=_pending['operation'], began=_pending['began'],
                    ready=time.monotonic(), before_uid=_pending['before_uid'], after_uid=output.strip(),
                    request_status=_pending['request_status'])) + '\n')
        _pending = None


class Observer:
    def __init__(self, stream, resets, spawn=subprocess.Popen, now=time.monotonic):
        self.stream, self.resets, self.spawn, self.now = stream, resets, spawn, now
        self.reconnections = []
        self.start()

    def start(self):
        self.started = self.last_alive = self.now()
        self.stopped = None
        # Each connection dumps retained buffers before following. Append to
        # the same kept file; startup_trace deduplicates the overlapping lines.
        self.stream.flush()
        self.process = self.spawn(['adb', 'logcat', '-b', 'all', '-v', 'threadtime',
                                   '-v', 'year', '-v', 'UTC', '-v', 'usec'],
                                  stdout=self.stream, stderr=subprocess.STDOUT)

    def tick(self):
        if self.process.poll() is None:
            self.last_alive = self.now()
            return
        if self.stopped is None:
            self.stopped = self.now()
        rows = ([json.loads(line) for line in self.resets.read_text().splitlines(keepends=True)
                 if line.endswith('\n')] if self.resets.exists() else [])
        # The old client can briefly drain received bytes after adbd is ready.
        # A receipt predating this connection can never authorise another one.
        owned = [row for row in rows if row['operation'] in ('root', 'unroot') and
                 row['began'] <= self.stopped and row['ready'] + 1 >= self.last_alive and
                 row['ready'] >= self.started]
        if owned:
            self.reconnections.append(dict(reset=owned[-1], status=self.process.returncode,
                                           observed_stopped=self.stopped, resumed=self.now()))
            self.start()

    def close(self):
        self.tick()
        streaming = self.process.poll() is None
        if streaming:
            self.process.terminate()
        self.process.wait(timeout=5)
        return dict(streaming_until_child_exit=streaming, status=self.process.returncode,
                    reconnections=self.reconnections)


def controls():
    global _pending
    _pending = None
    import io
    import tempfile
    from unittest.mock import patch
    class Process:
        returncode = None
        def poll(self): return self.returncode
        def terminate(self): self.returncode = -15
        def wait(self, **kwargs): return self.returncode
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'resets.txt'
        clock, calls = [10], []
        def spawn(arguments, **kwargs):
            assert arguments[:4] == ['adb', 'logcat', '-b', 'all']
            process = Process(); calls.append(process)
            return process
        observer = Observer(io.StringIO(), path, spawn, lambda: clock[0])
        clock[0] = 11; observer.tick()
        with patch.dict(os.environ, ESDE_SMOKE_LOGCAT_RESETS=str(path)), patch.object(time, 'monotonic', return_value=12):
            adb_completed(('root',), 'adbd is already running as root', 11.1, before_uid='0')
            adb_completed(('wait-for-device',), '', 11.2)
            adb_completed(('shell', 'id -u'), '0', 11.3)
            assert not path.exists()
            adb_completed(('root',), 'restarting adbd as root', 11.5, before_uid='2000')
            adb_completed(('shell', 'id -u'), '0', 11.6)
            assert not path.exists()  # The owned transaction must finish its device wait.
            adb_completed(('wait-for-device',), '', 11.9)
            assert not path.exists()  # Device presence alone is not a UID transition.
            adb_completed(('shell', 'id -u'), '0', 12)
        calls[-1].returncode = 255
        clock[0] = 12.1; observer.tick()
        assert len(calls) == 2 and len(observer.reconnections) == 1
        # A controlled reset can disconnect its requesting client before a
        # restart message arrives. The verified UID transition is the proof.
        clock[0] = 12.2; observer.tick()
        calls[-1].returncode = 255
        clock[0] = 12.6; observer.tick()
        with patch.dict(os.environ, ESDE_SMOKE_LOGCAT_RESETS=str(path)), patch.object(time, 'monotonic', return_value=13):
            adb_completed(('unroot',), '', 12.3, before_uid='0', status=255)
            adb_completed(('wait-for-device',), '', 12.5)
            adb_completed(('shell', 'id -u'), '2000', 13)
        clock[0] = 13.1; observer.tick()
        assert len(calls) == 3 and observer.reconnections[-1]['reset']['request_status'] == 255
        # A previous owned reset cannot excuse a later unexpected EOF.
        calls[-1].returncode = 255
        clock[0] = 14; observer.tick()
        assert len(calls) == 3
        assert not observer.close()['streaming_until_child_exit']
        # A failed request without an actual UID change grants no reconnect.
        before = path.read_text()
        with patch.dict(os.environ, ESDE_SMOKE_LOGCAT_RESETS=str(path)):
            adb_completed(('root',), 'request failed', 14.1, before_uid='2000', status=1)
            adb_completed(('wait-for-device',), '', 14.2)
            adb_completed(('shell', 'id -u'), '2000', 14.3)
        assert path.read_text() == before
        _pending = None
        healthy = Observer(io.StringIO(), path, spawn, lambda: clock[0])
        assert healthy.close()['streaming_until_child_exit']
        clock[0] = 20
        stale = Observer(io.StringIO(), path, spawn, lambda: clock[0])
        path.write_text(json.dumps(dict(operation='unroot', began=20.1, ready=20.2)) + '\n')
        clock[0] = 22; stale.tick()
        before = len(calls); calls[-1].returncode = 255
        clock[0] = 23; stale.tick()
        assert len(calls) == before and not stale.close()['streaming_until_child_exit']
    return ('PASS: log observer requires an owned request, device wait and verified UID transition; '
            'lost restart text still accounts for an actual reset; no frontend action replay; '
            'no-op/failed requests, stale resets and unexplained EOF do not authorise reconnect.\n')
