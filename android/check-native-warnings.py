#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus; checks AGP's actual CMake/Ninja output.
import pathlib
import re
import sys
import subprocess

roots = [pathlib.Path(argument) for argument in sys.argv[1:]]
assert roots, 'Supply actual native output roots'
logs = sorted({p for root in roots for p in ([root] if root.is_file() else root.rglob('*.txt'))
               if re.fullmatch(r'build_(?:stdout|stderr|output|error).*\.txt', p.name)})
assert logs and any(p.stat().st_size for p in logs), 'Missing actual native build output'
if not all(root.is_file() for root in roots):
    for abi in ['arm64-v8a', 'x86_64']:
        assert any(abi in str(p) and p.stat().st_size for p in logs), ('Missing native output', abi)
# The protocol pins this upstream fork point. Derive the scope from git, so a
# new or newly edited native file cannot silently escape the warning gate.
changed = subprocess.check_output(
    ['git', 'diff', '--name-only', '--diff-filter=ACMR', '50e4b600a', '--'], text=True).splitlines()
changed += subprocess.check_output(
    ['git', 'ls-files', '--others', '--exclude-standard'], text=True).splitlines()
native = {pathlib.Path(name).name for name in changed
          if pathlib.Path(name).suffix.lower() in {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp'}
          and not name.startswith('external/')}
assert {'Window.cpp', 'main.cpp', 'InputOverlayModel.cpp'} <= native
files = r'(?:^|[/\\\s])(?:' + '|'.join(re.escape(name) for name in sorted(native)) + r'):\d+(?::\d+)?:'
for name in ('Window.cpp', 'main.cpp', 'InputOverlayModel.cpp'):
    control = f'/source/{name}:97:9: warning: add explicit braces [-Wdangling-else]'
    assert re.search(files, control), ('Warning scope control escaped', name)
print(f'PASS: warning scope covers {len(native)} ES-DE-Plus-edited native files; '
      'Window/main/model dangling-else controls rejected')
warnings = []
compiled = {abi: set() for abi in ['arm64-v8a', 'x86_64']}
for log in logs:
    print(f'NATIVE BUILD LOG {log}: {log.stat().st_size} bytes')
    text = log.read_text(errors='replace')
    print(text)
    for abi in compiled:
        if abi in log.parts:
            compiled[abi].update(re.findall(r'(InputOverlay|PlatformUtilAndroid|ConvertPDF|PDFViewer|PdfSmoke|EmulatorManagerConfig|EmulatorLaunchProfile|EmulatorManagerRuntime|EmulatorManagerTouch|GuiEmulatorManager|FileData|SystemData|GuiAlternativeEmulators|ViewController|InputManager|GuiMenu|GuiSettings|GuiComponent|ComponentList)\.cpp\.o', text))
    warnings.extend(line for line in text.splitlines() if 'warning:' in line and re.search(files, line))
if warnings:
    print('FAIL: native warnings in ES-DE-Plus files\n' + '\n'.join(warnings))
    sys.exit(1)
def compilation(files, abi):
    assert files == {'ComponentList', 'ConvertPDF', 'EmulatorLaunchProfile', 'EmulatorManagerConfig', 'EmulatorManagerRuntime', 'EmulatorManagerTouch', 'FileData', 'GuiAlternativeEmulators', 'GuiComponent', 'GuiEmulatorManager', 'GuiMenu', 'GuiSettings', 'InputManager', 'InputOverlay', 'PDFViewer', 'PdfSmoke', 'PlatformUtilAndroid', 'SystemData', 'ViewController'}, ('Missing per-ABI compilation evidence', abi, files)

for abi, files in compiled.items():
    compilation(files, abi)
    try:
        compilation(files - {'ConvertPDF'}, abi)
    except AssertionError:
        print(f'PASS: {abi} missing converter compilation positive control rejected')
    else:
        raise AssertionError('Compilation evidence control escaped')
    print(f'PASS: {abi} compiled bridge, overlay, Android ConvertPDF.cpp and PDFViewer.cpp')
print('PASS: no compiler warnings in the changed and ES-DE-Plus native files')
