# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus.
# Compile the actual frontend hook bodies without its SDL/rendering dependency graph.
import pathlib
import sys

root, output = map(pathlib.Path, sys.argv[1:])
parts = []
for name, signatures in {
    'FileData.cpp': ['FileData::~FileData()', 'void FileData::addChild(FileData* file)',
                     'void FileData::removeChild(FileData* file)'],
    'SystemData.cpp': ['void SystemData::deleteSystems()'],
    'main.cpp': ['void onExit()'],
}.items():
    source = root / 'es-app/src' / name
    text = source.read_text()
    for signature in signatures:
        begin = text.index(signature + '\n{')
        end = text.index('{', begin)
        depth = 1
        while depth:
            end += 1
            depth += (text[end] == '{') - (text[end] == '}')
        parts.append(f'#line {text[:begin].count(chr(10)) + 1} "{source}"\n' + text[begin:end + 1])
    if name == 'SystemData.cpp':
        load = text[text.index('bool SystemData::loadConfig('):text.index('void SystemData::deleteSystems()')]
        if 'LibrarySearch::engine(' in load:
            raise SystemExit('loadConfig must not build the search index synchronously')
output.write_text('\n'.join(parts) + '\n')
