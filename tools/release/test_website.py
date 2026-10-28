#!/usr/bin/env python3
"""Host test for tools/release/website.py on a small fixture (no game data, no work/): the page is generated, --check
passes on a fresh page and fails on a stale page, a missing key feature row, a missing requirements section and a
missing style.css; Markdown in the data is escaped and links become GitHub URLs; the headline follows the "Full
campaign" row; the screenshot section is left out while SHOTS is empty and works (and fails on a missing checkpoint)
when it is not; the lint refuses scripts, event handlers and outside resources other than Google Fonts; the
forbidden third-party service name appears nowhere. From KZ3 78bf574 tools/release/test_website.py. Exit 0 = PASS.

    python3 tools/release/test_website.py
"""
import contextlib
import io
import os
import pathlib
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import website  # noqa: E402

FORBIDDEN = "rew" + "ired"   # spelled in two parts so that a repo-wide grep for the name stays empty
HEAD = "kind\tarea\tfeature\tdetail\tstatus\tdone\tdays\tlane\tevidence\tnote\n"
REQ = """# Requirements

## What you need from your own copy of the game

| Item | Required | Details |
|---|---|---|
| **Disc** | yes | dump it (D4) |
| **Update** | yes | 1.29 |

## Hardware to play

| | Minimum | Recommended | Basis |
|---|---|---|---|
| **CPU** | 6 cores | 8 cores | threads |

## Other
"""


def fixture(root, playable="not yet", drop_key=None, req=REQ, shots=()):
    rows = [("ps3", "Campaign", website.PLAYABLE_ROW, "9 levels", playable, "0", "1", "x", "ev", "")]
    for i, k in enumerate(website.KEY_ROWS):
        if k != drop_key and k != website.PLAYABLE_ROW:
            rows.append(("port" if i % 3 == 0 else "ps3", "Campaign" if i % 2 else "Graphics", k,
                         "PS3 does **it** `x` <script>x</script> see [notes](docs/a.md)", "partial", "0.5", "1", "x", "ev", ""))
    rows.append(("port", "Extras", "Mouse aim", "", "not yet", "0", "1", "x", "ev", ""))
    rows.append(("port", "Extras", "Hidden", "", "not yet", "0", "1", "x", "ev", "BACKLOG later"))
    (root / "docs").mkdir(parents=True)
    (root / "docs/features.tsv").write_text("# fixture\n" + HEAD + "".join("\t".join(r) + "\n" for r in rows))
    if shots:
        (root / "docs/checkpoints").mkdir()
        (root / "docs/checkpoints/README.md").write_text(
            "| a | b |\n|---|---|\n| 2026-10-01 | [shot-a](20261001-000000Z_shot-a.png) |\n")
    if req is not None:
        (root / "docs/requirements.md").write_text(req)
    (root / "public/site").mkdir(parents=True)
    (root / "public/site/style.css").write_text("body{}\n")


def run(*args):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = website.main(list(args))
    return rc, err.getvalue()


def main():
    fails = []

    def expect(cond, what):
        if not cond:
            fails.append(what)

    with tempfile.TemporaryDirectory() as t:
        root = pathlib.Path(t) / "ok"
        fixture(root)
        expect(run("--root", str(root), "--check")[0] == 1, "check passes with no page")
        expect(run("--root", str(root))[0] == 0, "generate fails")
        rc, err = run("--root", str(root), "--check")
        expect(rc == 0, f"check fails on a fresh page: {err}")
        page = (root / website.PAGE).read_text()
        expect("Partly playable" in page, "headline not 'Partly playable' (campaign row not yet, in-level play row partial)")
        expect("<script>" not in page and "&lt;script&gt;" in page, "detail text not escaped")
        expect(f'href="{website.REPO}/blob/main/docs/a.md"' in page, "relative link not a GitHub URL")
        expect("<strong>it</strong>" in page and "<code>x</code>" in page, "inline Markdown not rendered")
        expect('id="shots"' not in page and "<figure" not in page, "screenshot section present while SHOTS is empty")
        expect('src="../assets/banner.png"' in page and "../assets/banner@2x.png 2x" in page, "banner missing")
        expect("(D4)" not in page and "<td>6 cores</td>" in page and "Basis" not in page, "requirements table wrong")
        expect("Hidden" not in page, "BACKLOG row shown")
        expect(f'href="{website.HELGHAST}"' in page, "Project Helghast link missing")
        expect(not website.lint(page), f"lint on the generated page: {website.lint(page)}")
        expect(FORBIDDEN not in page.lower(), "page names the forbidden service")
        expect(FORBIDDEN not in open(os.path.join(HERE, "website.py")).read().lower(), "website.py names it")
        (root / website.PAGE).write_text(page + "x")
        expect(run("--root", str(root), "--check")[0] == 1, "stale page passes")
        (root / website.PAGE).write_text(page.replace("<body>", "<body><script>x</script>"))
        expect(run("--root", str(root), "--check")[0] == 1, "injected script passes")
        (root / website.PAGE).write_text(page.replace("<body>", '<body><img src="https://example.com/a.png">'))
        expect(run("--root", str(root), "--check")[0] == 1, "outside resource passes")

        root = pathlib.Path(t) / "playable"
        fixture(root, playable="works")
        run("--root", str(root))
        expect("<strong>Playable</strong>" in (root / website.PAGE).read_text(), "headline ignores the campaign row")

        for name, kw in (("nokey", {"drop_key": website.KEY_ROWS[1]}), ("noreq", {"req": None}),
                         ("badreq", {"req": REQ.replace("## Hardware to play", "## Hardware")})):
            root = pathlib.Path(t) / name
            fixture(root, **kw)
            expect(run("--root", str(root))[0] == 1, f"{name}: generate passes")
        root = pathlib.Path(t) / "nocss"
        fixture(root)
        run("--root", str(root))
        (root / "public/site/style.css").unlink()
        expect(run("--root", str(root), "--check")[0] == 1, "missing style.css passes")

        # screenshots: the code path stays usable
        old = website.SHOTS
        try:
            website.SHOTS = (("shot-a", "A shot"),)
            root = pathlib.Path(t) / "shots"
            fixture(root, shots=True)
            expect(run("--root", str(root))[0] == 0, "generate with a screenshot fails")
            page = (root / website.PAGE).read_text()
            expect('src="../docs/checkpoints/20261001-000000Z_shot-a.png"' in page and 'id="shots"' in page, "shot not shown")
            root = pathlib.Path(t) / "noshot"
            fixture(root)
            expect(run("--root", str(root))[0] == 1, "missing checkpoint passes")
        finally:
            website.SHOTS = old

    for bad in ('<script src="a.js"></script>', '<img src="x.png" onerror="x()">', '<a href="javascript:x()">a</a>',
                '<img src="https://example.com/a.png">', '<link rel="stylesheet" href="https://cdn.example/x.css">',
                '<link href="https://fonts.googleapis.com.evil.example/x">', '<img src="file:///C:/a.png">'):
        expect(website.lint(bad), f"lint misses {bad}")
    for good in ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X">',
                 '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>', '<img src="../assets/a.png">',
                 f'<a href="{website.REPO}/issues">issues</a>'):
        expect(not website.lint(good), f"lint refuses {good}")

    if fails:
        print("FAIL test_website:\n  - " + "\n  - ".join(fails))
        return 1
    print("PASS test_website (generate, check, negative controls, screenshots path, 7 lint refusals)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
