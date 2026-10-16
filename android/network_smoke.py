#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real frontend HTTPS smoke and permission control.
import contextlib
import json
import pathlib
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile


@contextlib.contextmanager
def wall_budget(seconds, description, reserve=False):
    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def expired(*_):
        raise AssertionError('Total time bound exceeded: ' + description)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, timer[0]) if timer[0] and not reserve else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, timer[0] - (time.monotonic() - started)), timer[1])


def mainloop_input(before, after):
    assert after.startswith(before), 'Frontend log reset during main-loop proof'
    assert re.search(r'Window::logInput\(Keyboard\): Key F12, .*value=1\b', after[len(before):]), \
        'Frontend main loop did not acknowledge the harmless F12 key'


def root_destinations(api, removable_roots):
    # Shared names use legal special characters. Actual quoted/backslash Git
    # paths are exercised on private storage by the native debug controls.
    result = [('/sdcard/ESDEPlus trust # ; café', 'escaping')] if api == 34 else []
    if removable_roots:
        result.append((removable_roots[0] + '/ESDEPlus removable café', 'removable'))
    return result


def process_stacks(text, pid, app):
    blocks = re.findall(r'^----- pid ' + re.escape(pid) + r' at [^\n]*\n.*?^----- end ' +
                        re.escape(pid) + r' -----', text, re.M | re.S)
    return '\n'.join(block for block in blocks if re.search(r'^Cmd line: ' + re.escape(app) + r'$', block, re.M))


class RemoteFailure(Exception):
    def __init__(self, message):
        assert remote_error(message), 'Failure is not eligible for remote handling: ' + message
        super().__init__(message)


class RemoteStall(RemoteFailure):
    def __init__(self, description, timeout):
        # Constructed only by the deadline path after the final health check.
        Exception.__init__(self, f'{description}: healthy frontend, remote deadline {timeout}s expired')


def wait_request(read, healthy, success, failure, description, timeout, *, started, responsive,
                 clock=time.monotonic, pause=time.sleep):
    deadline = clock() + timeout
    while True:
        output = read()
        healthy()  # Includes the completing poll and the deadline poll.
        if success(output) or failure(output):
            return output
        assert 'Error:' not in output and 'No themes.json file found' not in output, output
        # Never turn a TLS/permission diagnostic into a stall just because the
        # expected completion line is absent.
        assert not any(value in output.lower() for value in
                       ['permission denied', 'not permitted', 'ssl', 'tls', 'certificate']), output
        if clock() >= deadline:
            assert started(output), 'Remote request never provably started: ' + description
            responsive()  # A live/focused process alone cannot prove SDL is responsive.
            raise RemoteStall(description, timeout)
        pause(min(2, max(0, deadline - clock())))


def remote_attempts(action, recover, record, name, pause=time.sleep):
    for attempt in range(1, 4):
        try:
            return action()
        except RemoteFailure as error:
            record(f'REMOTE {name} attempt {attempt}/3 failed: {error}')
            if attempt == 3:
                raise
            recover(error)
            pause(5)


def remote_outcome(api, error, record):
    record(f'{"FAIL" if api == 34 else "NON-GATING REMOTE DIAGNOSTIC"}: API {api}: {error}')
    if api == 34:
        raise error


def frontend_process(pid, current, logcat):
    assert pid and current == pid, 'Frontend process died or restarted'
    # An SDL destroy join can stall while its process/window still look alive.
    # Match this process's threadtime PID, excluding earlier fixture processes.
    assert not re.search(r'^\S+\s+\S+\s+' + re.escape(pid) +
                         r'\s+\d+\s+\w\s+ES-DE-Plus\s*:\s*Destroying SDL activity\b',
                         logcat, re.M), 'Frontend entered SDL destruction during network wait'


def resolve_error(output):
    return any(value in output.lower() for value in
               ['could not resolve host', "couldn't resolve host", 'failed to resolve address'])


def remote_error(output):
    # A missing INTERNET grant can also produce a plain resolve diagnostic.
    # The per-attempt grant assertion, not this text classifier, excludes it.
    # TLS, explicit permission errors and frontend failures never qualify.
    lowered = output.lower()
    if any(value in lowered for value in ['permission denied', 'not permitted', 'ssl', 'tls', 'certificate']):
        return False
    return resolve_error(output) or any(value in lowered for value in
        ['failed to connect', "couldn't connect", 'connection timed out', 'timeout was reached',
         'connection reset', 'unexpected eof', 'early eof']) or bool(re.search(
             r'(?:http error code|unexpected http status code:?|status code:) (?:429|50[0234])\b', lowered))


def scraper_reply(output):
    # These diagnostics are emitted only after curl received an HTTPS response.
    # DNS/connect/TLS failures and mere search-start logging cannot satisfy this gate.
    return any(value in output for value in [
        'GuiScraperSearch::onSearchDone(): Scraper service did not return any results',
        'ScreenScraperRequest::processGame(): Name:',
        'ScreenScraperRequest - Error parsing XML:',
        'Server returned HTTP error code ',
    ])


def controls():
    assert resolve_error("Couldn't resolve host name")
    assert resolve_error("failed to resolve address for gitlab.com: Permission denied")
    for value in ['Permission denied', 'TLS certificate verification failed',
                  'Frontend ANR', 'Timed out: frontend startup', 'No themes.json file found',
                  'failed to resolve address: Permission denied', 'unexpected HTTP status code: 404']:
        assert not remote_error(value), value
        try:
            RemoteFailure(value)
        except AssertionError:
            pass
        else:
            raise AssertionError('Non-remote failure entered retry/diagnostic handling: ' + value)
    for value in ['failed to resolve address for gitlab.com', 'Failed to connect to server',
                  'unexpected HTTP status code: 503', 'Server returned HTTP error code 429']:
        assert remote_error(value), value
    assert scraper_reply('ScreenScraperRequest::processGame(): Name: Example')
    assert scraper_reply('GuiScraperSearch: Network error: Server returned HTTP error code 403')
    for value in ['Scraper::startScraperSearch(): Scraping system "nes"',
                  'ScraperHttpRequest network error - Could not resolve hostname',
                  'SSL peer certificate cannot be authenticated']:
        assert not scraper_reply(value), value
    reports = []
    destinations = root_destinations(34, ['/storage/0000-0000'])
    assert len(destinations) == 2
    assert destinations[0][1] == 'escaping' and destinations[0][0].startswith('/sdcard/')
    assert all(character in destinations[0][0] for character in ['#', ';', ' ', 'é'])
    assert '"' not in destinations[0][0]
    assert destinations[1][1] == 'removable'
    assert not any(character in pathlib.PurePosixPath(destinations[1][0]).name
                   for character in '<>:"/\\|?*')
    assert root_destinations(31, []) == [] and root_destinations(36, []) == []
    assert len(root_destinations(34, [])) == 1
    assert all(root_destinations(api, ['/storage/card'])[0][1] == 'removable' for api in (31, 36))
    reports.append('PASS: API34 legal special-character fixture remains on emulated storage even with a card; '
                   'removable clone/load fixture uses a portable filename; absence is explicit.')
    for api in (31, 34, 36):
        ticks = [0]
        attempts = []
        recoveries = []
        def pause(seconds):
            ticks[0] += seconds
        def stalled():
            attempts.append(ticks[0])
            return wait_request(lambda: 'request started', lambda: None, lambda _: False, lambda _: False,
                                'fixture stalled remote', 10, started=lambda s: s == 'request started',
                                responsive=lambda: None,
                                clock=lambda: ticks[0], pause=pause)
        try:
            remote_attempts(stalled, lambda error: recoveries.append(str(error)), reports.append,
                            'fixture', pause=pause)
        except RemoteStall as error:
            assert attempts == [0, 15, 30] and ticks[0] == 40 and len(recoveries) == 2
            try:
                remote_outcome(api, error, reports.append)
            except RemoteStall:
                assert api == 34
            else:
                assert api != 34
        else:
            raise AssertionError('Stalled-remote control escaped')
    for problem in ['Frontend process died', 'Frontend ANR', 'Frontend lost focus', 'Frontend SDL destruction',
                    'INTERNET permission differs', 'TLS certificate verification failed']:
        attempts = []
        ticks = [0]
        def unhealthy():
            if ticks[0] >= 2:
                raise AssertionError(problem)
        def failed_frontend():
            attempts.append(1)
            return wait_request(lambda: '', unhealthy, bool, bool, 'fixture', 10,
                                started=lambda _: True, responsive=lambda: None,
                                clock=lambda: ticks[0], pause=lambda seconds: ticks.__setitem__(0, ticks[0] + seconds))
        try:
            remote_attempts(failed_frontend, lambda error: reports.append('BAD RECOVERY'),
                            reports.append, 'fixture')
        except AssertionError as error:
            assert str(error) == problem and len(attempts) == 1
        else:
            raise AssertionError('Frontend/permission/TLS control escaped')
    reports.append('PASS: three bounded stalled-remote attempts (40 virtual seconds including backoff); '
                   'API 29/TV diagnostic, API 34 hard failure; frontend death/ANR/focus, permission and TLS never retried.')
    reports.append('PASS: a bare no-INTERNET resolve error is textually remote; the per-attempt grant check prevents masking. '
                   'Negative permission probes bypass retries and must receive their one resolve error.')
    reports.append('PASS: only an HTTPS service reply satisfies scraper reachability.')
    destruction = '10-14 12:34:56.789  1234  1250 I ES-DE-Plus: Destroying SDL activity held=false'
    frontend_process('5678', '5678', destruction)
    try:
        frontend_process('1234', '1234', destruction)
    except AssertionError as error:
        assert 'SDL destruction' in str(error)
    else:
        raise AssertionError('Live/focused destruction control escaped')
    reports.append('PASS: current-PID SDL destruction is hard even before ANR; earlier-PID logs cannot fail a healthy request.')
    for diagnostic in ['Error: frontend failed to parse theme list', 'No themes.json file found',
                       'SSL certificate verification failed', 'Permission denied']:
        attempts = []
        def invalid_request():
            attempts.append(1)
            return wait_request(lambda: diagnostic, lambda: None, lambda _: False, lambda _: False,
                                'fixture invalid completion', 10, started=lambda _: True, responsive=lambda: None)
        try:
            remote_attempts(invalid_request, lambda error: reports.append('BAD RECOVERY'),
                            reports.append, 'fixture')
        except AssertionError:
            assert attempts == [1]
        else:
            raise AssertionError('Incomplete frontend/TLS/permission error became a remote stall')
    reports.append('PASS: incomplete frontend/error, TLS and permission diagnostics stay hard before deadline classification.')
    for did_start, loop_alive in [(False, True), (True, False)]:
        attempts = []
        ticks = [0]
        def responsive():
            mainloop_input('', 'Window::logInput(Keyboard): Key F12, isMappedTo=, value=1' if loop_alive else '')
        def unproven():
            attempts.append(1)
            return wait_request(lambda: '', lambda: None, bool, bool, 'unproven fixture', 2,
                                started=lambda _: did_start, responsive=responsive,
                                clock=lambda: ticks[0], pause=lambda n: ticks.__setitem__(0, ticks[0] + n))
        try:
            remote_attempts(unproven, lambda _: reports.append('BAD RECOVERY'), reports.append, 'unproven')
        except AssertionError:
            assert attempts == [1]
        else:
            raise AssertionError('Unproven start or frozen main loop became a remote stall')
    stale = 'Window::logInput(Keyboard): Key F12, isMappedTo=, value=1'
    try:
        mainloop_input(stale, stale)
    except AssertionError:
        pass
    else:
        raise AssertionError('Earlier F12 log satisfied main-loop proof')
    trace = ('----- pid 1234 at 2026-10-15 04:00:00 -----\nCmd line: example.app\n'
             '"SDLThread" native\n  native: #00 pc 0001 libmain.so\n----- end 1234 -----')
    assert process_stacks(trace, '1234', 'example.app') == trace
    assert not process_stacks(trace, '5678', 'example.app')
    assert not process_stacks(trace, '1234', 'other.app')
    assert not process_stacks('native: #00 pc 0001 libmain.so', '1234', 'example.app')
    with wall_budget(1, 'timer control'):
        pass
    try:
        with wall_budget(0.01, 'blocked timer control'):
            time.sleep(1)
    except AssertionError as error:
        assert 'Total time bound' in str(error)
    else:
        raise AssertionError('Wall-time control escaped')
    reports.append('PASS: missing request-start proof, frozen main loop and stale key logs stay hard; trace extraction rejects other PID/app data; wall-time budget interrupts blocked work.')
    return '\n'.join(reports) + '\n'


def run(harness, scoped=False):
    try:
        with wall_budget(90 * 60, 'network checks (90 minutes)'):
            run_checks(harness, scoped)
    except Exception:
        harness['evidence'].joinpath('network-exception.txt').write_text(traceback.format_exc())
        raise


def run_checks(harness, scoped=False):
    import theme_trust_smoke
    h = type('Harness', (), harness)
    h.evidence.joinpath('network-assertion-positive-controls.txt').write_text(controls())
    subprocess.run([sys.executable, 'android/network-control.py', '--self-test'], check=True)
    original = h.shell('cat', h.settings)
    document = h.launch_checks.settings_fragment(original)
    # Ordinary upstream user settings, written through the existing SDK-context
    # fixture driver. No request interception, injected reply or native test hook.
    values = [('bool', 'DebugMode', 'true'), ('string', 'Scraper', 'screenscraper'),
              ('bool', 'ScraperUseAccountScreenScraper', 'false'),
              ('bool', 'ScraperInteractive', 'true'), ('bool', 'ScraperSemiautomatic', 'false'),
              ('int', 'ScraperRetryOnErrorCount', '0'), ('int', 'ScraperConnectionTimeout', '30'),
              ('int', 'ScraperTransferTimeout', '60')]
    values.append(('bool', 'DebugSkipInputLogging', 'false'))
    for kind, name, value in values:
        node = document.find(f"{kind}[@name='{name}']")
        if node is None:
            node = ET.SubElement(document, kind, name=name)
        node.set('value', value)
    configured = '<?xml version="1.0"?>\n' + ''.join(ET.tostring(n, encoding='unicode') for n in document)
    h.user_file('settings/es_settings.xml', configured)
    volumes = h.shell('am', 'instrument', '-w', '-e', 'mode', 'theme-volumes',
                      h.app + '/org.esdeplus.frontend.RuntimeSmoke')
    h.smoke_checks.probe_passed(volumes, 'PASS: app-context storage volumes')
    removable_roots = [line.split('directory=', 1)[1].strip() for line in volumes.splitlines()
                       if 'removable=true' in line and 'state=mounted ' in line and 'directory=/' in line]
    h.evidence.joinpath('theme-storage-volumes.txt').write_text(
        'mode=' + ('scoped' if scoped else 'direct') + '\n' + volumes +
        ('\nNo writable mounted removable volume reported by the SDK; raw states are recorded above.\n' if not removable_roots else '\nRemovable volume will run the clone/load path.\n'))
    control = pathlib.Path('android/.deps/network/no-internet.apk')
    attempts = {}
    active = ['network-setup']
    trust_controls_complete = False
    owner_leftover = False

    def begin(operation):
        attempts[operation] = attempts.get(operation, 0) + 1
        active[0] = f'network-{operation}-attempt{attempts[operation]}'

    def record(message):
        message += ' [mode=' + ('scoped' if scoped else 'direct') + ']'
        print(message, flush=True)
        with h.evidence.joinpath('network-result.txt').open('a') as output:
            output.write(message + '\n')

    def permission(expected):
        dump = h.shell('dumpsys', 'package', h.app)
        granted = bool(re.search(r'android.permission.INTERNET: granted=true\b', dump))
        assert granted == expected, 'Installed INTERNET permission differs from probe: ' + dump
        h.evidence.joinpath(active[0] + '-package.txt').write_text(dump)

    def theme_path(relative):
        # The upstream getter is named getInternalAppDataDirectory, but the
        # accepted bridge maps it to the configured application-data directory.
        # Use fresh frontend evidence, not the internal bundled-resource path.
        matches = re.findall(r'Android external directory: (.+)', h.log())
        assert len(matches) == 1 and matches[0].startswith('/'), matches
        return matches[0] + '/themes/' + relative

    def delta(before):
        output = h.log()
        assert output.startswith(before), 'Frontend log reset during a network operation'
        return output[len(before):]

    def menu(index):
        h.key('KEYCODE_ESCAPE')
        for _ in range(index):
            h.key('KEYCODE_DPAD_DOWN')
        h.key('KEYCODE_ENTER')

    def downloader():
        menu(2)  # SEARCH, SCRAPER, UI SETTINGS; first row is THEME DOWNLOADER.
        h.key('KEYCODE_ENTER')

    def clone_target_started(repository):
        target = shlex.quote(theme_path(repository + '/.git'))
        observed = h.shell('sh', '-c', 'test -d ' + target + ' && echo started', check=False).strip() == 'started'
        h.evidence.joinpath(active[0] + '-clone-start.txt').write_text(
            f'Initially absent destination; new clone target {target}: observed={observed}\n')
        return observed

    def capture(name):
        stem = active[0] + '-' + name.removeprefix('network-')
        h.screenshot(stem)
        h.save_logs(stem)
        return stem

    def live_state(name, required=False):
        stem = capture(name)
        pid = h.shell('pidof', h.app, check=False).strip()
        h.evidence.joinpath(stem + '-window.txt').write_text(h.shell('dumpsys', 'window', 'displays', check=False))
        if not re.fullmatch(r'\d+', pid):
            h.evidence.joinpath(stem + '-process.txt').write_text('Frontend PID absent: ' + pid)
            assert not required, 'Frontend died before live diagnostics'
            return ''
        # The debug APK owns its SIGQUIT request and fd snapshot. The shell
        # reads the shared network tables (apps cannot read /proc/net on API 29+).
        # Prefer the fast native dump where supported; bugreport retrieves
        # ART's all-thread traces on production images too;
        # only this PID/app's trace text is retained, never the raw archive.
        sockets = h.shell('run-as', h.app, 'sh', '-c',
            f'exec 2>&1; cat /proc/{pid}/status; echo "FD LINKS"; ls -l /proc/{pid}/fd', check=False)
        sockets += h.shell('sh', '-c', 'exec 2>&1; for table in tcp tcp6 udp udp6; '
                           'do echo "TABLE $table"; cat /proc/net/$table; done', check=False)
        h.evidence.joinpath(stem + '-sockets.txt').write_text(sockets)
        stack_file = h.evidence.joinpath(stem + '-stacks.txt')
        stack_file.write_text(f'Collecting frontend thread stacks for PID {pid}\n')
        stacks = ''
        root = h.adb('root', check=False)
        if 'cannot run as root' not in root:
            try:
                h.adb('wait-for-device')
                h.wait_for(lambda: h.shell('id', '-u', check=False).strip() == '0',
                           'native diagnostic shell', timeout=10)
                stacks = h.shell('sh', '-c', f'debuggerd -b {pid} 2>&1', check=False)
            finally:
                h.adb('unroot', check=False)
                h.adb('wait-for-device')
                h.wait_for(lambda: h.shell('id', '-u', check=False).strip() == '2000',
                           'ordinary shell after frontend diagnostics', timeout=10)
        # Production images reject root. Required stall/control snapshots use
        # the app-owned dump below. Cleanup retains live logs/fds without
        # starting a second whole-device report after an earlier failure.
        if not re.search(r'#00\s+pc\s', stacks) and required:
            before_dump = h.adb('logcat', '-d', '--pid=' + pid)
            h.shell('run-as', h.app, 'kill', '-3', pid)
            def dump_finished():
                output = h.adb('logcat', '-d', '--pid=' + pid)
                assert output.startswith(before_dump), 'App diagnostic log reset during SIGQUIT'
                return 'Wrote stack traces to tombstoned' in output[len(before_dump):]
            h.wait_for(dump_finished, 'fresh app-owned thread dump completed', timeout=20)
            h.evidence.joinpath(stem + '-dump-logcat.txt').write_text(h.adb('logcat', '-d', '--pid=' + pid))
            parent = pathlib.Path('android/.deps/network')
            parent.mkdir(parents=True, exist_ok=True)
            stacks = ''
            with tempfile.TemporaryDirectory(prefix='traces-', dir=parent) as temporary:
                report = pathlib.Path(temporary) / 'report.zip'
                h.adb('bugreport', str(report))
                with zipfile.ZipFile(report) as archive:
                    for entry in archive.namelist():
                        if entry.startswith('FS/data/anr/') or (entry.startswith('bugreport-') and entry.endswith('.txt')):
                            stacks += process_stacks(archive.read(entry).decode(errors='replace'), pid, h.app)
        stack_file.write_text(stacks or 'No native trace captured; live process/window/socket evidence retained\n')
        if required:
            assert re.search(r'#00\s+pc\s', stacks), 'No frontend thread backtrace captured'
            assert 'Uid:' in sockets and 'FD LINKS' in sockets and 'local_address' in sockets and \
                'Permission denied' not in sockets, 'No app socket snapshot captured'

        return stacks

    def responsive(pid):
        before = h.log()
        h.key('KEYCODE_F12')  # Unmapped upstream: logs SDL input without changing the GUI.
        h.wait_for(lambda: bool(re.search(r'Window::logInput\(Keyboard\): Key F12, .*value=1\b', delta(before))),
                   'frontend main-loop F12 acknowledgement', timeout=10)
        mainloop_input(before, h.log())
        healthy(pid)
        h.evidence.joinpath(active[0] + '-mainloop.txt').write_text(f'PID {pid}; fresh F12 acknowledgement:\n' + delta(before))

    def healthy(pid):
        assert pid, 'Frontend process died'
        h.dismiss_stock_onboarding()
        h.hierarchy()  # The shared handler raises on a frontend ANR.
        logcat = h.adb('logcat', '-d', '-v', 'threadtime')
        frontend_process(pid, h.shell('pidof', h.app, check=False).strip(), logcat)
        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), 'Frontend lost focus'
        assert 'ANR in ' + h.app not in logcat, 'Frontend ANR'

    def request_result(before, success, failure, description, timeout, started, negative=False):
        pid = h.shell('pidof', h.app, check=False).strip()
        assert pid, 'Frontend process died'
        print('WAIT: ' + description, flush=True)
        def confirmed_start(output):
            observed = started(output)
            h.evidence.joinpath(active[0] + '-request-start.txt').write_text(
                f'{description}: started={observed}\n' + output)
            return observed
        def deadline_proof():
            assert not negative, 'No-INTERNET control did not produce its resolve error'
            responsive(pid)
            with wall_budget(120, 'stalled-request evidence'):
                live_state('stalled-request', required=True)
            healthy(pid)
        try:
            output = wait_request(lambda: delta(before), lambda: healthy(pid), success, failure,
                                  description, timeout, started=confirmed_start, responsive=deadline_proof)
        except RemoteStall:
            healthy(pid)
            output = delta(before)
            if success(output) or failure(output):
                return output  # Completion during evidence capture wins over the deadline.
            assert 'Error:' not in output and 'No themes.json file found' not in output, output
            assert not any(value in output.lower() for value in
                           ['permission denied', 'not permitted', 'ssl', 'tls', 'certificate']), output
            # A no-INTERNET control must produce its resolve error, never a
            # diagnostic exemption or retry on an otherwise healthy deadline.
            assert not negative, 'No-INTERNET control did not produce its resolve error'
            raise
        time.sleep(1)  # Let the GUI dismiss its busy overlay.
        healthy(pid)
        return output

    def restart_remote(error, relative=None):
        # Upstream ignores all downloader input while fetching. Only a proven
        # healthy remote stall may be cancelled this way, never a frontend failure.
        # The caller asserted the target absent immediately before the request;
        # remove only that probe-created incomplete clone, preserving the list
        # and every successful download. No product state or permission is reset.
        pid = h.shell('pidof', h.app, check=False).strip()
        healthy(pid)
        with wall_budget(120, 'live state before remote cancellation'):
            live_state('before-remote-restart')
        healthy(pid)
        h.shell('am', 'force-stop', h.app)
        if isinstance(error, RemoteStall) and relative:
            h.shell('rm', '-rf', theme_path(relative))
        h.launch()  # Ordinary startup stays a hard, single-attempt assertion.

    def theme_list(negative):
        nonlocal trust_controls_complete, owner_leftover
        begin(('control' if negative else 'fixed') + '-theme-list')
        permission(not negative)
        recovering = owner_leftover and not negative
        if recovering:
            h.shell('test', '-d', theme_path('themes-list/.git'))
        else:
            h.shell('test', '!', '-e', theme_path('themes-list'))
        before = h.log()
        controls = not scoped and not negative and not trust_controls_complete
        if controls:
            theme_trust_smoke.request(h)
        downloader()
        if controls:
            theme_trust_smoke.collect(h)
            trust_controls_complete = True
        capture('network-' + ('control' if negative else 'fixed') + '-first-use')
        # Debug prerequisites have their own result and may mention arbitrary
        # paths. Classify diagnostics from the actual request, after PROCEED.
        before = h.log()
        h.key('KEYCODE_ENTER')  # Real first-use PROCEED, never bypassed.
        output = request_result(before,
            lambda s: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', s)),
            lambda s: "Couldn't clone repository" in s,
            'frontend themes-list HTTPS clone completed', 300,
            lambda s: 'GuiThemeDownloader: Creating initial themes list repository clone' in s, negative)
        if recovering and 'Renaming directory ' + theme_path('themes-list') in output:
            owner_leftover = False
            assert output.count('Renaming directory ' + theme_path('themes-list')) == 1, output
            h.shell('test', '-d', theme_path('themes-list_CORRUPT_DISABLED/.git'))
            record('PASS: half-initialized list explicitly recovered once; old metadata retained until next visit.')
        capture('network-' + ('control' if negative else 'fixed') + '-theme-list')
        if negative:
            assert '"themes-list"' in output and resolve_error(output), output
            record('PASS: no-INTERNET APK rejects real themes-list clone with resolve error (one attempt).')
            h.key('KEYCODE_ENTER')  # Error OK.
            h.key('KEYCODE_DEL')  # Downloader, UI settings, main menu.
            h.key('KEYCODE_DEL')
            h.key('KEYCODE_DEL')
            return
        if "Couldn't clone repository" in output:
            if remote_error(output):
                h.key('KEYCODE_ENTER')
                h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
                raise RemoteFailure(output)
            raise AssertionError(output)
        raw = h.shell('cat', theme_path('themes-list/themes.json'))
        themes = json.loads(raw)
        names = theme_trust_smoke.allowlist(h)
        entries = sorted([entry for entry in themes['themes'] + themes.get('themesAndroid', [])
                          if entry['reponame'] in names], key=lambda t: t['name'].upper())
        assert entries and h.shell('cat', theme_path('themes-list/.git/HEAD')).strip()
        h.evidence.joinpath(active[0] + '-themes-list-head.txt').write_text(
            h.shell('cat', theme_path('themes-list/.git/HEAD')) +
            h.shell('cat', theme_path('themes-list/.git/config')))
        record(f'PASS: frontend cloned canonical themes-list using bundled CA; rendered {len(entries)} themes.')
        if 'Not running the most current application release' in output:
            h.key('KEYCODE_ENTER')  # Upstream's compatibility warning, captured above.
        return entries

    def owner_positive_control():
        nonlocal owner_leftover
        baseline = pathlib.Path('android/.deps/theme-owner/prefix.apk')
        if scoped or h.api not in (31, 34) or not baseline.is_file():
            return  # TV36 already has the required historical 438bf5927 evidence.
        begin('historical-owner-control')
        # user_file() stopped the frontend after preparing DebugMode. Load it
        # before theme_path() requires the native directory record in its log.
        h.launch()
        h.shell('test', '!', '-e', theme_path('themes-list'))
        h.shell('am', 'force-stop', h.app)
        h.adb('install', '-r', '-d', str(baseline))
        h.launch()
        before = h.log()
        downloader()
        capture('historical-owner-first-use')
        h.key('KEYCODE_ENTER')
        output = request_result(before, lambda text: "Couldn't clone repository" in text,
            lambda text: 'parseThemesList(): Parsed ' in text,
            '438bf5927 ownership rejection positive control', 120,
            lambda text: 'Creating initial themes list repository clone' in text)
        h.evidence.joinpath('theme-owner-control.txt').write_text(output)
        assert 'error code: -36' in output and 'not owned by current user' in output, output
        h.shell('test', '-d', theme_path('themes-list/.git'))
        capture('historical-owner-error')
        record('PASS: exact pre-fix 438bf5927 rejects direct themes-list clone with GIT_EOWNER -36; partial metadata retained.')
        h.shell('am', 'force-stop', h.app)
        h.adb('install', '-r', str(h.apk))
        owner_leftover = True

    def download_theme(entries, extended=True):
        nonlocal owner_leftover
        # Select the same named, fully bundled theme from the real admitted
        # list on every image. Its size also exercises TV's large-clone timing.
        selected = next(entry for entry in entries if entry['reponame'] == 'art-book-next-es-de')
        def select_theme_row():
            h.key('KEYCODE_MOVE_HOME')
            for _ in range(entries.index(selected)):
                h.key('KEYCODE_DPAD_DOWN')
        repository = selected['reponame']
        assert re.fullmatch(r'[A-Za-z0-9._-]+', repository) and not repository.startswith('.'), repository
        assert selected['url'].startswith('https://') and not selected.get('deprecated')
        downloaded = f'Downloaded theme "{repository}"'
        before = ''
        def attempt():
            nonlocal before
            begin('fixed-theme-download')
            permission(True)
            h.shell('test', '!', '-e', theme_path(repository))
            select_theme_row()
            capture('network-theme-selected')
            before = h.log()
            h.key('KEYCODE_ENTER')
            output = request_result(before, lambda s: downloaded in s,
                lambda s: "Couldn't clone repository" in s,
                'frontend theme HTTPS download completed', 300,
                lambda _: clone_target_started(repository))
            capture('network-theme-downloaded')
            if "Couldn't clone repository" in output:
                raise RemoteFailure(output)
            return output
        def recover(error):
            if isinstance(error, RemoteStall):
                restart_remote(error, repository)
                def reopen():
                    begin('fixed-list-reopen')
                    permission(True)
                    before_list = h.log()
                    downloader()  # Upstream automatically fetches the existing list.
                    output = request_result(before_list,
                        lambda s: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', s)),
                        lambda s: "Couldn't fetch" in s or "Couldn't clone" in s,
                        'existing themes-list ready after remote cancellation', 300,
                        # This target already existed: only a worker frame can
                        # prove a fresh fetch when no start log is available.
                        lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('fetch-start-proof', required=True))))
                    if 'parseThemesList(): Parsed ' not in output:
                        raise RemoteFailure(output)
                    if 'Not running the most current application release' in output:
                        h.key('KEYCODE_ENTER')
                # Reopening necessarily issues upstream's refresh. Its remote
                # failure uses the same bound/classification; the saved list is
                # never deleted, and startup itself is never retried.
                remote_attempts(reopen, restart_remote, record, 'themes-list reopen')
            else:
                h.key('KEYCODE_ENTER')  # Completed remote error OK; selection retained.
        clone_began = time.monotonic()
        remote_attempts(attempt, recover, record, 'theme')
        size_kib = int(h.shell('du', '-sk', theme_path(repository)).split()[0])
        if h.television:
            assert size_kib >= 50 * 1024, ('TV large-theme control must exceed 50 MiB', size_kib)
        record(f'PASS: shared-data theme clone seconds={time.monotonic() - clone_began:.3f} KiB={size_kib} path={theme_path(repository)}')
        if extended and h.api in (31, 34, 36):
            # AC-4 exercises a fresh frontend; its admission hook rewinds this
            # run's clone before inventory.
            h.shell('am', 'force-stop', h.app)
            h.launch()
            # The fresh frontend rotates its log. Subsequent inventory/theme
            # assertions must use this process's prefix, retaining delta's reset guard.
            before = h.log()
            theme_trust_smoke.request_rewind(h, repository)
            begin('shared-theme-update-list')
            before_list = h.log()
            downloader()
            request_result(before_list,
                lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
                lambda text: "Couldn't fetch" in text,
                'shared-data list refreshed before real update', 300,
                lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('rewind-list-start', required=True))))
            rewind = theme_trust_smoke.rewind_result(h)
            h.shell('test', '!', '-e', theme_path('themes-list_CORRUPT_DISABLED'))
            if 'Not running the most current application release' in delta(before_list):
                h.key('KEYCODE_ENTER')
            select_theme_row()
            begin('shared-theme-update')
            before_update = h.log()
            update_began = time.monotonic()
            h.key('KEYCODE_ENTER')
            updated = request_result(before_update,
                lambda text: f'Performing fast-forward of repository "{repository}"' in text,
                lambda text: "Couldn't fetch" in text,
                'shared-data theme update', 300,
                lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('update-start', required=True))))
            assert "Couldn't fetch" not in updated, updated
            h.wait_for(lambda: h.shell('cat', theme_path(repository + '/.git/' + rewind['reference'])).strip()
                       == rewind['latest'], 'actual theme fast-forward HEAD reaches original commit', 90)
            h.shell('test', '!', '-e', theme_path(repository + '_DISABLED'))
            assert 'contains local changes' not in delta(before_update), delta(before_update)
            record(f'PASS: shared-data theme update seconds={time.monotonic() - update_began:.3f}; '
                   f'HEAD {rewind["previous"]} -> {rewind["latest"]}; '
                   f'core.filemode={rewind["core.filemode"]}; no spurious local changes or disabled rename')
        if extended and h.api == 34 and not scoped:
            # Model a manual download using only this run's new clone. Preserve
            # its metadata and authored marker in the directory being renamed.
            h.key('KEYCODE_DEL')
            h.shell('mv', theme_path(repository + '/.git'), theme_path(repository + '/prf-git-metadata'))
            marker = 'ES-DE-Plus authored reset positive control'
            h.shell('sh', '-c', 'printf %s ' + shlex.quote(marker) + ' > ' +
                    shlex.quote(theme_path(repository + '/prf-reset-marker.txt')))
            begin('shared-theme-reset-list')
            list_before = h.log()
            h.key('KEYCODE_ENTER')
            listed = request_result(list_before,
                lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
                lambda text: "Couldn't fetch" in text,
                'shared-data reset inventory refresh', 300,
                lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('reset-list-start', required=True))))
            assert "Couldn't fetch" not in listed, listed
            if 'Not running the most current application release' in listed:
                h.key('KEYCODE_ENTER')
            select_theme_row()
            h.key('KEYCODE_ENTER')  # Manual-download confirmation; no filesystem rename by the harness.
            capture('shared-theme-reset-confirmation')
            begin('shared-theme-reset')
            reset_before = h.log()
            reset_began = time.monotonic()
            h.key('KEYCODE_ENTER')  # PROCEED: native downloader renames and clones.
            reset = request_result(reset_before, lambda text: downloaded in text,
                lambda text: "Couldn't clone" in text or 'Cannot rename' in text,
                'shared-data theme reset and clone', 300,
                lambda _: clone_target_started(repository))
            assert downloaded in reset, reset
            assert h.shell('cat', theme_path(repository + '_DISABLED/prf-reset-marker.txt')) == marker
            h.shell('test', '-f', theme_path(repository + '_DISABLED/prf-git-metadata/HEAD'))
            h.shell('test', '-f', theme_path(repository + '/.git/HEAD'))
            record(f'PASS: shared-data theme reset seconds={time.monotonic() - reset_began:.3f}; '
                   f'native _DISABLED rename retains marker and metadata; fresh clone={theme_path(repository)}')
        h.shell('test', '-f', theme_path(repository + '/theme.xml'))
        h.shell('test', '-f', theme_path(repository + '/.git/HEAD'))
        h.key('KEYCODE_DEL')  # Closing downloader repopulates the real theme selector.
        h.wait_for(lambda: re.search(r'Added theme "[^"]+/' + re.escape(repository) + '"', delta(before)),
                   'downloaded theme added to frontend inventory')
        h.key('KEYCODE_DPAD_DOWN')  # Theme selector, below downloader.
        h.key('KEYCODE_DPAD_RIGHT')  # Linear and the one newly downloaded theme.
        capture('network-theme-selectable')
        h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
        h.wait_for(lambda: f'Finished loading theme "{repository}"' in delta(before),
                   'downloaded theme selected and loaded through UI')
        saved = h.shell('cat', h.settings)
        assert h.launch_checks.settings_fragment(saved).find("string[@name='Theme']").get('value') == repository, saved
        for cycle in range(2 if extended else 0):
            begin('same-process-downloader-reopen')
            pid = h.shell('pidof', h.app).strip()
            reopened_before = h.log()
            downloader()
            refreshed = request_result(reopened_before,
                lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
                lambda text: "Couldn't fetch" in text,
                'same-process downloader reopen and real themes-list update', 300,
                lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('reopen-start', required=True))))
            assert 'owner validation=1; config=' in refreshed, refreshed
            assert h.shell('pidof', h.app).strip() == pid, 'Downloader reopen restarted the app'
            if 'Not running the most current application release' in refreshed:
                h.key('KEYCODE_ENTER')
            theme_trust_smoke.allowlist(h)
            if cycle == 0 and h.api == 34 and not scoped:
                h.shell('test', '!', '-e', theme_path(repository + '_DISABLED'))
            h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
            record(f'PASS: downloader reopen cycle={cycle + 1}; same PID={pid}; configuration rebuilt; list fetched')
        faults = [('temporary', 'Injected temporary config creation failure'),
                                  ('replace', 'Cannot atomically replace the private Git config'),
                                  ('search', 'Injected search-path setup failure')]
        for fault, diagnostic in (faults if extended else []):
            begin('recoverable-trust-failure-' + fault)
            paths = [repository + '/theme.xml', repository + '/.git/HEAD', repository + '/.git/config']
            hashes = {path: h.shell('sha256sum', theme_path(path)).split()[0] for path in paths}
            failed_before = h.log()
            theme_trust_smoke.request_failure(h, fault)
            downloader()
            h.wait_for(lambda: diagnostic in delta(failed_before), 'recoverable downloader trust error: ' + fault)
            capture('recoverable-trust-' + fault)
            h.key('KEYCODE_ENTER')  # Actual recoverable error OK, then downloader CLOSE.
            h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
            failed = delta(failed_before)
            for forbidden in ['Creating initial themes list repository clone', 'Performing fast-forward',
                              'Renaming directory', 'Removing disabled theme directory', 'parseThemesList(): Parsed']:
                assert forbidden not in failed, (fault, failed)
            assert {path: h.shell('sha256sum', theme_path(path)).split()[0] for path in paths} == hashes
            retry_before = h.log()
            downloader()
            retry = request_result(retry_before,
                lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
                lambda text: "Couldn't fetch" in text,
                'successful retry after restoring trust prerequisite', 300,
                lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('retry-start', required=True))))
            assert 'owner validation=1; config=' in retry, retry
            if 'Not running the most current application release' in retry:
                h.key('KEYCODE_ENTER')
            h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
            record(f'PASS: actual downloader {fault} failure showed recoverable UI; no repository operations; restored retry fetched successfully')
        for subject in (('themes-list', repository) if extended else ()):
            begin('actual-worker-origin-race-' + subject)
            theme_trust_smoke.request_remote_race(h, subject)
            raced_before = h.log()
            downloader()
            if subject != 'themes-list':
                listed = request_result(raced_before,
                    lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
                    lambda text: "Couldn't fetch" in text,
                    'valid list before per-theme worker origin race', 300,
                    lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('origin-race-list', required=True))))
                if 'Not running the most current application release' in listed:
                    h.key('KEYCODE_ENTER')
                select_theme_row()
                h.key('KEYCODE_ENTER')
            h.wait_for(lambda: 'Theme fetch trust check failed' in delta(raced_before),
                       'actual fetch rejects origin changed after precheck', 90)
            raced = delta(raced_before)
            assert 'Actual fetch remote differs from the admitted URL' in raced, raced
            proof = h.shell('run-as', h.app, 'cat', 'files/theme-trust.remote-race-result')
            assert 'PASS: worker changed origin after precheck and before lookup' in proof, proof
            h.evidence.joinpath('theme-worker-origin-race-' + subject + '.txt').write_text(proof + '\n' + raced)
            capture('actual-worker-origin-rejected-' + subject)
            assert h.shell('pidof', h.app).strip(), 'Origin rejection killed the frontend'
            h.shell('am', 'force-stop', h.app)
            restored = h.shell('am', 'instrument', '-w', '-e', 'mode', 'theme-remote-restore',
                               h.app + '/org.esdeplus.frontend.RuntimeSmoke')
            h.smoke_checks.probe_passed(restored, 'PASS: actual theme origin fixture restored under app UID')
            h.launch()
            retry_before = h.log()
            downloader()
            retried = request_result(retry_before,
                lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
                lambda text: "Couldn't fetch" in text,
                'restored actual origin positive control', 300,
                lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('origin-restored-list', required=True))))
            if 'Not running the most current application release' in retried:
                h.key('KEYCODE_ENTER')
            if subject != 'themes-list':
                select_theme_row()
                before_theme_retry = h.log()
                h.key('KEYCODE_ENTER')
                request_result(before_theme_retry,
                    lambda text: f'Repository "{repository}" already up to date' in text,
                    lambda text: "Couldn't fetch" in text,
                    'restored actual theme fetch positive control', 300,
                    lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('origin-restored-theme', required=True))))
            h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
            record(f'PASS: actual {subject} origin changed in worker after precheck and before lookup; URL gate stopped fetch; restored UI fetch passed')
        if extended and not scoped and h.api in (34, 36):
            retained = [repository + '/theme.xml', repository + '/.git/HEAD',
                        repository + '/.git/config']
            symbolic = h.shell('cat', theme_path(repository + '/.git/HEAD')).strip()
            assert symbolic.startswith('ref: refs/heads/') and '..' not in symbolic.split('/'), symbolic
            retained.append(repository + '/.git/' + symbolic.removeprefix('ref: '))
            hashes = {path: h.shell('sha256sum', theme_path(path)).split()[0] for path in retained}
            begin('shared-theme-real-uninstall')
            assert 'Success' in h.adb('uninstall', h.app)
            assert 'Success' in h.adb('install', str(h.apk))
            h.start_entry('HomeEntry', 'android.intent.category.HOME')
            h.ui('Use direct filesystem compatibility', dpad=True)
            h.ui('Grant direct filesystem access', dpad=True)
            h.grant_from_settings()
            h.ui('Review application-data folder', dpad=True)
            h.ui('Confirm and use this data folder', dpad=True)
            h.ui('Absolute shared ROM folder path', dpad=True)
            h.shell('input', 'text', h.shared)
            h.key('KEYCODE_BACK')
            h.ui('Use typed folder path', dpad=True)
            h.ui('Create system folders', dpad=True)
            h.ui('Save and start frontend', dpad=True)
            h.configured_system('shared-theme-after-real-uninstall-reselect')
            assert f'Finished loading theme "{repository}"' in h.log(), h.log()
            assert {path: h.shell('sha256sum', theme_path(path)).split()[0] for path in retained} == hashes
            h.evidence.joinpath('shared-theme-uninstall-hashes.txt').write_text(json.dumps(hashes, indent=2))
            theme_trust_smoke.request_rewind(h, repository)
            before_reinstall_update = h.log()
            downloader()
            refreshed = request_result(before_reinstall_update,
                lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
                lambda text: "Couldn't fetch" in text,
                'retained themes inventory after real uninstall', 300,
                lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('reinstall-list-start', required=True))))
            if 'Not running the most current application release' in refreshed:
                h.key('KEYCODE_ENTER')
            retained_rewind = theme_trust_smoke.rewind_result(h)
            select_theme_row()
            before_retained_update = h.log()
            retained_update_began = time.monotonic()
            h.key('KEYCODE_ENTER')
            updated = request_result(before_retained_update,
                lambda text: f'Performing fast-forward of repository "{repository}"' in text,
                lambda text: "Couldn't fetch" in text or "Couldn't clone" in text,
                'retained installed theme update after real uninstall', 300,
                lambda _: bool(re.search(r'\bgit_remote_fetch\b', live_state('reinstall-update-start', required=True))))
            h.wait_for(lambda: h.shell('cat', theme_path(repository + '/.git/' + retained_rewind['reference'])).strip()
                       == retained_rewind['latest'], 'retained theme fast-forward after uninstall', 90)
            h.shell('test', '!', '-e', theme_path(repository + '_DISABLED'))
            assert 'contains local changes' not in updated, updated
            h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
            record(f'PASS: real uninstall without -k; reselected shared data; hashes/HEAD retained, '
                   f'theme loaded, installed inventory and actual fast-forward passed; '
                   f'HEAD {retained_rewind["previous"]} -> {retained_rewind["latest"]}; '
                   f'seconds={time.monotonic() - retained_update_began:.3f}')
        destinations = root_destinations(h.api, removable_roots) if extended and not scoped else []
        for new_root, root_kind in destinations:
            # Real root re-selection, using ordinary EditText paste for Unicode.
            old_root = h.data_root
            saved_root = old_root + '.prf-theme-root-saved'
            h.shell('am', 'force-stop', h.app)
            h.shell('test', '!', '-e', saved_root)
            h.shell('mv', old_root, saved_root)
            try:
                pasted = h.shell('am', 'instrument', '-w', '-e', 'mode', 'theme-path-clipboard',
                                 '-e', 'path', new_root, h.app + '/org.esdeplus.frontend.RuntimeSmoke')
                h.smoke_checks.probe_passed(pasted, 'PASS: fixture path clipboard prepared')
                h.start_entry('HomeEntry', 'android.intent.category.HOME')
                h.ui('Absolute application-data folder path', dpad=True)
                current = next(node.get('text', '') for node in h.hierarchy()
                               if node.get('class') == 'android.widget.EditText')
                h.key('KEYCODE_MOVE_END')
                if current:
                    h.shell('input', 'keyevent', *(['KEYCODE_DEL'] * len(current)))
                h.key('KEYCODE_PASTE')
                assert any(node.get('class') == 'android.widget.EditText' and
                           node.get('package') == h.app and node.get('text') == new_root
                           for node in h.hierarchy()), 'Unicode paste lost path characters'
                h.key('KEYCODE_BACK')
                h.ui('Review application-data folder', dpad=True)
                h.ui('Confirm and use this data folder', dpad=True)
                h.select_data_root(new_root)
                h.data_root = new_root
                h.settings = new_root + '/settings/es_settings.xml'
                h.ui('Use typed folder path', dpad=True)
                h.ui('Save and start frontend', dpad=True)
                h.configured_system('theme-unicode-root-reselected')
            finally:
                h.shell('test', '!', '-e', old_root)
                h.shell('mv', saved_root, old_root)
            fresh_settings = h.launch_checks.settings_fragment(h.shell('cat', h.settings))
            debug = fresh_settings.find("bool[@name='DebugMode']")
            if debug is None:
                debug = ET.SubElement(fresh_settings, 'bool', name='DebugMode')
            debug.set('value', 'true')
            h.user_file('settings/es_settings.xml', '<?xml version="1.0"?>\n' +
                        ''.join(ET.tostring(node, encoding='unicode') for node in fresh_settings))
            h.launch()
            owner_leftover = False
            unicode_entries = remote_attempts(lambda: theme_list(False), recover_list, record, 'Unicode-root list')
            download_theme(unicode_entries, extended=False)
            contents = h.shell('run-as', h.app, 'cat', 'files/libgit2/.gitconfig')
            paths = [json.loads(line.split(' = ', 1)[1]) for line in contents.splitlines()
                     if line.startswith('\tdirectory = ')]
            expected_parent = h.shell('readlink', '-f', new_root + '/themes').strip()
            assert all(str(pathlib.PurePosixPath(path).parent) == expected_parent for path in paths), contents
            h.evidence.joinpath('theme-root-reselection-allowlist.txt').write_text(contents)
            record('PASS: real ' + root_kind + ' root re-selection path=' + new_root +
                   '; HTTPS list/theme cloned, selected and loaded; allowlist contains only new root')
        capture('network-theme-applied')
        record(f'PASS: real downloaded {repository} is selectable, saved and loaded through the UI.')

    def scraper(negative):
        begin(('control' if negative else 'fixed') + '-scraper')
        permission(not negative)
        before = h.log()
        menu(1)  # SCRAPER; choose its real system checkbox before START.
        h.key('KEYCODE_DPAD_DOWN'); h.key('KEYCODE_DPAD_DOWN')
        h.key('KEYCODE_ENTER')
        capture('network-' + ('control' if negative else 'fixed') + '-scraper-systems')
        h.key('KEYCODE_ENTER')  # The single loaded NES system.
        capture('network-' + ('control' if negative else 'fixed') + '-scraper-nes-selected')
        h.key('KEYCODE_DEL')
        for _ in range(5):  # From systems row, through four submenus to START.
            h.key('KEYCODE_DPAD_DOWN')
        capture('network-' + ('control' if negative else 'fixed') + '-scraper-start')
        h.key('KEYCODE_ENTER')
        h.wait_for(lambda: 'Scraper::startScraperSearch(): Scraping system "nes"' in delta(before),
                   'real UI submitted NES scraper search', timeout=10)
        output = request_result(before, scraper_reply,
            lambda s: 'ScraperHttpRequest network error' in s,
            'frontend ScreenScraper HTTPS request completed', 90,
            lambda s: 'Scraper::startScraperSearch(): Scraping system "nes"' in s, negative)
        capture('network-' + ('control' if negative else 'fixed') + '-scraper-reply')
        assert 'Scraper::startScraperSearch(): Scraping system "nes"' in output, output
        if negative:
            assert not scraper_reply(output) and resolve_error(output), output
            record('PASS: no-INTERNET APK rejects real scraper HTTPS request with resolve error (one attempt).')
        else:
            if not scraper_reply(output) and remote_error(output):
                raise RemoteFailure('Scraper remote request failed: ' + output)
            assert scraper_reply(output) and not resolve_error(output), output
            record('PASS: frontend ScreenScraper HTTPS request reached service (result/service-level reply).')

    try:
        record(f'Network UI probes: API {h.api}; TV={h.television}; maximum three attempts per remote operation '
               '(clone 300s, scraper 90s, backoff 5s); total work budget 90 minutes, failure evidence 1 minute, '
               'cleanup 5 minutes; no frontend/permission/TLS retries.')
        if h.api == 34 and not scoped:
            begin('control-startup')
            assert control.is_file(), 'Missing built no-INTERNET APK'
            h.adb('install', '-r', str(control))
            permission(False)
            h.launch()
            theme_list(True)
            scraper(True)
            h.shell('am', 'force-stop', h.app)
            h.adb('install', '-r', str(h.apk))
            # libgit2 cleans its failed clone; never delete user data to pass.
            h.shell('test', '!', '-e', theme_path('themes-list'))
        begin('fixed-startup')
        permission(True)
        owner_positive_control()
        h.launch()
        if not scoped and h.api == 36:
            h.shell('mkdir', '-p', theme_path('themes-list/.git'))
            owner_leftover = True
        begin('liveness-control')
        responsive(h.shell('pidof', h.app, check=False).strip())
        with wall_budget(120, 'native diagnostic control'):
            live_state('healthy-frontend', required=True)
        record('PASS: real frontend acknowledges harmless F12; thread stacks and app socket snapshot captured.')
        def recover_list(error):
            if isinstance(error, RemoteStall):
                restart_remote(error, 'themes-list')
            h.shell('test', '!', '-e', theme_path('themes-list'))
        try:
            entries = remote_attempts(lambda: theme_list(False), recover_list, record, 'themes-list')
            download_theme(entries)
        except RemoteFailure as error:
            remote_outcome(h.api, error, record)
            # Finish/cancel only the failed network operation before the independent
            # scraper probe; its startup, permission and UI assertions stay hard.
            restart_remote(error)
        try:
            remote_attempts(lambda: scraper(False), restart_remote, record, 'scraper')
        except RemoteFailure as error:
            remote_outcome(h.api, error, record)
    except BaseException:
        try:
            with wall_budget(60, 'live failure evidence before cleanup', reserve=True):
                live_state('failure-before-stop')
        except Exception as error:
            record('Live failure evidence incomplete: ' + str(error))
        raise
    finally:
        with wall_budget(300, 'network cleanup (5 minutes)', reserve=True):
            h.shell('am', 'force-stop', h.app)
            if h.api == 34:
                h.adb('install', '-r', str(h.apk))
            h.user_file('settings/es_settings.xml', original)
    # Restore the caller's actual HOME entry before inherited lifecycle probes.
    h.start_entry('HomeEntry', 'android.intent.category.HOME')
    h.configured_system('network-restored-home')


if __name__ == '__main__':
    print(controls(), end='')
