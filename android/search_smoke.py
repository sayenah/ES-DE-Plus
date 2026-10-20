#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Real search launch/history restart assertions.
import re
import types
import xml.etree.ElementTree as ET


def context(scope):
    return types.SimpleNamespace(**scope) if isinstance(scope, dict) else scope


def launches(scope):
    h = context(scope)
    return re.findall(r'Launching game "([^"]+)" from system', h.log())


def assert_launched(scope, expected, before):
    h = context(scope)
    h.wait_for(lambda: len(launches(h)) > before, 'new native game-launch record')
    assert launches(h)[-1] == expected, (expected, launches(h))


def history(scope, root):
    h = context(scope)
    path = root + '/settings/search_history.xml'
    for read in (h.shell, h.private):
        value = read('cat', path, check=False)
        try:
            return ET.fromstring(value)
        except ET.ParseError:
            pass
    return None


def committed(scope, root, query, game=True):
    value = history(scope, root)
    return (value is not None and query in [node.text for node in value.findall('query')]
            and (not game or any(node.get('system') == 'nes' and
                                 node.get('path') == 'Smoke Alpha.nes'
                                 for node in value.findall('game'))))


def restart(scope, root, query, next_query, name):
    h = context(scope)
    assert committed(h, root, query), 'History missing before restart: ' + root
    h.shell('am', 'force-stop', h.app)
    h.adb('logcat', '-c')
    h.start_entry()
    h.configured_system(name + '-restarted')
    assert committed(h, root, query), 'History missing after restart: ' + root
    # A second committed query makes the new process load and rewrite the store,
    # proving that both the old query and opened game were actually read back.
    h.key('KEYCODE_ESCAPE')
    h.key('KEYCODE_ENTER')
    h.shell('input', 'text', next_query.replace(' ', '%s'))
    h.key('KEYCODE_ENTER')
    h.wait_for(lambda: committed(h, root, next_query), 'new process rewrote search history')
    assert committed(h, root, query), 'History was overwritten instead of loaded'
    value = history(h, root)
    assert value.findall('query')[0].text == next_query
    h.evidence.joinpath(name + '-history.xml').write_text(ET.tostring(value, encoding='unicode'))
    h.key('KEYCODE_ESCAPE')
    h.key('KEYCODE_ESCAPE')
    print('PASS: search query and opened game survive restart/read/rewrite: ' + name, flush=True)
