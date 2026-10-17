<!-- SPDX-License-Identifier: MIT -->
<!-- ES-DE-Plus — written for ES-DE-Plus from D-012 amendments 6 and 7. -->
# Theme downloader upstream-sync checklist

For a libgit2 upgrade or an upstream merge touching the downloader:

- Re-run AC-3 (at least 20 clones, three changing updates each, application-view/lower metadata comparisons) and AC-5 (lower config unchanged across updates), including loose and pre-existing packed refs. A metadata mismatch returns under protocol §9; it is never erased by a rerun.
- Review both invariants: the update path never writes `.git/config`; ES-DE-Plus production code never probes case variants or intentionally renames over an existing file under shared `.git`. Retirement remains config-only and clone-only. Recheck the Linux init-key table, clone identity/content checks, and the unlink-to-rename race evidence. Exclusive creation and post-checks do not establish race-freedom or content freshness.
