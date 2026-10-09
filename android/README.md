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
  Accepting another folder releases superseded pending grants; cancel keeps only
  the saved folder's grant. Saving app-owned mode releases the old shared grant.

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
the draft. The SDK activity factory redirects duplicate HOME/standard-task entries
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
