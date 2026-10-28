#!/usr/bin/env python3
"""Test only (VM kit pre-flight, tools/release/vm_kit.sh preflight with KZ2_VMKIT_FAKEBUILD): mark an install's
partial build as finished around a borrowed kz2.exe, so the launcher's "run" path (vfs junction, game variables,
the game start) can be walked without a Windows compiler. Writes build/build-stamp.json the way firstrun.py's stamp
step does (parts, eboot_stat, version) and marks it test_only. Never in the payload.

    python fake_stamp.py <install root>
"""
import json
import os
import sys

root = os.path.abspath(sys.argv[1])
sys.path.insert(0, os.path.join(root, "kz2-setup", "release"))
import firstrun as fr  # noqa: E402
import launch as la  # noqa: E402

paths = la.load_json(os.path.join(root, "build", "paths.json")) or {}
c = la.ctx_for(root, paths)
stamp = {"parts": c.parts(), "version": fr.port_version(root), "eboot_stat": fr.eboot_stat(paths["eboot"]),
         "test_only": "VM kit pre-flight: a borrowed kz2.exe, not built here"}
with open(os.path.join(root, "build", "build-stamp.json"), "w", encoding="utf-8") as f:
    json.dump(stamp, f, indent=1)
print("fake stamp written; launcher decision:", la.decide(root))
