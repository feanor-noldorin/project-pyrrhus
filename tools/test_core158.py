#!/usr/bin/env python3
"""Host test for the RTTIBin<1.58> parts of tools/core.py. Synthetic bytes only, no game data.

Covers: the object list header (32-byte entries, no count m), the three token forms (81 00 ff ff / 81 00 80 + offset /
00 + offset), a nonzero entry tail being rejected, the Lua 5.1 chunk length parser, and that a <1.73> header still
takes the old 20-byte-entry path."""
import json, os, struct, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core


def schema():
    j = {"classes": [{"name": "Foo", "bases": [], "base_words": [], "members": [], "size": 8}], "types": {}}
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(j, f)
    f.close()
    try:
        return core.Schema(f.name)
    finally:
        os.unlink(f.name)


def tok(sz, align=0x10, f=b"\x81\x00\xff\xff", owner=0):
    return bytes([sz]) + bytes([align]) + f + bytes([owner])


def build(magic=b"RTTIBin<1.58>", entry_tail=bytes(12), alloc=tok(8), a=b"", b=b""):
    h = magic + b"  \x01" + bytes(16)
    assert len(h) == 0x20
    types = bytes([1, 3]) + b"Foo"
    obj = bytes([1]) + bytes([0])                       # n = 1, root type index 0
    if magic.endswith(b"1.58>"):
        obj += bytes(16) + struct.pack(">I", 0) + entry_tail   # hash, stored length, 12 bytes
    else:
        obj += bytes([0]) + bytes(16) + struct.pack(">I", 0)    # count m, hash, stored length
    return h + types + obj + bytes([0, 0]) + bytes([0, 1]) + alloc + a + b"\x00\x00"


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    return cond


def main():
    s = schema()
    ok = True
    # header: one object, 32-byte entry
    c = core.Core(build(), s)
    ok &= check("1.58 header: v158 flag, 1 root", c.v158 and c.roots == [0] and c.hashes == [("00" * 16, 0)])
    c, probs = None, None
    path = tempfile.NamedTemporaryFile(suffix=".core", delete=False).name
    for label, data in (("minimal 1.58 file decodes to the end", build()),):
        open(path, "wb").write(data)
        c, probs = core.check_file(path, s)
        ok &= check(label, not probs and len(c.objects) == 1)
    # nonzero tail in the 32-byte entry is rejected
    try:
        core.Core(build(entry_tail=b"\x01" + bytes(11)), s)
        ok &= check("nonzero 12-byte entry tail rejected", False)
    except core.DecodeError:
        ok &= check("nonzero 12-byte entry tail rejected", True)
    # token forms
    for label, f in (("81 00 ff ff", b"\x81\x00\xff\xff"), ("81 00 80 + u32 offset", b"\x81\x00\x80\x80\x00\x0b\xe7\x80"),
                     ("00 + u32 offset", b"\x00\x80\x00\x15\x56\x00")):
        t = core.Core(build(), s)
        raw = bytes([0x81, 0x27, 0x88, 0x81, 0x00, 0x80]) + f + bytes([0x81, 0x01, 0x05])
        t.r = core.Reader(raw)
        sz, owner = t.token()
        ok &= check(f"token form {label}: size {0x2788}, owner 261, all bytes used", sz == 0x2788 and owner == 261 and t.r.p == len(raw))
    # Lua 5.1 chunk: header + empty main function (no code, constants, protos, debug)
    hdr = b"\x1bLuaQ\x00\x00\x04\x04\x04\x04\x00"
    fn = (b"\x00\x00\x00\x00"            # source name: size_t 0
          + b"\x00\x00\x00\x00" * 2        # linedefined, lastlinedefined
          + b"\x00\x00\x00\x02"            # nups, numparams, is_vararg, maxstack
          + b"\x00\x00\x00\x00"            # code
          + b"\x00\x00\x00\x00"            # constants
          + b"\x00\x00\x00\x00"            # protos
          + b"\x00\x00\x00\x00"            # line info
          + b"\x00\x00\x00\x00"            # locvars
          + b"\x00\x00\x00\x00")           # upvalue names
    chunk = hdr + fn
    ok &= check("Lua 5.1 chunk length", core.lua51_chunk_len(b"xx" + chunk + b"yy", 2) == len(chunk))
    # 1.73 header still uses the count m and 20-byte entries
    c = core.Core(build(magic=b"RTTIBin<1.73>"), s)
    ok &= check("1.73 header path unchanged", not c.v158 and c.nhash == 0 and len(c.hashes) == 1)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
