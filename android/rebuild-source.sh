#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Rebuild only the extracted D-009 source bundle.
set -euo pipefail
bundle=$(cd "${1:?Specify the extracted source artefact directory}" && pwd)
[[ -f .clang-format && -f android/distribution.py ]] || { echo 'Run from the extracted repository source'; exit 1; }
[[ ! -d android/.deps && ! -d android/libs && ! -d android/app/.cxx ]] || { echo 'Rebuild requires a fresh source tree, without dependency/build caches'; exit 1; }
python3 android/distribution.py validate "$bundle"
python3 android/distribution.py controls "$bundle"
export GRADLE_USER_HOME="$PWD/android/.deps/rebuild-gradle"
mkdir -p android/.deps/downloads android/evidence
cp "$bundle"/archives/* android/.deps/downloads/
# These copies are independently SHA256 checked by setup before any extraction.
tools/Android_dependencies_setup.sh
export JOBS=${JOBS:-2}
tools/Android_dependencies_build.sh arm64-v8a
tools/Android_dependencies_build.sh x86_64
tools/Android_dependencies_setup.sh
# git archive has no .git; use the exact public version recorded in the bundle.
read -r rebuild_code rebuild_name < <(python3 - "$bundle/manifest.json" <<'PYCODE'
import json, sys
record = json.load(open(sys.argv[1]))['apk']
print(record.get('version_code', 1), record.get('version_name', 'slice-1'))
PYCODE
)
(cd android; ./gradlew --no-daemon -Pesde.versionCode="$rebuild_code" -Pesde.versionName="$rebuild_name" :app:assembleDebug :app:assembleRelease :app:auditRuntimeLicences)
python3 android/license-inputs.py audit android/app/build/outputs/apk/debug/app-debug.apk android/app/build/outputs/apk/release/app-release-unsigned.apk "$ANDROID_NDK_HOME"
python3 android/check-elf.py android/app/build/outputs/apk/debug/app-debug.apk
python3 android/check-identity.py android/app/build/outputs/apk/debug/app-debug.apk
python3 android/check-identity.py android/app/build/outputs/apk/release/app-release-unsigned.apk --release
echo 'PASS: both ABIs rebuilt from the extracted source artefact, without checkout or dependency cache; APKs remain on this runner only.'
