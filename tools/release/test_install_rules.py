#!/usr/bin/env python3
"""Host test for installer/kz2.iss rules that a compile does not catch (adapted from Project Helghast, the Killzone 3
PC port, same author, MIT: KZ3 3068397 test_install_dir_rule.py, b1a6262 / 3d692df test_install_dump_page.py).
Runs without game data and without Inno Setup.

    python3 tools/release/test_install_rules.py

Cases:
  - TimeStampsInUTC=yes: the payload's file times are converted to the player's time zone (Inno's default keeps the
    build machine's local times, which put a UTC-built release hours in the future west of UTC).
  - ArchiveProblem: the dump page takes USRDIR\\data_ps3.psarc or its FAT32 parts .66600, .66601, ... and names the
    missing file; a transcription of the Pascal agrees with firstrun_check.split_parts on the folder-pick cases (one
    file, all parts, a gap, no first part, the first part only, nothing, an unrelated suffix).
  - WritePaths: the wizard's folders go to kz2-install.ini [paths] (dump, update, eboot) from [Code] at ssPostInstall,
    whether or not "Build now" is ticked; never an [INI] entry (Inno's setup log prints [INI] values).
Exit 0 = PASS, 1 = FAIL.
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import firstrun_check as fc  # noqa: E402

bad = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        bad.append(msg)


def find_iss():
    for rel in (("installer", "kz2.iss"),):
        p = os.path.join(ROOT, *rel)
        if os.path.isfile(p):
            return p
    return ""


ISS = find_iss()
t = open(ISS, encoding="utf-8").read() if ISS else ""
check(bool(t), "installer/kz2.iss found")


def func(name):
    """The text of one [Code] function or procedure: from its header to the first 'end;' at the start of a line."""
    m = re.search(r"^(function|procedure) " + re.escape(name) + r"\b.*?^end;", t, re.M | re.S)
    return m.group(0) if m else ""


def section(name):
    m = re.search(r"^\[" + re.escape(name) + r"\]\s*$(.*?)(?=^\[[A-Za-z]+\]\s*$)", t, re.M | re.S)
    return m.group(1) if m else ""


# file times
setup = section("Setup")
check(re.search(r"^TimeStampsInUTC=yes\s*$", setup, re.M) is not None,
      "TimeStampsInUTC=yes in [Setup] (file times converted to the player's time zone, not future-dated)")

# split disc archive on the dump page
f = func("ArchiveProblem")
check("'data_ps3.psarc'" in f and "66600" in f and "FileExists(Usr + 'data_ps3.psarc.' + IntToStr(N))" in f
      and "66601 to 66640" in f and "data_ps3.psarc.66600 is missing" in f and "data_ps3.psarc is missing" in f,
      "ArchiveProblem takes the file or consecutive parts from .66600 and names the missing file")
nb = func("NextButtonClick")
check("ArchiveProblem(D + 'PS3_GAME\\USRDIR\\')" in nb, "the dump page asks ArchiveProblem")
check("FileExists(D + 'PS3_GAME\\USRDIR\\data_ps3.psarc')" not in nb,
      "no single-file-only archive check is left on the dump page")


def archive_problem(usr):
    """ArchiveProblem transcribed: -> the name of the missing file, '' when the archive is there."""
    ex = lambda n: os.path.isfile(os.path.join(usr, "data_ps3.psarc" + n))  # noqa: E731
    if ex(""):
        return ""
    n = 66600
    while ex("." + str(n)):
        n += 1
    if n > 66600:
        return "data_ps3.psarc." + str(n) if any(ex("." + str(k)) for k in range(n + 1, n + 41)) else ""
    if any(ex("." + str(k)) for k in range(66601, 66641)):
        return "data_ps3.psarc.66600"
    return "data_ps3.psarc"


with tempfile.TemporaryDirectory() as tmp:
    cases = {"single": [""], "all": [".66600", ".66601", ".66602"], "gap": [".66600", ".66601", ".66603"],
             "no first": [".66601", ".66602"], "first only": [".66600"], "none": [], "other": [".bak"]}
    want = {"single": "", "all": "", "gap": "data_ps3.psarc.66602", "no first": "data_ps3.psarc.66600",
            "first only": "", "none": "data_ps3.psarc", "other": "data_ps3.psarc"}
    for name, sufs in cases.items():
        usr = os.path.join(tmp, name.replace(" ", "_"))
        os.makedirs(usr)
        for s in sufs:
            open(os.path.join(usr, "data_ps3.psarc" + s), "wb").write(b"x")
        parts, missing = fc.split_parts(os.path.join(usr, "data_ps3.psarc"))
        check(archive_problem(usr) == missing == want[name],
              f"ArchiveProblem and firstrun_check.split_parts agree: {name} ({missing!r})")

# the wizard's folders, given once
f = func("WritePaths")
check(all(("SetIniString('paths', '%s'" % k) in f for k in ("dump", "update", "eboot")) and "kz2-install.ini" in f
      and "DumpDir" in f and "UpdateDir" in f and "EbootFile" in f,
      "WritePaths writes the wizard's folders to kz2-install.ini [paths]")
check("(DumpDir = '') or (UpdateDir = '') then Exit" in f, "WritePaths writes nothing without a dump and an update")
f = func("CurStepChanged")
line = next((ln for ln in f.splitlines() if "WritePaths" in ln), "")
check("CurStep = ssPostInstall" in line and "buildnow" not in line,
      "WritePaths runs at ssPostInstall whether or not buildnow is ticked")
check(f.find("RunBuild") < f.find("WritePaths"), "WritePaths runs after RunBuild (the RPCS3 lookup fills the folders)")
check('Section: "paths"' not in section("INI"), "no [INI] entry for [paths] (the setup log would show it)")

print("test_install_rules:", "PASS" if not bad else f"FAIL ({len(bad)})")
sys.exit(1 if bad else 0)
