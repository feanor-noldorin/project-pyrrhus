#!/usr/bin/env python3
"""pso_template.py: inspect and merge pipeline templates (patch 2071's rsx_pso_template.h layout, KZ2 patch 2120).

  pso_template.py info FILE...            header and record counts (records with a duplicate key are counted once)
  pso_template.py merge OUT FILE...       OUT = every record of the inputs, first record of each key wins

A template holds hashes and numeric pipeline state only (no shader text, no microcode). Each KZ2 session writes its
own to <shader cache dir>/pso-template-own.bin (patch 2120); merged, they become the template a release ships
(pso-template.bin next to kz2.exe or one folder up, patch 2077), which prewarms a first play's pipelines while the
level loads. Same file layout as Project Helghast's template.
"""
import struct
import sys

MAGIC, VERSION, KEYVER = 0x54505A4B, 1, 1
HDR = struct.Struct("<6I")   # magic, version, rec_size, key_version, flags, count
MAX_RECS = 65536


def read(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < HDR.size:
        raise ValueError(f"{path}: short file")
    magic, ver, rec_size, keyver, flags, count = HDR.unpack_from(data)
    if magic != MAGIC or ver != VERSION or keyver != KEYVER or count > MAX_RECS or rec_size < 8:
        raise ValueError(f"{path}: not a version {VERSION} / key version {KEYVER} template")
    body = data[HDR.size:]
    n = min(count, len(body) // rec_size)
    recs = [body[i * rec_size:(i + 1) * rec_size] for i in range(n)]
    return {"rec_size": rec_size, "flags": flags, "count": count, "recs": recs}


def key(rec):
    return struct.unpack_from("<Q", rec)[0] or 1


def merge(paths):
    out, seen, rec_size, flags = [], set(), None, 0
    for p in paths:
        t = read(p)
        if rec_size is None:
            rec_size, flags = t["rec_size"], t["flags"]
        elif t["rec_size"] != rec_size:
            raise ValueError(f"{p}: record size {t['rec_size']} != {rec_size}")
        for r in t["recs"]:
            k = key(r)
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
    if len(out) > MAX_RECS:
        raise ValueError(f"{len(out)} records > {MAX_RECS}")
    return rec_size, flags, out


def write(path, rec_size, flags, recs):
    with open(path, "wb") as f:
        f.write(HDR.pack(MAGIC, VERSION, rec_size, KEYVER, flags, len(recs)))
        for r in recs:
            f.write(r)


def main(argv):
    if len(argv) >= 2 and argv[0] == "info":
        for p in argv[1:]:
            t = read(p)
            keys = {key(r) for r in t["recs"]}
            print(f"{p}: {len(t['recs'])} records ({len(keys)} distinct keys), record {t['rec_size']} bytes, "
                  f"flags 0x{t['flags']:x}")
        return 0
    if len(argv) >= 3 and argv[0] == "merge":
        rec_size, flags, recs = merge(argv[2:])
        write(argv[1], rec_size, flags, recs)
        print(f"{argv[1]}: {len(recs)} records from {len(argv) - 2} file(s)")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
