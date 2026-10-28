#!/usr/bin/env python3
"""Host test for tools/release/spu_step.py (the first-run SPU lift), on a synthetic tree in a temp folder: the real
spu_step.py and the real tools/spu/kz2ver.py, with stand-ins for lift_spu.py and gen_spu_register.py that only record
what they were given. No game data, no EBOOT bytes, no toolkit. Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_spu_step.py

Cases: both scripts run, lift first, with --ps3recomp/--out/-j and --lift; kz2ver.EBOOT is the --eboot file (not
work/bin/EBOOT-129.elf), kz2ver.VER follows KZ2_EBOOT_VER (129 and 101), the census table is <root>/re/wws_jobs_v<VER>.tsv;
refused (exit 3, nothing run): missing EBOOT, toolkit without spu_lifter.py, missing image table; a bad
KZ2_EBOOT_VER exits; the same layout under kz2-setup/ (the payload) works; a failing lift stops before the register step.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
FAILS = []

LIFT = '''import json, os, sys
import kz2ver
def main():
    open(os.environ["REC"], "a").write(json.dumps(["lift", sys.argv[1:], kz2ver.EBOOT, kz2ver.VER, len(kz2ver.rows())]) + "\\n")
    return int(os.environ.get("LIFT_RC", "0"))
'''
GEN = '''import json, os, sys
import kz2ver
def main():
    open(os.environ["REC"], "a").write(json.dumps(["gen", sys.argv[1:], kz2ver.EBOOT]) + "\\n")
'''
TSV = "kind\tfile_offset\tsize\treg_name\nelf\t0x10\t4\tA\njob\t0x20\t4\tB\n"


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"  {detail}"[:600]))
    if not cond:
        FAILS.append(what)


def layout(root, base):
    """root/<base>/{release/spu_step.py, spu/...}, root/re/ tables, root/ps3/tools/spu_lifter.py, root/E.elf."""
    for rel, data in ((f"{base}/release/spu_step.py", open(os.path.join(HERE, "spu_step.py")).read()),
                      (f"{base}/spu/kz2ver.py", open(os.path.join(REPO, "tools", "spu", "kz2ver.py")).read()),
                      (f"{base}/spu/lift_spu.py", LIFT), (f"{base}/spu/gen_spu_register.py", GEN),
                      ("re/wws_jobs_v129.tsv", TSV), ("re/wws_jobs_v101.tsv", TSV + "pm\t0x30\t4\tC\n"),
                      ("ps3/tools/spu_lifter.py", "#\n"), ("E.elf", "not an elf\n")):
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(data)


def run(root, base, ver, extra=None, **env):
    rec = os.path.join(root, "rec.jsonl")
    if os.path.exists(rec):
        os.remove(rec)
    e = dict(os.environ, KZ2_EBOOT_VER=ver, REC=rec, **env)
    argv = extra if extra is not None else ["--ps3recomp", os.path.join(root, "ps3"), "--out", os.path.join(root, "out"),
                                             "--eboot", os.path.join(root, "E.elf"), "-j", "3"]
    p = subprocess.run([sys.executable, os.path.join(root, base, "release", "spu_step.py"), *argv],
                       env=e, capture_output=True, text=True, timeout=60)
    lines = [json.loads(l) for l in open(rec).read().splitlines()] if os.path.exists(rec) else []
    return p.returncode, lines, p.stderr + p.stdout


def main():
    tmp = tempfile.mkdtemp(prefix="kz2-spustep-")
    try:
        for base in ("tools", "kz2-setup"):
            root = os.path.join(tmp, base)
            layout(root, base)
            E = os.path.join(root, "E.elf")
            rc, rec, txt = run(root, base, "129")
            ok = rc == 0 and [r[0] for r in rec] == ["lift", "gen"]
            check(ok, f"{base}: lift then register, exit 0", txt)
            if not ok:
                continue
            check(rec[0][1] == ["--ps3recomp", os.path.join(root, "ps3"), "--out", os.path.join(root, "out"), "-j", "3"]
                  and rec[1][1] == ["--lift", os.path.join(root, "out")], f"{base}: arguments of both scripts", rec)
            check(rec[0][2] == E and rec[1][2] == E and rec[0][3] == "129" and rec[0][4] == 2,
                  f"{base}: kz2ver.EBOOT is --eboot, VER 129, 2 census rows", rec)
            rc, rec, txt = run(root, base, "101")
            check(rc == 0 and rec[0][3] == "101" and rec[0][4] == 3 and rec[0][2] == E,
                  f"{base}: KZ2_EBOOT_VER=101 reads the 101 table and still uses --eboot", rec)

        root, base = os.path.join(tmp, "tools"), "tools"
        rc, rec, txt = run(root, base, "129", LIFT_RC="1")
        check(rc == 1 and [r[0] for r in rec] == ["lift"], "a failing lift stops before the register step", (rc, rec))
        rc, rec, txt = run(root, base, "77")
        check(rc != 0 and not rec and "129 or 101" in txt, "a bad KZ2_EBOOT_VER exits before any script", (rc, txt))
        rc, rec, txt = run(root, base, "129", ["--ps3recomp", os.path.join(root, "ps3"), "--out", "o",
                                               "--eboot", os.path.join(root, "nope.elf")])
        check(rc == 3 and not rec and "no EBOOT" in txt, "missing EBOOT: exit 3", (rc, txt))
        rc, rec, txt = run(root, base, "129", ["--ps3recomp", os.path.join(root, "nokit"), "--out", "o",
                                               "--eboot", os.path.join(root, "E.elf")])
        check(rc == 3 and not rec and "spu_lifter.py" in txt, "toolkit without spu_lifter.py: exit 3", (rc, txt))
        os.remove(os.path.join(root, "re", "wws_jobs_v129.tsv"))
        rc, rec, txt = run(root, base, "129")
        check(rc == 3 and not rec and "image table" in txt, "missing image table: exit 3", (rc, txt))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
