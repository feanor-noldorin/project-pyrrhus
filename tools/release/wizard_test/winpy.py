#!/usr/bin/env python3
"""Test stand-in helper for pyshim.c (wizard_test.sh only): run a script on the Linux python with the Windows paths
in its arguments mapped (Z:\\x -> /x, C:\\x -> the prefix's drive_c), then map the Linux paths in the --out file
back to Z:\\ so the wizard shows what a player's Windows would."""
import os, re, runpy, sys

CDRIVE = os.environ.get("KZ2_WT_CDRIVE", "")


def to_unix(a):
    m = re.fullmatch(r'([A-Za-z]):\\(.*)', a)
    if not m:
        return a
    rest = m.group(2).replace("\\", "/")
    return "/" + rest if m.group(1).upper() == "Z" else os.path.join(CDRIVE, rest)


def to_win(p):
    if p.startswith(CDRIVE + "/"):
        return "C:\\" + p[len(CDRIVE) + 1:].replace("/", "\\")
    return "Z:" + p.replace("/", "\\")


def _bridge():
    """KZ2_WT_WINE=<wine binary>: a Windows .exe the script starts (launch.py starting build\\kz2.exe) is run through that
    wine in the same prefix, with Linux paths in its arguments and environment turned back into Z:\\ / C:\\ ones
    (this box has no Windows Python, so the launcher's own interpreter is the Linux one; test-only, never shipped)."""
    wine = os.environ.get("KZ2_WT_WINE")
    if not wine:
        return
    import subprocess
    real = subprocess.call

    def conv(v):
        return to_win(v) if isinstance(v, str) and v.startswith("/") else v

    def call(argv, *a, **kw):
        if isinstance(argv, (list, tuple)) and str(argv[0]).lower().endswith(".exe"):
            env = kw.pop("env", None)
            if env is not None:
                env = {k: (conv(v) if k.startswith(("PS3_", "KZ2_")) else v) for k, v in env.items()}
            kw.pop("creationflags", None)
            cmd = [wine] + [conv(x) for x in argv]
            with open(os.path.join(CDRIVE, "pyshim.log"), "a") as lg:
                lg.write("bridge: " + " ".join(cmd) + "\n")
            return real(cmd, *a, env=env, **kw)
        return real(argv, *a, **kw)
    subprocess.call = call


DONE = ""
if len(sys.argv) > 1 and sys.argv[1].startswith("--done="):
    DONE = sys.argv.pop(1)[len("--done="):]


def main():
    args = [to_unix(a) for a in sys.argv[1:]]
    script, rest = args[0], args[1:]
    out = rest[rest.index("--out") + 1] if "--out" in rest else ""
    sys.argv = [script] + rest
    with open(os.path.join(CDRIVE, "pyshim.log"), "a") as lg:
        lg.write("winpy: " + " ".join(sys.argv) + "\n")
    sys.path.insert(0, os.path.dirname(script))
    _bridge()
    rc = 0
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    if out and os.path.isfile(out):
        raw = open(out, "rb").read()
        bom = raw.startswith(b"\xef\xbb\xbf")
        lines = raw.decode("utf-8-sig").split("\n")
        fixed = []
        for ln in lines:
            k, eq, v = ln.partition("=")
            if eq and k in ("root", "dump", "update", "eboot", "outside") and v.startswith("/"):
                ln = k + "=" + to_win(v.rstrip("\r")) + ("\r" if ln.endswith("\r") else "")
            fixed.append(ln)
        data = "\n".join(fixed).encode("utf-8")
        open(out, "wb").write((b"\xef\xbb\xbf" if bom else b"") + data)
    done = DONE
    if done:
        with open(to_unix(done), "w") as f:
            f.write(str(rc))
    sys.exit(rc)


try:
    main()
except SystemExit:
    raise
except BaseException:
    import traceback
    with open(os.path.join(CDRIVE, "pyshim.log"), "a") as lg:
        traceback.print_exc(file=lg)
    done = DONE
    if done:
        with open(to_unix(done), "w") as f:
            f.write("1")
    sys.exit(1)
