#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real frontend HTTPS smoke and permission control.
import json
import pathlib
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


class RemoteFailure(Exception):
    def __init__(self, message):
        assert remote_error(message), 'Failure is not eligible for remote handling: ' + message
        super().__init__(message)


class RemoteStall(RemoteFailure):
    def __init__(self, description, timeout):
        # Constructed only by the deadline path after the final health check.
        Exception.__init__(self, f'{description}: healthy frontend, remote deadline {timeout}s expired')


def wait_request(read, healthy, success, failure, description, timeout,
                 clock=time.monotonic, pause=time.sleep):
    deadline = clock() + timeout
    while True:
        output = read()
        healthy()  # Includes the completing poll and the deadline poll.
        if success(output) or failure(output):
            return output
        # Never turn a TLS/permission diagnostic into a stall just because the
        # expected completion line is absent.
        assert not any(value in output.lower() for value in
                       ['permission denied', 'not permitted', 'ssl', 'tls', 'certificate']), output
        if clock() >= deadline:
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
    for api in (29, 34, 36):
        ticks = [0]
        attempts = []
        recoveries = []
        def pause(seconds):
            ticks[0] += seconds
        def stalled():
            attempts.append(ticks[0])
            return wait_request(lambda: '', lambda: None, bool, bool, 'fixture stalled remote', 10,
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
    return '\n'.join(reports) + '\n'


def run(harness):
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
    for kind, name, value in values:
        node = document.find(f"{kind}[@name='{name}']")
        if node is None:
            node = ET.SubElement(document, kind, name=name)
        node.set('value', value)
    configured = '<?xml version="1.0"?>\n' + ''.join(ET.tostring(n, encoding='unicode') for n in document)
    h.user_file('settings/es_settings.xml', configured)
    control = pathlib.Path('android/.deps/network/no-internet.apk')

    def record(message):
        print(message, flush=True)
        with h.evidence.joinpath('network-result.txt').open('a') as output:
            output.write(message + '\n')

    def permission(expected):
        dump = h.shell('dumpsys', 'package', h.app)
        granted = bool(re.search(r'android.permission.INTERNET: granted=true\b', dump))
        assert granted == expected, 'Installed INTERNET permission differs from probe: ' + dump
        h.evidence.joinpath('network-' + ('fixed' if expected else 'control') + '-package.txt').write_text(dump)

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

    def capture(name):
        h.screenshot(name)
        h.save_logs(name)

    def healthy(pid):
        assert pid, 'Frontend process died'
        h.dismiss_stock_onboarding()
        h.hierarchy()  # The shared handler raises on a frontend ANR.
        logcat = h.adb('logcat', '-d', '-v', 'threadtime')
        frontend_process(pid, h.shell('pidof', h.app, check=False).strip(), logcat)
        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), 'Frontend lost focus'
        assert 'ANR in ' + h.app not in logcat, 'Frontend ANR'

    def request_result(before, success, failure, description, timeout, negative=False):
        pid = h.shell('pidof', h.app, check=False).strip()
        assert pid, 'Frontend process died'
        print('WAIT: ' + description, flush=True)
        try:
            output = wait_request(lambda: delta(before), lambda: healthy(pid), success, failure,
                                  description, timeout)
        except RemoteStall:
            capture('network-stalled-request')
            healthy(pid)
            output = delta(before)
            if success(output) or failure(output):
                return output  # Completion during evidence capture wins over the deadline.
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
        healthy(h.shell('pidof', h.app, check=False).strip())
        h.shell('am', 'force-stop', h.app)
        if isinstance(error, RemoteStall) and relative:
            h.shell('rm', '-rf', theme_path(relative))
        h.launch()  # Ordinary startup stays a hard, single-attempt assertion.

    def theme_list(negative):
        permission(not negative)
        h.shell('test', '!', '-e', theme_path('themes-list'))
        before = h.log()
        downloader()
        capture('network-' + ('control' if negative else 'fixed') + '-first-use')
        h.key('KEYCODE_ENTER')  # Real first-use PROCEED, never bypassed.
        output = request_result(before,
            lambda s: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', s)),
            lambda s: "Couldn't clone repository" in s,
            'frontend themes-list HTTPS clone completed', 300, negative)
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
        entries = sorted(themes['themes'] + themes.get('themesAndroid', []), key=lambda t: t['name'].upper())
        assert entries and h.shell('cat', theme_path('themes-list/.git/HEAD')).strip()
        h.evidence.joinpath('network-themes-list-head.txt').write_text(
            h.shell('cat', theme_path('themes-list/.git/HEAD')) +
            h.shell('cat', theme_path('themes-list/.git/config')))
        record(f'PASS: frontend cloned canonical themes-list using bundled CA; rendered {len(entries)} themes.')
        if 'Not running the most current application release' in output:
            h.key('KEYCODE_ENTER')  # Upstream's compatibility warning, captured above.
        return entries

    def download_theme(entries):
        # HOME is upstream's first-row action. Use the real fetched row.
        selected = entries[0]
        repository = selected['reponame']
        assert re.fullmatch(r'[A-Za-z0-9_-]+', repository), repository
        assert selected['url'].startswith('https://') and not selected.get('deprecated')
        downloaded = f'Downloaded theme "{repository}"'
        before = ''
        def attempt():
            nonlocal before
            permission(True)
            h.shell('test', '!', '-e', theme_path(repository))
            h.key('KEYCODE_MOVE_HOME')
            capture('network-theme-selected')
            before = h.log()
            h.key('KEYCODE_ENTER')
            output = request_result(before, lambda s: downloaded in s,
                lambda s: "Couldn't clone repository" in s,
                'frontend theme HTTPS download completed', 300)
            capture('network-theme-downloaded')
            if "Couldn't clone repository" in output:
                raise RemoteFailure(output)
            return output
        def recover(error):
            if isinstance(error, RemoteStall):
                restart_remote(error, repository)
                permission(True)
                before_list = h.log()
                downloader()  # Existing list opens without first-use PROCEED.
                output = request_result(before_list,
                    lambda s: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', s)),
                    lambda s: "Couldn't fetch" in s or "Couldn't clone" in s,
                    'existing themes-list ready after remote cancellation', 300)
                # Recovery is never another retry budget for the list.
                assert 'parseThemesList(): Parsed ' in output, output
                if 'Not running the most current application release' in output:
                    h.key('KEYCODE_ENTER')
            else:
                h.key('KEYCODE_ENTER')  # Completed remote error OK; selection retained.
        remote_attempts(attempt, recover, record, 'theme')
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
        capture('network-theme-applied')
        record(f'PASS: real downloaded {repository} is selectable, saved and loaded through the UI.')

    def scraper(negative):
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
            'frontend ScreenScraper HTTPS request completed', 90, negative)
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
        record(f'Network UI probes: API {h.api}; TV={h.television}; maximum three attempts per remote operation (clone 300s, scraper 90s, backoff 5s); no frontend/permission/TLS retries.')
        if h.api == 34:
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
        permission(True)
        h.launch()
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
    finally:
        h.shell('am', 'force-stop', h.app)
        if h.api == 34:
            h.adb('install', '-r', str(h.apk))
        h.user_file('settings/es_settings.xml', original)
    # Restore the caller's actual HOME entry before inherited lifecycle probes.
    h.start_entry('HomeEntry', 'android.intent.category.HOME')
    h.configured_system('network-restored-home')


if __name__ == '__main__':
    print(controls(), end='')
