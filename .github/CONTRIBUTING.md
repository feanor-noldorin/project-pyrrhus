# Contributing

Contributions are welcome: bug reports, fixes, feedback and questions, and ideas for features. Use the issue templates
(bug report, performance report, feature request, feedback or question) or open a pull request. Pull requests and
feature requests are welcome. A fix pull request is read by the maintainer; run the host tests and
`tools/ps3recomp-patched.sh` yourself first (CI runs the same host tests, the patch series and a secret scan on every pull request). General recompiler fixes go
upstream to ps3recomp (see below). Known problems are listed in [docs/KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md).

## Before you start

- **Open an issue first for big work** (a new feature, a refactor, a change to many files), so the idea can be talked
  through before you spend the time. Small fixes can go straight to a pull request.
- **No promise of review time or of merging.** This is a one-person project; a change may wait, be changed, or be
  declined. A decline is not a judgement of the work.
- **Never post game files, keys or decrypted binaries**, in an issue, a pull request, a log or a screenshot.
- **MIT-compatible contributions only.** What you submit is licensed under the project's [MIT licence](../LICENSE); do
  not submit code you cannot license that way (no GPL code, and nothing copied from RPCS3).
- **Disclose AI help.** If an AI tool wrote or shaped part of a pull request, say so in the pull request. You stay
  responsible for it: read it and test it.

## Ground rules

- **No game material, ever:** no files from the disc or the update, no decrypted or translated game code, no extracted
  assets, saves, keys or firmware, and no links to where they can be downloaded. Numbers, names, structure layouts
  and formulas worked out from the game are fine.
- **No GPL code:** RPCS3 is a reference to read, not code to copy. Write behaviour from your own understanding.
- **Recompiler fixes go upstream:** a fix that is not specific to Killzone 2 belongs in
  [ps3recomp](https://github.com/sp00nznet/ps3recomp). Here it lives as a patch in `port/patches/` until upstream
  takes it. Patches 0001-5004 are shared with [Project Helghast](https://github.com/undecuple/project-helghast).

## Reporting a problem

Use the issue templates. Say which build you ran (commit or release), whether the 1.01 disc or the 1.29 update, your
GPU and driver, Windows or Proton (and which Proton), the chapter or menu, and attach the run's log file and a screenshot
if something looks wrong. Do not attach save files, dumps of game memory or anything else that contains game data.
Remove your user name and folder paths from logs before attaching them. Security problems: see
[SECURITY.md](SECURITY.md), not an issue.

## Making a change

- Build instructions: [docs/BUILDING.md](../docs/BUILDING.md). Port code lives in `port/kz2/`.
- AI coding tools are fine if you disclose them (see "Before you start") and remain responsible for what you submit. Point an AI coding agent at [AGENTS.md](../AGENTS.md) (the same rules, written for agents).
- Changes to ps3recomp: a new numbered patch in `port/patches/` (`git diff` style against the pinned submodule, in the
  number block of its area); `tools/ps3recomp-patched.sh` applies them all and fails on one that does not apply.
- Keep the original function addresses in comments (`// @0x00123abc`) and mark guesses `ASSUMPTION:`. New
  non-original features are marked `ENHANCEMENT:`; anything that changes gameplay stays optional.
- Commits: short, descriptive messages.

## Testing

- **Without the game:** the host tests listed in `tools/host-tests.txt` (each line is a command, run inside the Nix
  shell it names), and `tools/ps3recomp-patched.sh`. A fix should come with a host test that fails without it and passes with it.
- **With the game:** changes that need the game are tested with your own copy under Proton or Windows
  (`tools/proton-test.sh`). Say in the pull request what you ran and what you saw; a screenshot helps.

## Proposing a fix to ps3recomp

If a patch here fixes something general (a lifter bug, a library that behaves differently from the PS3, a runtime
limit), it can go to ps3recomp: open an issue there describing the symptom, the cause and the fix, with a focused test,
and follow the maintainer's lead on how they want the pull request. Keep it free of anything specific to Killzone 2.
