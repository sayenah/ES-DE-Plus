#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Assertions used on actual recipient/native evidence.
import copy
import hashlib


def equal(actual, expected, label):
    assert actual == expected, f'{label}: expected={expected!r}; actual={actual!r}'


def recipient(observation, frontend_uid, contents):
    assert observation['uid'] != frontend_uid and observation['uid'] >= 10000, observation
    equal(observation['sha256'], hashlib.sha256(contents).hexdigest(), 'Recipient ROM bytes')
    equal(observation['action'], 'android.intent.action.VIEW', 'Recipient action')
    equal(observation['mime'], 'application/octet-stream', 'Recipient MIME')
    assert observation['data'].startswith('content://') and '.roms/' in observation['data'], observation
    for name in ['writeDenied', 'deleteDenied', 'insertDenied', 'updateDenied']:
        equal(observation[name], True, name)


def positive_controls():
    rejected = []

    def reject(label, action):
        try:
            action()
        except AssertionError:
            rejected.append(label)
        else:
            raise AssertionError('Positive control escaped: ' + label)

    equal(True, True, 'true observation')
    reject('false observation', lambda: equal(False, True, 'true observation'))
    equal('expected', 'expected', 'text observation')
    reject('wrong text', lambda: equal('unexpected', 'expected', 'text observation'))
    valid = {'uid': 10002, 'sha256': hashlib.sha256(b'ROM').hexdigest(),
             'action': 'android.intent.action.VIEW', 'mime': 'application/octet-stream',
             'data': 'content://sample.roms/rom/file',
             **{k: True for k in ['writeDenied', 'deleteDenied', 'insertDenied', 'updateDenied']}}
    recipient(valid, 10001, b'ROM')
    for name, value in [('uid', 10001), ('uid', 2000), ('sha256', 'corrupt'),
                        ('action', 'wrong'), ('mime', 'wrong'), ('data', '/raw/path'),
                        *[(k, False) for k in ['writeDenied', 'deleteDenied', 'insertDenied', 'updateDenied']]]:
        changed = copy.deepcopy(valid)
        changed[name] = value
        reject(name, lambda changed=changed: recipient(changed, 10001, b'ROM'))
    return 'PASS: launch evidence assertions reject positive controls: ' + ', '.join(rejected) + '\n'


if __name__ == '__main__':
    print(positive_controls(), end='')
