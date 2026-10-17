#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real surface/renderer resize regression evidence.
import json
import os
import re
import time


RELOAD = r'Window size has changed from (\d+x\d+) to (\d+x\d+), reloading'
HOOK = (r'Window snapshot source=surfaceChanged size=(\d+x\d+) '
        r'decor=(\d+x\d+) metrics=(\d+x\d+) surface=(\d+x\d+)')


def ordered_snapshot(logs, size):
    for hook in re.finditer(HOOK, logs):
        snapshot, decor, metrics, child = hook.groups()
        if snapshot != size or decor != size or metrics != size:
            continue
        surface = logs.find('Window size: ' + child, hook.end())
        comparison = logs.find('Android window snapshot ' + size + ', renderer ', surface)
        if hook.end() <= surface < comparison:
            return True
    return False


def matching_frames(logs):
    hooks = list(re.finditer(HOOK, logs))
    assert hooks, 'Missing hook-time window geometry'
    for hook in hooks:
        snapshot, decor, metrics, _ = hook.groups()
        assert snapshot == decor == metrics, 'Hook frame disagrees with window bounds: ' + hook.group()
    return hooks


def render_thread(logs, pid):
    # Native workers can inherit SDLThread's kernel name. The startup line
    # comes from SDL_main itself, so its logcat TID identifies the renderer.
    tids = set(re.findall(r'(?m)^\S+\s+\S+\s+' + re.escape(pid) +
                          r'\s+(\d+)\s+I\s+.*Application startup time:', logs))
    assert len(tids) == 1, ('Missing unique native startup thread', tids)
    return tids.pop()


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
    assert re.findall(r'Display resolution: (\d+x\d+)', h.log())[-1] == full
    assert re.findall(r'Screen mode: (\w+)', h.log())[-1] == 'fullscreen'
    startup = h.adb('logcat', '-d', '-v', 'threadtime')
    startup = '\n'.join(line for line in startup.splitlines()
                        if re.search(r'\s' + pid + r'\s', line))
    if not control:
        matching_frames(startup)
        assert ordered_snapshot(startup, full), startup
    tid = render_thread(startup, pid)
    assert h.private('cat', f'/proc/{pid}/task/{tid}/comm').strip() == 'SDLThread'
    rows = []

    def capture(name):
        h.save_logs(name)
        for service in ('activity', 'window', 'input', 'SurfaceFlinger'):
            (h.evidence / (name + '-' + service + '.txt')).write_text(
                h.shell('dumpsys', service, check=False))
        h.screenshot(name)

    def action(name, command, expected=None, single=False):
        before = h.log()
        def cpu_ticks():
            fields = h.private('cat', f'/proc/{pid}/task/{tid}/schedstat').split()
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
            hooks = list(re.finditer(HOOK, own))
            target = expected or (hooks[-1][1] if hooks else None)
            resolutions = re.findall(r'Application resolution: (\d+x\d+)', delta)
            complete = (target and surfaces and reloads and
                        reloads[-1][1] == target and resolutions and resolutions[-1] == target and
                        delta.count('Setting up AudioManager...') == len(reloads))
            if complete:
                if not control:
                    matching_frames(own)
                    assert ordered_snapshot(own, target), 'Snapshot was not published before native compared: ' + own
                if single:
                    assert len(reloads) == 1, ('Duplicate resize reload', name, reloads)
                display = re.findall(r'Display resolution: (\d+x\d+)', delta)[-1]
                mode = re.findall(r'Screen mode: (\w+)', delta)[-1]
                assert mode == ('fullscreen' if target == display else 'windowed'), (name, target, display, mode)
                assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), name
                row = dict(action=name, command=command, size=target, reloads=len(reloads),
                           audio_setups=delta.count('Setting up AudioManager...'), pid=pid,
                           snapshot_before_native=not control, screen_mode=mode, display=display)
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
                    render_tid=tid, cpu_ns_before=cpu_before, cpu_ns_after=cpu_after,
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
    fixed_rotation = h.shell('wm', 'fixed-to-user-rotation').strip()
    assert fixed_rotation in ('default', 'enabled', 'disabled'), fixed_rotation
    try:
        try:
            cycle_start = h.log()
            for cycle in range(1, 21):
                action(f'window-{cycle:02}-resize', ('wm', 'size', reduced), reduced, single=True)
                action(f'window-{cycle:02}-reset', ('wm', 'size', 'reset'), full, single=True)
        except LostResize as error:
            if not control:
                raise
            (h.evidence / 'window-positive-control.txt').write_text(str(error) + '\n')
            print('PASS: unfixed main positive control: ' + str(error), flush=True)
            return
        assert not control, 'Unfixed main completed 20/20; G-31 positive control not reproduced'
        capture('window-20-cycles')
        assert len(re.findall(RELOAD, h.log()[len(cycle_start):])) == 40, 'Unexpected cycle reload count'
        if not h.television:
            h.shell('settings', 'put', 'system', 'accelerometer_rotation', '0')
            h.shell('settings', 'put', 'system', 'user_rotation', '0')
            # SDL fixes the activity orientation to its current window shape.
            # Force a real display rotation through Android's shell policy;
            # changing user_rotation alone is ignored by SENSOR_PORTRAIT.
            h.shell('wm', 'fixed-to-user-rotation', 'enabled')
            rotated = action('window-rotate', ('settings', 'put', 'system', 'user_rotation', '1'))
            assert rotated != full, 'Rotation did not change geometry'
            capture('window-rotated')
            display = (h.evidence / 'window-rotated-window.txt').read_text()
            assert re.search(r'\n\s*mRotation=(?:1|ROTATION_90)\b', display), 'Display did not rotate'
            action('window-rotate-reset', ('settings', 'put', 'system', 'user_rotation', '0'), full)
            capture('window-rotation')
            h.shell('wm', 'fixed-to-user-rotation', fixed_rotation)
            # The diagnostic AVD exposes freeform via its developer setting.
            # Mode entry alone can leave the bounds unchanged on API 31.
            # Wait for its layout/native agreement, then resize the real task.
            marker = 'window-freeform-mode-' + str(time.monotonic_ns())
            h.shell('log', '-p', 'i', '-t', 'ESDEPlusWindow', marker)
            h.shell('am', 'start', '--windowingMode', '5', '-n', h.activity)
            deadline = time.monotonic() + 60
            while True:
                assert h.shell('pidof', h.app, check=False).strip() == pid, 'PID changed entering freeform'
                logs = h.adb('logcat', '-d', '-v', 'threadtime')
                assert marker in logs, 'Freeform mode marker missing from logcat'
                logs = logs.split(marker, 1)[1]
                own = '\n'.join(line for line in logs.splitlines()
                                if re.search(r'\s' + pid + r'\s', line))
                sizes = re.findall(r'Window snapshot source=(?:layout|surfaceChanged) size=(\d+x\d+)', own)
                native = h.log()
                rendered = re.findall(r'Application resolution: (\d+x\d+)', native)
                if (sizes and rendered and sizes[-1] == rendered[-1] and
                        native.count('Setting up AudioManager...') == len(re.findall(RELOAD, native)) + 1):
                    break
                assert time.monotonic() < deadline, 'Freeform mode layout/native agreement timed out'
                time.sleep(.25)
            dump, records = h.activity_records()
            assert len(records) == 1, dump
            task = records[0][1]
            task_mode = r'Task\{[^\n]*#' + re.escape(task) + r'\b[^\n]*mode=freeform'
            assert re.search(task_mode, dump), dump
            capture('window-freeform-enter')
            width, height = map(int, physical.groups())
            action('window-freeform-resize-1', ('am', 'task', 'resize', task, '0', '0',
                                               str(width * 3 // 5), str(height * 3 // 5)), single=True)
            action('window-freeform-resize', ('am', 'task', 'resize', task, '0', '0',
                                             str(width * 4 // 5), str(height * 4 // 5)), single=True)
            dump = h.shell('dumpsys', 'activity', 'activities')
            (h.evidence / 'window-freeform-activities.txt').write_text(dump)
            assert re.search(task_mode, dump), dump
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
        h.shell('wm', 'fixed-to-user-rotation', fixed_rotation)


def self_test():
    startup = '10-17 00:00:00.000 123 456 I app: Info: Application startup time: 200 ms'
    assert render_thread(startup, '123') == '456'
    assert render_thread(startup + '\n' + startup.replace('123 456', '789 111'), '123') == '456'
    try:
        render_thread(startup + '\n' + startup.replace('123 456', '123 999'), '123')
    except AssertionError:
        pass
    else:
        raise AssertionError('Ambiguous native startup threads accepted')
    logs = ('Window snapshot source=surfaceChanged size=972x1728 '
            'decor=972x1728 metrics=972x1728 surface=972x1602\n'
            'SDL: Window size: 972x1602\nAndroid window snapshot 972x1728, renderer 1080x1920')
    assert ordered_snapshot(logs, '972x1728')
    matching_frames(logs)
    assert not ordered_snapshot('\n'.join(reversed(logs.splitlines())), '972x1728')
    assert not ordered_snapshot(logs.replace('size=972x1728', 'size=1080x1920'), '972x1728')
    assert not ordered_snapshot(logs.replace('snapshot 972x1728', 'snapshot 1080x1920'), '972x1728')
    assert not ordered_snapshot(logs.replace('decor=972x1728', 'decor=1080x1920'), '972x1728')
    assert not ordered_snapshot(logs.replace('metrics=972x1728', 'metrics=1080x1920'), '972x1728')
    print('PASS: window ordering oracle rejects stale, late and missing snapshots')


if __name__ == '__main__':
    self_test()
