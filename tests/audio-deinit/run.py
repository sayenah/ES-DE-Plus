#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Same-job unfixed/fixed controls; no framework.
import math
import os
import pathlib
import struct
import subprocess
import sys
import wave


def run(base, build):
    root = pathlib.Path(__file__).resolve().parents[2]
    build = pathlib.Path(build).resolve()
    build.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(
        ['git', 'show', base + ':es-core/src/AudioManager.cpp'], cwd=root, text=True)
    # Do not accidentally label an already-fixed base as a positive control.
    assert 'SDL_CloseAudio();' in source and 'SDL_LockAudioDevice(sAudioDevice);' in source
    control = build / 'AudioManager-base.cpp'
    control.write_text(source)
    fixture = build / 'navigation.wav'
    with wave.open(str(fixture), 'wb') as wav:
        wav.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
        wav.writeframes(b''.join(struct.pack('<hh', value, value) for value in
                        (int(8000 * math.sin(i * 2 * math.pi * 440 / 44100)) for i in range(44100))))
    env = dict(os.environ, SDL_AUDIODRIVER='dummy')
    results = []
    for name, source in [('base', control), ('fixed', root / 'es-core/src/AudioManager.cpp')]:
        target = build / name
        subprocess.run(['cmake', '-S', str(root / 'tests/audio-deinit'), '-B', str(target),
                        '-DCMAKE_BUILD_TYPE=Release', '-DAUDIO_MANAGER_SOURCE=' + str(source)], check=True)
        subprocess.run(['cmake', '--build', str(target), '--parallel', '2'], check=True)
        cases = [('armed', 1)] * 10 if name == 'base' else [('armed', 500), ('disarmed', 10)]
        for index, (mode, cycles) in enumerate(cases, 1):
            completed = subprocess.run([str(target / 'audio-deinit'), mode, str(cycles), str(fixture)],
                                       env=env, capture_output=True, text=True, timeout=300)
            output = completed.stdout + completed.stderr
            (build / f'{name}-{mode}-{index}.txt').write_text(output)
            if name == 'base':
                assert completed.returncode == 86 and 'DETECTED:' in output, output
            else:
                assert completed.returncode == 0 and f'PASS: {cycles} cycles' in output, output
            results.append(f'{name} {mode} #{index}: cycles={cycles}, exit={completed.returncode}\n{output}')
            print(results[-1], flush=True)
    (build / 'summary.txt').write_text(''.join(results))
    print('PASS: base detected 10/10; fixed 500 armed + 10 disarmed cycles clean', flush=True)


if __name__ == '__main__':
    run(*sys.argv[1:])
