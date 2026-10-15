#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real window-reload audio regression and controls.
import hashlib
import io
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
import pdf_smoke


# Main at WO-15 dispatch. Only this source file replaces the current source in
# the isolated control; no other workstream or APK is used.
CONTROL_BASE = '063e454da'
ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTROL = ROOT / 'android/.deps/audio-control'


class ControlComplete(Exception):
    pass


class GLTransportInfrastructure(Exception):
    pass


def build_control():
    source = CONTROL / 'source'
    assert not source.exists(), 'Control build must start in a fresh directory'
    source.mkdir(parents=True)
    archive = subprocess.check_output(['git', 'archive', 'HEAD'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(source, filter='data')
    original = subprocess.check_output(
        ['git', 'show', CONTROL_BASE + ':es-core/src/AudioManager.cpp'], cwd=ROOT)
    assert b'SDL_CloseAudio();' in original
    (source / 'es-core/src/AudioManager.cpp').write_bytes(original)
    # Reuse verified dependency sources/installs, never native app objects.
    (source / 'android/.deps').symlink_to(ROOT / 'android/.deps', target_is_directory=True)
    (source / 'android/libs').symlink_to(ROOT / 'android/libs', target_is_directory=True)
    normal_apk = ROOT / 'android/app/build/outputs/apk/debug/app-debug.apk'
    before = hashlib.sha256(normal_apk.read_bytes()).hexdigest()
    subprocess.run(['bash', 'tools/Android_dependencies_setup.sh'], cwd=source, check=True)
    subprocess.run(['./gradlew', '--no-daemon', *shlex.split(os.environ.get('GRADLE_NETWORK_ARGS', '')),
                    '-Pesde.versionCode=' + os.environ['ESDE_VERSION_CODE'],
                    '-Pesde.versionName=test-' + subprocess.check_output(
                        ['git', 'rev-parse', '--short=9', 'HEAD'], cwd=ROOT, text=True).strip(),
                    ':app:assembleDebug'], cwd=source / 'android', check=True)
    shutil.copyfile(source / 'android/app/build/outputs/apk/debug/app-debug.apk', CONTROL / 'unfixed.apk')
    assert hashlib.sha256(normal_apk.read_bytes()).hexdigest() == before
    evidence = ROOT / 'android/evidence/audio-control-build.txt'
    evidence.write_text(f'Unfixed AudioManager source: {CONTROL_BASE}\n'
                        f'Unfixed source SHA256: {hashlib.sha256(original).hexdigest()}\n'
                        f'Normal APK unchanged: {before}\n'
                        'Control rebuilt in isolated source; runner only, never uploaded.\n')


def control_launch():
    if os.environ['IMAGE'] == 'api34':
        return
    app = next(line.split('=', 1)[1] for line in (ROOT / 'android/gradle.properties').read_text().splitlines()
               if line.startswith('esde.applicationId='))

    def shell(*arguments):
        return subprocess.check_output(['adb', 'shell', *arguments], text=True).strip()

    def font_weight():
        configuration = shell('dumpsys', 'activity', 'activities')
        match = re.search(r'^\s*mGlobalConfig=.*\bfontWeightAdjustment=(-?\d+)', configuration, re.M)
        assert match, 'Global font-weight configuration unavailable'
        return match.group(1)

    api = int(shell('getprop', 'ro.build.version.sdk'))
    if api >= 31:
        previous_setting = shell('settings', 'get', 'secure', 'font_weight_adjustment')
        previous_weight = font_weight()
    try:
        result = subprocess.run([sys.executable, 'android/smoke.py', str(CONTROL / 'unfixed.apk'),
                                 '--audio-control'], cwd=ROOT)
        (ROOT / 'android/evidence/audio-control-result.txt').write_text(str(result.returncode) + '\n')
    finally:
        for failure in (ROOT / 'android/evidence').glob('failure*'):
            failure.rename(failure.with_name('audio-control-' + failure.name))
        # Controls use the normal SDK debug signer, preceding the full gating
        # smoke's independently signed APK. Never transfer data across signers.
        subprocess.run(['adb', 'uninstall', app], check=True)
        if api >= 31:
            # The inherited smoke deletes an originally absent setting, which
            # can leave the effective configuration at the probe's weight. Put
            # the original effective value first so the next full smoke must
            # trigger a real change again; preserve the original database value.
            shell('settings', 'put', 'secure', 'font_weight_adjustment', previous_weight)
            deadline = time.monotonic() + 30
            while font_weight() != previous_weight:
                assert time.monotonic() < deadline, 'Control did not restore effective font weight'
                time.sleep(.25)
            if previous_setting == 'null':
                shell('settings', 'delete', 'secure', 'font_weight_adjustment')
            else:
                shell('settings', 'put', 'secure', 'font_weight_adjustment', previous_setting)
            assert shell('settings', 'get', 'secure', 'font_weight_adjustment') == previous_setting
            assert font_weight() == previous_weight
            (ROOT / 'android/evidence/audio-control-device-restored.txt').write_text(
                f'PASS: original font-weight setting={previous_setting}; '
                f'effective weight={previous_weight}; both restored before fixed smoke.\n')


def xml_settings(document):
    return '<?xml version="1.0"?>\n' + ''.join(ET.tostring(n, encoding='unicode') for n in document)


def set_setting(document, kind, name, value):
    node = document.find(f"{kind}[@name='{name}']")
    if node is None:
        node = ET.SubElement(document, kind, name=name)
    node.set('value', str(value))


def fatal_lines(logcat, pid, app):
    # libc/FORTIFY messages carry the crashing PID; crash-buffer records carry
    # the package. Unrelated stock-launcher crashes do not count as this defect.
    # Read the emitting PID column, not a PID mentioned in a diagnostic message
    # (debuggerd -b registers a nonfatal tombstoned backtrace intercept for it).
    return [line for line in logcat.splitlines()
            if (re.match(r'^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+\s+' + re.escape(pid) +
                         r'\s+\d+\s+[VDIWEFAS]\s+', line) or app in line)
            and re.search(r'FORTIFY|Fatal signal|tombstone|>>>.*' + re.escape(app), line, re.I)]


def after_marker(logcat, marker):
    lines = logcat.splitlines()
    boundary = [index for index, line in enumerate(lines)
                if re.search(r'\bI\s+ESDEPlusAudio\s*:\s*' + re.escape(marker) + r'$', line)]
    assert len(boundary) == 1, 'Audio action log boundary missing or ambiguous'
    return '\n'.join(lines[boundary[0] + 1:])


def marker_time(logcat, marker):
    after_marker(logcat, marker)  # Reject missing/duplicate boundaries first.
    matches = re.findall(r'^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\s+.*'
                         r'\bI\s+ESDEPlusAudio\s*:\s*' + re.escape(marker) + r'$', logcat, re.M)
    assert len(matches) == 1, 'Audio action log timestamp unavailable'
    return matches[0]


def startup_relaunch_allowed(dismissed, created, used, stock_focused):
    return dismissed and not created and not used and stock_focused


def capture_startup(h, name):
    # Capture the live failure/preemption, before run()'s finally restores HOME.
    (h.evidence / (name + '.png')).write_bytes(h.adb('exec-out', 'screencap', '-p', binary=True))
    (h.evidence / (name + '-window.txt')).write_text(h.focused_window())
    (h.evidence / (name + '-activities.txt')).write_text(h.shell('dumpsys', 'activity', 'activities'))
    (h.evidence / (name + '-logcat-tail.txt')).write_text(
        h.adb('logcat', '-d', '-v', 'threadtime', '-t', '300'))
    (h.evidence / (name + '-es_log.txt')).write_text(h.log())


def startup(harness, name, baseline):
    h = type('Harness', (), harness)
    previous_guard = harness['onboarding_guard']
    dismissals = harness['onboarding_dismissals']
    initial_pid = h.shell('pidof', h.app, check=False).strip()
    marker = name + '-' + str(time.monotonic_ns())
    h.shell('log', '-p', 'i', '-t', 'ESDEPlusAudio', marker)
    since = marker_time(h.adb('logcat', '-d', '-v', 'threadtime', 'ESDEPlusAudio:I', '*:S'), marker)
    def logs():
        return after_marker(h.adb('logcat', '-d', '-b', 'main,system,crash',
                                  '-v', 'threadtime', '-T', since), marker)
    used = False
    try:
        harness['onboarding_guard'] = h.television
        h.dismiss_stock_onboarding(force=True)
        h.shell('am', 'start', '-n', h.activity)
        started = time.monotonic()
        def ready():
            nonlocal used
            current = h.log()
            if current != baseline and 'Application startup time:' in current:
                return True
            if h.television and not used and time.monotonic() - started >= 5:
                interval = logs()
                created = (bool(initial_pid) or 'Creating sole SDL activity' in interval or
                           re.search(r'\bSDL\s*:\s*onCreate\(\)', interval) is not None)
                dismissed = harness['onboarding_dismissals'] > dismissals
                stock_focused = h.smoke_checks.package_window_focused(h.focused_window(), h.stock_package)
                if startup_relaunch_allowed(dismissed, created, used, stock_focused):
                    capture_startup(h, name + '-onboarding-preempted')
                    (h.evidence / (name + '-pre-relaunch-logcat.txt')).write_text(interval)
                    with (h.evidence / 'audio-startup-relaunches.jsonl').open('a') as output:
                        output.write(json.dumps(dict(session=name, relaunch=1, marker=marker,
                            stock_tutorial_dismissed=True, activity_created=False, initial_pid=initial_pid,
                            pid=h.shell('pidof', h.app, check=False).strip())) + '\n')
                    used = True
                    # D-019 am. 2 only: no force-stop, settings change or deadline
                    # extension; at most one start after proven stock preemption.
                    h.shell('am', 'start', '-n', h.activity)
            return False
        h.wait_for(ready, 'fresh frontend startup/system loading')
    except BaseException:
        capture_startup(h, name + '-startup-timeout')
        raise
    finally:
        harness['onboarding_guard'] = previous_guard


def gl_transport_stall(stacks, later='', cpu=None, later_cpu=None, elapsed=0, surface=False):
    # Require both signatures in their own captured threads, never a match
    # assembled from unrelated frames elsewhere in the process dump.
    threads = re.findall(r'^"([^"\n]+)"[^\n]*\n(.*?)(?=^"|^----- end|\Z)',
                         stacks, re.M | re.S)
    render = [body for name, body in threads if name == 'SDLThread']
    audio = [body for name, body in threads if re.fullmatch(r'SDLAudioP\d+', name)]
    signature = (len(render) == 1 and bool(audio)
            and re.search(r'#00\s+pc\s+.*\b(?:write|read|ioctl)(?:\+|\))', render[0]) is not None
            and re.search(r'(?:QemuPipeStream::|goldfish_pipe_).*\n(?:.*\n)*?.*glGetError_enc',
                          render[0]) is not None
            and all(re.search(r'#0[0-3]\s+pc\s+.*\b(?:sem_wait|SDL_SemWait)(?:\+|\))', body)
                    and 'libSDL2.so' in body and 'AudioStream' not in body for body in audio))
    if not signature or not later or not surface or elapsed < 5:
        return False
    # A healthy debug render loop routinely has this signature. Require the
    # same native frames and thread identity, plus no CPU progress between the
    # captures. A single snapshot (including QA's healthy capture) proves nothing.
    later_threads = re.findall(r'^"([^"\n]+)"[^\n]*\n(.*?)(?=^"|^----- end|\Z)',
                               later, re.M | re.S)
    later_render = [body for name, body in later_threads if name == 'SDLThread']
    later_audio = [body for name, body in later_threads if re.fullmatch(r'SDLAudioP\d+', name)]
    frames = lambda body: re.findall(r'^\s*(#\d+\s+pc\s+[^\n]+)', body, re.M)
    tid = lambda dump: re.findall(r'^"SDLThread"[^\n]*\bsysTid=(\d+)\b', dump, re.M)
    return (len(later_render) == 1 and frames(render[0]) == frames(later_render[0])
            and bool(later_audio) and all(re.search(
                r'#0[0-3]\s+pc\s+.*\b(?:sem_wait|SDL_SemWait)(?:\+|\))', body)
                and 'libSDL2.so' in body and 'AudioStream' not in body for body in later_audio)
            and len(tid(stacks)) == 1 and tid(stacks) == tid(later)
            and isinstance(cpu, int) and cpu >= 0 and cpu == later_cpu)


def surface_changed(logcat, pid, size):
    own = '\n'.join(line for line in logcat.splitlines() if re.match(
        r'^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+\s+' + re.escape(pid) +
        r'\s+\d+\s+V\s+SDL\s*:', line))
    return re.search(r'surfaceChanged\(\)\n(?:.*\n)*?.*Window size: ' +
                     re.escape(size) + r'\s*(?:\n|$)', own) is not None


def active_tracks(dump, pid):
    # AudioFlinger's playback table exposes Active, Client PID (PID/UID on
    # newer Android), and the hexadecimal Server frame counter. Require the
    # playback header and the app's own client, not a global active-track count.
    server_field = None
    result = {}
    for line in dump.splitlines():
        if line.lstrip().startswith('Type') and 'Active Client' in line and 'Server FrmCnt' in line:
            # Newer tables add PortVol/PortMuted before Server. Parse columns,
            # not character offsets: their printed widths can differ from the
            # header by a space between Android versions.
            server_field = 16 if 'PortMuted' in line else 14
            continue
        match = re.match(r'^\s*(?:F\d+\s+)?(?:[SP?]\s+)?(\d+)\s+yes\s+(\d+)'
                         r'(?:\s*/\s*\d+)?\s+', line)
        if server_field is not None and match and match[2] == pid:
            fields = line[match.end():].split()
            if (len(fields) > server_field and fields[3].startswith('0x')
                    and re.fullmatch(r'[0-9A-Fa-f]{8}', fields[server_field])):
                result[match[1]] = int(fields[server_field], 16)
    return result


def audio_output(h, prefix, pid):
    snapshots = []
    tracks = []
    for sample in range(2):
        snapshots.append(h.shell('dumpsys', 'media.audio_flinger'))
        (h.evidence / f'{prefix}-audio-flinger-{sample + 1}.txt').write_text(snapshots[-1])
        tracks.append(active_tracks(snapshots[-1], pid))
        if sample == 0:
            time.sleep(.25)
    advanced = {track: [frames, tracks[1][track]] for track, frames in tracks[0].items()
                if track in tracks[1] and tracks[1][track] > frames}
    assert advanced, f'{prefix}: no active app audio track with advancing server frames (PID {pid})'
    return advanced


def capture_stacks(h, prefix, pid):
    (h.evidence / (prefix + '-window.txt')).write_text(h.shell('dumpsys', 'window', 'displays'))
    (h.evidence / (prefix + '-activities.txt')).write_text(h.shell('dumpsys', 'activity', 'activities'))
    try:
        command = 'debuggerd -b ' + shlex.quote(pid) + ' 2>&1'
        stacks = h.shell('sh', '-c', command, check=False)
        if not re.search(r'#00\s+pc\s', stacks):
            root = h.adb('root', check=False)
            h.adb('wait-for-device')
            if 'cannot run as root' in root:
                stacks += '\nCAPABILITY GAP: native backtrace unavailable: ' + root
            else:
                try:
                    h.wait_for(lambda: h.shell('id', '-u').strip() == '0',
                               'privileged reload-timeout diagnostic shell')
                    stacks += '\nPrivileged backtrace:\n' + h.shell('sh', '-c', command, check=False)
                finally:
                    h.adb('unroot', check=False)
                    h.adb('wait-for-device')
                h.wait_for(lambda: h.shell('id', '-u').strip() == '2000',
                           'ordinary shell after reload-timeout diagnostics')
    except subprocess.SubprocessError as error:
        stacks = f'Native backtrace unavailable: {error}\n'
    (h.evidence / (prefix + '-stacks.txt')).write_text(stacks)
    return stacks


def classify_stall(h, name, pid, logs, reloads, setups, size):
    prefix = name + '-reload-timeout'
    stacks = capture_stacks(h, prefix + '-1', pid)
    tids = re.findall(r'^"SDLThread"[^\n]*\bsysTid=(\d+)\b', stacks, re.M)
    def cpu_sample(number):
        raw = h.private('cat', f'/proc/{pid}/task/{tids[0]}/schedstat', check=False) if len(tids) == 1 else ''
        (h.evidence / f'{prefix}-cpu-{number}.txt').write_text(raw)
        fields = raw.split()
        return int(fields[0]) if len(fields) == 3 and all(n.isdigit() for n in fields) else None
    cpu = cpu_sample(1)
    started = time.monotonic()
    time.sleep(5)
    later_cpu = cpu_sample(2)
    elapsed = time.monotonic() - started
    later = capture_stacks(h, prefix + '-2', pid)
    interval = logs()
    (h.evidence / (prefix + '-logcat.txt')).write_text(interval)
    current = h.log()
    # Recheck after stack collection. A fatal, changed PID or an unmatched
    # audio setup cannot be reclassified by any renderer stack signature.
    assert h.shell('pidof', h.app, check=False).strip() == pid, 'PID changed during reload stall'
    assert not fatal_lines(logs(), pid, h.app), 'Native fatal during reload stall'
    assert current.count('Setting up AudioManager...') > 0
    assert current.count('Audio driver:') == current.count('Setting up AudioManager...'), 'Missing audio driver setup'
    assert not re.search(r"Couldn't initialize SDL audio|Unable to open audio device", current)
    assert (current.count('Setting up AudioManager...') - setups ==
            current.count('Window size has changed from ') - reloads), 'Missing reload audio setup'
    no_reload = current.count('Window size has changed from ') == reloads
    surface = surface_changed(interval, pid, size)
    (h.evidence / (prefix + '-progress.json')).write_text(json.dumps(dict(
        tid=tids, cpu_ns=cpu, later_cpu_ns=later_cpu, elapsed_seconds=elapsed,
        expected_size=size, java_surface_changed=surface, no_native_reload=no_reload), indent=2) + '\n')
    if no_reload and gl_transport_stall(stacks, later, cpu, later_cpu, elapsed, surface):
        message = f'{name}: emulator GL-transport infrastructure; two unchanged render stacks/CPU over {elapsed:.3f}s; Java resized to {size}, no native reload'
        (h.evidence / (name + '-infrastructure.txt')).write_text(message + '\n')
        print(message, flush=True)
        raise GLTransportInfrastructure(message)


def controls():
    assert fatal_lines('10-14 00:00:00.000 123 124 F libc: Fatal signal 6', '123', 'app')
    assert not fatal_lines('10-14 00:00:00.000 555 556 F libc: Fatal signal 6', '123', 'app')
    assert fatal_lines('10-14 00:00:00.000 123 124 F libc: FORTIFY: destroyed mutex', '123', 'app')
    assert not fatal_lines('10-14 00:00:00.000 123 124 I AudioTrack: start', '123', 'app')
    assert not fatal_lines('10-14 00:00:00.000 555 555 I /system/bin/tombstoned: '
                           'registered intercept for pid 123 and type kDebuggerdNativeBacktrace',
                           '123', 'app')
    assert not fatal_lines('10-14 00:00:00.000 555 123 F libc: Fatal signal 6', '123', 'app')
    assert fatal_lines('10-14 00:00:00.000 555 556 F DEBUG: >>> app <<<', '123', 'app')
    old_fatal = '10-14 00:00:00.000 123 124 F libc: Fatal signal 6'
    marker = '10-14 00:00:01.000 555 556 I ESDEPlusAudio: boundary-test'
    new_fatal = '10-14 00:00:02.000 123 124 F libc: FORTIFY: destroyed mutex'
    assert marker_time(marker, 'boundary-test') == '10-14 00:00:01.000'
    assert not fatal_lines(after_marker(old_fatal + '\n' + marker, 'boundary-test'), '123', 'app')
    assert fatal_lines(after_marker(marker + '\n' + new_fatal, 'boundary-test'), '123', 'app')
    for invalid in (old_fatal, marker + '\n' + marker):
        try:
            after_marker(invalid, 'boundary-test')
        except AssertionError:
            pass
        else:
            raise AssertionError('Invalid audio log boundary accepted')
    render = ('"SDLThread" sysTid=1\n'
              ' #00 pc 0000 /libc.so (write+7)\n'
              ' #01 pc 0000 /vendor/lib.so (QemuPipeStream::writeFully+83)\n'
              ' #02 pc 0000 /vendor/lib.so (glGetError_enc+209)\n')
    idle = ('"SDLAudioP2" sysTid=2\n'
            ' #00 pc 0000 /libc.so (syscall+24)\n'
            ' #01 pc 0000 /libc.so (__futex_wait_ex+138)\n'
            ' #02 pc 0000 /libc.so (sem_wait+91)\n'
            ' #03 pc 0000 /libSDL2.so (SDL_SemWait+23)\n')
    qualifies = lambda stacks: gl_transport_stall(stacks, stacks, 100, 100, 5, True)
    assert qualifies(render + idle)
    assert not gl_transport_stall(render + idle)
    for later, cpu, later_cpu, elapsed, surface in (
            (render + idle, 100, 101, 5, True),
            (render + idle, None, None, 5, True),
            (render + idle, 100, 100, 4.9, True),
            (render + idle, 100, 100, 5, False),
            (render.replace('sysTid=1', 'sysTid=3') + idle, 100, 100, 5, True),
            (render.replace('0000', '0001') + idle, 100, 100, 5, True)):
        assert not gl_transport_stall(render + idle, later, cpu, later_cpu, elapsed, surface)
    for invalid in (render, idle, render.replace('SDLThread', 'worker') + idle,
                    render.replace('glGetError_enc', 'other_gl') + idle,
                    render.replace('QemuPipeStream::', 'other::') + idle,
                    render.replace('(write+7)', '(pthread_mutex_lock+7)') + idle,
                    render + idle.replace('sem_wait', 'busy').replace('SDL_SemWait', 'busy'),
                    render + idle + idle.replace('sysTid=2', 'sysTid=3').replace(
                        'sem_wait', 'busy').replace('SDL_SemWait', 'busy')):
        assert not qualifies(invalid), 'Nonmatching stack accepted as GL infrastructure'
    # Actual healthy-frontend native excerpt (paths abbreviated): run 38772440030 API 29, artifact
    # 11999756020, network-liveness-control-attempt1-healthy-frontend-stacks.txt.
    # QA reproduced the old false positive here. A snapshot alone fails; even
    # identical repeated frames fail if the render CPU advanced.
    healthy = ('"SDLThread" sysTid=18196\n'
        ' #00 pc 00000000000ec817 /apex/com.android.runtime/lib64/bionic/libc.so (read+7)\n'
        ' #01 pc 000000000000b971 /vendor/lib64/libOpenglSystemCommon.so (QemuPipeStream::commitBufferAndReadFully(unsigned long, void*, unsigned long)+177)\n'
        ' #02 pc 0000000000049751 /vendor/lib64/libGLESv2_enc.so ((anonymous namespace)::glGetError_enc(void*)+209)\n'
        '"SDLAudioP2" sysTid=18225\n'
        ' #00 pc 00000000000943f8 /apex/com.android.runtime/lib64/bionic/libc.so (syscall+24)\n'
        ' #01 pc 0000000000097e1a /apex/com.android.runtime/lib64/bionic/libc.so (__futex_wait_ex(void volatile*, bool, int, bool, timespec const*)+138)\n'
        ' #02 pc 00000000000a2f7b /apex/com.android.runtime/lib64/bionic/libc.so (sem_wait+91)\n'
        ' #03 pc 000000000013f5a7 /base.apk!libSDL2.so (SDL_SemWait+23)\n')
    assert not gl_transport_stall(healthy)
    assert not gl_transport_stall(healthy, healthy, 100, 101, 5, True)
    java = ('10-14 00:00:02.000 123 124 V SDL: surfaceChanged()\n'
            '10-14 00:00:02.001 123 124 V SDL: Window size: 972x1728')
    assert surface_changed(java, '123', '972x1728')
    assert not surface_changed(java, '555', '972x1728')
    assert not surface_changed(java, '123', '1080x1920')
    assert not surface_changed(java.replace('surfaceChanged()', 'other'), '123', '972x1728')
    assert startup_relaunch_allowed(True, False, False, True)
    for dismissed, created, used, focused in ((False, False, False, True),
            (True, True, False, True), (True, False, True, True), (True, False, False, False)):
        assert not startup_relaunch_allowed(dismissed, created, used, focused)
    # Own table samples exercise both documented PID column layouts, reject
    # other clients/inactive tracks and require the actual server-frame field.
    for client in ('Client', 'Client(pid/uid)'):
        header = '    Type     Id Active ' + client + ' Session Port Id S  Flags '
        if '/' in client:
            header += 'PortVol dB PortMuted '
        header += 'Server FrmCnt'
        row = '              7    yes ' + ('123/ 10001' if '/' in client else '123')
        row += ' 1 2 A 0x000 00000001 00000003 44100 3 1 0 0 0 0 0'
        if '/' in client:
            row += ' 0 false'
        row += ' 00001234 4096'
        assert active_tracks(header + '\n' + row, '123') == {'7': 0x1234}
        assert not active_tracks(header + '\n' + row, '555')
        assert not active_tracks(header + '\n' + row.replace('yes', ' no'), '123')
    return 'PASS: app crash/log boundary; GL no-progress proof and healthy negative; bounded onboarding eligibility; app audio-track controls.\n'


def image_distance(first, second):
    def samples(png):
        width, height, channels, rows = pdf_smoke.pixels(png)
        return [rows[int(y * (height - 1) / 17)][int(x * (width - 1) / 31) * channels + c]
                for y in range(18) for x in range(32) for c in range(3)]
    return sum(abs(a - b) for a, b in zip(samples(first), samples(second))) / (32 * 18 * 3 * 255)


def video_visible(png):
    width, height, channels, rows = pdf_smoke.pixels(png)
    count = 0
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            r, g, b = rows[y][x * channels:x * channels + 3]
            count += r < 30 and ((g > 220 and b < 30) or (b > 220 and g < 30))
    return count > width * height / 400


def cycle(h, name, count, allow_crash=False):
    physical = re.search(r'Physical size: (\d+)x(\d+)', h.shell('wm', 'size'))
    assert physical, 'Physical display dimensions unavailable'
    reduced = 'x'.join(str(int(int(n) * .9)) for n in physical.groups())
    session_pid = h.shell('pidof', h.app).strip()
    assert session_pid.isdigit()
    rows = []
    try:
        h.screenshot(name + '-system-before')
        for index in range(count):
            for size in (reduced, 'reset'):
                pid = h.shell('pidof', h.app).strip()
                assert pid == session_pid or allow_crash, 'PID changed between resize actions'
                before = h.log()
                reloads = before.count('Window size has changed from ')
                setups = before.count('Setting up AudioManager...')
                # Bound this action without clearing device logs. Logcat's
                # buffer-clear control can fail independently of log reads.
                marker = f'{name}-{index + 1}-{size}-{time.monotonic_ns()}'
                h.shell('log', '-p', 'i', '-t', 'ESDEPlusAudio', marker)
                def boundary_logs():
                    return h.adb('logcat', '-d', '-b', 'main', '-v', 'threadtime',
                                 'ESDEPlusAudio:I', '*:S')
                h.wait_for(lambda: marker in boundary_logs(), 'audio action log boundary')
                since = marker_time(boundary_logs(), marker)
                def action_logs():
                    # Ask logd for the same interval we validate, rather than
                    # repeatedly transferring the entire retained history.
                    return after_marker(h.adb('logcat', '-d', '-b', 'main,system,crash',
                                              '-v', 'threadtime', '-T', since), marker)
                action_logs()  # Verify the boundary before the product action.
                h.shell('wm', 'size', size)
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    current_pid = h.shell('pidof', h.app, check=False).strip()
                    logs = action_logs()
                    fatal = fatal_lines(logs, pid, h.app)
                    if fatal or current_pid != pid:
                        # A lifecycle stall without a native fatal is never a control hit.
                        assert allow_crash and fatal, (name, index, size, current_pid, fatal, logs)
                        row = dict(cycle=index + 1, size=size, pid=pid, crash=True, fatal=fatal)
                        break
                    current = h.log()
                    new_reloads = current.count('Window size has changed from ') - reloads
                    new_setups = current.count('Setting up AudioManager...') - setups
                    # Wait for actual reload and audio reinit, then let theme/resource
                    # reload finish before the next size event. No synthetic input sound.
                    if new_reloads > 0 and new_setups == new_reloads:
                        time.sleep(2)
                        assert h.shell('pidof', h.app).strip() == pid
                        assert not fatal_lines(action_logs(), pid, h.app)
                        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app)
                        current = h.log()
                        assert current.count('Setting up AudioManager...') - setups == current.count(
                            'Window size has changed from ') - reloads
                        output = audio_output(h, f'{name}-{index + 1}-{size}', pid)
                        assert h.shell('pidof', h.app).strip() == session_pid or allow_crash
                        assert not fatal_lines(action_logs(), pid, h.app)
                        row = dict(cycle=index + 1, size=size, pid=pid, crash=False,
                                   reloads=new_reloads, audio_setups=new_setups, audio_output=output)
                        break
                    time.sleep(.25)
                else:
                    rows.append(dict(cycle=index + 1, size=size, pid=pid, stall=True,
                                     log_marker=marker, log_since=since))
                    classify_stall(h, name, pid, action_logs, reloads, setups,
                                   'x'.join(physical.groups()) if size == 'reset' else size)
                    raise AssertionError(f'{name}: reload failed to complete: cycle={index + 1}, size={size}')
                row['log_marker'] = marker
                row['log_since'] = since
                rows.append(row)
                (h.evidence / (name + '-cycles.txt')).write_text(json.dumps(rows, indent=2) + '\n')
                prefix = f'{name}-{index + 1}-{size}'
                (h.evidence / (prefix + '-es_log.txt')).write_text(h.log())
                (h.evidence / (prefix + '-logcat.txt')).write_text(action_logs())
                if row['crash']:
                    # Positive controls intentionally restart after each observed fatal;
                    # fixed and negative-control sessions may never change PID.
                    h.shell('am', 'force-stop', h.app)
                    h.launch()
                    nodes = h.hierarchy()
                    crash_dialog = any(n.get('resource-id') == 'android:id/alertTitle' and
                                       h.label in n.get('text', '') and
                                       'keeps stopping' in n.get('text', '') for n in nodes)
                    if crash_dialog:
                        # Android can retain the preceding intentional crash's
                        # dialog over the new process. Close only this exact app
                        # dialog, then start a fresh positive-control session.
                        assert any(n.get('resource-id') == 'android:id/aerr_close' and
                                   n.get('text') == 'Close app' for n in nodes)
                        h.screenshot(f'{name}-{index + 1}-{size}-recorded-crash-dialog')
                        h.ui('Close app')
                        h.shell('am', 'force-stop', h.app)
                        h.launch()
        if not allow_crash:
            assert h.shell('pidof', h.app).strip() == session_pid
        # A slow default-settings stress run can reach the idle screensaver.
        # Shift is unmapped in the default keyboard config: it only wakes the
        # window and cannot navigate a wrong view back to the expected one.
        h.key('KEYCODE_SHIFT_LEFT')
        h.screenshot(name + '-system-restored')
        # Prove the real system view was restored: Enter exposes the NES game
        # list, and Back returns to system selection, without launching a game.
        h.key('KEYCODE_ENTER')
        h.screenshot(name + '-gamelist-after')
        h.key('KEYCODE_DEL')
        h.screenshot(name + '-system-after-back')
        restored = (h.evidence / (name + '-system-restored.png')).read_bytes()
        gamelist = (h.evidence / (name + '-gamelist-after.png')).read_bytes()
        returned = (h.evidence / (name + '-system-after-back.png')).read_bytes()
        changed = image_distance(restored, gamelist)
        if changed <= .01 or image_distance(restored, returned) >= changed / 2:
            raise AssertionError('Enter/Back did not restore the expected system/gamelist views')
        (h.evidence / (name + '-view-oracle.txt')).write_text(
            f'Enter image distance={changed}; Back distance={image_distance(restored, returned)}\n')
        return sum(row['crash'] for row in rows)
    finally:
        h.shell('wm', 'size', 'reset')
        (h.evidence / (name + '-cycles.txt')).write_text(json.dumps(rows, indent=2) + '\n')
        h.save_logs(name + '-final')


def run_control(harness):
    h = type('Harness', (), harness)
    assert h.device_api == 29 or h.television
    original = h.shell('cat', h.settings)
    document = h.launch_checks.settings_fragment(original)
    navigation = document.find("bool[@name='NavigationSounds']")
    assert navigation is None or navigation.get('value') == 'true', 'Control requires default sounds'
    batches = []
    # Race-dependent evidence only. A zero-hit or stalled positive sample must
    # never prevent the independent sounds-disabled comparison from running.
    try:
        for attempt in range(1, 4):
            if attempt > 1:
                h.shell('am', 'force-stop', h.app)
                h.launch()
            name = 'audio-unfixed-default' + (f'-batch{attempt}' if attempt > 1 else '')
            crashes = cycle(h, name, 20, allow_crash=True)
            batches.append(dict(batch=attempt, cycles=20, actions=40, crashes=crashes))
            print(f'Unfixed audio control batch {attempt}/3: {crashes}/40 native crashes', flush=True)
            if crashes:
                break
    except Exception as error:
        batches.append(dict(outcome=type(error).__name__, detail=str(error)))
        h.save_logs('audio-unfixed-default-stalled-or-failed')
    finally:
        (h.evidence / 'audio-positive-batches.txt').write_text(json.dumps(batches, indent=2) + '\n')
        comparison = {}
        try:
            set_setting(document, 'bool', 'NavigationSounds', 'false')
            h.user_file('settings/es_settings.xml', xml_settings(document))
            h.launch(audio_relaunch='audio-control-comparison-startup')
            comparison = dict(crashes=cycle(h, 'audio-unfixed-sounds-disabled', 20), actions=40)
        except Exception as error:
            comparison = dict(outcome=type(error).__name__, detail=str(error))
            h.save_logs('audio-unfixed-sounds-disabled-stalled-or-failed')
        finally:
            (h.evidence / 'audio-control-summary.txt').write_text(json.dumps(
                dict(source=CONTROL_BASE, non_gating=True, positive=batches,
                     navigation_sounds_false=comparison), indent=2) + '\n')
    raise ControlComplete()


def video_fixture(path):
    # Original 64x64 RGB animation + 440 Hz stereo PCM in an AVI container.
    # stdlib only; no downloaded media, codec binary or test dependency.
    def chunk(kind, data):
        return kind + struct.pack('<I', len(data)) + data + b'\0' * (len(data) % 2)

    def listing(kind, data):
        return chunk(b'LIST', kind + data)

    frames = 50
    header = struct.pack('<14I', 100000, 400000, 0, 0x100, frames, 0, 2, 0, 64, 64, 0, 0, 0, 0)
    def stream(kind, handler, scale, rate, length, sample_size):
        return struct.pack('<4s4sIHH8I4h', kind, handler, 0, 0, 0, 0, scale, rate, 0,
                           length, 0, 0xffffffff, sample_size, 0, 0, 64 if kind == b'vids' else 0,
                           64 if kind == b'vids' else 0)
    video = listing(b'strl', chunk(b'strh', stream(b'vids', b'DIB ', 1, 10, frames, 0)) +
                    chunk(b'strf', struct.pack('<IiiHHIIiiII', 40, 64, 64, 1, 24, 0, 64*64*3, 0, 0, 0, 0)))
    # WAVEFORMATEXTENSIBLE declares the stereo channel mask explicitly. A plain
    # PCM header leaves FFmpeg's channel layout unspecified on some versions.
    pcm_format = struct.pack('<HHIIHHHHI', 0xfffe, 2, 44100, 44100*4, 4, 16, 22, 16, 3)
    pcm_format += bytes.fromhex('0100000000001000800000aa00389b71')
    audio = listing(b'strl', chunk(b'strh', stream(b'auds', b'\0'*4, 4, 44100*4, frames*4410, 4)) +
                    chunk(b'strf', pcm_format))
    movie = b''
    for frame in range(frames):
        colour = b'\0\xff\0' if frame % 10 < 5 else b'\xff\0\0'
        movie += chunk(b'00db', colour * (64*64))
        pcm = b''.join(struct.pack('<hh', value, value) for value in
                       (int(8000 * math.sin(i * 2 * math.pi * 440 / 44100))
                        for i in range(frame*4410, (frame+1)*4410)))
        movie += chunk(b'01wb', pcm)
    content = listing(b'hdrl', chunk(b'avih', header) + video + audio) + listing(b'movi', movie)
    path.write_bytes(b'RIFF' + struct.pack('<I', len(content) + 4) + b'AVI ' + content)


def fixed_session(h, name, count):
    completed = True
    try:
        assert cycle(h, name, count) == 0
        outcome = f'PASS: {count} size/reset cycles; same PID; matching reload/audio setup; active app audio output.'
    except GLTransportInfrastructure as error:
        completed = False
        outcome = str(error) + '; session stopped, no completed-stress claim.'
        # Retire this captured infrastructure session before the independent
        # checks. Do not retry it, count it as passing stress, or recover a
        # lifecycle stall / any unclassified product failure.
        h.shell('am', 'force-stop', h.app)
        h.launch(audio_relaunch=name + '-independent-startup')
    (h.evidence / (name + '-result.txt')).write_text(outcome + '\n')
    return completed


def run(harness):
    h = type('Harness', (), harness)
    (h.evidence / 'audio-assertion-controls.txt').write_text(controls())
    if h.device_api != 29 and not h.television:
        return
    fixed_session(h, 'audio-fixed-default', 20)
    original = h.shell('cat', h.settings)
    document = h.launch_checks.settings_fragment(original)
    media = '/sdcard/ESDEPlusAudioMedia'
    fixture = h.evidence / 'audio-video.avi'
    video_fixture(fixture)
    h.shell('mkdir', '-p', media + '/nes/videos')
    h.adb('push', str(fixture), media + '/nes/videos/Smoke Alpha.avi')
    set_setting(document, 'string', 'MediaDirectory', media)
    set_setting(document, 'bool', 'ViewsVideoAudio', 'true')
    set_setting(document, 'string', 'ThemeVariant', 'textlistWithVideos')
    try:
        h.user_file('settings/es_settings.xml', xml_settings(document))
        h.launch(audio_relaunch='audio-video-startup')
        h.key('KEYCODE_ENTER')
        h.wait_for(lambda: video_visible(h.adb('exec-out', 'screencap', '-p', binary=True)),
                   'original audio-track video visibly plays before reload')
        h.screenshot('audio-video-before-reload')
        h.save_logs('audio-video-before-reload')
        reloaded = fixed_session(h, 'audio-fixed-video', 1)
        phase = 'after-reload' if reloaded else 'independent-session-after-infrastructure'
        h.key('KEYCODE_ENTER')
        h.wait_for(lambda: video_visible(h.adb('exec-out', 'screencap', '-p', binary=True)),
                   'original audio-track video visibly plays: ' + phase)
        h.screenshot('audio-video-' + phase)
        h.save_logs('audio-video-' + phase)
        audio_output(h, 'audio-video-playing-' + phase, h.shell('pidof', h.app).strip())
        (h.evidence / 'audio-fixed-summary.txt').write_text(
            'See per-session results: completed stress sessions or stack-qualified GL infrastructure.\n'
            'Every completed reload has matching audio setup and active app AudioFlinger track '
            f'with advancing server frames; original audio-track video visibly plays: {phase}.\n'
            'Real nonzero navigation and video PCM mixing is asserted separately on Linux.\n')
    finally:
        h.user_file('settings/es_settings.xml', original)
        h.start_entry('HomeEntry', 'android.intent.category.HOME')
        h.configured_system('audio-restored-home')


if __name__ == '__main__':
    {'build-control': build_control, 'control': control_launch,
     'controls': controls}[sys.argv[1]]()
