# tools/

Index of the scripts and folders in this directory (layout adapted from Project Helghast, the Killzone 3 PC port).
Build and test details are in [docs/BUILDING.md](../docs/BUILDING.md).

## Entry points

| Script | What it does |
|---|---|
| `lift.sh` | Lifts the PPU code of the player's own EBOOT to C (static recompilation) with the patched ps3recomp. |
| `build-kz2.sh` | Configures and builds the Windows exe (`kz2.exe`) with the MinGW-w64 cross toolchain, one build at a time. |
| `ps3recomp-patched.sh` | Applies the project's patches (`port/patches`) to a copy of the pinned ps3recomp checkout. |
| `sandbox.sh` | Runs a command with the game and the repository read-only; only `work/` and `build/` are writable; no network. |
| `proton-test.sh`, `proton-inner.sh` | Run a Windows program under Proton on Linux, hidden and muted (tests on Linux). |
| `safe_rm.sh` | Deletes files inside the repository only. |
| `host-tests.txt` | The host tests CI runs: no game data, no network. |

## Folders

| Folder | Contents |
|---|---|
| `release/` | Installer, portable zip and first-run build: payload assembly, toolchain fetch (`toolchain.json`, with the licence texts it pins in `licence-texts/`), game-file checks, the launcher's logic, the version, the project page generator (`website.py`), the CI host-test runner (`ci_host_tests.sh`) and their host tests. |
| `spu/` | SPU lift (`lift_spu.sh`, `lift_spu.py`, `gen_spu_register.py`), version tables and the SPU host tests. |
| `runtime/` | `ffmpeg-lgpl-win.nix` (the LGPL FFmpeg decoder DLLs) and `pso_template.py` (reads and merges the pipeline template). |
| `assets/` | `profile_edit.py` (reads and edits the profile save) and its host test. |

Single-file helpers: `disc_info.py` (disc folder summary), `psarc.py` (archive list and extract), `elf_info.py`
(EBOOT inspection), `rtti_dump.py` (the engine's class descriptors from the EBOOT), `core.py` (reads `.core` files with
that schema) and its host test `test_core158.py`.

Comments may cite internal numbering (patch numbers, plan items) from the development notes; they are labels, not links.
