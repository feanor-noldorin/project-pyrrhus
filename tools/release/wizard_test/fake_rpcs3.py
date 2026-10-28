#!/usr/bin/env python3
"""Fake RPCS3 trees for the wizard walk (wizard_test.sh rpcs3 mode). No game data: PARAM.SFOs from the test helpers
of test_rpcs3_import.py, a real-ELF-magic EBOOT.elf, an encrypted-magic (SCE) EBOOT.BIN, a fake save.

    fake_rpcs3.py OUTDIR      writes OUTDIR/{good,noupdate,wrong,manual}/ (noupdate/update-129 = the fix)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import test_rpcs3_import as t  # noqa: E402

SCE = b"SCE\0" + b"\0" * 28


def main():
    out = Path(sys.argv[1])
    root, disc = t.tree(out / "good", name="rpcs3")          # complete; the disc is outside (asked about)
    (root / "dev_hdd0" / "game" / t.T / "USRDIR" / "EBOOT.BIN").write_bytes(SCE)
    t.add_save(root)
    root2, _ = t.tree(out / "noupdate", name="rpcs3", update=None)   # no 1.29 update installed
    t.add_save(root2)
    u = out / "noupdate" / "update-129"      # what the walk copies into root2's dev_hdd0/game/BCUS98116 to fix it
    t.w(u / "PARAM.SFO", t.sfo(TITLE_ID=t.T, APP_VER="01.29", CATEGORY="GD"))
    t.w(u / "USRDIR" / "EBOOT.BIN", SCE)
    t.w(u / "USRDIR" / "EBOOT.elf", t.ELF + b"update")
    (out / "wrong").mkdir(parents=True, exist_ok=True)
    (out / "wrong" / "readme.txt").write_text("not an RPCS3 folder\n")
    # the manual path: dump, update and an EBOOT.BIN that is still encrypted
    m = out / "manual"
    t.w(m / "dump" / "PS3_GAME" / "PARAM.SFO", t.sfo(TITLE_ID=t.T, VERSION="01.01", APP_VER="01.01"))
    t.w(m / "dump" / "PS3_GAME" / "USRDIR" / "data_ps3.psarc", b"PSAR")
    t.w(m / "update" / "PARAM.SFO", t.sfo(TITLE_ID=t.T, APP_VER="01.29", CATEGORY="GD"))
    t.w(m / "update" / "USRDIR" / "EBOOT.BIN", SCE)
    t.w(m / "update" / "USRDIR" / "added_data_ps3.psarc", b"PSAR")
    t.w(m / "update" / "USRDIR" / "EBOOT.elf", t.ELF + b"update")
    print("ok", out)


main()
