#!/usr/bin/env python3
"""The release version: one source of truth for every place that shows it. Standard library only.

    release_version.py [--repo DIR]                       print the version (installer/VERSION)
    release_version.py --check [--tag vX.Y.Z]             VERSION is MAJOR.MINOR.PATCH with no suffix; with --tag the
                                                          release tag is "v" + that version (a tag is never moved)
    release_version.py --stamp-citation --date YYYY-MM-DD  public/CITATION.cff version and date-released (release time)
    release_version.py --rc                               the version as "0,1,0,0" (windres FILEVERSION)

installer/VERSION holds MAJOR.MINOR.PATCH and nothing else. From it:
  - assemble_payload.py: VERSION.txt in the payload (and refuses a --version that differs or carries a suffix);
    the payload's port/kz2/app.rc (kz2.exe's version block and icon) is generated from installer/app.rc.in;
  - installer/kz2.iss: AppVersion read from the payload's VERSION.txt at compile time;
  - build_launcher.sh: the launcher's version block (launcher.rc gets KZ2_VER_* from --rc);
  - version_check.py: compares the installed VERSION.txt with the releases' tags;
  - public/CITATION.cff: --stamp-citation at release time.
Tags are vMAJOR.MINOR.PATCH; every release is a GitHub pre-release until v1.0.0; no suffixes.
Exit 0 = ok, 1 = a check failed, 2 = usage.
"""
import argparse
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
VERSION_FILE = os.path.join("installer", "VERSION")
CITATION = os.path.join("public", "CITATION.cff")
STRICT = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def valid(v):
    """'0.1.0' -> True; '0.1', '0.1.0-rc1', 'v0.1.0', '01.1.0' -> False."""
    return bool(STRICT.fullmatch(v or ""))


def read(repo=REPO):
    """installer/VERSION, or raises ValueError with the reason."""
    p = os.path.join(repo, VERSION_FILE)
    try:
        with open(p, encoding="utf-8") as f:
            v = f.read().strip()
    except OSError as e:
        raise ValueError(f"{VERSION_FILE}: {e}") from e
    if not valid(v):
        raise ValueError(f"{VERSION_FILE} holds {v!r}: expected MAJOR.MINOR.PATCH with no suffix")
    return v


def from_tag(tag):
    """'v0.1.0' -> '0.1.0'; anything else -> None."""
    return tag[1:] if tag.startswith("v") and valid(tag[1:]) else None


def rc_comma(v):
    return ",".join(v.split(".") + ["0"])


def stamp_citation(repo, v, date):
    """Set version and date-released in public/CITATION.cff (added after the title line when missing)."""
    p = os.path.join(repo, CITATION)
    with open(p, encoding="utf-8") as f:
        lines = f.read().splitlines()
    want = {"version": f'version: "{v}"', "date-released": f'date-released: "{date}"'}
    keys = {line.split(":", 1)[0] for line in lines}
    out = []
    for line in lines:
        key = line.split(":", 1)[0]
        out.append(want.get(key, line))
        if key == "title":
            out += [want[k] for k in ("version", "date-released") if k not in keys]
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--rc", action="store_true")
    ap.add_argument("--stamp-citation", action="store_true")
    ap.add_argument("--date", default="")
    a = ap.parse_args(argv)
    try:
        v = read(a.repo)
    except ValueError as e:
        print(f"FAIL {e}", file=out)
        return 1
    if a.tag and from_tag(a.tag) != v:
        print(f"FAIL tag {a.tag!r} is not v{v} (installer/VERSION); tags are vMAJOR.MINOR.PATCH, never moved", file=out)
        return 1
    if a.stamp_citation:
        try:
            d = datetime.date.fromisoformat(a.date).isoformat()
        except ValueError:
            print("--stamp-citation needs --date YYYY-MM-DD (the release day)", file=out)
            return 2
        stamp_citation(a.repo, v, d)
        print(f"{CITATION}: version {v}, date-released {d}", file=out)
        return 0
    print(rc_comma(v) if a.rc else (f"ok {v}" if a.check else v), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
