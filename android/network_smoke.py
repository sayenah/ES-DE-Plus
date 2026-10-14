#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real frontend HTTPS smoke and permission control.
import json
import pathlib
import re
import time
import xml.etree.ElementTree as ET


class RemoteFailure(Exception):
    pass


def resolve_error(output):
    return any(value in output.lower() for value in
               ['could not resolve host', "couldn't resolve host", 'failed to resolve address'])


def remote_error(output):
    # Only a completed request with a specific remote/transport diagnostic
    # qualifies. Permissions, TLS verification, UI, process and wait failures do not.
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
    for value in ['failed to resolve address for gitlab.com', 'Failed to connect to server',
                  'unexpected HTTP status code: 503', 'Server returned HTTP error code 429']:
        assert remote_error(value), value
    assert scraper_reply('ScreenScraperRequest::processGame(): Name: Example')
    assert scraper_reply('GuiScraperSearch: Network error: Server returned HTTP error code 403')
    for value in ['Scraper::startScraperSearch(): Scraping system "nes"',
                  'ScraperHttpRequest network error - Could not resolve hostname',
                  'SSL peer certificate cannot be authenticated']:
        assert not scraper_reply(value), value
    return 'PASS: retry classification excludes permission/TLS/frontend failures; only an HTTPS service reply satisfies scraper reachability.\n'


def run(harness):
    h = type('Harness', (), harness)
    h.evidence.joinpath('network-assertion-positive-controls.txt').write_text(controls())
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

    def request_result(before, success, failure, description, timeout):
        output = ''
        def complete():
            nonlocal output
            output = delta(before)
            return success(output) or failure(output)
        h.wait_for(complete, description, timeout=timeout)
        # The poll waits for a request to complete; it never resends an action.
        time.sleep(1)  # Let the GUI's promise/future completion dismiss the busy overlay.
        assert h.shell('pidof', h.app, check=False).strip(), 'Frontend process died'
        assert h.smoke_checks.package_window_focused(h.focused_window(), h.app), 'Frontend lost focus'
        return output

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
            'frontend themes-list HTTPS clone completed', 300)
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
        # A small public theme from the actual fetched inventory, no modified list.
        selected = next(i for i, t in enumerate(entries) if t['reponame'] == 'simplemenu-es-de')
        assert entries[selected]['url'].startswith('https://') and not entries[selected].get('deprecated')
        for _ in range(selected):
            h.key('KEYCODE_DPAD_DOWN')
        capture('network-theme-selected')
        before = h.log()
        h.key('KEYCODE_ENTER')
        output = request_result(before,
            lambda s: 'Downloaded theme "simplemenu-es-de"' in s,
            lambda s: "Couldn't clone repository" in s,
            'frontend theme HTTPS download completed', 300)
        capture('network-theme-downloaded')
        if "Couldn't clone repository" in output:
            # Only retry this remote clone, never the successful list/UI/startup.
            for attempt in range(2, 4):
                if not remote_error(output):
                    raise AssertionError(output)
                record(f'REMOTE theme attempt {attempt - 1}/3 failed: {output.strip()}')
                h.key('KEYCODE_ENTER')  # Error OK; selection is retained.
                time.sleep(5)
                permission(True)
                before = h.log()
                h.key('KEYCODE_ENTER')
                output = request_result(before,
                    lambda s: 'Downloaded theme "simplemenu-es-de"' in s,
                    lambda s: "Couldn't clone repository" in s,
                    'remote-only theme download retry completed', 300)
                capture(f'network-theme-attempt{attempt}')
                if 'Downloaded theme "simplemenu-es-de"' in output:
                    break
            else:
                raise AssertionError('Theme remote retries exhausted: ' + output)
        h.shell('test', '-f', theme_path('simplemenu-es-de/theme.xml'))
        h.shell('test', '-f', theme_path('simplemenu-es-de/.git/HEAD'))
        h.key('KEYCODE_DEL')  # Closing downloader repopulates the real theme selector.
        h.wait_for(lambda: re.search(r'Added theme "[^"]+/simplemenu-es-de"', delta(before)),
                   'downloaded theme added to frontend inventory')
        h.key('KEYCODE_DPAD_DOWN')  # Theme selector, below downloader.
        h.key('KEYCODE_DPAD_RIGHT')  # Linear and the newly downloaded SimpleMenu.
        capture('network-theme-selectable')
        h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
        h.wait_for(lambda: 'Finished loading theme "simplemenu-es-de"' in delta(before),
                   'downloaded theme selected and loaded through UI')
        saved = h.shell('cat', h.settings)
        assert h.launch_checks.settings_fragment(saved).find("string[@name='Theme']").get('value') == 'simplemenu-es-de', saved
        capture('network-theme-applied')
        record('PASS: real downloaded simplemenu-es-de is selectable, saved and loaded through the UI.')

    def scraper(negative):
        permission(not negative)
        before = h.log()
        menu(1)  # SCRAPER; seven rows, then START button.
        for _ in range(7):
            h.key('KEYCODE_DPAD_DOWN')
        capture('network-' + ('control' if negative else 'fixed') + '-scraper-start')
        h.key('KEYCODE_ENTER')
        output = request_result(before, scraper_reply,
            lambda s: 'ScraperHttpRequest network error' in s,
            'frontend ScreenScraper HTTPS request completed', 90)
        capture('network-' + ('control' if negative else 'fixed') + '-scraper-reply')
        assert 'Scraper::startScraperSearch(): Scraping system "nes"' in output, output
        if negative:
            assert not scraper_reply(output) and resolve_error(output), output
            record('PASS: no-INTERNET APK rejects real scraper HTTPS request with resolve error (one attempt).')
        else:
            assert scraper_reply(output) and not resolve_error(output), output
            record('PASS: frontend ScreenScraper HTTPS request reached service (result/service-level reply).')

    try:
        record(f'Network UI probes: API {h.api}; TV={h.television}; maximum three remote theme attempts; no frontend/permission retries.')
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
        for attempt in range(1, 4):
            try:
                theme_list(False)
                break
            except RemoteFailure as error:
                record(f'REMOTE themes attempt {attempt}/3 failed: {error}')
                if attempt == 3:
                    raise
                # libgit2 normally cleans an unsuccessful clone; do not remove a
                # successful list or reset the frontend to make a probe pass.
                h.shell('test', '!', '-e', theme_path('themes-list'))
                time.sleep(5)
        scraper(False)
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
