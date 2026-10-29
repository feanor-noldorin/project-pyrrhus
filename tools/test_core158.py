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


def expect_error(label, fn, *a):
    try:
        fn(*a)
    except core.DecodeError:
        return check(label, True)
    return check(label, False)


def tex_blob(w=8, h=8, pf=19, mips=1, cube=False, cf=1):
    """Synthetic Texture payload in the layout of Killzone2_Blender's notes (all values made up here)."""
    lvl = [core._tex_level_bytes(pf, max(1, w >> i), max(1, h >> i)) for i in range(mips)]
    face = core._align(sum(lvl), 128)
    payload = face * (6 if cube else 1)
    rsx_fmt = {19: 0x86, 5: 0x85}[pf]
    rsx = bytes([rsx_fmt, mips, 2, 1 if cube else 0]) + bytes.fromhex("0000aae4") + struct.pack(">HHH", w, h, 1) + bytes(2) \
        + bytes(4) + bytes(4)
    return (struct.pack(">III", payload + 128, 0x01050000, payload) + struct.pack(">IIII", 1, 0, 128, payload - (face - sum(lvl)))
            + rsx + b"\x50" * 80 + bytes(payload))


def tex_fields(w=8, h=8, pf=19, mips=1, cube=False, cf=1):
    return {"Format": {"Width": w, "Height": h, "PixelFormat": f"X ({pf})", "MemoryType": "SYSTEM_MEMORY (0)"},
            "Type": "CubeMap (2)" if cube else "2D (0)", "NumSurfaces": mips, "CreationFlags": f"static ({cf})"}


def payload_tests():
    """RTTIBin<1.58> payload checks, synthetic bytes. Layouts: format notes of Killzone2_Blender by Tzeentchnet (MIT)."""
    ok = True
    # Texture: 2D DXT1 with a mip chain, a cubemap, and the failure modes
    for label, kw in (("2D DXT1 8x8, 4 mips", dict(mips=4)), ("cubemap DXT1 16x16, 5 mips", dict(w=16, h=16, mips=5, cube=True)),
                      ("2D RGBA8 4x4", dict(w=4, h=4, pf=5))):
        info = core.check_texture(tex_blob(**kw), tex_fields(**kw))
        ok &= check(f"Texture {label}: layout accepted, payload {info['payload']}", info["payload"] % 128 == 0 and info["faces"] == (6 if kw.get("cube") else 1))
    good = tex_blob(mips=4)
    ok &= expect_error("Texture with a wrong constant word rejected", core.check_texture, good[:4] + bytes(4) + good[8:], tex_fields(mips=4))
    ok &= expect_error("Texture with a short payload rejected", core.check_texture, good[:-1], tex_fields(mips=4))
    ok &= expect_error("Texture whose descriptor width differs rejected", core.check_texture, good, tex_fields(w=16, mips=4))
    ok &= expect_error("Texture whose fill bytes differ rejected", core.check_texture, good[:60] + b"\x00" + good[61:], tex_fields(mips=4))
    # VertexArrayResource: 2 streams, 3 vertices, second stream aligned
    def vtx(start):
        pad = (-start) % 4
        b = bytes(pad) + struct.pack(">iii", 3, 3, 2)
        b += struct.pack(">iii", 33, 6, 1) + struct.pack(">IBBBB", 0, 0, 1, 3, 0)          # stream 0: position 3 x s16 norm, stride 6
        b += struct.pack(">iii", 33, 5, 1) + struct.pack(">IBBBB", 7, 0, 4, 4, 0)          # stream 1 declares 4 x u8, stride 5
        for stride in (6, 5):
            b += bytes((-(start + len(b))) % 4) + bytes(3 * stride)
        return b
    for start in (0, 1, 2, 3):
        b = vtx(start)
        info = core.check_vertex_array(b, start)
        ok &= check(f"VertexArray at file offset %4 = {start}: 3 vertices, 2 streams", info["vertices"] == 3 and len(info["streams"]) == 2)
    ok &= expect_error("VertexArray with a stray byte rejected", core.check_vertex_array, vtx(0) + b"\x00", 0)
    ok &= expect_error("VertexArray with a truncated stream rejected", core.check_vertex_array, vtx(0)[:-1], 0)
    # IndexArrayResource: 3 indices => 2 bytes of padding to 4; 6 indices => none
    for n in (3, 6):
        b = struct.pack(">i", n) + struct.pack(">II", 1, 2) + struct.pack(f">{n}H", *range(n)) + bytes(2 * (n % 2))
        ok &= check(f"IndexArray with {n} indices accepted", core.check_index_array(b, 0)["indices"] == n)
    ok &= expect_error("IndexArray with non-zero padding rejected", core.check_index_array,
                       struct.pack(">i", 3) + struct.pack(">II", 1, 2) + struct.pack(">3H", 0, 1, 2) + b"\x00\x01", 0)
    # ShaderResource
    sh = b"\x00" * 8 + b"SHO\x08" + bytes(20)
    ok &= check("ShaderResource size + SHO object accepted", core.check_shader(struct.pack(">I", len(sh)) + sh)["size"] == len(sh))
    ok &= expect_error("ShaderResource with a wrong size rejected", core.check_shader, struct.pack(">I", len(sh) + 4) + sh)
    # ES00: 2 joints, pose at +0x14, parents at +0x18
    es = bytearray(0x2C + 2 * 48 + 4)
    es[:4] = b"ES00"
    struct.pack_into(">I", es, 8, len(es))
    struct.pack_into(">H", es, 12, 2)
    struct.pack_into(">I", es, 0x14, 0x2C - 0x14)                 # pose
    struct.pack_into(">I", es, 0x18, 0x2C + 96 - 0x18)            # parents
    for j in range(2):
        struct.pack_into(">4f", es, 0x2C + 48 * j, 0, 0, 0, 1)
    struct.pack_into(">2H", es, 0x2C + 96, 0xFFFF, 0)
    ok &= check("ES00 two joints, parent before child", core.check_es00(bytes(es))["parents"] == (0xFFFF, 0))
    bad = bytearray(es); struct.pack_into(">2H", bad, 0x2C + 96, 1, 0xFFFF)
    ok &= expect_error("ES00 parent after child rejected", core.check_es00, bytes(bad))
    ok &= expect_error("ES00 with a wrong total size rejected", core.check_es00, bytes(es) + b"\x00")
    ok &= check("empty EdgeAnimSkeleton is accepted as none", core.check_es00(b"") is None)
    # EA02: 5 frames over 2 s (frequency 2), two frame sets (base 0 and the sentinel at frame 4)
    ea = bytearray(0x54 + 8)
    ea[:4] = b"EA02"
    struct.pack_into(">ff", ea, 4, 2.0, 2.0)
    struct.pack_into(">HHHH", ea, 12, 0x60, 3, 5, 2)
    struct.pack_into(">I", ea, 0x38, 0x54 - 0x38)
    struct.pack_into(">HHHH", ea, 0x54, 0, 3, 4, 0)
    ok &= check("EA02 header accepted", core.check_ea02(bytes(ea), 2.0)["framesets"] == 2)
    ok &= expect_error("EA02 with a different Duration field rejected", core.check_ea02, bytes(ea), 3.0)
    badf = bytearray(ea); struct.pack_into(">f", badf, 8, 5.0)
    ok &= expect_error("EA02 with a wrong sample frequency rejected", core.check_ea02, bytes(badf), 2.0)
    bads = bytearray(ea); struct.pack_into(">H", bads, 0x58, 3)
    ok &= expect_error("EA02 without the sentinel frame set rejected", core.check_ea02, bytes(bads), 2.0)
    # object ids: reversed 4-byte groups, self-inverse
    h = "00112233445566778899aabbccddeeff"
    ok &= check("object id display = 4-byte groups reversed", core.object_id_display(h) == "33221100" "77665544" "bbaa9988" "ffeeddcc")
    ok &= check("object id display is its own inverse", core.object_id_display(core.object_id_display(h)) == h)
    return ok


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
    ok &= payload_tests()
    # 1.73 header still uses the count m and 20-byte entries
    c = core.Core(build(magic=b"RTTIBin<1.73>"), s)
    ok &= check("1.73 header path unchanged", not c.v158 and c.nhash == 0 and len(c.hashes) == 1)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
