#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Observe single-key PDF closes without replay.
import datetime
import json
import re
import shlex
import time


def resume_input_release(logcat, pid):
    # A release without its matching start cannot prove readiness. Callers
    # clear logcat before BACK, then inspect only this retained native PID.
    started = released = None
    for line in logcat.splitlines():
        fields = line.split()
        if len(fields) < 6 or fields[2] != pid:
            continue
        event = re.search(r'Android foreground input block (started|released) uptime_ms=(\d+)', line)
        if not event:
            continue
        uptime = int(event[2])
        if event[1] == 'started':
            started, released = uptime, None
        else:
            released = uptime if started is not None and uptime >= started else None
    if released is None:
        return None
    return dict(start_uptime_ms=started, release_uptime_ms=released)


def controls():
    def event(kind, uptime, pid='123'):
        return ('10-16 01:02:03.000 ' + pid + ' 124 D app: Android foreground input block ' +
                kind + ' uptime_ms=' + str(uptime) + '\n')
    start, release = event('started', 100), event('released', 101)
    assert resume_input_release(start + release, '123') == dict(start_uptime_ms=100, release_uptime_ms=101)
    assert resume_input_release(start + event('released', 100), '123')['release_uptime_ms'] == 100
    checks = ['PASS: paired native release accepted, including immediate release after pause delta']
    for name, logs, pid in [
        ('empty log', '', '123'), ('start without release', start, '123'),
        ('release without start', release, '123'), ('wrong process', start + release, '321'),
        ('release before start', release + start, '123'),
        ('new block after release', start + release + event('started', 102), '123'),
        ('regressed uptime', start + event('released', 99), '123'),
        ('other process release', start + event('released', 101, '321'), '123'),
    ]:
        assert resume_input_release(logs, pid) is None, name
        checks.append('PASS: native input-readiness control rejected: ' + name)
    return '\n'.join(checks)


class CloseProbe:
    def __init__(self, harness, mode):
        self.h = harness
        self.prefix = 'pdf-' + mode + '-close'
        self.sequence = 0

    def record(self, **fields):
        fields.update(host_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      host_monotonic=time.monotonic(), cycle=self.sequence)
        with (self.h.evidence / (self.prefix + '-markers.txt')).open('a') as output:
            output.write(json.dumps(fields) + '\n')

    def key(self, purpose):
        # Keep the original key's 0.4 s post-injection delay. Device markers
        # surround the actual input command in the same shell, avoiding an
        # extra ADB round trip between the marker and injection.
        label = self.prefix + '-' + str(self.sequence) + '-' + purpose
        self.record(event='key-begin', purpose=purpose, code='KEYCODE_DEL')
        script = ('log -t ESDE-PDF-CLOSE ' + shlex.quote(label + ' begin') +
                  '; cat /proc/uptime; input keyevent KEYCODE_DEL; result=$?; ' +
                  'cat /proc/uptime; log -t ESDE-PDF-CLOSE ' + shlex.quote(label + ' end') +
                  '; exit "$result"')
        uptime = self.h.shell('sh', '-c', script)
        self.record(event='key-end', purpose=purpose, device_uptime_before_after=uptime)
        time.sleep(0.4)

    def capture(self, reason):
        h = self.h
        name = self.prefix + '-' + str(self.sequence) + '-' + reason
        # Each capture is independent: diagnostic capability failures must not
        # prevent the remaining live evidence, or replace the close assertion.
        actions = [
            ('screen', lambda: (h.evidence / (name + '.png')).write_bytes(
                h.adb('exec-out', 'screencap', '-p', binary=True))),
            ('input', lambda: (h.evidence / (name + '-input.txt')).write_text(h.shell('dumpsys', 'input'))),
            ('window', lambda: (h.evidence / (name + '-window.txt')).write_text(h.shell('dumpsys', 'window'))),
            ('surface', lambda: self.surface(name)),
            ('stacks', lambda: h.capture_frontend_stacks(name)),
            ('logs', lambda: h.save_logs(name)),
        ]
        for stage, action in actions:
            try:
                action()
                self.record(event='capture', reason=reason, stage=stage)
            except Exception as error:
                self.record(event='capture-error', reason=reason, stage=stage, error=str(error))

    def surface(self, name):
        h = self.h
        layers = h.shell('dumpsys', 'SurfaceFlinger', '--list')
        state = h.shell('dumpsys', 'SurfaceFlinger')
        for layer in layers.splitlines():
            if h.app in layer or 'org.esdeplus.frontend.MainActivity' in layer:
                state += '\nLAYER ' + layer + '\n' + h.shell('dumpsys', 'SurfaceFlinger', '--latency', layer)
        (h.evidence / (name + '-surface.txt')).write_text(layers + '\n' + state)

    def close(self, visible, diagnostic=False, kind='reopen'):
        self.sequence += 1
        self.record(event='cycle-begin', kind=kind)
        stops_before = len(re.findall(r'PDF viewer stopped ticks=', self.h.log()))
        polls = 0

        def closed():
            nonlocal polls
            polls += 1
            png = self.h.adb('exec-out', 'screencap', '-p', binary=True)
            opened = visible(png)
            stopped = len(re.findall(r'PDF viewer stopped ticks=', self.h.log())) > stops_before
            self.record(event='poll', poll=polls, manual_visible=opened, native_stopped=stopped)
            if polls == 1 or not opened:
                (self.h.evidence / (self.prefix + '-' + str(self.sequence) +
                                    '-poll-' + str(polls) + '.png')).write_bytes(png)
            # A black/transition frame can lack all manual markers while the
            # viewer is still inside stopPDFViewer. Require actual native stop.
            return stopped and not opened

        try:
            self.key('single-close')
            self.h.wait_for(closed, 'manual closed before next cycle')
        except Exception:
            self.capture('timeout')
            if diagnostic:
                # This second key can only diagnose the already failed cycle.
                # It never satisfies the original assertion or changes its result.
                try:
                    self.key('diagnostic-second-key')
                    self.record(event='second-key-result', closed=closed())
                    self.h.save_logs(self.prefix + '-' + str(self.sequence) + '-second-key')
                except Exception as error:
                    self.record(event='second-key-error', error=str(error))
            raise
        self.h.save_logs(self.prefix + '-' + str(self.sequence))
        self.record(event='cycle-end', polls=polls)
        return polls
