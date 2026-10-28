#!/usr/bin/env python3
"""First-run SPU lift: the same scripts as tools/spu/lift_spu.sh (lift_spu.py, then gen_spu_register.py), run on the
EBOOT the player decrypted. Part of the installer flow (firstrun.py's spu-lift step); a developer uses lift_spu.sh.

    spu_step.py --ps3recomp DIR --out DIR --eboot EBOOT.elf [-j N]

The EBOOT version comes from KZ2_EBOOT_VER (129 or 101; firstrun.py sets it from the tree, as tools/spu/kz2ver.py
reads it). kz2ver.py names its EBOOT by a fixed path (work/bin/EBOOT-129.elf, or the disc EBOOT for 101) that a
player's machine does not have, so --eboot replaces kz2ver.EBOOT before the lift; nothing else of the scripts changes.
The scripts are found beside this folder: ../spu (kz2-setup/spu in the payload, tools/spu in the source tree); the
census tables are <root>/re/wws_jobs_v<VER>.tsv (kz2ver.TSV). Output: <out>/lift/<image>/spu_recomp.{c,h},
<out>/lift/spu_workloads.c, <out>/eboot_ver, which port/kz2's CMake picks up as -DSPU_DIR=<out>/lift.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPU = os.path.join(os.path.dirname(HERE), "spu")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ps3recomp", required=True, help="the patched toolkit (tools/spu_lifter.py inside)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--eboot", required=True, help="the decrypted EBOOT.elf")
    ap.add_argument("-j", type=int, default=os.cpu_count() or 1)
    a = ap.parse_args(argv)
    if not os.path.isfile(a.eboot):
        print(f"spu_step: no EBOOT at {a.eboot}", file=sys.stderr)
        return 3
    if not os.path.isfile(os.path.join(a.ps3recomp, "tools", "spu_lifter.py")):
        print(f"spu_step: no spu_lifter.py in {a.ps3recomp}", file=sys.stderr)
        return 3
    sys.path.insert(0, SPU)
    import kz2ver                                   # exits itself unless KZ2_EBOOT_VER is 129 or 101
    kz2ver.EBOOT = os.path.abspath(a.eboot)
    if not os.path.isfile(kz2ver.TSV):
        print(f"spu_step: no image table {kz2ver.TSV}", file=sys.stderr)
        return 3
    out = os.path.abspath(a.out)
    import lift_spu
    import gen_spu_register
    for mod, args in ((lift_spu, ["--ps3recomp", a.ps3recomp, "--out", out, "-j", str(a.j)]),
                      (gen_spu_register, ["--lift", out])):
        sys.argv = [mod.__file__] + args
        rc = mod.main()
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
