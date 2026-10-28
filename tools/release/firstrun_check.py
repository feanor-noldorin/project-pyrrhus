#!/usr/bin/env python3
"""First-run checks for the release installer and the portable zip: is the player's own Killzone 2 dump, 1.29 update
and decrypted EBOOT what the port can lift and build from? From KZ3 78bf574 tools/release/firstrun_check.py.
Standard library only, Python 3.8+, runs on the bundled Windows Python and on Linux; reads nothing of the game beyond PARAM.SFO, the first bytes of each file (magic),
file sizes and the hashes (H1: the decrypted EBOOT; A1: the disc archive, unless --skip-archive-hash).

    firstrun_check.py --dump DIR [--update DIR] [--eboot FILE] [--json] [--min-psarc-bytes N] [--hashes FILE]
                      [--psarc-hashes FILE] [--build DIR] [--progress] [--skip-archive-hash]

  --dump    the decrypted disc dump folder (holds PS3_GAME/PARAM.SFO)
  --update  the installed 1.29 update folder, where a PS3 or RPCS3 keeps it: .../dev_hdd0/game/BCUS98116 (the update
            installs under the disc's own title id; holds PARAM.SFO and USRDIR/EBOOT.BIN)
  --eboot   the decrypted EBOOT (an ELF); default: <update>/USRDIR/EBOOT.elf, else <dump>/PS3_GAME/USRDIR/EBOOT.elf
            (next to EBOOT.BIN), else an EBOOT.BIN that is already an ELF
  --hashes  expected EBOOT SHA-256 per version; default eboot_sha256.json next to this script. H1 checks
            the ELF's SHA-256 against it: a mismatch is a WARN with the size and both hashes (never a FAIL: the build
            only needs a 1.29 EBOOT that lifts); an empty value means "unknown yet" and also only warns.
  --psarc-hashes  the known disc archive (default psarc_sha256.json next to this script). A1: SHA-256 of the whole
            data_ps3.psarc (read in 8 MiB pieces) against it. OK = matches; a mismatch on a disc listed there is a FAIL
            when the file says fail_on_mismatch, else a WARN (one copy checked so far); any other disc = WARN. A
            different size is a mismatch without reading the file. Cached in <build>/psarc-sha256-cache.json by path,
            size and mtime of every part (no cache without --build). --progress prints "ARCHIVE-HASH done=X total=Y"
            lines (firstrun.py turns them into PROGRESS lines); --skip-archive-hash leaves A1 out (from KZ3 2f45a2b).

Split archives (from KZ3 b1a6262): a dump copied to a FAT32 drive stores a file over 4 GiB as parts
<name>.66600, .66601, ... (data_ps3.psarc is 6.5 GiB). D3 accepts the parts in place of data_ps3.psarc (sizes added
up, magic from the first part) and names the first missing part when the numbering has a gap; A1 hashes the parts in
order as one stream.

One line per check: OK / WARN / FAIL <code>: <message>. Exit 0 = no FAIL, 1 = at least one FAIL, 2 = usage.
--json prints {"ok": bool, "checks": [{"code", "level", "message"}], "facts": {...}} instead. Numbers come from
the RE notes and a disc dump with the 1.29 update; no game content is embedded.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

TITLE_ID = "BCUS98116"                 # US disc (the RE notes); other regions are untested
DISC_EBOOT_BIN_SIZE = 16_384_360       # PS3_GAME/USRDIR/EBOOT.BIN on the disc, encrypted SELF (the RE notes)
EBOOT_ELF_SIZES = {                    # decrypted EBOOTs (of a disc dump and the 1.29 update)
    16_381_928: "1.01",
    16_455_144: "1.29",
}
UPDATE_APP_VER = "01.29"               # the 1.29 update's PARAM.SFO APP_VER (read 2026-10-12; its VERSION is 01.00)
UPDATE_DATA = "added_data_ps3.psarc"   # the 1.29 update's data archive, a plain PSARC (15,725,397 bytes)
UPDATE_PATCH_DIR = "patch_data_ps3"     # the 1.29 update's *.pspatch files (folder)
MIN_PSARC_BYTES = 6 << 30              # data_ps3.psarc is 6,998,576,922 bytes on disc; smaller = truncated dump
PSARC_MAGIC = b"PSAR"
SELF_MAGIC = b"SCE\0"
ELF_MAGIC = b"\x7fELF"
EM_PPC64 = 0x15
HASHES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eboot_sha256.json")
PSARC_HASHES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psarc_sha256.json")
PSARC_CACHE_NAME = "psarc-sha256-cache.json"
HASH_CHUNK = 8 << 20
SPLIT_FIRST = 66600                    # a FAT32 dump cuts a file over 4 GiB into <name>.66600, .66601, ...
PSARC_NAME = "data_ps3.psarc"


def read_sfo(path):
    """PARAM.SFO -> dict (same decoder as tools/disc_info.py)."""
    d = open(path, "rb").read()
    if d[:4] != b"\0PSF":
        raise ValueError("not a PARAM.SFO (bad magic)")
    _, _, kt, dt, n = struct.unpack("<4sIIII", d[:20])
    out = {}
    for i in range(n):
        ko, fmt, ln, _, do = struct.unpack("<HHIII", d[20 + 16 * i:36 + 16 * i])
        k = d[kt + ko:d.index(b"\0", kt + ko)].decode()
        v = d[dt + do:dt + do + ln]
        out[k] = struct.unpack("<I", v)[0] if fmt == 0x404 else v.rstrip(b"\0").decode(errors="replace")
    return out


def head(path, n):
    with open(path, "rb") as f:
        return f.read(n)


class Report:
    def __init__(self):
        self.checks = []
        self.facts = {}

    def add(self, level, code, msg):
        self.checks.append({"code": code, "level": level, "message": msg})

    def ok(self, code, msg):
        self.add("OK", code, msg)

    def warn(self, code, msg):
        self.add("WARN", code, msg)

    def fail(self, code, msg):
        self.add("FAIL", code, msg)

    @property
    def passed(self):
        return not any(c["level"] == "FAIL" for c in self.checks)


def check_sfo(r, path, code, what):
    """Shared PARAM.SFO check for the dump and the update. Returns the fields or None."""
    if not os.path.isfile(path):
        r.fail(code, f"{what}: no PARAM.SFO at {path}")
        return None
    try:
        sfo = read_sfo(path)
    except (ValueError, struct.error, IndexError) as e:
        r.fail(code, f"{what}: PARAM.SFO unreadable ({e})")
        return None
    tid = sfo.get("TITLE_ID")
    if tid != TITLE_ID:
        r.fail(code, f"{what}: TITLE_ID is {tid!r}, the port needs {TITLE_ID} (US disc); other releases are untested")
    else:
        r.ok(code, f"{what}: TITLE_ID {tid} ({sfo.get('TITLE', '?')})")
    return sfo


def split_parts(path):
    """The pieces of a file as a FAT32 dump stores it. -> (parts, missing): parts = [path] when the file exists, else
    the consecutive <path>.66600, .66601, ... that exist (stops at the first gap); missing = the file name to ask the
    player for ("" when nothing is missing): <name> when neither the file nor any part exists, <name>.666NN for the
    first gap in the numbering (also when later parts exist but .66600 does not). Names compare case-blind."""
    if os.path.isfile(path):
        return [path], ""
    d, name = os.path.split(path)
    pre = name.lower() + "."
    nums = {}
    try:
        for n in os.listdir(d or "."):
            tail = n[len(pre):]
            if n.lower().startswith(pre) and tail.isdigit() and int(tail) >= SPLIT_FIRST \
                    and os.path.isfile(os.path.join(d, n)):
                nums[int(tail)] = os.path.join(d, n)
    except OSError:
        pass
    parts, i = [], SPLIT_FIRST
    while i in nums:
        parts.append(nums[i])
        i += 1
    if not nums:
        return [], name
    if max(nums) >= i:                    # a part past the gap exists: the numbering has a hole
        return parts, f"{name}.{i}"
    return parts, ""


def psarc_info(path):
    """-> (parts, missing, total size, first four bytes) of data_ps3.psarc as one file or as FAT32 split parts."""
    parts, missing = split_parts(path)
    if not parts or missing:
        return parts, missing, 0, b""
    return parts, "", sum(os.path.getsize(p) for p in parts), head(parts[0], 4)


def check_dump(r, dump, min_psarc):
    sfo = check_sfo(r, os.path.join(dump, "PS3_GAME", "PARAM.SFO"), "D1", "disc dump")
    if sfo:
        r.facts["disc"] = {k: sfo.get(k) for k in ("TITLE_ID", "TITLE", "VERSION", "APP_VER", "CATEGORY")}
        if sfo.get("CATEGORY") != "DG":
            r.warn("D1", f"disc dump: CATEGORY {sfo.get('CATEGORY')!r}, a disc game is 'DG' (an installed copy?)")
    eboot = os.path.join(dump, "PS3_GAME", "USRDIR", "EBOOT.BIN")
    if not os.path.isfile(eboot):
        r.fail("D2", "disc dump: no PS3_GAME/USRDIR/EBOOT.BIN (dump incomplete)")
    else:
        magic, size = head(eboot, 4), os.path.getsize(eboot)
        r.facts["disc_eboot_bin"] = {"size": size, "magic": magic.hex()}
        if magic == SELF_MAGIC:
            r.ok("D2", f"disc EBOOT.BIN is an encrypted SELF ({size:,} bytes; expected: the disc one is never used directly)")
        elif magic == ELF_MAGIC:
            r.ok("D2", f"disc EBOOT.BIN is already a decrypted ELF ({size:,} bytes)")
        else:
            r.fail("D2", f"disc EBOOT.BIN has magic {magic!r}: neither SELF nor ELF (bad dump)")
        if magic == SELF_MAGIC and size != DISC_EBOOT_BIN_SIZE:
            r.warn("D2", f"disc EBOOT.BIN is {size:,} bytes, the US disc's is {DISC_EBOOT_BIN_SIZE:,} (another version?)")
    psarc = os.path.join(dump, "PS3_GAME", "USRDIR", PSARC_NAME)
    parts, missing, size, magic = psarc_info(psarc)
    if missing and missing != PSARC_NAME:
        r.fail("D3", f"disc dump: PS3_GAME/USRDIR/{missing} is missing: data_ps3.psarc is split into parts "
                     "(data_ps3.psarc.66600, .66601, ...) and the numbering has a gap (dump incomplete)")
    elif not parts:
        r.fail("D3", "disc dump: no PS3_GAME/USRDIR/data_ps3.psarc (the game's data archive)")
    else:
        r.facts["psarc"] = {"size": size}
        if len(parts) > 1 or parts[0] != psarc:
            r.facts["psarc"]["parts"] = [os.path.basename(p) for p in parts]
        if magic != PSARC_MAGIC:
            r.fail("D3", f"data_ps3.psarc does not start with PSAR (magic {magic!r}): not a PSARC, or still encrypted")
        elif size < min_psarc:
            r.fail("D3", f"data_ps3.psarc is {size:,} bytes, less than {min_psarc:,}: the dump looks truncated")
        else:
            r.ok("D3", f"data_ps3.psarc present ({size / 2**30:.2f} GiB"
                       + (f", {len(parts)} split parts .66600 ...)" if parts[0] != psarc else ")"))


def hash_file(path, progress=None):
    """-> the SHA-256 (hex) of a file, or of a list of split parts joined in list order, read in HASH_CHUNK pieces;
    progress(done, total) after each piece, over the total size."""
    h = hashlib.sha256()
    paths = [path] if isinstance(path, str) else list(path)
    total = sum(os.path.getsize(p) for p in paths)
    done = 0
    for p in paths:
        with open(p, "rb") as f:
            while True:
                b = f.read(HASH_CHUNK)
                if not b:
                    break
                h.update(b)
                done += len(b)
                if progress:
                    progress(done, total)
    return h.hexdigest()


def check_psarc_hash(r, psarc, title_id, hashes_file=PSARC_HASHES_FILE, cache_dir=None, progress=None):
    """A1: data_ps3.psarc (one file or its split parts) against the known disc archive (psarc_sha256.json: sha256,
    size, discs, fail_on_mismatch). A different size is a mismatch without reading the file. The hash is cached in
    <cache_dir>/psarc-sha256-cache.json keyed by the path, the total size and every part's path, size and mtime."""
    try:
        with open(hashes_file, encoding="utf-8") as f:
            known = json.load(f)
        want, want_size = known["sha256"].strip().lower(), int(known["size"])
        discs, hard = list(known.get("discs", [])), bool(known.get("fail_on_mismatch", False))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        r.warn("A1", f"known archive hash not readable ({hashes_file}: {e}); data_ps3.psarc not checked")
        return
    parts, missing = split_parts(psarc)
    if not parts or missing:
        r.warn("A1", f"data_ps3.psarc not complete ({missing or 'not found'} is missing); archive not hashed")
        return
    size = sum(os.path.getsize(p) for p in parts)
    sig = [[os.path.abspath(p), os.path.getsize(p), os.stat(p).st_mtime_ns] for p in parts]
    key = os.path.abspath(psarc)
    cache_path = os.path.join(cache_dir, PSARC_CACHE_NAME) if cache_dir else None
    cache = {}
    if cache_path:
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            if not isinstance(cache, dict):
                cache = {}
        except (OSError, ValueError):
            cache = {}
    got, cached = None, False
    ent = cache.get(key)
    if isinstance(ent, dict) and ent.get("size") == size and ent.get("parts") == sig and ent.get("sha256"):
        got, cached = ent["sha256"], True
    elif size == want_size:
        got = hash_file(parts[0] if len(parts) == 1 else parts, progress)
        if cache_path:
            cache[key] = {"size": size, "parts": sig, "sha256": got}
            try:
                os.makedirs(cache_dir, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=1)
            except OSError:
                pass
    r.facts.setdefault("psarc", {})["sha256"] = got or ""
    detail = f"{size:,} bytes" + (f", SHA-256 {got}" if got else f"; the known archive is {want_size:,} bytes")
    if got == want:
        r.ok("A1", "data_ps3.psarc matches the known disc archive" + (" (hash cached from an earlier run)" if cached else ""))
    elif title_id in discs and hard:
        r.fail("A1", f"data_ps3.psarc differs from the known disc archive (damaged or modified copy): copy or dump the "
                     f"disc again ({detail})")
    elif title_id in discs:
        r.warn("A1", f"data_ps3.psarc differs from the known disc archive ({detail}): a damaged or modified copy, or a "
                     "disc printing not seen yet. If the game does not start or stops loading, copy or dump the disc again")
    else:
        r.warn("A1", f"data_ps3.psarc is not a known archive ({title_id or 'no title id'}; {detail})")


def check_update(r, upd):
    sfo = check_sfo(r, os.path.join(upd, "PARAM.SFO"), "U1", "1.29 update")
    if sfo:
        ver = sfo.get("APP_VER")
        r.facts["update"] = {k: sfo.get(k) for k in ("TITLE_ID", "APP_VER", "VERSION", "CATEGORY")}
        if ver != UPDATE_APP_VER:
            r.warn("U1", f"update APP_VER is {ver!r}, the port is built for {UPDATE_APP_VER} (unverified expectation)")
        else:
            r.ok("U1", f"update APP_VER {ver}")
    eb = os.path.join(upd, "USRDIR", "EBOOT.BIN")
    if not os.path.isfile(eb):
        r.fail("U2", "1.29 update: no USRDIR/EBOOT.BIN (update not installed here)")
    else:
        r.ok("U2", f"update EBOOT.BIN present ({os.path.getsize(eb):,} bytes, {'SELF' if head(eb, 4) == SELF_MAGIC else 'ELF'})")
    data = os.path.join(upd, "USRDIR", UPDATE_DATA)
    if not os.path.isfile(data):
        r.warn("U3", f"1.29 update: no USRDIR/{UPDATE_DATA}; the update's data layer will be missing (disc data only)")
    elif head(data, 4) != PSARC_MAGIC:
        r.warn("U3", f"1.29 update: USRDIR/{UPDATE_DATA} does not start with PSAR (still encrypted, or damaged)")
    else:
        r.ok("U3", f"update data archive present ({os.path.getsize(data):,} bytes)")
    if not os.path.isdir(os.path.join(upd, "USRDIR", UPDATE_PATCH_DIR)):
        r.warn("U3", f"1.29 update: no USRDIR/{UPDATE_PATCH_DIR}/ (the update's patch files)")


def check_eboot_elf(r, elf, target="1.29"):
    if not os.path.isfile(elf):
        r.fail("E1", f"no decrypted EBOOT at {elf}: the port cannot decrypt it; it needs a decrypted EBOOT.elf, made from your own copy, there")
        return
    h, size = head(elf, 64), os.path.getsize(elf)
    r.facts["eboot_elf"] = {"path": elf, "size": size}
    if len(h) < 64 or h[:4] != ELF_MAGIC:
        r.fail("E1", f"{elf} is not an ELF (magic {h[:4]!r}); an encrypted SELF starts with 'SCE'")
        return
    cls, data = h[4], h[5]
    machine = struct.unpack(">H", h[18:20])[0] if data == 2 else struct.unpack("<H", h[18:20])[0]
    if cls != 2 or data != 2 or machine != EM_PPC64:
        r.fail("E1", f"{elf}: ELF class {cls}, data {data}, machine 0x{machine:x}; a PS3 EBOOT is 64-bit big-endian PPC64")
        return
    ver = EBOOT_ELF_SIZES.get(size)
    r.facts["eboot_elf"]["version"] = ver
    if ver == target:
        r.ok("E1", f"decrypted EBOOT is the {ver} one ({size:,} bytes)")
    elif ver == "1.01":
        r.warn("E1", f"decrypted EBOOT is the disc v1.01 one ({size:,} bytes); the port is built on {target}: "
                     "install the 1.29 update and use its decrypted EBOOT.elf")
    elif ver:
        r.warn("E1", f"decrypted EBOOT is the {ver} one ({size:,} bytes); this build is for the {target} EBOOT")
    else:
        r.warn("E1", f"decrypted EBOOT has an unknown size ({size:,} bytes): not 1.01 or 1.29; the lift fixups may not apply")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_eboot_hash(r, elf, hashes_file):
    """H1: the decrypted EBOOT's SHA-256 against the expected one for its version (1.29 when the size
    is unknown). Warn-only: mismatch, unknown yet (empty value) and an unreadable hashes file all give WARN."""
    info = r.facts.get("eboot_elf")
    if not info or "version" not in info:      # E1 failed (missing, not an ELF, wrong machine): nothing to hash
        return
    try:
        got = file_sha256(elf)
    except OSError as e:
        r.warn("H1", f"could not read {elf} to hash it: {e}")
        return
    info["sha256"] = got
    ver = info.get("version") or "1.29"
    try:
        with open(hashes_file, encoding="utf-8") as f:
            want = (json.load(f).get(ver) or {}).get("sha256", "").strip().lower()
    except (OSError, ValueError, AttributeError) as e:
        r.warn("H1", f"expected EBOOT hashes not readable ({hashes_file}: {e}); SHA-256 {got} not checked")
        return
    if not want:
        r.warn("H1", f"expected SHA-256 of the {ver} EBOOT is unknown yet (empty in {os.path.basename(hashes_file)}); "
                     f"this one is {got} ({info['size']:,} bytes), not checked")
    elif want == got:
        r.ok("H1", f"EBOOT SHA-256 matches the known {ver} EBOOT")
    else:
        r.warn("H1", f"EBOOT SHA-256 differs from the known {ver} one: {info['size']:,} bytes, SHA-256 {got}, "
                     f"expected {want}. The build may still work if it is a 1.29 EBOOT that lifts; if it fails, "
                     "check that the decrypted EBOOT.elf is the update's")


BUILD_DLL = "at3_standalone.dll"   # built beside kz2.exe (patch 6022, PS3RECOMP_AT3_SHARED); kz2.exe imports it


def check_build(obj_dir):
    """-> problems for the finished build folder (where kz2.exe was linked): kz2.exe imports at3_standalone.dll, so
    without it the game does not start at all (Windows: 'the code execution cannot proceed because
    at3_standalone.dll was not found'). The FFmpeg DLLs are not checked here: they ship prebuilt in the payload."""
    bad = []
    if not os.path.isfile(os.path.join(obj_dir, "kz2.exe")):
        bad.append(f"kz2.exe was not built in {obj_dir}")
    dll = os.path.join(obj_dir, BUILD_DLL)
    if not os.path.isfile(dll):
        bad.append(f"{BUILD_DLL} is missing from {obj_dir}: the build did not produce it, and kz2.exe will not start "
                   f"without it (rebuild; the compile step must finish without errors)")
    elif os.path.getsize(dll) == 0:
        bad.append(f"{dll} is empty")
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--build-dir", help="check the finished build folder (kz2.exe + at3_standalone.dll) instead of the game files")
    ap.add_argument("--dump")
    ap.add_argument("--update")
    ap.add_argument("--eboot")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-psarc-bytes", type=int, default=MIN_PSARC_BYTES)
    ap.add_argument("--hashes", default=HASHES_FILE)
    ap.add_argument("--psarc-hashes", default=PSARC_HASHES_FILE)
    ap.add_argument("--build", help="the build folder: A1 caches the archive's SHA-256 there")
    ap.add_argument("--progress", action="store_true", help="print ARCHIVE-HASH progress lines while A1 hashes")
    ap.add_argument("--skip-archive-hash", action="store_true", help="leave A1 (the archive's SHA-256) out")
    ap.add_argument("--target", choices=("1.01", "1.29"), default="1.29",
                    help="the EBOOT version the build is for (firstrun.py passes its tree's)")
    a = ap.parse_args(argv)
    if a.build_dir:
        bad = check_build(a.build_dir)
        for b in bad:
            print(f"FAIL B1: {b}")
        print("build checks:", "FAIL" if bad else "pass")
        return 1 if bad else 0
    if not a.dump:
        ap.error("--dump is required")
    r = Report()
    if not os.path.isdir(a.dump):
        r.fail("D0", f"dump folder not found: {a.dump}")
    else:
        check_dump(r, a.dump, a.min_psarc_bytes)
        psarc = os.path.join(a.dump, "PS3_GAME", "USRDIR", PSARC_NAME)
        if not a.skip_archive_hash and not any(c["code"] == "D3" and c["level"] == "FAIL" for c in r.checks) \
                and "psarc" in r.facts:
            def prog(done, total):
                print(f"ARCHIVE-HASH done={done} total={total}", flush=True)
            check_psarc_hash(r, psarc, (r.facts.get("disc") or {}).get("TITLE_ID"), a.psarc_hashes, a.build,
                             prog if a.progress else None)
    if a.update:
        if not os.path.isdir(a.update):
            r.fail("U0", f"update folder not found: {a.update}")
        else:
            check_update(r, a.update)
    else:
        r.warn("U0", "no --update given: the 1.29 update is required (the port is built on its EBOOT)")
    elf = a.eboot
    if not elf:
        # EBOOT.elf sits next to EBOOT.BIN; a dump may also hold an ELF as EBOOT.BIN.
        cand = [os.path.join(a.update, "USRDIR", n) for n in ("EBOOT.elf", "EBOOT.BIN")] if a.update else []
        cand += [os.path.join(a.dump, "PS3_GAME", "USRDIR", n) for n in ("EBOOT.elf", "EBOOT.BIN")]
        elf = next((c for c in cand if os.path.isfile(c) and head(c, 4) == ELF_MAGIC), cand[0])
    check_eboot_elf(r, elf, a.target)
    check_eboot_hash(r, elf, a.hashes)
    if a.json:
        print(json.dumps({"ok": r.passed, "checks": r.checks, "facts": r.facts}, indent=2))
    else:
        for c in r.checks:
            print(f"{c['level']:4} {c['code']}: {c['message']}")
        print("first-run checks:", "pass" if r.passed else "FAIL")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
