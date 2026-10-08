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
for prefix in ('Lorg/esdeplus/frontend/', 'Lorg/libsdl/app/', 'Lkotlin/', 'Lorg/jetbrains/annotations/'):
    print(f'DEX CLASSES {prefix}: {sum(name.startswith(prefix) for name in classes)}')
assert 'Lorg/esdeplus/frontend/MainActivity;' in classes
assert ('Lorg/esdeplus/frontend/RuntimeSmoke;' in classes) != release
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
for owner in ['MainActivity', 'NativeBridge']:
    methods = classes['Lorg/esdeplus/frontend/' + owner + ';']
    assert required_methods <= methods, (owner, 'Missing JNI methods', required_methods - methods)
    for name, descriptor in sorted(required_methods):
        print(f'KEPT JNI METHOD {owner}.{name}{descriptor}')
print('PASS: actual defined JNI methods retain every name/descriptor in ' + ('minified release' if release else 'debug') + ' dex')

label = ET.parse('android/app/src/main/res/values/strings.xml').find("string[@name='app_name']").text
aapt = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0/aapt'
badging = subprocess.check_output([str(aapt), 'dump', 'badging', str(apk)], text=True)
print(badging)
# Release resource optimization shortens filenames. Follow the manifest's real
# icon entry and compare its compiled vector, rather than assuming a ZIP path.
icons = set(re.findall(r"^application-icon-\d+:'([^']+)'$", badging, re.M))
assert icons, 'No manifest-selected application icon'
placeholder = ET.parse('android/app/src/main/res/drawable/placeholder_icon.xml').getroot()
for icon in sorted(icons):
    tree = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), icon], text=True)
    print(f'PACKAGED ICON {icon}\n{tree}')
    nodes = re.split(r'^\s*E:\s+(\w+).*$', tree, flags=re.M)[1:]
    expected_nodes = list(placeholder.iter())
    assert nodes[::2] == [node.tag for node in expected_nodes], (icon, 'Icon geometry differs')
    for expected, body in zip(expected_nodes, nodes[1::2]):
        attributes = dict(re.findall(r'^\s*A:\s+android:(\w+)\([^)]*\)=(.*)$', body, re.M))
        expected_attributes = {name.rsplit('}', 1)[-1]: value for name, value in expected.attrib.items()}
        assert attributes.keys() == expected_attributes.keys(), (icon, attributes)
        for name, value in expected_attributes.items():
            actual = attributes[name]
            if name == 'pathData':
                assert re.match(r'^"([^"]*)"', actual).group(1) == value, (icon, name, actual)
                continue
            kind, data = re.match(r'\(type 0x([0-9a-f]+)\)0x([0-9a-f]+)', actual).groups()
            kind, data = int(kind, 16), int(data, 16)
            if name == 'fillColor':
                assert 28 <= kind <= 31 and data == (int(value[1:], 16) | 0xff000000), (icon, name, actual)
            elif name in ('width', 'height'):
                # Android complex dimensions: signed 24-bit mantissa and radix.
                mantissa = struct.unpack('<i', struct.pack('<I', data))[0] >> 8
                dimension = mantissa * (1, 1/128, 1/32768, 1/8388608)[(data >> 4) & 3]
                assert kind == 5 and (data & 15) == 1 and value.endswith('dp') and dimension == float(value[:-2]), (icon, name, actual)
            else:
                assert kind == 4 and struct.unpack('<f', struct.pack('<I', data))[0] == float(value), (icon, name, actual)
print('PASS: manifest-selected compiled icon matches the original placeholder vector')
assert ('application-debuggable' in badging) != release
assert f"package: name='{application_id}'" in badging
assert f"application-label:'{label}'" in badging
assert "sdkVersion:'29'" in badging and "targetSdkVersion:'36'" in badging
print(f'PASS APK identity audit: {application_id}, label={label}, original placeholder icon/splash; only exact upstream desktop literals allowed in libmain.so')
