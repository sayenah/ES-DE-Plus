#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus; checks AGP's actual CMake/Ninja output.
import pathlib
import re
import sys

roots = [pathlib.Path(argument) for argument in sys.argv[1:]]
assert roots, 'Supply actual native output roots'
logs = sorted({p for root in roots for p in ([root] if root.is_file() else root.rglob('*.txt'))
               if re.fullmatch(r'build_(?:stdout|stderr|output|error).*\.txt', p.name)})
assert logs and any(p.stat().st_size for p in logs), 'Missing actual native build output'
if not all(root.is_file() for root in roots):
    for abi in ['arm64-v8a', 'x86_64']:
        assert any(abi in str(p) and p.stat().st_size for p in logs), ('Missing native output', abi)
files = r'(?:InputOverlay|PlatformUtilAndroid)\.(?:cpp|h)'
warnings = []
compiled = set()
for log in logs:
    print(f'NATIVE BUILD LOG {log}: {log.stat().st_size} bytes')
    text = log.read_text(errors='replace')
    print(text)
    compiled.update(re.findall(r'(InputOverlay|PlatformUtilAndroid)\.cpp\.o', text))
    warnings.extend(line for line in text.splitlines() if 'warning:' in line and re.search(files, line))
if warnings:
    print('FAIL: native warnings in ES-DE-Plus files\n' + '\n'.join(warnings))
    sys.exit(1)
assert compiled == {'InputOverlay', 'PlatformUtilAndroid'}, ('Missing compilation evidence', compiled)
print('PASS: no compiler warnings in the four ES-DE-Plus native files')
