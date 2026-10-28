#!/usr/bin/env python3
"""Dump the engine's RTTI class descriptors from the decrypted EBOOT: the schema of .core files.

    rtti_dump.py EBOOT.elf [--json OUT.json] [--class NAME]...

JSON: {"classes": [{name, record, size, kind, bases, members:[{name,type,offset,flags,group}]}],
       "types": {primitive/enum name: {kind, size[, values]}}}; tools/core.py reads it.

Layout recovered 2026-10-07 (the RE notes, "RTTI"):
  type descriptor D (data segment; "type pointers" everywhere point at D):
    +0x00 0xFFFFFFFF
    +0x04 u32 kind, by top byte:
          0x01 primitive: byte1 = size, +0x08 name ptr            (float 0x01040100, bool 0x01010100, String 0x01040000)
          0x02 reference: +0x08 = target descriptor, +0x0C -> vtable-like record whose first word is a name
               ("Ref" -> `T*`, "cptr" -> `T^`)
          0x03 container: +0x08 = element descriptor, +0x0C -> "Array" (`T[]`) or "TinyArray" (`T[tiny]`)
          0x04 enum: low byte = number of values, byte1 = size, +0x08 name ptr, +0x0C -> (value, name ptr) pairs
          0x05 class (below)
    class: +0x08 u32 ASSUMPTION: flags/hash, +0x0C instance size, +0x30 name ptr, +0x34 0xFFFFFFFF, +0x38/+0x3C 0,
           +0x40 bases ptr (8-byte entries: base descriptor ptr, u32 ASSUMPTION: base offset; the list ends at the
                  first entry that is not a class descriptor or at the members pointer),
           +0x44 members ptr (0 = none), +0x48 ASSUMPTION: script methods, +0x4C..+0x50 message handler table
           (12-byte entries: message class, handler OPD, 0; e.g. MsgReadBinary = custom serialiser)
  member entry (0x1C bytes):
    +0x00 type descriptor ptr (0 = category header such as "General")
    +0x04 u16 field offset, u16 flags (bit 0x1 ... see core.py), +0x08 name ptr, +0x0C..+0x18 0
  A member list ends where the next class's base list (or member list) begins, so lists are bounded by the
  sorted set of all bases/members pointers, and at the first entry whose type does not resolve and whose offset is
  past the class size (HUDPartText, DRange run-on).
  Unresolved today: 4 members whose type is a runtime-initialised descriptor in .bss (type@0x143b620, a position type).
"""
import argparse, bisect, json, struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from elf_info import Elf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("--json")
    ap.add_argument("--class", dest="classes", action="append")
    ap.add_argument("--layout", choices=["kz3", "kz2"], default="kz3",
                    help="kz2 = RTTIBin<1.58> engine (Killzone 2): see the RE notes")
    a = ap.parse_args()
    e = Elf(a.elf)
    data = next(p for p in e.ph if p["type"] == 1 and p["flags"] & 2)
    text = next(p for p in e.ph if p["type"] == 1 and not p["flags"] & 2)
    d = e.d
    kz2 = a.layout == "kz2"
    # KZ2 layout (found 2026-10-12, v1.01 EBOOT): a type pointer points at the kind word, there is no leading
    # 0xFFFFFFFF, so every KZ3 offset into a primitive/reference/container type descriptor is 4 smaller (sh). Class descriptor C (name at C+0x30,
    # 0xFFFFFFFF at C+0x34 as in KZ3) is referenced as T = C-4 (the kind word, e.g. 0x05000200, is at T); its base list is
    # at C+0x38 and members at C+0x3C (KZ3: +0x40/+0x44). Size is at C+0xC. Some classes have kind 0 in the file.
    sh = 4 if kz2 else 0

    def is_ro(va):
        return text["va"] <= va < text["va"] + text["filesz"]

    def is_data(va):
        return data["va"] <= va < data["va"] + data["memsz"]

    def cstr(va):
        try:
            s = e.cstr(va)
        except (ValueError, IndexError, TypeError):
            return None
        return s if s and s.isascii() and s.isprintable() and len(s) < 128 else None

    # 1. class descriptors
    recs = {}
    base, size = data["off"], data["filesz"]
    words = struct.unpack(f">{size // 4}I", d[base:base + size - size % 4])
    for i in range(len(words) - 20):
        if kz2:
            if words[i + 1] != 0xFFFFFFFF or i < 12:
                continue
            nm, bp, mp = words[i], words[i + 2], words[i + 3]
            if not (is_ro(nm) and (bp == 0 or is_data(bp) or is_ro(bp)) and (mp == 0 or is_data(mp) or is_ro(mp))
                    and (not bp or not mp or (bp <= mp and mp - bp < 0x400))):
                continue
            name = cstr(nm)
            if name and name.isidentifier() and words[i - 9] < 0x100000:
                va = data["va"] + 4 * (i - 12) - 4
                recs[va] = dict(name=name, bases_ptr=bp, members_ptr=mp, kind=words[i - 13], w08=words[i - 10],
                                size=words[i - 9])
            continue
        if words[i] != 0xFFFFFFFF or words[i + 1] >> 24 != 0x05 or words[i + 13] != 0xFFFFFFFF:
            continue
        nm, bp, mp = words[i + 12], words[i + 16], words[i + 17]
        if not (is_ro(nm) and (bp == 0 or is_data(bp)) and (mp == 0 or is_data(mp)) and (not bp or not mp or (bp <= mp and mp - bp < 0x400))):
            continue
        name = cstr(nm)
        if name and name.isidentifier():
            va = data["va"] + 4 * i
            recs[va] = dict(name=name, bases_ptr=bp, members_ptr=mp, kind=words[i + 1], w08=words[i + 2],
                            size=words[i + 3])
    bounds = sorted({r[k] for r in recs.values() for k in ("bases_ptr", "members_ptr")} - {0})

    types = {}  # name -> primitive/enum info, for core.py

    def note_type(t, name):
        kind = e.u32(t + 4 - sh)
        info = dict(kind=f"{kind:#010x}", size=(kind >> 16) & 0xFF)
        if kind >> 24 == 4:  # enum: +0xC -> (value, name ptr) pairs, ends at a null name
            vals, p = {}, e.u32(t + 12 - sh)
            while p and is_ro(e.u32(p + 4) or 0) and len(vals) < 512:
                vals[e.u32(p)] = cstr(e.u32(p + 4))
                p += 8
            info["values"] = {str(k): v for k, v in vals.items()}
        types[name] = info

    def type_name(t, depth=0):
        """Name of the type a descriptor describes. kind top byte 0x02 = reference to the target at +8
        (+0x0C -> "Ref": `Name*`, "cptr": `Name^`), 0x03 = container of the element type at +8
        (+0x0C -> "Array": `Name[]`, "TinyArray": `Name[tiny]`), a class record = its
        name, anything else with a name pointer at +8 / +0x30 = primitive or enum."""
        if t in recs:
            return recs[t]["name"]
        if depth < 6 and e.u32(t + 4 - sh) is not None and (kz2 or e.u32(t) == 0xFFFFFFFF):
            top = e.u32(t + 4 - sh) >> 24
            tgt = e.u32(t + 8 - sh)
            if top in (2, 3) and is_data(tgt):
                inner = type_name(tgt, depth + 1)
                tag = cstr(e.u32(e.u32(t + 12 - sh)) or 0) if is_data(e.u32(t + 12 - sh)) else None
                suffix = {"Ref": "*", "cptr": "^", "Array": "[]", "TinyArray": "[tiny]"}.get(tag)
                return inner + (suffix or ("*" if top == 2 else "[]"))
            for off in (8 - sh, 0x30 - sh):
                s = cstr(e.u32(t + off) or 0)
                if s:
                    if top in (1, 4):
                        note_type(t, s)
                    return s
        for k in range(4):
            w = e.u32(t + 4 * k)
            if w and is_ro(w):
                s = cstr(w)
                if s:
                    return s
        return f"type@{t:#x}"

    out = []
    for va, r in sorted(recs.items(), key=lambda kv: kv[1]["name"]):
        if a.classes and r["name"] not in a.classes:
            continue
        def next_bound(x):
            i = bisect.bisect_right(bounds, x)
            return bounds[i] if i < len(bounds) else x + 0x1C * 256

        bases, base_words = [], []
        bp, mp = r["bases_ptr"], r["members_ptr"]
        if bp:
            p = bp
            while (not mp or p < mp) and e.u32(p) in recs:
                bn = recs[e.u32(p)]["name"]
                base_words.append((bn, e.u32(p + 4)))
                if bn != r["name"] and bn not in bases:  # duplicates / self entries occur (RTTIRefObject, BaseResource)
                    bases.append(bn)
                p += 8
        end = next_bound(mp) if mp else 0
        members, p, group = [], mp, None
        while mp and p + 0x1C <= end and len(members) < 512:
            t, ow, nm = e.u32(p), e.u32(p + 4), e.u32(p + 8)
            name = cstr(nm) if nm else None
            if t == 0 and name:
                group = name
            elif t and name:
                tn = type_name(t)
                if tn.startswith("type@") and (ow >> 16) >= r["size"]:
                    break  # ran past the real list into unrelated data (HUDPartText, DRange)
                members.append(dict(name=name, type=tn, offset=ow >> 16, flags=ow & 0xFFFF, group=group))
            else:
                break
            p += 0x1C
        out.append(dict(name=r["name"], record=f"{va:#x}", size=r["size"], kind=f"{r['kind']:#010x}",
                        bases=bases, base_words=base_words, members=members))

    if a.json:
        json.dump(dict(classes=out, types=types), open(a.json, "w"), indent=1)
    print(f"classes: {len(out)}  members: {sum(len(c['members']) for c in out)}")
    if a.classes:
        for c in out:
            print(f"\nclass {c['name']} : {', '.join(c['bases']) or '-'}   size {c['size']:#x}  kind {c['kind']}  @{c['record']}")
            for m in c["members"]:
                print(f"  +{m['offset']:#06x} {m['type']:<24} {m['name']:<28} flags {m['flags']:#06x}  [{m['group']}]")


if __name__ == "__main__":
    main()
