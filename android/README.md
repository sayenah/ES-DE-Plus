<!-- SPDX-License-Identifier: MIT; ES-DE-Plus — written for ES-DE-Plus. -->
# ES-DE Plus Android host

The open-source Android host supports Android 12 (API 31) and later.

ES-DE-Plus is a fork whose own source remains MIT-licensed. Apart from libgit2 under GPL-2.0 with its linking exception and the RetroArch-derived scanline shader `resources/shaders/glsl/scanlines.glsl` under GPL-2.0-or-later, its Android APK's code contains no GPL code; the shader ships as its own source text and is compiled by the GPU driver at runtime. The APK also includes permissive and Apache-2.0 components and LGPL-2.1 shared libraries. FreeImage offers FIPL, GPL-2.0 or GPL-3.0 (FIPL selected), FreeType's FTL and CImg's CeCILL-C options are selected, and LibRaw inside FreeImage offers LGPL-2.1 or CDDL-1.0 (LGPL-2.1 selected). Bundled fonts, sounds, themes and certificates keep their own licences, including Debian's patched GNU FreeFont (patch series in the manifest; GPL-3.0). Every published APK has a matching source artefact in the same CI run, including pinned third-party sources and build recipes. See [the Android dependency inventory](DEPENDENCY-LICENSES.md) for component terms.

Published CI debug APKs use one stable **test** key held only in GitHub's
`test-signing` environment (the `main` branch only). Certificate SHA-256:
`6bd277aa2b4feb1bd4eae5524defff7be22600c043aaa5e7d9e675aee6920ff0`.
When moving from older throwaway-key builds, **back up and uninstall once**:
uninstall deletes app-owned ROMs, settings, collections, media and logs. ROMs in
selected shared folders survive. Higher-version stable-key builds then update in
place and preserve app data. This is test signing; production/store signing
requires a separate Founder decision. Missing, lost, corrupt or compromised key
material stops publication pending a Founder ruling; CI has no fallback key.

The Orchestrator publishes test builds on demand, after a batch of merged work,
by dispatching **Build Android** on `main` in `sayenah/ES-DE-Plus` with
`publish: true` (default `false`; for example,
`gh workflow run build-android.yml --ref main -F publish=true`). Download them
from [Releases](https://github.com/sayenah/ES-DE-Plus/releases). Each successful publication
creates a pre-release `android-test-<short-sha>` on the exact full commit with
four assets: the exact smoked debug APK, licence-notice ZIP, complete source TAR
and `SHA256SUMS.txt`. The source TAR includes pinned third-party archives,
Debian's font patches and build/relink recipes; GitHub-generated source snapshots
are insufficient. Notes record version, certificate, APK hash and originating
run/attempt. Version code is `1000 + git rev-list --count --first-parent <sha>`
from full history; version name is `test-<short-sha>`. Older out-of-order new
publications are refused. CI stages and downloads/verifies every asset in a
draft before publishing. A matching draft resumes only from the same originating
run/attempt and artefact IDs (rerun the failed publisher job to retain the successful
API 34 job's outputs). A completed release for the same commit, including one
from another run, is fully verified against its original APK/source/provenance
and succeeds without mutation. A new same-commit dispatch retains that original
release; its Actions artefacts remain specific to the new run. A partial draft
from another run/attempt fails with manual recovery instructions: the Orchestrator
removes that unpublished draft, then starts another run. Conflicts, corrupt/missing assets and wrong tags
fail instead of overwriting a published set. CI never deletes releases, tags or
source bundles, and pre-releases are never marked latest.

The same run's Actions source/APK artefacts remain available for 14/7 days.
Keep the corresponding source beside your APK. All pushes (including `main`),
dispatches without `publish: true`, PRs, forks and branch runs use throwaway keys,
exercise packaging and the same release decisions through a non-writing transport,
and never upload an APK or call release APIs. Only the
eligible API 34 job accesses the signing environment; credentials reach SDK
`apksigner` outside Gradle through `env:` password inputs. Its mode-600 temporary
keystore is removed before audits/smoke and on signing failures, outside caches
and uploads. Rebuilds and failure controls cannot publish or access that
environment, even with `publish: true`. See
[the distribution README](DISTRIBUTION-README.md) for source and own-key rebuilding.
Every third-party action in the environment-bound job is pinned to a full
commit SHA. Residual trust in Gradle/AGP resolution without dependency
verification and dependency build code is accepted for this test key under
D-013 am. 2. A compromise stops publication for a Founder ruling on rotation,
which requires another uninstall. Release signing is a separate Founder decision
and cannot reuse this arrangement without a fresh ruling.

CI proves replacement on API 31/34 with two version codes and one throwaway key:
`adb install -r` retains settings, accepted storage configuration and app data,
then launches the higher build. Stable-key custody, real release API publication
and retries, and continuity across two stable-key publications require real
main-run evidence after merge; branch fixtures do not prove those outcomes.

On first launch choose a storage mode before granting permissions. Application
settings, collections and logs stay in the current user's app-specific external
`ES-DE-Plus` directory. Official ES-DE application data is never adopted or migrated.

- **App-owned storage (default):** ROMs live in the app-specific external `ROMs`
  directory. The configurator shows its exact path and how to populate it: install
  Android platform tools on a computer, enable USB debugging, authorize that
  computer, then use `adb push your-ROM-folder/. <displayed-ROM-path>/`. Organize
  games into system folders such as `nes`. Uninstalling removes these games.
  SAF import is deferred.
- **Direct filesystem compatibility (explicit choice):** Open the app's
  all-files-access settings, falling back to the generic settings page if the
  app-specific page is unavailable. Select a local shared ROM folder through the system
  picker, then copy games there using USB file transfer or a file manager. Only
  external-storage-provider trees on a verified mounted current-user volume can
  be mapped to a native path. Both persisted URI grants and actual filesystem
  read/write access are checked. A SAF grant alone does not enable native access.
  If the picker is missing, enter an absolute local folder path; this fallback
  verifies the same volumes/access and creates no URI grant. If all-files settings
  are both missing, use app-owned storage or grant access through device settings.
  Accepting another folder releases superseded pending grants; cancel keeps the
  displayed selection and its grant. Saving app-owned mode releases the old shared grant.

**Create system folders** is a one-shot request on configuration save. The request
is persisted as consumed before native creation begins. Later starts never
regenerate deleted system folders or rewrite their `systeminfo.txt` files. Check
the box again when explicitly saving configuration to request creation again.

The normal launcher, HOME alias and TV/Leanback alias all enter one `singleTask`
SDL activity. Only an intent through the HOME alias with the HOME category sets
HOME state; a normal or Leanback entry clears it, including warm re-entry.
Configurator return preserves the originating entry. HOME mode suppresses the
frontend's Back-to-exit and quit paths; Leanback uses normal app semantics.
Configuration uses ordinary Android views and works with a D-pad. Back/cancel
keeps a recoverable screen and the current selections; startup waits without a
user timeout. The configurator shares the frontend task. Removing that task while
held saves its draft and ends the native wait on SDL's quit event; relaunch restores
the same session's draft. A start needing no configuration clears an abandoned
draft. A retained configurator moves above a new frontend without destroying it.
The SDK activity factory redirects duplicate HOME/standard-task entries
before a second SDL host can initialise. Storage failures require restoring access or explicitly choosing
another mode. Failed resource installation presents Retry; partial resources are
verified and repaired without replacing user games, settings or themes.

The typed path keeps its text and focus when the screen re-renders. D-pad Center
opens the device's text-entry IME; character entry uses that IME or a keyboard.
The TV smoke drives D-pad focus/IME opening and keyboard events for the path;
it does not claim character-by-character navigation of every TV keyboard layout.

CI caches the Gradle wrapper and dependency inputs separately from native
installs. Exact Gradle cache hits resolve offline. Dispatch
`clean_gradle_cache=true` for the cold Gradle positive control, or
`clean_cache=true` for fully cold downloads, native installs and Gradle.

The host uses the pinned wrapper/toolchain in `gradle.properties` and
`app/build.gradle.kts`. CI builds Linux, both Android ABIs and minified release,
then drives real configurator/permission screens on API 31, API 34 and Android TV
API 36 x86_64. API 34 runs last on its own runner, after the API 31 and TV legs pass. After
same-commit Linux success and all Android checks, CI uploads and validates the
source artefact on both dry-run and publication paths. Only an eligible
`publish: true` dispatch then uploads the exact smoked debug APK; every other
normal run exercises all gates and release packaging without uploading an APK
or calling release APIs. No intermediary APK is uploaded. Dispatch with
`rebuild_run` and `rebuild_attempt` rebuilds both ABIs from an extracted source artefact without checkout or dependency caches; rebuild APKs
remain on that runner. `failure` controls are dry-run only and forbidden on main.

Game launching uses the existing Android find rules and Intent variables in
`INSTALL.md`. The transport token determines the value in either storage mode:

| Token | Intent value | Recipient access |
| --- | --- | --- |
| `%ROM%` | Absolute filesystem path | The emulator needs its own filesystem permission. Another app generally cannot read the frontend's app-owned `Android/data` directory; use `%ROMPROVIDER%` for app-owned games. |
| `%ROMSAF%` | External-storage document URI on the verified current-user volume | A held persisted tree covering this file permits an exact read grant. URI extras retain their string type and carry the grant through `ClipData`. Without a held tree the emulator needs its own SAF access. App-owned `Android/data` paths are refused with the frontend's launch-error popup. |
| `%ROMPROVIDER%` | ES-DE Plus content URI in Intent data | The selected file receives a temporary read-only grant in both modes. No emulator storage permission is needed to read that file. |

Rules with data and no explicit `%MIMETYPE%` use `application/octet-stream`, as
`INSTALL.md` specifies. Explicit MIME types override that default; data and type
are set together. Rules without data or an explicit MIME type carry no type.

The provider exposes only the configured ROM directory in direct mode or the
app-owned ROM directory in scoped mode. It refuses directories, traversal,
symlink escapes and writes, and checks containment each time a file is opened.
Its URI retains a root-identity segment and separate relative path segments,
ending in the file name. Queries return the requested display name and size
columns, ignoring unknown columns for FileProvider compatibility. Provider and
launch access checks only read; configuration still verifies read/write access.
The grant covers one file: siblings such as a `.bin` beside a `.cue` receive no
access. A grant from a previous ROM-directory selection cannot expose a file
with the same relative name in a new selection. Multi-file games need emulator-side access through `%ROMSAF%` or a
filesystem path. A successful activity launch cannot confirm whether the
recipient subsequently reads or loads the game.

Typed-path configuration creates no tree grant. All-files access grants the
frontend filesystem access; it does not give an emulator a SAF or filesystem
permission. A revoked tree or unavailable selected volume must be restored or
explicitly reconfigured. The frontend never widens a grant to make a launch work.

Explicit activities, including `.RelativeActivity` names, stay within the
configured package. Package-only rules use the package's phone launcher then
Leanback launcher, with Leanback preferred on TV. Missing, disabled, unexported
or permission-protected targets produce the existing error popup. Returning
from an emulator resumes the frontend. Other-screen launching remains deferred.

Build-time package visibility includes every emulator package in the bundled
Android find rules and both phone and Leanback launcher signatures, without
`QUERY_ALL_PACKAGES`. Custom emulator packages outside those rules are visible
only when they match a launcher signature. The Android-apps importer deduplicates
components and uses sanitised labels as filenames, preserving Unicode. Only
colliding labels receive a short deterministic component suffix. Icons are
always staged; its banner/logo option controls additional artwork only.

`RetroArchCoreQueryExperimental` remains opt-in and defaults off. The query
registers its reply receiver before sending, serializes queries and waits at
most one second including lock acquisition, then removes the receiver.
Installed/absent/timeout/unknown are `1`/`0`/`-1`/`-2`. Only a valid timely core
list can report absence. Core lists contain bounded file names ending in
`_libretro_android.so` or `_libretro.so`, matched against the requested file name.
On Android 14+, a reported sender different from the queried package reports
unknown; when the platform does not report a sender, content determines the
result. Malformed replies and query failures report unknown and allow launching.
The public reply carries no request ID; after a failed query, absence in a later
reply is ambiguous and reports unknown for the rest of that frontend process.
An installed-core reply can still confirm presence.
Stable RetroArch releases through
v1.22.2 do not answer this broadcast: the check times out and launching proceeds.
CI verifies this with the official pinned v1.22.2 release, downloaded and
SHA-256 checked in the runner, installed separately and never uploaded. This
release APK declares Android `versionName` `1.22.2_GIT`, verified exactly in CI.
When the emulator presents Play Protect's older-Android-target warning, CI uses
the visible installation confirmation for this pinned APK. Package verification
stays enabled and the APK is not modified.
Under D-010 am. 1, the pinned stable RetroArch exact-ROM receipt gates on the
API 31 and API 34 phone images. It still runs on TV as a clearly labelled
non-gating diagnostic, with outcome, live logs and backtrace capability gaps
in the evidence and CI summary. Frontend launch, stub-recipient, provider,
core-query and host lifecycle checks stay gating on every image; no product
assertion is retried.

The network smoke opens the real theme downloader, clones the canonical HTTPS
themes list with the bundled CA bundle, downloads and selects one live theme,
and submits a real ScreenScraper HTTPS search without an account. A result or
service-level reply proves scraper reachability. API 34 gates these checks;
API 31 and TV record exhausted remote failures as non-gating diagnostics.
Each remote operation has at most three attempts with 5 seconds between attempts:
300 seconds per clone and 90 seconds per scraper request, plus UI, health-check
and evidence-capture time. During a request the same process must remain alive,
focused and free of frontend ANRs. Permission, TLS, UI, startup and frontend
failures always fail the leg and are never retried. The INTERNET grant is checked
before each attempt: a resolve diagnostic alone cannot distinguish a missing grant.
An SDL destruction-start log from the current PID also fails immediately, even
when the process and focus still appear live before an ANR.

A deadline qualifies as a remote stall only with fresh start proof: the initial
list-clone log, the new theme's clone target (verified absent before submission),
or the scraper-search start log. An existing-list refresh needs a captured
`git_remote_fetch` worker frame because its target already existed. A single
unmapped F12 key must then produce a fresh `Window::logInput` acknowledgement
within 10 seconds. Missing start/liveness proof is a hard failure. Stall evidence
includes app-owned SIGQUIT all-thread traces (including native frames), app
file-descriptor socket inodes and shell TCP/UDP tables, collected before
cancellation. A fast `debuggerd` snapshot is preferred when `adb root` is
available, with privilege dropped afterward. Otherwise `adb bugreport` retrieves
the app-owned SIGQUIT traces even on production images;
only the matching app/PID trace text is retained, and the temporary raw report
is deleted. No root or extra package is required. Diagnostic collection has a
two-minute budget within the whole-network budget.
Cleanup preserves live logs/window/fds without starting another whole-device
bugreport after an earlier diagnostic failure.
Each operation/attempt has separate evidence names, such as
`network-fixed-theme-download-attempt2-stalled-request-stacks.txt`. Failures are
captured while the process is still live, before cleanup force-stops it.

The total request-deadline/backoff allowance is at most 3,920 seconds (65m20s),
including both possible three-attempt list refreshes during theme recovery.
API 34 adds one 300-second and one 90-second negative probe: 4,310 seconds
(71m50s). The whole network phase also has a 90-minute wall-time budget covering
UI actions, health checks and diagnostics; exceeding it is hard, never remote.
Failure capture and state restoration have separate 60-second and five-minute
budgets (96 minutes including those reserves). The normal smoke also exercises
the real F12 acknowledgement and native/socket collector on a healthy frontend.

The downloader cannot cancel an active clone through its UI. On a healthy remote
deadline the harness captures evidence, rechecks health, stops that healthy
process and removes only the incomplete clone whose destination it verified
absent before the attempt. It then starts the frontend once and issues the next
request through the UI. Successful lists/downloads are preserved. A failed
startup during recovery fails the leg, including an SDL lifecycle stall.
The scraper uses the same retry policy; the independent scraper probe still runs
after an exhausted non-gating theme failure.

CI runs six gating smoke phases, each in a distinct cold AVD: `core`
(configurator, storage, held destruction, process death, launch/importer and
RetroArch), `lifecycle` (debug/minified stall and restart probes), `integration`
(update continuity on API 31/34 and network checks), `pdf-direct`,
`pdf-scoped` (including minified PDF/Unicode), and `assets` (four forced asset-path
relaunches plus predictive-back cancellation on API 34). A stopped frontend's
asset relaunch waits for a resumed, focused entry before using the existing
restart helper; a back preview never starts another native main. Predictive
back is absent on API 31 and edge gestures are not a TV navigation mode.
The same built APK is installed
in each fresh guest; configuration and grants are established through the UI.
The default `smoke.py APK` command runs core only. For another phase, pass
`--phase PHASE`; every phase is required for the complete CI regression suite.
`smoke_session.py PHASE -- COMMAND` preserves the command's exit status,
verifies a clean guest and distinct boot identity, and records read-only QEMU
RSS, host available memory and wrapped-ADB command counts/durations. Each
phase's evidence is uploaded before the next AVD starts; publication still
requires every phase and all existing D-020 gates.

For a local API 34 network smoke, start a fresh AVD and use a full-history checkout at the commit being tested.
Follow the [workflow's dependency, emulator and fixture preparation](../.github/workflows/build-android.yml),
including PDF fixtures; set `RUNNER_TEMP` to a temporary directory outside the
checkout for throwaway signing material. The network/signing sequence, from the
repository root, is:

```sh
esde_smoke_code=$(python3 android/test_signing.py version | python3 -c 'import json, sys; print(json.load(sys.stdin)["version_code"])')
android/gradlew -p android --no-daemon assembleDebug assembleRelease
mkdir -p android/.deps/update
android/gradlew -p android --no-daemon -Pesde.versionCode=$((esde_smoke_code - 1)) :app:assembleDebug
cp android/app/build/outputs/apk/debug/app-debug.apk android/.deps/update/lower-unsigned.apk
android/gradlew -p android --no-daemon :app:assembleDebug
python3 android/network-control.py
python3 android/test_signing.py fixtures
python3 android/smoke_session.py integration -- python3 android/smoke.py android/app/build/outputs/apk/debug/app-debug.apk --phase integration
```

The signing fixture re-signs both smoke variants and the control with the same
in-run throwaway key. Do not install a control over a differently signed frontend.
The control command requires the same SDK/JDK/Gradle setup as the normal build
and `ANDROID_HOME` with build-tools 36.0.0. It assembles a no-INTERNET control in
an isolated temporary copy using the built native inputs and explicitly passes
the original commit's `esde.versionCode` and `esde.versionName` to Gradle. It never
uses parent history from the temporary source directory. The original manifest
and normal APK are never edited. The destination is pre-cleaned and the validated
control is published atomically. Its full compiled manifest must equal the
normal APK's except for the single INTERNET declaration; every other element,
attribute and typed value is checked. The control must fail each real network check
with one resolve error, without retries or a non-gating exemption. It remains
runner-local and is never uploaded. CI runs this build before the API 34 smoke.
`python3 android/network_smoke.py` exercises deadline/classification controls
with a virtual clock; `python3 android/network-control.py --self-test` kills a
fixture build with SIGKILL and checks original-file hashes. The smoke runs both
controls and writes their results alongside network logs/screenshots in
`android/evidence/`, including normal manifest/APK hashes before and after the
real control build.

The `stub-emulator` module is a separate-UID, debug-only CI recipient written
for ES-DE Plus; it is never included in the frontend APK or a release variant.
Its observations verify transport reads and failures, not real game emulation.
Real game loads in third-party SAF/provider emulators remain device evidence
to collect after the distribution work in PR #6.

PDF manuals use the platform [PdfRenderer](https://developer.android.com/reference/android/graphics/pdf/PdfRenderer)
API-21 constructor and display render mode through ES-DE-Plus's MIT Android
converter. Place manuals in the normal media directory's `<system>/manuals/`
with the game's filename, as upstream specifies. Readable local filesystem paths
work in either storage mode, including spaces and supplementary Unicode characters;
`content://` manuals and password-protected documents are unsupported. The
existing viewer supports paging, first/last, zoom, pan, closing and reopening.
Malformed, unavailable and unsupported documents or failed rasters show the
existing localized PDF error and return to the frontend; a failed later page
closes the manual instead of retaining an old image.

Each call opens and closes a fresh renderer and its owned descriptor, with
open/render/close serialized. Rasters are BGRA, top-down, on opaque white and
limited to 4096 pixels per side and 32 MiB each. The inherited viewer retains
visited page pixels until close: total cache memory grows with pages visited
and has no eviction policy. The renderer runs in the frontend process, per
D-008. A native platform renderer fault or hang can therefore crash or hang the
frontend; catchable Java failures recover, but process isolation is not part of
PR-D. Only use trusted manuals where that risk is unacceptable.

The reconciled Android inventory is [DEPENDENCY-LICENSES.md](DEPENDENCY-LICENSES.md).
Upstream's GPL converter/Poppler and standalone Poppler-only codecs are excluded
from every Android variant. libgit2 retains its GPL linking exception; LGPL
runtime libraries stay shared. The platform renderer adds no application dependency. CI generates PDF fixtures without a third-party PDF library and checks
native input/licence closure, JNI contracts and viewer behaviour on all three images.
