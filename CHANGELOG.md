# Changelog

All notable changes for players, newest first, in the style of [Keep a Changelog](https://keepachangelog.com/). The
port is a pre-release (partly playable): see [RELEASE-CRITERIA.md](docs/RELEASE-CRITERIA.md). Versions follow
`vMAJOR.MINOR.PATCH`; every release stays a pre-release until `v1.0.0`.

## [Unreleased]

### Changed
- A frame waiting on a graphics job from the game's SPU code is resumed as soon as the job writes its result, instead of after a fixed 4 ms sleep. In our tests the time from a button press to the frame being handed to Windows went down by 4 to 5 ms (median), to about 59 ms; the screen's own delay comes on top and was not measured.
- The release notes on GitHub list each change as its own bullet, with the fixes in a list of their own, instead of one long paragraph.

### Fixed
- The first-run log no longer keeps the Windows user name when a path is written in its escaped form, with doubled backslashes (an error message, or a list or JSON of paths). Reported by @feanor-noldorin (#9).
- `bump_version.py` keeps each file's line endings instead of writing Windows line endings when run on Windows. Reported by @feanor-noldorin (#9).
- `tools/ps3recomp-patched.sh` stops before copying anything when git has checked the ps3recomp submodule out with Windows line endings (`core.autocrlf`, on by default in Git for Windows), and names the commands that fix it. Before, the patch series failed part-way through with a "patch does not apply" error. BUILDING.md has a note on cloning on Windows (#9).
- `tools/ps3recomp-patched.sh` finds a working Python 3 itself: `python3`, else `python`, else the Windows launcher `py -3`. On Windows, `python3` is often the Microsoft Store alias, and the script used to stop with exit code 49 after applying every patch. With no working Python, it now stops before copying anything and says what it tried (#9).

## [0.1.2] - 2026-10-28 (pre-release)

### Added
- A decrypted disc image (.iso) can be picked instead of a dump folder ("Browse for ISO file" in the setup, or the path in the console). The first run checks the disc inside it, then copies its game files (about 7 GB) into the install folder once; the ISO itself is only read. An encrypted ISO is refused with "this ISO is encrypted; use a decrypted dump".
- The setup reads the disc's title id and shows what it found under the folder ("Found: BCUS98116 (Killzone 2, US disc)"). Another game is refused by its title id and name. The Killzone Trilogy disc, whose Killzone 2 is the same title id, is named and allowed as untested.
- The game window shows the project's icon in its title bar and taskbar.

### Changed
- Picking the PS3_GAME or PS3_GAME/USRDIR folder of the dump, or the USRDIR folder of the update, works: the setup and the first run use the folder above.
- When the first start asks for the decrypted EBOOT, a folder is accepted too: it looks for EBOOT.elf in it and in its USRDIR folder, and says where it looked when it is not there. The setup's EBOOT page does the same.
- The update must carry the same title id as the disc; the setup and the first-run check say so when it does not.

### Fixed
- The folder hints of the setup and the first-run check offer only Killzone 2 dumps (other games' dumps on a drive are not named) and name up to three `.iso` files in the folder (or one level down on a drive) beside the folder hints. When no more input comes (a closed console), the first-run check stops with its FAIL lines instead of asking again. The same fixes as Project Helghast PR #17.
- Installing into a OneDrive folder is refused, as a precaution taken from a problem reported on Project Helghast: OneDrive synced the build's thousands of files while they were written and locked them. The first-run check also stops when the install or build folder is inside OneDrive (O1), or when a game file is only online in OneDrive (O2, before anything is read, so nothing is downloaded); right-click the game folders and choose "Always keep on this device".
- When the first-run console window is closed with its X, the launcher says so ("its window was closed before it finished; finished steps are kept") instead of showing an error code. It names the first-run log only when the log exists.
- When the setup or the first run stops, the setup's message box, the launcher's dialog and the portable zip's console say why (the same reason the log has). The next start checks your files first and asks again only for the one that was wrong. The setup's EBOOT page refuses the disc's 1.01 EBOOT and names the update's USRDIR folder, where the 1.29 one is; a silent install with /EBOOT= stops with the same text. Adapted from Project Helghast's fix for the same mix-up (its PR #11).
- When a check of your game files fails, the setup's message box, the launcher's dialog and the console say which input failed ("Disc dump", "1.29 update" or "EBOOT"), the path, what is there and what it must hold, and which inputs passed. A disc dump and an update given the wrong way round are named as such, a drive picked instead of a folder gets a pointer to the folders on it that look like the disc or the update, and the disc's PS3_GAME folder given as the update fails its check. Adapted from Project Helghast's fix for the same mix-ups (its PR #14).
- The setup's disc page says what a folder without PS3_GAME holds and where PS3_GAME is when it is one folder down; the update page names the path and the missing files, or says the folder is a disc dump.
- With a decrypted ISO as the disc, the first-run check could not load its ISO reader under the bundled Python, which does not look in the check's own folder; it now does.
- [Getting your files ready](docs/GETTING-FILES.md) lists what each input must contain, says that the update does not hold the disc archive, and warns against picking a drive instead of the dump folder or the .iso file.
- Uninstalling removes the whole install folder: the first-run logs and their earlier copies no longer keep it behind.
- "Verify and rebuild" counts only the files it checked.
- The game window's messages (input and window events) are now handled on every frame tick, the same fix as Project Helghast 0.1.4. In our tests a 3.7-second stretch with no messages handled, during a busy catch-up, is gone.
- The game's disk cache is rebuilt once when the installed build changes, so the first start after an update loads a little slower. This is a precaution taken from Project Helghast 0.1.4, where a cache left by an older build ended a level with error 20000; it has not been seen on Killzone 2.
- Files the game opens to create or append to are now opened the way the console does (the toolkit read three of the open flags with the wrong values). In our tests no visible change yet: the opens seen at start are read-only.
- The game window keeps responding while the game builds its graphics pipelines on the first start of a level, which can take several seconds with an empty shader cache: the window now has its own thread, so Windows no longer marks it as not responding. In our tests the longest stretch without an answer went from 7.9 s to 0.05 s; the first start of a level is still slower than later ones.

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
