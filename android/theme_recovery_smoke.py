#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real UI process-interruption controls.
import re
import shlex
import xml.etree.ElementTree as ET


def classifier(h, repository, select_row, downloader, request_result, capture, record, theme_path):
    def request(name):
        h.shell('run-as', h.app, 'sh', '-c', 'printf %s ' + shlex.quote(name + '\n') +
                ' > files/theme-retire.missing-origin')

    def fingerprint(path):
        return h.shell('sh', '-c', 'find ' + shlex.quote(path) +
                       ' -type f -exec sha256sum {} \\; | sort')

    def restart(restore=False):
        h.shell('am', 'force-stop', h.app)
        if restore:
            result = h.shell('am', 'instrument', '-w', '-e', 'mode', 'theme-remote-restore',
                             h.app + '/org.esdeplus.frontend.RuntimeSmoke')
            h.smoke_checks.probe_passed(result, 'PASS: actual theme origin fixture restored under app UID')
        h.launch()

    def list_ready(before):
        result = request_result(before,
            lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
            lambda text: "Couldn't fetch" in text or "Couldn't clone" in text,
            'classifier restored themes-list positive control', 300,
            lambda text: 'themes-list' in text)
        assert "Couldn't fetch" not in result and "Couldn't clone" not in result, result
        if 'Not running the most current application release' in result:
            h.key('KEYCODE_ENTER')
        return result

    if h.api == 31:
        for fault in ('cancel', 'private', 'storage', 'identity', 'proceed'):
            restart()
            request('themes-list')
            before = h.log()
            downloader()
            h.wait_for(lambda: 'Android 12 missing-origin classification;' in h.log()[len(before):],
                       'exact Android 12 themes-list classifier', 60)
            capture('missing-origin-list-' + fault + '-prompt')
            path = theme_path('themes-list')
            state = fingerprint(path)
            assert state
            observed_path = path
            if fault == 'private':
                h.shell('run-as', h.app, 'mv', 'files/libgit2/.gitconfig',
                        'files/libgit2/.prf-before-fault')
            elif fault == 'storage':
                h.shell('mv', h.data_root, h.data_root + '.prf-unavailable')
                observed_path = h.data_root + '.prf-unavailable/themes/themes-list'
            elif fault == 'identity':
                h.shell('mv', path + '/.git', path + '/.git.prf-before-fault')
                h.shell('mkdir', path + '/.git')
                state = fingerprint(path)
            if fault == 'cancel':
                h.key('KEYCODE_DPAD_RIGHT')
            h.key('KEYCODE_ENTER')
            if fault == 'proceed':
                result = list_ready(before)
                assert result.count('Renaming directory ' + path) == 1, result
                h.shell('test', '-d', path + '_CORRUPT_DISABLED/.git')
                capture('missing-origin-list-recovered')
                record('PASS: exact Android 12 themes-list condition; D-pad explicit bounded '
                       'rename/fresh clone; retained old directory; restored list usable')
                h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
                continue
            # No sleeps or retries: wait for the cancel/error UI to render, then
            # compare against the state after the deliberate fault injection.
            capture('missing-origin-list-' + fault + '-confirmation')
            after = fingerprint(observed_path)
            if fault == 'storage':
                # Normalize only the deliberately moved pathname in hash output.
                after = after.replace(h.data_root + '.prf-unavailable', h.data_root)
                h.shell('mv', h.data_root + '.prf-unavailable', h.data_root)
            assert after == state, (fault, 'confirmation mutated the rejected repository')
            if fault == 'private':
                h.shell('run-as', h.app, 'mv', 'files/libgit2/.prf-before-fault',
                        'files/libgit2/.gitconfig')
            elif fault == 'identity':
                h.shell('rmdir', path + '/.git')
                h.shell('mv', path + '/.git.prf-before-fault', path + '/.git')
            assert 'Renaming directory ' + path not in h.log()[len(before):]
            record('PASS: missing-origin prompt ' + fault + '; confirmation/cancel made no '
                   'repository mutation; fault restored only after observation')
            restart(restore=True)
            positive = h.log()
            downloader()
            list_ready(positive)
            h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
    restart()
    before = h.log()
    downloader()
    list_ready(before)
    select_row()
    request(repository)
    before = h.log()
    h.key('KEYCODE_ENTER')
    h.wait_for(lambda: "Couldn't get information about origin" in h.log()[len(before):],
               'actual theme missing-origin failure', 90)
    result = h.log()[len(before):]
    assert ('Android 12 missing-origin classification;' in result) == (h.api == 31), result
    assert 'Renaming directory ' not in result and 'Deleting theme directory ' not in result
    capture('missing-origin-theme-error-api' + str(h.api))
    record('PASS: actual theme missing-origin error; platform wording path recorded; '
           'no automatic rename/delete; native corrupt(false) control also required')
    restart(restore=True)
    before = h.log()
    downloader()
    list_ready(before)
    select_row()
    before = h.log()
    h.key('KEYCODE_ENTER')
    result = request_result(before,
        lambda text: f'Repository "{repository}" already up to date' in text,
        lambda text: "Couldn't fetch" in text or "Couldn't get information about origin" in text,
        'restored actual theme fetch positive control', 300,
        lambda text: repository in text)
    assert f'Repository "{repository}" already up to date' in result, result
    h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')


def run(h, repository, select_row, downloader, request_result, capture, record, theme_path):
    """Disposable clones are prepared before each kill; recovery gets no file repair."""
    original = h.shell('cat', h.settings)
    document = h.launch_checks.settings_fragment(original)
    document.find("string[@name='Theme']").set('value', 'linear-es-de')
    h.shell('am', 'force-stop', h.app)
    h.user_file('settings/es_settings.xml', '<?xml version="1.0"?>\n' +
                ''.join(ET.tostring(node, encoding='unicode') for node in document))
    h.launch()

    def control(name, value):
        h.shell('run-as', h.app, 'sh', '-c', 'printf %s ' + shlex.quote(value) +
                ' > files/' + name)

    def listed(before):
        result = request_result(before,
            lambda text: bool(re.search(r'parseThemesList\(\): Parsed [1-9]\d* themes', text)),
            lambda text: "Couldn't fetch" in text or "Couldn't clone" in text,
            'interruption control themes-list ready', 300,
            lambda text: 'themes-list' in text)
        assert "Couldn't fetch" not in result and "Couldn't clone" not in result, result
        if 'Not running the most current application release' in result:
            h.key('KEYCODE_ENTER')
        return result

    def completed(before, name):
        if name == 'themes-list':
            return listed(before)
        marker = f'Downloaded theme "{name}"'
        result = request_result(before, lambda text: marker in text,
            lambda text: "Couldn't clone" in text,
            'fresh theme download after process interruption', 300,
            lambda text: f'repository "{name}"' in text or 'Cloning' in text)
        assert marker in result, result
        return result

    for name in ('themes-list', repository):
        for stage in ('clone-retire-created', 'clone-retire-unlinked',
                      'clone-retire-renamed', 'clone-post-check'):
            label = 'retire-kill-' + name + '-' + stage
            h.shell('am', 'force-stop', h.app)
            # Initial fixture setup only: remove this run's disposable target.
            # There are no filesystem repair operations after termination.
            h.shell('rm', '-rf', theme_path(name))
            h.shell('run-as', h.app, 'rm', '-f', 'files/theme-retire.reached')
            control('theme-retire.interrupt', stage + '\n' + name + '\n')
            other = repository if name == 'themes-list' else 'themes-list'
            protected = [theme_path(other + '/.git/config'), theme_path(other + '/.git/HEAD'),
                         theme_path(other + ('/themes.json' if other == 'themes-list' else '/theme.xml'))]
            hashes = {path: h.shell('sha256sum', path).split()[0] for path in protected}
            ca = h.shell('run-as', h.app, 'sha256sum',
                         'files/resources/certificates/curl-ca-bundle.crt')
            h.launch()
            before = h.log()
            downloader()
            if name == 'themes-list':
                h.key('KEYCODE_ENTER')  # Normal first-download consent.
            else:
                listed(before)
                select_row()
                h.key('KEYCODE_ENTER')
            h.wait_for(lambda: stage + '\n' + name + '\n' in h.shell(
                'run-as', h.app, 'cat', 'files/theme-retire.reached', check=False),
                'actual clone interruption barrier ' + label, 300)
            state = h.shell('run-as', h.app, 'cat', 'files/theme-retire.reached')
            h.evidence.joinpath(label + '-state.txt').write_text(state)
            at_barrier = h.log()
            assert f'Downloaded theme "{name}"' not in at_barrier[len(before):]
            capture(label + '-before-kill')
            killed = h.shell('pidof', h.app).strip()
            h.shell('am', 'force-stop', h.app)
            assert not h.shell('pidof', h.app, check=False).strip()
            h.launch()
            assert h.shell('pidof', h.app).strip() != killed
            fresh = h.log()
            downloader()
            if name != 'themes-list':
                listed(fresh)
                select_row()
                h.key('KEYCODE_ENTER')
            capture(label + '-recovery-ui')
            # For an incomplete clone the native UI offers bounded rename and
            # download. A valid post-clone tree may instead take the update
            # path: record that observation and keep the fresh-download AC hard.
            h.key('KEYCODE_ENTER')
            result = completed(fresh, name)
            expected = ('Creating initial themes list repository clone' if name == 'themes-list'
                        else f'Downloaded theme "{name}"')
            if expected not in result:
                record('OBSERVATION: ' + label +
                       ' fresh UI used an existing repository; no fresh clone was observed')
            assert expected in result, (label, 'AC-7 requires a fresh UI download; section 9', result)
            h.shell('test', '!', '-e', theme_path(name + '/.git/esde-plus-init-config'))
            h.evidence.joinpath(label + '-recovery-log.txt').write_text(result)
            assert {path: h.shell('sha256sum', path).split()[0] for path in protected} == hashes
            assert h.shell('run-as', h.app, 'sha256sum',
                           'files/resources/certificates/curl-ca-bundle.crt') == ca
            record('PASS: ' + label + '; fresh PID; UI fresh download; no file-manager repair; '
                   'temporary not promoted; other config/HEAD/content and CA unchanged; '
                   'process interruption only')
            h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL'); h.key('KEYCODE_DEL')
    h.shell('am', 'force-stop', h.app)
    h.user_file('settings/es_settings.xml', original)
    h.launch()
