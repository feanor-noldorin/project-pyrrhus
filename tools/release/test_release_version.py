#!/usr/bin/env python3
"""Host test for tools/release/release_version.py (the one version) on fake trees: strict MAJOR.MINOR.PATCH,
the tag check, the windres form, CITATION.cff stamping, and that the repository's own installer/VERSION is valid.

    python3 tools/release/test_release_version.py
"""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import release_version as rv  # noqa: E402

FAILS = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"\n     {str(detail)[:400]}"))
    if not cond:
        FAILS.append(what)


def run(*args):
    buf = io.StringIO()
    rc = rv.main(list(args), out=buf)
    return rc, buf.getvalue()


def main():
    check(all(rv.valid(v) for v in ("0.1.0", "1.0.0", "0.10.2"))
          and not any(rv.valid(v) for v in ("0.1", "v0.1.0", "0.1.0-rc1", "01.1.0", "0.1.0.0", "", "0.1.0 ")),
          "valid: MAJOR.MINOR.PATCH only")
    check(rv.from_tag("v0.1.0") == "0.1.0" and rv.from_tag("0.1.0") is None and rv.from_tag("v0.1.0-rc1") is None,
          "tags are v + the version")
    rc, out = run()
    check(rc == 0 and rv.valid(out.strip()), "the repository's installer/VERSION is valid", out)
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "installer"))
        os.makedirs(os.path.join(tmp, "public"))
        ver = os.path.join(tmp, "installer", "VERSION")
        open(ver, "w").write("0.2.3\n")
        check(run("--repo", tmp, "--rc") == (0, "0,2,3,0\n"), "windres form")
        check(run("--repo", tmp, "--check", "--tag", "v0.2.3")[0] == 0, "matching tag passes")
        rc, out = run("--repo", tmp, "--check", "--tag", "v0.2.4")
        check(rc == 1 and "never moved" in out, "another tag fails", out)
        open(ver, "w").write("0.2.3-dev\n")
        rc, out = run("--repo", tmp, "--check")
        check(rc == 1 and "no suffix" in out, "a suffixed VERSION fails", out)
        open(ver, "w").write("0.2.3\n")
        cff = os.path.join(tmp, "public", "CITATION.cff")
        open(cff, "w").write('cff-version: 1.2.0\ntitle: "Project Pyrrhus"\nlicense: MIT\n')
        rc, out = run("--repo", tmp, "--stamp-citation", "--date", "2026-10-30")
        text = open(cff).read()
        check(rc == 0 and text == 'cff-version: 1.2.0\ntitle: "Project Pyrrhus"\nversion: "0.2.3"\n'
              'date-released: "2026-10-30"\nlicense: MIT\n', "CITATION.cff gets version and date after the title", text)
        open(ver, "w").write("0.2.4\n")
        run("--repo", tmp, "--stamp-citation", "--date", "2026-11-02")
        text = open(cff).read()
        check(text.count("\nversion:") == 1 and 'version: "0.2.4"' in text and 'date-released: "2026-11-02"' in text,
              "a second stamp replaces the lines in place", text)
        check(run("--repo", tmp, "--stamp-citation", "--date", "soon")[0] == 2, "a bad date is a usage error")
    print(f"\n{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
