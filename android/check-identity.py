#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus; audits identity surfaces under D-002 am. 1.
import os
import pathlib
import re
import struct
import xml.etree.ElementTree as ET
import subprocess
import sys
import zipfile
import copy

def dex_definitions(data):
    # Public AOSP DEX class_data_item and method_id_item layouts. Inspect actual
    # defined methods, not mere references, so release keep-rule checks are real.
    assert data.startswith(b'dex\n'), 'Unexpected DEX format'
    def uint(offset):
        return struct.unpack_from('<I', data, offset)[0]
    def uleb(offset):
        value = shift = 0
        while True:
            byte = data[offset]; offset += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value, offset
            shift += 7
    def string(index):
        _, offset = uleb(uint(uint(60) + index * 4))
        return data[offset:data.index(0, offset)].decode('utf-8', errors='replace')
    def type_name(index):
        return string(uint(uint(68) + index * 4))
    def method(index):
        owner, proto, name = struct.unpack_from('<HHI', data, uint(92) + index * 8)
        prototype = uint(76) + proto * 12
        parameters = uint(prototype + 8)
        args = '' if not parameters else ''.join(type_name(struct.unpack_from('<H', data, parameters + 4 + i * 2)[0])
                                                for i in range(uint(parameters)))
        return string(name), '(' + args + ')' + type_name(uint(prototype + 4))
    result = {}
    for index in range(uint(96)):
        definition = uint(100) + index * 32
        owner = type_name(uint(definition))
        result[owner] = set()
        offset = uint(definition + 24)
        if not offset:
            continue
        counts = []
        for _ in range(4):
            count, offset = uleb(offset); counts.append(count)
        for _ in range(counts[0] + counts[1]):
            _, offset = uleb(offset); _, offset = uleb(offset)
        for count in counts[2:]:
            method_index = 0
            for _ in range(count):
                difference, offset = uleb(offset); method_index += difference
                _, offset = uleb(offset); _, offset = uleb(offset)
                result[owner].add(method(method_index))
    return result


apk = pathlib.Path(sys.argv[1])
application_id = next(line.split('=', 1)[1] for line in pathlib.Path('android/gradle.properties').read_text().splitlines()
                      if line.startswith('esde.applicationId='))
forbidden = 'org.es_de.frontend'
classes = {}
release = len(sys.argv) > 2 and sys.argv[2] == "--release"
with zipfile.ZipFile(apk) as archive:
    for entry in archive.namelist():
        data = archive.read(entry)
        if re.fullmatch(r'classes[0-9]*\.dex', entry):
            classes.update(dex_definitions(data))
        if entry.startswith('lib/'):
            if forbidden.encode() in data:
                assert entry.endswith('/libmain.so'), entry
                for offset in [m.start() for m in re.finditer(re.escape(forbidden.encode()), data)]:
                    assert data[offset:].startswith((forbidden + '.desktop\0').encode()), (entry, offset)
                print(f'Permitted upstream desktop-shortcut interoperability literal: {entry}')
        else:
            for encoding in ('utf-8', 'utf-16le', 'utf-16be'):
                assert forbidden.encode(encoding) not in data, (entry, encoding)
        assert not entry.endswith(('.jks', '.keystore')), entry
    assert archive.read('assets/graphics/splash.svg') == pathlib.Path('android/branding/splash.svg').read_bytes()
for prefix in ('Lorg/esdeplus/frontend/', 'Lorg/libsdl/app/', 'Lkotlin/', 'Lorg/jetbrains/annotations/',
               'Lorg/intellij/lang/annotations/'):
    print(f'DEX CLASSES {prefix}: {sum(name.startswith(prefix) for name in classes)}')
assert 'Lorg/esdeplus/frontend/MainActivity;' in classes
assert ('Lorg/esdeplus/frontend/RuntimeSmoke;' in classes) != release
assert ('Lorg/esdeplus/frontend/StartupProbeActivity;' in classes) != release
required_methods = {
    ('checkConfigurationNeeded', '()Z'),
    ('checkEmulatorInstalled', '(Ljava/lang/String;Ljava/lang/String;)Z'),
    ('checkNeedResourceCopy', '(Ljava/lang/String;)Z'),
    ('checkRACoreInstalled', '(Ljava/lang/String;Ljava/lang/String;)I'),
    ('getBatteryStatus', '()[I'), ('getBluetoothStatus', '()I'), ('getCellularStatus', '()I'),
    ('getCreateSystemDirectories', '()Z'), ('getExternalDirectory', '()Ljava/lang/String;'),
    ('getInstalledApps', '(ZZ)[Ljava/lang/String;'), ('getInternalDirectory', '()Ljava/lang/String;'),
    ('getWifiStatus', '()I'), ('getWindowSize', '()[I'), ('getDeviceInfo', '()Ljava/lang/String;'),
    ('getInternalDataDirectory', '()Ljava/lang/String;'), ('getAppDataDirectory', '()Ljava/lang/String;'),
    ('getROMDirectory', '()Ljava/lang/String;'), ('setupFontFiles', '()V'), ('setupLocalizationFiles', '()V'),
    ('setupResources', '(Ljava/lang/String;)Z'), ('startConfigurator', '()V'), ('onNativeFrontendResume', '()V'),
    ('launchGame', '([Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;Z)I'),
}
def pdf_descriptors(methods):
    expected = {('getPdfPageInfo', '(Ljava/lang/String;)Ljava/lang/String;'),
                ('renderPdfPage', '(Ljava/lang/String;III)[B')}
    assert expected <= methods, ('Missing PDF JNI descriptors', expected - methods)

for owner in ['MainActivity', 'NativeBridge']:
    methods = classes['Lorg/esdeplus/frontend/' + owner + ';']
    if owner == 'MainActivity':
        pdf_descriptors(methods)
        for missing in [('getPdfPageInfo', '(Ljava/lang/String;)Ljava/lang/String;'), ('renderPdfPage', '(Ljava/lang/String;III)[B')]:
            try:
                pdf_descriptors(methods - {missing})
            except AssertionError:
                print('PASS: removed PDF JNI descriptor control rejected: ' + missing[0])
            else:
                raise AssertionError('PDF JNI control escaped')
        methods_required = required_methods | {('getPdfPageInfo', '(Ljava/lang/String;)Ljava/lang/String;'),
                                              ('renderPdfPage', '(Ljava/lang/String;III)[B')}
    else:
        methods_required = required_methods
    assert methods_required <= methods, (owner, 'Missing JNI methods', methods_required - methods)
    for name, descriptor in sorted(methods_required):
        print(f'KEPT JNI METHOD {owner}.{name}{descriptor}')
print('PASS: actual defined JNI methods retain every name/descriptor in ' + ('minified release' if release else 'debug') + ' dex')

def dex_licences(names):
    mapping = {}
    if release:
        for line in pathlib.Path('android/app/build/outputs/mapping/release/mapping.txt').read_text().splitlines():
            match = re.fullmatch(r'(\S+) -> (\S+):', line)
            if match:
                mapping['L' + match[2].replace('.', '/') + ';'] = 'L' + match[1].replace('.', '/') + ';'
    for name in names:
        original = mapping.get(name, name)
        assert original.startswith(('Lorg/esdeplus/frontend/', 'Lorg/libsdl/app/', 'Lkotlin/',
                                    'Lorg/jetbrains/annotations/', 'Lorg/intellij/lang/annotations/',
                                    'Lcom/android/tools/r8/')), ('Unreviewed dex class', name, original)

dex_licences(classes)
try:
    dex_licences([*classes, 'Lcom/unreviewed/Library;'])
except AssertionError:
    print('PASS: unreviewed dex class positive control rejected')
else:
    raise AssertionError('Dex licence control escaped')
print('PASS: actual dex definitions belong to the reviewed runtime inventory (R8 mapping in release)')

label = ET.parse('android/app/src/main/res/values/strings.xml').find("string[@name='app_name']").text
aapt = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0/aapt'
badging = subprocess.check_output([str(aapt), 'dump', 'badging', str(apk)], text=True)
print(badging)
# Follow the resource table, including release-shortened ZIP paths. Validate
# every compiled adaptive layer and mark selected by the packaged resources.
resource_table = subprocess.check_output([str(aapt), 'dump', '--values', 'resources', str(apk)], text=True)
pathlib.Path('android/evidence').mkdir(exist_ok=True)
pathlib.Path('android/evidence/identity-resources' + ('-release' if release else '-debug') + '.txt').write_text(resource_table)
resources = {}
resource_names = {}
current = None
for line in resource_table.splitlines():
    if re.match(r'\s*type \d+ ', line):
        current = None
    match = re.search(r'(?<!spec )resource (0x[0-9a-f]+) [^:]+:(\w+)/(\w+)', line)
    if match:
        current = match[2] + '/' + match[3] if match[2] in ('drawable', 'mipmap') else None
    if match and current:
        resource_names[int(match[1], 16)] = current
        resources.setdefault(current, set())
    if current:
        resources[current].update(re.findall(r'\bres/[^\s"\)]+\.xml', line))

def resource_reference(value):
    match = re.search(r'@(?:0x)?([0-9a-f]{8})', value)
    assert match, ('Not a packaged resource reference', value)
    return resource_names[int(match[1], 16)]

packaged_art = {}

def compiled_art(name):
    kind, basename = name.split('/')
    directory = 'mipmap-anydpi' if kind == 'mipmap' else kind
    source = pathlib.Path('android/app/src/main/res') / directory / (basename + '.xml')
    expected_nodes = list(ET.parse(source).getroot().iter())
    assert resources.get(name), ('Missing packaged art', name)
    for path in sorted(resources[name]):
        tree = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), path], text=True)
        print(f'PACKAGED ART {name} {path}\n{tree}')
        validate_art(name, tree, expected_nodes)
        packaged_art[name] = (tree, expected_nodes)

def validate_art(name, tree, expected_nodes):
    nodes = re.split(r'^\s*E:\s+([\w-]+).*$', tree, flags=re.M)[1:]
    assert nodes[::2] == [node.tag for node in expected_nodes], (name, 'Art geometry differs')
    for expected, body in zip(expected_nodes, nodes[1::2]):
        attributes = dict(re.findall(r'^\s*A:\s+android:(\w+)\([^)]*\)=(.*)$', body, re.M))
        expected_attributes = {key.rsplit('}', 1)[-1]: value for key, value in expected.attrib.items()}
        assert attributes.keys() == expected_attributes.keys(), (name, attributes)
        for key, value in expected_attributes.items():
            actual = attributes[key]
            if value.startswith('@'):
                assert resource_reference(actual) == value[1:], (name, key, actual)
                continue
            if key == 'pathData':
                assert re.match(r'^"([^"]*)"', actual)[1] == value, (name, key, actual)
                continue
            kind, data = re.match(r'\(type 0x([0-9a-f]+)\)0x([0-9a-f]+)', actual).groups()
            kind, data = int(kind, 16), int(data, 16)
            if key in ('fillColor', 'strokeColor'):
                colour = int(value[1:], 16) | (0xff000000 if len(value) == 7 else 0)
                assert 28 <= kind <= 31 and data == colour, (name, key, actual)
            elif key in ('strokeLineCap', 'strokeLineJoin'):
                assert kind == 16 and data == {'round': 1}[value], (name, key, actual)
            elif key in ('width', 'height'):
                mantissa = struct.unpack('<i', struct.pack('<I', data))[0] >> 8
                dimension = mantissa * (1, 1/128, 1/32768, 1/8388608)[(data >> 4) & 3]
                assert kind == 5 and (data & 15) == 1 and value.endswith('dp') and dimension == float(value[:-2]), (name, key, actual)
            else:
                assert kind == 4 and abs(struct.unpack('<f', struct.pack('<I', data))[0] - float(value)) < 1e-6, (name, key, actual)

for name in ['mipmap/ic_launcher', 'mipmap/ic_launcher_round', 'drawable/pixel_plus_background',
             'drawable/pixel_plus_foreground', 'drawable/pixel_plus_monochrome',
             'drawable/pixel_plus_mark', 'drawable/tv_banner']:
    compiled_art(name)
# Positive controls use the same validator and actual packaged trees: neither
# changed colour data nor an absent adaptive monochrome layer may pass.
controls = []
tree, expected = packaged_art['drawable/pixel_plus_foreground']
assert '0xff00d1ff' in tree, 'Colour control requires the compiled cyan block'
controls.append(('altered colour', 'drawable/pixel_plus_foreground',
                 tree.replace('0xff00d1ff', '0xff123456', 1), expected))
tree, expected = packaged_art['mipmap/ic_launcher']
missing = re.sub(r'(?ms)^\s*E: monochrome\b.*\Z', '', tree)
assert missing != tree, 'Monochrome control requires the compiled layer'
controls.append(('missing monochrome layer', 'mipmap/ic_launcher', missing, expected))
for fault, name, tree, expected in controls:
    try:
        validate_art(name, tree, expected)
    except AssertionError:
        print('PASS: packaged art positive control rejected: ' + fault)
    else:
        raise AssertionError('Packaged art positive control escaped: ' + fault)
icons = set(re.findall(r"^application-icon-\d+:'([^']+)'$", badging, re.M))
assert icons and icons <= resources['mipmap/ic_launcher'] | resources['mipmap/ic_launcher_round'], icons
assert 'placeholder_icon' not in resource_table, 'Placeholder identity art is still packaged'
print('PASS: manifest-selected Pixel Plus adaptive/round icons, monochrome, marks and TV banner match the original vectors')
assert ('application-debuggable' in badging) != release
assert f"package: name='{application_id}'" in badging
assert f"application-label:'{label}'" in badging
assert "sdkVersion:'33'" in badging and "targetSdkVersion:'36'" in badging
print(f'PASS APK identity audit: {application_id}, label={label}, original Pixel Plus icon/splash; only exact upstream desktop literals allowed in libmain.so')

# Inspect packaged manifest values, including release output, rather than only
# trusting the source declarations or aapt's selected launchable activity.
manifest_tree = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'], text=True)
print('PACKAGED MANIFEST\n' + manifest_tree)
stack = []
manifest_nodes = []
for line in manifest_tree.splitlines():
    element = re.match(r'^(\s*)E: ([\w-]+)', line)
    if element:
        depth = len(element[1])
        while stack and stack[-1][0] >= depth:
            stack.pop()
        node = {'tag': element[2], 'attributes': {}, 'children': []}
        if stack:
            stack[-1][1]['children'].append(node)
        stack.append((depth, node))
        manifest_nodes.append(node)
    else:
        attribute = re.match(r'^\s*A: (?:android:)?(\w+)(?:\([^)]*\))?=(.*)$', line)
        if attribute and stack:
            stack[-1][1]['attributes'][attribute[1]] = attribute[2]

def string_attribute(node, name):
    return re.match(r'^"([^"]*)"', node['attributes'][name])[1]

def integer_attribute(node, name):
    return int(re.match(r'^\(type 0x[0-9a-f]+\)0x([0-9a-f]+)', node['attributes'][name])[1], 16)

activities = {string_attribute(n, 'name'): n for n in manifest_nodes if n['tag'] == 'activity'}
main = activities['org.esdeplus.frontend.MainActivity']
configurator = activities['org.esdeplus.frontend.ConfiguratorActivity']
restart = activities['org.esdeplus.frontend.FrontendRestartActivity']
assert integer_attribute(restart, 'exported') == 0, 'Lifecycle restart must be private'
assert string_attribute(restart, 'process') == ':lifecycle', 'Lifecycle restart must survive the SDL process exit'
assert not restart['children'], 'Lifecycle restart must have no public intent filters'
assert 'taskAffinity' not in configurator['attributes'], 'Configurator must share the SDL task affinity'
assert integer_attribute(main, 'launchMode') == 2, 'SDL activity must be singleTask'
assert integer_attribute(main, 'exported') == 0xffffffff
assert integer_attribute(configurator, 'exported') == 0
aliases = {string_attribute(n, 'name'): n for n in manifest_nodes if n['tag'] == 'activity-alias'}
for alias, category in [('HomeEntry', 'HOME'), ('LeanbackEntry', 'LEANBACK_LAUNCHER')]:
    node = aliases['org.esdeplus.frontend.' + alias]
    assert string_attribute(node, 'targetActivity') == 'org.esdeplus.frontend.MainActivity'
    assert integer_attribute(node, 'exported') == 0xffffffff
    categories = [string_attribute(child, 'name') for intent in node['children']
                  if intent['tag'] == 'intent-filter' for child in intent['children'] if child['tag'] == 'category']
    assert 'android.intent.category.' + category in categories
    assert ('android.intent.category.HOME' in categories) == (alias == 'HomeEntry')
permissions = {string_attribute(n, 'name'): n for n in manifest_nodes if n['tag'] == 'uses-permission'}
for permission in ['READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE']:
    assert integer_attribute(permissions['android.permission.' + permission], 'maxSdkVersion') == 29
assert 'android.permission.MANAGE_EXTERNAL_STORAGE' in permissions
expected_permissions = {'android.permission.' + name for name in
                        ['INTERNET', 'READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE',
                         'MANAGE_EXTERNAL_STORAGE']}
def network_permissions(actual):
    assert set(actual) == expected_permissions, ('Unexpected APK permissions', set(actual))

network_permissions(permissions)
network_permissions(re.findall(r"^uses-permission(?:-sdk-\d+)?: name='([^']+)'", badging, re.M))
for wrong in [expected_permissions - {'android.permission.INTERNET'},
              expected_permissions | {'android.permission.ACCESS_NETWORK_STATE'}]:
    try:
        network_permissions(wrong)
    except AssertionError:
        print('PASS: missing INTERNET / added permission positive control rejected')
    else:
        raise AssertionError('Network permission control escaped')
print('PASS: badging and packaged manifest declare INTERNET and only the three existing storage permissions')
application = next(n for n in manifest_nodes if n['tag'] == 'application')
assert string_attribute(application, 'appComponentFactory') == 'org.esdeplus.frontend.FrontendActivityFactory'
assert ('nativeWaitForConfiguration', '()V') in classes['Lorg/esdeplus/frontend/MainActivity;']
assert integer_attribute(application, 'requestLegacyExternalStorage') == 0xffffffff
for attribute, expected in [('icon', 'mipmap/ic_launcher'), ('roundIcon', 'mipmap/ic_launcher_round'),
                            ('banner', 'drawable/tv_banner')]:
    actual = resource_reference(application['attributes'][attribute])
    assert actual == expected, (attribute, actual)
    print(f'PASS: packaged manifest {attribute}={actual}')
features = {string_attribute(n, 'name'): n for n in manifest_nodes
            if n['tag'] == 'uses-feature' and 'name' in n['attributes']}
assert integer_attribute(features['android.software.leanback'], 'required') == 0
for name in ['nativeSetHold', 'nativeSetHomeApp', 'nativeSetResetTouchOverlay']:
    assert (name, '(Z)V') in classes['Lorg/esdeplus/frontend/MainActivity;']
print('PASS: packaged launcher aliases, singleTask, configurator export, API-specific permissions, TV banner/feature and static native callbacks')

# Use the packaged values for both variants, with deliberately incomplete
# manifests as positive controls for the same audit.
def discovery_manifest(nodes):
    queries = next(n for n in nodes if n['tag'] == 'queries')
    actual = {string_attribute(n, 'name') for n in queries['children'] if n['tag'] == 'package'}
    expected = {entry.text.strip().split('/')[0] for rule in
                ET.parse('resources/systems/android/es_find_rules.xml').iter('rule')
                if rule.get('type') == 'androidpackage' for entry in rule.findall('entry')}
    assert actual == expected, ('Emulator visibility differs from bundled find rules', expected - actual, actual - expected)
    signatures = {(tuple(string_attribute(c, 'name') for c in n['children'] if c['tag'] == 'action'),
                   tuple(string_attribute(c, 'name') for c in n['children'] if c['tag'] == 'category'))
                  for n in queries['children'] if n['tag'] == 'intent'}
    assert signatures == {(("android.intent.action.MAIN",), ("android.intent.category.LAUNCHER",)),
                          (("android.intent.action.MAIN",), ("android.intent.category.LEANBACK_LAUNCHER",))}, signatures
    assert all(not (n['tag'] == 'uses-permission' and
                   string_attribute(n, 'name') == 'android.permission.QUERY_ALL_PACKAGES') for n in nodes)
    provider = next(n for n in nodes if n['tag'] == 'provider' and
                    string_attribute(n, 'authorities') == application_id + '.roms')
    assert integer_attribute(provider, 'exported') == 0
    assert integer_attribute(provider, 'grantUriPermissions') == 0xffffffff
    assert not any(n['tag'] in ('grant-uri-permission', 'path-permission') for n in provider['children'])
    return len(actual)

count = discovery_manifest(manifest_nodes)
for fault in ['package', 'signature', 'broad-query', 'provider-export', 'provider-grants', 'provider-path']:
    malformed = copy.deepcopy(manifest_nodes)
    queries = next(n for n in malformed if n['tag'] == 'queries')
    if fault == 'package':
        queries['children'] = [n for i, n in enumerate(queries['children']) if i != next(
            i for i, n in enumerate(queries['children']) if n['tag'] == 'package')]
    elif fault == 'signature':
        queries['children'] = [n for n in queries['children'] if n['tag'] != 'intent']
    elif fault == 'broad-query':
        malformed.append({'tag': 'uses-permission', 'attributes': {'name': '"android.permission.QUERY_ALL_PACKAGES"'}, 'children': []})
    elif fault == 'provider-export':
        next(n for n in malformed if n['tag'] == 'provider')['attributes']['exported'] = '(type 0x12)0xffffffff'
    elif fault == 'provider-grants':
        next(n for n in malformed if n['tag'] == 'provider')['attributes']['grantUriPermissions'] = '(type 0x12)0x0'
    else:
        next(n for n in malformed if n['tag'] == 'provider')['children'].append(
            {'tag': 'grant-uri-permission', 'attributes': {}, 'children': []})
    try:
        discovery_manifest(malformed)
    except AssertionError:
        print('PASS: discovery manifest positive control rejected: ' + fault)
    else:
        raise AssertionError('Manifest positive control escaped: ' + fault)
def frontend_only(definitions):
    assert not any(n.startswith('Lorg/esdeplus/stub/') for n in definitions), 'CI recipient must never be in the frontend APK'

frontend_only(classes)
try:
    frontend_only([*classes, 'Lorg/esdeplus/stub/RecipientActivity;'])
except AssertionError:
    print('PASS: separate recipient code positive control rejected')
else:
    raise AssertionError('Recipient code positive control escaped')
print(f'PASS: {count} bundled emulator packages, both launcher signatures, exact-grant non-exported provider; no broad visibility or stub code')
