# Changelog

All notable changes for players, newest first, in the style of [Keep a Changelog](https://keepachangelog.com/). The
port is a pre-release (partly playable): see [RELEASE-CRITERIA.md](docs/RELEASE-CRITERIA.md). Versions follow
`vMAJOR.MINOR.PATCH`; every release stays a pre-release until `v1.0.0`.

## [0.1.1] - 2026-10-28 (pre-release)

### Added
- A disc dump copied to a FAT32 drive, where the game archive is split into parts (data_ps3.psarc.66600, .66601, and so on), is accepted as it is by the setup, the first-run check and the game. A missing part is named.
- The first run checks the disc's game archive against the known copy (check A1) and says when it differs.
- The launcher log starts each run with a version line, so a shared log says which version made it.
- A new page, docs/GETTING-FILES.md, shows what the disc dump, the 1.29 update and the EBOOT must contain and what every first-run check means.

### Changed
- The game folders are given once: when the build is started later or a check fails, the first start checks the folders from the setup instead of asking for them again.
- When an upgrade changes the tables the game's code is translated with, the first start translates and builds the game again instead of reusing the old build.
- The help for using an RPCS3 install points to RPCS3's own documentation.

### Fixed
- Installed files carry the right time on PCs in time zones west of UTC (the Americas), so the first build does not loop on files dated in the future ("build.ninja still dirty after 100 tries"). The first run stops with a plain message if it finds such files.

## [0.1.0] - 2026-10-28 (tagged, not released)

The tag v0.1.0 marks the first build of the Windows installer and portable zip. It was never published as a release:
the fixes listed above came first, and the first published release is the next version.
