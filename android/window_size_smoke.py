#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real surface/renderer resize regression evidence.
import json
import os
import re
import time


RELOAD = r'Window size has changed from (\d+x\d+) to (\d+x\d+), reloading'


def ordered_snapshot(logs, size):
    publication = logs.find('Window snapshot source=surfaceChanged size=' + size)
    surface = logs.find('Window size: ' + size, publication)
    comparison = logs.find('Android window snapshot ' + size + ', renderer ', surface)
    return 0 <= publication < surface < comparison


class LostResize(AssertionError):
    pass


def run(harness):
    h = type('Harness', (), harness)
    control = os.environ.get('ESDE_WINDOW_CONTROL') == '1'
    physical = re.search(r'Physical size: (\d+)x(\d+)', h.shell('wm', 'size'))
    assert physical, 'Missing physical display size'
    full = 'x'.join(physical.groups())
    reduced = 'x'.join(str(int(int(value) * .9)) for value in physical.groups())
    # DebugMode enables existing native debug logging; every other setting,
    # including navigation audio, retains its default value.
    settings = h.shell('cat', h.settings)
    settings, count = re.subn(r'(<bool name="DebugMode" value=")[^"]*("\s*/>)',
                              r'\g<1>true\2', settings)
    assert count == 1, 'Missing DebugMode setting'
    h.user_file('settings/es_settings.xml', settings)
    h.launch()
    h.configured_system('window-debug-start')
    pid = h.shell('pidof', h.app).strip()
    assert pid.isdigit()
    assert re.findall(r'Application resolution: (\d+x\d+)', h.log())[-1] == full
    tids = [tid for tid in h.private('ls', '/proc/' + pid + '/task').split()
            if h.private('cat', f'/proc/{pid}/task/{tid}/comm', check=False).strip() == 'SDLThread']
    assert len(tids) == 1, ('Missing unique frontend render thread', tids)
    rows = []

    def capture(name):
        h.save_logs(name)
        for service in ('activity', 'window', 'input', 'SurfaceFlinger'):
            (h.evidence / (name + '-' + service + '.txt')).write_text(
                h.shell('dumpsys', service, check=False))
        h.screenshot(name)

    def action(name, command, expected=None):
        before = h.log()
        def cpu_ticks():
            fields = h.private('cat', f'/proc/{pid}/task/{tids[0]}/schedstat').split()
            assert len(fields) == 3 and all(value.isdigit() for value in fields), fields
            return int(fields[0])
        marker = name + '-' + str(time.monotonic_ns())
        h.shell('log', '-p', 'i', '-t', 'ESDEPlusWindow', marker)
        h.shell(*command)
        deadline = time.monotonic() + 60
        while True:
            assert h.shell('pidof', h.app, check=False).strip() == pid, 'Host PID changed: ' + name
            logs = h.adb('logcat', '-d', '-v', 'threadtime')
            assert marker in logs, 'Window action marker missing from logcat'
            interval = logs.split(marker, 1)[1]
            own = '\n'.join(line for line in interval.splitlines()
                            if re.search(r'\s' + pid + r'\s', line))
            assert not re.search(r'Fatal signal|FORTIFY|FATAL EXCEPTION|Destroying SDL activity', own), own
            surfaces = re.findall(r'Window size: (\d+x\d+)', own)
            current = h.log()
            assert current.startswith(before), 'Native log replaced during resize: ' + name
            delta = current[len(before):]
            reloads = re.findall(RELOAD, delta)
            target = expected or (surfaces[-1] if surfaces else None)
            resolutions = re.findall(r'Application resolution: (\d+x\d+)', delta)
            complete = (target and surfaces and surfaces[-1] == target and reloads and
                        reloads[-1][1] == target and resolutions and resolutions[-1] == target and
                        delta.count('Setting up AudioManager...') == len(reloads))
            if complete:
                if not control:
                    assert ordered_snapshot(own, target), 'Snapshot was not published before native compared: ' + own
                assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), name
                row = dict(action=name, command=command, size=target, reloads=len(reloads),
                           audio_setups=delta.count('Setting up AudioManager...'), pid=pid,
                           snapshot_before_native=not control)
                rows.append(row)
                (h.evidence / 'window-cycles.txt').write_text(json.dumps(rows, indent=2) + '\n')
                (h.evidence / (name + '-logcat.txt')).write_text(interval)
                (h.evidence / (name + '-es_log.txt')).write_text(delta)
                print('WINDOW ' + json.dumps(row), flush=True)
                return target
            if time.monotonic() >= deadline:
                cpu_before = cpu_ticks()
                progress_start = time.monotonic()
                capture(name + '-timeout')
                cpu_after = cpu_ticks()
                (h.evidence / (name + '-progress.txt')).write_text(json.dumps(dict(
                    render_tid=tids[0], cpu_ns_before=cpu_before, cpu_ns_after=cpu_after,
                    seconds=time.monotonic() - progress_start)) + '\n')
                h.capture_frontend_stacks(name + '-timeout')
                assert h.shell('pidof', h.app, check=False).strip() == pid, name
                # A control hit requires an actual new SDL surface, no native
                # reload, the original live focused process and no fatal/destroy.
                rendered = re.findall(r'Application resolution: (\d+x\d+)', current)[-1]
                if (target and surfaces and surfaces[-1] == target and rendered != target and
                        not reloads and cpu_after > cpu_before):
                    assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), name
                    raise LostResize(f'G-31: {name}, SDL surface={target}, no native reload, pid={pid}')
                raise AssertionError('Resize did not complete: ' + name)
            time.sleep(.25)

    rotation = {key: h.shell('settings', 'get', 'system', key).strip()
                for key in ('accelerometer_rotation', 'user_rotation')}
    try:
        try:
            for cycle in range(1, 21):
                action(f'window-{cycle:02}-resize', ('wm', 'size', reduced), reduced)
                action(f'window-{cycle:02}-reset', ('wm', 'size', 'reset'), full)
        except LostResize as error:
            if not control:
                raise
            (h.evidence / 'window-positive-control.txt').write_text(str(error) + '\n')
            print('PASS: unfixed main positive control: ' + str(error), flush=True)
            return
        assert not control, 'Unfixed main completed 20/20; G-31 positive control not reproduced'
        capture('window-20-cycles')
        if not h.television:
            h.shell('settings', 'put', 'system', 'accelerometer_rotation', '0')
            h.shell('settings', 'put', 'system', 'user_rotation', '0')
            rotated = action('window-rotate', ('settings', 'put', 'system', 'user_rotation', '1'))
            assert rotated != full, 'Rotation did not change geometry'
            action('window-rotate-reset', ('settings', 'put', 'system', 'user_rotation', '0'), full)
            capture('window-rotation')
            # The diagnostic AVD exposes freeform via its developer setting.
            # Use real task bounds, then drag to another size within that mode.
            action('window-freeform-enter', ('am', 'start', '--windowingMode', '5', '-n', h.activity))
            dump, records = h.activity_records()
            assert len(records) == 1, dump
            task = records[0][1]
            width, height = map(int, physical.groups())
            action('window-freeform-resize', ('am', 'task', 'resize', task, '0', '0',
                                             str(width * 4 // 5), str(height * 4 // 5)))
            dump = h.shell('dumpsys', 'activity', 'activities')
            (h.evidence / 'window-freeform-activities.txt').write_text(dump)
            assert 'windowingMode=freeform' in dump or 'mode=freeform' in dump, dump
            capture('window-freeform')
        (h.evidence / 'window-result.txt').write_text(
            'PASS: 20/20 wm size 90%/reset cycles, 40 actions, matching native reload/audio setup; '
            'snapshot published before native compare on every action; same PID.\n')
    except BaseException:
        capture('window-failure')
        raise
    finally:
        h.shell('wm', 'size', 'reset')
        for key, value in rotation.items():
            h.shell('settings', 'delete', 'system', key) if value == 'null' else \
                h.shell('settings', 'put', 'system', key, value)


def self_test():
    logs = ('Window snapshot source=surfaceChanged size=972x1728\n'
            'SDL: Window size: 972x1728\nAndroid window snapshot 972x1728, renderer 1080x1920')
    assert ordered_snapshot(logs, '972x1728')
    assert not ordered_snapshot('\n'.join(reversed(logs.splitlines())), '972x1728')
    assert not ordered_snapshot(logs.replace('size=972x1728', 'size=1080x1920'), '972x1728')
    assert not ordered_snapshot(logs.replace('snapshot 972x1728', 'snapshot 1080x1920'), '972x1728')
    print('PASS: window ordering oracle rejects stale, late and missing snapshots')


if __name__ == '__main__':
    self_test()
