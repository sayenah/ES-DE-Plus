#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Shared smoke assertions and positive controls.
import pathlib
import re
import xml.etree.ElementTree as ET


def no_generation(output):
    assert 'Generating ROM directory structure' not in output, output


def warm_entry(output, home):
    assert ('SDL entry reused via onNewIntent' in output or
            'Focused redirect forwarding' in output), output
    assert f'HOME={str(home).lower()}' in output, output


def grants(count, expected):
    assert count == expected, f'Persisted tree grants: {count}; expected {expected}'


def probe_passed(output, diagnostic):
    assert diagnostic in output, output


def onboarding_disabled(changed):
    assert changed, 'Cannot disable stock TV onboarding component'


def onboarding_clear(nodes, package, frontend=None):
    assert any(n.get('package') in {package, frontend} - {None} for n in nodes), 'Launcher/frontend UI missing'
    assert not any(n.get('package') == package and n.get('text') == 'Dismiss' for n in nodes), 'Stock onboarding remains visible'
    assert not stock_tutorial_action(nodes, package), 'Stock tutorial negative action remains visible'


def stock_tutorial_action(nodes, package):
    return next((n.get('text') for n in nodes if n.get('package') == package and
                 n.get('resource-id') == package + ':id/tutorial_negative_action' and
                 n.get('text') in {'Dismiss', 'Continue'} and n.get('clickable') == 'true'), '')


def stock_tutorial_page(nodes, package):
    titles = tuple(sorted({n.get('text', '') for n in nodes if n.get('package') == package and
                          n.get('resource-id') == package + ':id/overlay_tutorial_title'}))
    return titles, stock_tutorial_action(nodes, package)


def live_window(window):
    assert 'WINDOW MANAGER LAST ANR' not in window, 'Historical ANR state cannot prove live focus'
    assert 'WINDOW MANAGER DISPLAY CONTENTS' in window, 'Live WindowManager display dump missing'
    return window


def stock_onboarding_focused(window, package):
    focus = next((line for line in window.splitlines() if 'mCurrentFocus=' in line), '')
    return bool(re.search(re.escape(package) + r'/(?:\.|' + re.escape(package) + r'\.)dialog\.ShowDialogsActivity', focus))


def package_window_focused(window, package):
    focus = next((line for line in window.splitlines() if 'mCurrentFocus=' in line), '')
    return bool(re.search(r'\s' + re.escape(package) + '/', focus))


def exact_label(node, label):
    return any(node.get(field, '').casefold() == label.casefold() for field in ('text', 'content-desc'))


def immersive_tutorial_present(nodes):
    return next((node for node in nodes if node.get('text') == 'Got it' and
                 node.get('package') in {'android', 'com.android.systemui'}), None) is not None


def stock_banner_dismiss_focused(nodes, package):
    return any(n.get('package') == package and n.get('text') == 'Dismiss' and
               n.get('resource-id') == package + ':id/tray_dismiss' and
               n.get('focused') == 'true' and n.get('clickable') == 'true'
               for n in nodes)


def onboarding_dismiss_focused(nodes, package, action='Dismiss'):
    assert action in {'Dismiss', 'Continue'}, action
    assert any(n.get('package') == package and n.get('text') == action and
               n.get('resource-id') == package + ':id/tutorial_negative_action' and
               n.get('focused') == 'true' and n.get('clickable') == 'true'
               for n in nodes), 'Stock onboarding negative action is not focused'


def held_restored(records, nodes, pid, old_pid, app):
    assert pid.isdigit() and pid != old_pid, f'Host did not restart: {old_pid} -> {pid}'
    assert len(records) == 2 and len({r[1] for r in records}) == 1, records
    assert sum(r[0] == 'ConfiguratorActivity' for r in records) == 1, records
    assert sum(r[0] in ('MainActivity', 'HomeEntry', 'LeanbackEntry') for r in records) == 1, records
    assert any(n.get('package') == app and
               n.get('text', '').startswith('Configure ') for n in nodes), nodes


def permission_revocation_return(nodes, old_pid, new_pid, logcat, app):
    # A reset of a stale Settings switch can revoke access, kill its UID and
    # return to the recoverable configurator. Never infer this from UI alone.
    return (old_pid.isdigit() and new_pid.isdigit() and old_pid != new_pid and
            any('Killing ' + old_pid + ':' + app + '/' in line and
                'MANAGE_EXTERNAL_STORAGE changed.' in line for line in logcat.splitlines()) and
            any(n.get('package') == app and n.get('resource-id') == app + ':string/grant_access' and
                n.get('text', '').casefold() == 'grant direct filesystem access' and
                n.get('clickable') == 'true' for n in nodes))


def focus_direction(current, target):
    current_x, current_y = current[0] + current[2], current[1] + current[3]
    target_x, target_y = target[0] + target[2], target[1] + target[3]
    # Dialog actions can share a horizontal row. Navigate with the same real
    # D-pad a TV user has, including left/right between those actions.
    if current_y == target_y and current_x != target_x:
        return 'KEYCODE_DPAD_LEFT' if target_x < current_x else 'KEYCODE_DPAD_RIGHT'
    return 'KEYCODE_DPAD_UP' if target_y < current_y else 'KEYCODE_DPAD_DOWN'


def positive_controls():
    rejected = []

    def reject(name, action):
        try:
            action()
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError('Positive control escaped: ' + name)

    # The generation line comes from the current upstream implementation,
    # so a spelling change cannot quietly make the absence check vacuous.
    source = pathlib.Path('es-app/src/SystemData.cpp').read_text()
    line = next(line for line in source.splitlines() if 'Generating ROM directory structure' in line)
    no_generation('Application startup time: 1s')
    reject('actual ROM-generation diagnostic', lambda: no_generation(line))
    for home in [False, True]:
        warm_entry(f'Focused redirect forwarding entry; HOME={str(home).lower()}', home)
        warm_entry(f'SDL entry reused via onNewIntent; HOME={str(home).lower()}', home)
        reject('missing entry diagnostic', lambda: warm_entry(f'HOME={str(home).lower()}', home))
        reject('wrong HOME state', lambda: warm_entry(f'Focused redirect forwarding; HOME={str(not home).lower()}', home))
    grants(1, 1)
    assert focus_direction([100, 400, 200, 460], [0, 400, 90, 460]) == 'KEYCODE_DPAD_LEFT'
    assert focus_direction([0, 400, 90, 460], [100, 400, 200, 460]) == 'KEYCODE_DPAD_RIGHT'
    assert focus_direction([0, 400, 200, 460], [0, 200, 200, 260]) == 'KEYCODE_DPAD_UP'
    assert focus_direction([0, 200, 200, 260], [0, 400, 200, 460]) == 'KEYCODE_DPAD_DOWN'
    # UIAutomator buttons are XML leaves: Element truthiness is false even
    # when the actual system action was found. Test the real node shape.
    tutorial = ET.fromstring('<node text="Got it" package="android" />')
    assert len(tutorial) == 0 and immersive_tutorial_present([tutorial])
    for nodes in [[], [{'text': 'Got it', 'package': 'smoke.app'}],
                  [{'text': 'Other action', 'package': 'android'}]]:
        reject('unrelated UI is not immersive tutorial', lambda: probe_passed(
            'found' if immersive_tutorial_present(nodes) else '', 'found'))
    probe_passed('exact' if exact_label({'text': 'ES-DE Plus'}, 'ES-DE Plus') else '', 'exact')
    reject('recipient is not frontend launcher icon', lambda: probe_passed(
        'exact' if exact_label({'text': 'ES-DE Plus recipient'}, 'ES-DE Plus') else '', 'exact'))
    reject('cancel revoked selected grant', lambda: grants(0, 1))
    probe_passed('PASS: probe', 'PASS: probe')
    reject('failed runtime probe', lambda: probe_passed('FAIL: probe', 'PASS: probe'))
    live = 'WINDOW MANAGER DISPLAY CONTENTS\nmCurrentFocus=Window{x u0 smoke.app/.MainActivity}'
    assert live_window(live) == live and package_window_focused(live_window(live), 'smoke.app')
    other = 'WINDOW MANAGER DISPLAY CONTENTS\nmCurrentFocus=Window{x u0 stock.launcher/.Home}'
    assert not package_window_focused(live_window(other), 'smoke.app')
    for cached, current in [(other, live), (live, other)]:
        reject('cached ANR focus never proves current focus', lambda cached=cached, current=current: live_window(
            'WINDOW MANAGER LAST ANR\n' + cached + '\n' + current))
    reject('missing live display dump', lambda: live_window('mCurrentFocus=Window{x u0 smoke.app/.MainActivity}'))
    onboarding_disabled(True)
    reject('onboarding control failed', lambda: onboarding_disabled(False))
    onboarding_clear([{'package': 'stock.launcher', 'text': 'Home'}], 'stock.launcher')
    reject('onboarding dialog still visible', lambda: onboarding_clear([{'package': 'stock.launcher', 'text': 'Dismiss'}], 'stock.launcher'))
    reject('missing stock UI after dismissal', lambda: onboarding_clear([], 'stock.launcher'))
    onboarding_clear([{'package': 'smoke.app'}], 'stock.launcher', 'smoke.app')
    reject('unrelated UI after dismissal', lambda: onboarding_clear([{'package': 'other.app'}], 'stock.launcher', 'smoke.app'))
    focus = 'mCurrentFocus=Window{x u0 stock.launcher/.dialog.ShowDialogsActivity}'
    probe_passed('focused' if stock_onboarding_focused(focus, 'stock.launcher') else '', 'focused')
    reject('frontend Dismiss button is not stock onboarding', lambda: probe_passed(
        'focused' if stock_onboarding_focused('mCurrentFocus=Window{x u0 smoke.app/.MainActivity}', 'stock.launcher') else '', 'focused'))
    dismiss = {'package': 'stock.launcher', 'text': 'Dismiss',
               'resource-id': 'stock.launcher:id/tutorial_negative_action',
               'focused': 'true', 'clickable': 'true'}
    onboarding_dismiss_focused([dismiss], 'stock.launcher')
    for field, wrong in [('package', 'smoke.app'), ('text', 'Go to Shop'),
                         ('resource-id', 'stock.launcher:id/tutorial_positive_action'),
                         ('focused', 'false'), ('clickable', 'false')]:
        reject('wrong Dismiss ' + field, lambda field=field, wrong=wrong:
               onboarding_dismiss_focused([dict(dismiss, **{field: wrong})], 'stock.launcher'))
    reject('missing Dismiss action', lambda: onboarding_dismiss_focused([], 'stock.launcher'))
    continued = dict(dismiss, text='Continue')
    assert stock_tutorial_action([continued], 'stock.launcher') == 'Continue'
    onboarding_dismiss_focused([continued], 'stock.launcher', 'Continue')
    reject('Continue tutorial still visible', lambda: onboarding_clear([continued], 'stock.launcher'))
    for field, wrong in [('package', 'smoke.app'), ('text', "See what's on"),
                         ('resource-id', 'stock.launcher:id/tutorial_positive_action'), ('clickable', 'false')]:
        reject('unsafe stock tutorial action ' + field, lambda field=field, wrong=wrong: probe_passed(
            stock_tutorial_action([dict(continued, **{field: wrong})], 'stock.launcher'), 'Continue'))
    title = {'package': 'stock.launcher', 'resource-id': 'stock.launcher:id/overlay_tutorial_title', 'text': 'Live TV'}
    page = stock_tutorial_page([title, continued], 'stock.launcher')
    assert page == stock_tutorial_page([title, title, continued], 'stock.launcher')
    assert page != stock_tutorial_page([dict(title, text='Apps'), continued], 'stock.launcher')
    probe_passed('focused' if package_window_focused(focus, 'stock.launcher') else '', 'focused')
    reject('unrelated window is not stock launcher', lambda: probe_passed(
        'focused' if package_window_focused('mCurrentFocus=Window{x u0 smoke.app/.MainActivity}', 'stock.launcher') else '', 'focused'))
    banner = dict(dismiss, **{'resource-id': 'stock.launcher:id/tray_dismiss'})
    probe_passed('focused' if stock_banner_dismiss_focused([banner], 'stock.launcher') else '', 'focused')
    for field, wrong in [('package', 'smoke.app'), ('text', 'Details'),
                         ('resource-id', 'stock.launcher:id/tutorial_negative_action'),
                         ('focused', 'false'), ('clickable', 'false')]:
        reject('wrong stock banner ' + field, lambda field=field, wrong=wrong: probe_passed(
            'focused' if stock_banner_dismiss_focused([dict(banner, **{field: wrong})], 'stock.launcher') else '', 'focused'))
    records = [('HomeEntry', '7'), ('ConfiguratorActivity', '7')]
    nodes = [{'package': 'smoke.app', 'text': 'Configure ES-DE Plus'}]
    held_restored(records, nodes, '200', '100', 'smoke.app')
    reject('dead relaunched host', lambda: held_restored(records, nodes, '', '100', 'smoke.app'))
    reject('old host survived', lambda: held_restored(records, nodes, '100', '100', 'smoke.app'))
    reject('missing configurator record', lambda: held_restored(records[:1], nodes, '200', '100', 'smoke.app'))
    reject('separate configurator task', lambda: held_restored([records[0], ('ConfiguratorActivity', '8')], nodes, '200', '100', 'smoke.app'))
    reject('two frontend records', lambda: held_restored([records[0], records[0]], nodes, '200', '100', 'smoke.app'))
    reject('redirect substituted for native host', lambda: held_restored([('FrontendRedirectActivity', '7'), records[1]], nodes, '200', '100', 'smoke.app'))
    reject('stock launcher obscures configuration', lambda: held_restored(records, [], '200', '100', 'smoke.app'))
    permission_nodes = [{'package': 'smoke.app', 'resource-id': 'smoke.app:string/grant_access',
                         'text': 'GRANT DIRECT FILESYSTEM ACCESS', 'clickable': 'true'}]
    killed = 'ActivityManager: Killing 100:smoke.app/u0a1 (adj 100): MANAGE_EXTERNAL_STORAGE changed.'
    def revocation(nodes=permission_nodes, old='100', new='200', trace=killed):
        probe_passed('proof' if permission_revocation_return(nodes, old, new, trace, 'smoke.app') else '', 'proof')
    revocation()
    reject('revocation needs new process', lambda: revocation(new='100'))
    reject('revocation needs live process', lambda: revocation(new=''))
    reject('revocation needs exact killed PID', lambda: revocation(trace=killed.replace('100:', '101:')))
    reject('revocation needs permission cause', lambda: revocation(trace=killed.replace('MANAGE_EXTERNAL_STORAGE changed.', 'other cause')))
    for field, wrong in [('package', 'other.app'), ('resource-id', 'smoke.app:string/create_systems'),
                         ('text', 'Other control'), ('clickable', 'false')]:
        reject('revocation wrong recovery ' + field,
               lambda field=field, wrong=wrong: revocation(nodes=[dict(permission_nodes[0], **{field: wrong})]))
    return 'PASS: production smoke assertions reject: ' + ', '.join(rejected) + '.\n'


if __name__ == '__main__':
    print(positive_controls(), end='')
