#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Observe single-key PDF closes without replay.
import datetime
import json
import shlex
import time


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

    def close(self, visible, diagnostic=False):
        self.sequence += 1
        self.record(event='cycle-begin')
        self.key('single-close')
        polls = 0

        def closed():
            nonlocal polls
            polls += 1
            png = self.h.adb('exec-out', 'screencap', '-p', binary=True)
            opened = visible(png)
            self.record(event='poll', poll=polls, manual_visible=opened)
            if polls == 1 or not opened:
                (self.h.evidence / (self.prefix + '-' + str(self.sequence) +
                                    '-poll-' + str(polls) + '.png')).write_bytes(png)
            return not opened

        try:
            self.h.wait_for(closed, 'manual closed before next cycle')
        except Exception:
            self.capture('timeout')
            if diagnostic:
                # This second key can only diagnose the already failed cycle.
                # It never satisfies the original assertion or changes its result.
                self.key('diagnostic-second-key')
                self.record(event='second-key-result', closed=closed())
                self.h.save_logs(self.prefix + '-' + str(self.sequence) + '-second-key')
            raise
        self.h.save_logs(self.prefix + '-' + str(self.sequence))
        self.record(event='cycle-end', polls=polls)
        return polls
