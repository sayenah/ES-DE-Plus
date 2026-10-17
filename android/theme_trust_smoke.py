#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Collects native app-context trust controls.
import shlex
import json
import pathlib
import re


def request(h):
    h.evidence.joinpath('theme-trust-ca-before.txt').write_text(
        h.shell('run-as', h.app, 'sha256sum', 'files/resources/certificates/curl-ca-bundle.crt'))
    h.evidence.joinpath('theme-trust-settings-before.txt').write_text(h.shell('sha256sum', h.settings))
    h.shell('run-as', h.app, 'rm', '-f', 'files/theme-trust.result')
    h.shell('run-as', h.app, 'sh', '-c',
            'printf %s ' + shlex.quote('ES-DE-Plus theme trust controls\n') +
            ' > files/theme-trust.request')


def collect(h):
    def result():
        return h.shell('run-as', h.app, 'cat', 'files/theme-trust.result', check=False)
    try:
        h.wait_for(lambda: 'PASS: app-context theme trust controls' in result() or
                   'FAIL:' in result(), 'native app-context repository trust controls', 300)
    finally:
        h.evidence.joinpath('theme-trust-controls.txt').write_text(result())
    report = result()
    if 'FAIL:' in report:
        # Observe the failed fixture later from the same UID, without retrying
        # the operation or changing its failed result. This distinguishes a
        # persistent missing origin from a transient shared-filesystem view.
        root = h.shell('readlink', '-f', h.data_root, check=False).strip()
        allowed = re.escape(root) + r'/theme-trust\.[^/\n]+/themes/(?:original|pending|themes-list)'
        paths = set(re.findall(r'^FETCH remote lookup=.*? path=(.*?) error=', report, re.M))
        paths.update(re.findall(r'^METADATA path=(.*?)$', report, re.M))
        for path in paths:
            if not root.startswith('/') or not re.fullmatch(allowed, path):
                continue
            resolved = h.shell('run-as', h.app, 'readlink', '-f', path + '/.git/config', check=False).strip()
            if resolved != path + '/.git/config':
                h.evidence.joinpath('theme-trust-failed-config-identity.txt').write_text(
                    'Refused diagnostic traversal through a redirected config: ' + path + '\n')
                continue
            observation = ('run-as UID=' + h.shell('run-as', h.app, 'id', '-u', check=False) +
                           '\nstat uid/gid/mode/inode/size=' +
                           h.shell('run-as', h.app, 'sh', '-c',
                                   shlex.join(['stat', '-c', '%u %g %a %i %s',
                                               path + '/.git/config']) + ' 2>&1', check=False) +
                           '\nCONFIG\n' + h.shell('run-as', h.app, 'sh', '-c',
                                   shlex.join(['cat', path + '/.git/config']) + ' 2>&1', check=False))
            if path.startswith('/storage/emulated/0/'):
                # Read only this authored failed fixture below FUSE, after its
                # failure is final. No operation/assertion is repeated. Restore
                # the normal shell before propagating the original failure.
                raw = '/data/media/0/' + path.removeprefix('/storage/emulated/0/')
                rooted = False
                try:
                    reply = h.adb('root', check=False)
                    observation += '\nRAW LOWER-FS DIAGNOSTIC\n' + reply
                    rooted = 'cannot run as root' not in reply
                    if rooted:
                        h.adb('wait-for-device')
                        h.wait_for(lambda: h.shell('id', '-u', check=False).strip() == '0',
                                   'failed-fixture diagnostic shell', timeout=10)
                        for command in (['stat', '-c', '%u %g %a %i %s %Y %Z', raw + '/.git/config'],
                                        ['cat', raw + '/.git/config']):
                            observation += h.shell('sh', '-c', shlex.join(command) + ' 2>&1', check=False)
                except Exception as error:
                    observation += '\nLower-FS diagnostic unavailable: ' + repr(error)
                finally:
                    if rooted:
                        try:
                            h.adb('unroot', check=False)
                            h.adb('wait-for-device')
                            h.wait_for(lambda: h.shell('id', '-u', check=False).strip() == '2000',
                                       'normal shell after failed-fixture diagnostic', timeout=10)
                        except Exception as error:
                            observation += '\nShell restoration failed: ' + repr(error)
            h.evidence.joinpath('theme-trust-failed-config-readback.txt').write_text(observation)
    ca_after = h.shell('run-as', h.app, 'sha256sum',
                       'files/resources/certificates/curl-ca-bundle.crt')
    h.evidence.joinpath('theme-trust-ca-after.txt').write_text(ca_after)
    assert ca_after == h.evidence.joinpath('theme-trust-ca-before.txt').read_text(), 'CA bundle changed'
    assert 'FAIL:' not in report and 'PASS: app-context theme trust controls\n' in report, report
    assert report.count('PASS: 16 mandatory clone/rewind/fetch/reset cycles; no retries\n') == 2, report
    assert report.count('PASS: config bytes survive unobserved tree traversal in all 16 cycles\n') == 2, report
    assert report.count('PASS: retirement boundaries and write/rename/cleanup controls; each restored clone passed\n') == 2, report
    for required in ['raw owner control shared=1 code=-36', 'worktree outside, private and admitted',
                     'gitlink and commondir blocked', 'non-repository, bare and linked worktree',
                     'between-precheck-fetch', 'substituted transport calls=0',
                     'fail-closed mode=direct prior=1', 'fail-closed mode=scoped prior=0',
                     'admission failure with prior allowlist', 'clone boundary clone-before-init',
                     'actual quoted/backslash private Git paths; protected allowlist parsed exactly',
                     'clone boundary clone-after-init', 'three shutdown/reinitialize/open cycles']:
        assert required in report, (required, report)
    print('PASS: native theme trust controls; app UID/stat, identity, remotes, failures, clone barriers',
          flush=True)


def after_all_controls(h):
    ca = h.shell('run-as', h.app, 'sha256sum', 'files/resources/certificates/curl-ca-bundle.crt')
    settings = h.shell('sha256sum', h.settings)
    h.evidence.joinpath('theme-trust-after-all-controls.txt').write_text(ca + settings)
    assert ca == h.evidence.joinpath('theme-trust-ca-before.txt').read_text(), 'CA changed across clone faults'
    assert settings == h.evidence.joinpath('theme-trust-settings-before.txt').read_text(), 'Settings changed across clone faults'


def allowlist(h):
    contents = h.shell('run-as', h.app, 'cat', 'files/libgit2/.gitconfig')
    h.evidence.joinpath('theme-trust-allowlist.txt').write_text(contents)
    assert contents.startswith('[safe]\n') and 'directory = ' in contents, contents
    assert '*' not in contents and '/"\n' not in contents and 'include' not in contents, contents
    paths = [json.loads(line.split(' = ', 1)[1]) for line in contents.splitlines()
             if line.startswith('\tdirectory = ')]
    assert len(paths) == len(set(paths)) and paths, contents
    assert len({str(pathlib.PurePosixPath(path).parent) for path in paths}) == 1, contents
    return {pathlib.PurePosixPath(path).name for path in paths}


def request_rewind(h, repository):
    h.shell('run-as', h.app, 'rm', '-f', 'files/theme-trust.rewind-result')
    h.shell('run-as', h.app, 'sh', '-c', 'printf %s ' + shlex.quote(repository + '\n') +
            ' > files/theme-trust.rewind')


def request_failure(h, fault):
    assert fault in ('temporary', 'replace', 'search')
    h.shell('run-as', h.app, 'sh', '-c', 'printf %s ' + shlex.quote(fault + '\n') +
            ' > files/theme-trust.inject')


def request_remote_race(h, repository):
    h.shell('run-as', h.app, 'rm', '-f', 'files/theme-trust.remote-race-result')
    h.shell('run-as', h.app, 'sh', '-c', 'printf %s ' +
            shlex.quote(repository + '\nhttp://127.0.0.1:9/ESDEPlus-substitute\n') +
            ' > files/theme-trust.remote-race')


def rewind_result(h):
    path = 'files/theme-trust.rewind-result'
    h.wait_for(lambda: 'PASS:' in h.shell('run-as', h.app, 'cat', path, check=False) or
               'FAIL:' in h.shell('run-as', h.app, 'cat', path, check=False),
               'native admitted theme set one commit behind', 90)
    result = h.shell('run-as', h.app, 'cat', path)
    h.evidence.joinpath('shared-theme-rewind.txt').write_text(result)
    assert 'PASS: one commit behind' in result and 'FAIL:' not in result, result
    values = dict(line.split('=', 1) for line in result.splitlines() if '=' in line)
    assert values['latest'] != values['previous'], result
    assert values['reference'].startswith('refs/heads/'), result
    return values
