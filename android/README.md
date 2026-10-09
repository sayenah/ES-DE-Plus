<!-- SPDX-License-Identifier: MIT; ES-DE-Plus — written for ES-DE-Plus. -->
# ES-DE Plus Android host

On first launch choose a storage mode before granting permissions. Application
settings, collections and logs stay in the current user's app-specific external
`ES-DE-Plus` directory. Official ES-DE application data is never adopted or migrated.

- **App-owned storage (default):** ROMs live in the app-specific external `ROMs`
  directory. The configurator shows its exact path and how to populate it: install
  Android platform tools on a computer, enable USB debugging, authorize that
  computer, then use `adb push your-ROM-folder/. <displayed-ROM-path>/`. Organize
  games into system folders such as `nes`. Uninstalling removes these games.
  SAF import is deferred.
- **Direct filesystem compatibility (explicit choice):** Android 10 requests
  legacy read/write storage permission. Android 11 and later open the app's
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

The host uses the pinned wrapper/toolchain in `gradle.properties` and
`app/build.gradle.kts`. CI builds Linux, both Android ABIs and minified release,
then drives real configurator/permission screens on API 29, API 34 and Android TV
API 36 x86_64. Only logs, screenshots and audits are uploaded. APK distribution
remains parked under the identity/licensing gates recorded in `docs/handoff.md`.

Game launching uses the existing Android find rules and Intent variables in
`INSTALL.md`. The transport token determines the value in either storage mode:

| Token | Intent value | Recipient access |
| --- | --- | --- |
| `%ROM%` | Absolute filesystem path | The emulator needs its own filesystem permission. On Android 11+ another app generally cannot read the frontend's app-owned `Android/data` directory; use `%ROMPROVIDER%` for app-owned games. |
| `%ROMSAF%` | External-storage document URI on the verified current-user volume | A held persisted tree covering this file permits an exact read grant. URI extras retain their string type and carry the grant through `ClipData`. Without a held tree the emulator needs its own SAF access. App-owned `Android/data` paths are refused with the frontend's launch-error popup. |
| `%ROMPROVIDER%` | ES-DE Plus content URI in Intent data | The selected file receives a temporary read-only grant in both modes. No emulator storage permission is needed to read that file. |

The provider exposes only the configured ROM directory in direct mode or the
app-owned ROM directory in scoped mode. It refuses directories, traversal,
symlink escapes and writes, and checks containment each time a file is opened.
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
components and creates deterministic filenames with a component hash. Icons are
always staged; its banner/logo option controls additional artwork only.

`RetroArchCoreQueryExperimental` remains opt-in and defaults off. The query
registers its reply receiver before sending, serializes queries and waits at
most one second including lock acquisition, then removes the receiver.
Installed/absent/timeout/unknown are `1`/`0`/`-1`/`-2`. Only a valid timely core
list can report absence; Android 14+ also requires the broadcasting package's
platform-reported identity. Missing identity, malformed replies and query
failures report unknown and allow launching. Stable RetroArch releases through
v1.22.2 do not answer this broadcast: the check times out and launching proceeds.
CI verifies this with the official pinned v1.22.2 release, downloaded and
SHA-256 checked in the runner, installed separately and never uploaded.

The `stub-emulator` module is a separate-UID, debug-only CI recipient written
for ES-DE Plus; it is never included in the frontend APK or a release variant.
Its observations verify transport reads and failures, not real game emulation.
Real game loads in third-party SAF/provider emulators remain device evidence
to collect when an APK can be distributed under the pending licensing ruling.
