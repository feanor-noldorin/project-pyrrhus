#!/usr/bin/env python3
"""Host test for tools/assets/profile_edit.py: synthetic bytes only (no saves, no game data)."""
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "assets" / "profile_edit.py"
sys.path.insert(0, str(TOOL.parent))
import profile_edit as pe  # noqa: E402

fails = 0


def check(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails += 1


def synth():
    d = bytearray(pe.SIZE)
    struct.pack_into(">I", d, 0, pe.VERSION_WORD)
    struct.pack_into(">f", d, pe.VOL_MUSIC, 0.25)
    d[pe.HINTS] = 1
    d[pe.NAME:pe.NAME + 4] = b"Test"
    struct.pack_into(">3I", d, pe.LEVEL0 + 3 * pe.LEVEL_STRIDE + 2 * pe.NODE_STRIDE, 0x2, 5, 321)  # level 3, node 3
    b = pe.SETUP0
    d[b:b + 5] = b"SETUP"
    d[b + 0x31:b + 0x35] = b"abcd"
    d[b + 0x173] = 1
    d[pe.GLOBALS:pe.GLOBALS + 4] = b"flag"
    struct.pack_into(">f", d, pe.GLOBALS + 28, 1.5)
    return d


def run(*args, env=None):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


# offsets against object offsets from the traced accessors (file = object - 0x24)
check(pe.VOL_MUSIC == 0x1C and pe.LEVEL0 == 0xB88 and pe.GLOBALS == 0x3A64 and pe.SETUP0 == 0x158, "offset anchors")
check(pe.SETUP0 + pe.SETUP_STRIDE * pe.SETUP_N <= pe.HUD, "setup slots end before the HUD byte")
check(pe.LEVEL0 + pe.NLEVELS * pe.LEVEL_STRIDE <= pe.SPSTAT, "level records end before the SP stats")
check(pe.NAMETAB + 32 * 128 == pe.GLOBALS, "name table ends where the globals start")
check(pe.GLOBALS + 32 * pe.GLOBALS_N <= pe.TAIL, "globals end before the tail")
with tempfile.TemporaryDirectory(dir=ROOT / "work") as t:
    t = Path(t)
    env = dict(os.environ, KZ2_WORK_DIR=str(t))
    src = t / "in" / "PROFILE.DAT"
    src.parent.mkdir()
    src.write_bytes(bytes(synth()))
    r = run("show", str(src))
    check(r.returncode == 0 and "music 0.250" in r.stdout and "'Test'" in r.stdout, "show prints settings")
    check("level  3: 1 nodes [3]" in r.stdout and "321 s" in r.stdout, "show prints the node and its best time")
    check("'SETUP'" in r.stdout and "game globals  1 set" in r.stdout, "show prints setup and global")
    out = t / "out" / "PROFILE.DAT"
    r = run("edit", str(src), "--out", str(out), "--complete-levels", "1-2", "--difficulty-bits", "0xC", "--music", "0.75",
            "--hints", "0", "--clear-setups", env=env)
    check(r.returncode == 0 and out.exists(), "edit writes a file below work/")
    o = out.read_bytes()
    check(len(o) == pe.SIZE and struct.unpack_from(">I", o, 0)[0] == pe.VERSION_WORD, "size and version word kept")
    check(pe.node(o, 1, 1)[0] == 0xC and pe.node(o, 2, 8)[0] == 0xC and pe.node(o, 2, 7)[0] == 0, "known nodes completed only")
    check(pe.node(o, 3, 3) == (2, 5, 321), "other levels untouched")
    check(abs(struct.unpack_from(">f", o, pe.VOL_MUSIC)[0] - 0.75) < 1e-6 and o[pe.HINTS] == 0, "settings edited")
    check(o[pe.SETUP0:pe.SETUP0 + 5] == bytes(5), "setups cleared")
    check(src.read_bytes() == bytes(synth()), "source unchanged")
    r = run("edit", str(src), "--out", str(src), env=env)
    check(r.returncode != 0, "refuses to overwrite the source")
    r = run("edit", str(src), "--out", "/tmp/x_profile", env=env)
    check(r.returncode != 0, "refuses output outside work/")
    bad = t / "bad" / "PROFILE.DAT"
    bad.parent.mkdir()
    bad.write_bytes(bytes(synth())[:-4])
    check(run("show", str(bad)).returncode != 0, "wrong size rejected like the game's validator")
    bad.write_bytes(b"\0" * pe.SIZE)
    check(run("show", str(bad)).returncode != 0, "wrong version word rejected")
    out2 = t / "out2" / "PROFILE.DAT"
    r = run("edit", str(src), "--out", str(out2), "--god", "2", "--inf-ammo", "1", env=env)
    d2 = out2.read_bytes() if out2.exists() else b""
    check(r.returncode == 0 and d2[0x30:0x34] == b"\0\0\0\x02" and d2[0xA20] == 1 and d2[0xA1F] == 0, "edit --god 2 --inf-ammo 1 writes file 0x30 / 0xA20 only")
    check(pe.GODMODE == 0x30 and pe.INFAMMO == 0xA20 and sum(a != b for a, b in zip(d2, bytes(synth()))) == 2, "god/inf-ammo offsets and nothing else changed")
    r = run("edit", str(src), "--out", str(t / "o3" / "PROFILE.DAT"), "--god", "3", env=env)
    check(r.returncode != 0, "--god 3 rejected")
    r = run("stage", str(src))
    check(r.returncode == 2 and "savedata" in r.stderr, "stage is a stub that says what it needs")
print("test_profile_edit: " + ("PASS" if not fails else f"{fails} FAIL"))
sys.exit(1 if fails else 0)
