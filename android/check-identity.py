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

def dex_classes(data):
    assert data.startswith(b'dex\n'), 'Unexpected DEX format'
    strings_offset = struct.unpack_from('<I', data, 60)[0]
    types_offset = struct.unpack_from('<I', data, 68)[0]
    count, classes_offset = struct.unpack_from('<II', data, 96)
    for index in range(count):
        type_index = struct.unpack_from('<I', data, classes_offset + index * 32)[0]
        string_index = struct.unpack_from('<I', data, types_offset + type_index * 4)[0]
        offset = struct.unpack_from('<I', data, strings_offset + string_index * 4)[0]
        # Skip the ULEB128 UTF-16 length; descriptors below use ASCII package names.
        while data[offset] & 128:
            offset += 1
        offset += 1
        yield data[offset:data.index(0, offset)].decode('utf-8')


apk = pathlib.Path(sys.argv[1])
application_id = next(line.split('=', 1)[1] for line in pathlib.Path('android/gradle.properties').read_text().splitlines()
                      if line.startswith('esde.applicationId='))
forbidden = 'org.es_de.frontend'
classes = set()
with zipfile.ZipFile(apk) as archive:
    for entry in archive.namelist():
        data = archive.read(entry)
        if re.fullmatch(r'classes[0-9]*\.dex', entry):
            classes.update(dex_classes(data))
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
    assert 'res/drawable/placeholder_icon.xml' in archive.namelist()
for prefix in ('Lorg/esdeplus/frontend/', 'Lorg/libsdl/app/', 'Lkotlin/', 'Lorg/jetbrains/annotations/'):
    print(f'DEX CLASSES {prefix}: {sum(name.startswith(prefix) for name in classes)}')
assert 'Lorg/esdeplus/frontend/MainActivity;' in classes
assert 'Lorg/esdeplus/frontend/RuntimeSmoke;' in classes

label = ET.parse('android/app/src/main/res/values/strings.xml').find("string[@name='app_name']").text
aapt = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0/aapt'
badging = subprocess.check_output([str(aapt), 'dump', 'badging', str(apk)], text=True)
print(badging)
assert f"package: name='{application_id}'" in badging
assert f"application-label:'{label}'" in badging
assert "sdkVersion:'29'" in badging and "targetSdkVersion:'36'" in badging
print(f'PASS APK identity audit: {application_id}, label={label}, original placeholder icon/splash; only exact upstream desktop literals allowed in libmain.so')
