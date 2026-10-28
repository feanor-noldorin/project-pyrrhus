#!/usr/bin/env python3
"""Host test: no line of an Inno Setup script (installer/*.iss) starts, after its indent, with "#" and a digit or with
"13#10". Inno's preprocessor (ISPP) reads every line whose first non-blank character is "#" as one of its own
directives, so a Pascal string continuation such as `#13#10 + 'text'` at the start of a line stops the compile
("Unknown preprocessor directive"); a line starting "13#10" is the same split one character later. Put the #13#10 at
the end of the previous line instead. Adapted from Project Helghast (the Killzone 3 PC port, same author, MIT), where
such a line cost a release tag. Runs without game data and without Inno Setup.

    python3 tools/release/test_iss_ispp.py
"""
import glob
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BAD = re.compile(r"^\s*(#\d|13#10)")


def scan_text(text):
    """-> [(line number, line)] of the lines ISPP would take for a directive."""
    return [(n, line) for n, line in enumerate(text.splitlines(), 1) if BAD.match(line)]


def selftest():
    bad = "x := 'a' +\n  #13#10 + 'b';\n13#10 + 'c'\n#10\n"
    good = "#define AppName \"x\"\n#if VER < EncodeVer(6,6,0)\n  x := 'a' + #13#10 +\n    'b'; // #13#10\n#endif\n"
    return [n for n, _ in scan_text(bad)] == [2, 3, 4] and scan_text(good) == []


def main():
    fails = 0
    if not selftest():
        print("FAIL self-test: the pattern does not match the known bad lines")
        fails += 1
    scripts = sorted(glob.glob(os.path.join(ROOT, "installer", "*.iss")))
    if not scripts:
        print("FAIL no installer/*.iss found")
        fails += 1
    for p in scripts:
        with open(p, encoding="utf-8-sig") as f:
            hits = scan_text(f.read())
        for n, line in hits:
            print(f"FAIL {os.path.relpath(p, ROOT)}:{n}: ISPP reads this as a directive: {line.strip()[:100]}")
        fails += len(hits)
        if not hits:
            print(f"ok   {os.path.relpath(p, ROOT)}: no line starts with #<digit> or 13#10")
    print("test_iss_ispp:", "PASS" if not fails else f"FAIL ({fails})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
