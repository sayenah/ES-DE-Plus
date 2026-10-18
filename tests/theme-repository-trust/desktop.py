#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Compares actual desktop preprocessor output.
import hashlib
import json
import pathlib
import shlex
import subprocess
import tempfile

root = pathlib.Path.cwd()
path = 'es-app/src/guis/GuiThemeDownloader.cpp'
command = next(entry for entry in json.loads((root / 'build/compile_commands.json').read_text())
               if pathlib.Path(entry['file']).resolve() == root / path)
arguments = command.get('arguments') or shlex.split(command['command'])
filtered = []
skip = False
for argument in arguments:
    if skip:
        skip = False
    elif argument == '-o':
        skip = True
    elif argument != '-c' and pathlib.Path(argument).resolve() != root / path:
        filtered.append(argument)
base = subprocess.check_output(['git', 'merge-base', 'origin/main', 'HEAD'], text=True).strip()
with tempfile.TemporaryDirectory(prefix='desktop-trust-', dir=root / 'build') as directory:
    before = pathlib.Path(directory) / 'GuiThemeDownloader.cpp'
    before.write_bytes(subprocess.check_output(['git', 'show', base + ':' + path]))
    for variant in ([], ['-DUSE_BUNDLED_CERTIFICATES']):
        results = []
        for source in (before, root / path):
            output = subprocess.check_output([*filtered, *variant, '-E', '-P', str(source)], cwd=command['directory'])
            results.append(output.replace(str(source).encode(), b'GuiThemeDownloader.cpp'))
        assert results[0] == results[1], ('Desktop GuiThemeDownloader preprocessor output changed', variant)
        print('PASS: desktop GuiThemeDownloader preprocessor output unchanged; base=' + base +
              '; variant=' + repr(variant) + '; sha256=' + hashlib.sha256(results[1]).hexdigest())
