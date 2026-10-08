#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus; audits identity surfaces under D-002 am. 1.
import pathlib
import subprocess
import sys
import zipfile

apk = pathlib.Path(sys.argv[1])
application_id = next(line.split('=', 1)[1] for line in pathlib.Path('android/gradle.properties').read_text().splitlines()
                      if line.startswith('esde.applicationId='))
forbidden = 'org.es_de.frontend'
with zipfile.ZipFile(apk) as archive:
    for entry in archive.namelist():
        data = archive.read(entry)
        if entry.startswith('lib/'):
            if forbidden.encode() in data:
                assert entry.endswith('/libmain.so'), entry
                print(f'Permitted upstream desktop-shortcut interoperability literal: {entry}')
        else:
            for encoding in ('utf-8', 'utf-16le', 'utf-16be'):
                assert forbidden.encode(encoding) not in data, (entry, encoding)
        assert not entry.endswith(('.jks', '.keystore')), entry
print(f'PASS APK identity audit: {application_id}; upstream literals allowed only in libmain.so')
