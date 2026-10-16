#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Collects native app-context trust controls.
import shlex
import json
import pathlib


def request(h):
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
    assert 'FAIL:' not in report and 'PASS: app-context theme trust controls\n' in report, report
    assert report.count('PASS: 16 mandatory clone/rewind/fetch/reset cycles; no retries\n') == 2, report
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
