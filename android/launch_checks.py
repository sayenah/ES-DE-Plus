#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Assertions used on actual recipient/native evidence.
import copy
import hashlib
import re
import xml.etree.ElementTree as ET


def equal(actual, expected, label):
    assert actual == expected, f'{label}: expected={expected!r}; actual={actual!r}'


def settings_fragment(text):
    # Settings::saveFile emits sibling elements after an XML declaration.
    # The wrapper is only for parsing; it never enters the user's file.
    fragment = re.sub(r'^\s*<\?xml[^?]*\?>', '', text, count=1)
    return ET.fromstring('<fragment>' + fragment + '</fragment>')


def enable_core_query(text):
    document = settings_fragment(text)
    enabled = document.find("bool[@name='RetroArchCoreQueryExperimental']")
    if enabled is None:
        enabled = ET.SubElement(document, 'bool', name='RetroArchCoreQueryExperimental')
    enabled.set('value', 'true')
    return '<?xml version="1.0"?>\n' + ''.join(ET.tostring(child, encoding='unicode') for child in document)


def core_query_enabled(text):
    enabled = settings_fragment(text).find("bool[@name='RetroArchCoreQueryExperimental']")
    equal(enabled is not None and enabled.get('value') == 'true', True, 'Experimental core query enabled')


def all_files_granted(appops):
    equal(bool(re.search(r'\bMANAGE_EXTERNAL_STORAGE:\s*allow\b', appops)), True,
          'Recipient actual all-files permission')


def recipient(observation, frontend_uid, contents):
    assert observation['uid'] != frontend_uid and observation['uid'] >= 10000, observation
    equal(observation['sha256'], hashlib.sha256(contents).hexdigest(), 'Recipient ROM bytes')
    equal(observation['action'], 'android.intent.action.VIEW', 'Recipient action')
    equal(observation['mime'], 'application/octet-stream', 'Recipient MIME')
    equal(observation['categories'], ['android.intent.category.DEFAULT'], 'Recipient category')
    requested = 0x10000000 | 0x04000000 | 0x40000000 | 1
    equal(observation['flags'] & requested, requested, 'Recipient activity/read flags')
    equal(observation['flags'] & 2, 0, 'Recipient receives no write grant')
    for name, expected in {'literal': ('java.lang.String', '雪'),
                           'words': ('[Ljava.lang.String;', ['one', 't,wo', '雪']),
                           'number': ('java.lang.Integer', -2147483648),
                           'yes': ('java.lang.Boolean', True),
                           'no': ('java.lang.Boolean', False)}.items():
        equal(observation['extras'][name]['type'], expected[0], 'Recipient extra type ' + name)
        equal(observation['extras'][name]['value'], expected[1], 'Recipient extra value ' + name)
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
    all_files_granted('Uid mode: MANAGE_EXTERNAL_STORAGE: allow')
    reject('stale Settings switch without app-op', lambda: all_files_granted('No operations.\nDefault mode: default'))
    original = '<?xml version="1.0"?>\n<bool name="RetroArchCoreQueryExperimental" value="false" />\n<string name="Theme" value="雪 &amp; sky" />\n<int name="Volume" value="83" />\n'
    edited = enable_core_query(original)
    core_query_enabled(edited)
    reject('core query still disabled', lambda: core_query_enabled(original))
    before = list(settings_fragment(original))[1:]
    after = list(settings_fragment(edited))[1:]
    equal([(n.tag, n.attrib) for n in after], [(n.tag, n.attrib) for n in before], 'Unrelated user settings preserved')
    valid = {'uid': 10002, 'sha256': hashlib.sha256(b'ROM').hexdigest(),
             'action': 'android.intent.action.VIEW', 'mime': 'application/octet-stream',
             'data': 'content://sample.roms/rom/file',
             'categories': ['android.intent.category.DEFAULT'], 'flags': 0x54000001,
             'extras': {k: {'type': t, 'value': v} for k, t, v in [
                 ('literal', 'java.lang.String', '雪'), ('words', '[Ljava.lang.String;', ['one', 't,wo', '雪']),
                 ('number', 'java.lang.Integer', -2147483648), ('yes', 'java.lang.Boolean', True),
                 ('no', 'java.lang.Boolean', False)]},
             **{k: True for k in ['writeDenied', 'deleteDenied', 'insertDenied', 'updateDenied']}}
    recipient(valid, 10001, b'ROM')
    for name, value in [('uid', 10001), ('uid', 2000), ('sha256', 'corrupt'),
                        ('action', 'wrong'), ('mime', 'wrong'), ('data', '/raw/path'),
                        ('categories', []), ('flags', 0), ('flags', 0x54000003),
                        *[(k, False) for k in ['writeDenied', 'deleteDenied', 'insertDenied', 'updateDenied']]]:
        changed = copy.deepcopy(valid)
        changed[name] = value
        reject(name, lambda changed=changed: recipient(changed, 10001, b'ROM'))
    for name in valid['extras']:
        for part in ['type', 'value']:
            changed = copy.deepcopy(valid)
            changed['extras'][name][part] = 'wrong'
            reject(name + '-' + part, lambda changed=changed: recipient(changed, 10001, b'ROM'))
    return 'PASS: launch evidence assertions reject positive controls: ' + ', '.join(rejected) + '\n'


if __name__ == '__main__':
    print(positive_controls(), end='')
