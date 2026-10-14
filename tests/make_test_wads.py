"""Generate small synthetic WADs for testing (no copyrighted data)."""
import io, random, struct, sys, zipfile
from pathlib import Path

def lump_wad(lumps, ident=b"PWAD"):
    data = b""; d = b""; off = 12
    for name, content in lumps:
        d += struct.pack("<ii8s", off + len(data), len(content), name.encode().ljust(8, b"\0"))
        data += content
    return ident + struct.pack("<ii", len(lumps), 12 + len(data)) + data + d

def room_map(name, things, rooms=4):
    verts, lines, sides, sectors = [], [], [], []
    for r in range(rooms):
        x0, y0 = r * 600, (r % 2) * 400
        base = len(verts)
        verts += [(x0, y0), (x0 + 512, y0), (x0 + 512, y0 + 512), (x0, y0 + 512)]
        sectors.append((0, 128 + 16 * r, 9 if r == 2 else 0))
        sd = len(sides)
        sides.append(len(sectors) - 1)
        for i in range(4):
            lines.append((base + i, base + (i + 1) % 4, 1, 0, 0, sd, 0xFFFF))
    v = b"".join(struct.pack("<hh", *x) for x in verts)
    l = b"".join(struct.pack("<HHHHHHH", *x) for x in lines)
    sdb = b"".join(struct.pack("<hh8s8s8sH", 0, 0, b"-", b"-", b"STARTAN1", s) for s in sides)
    sec = b"".join(struct.pack("<hh8s8shHH", f, c, b"FLOOR4_8", b"CEIL3_5", 160, sp, 0) for f, c, sp in sectors)
    th = b"".join(struct.pack("<hhhhH", x, y, 0, t, fl) for x, y, t, fl in things)
    return [(name, b""), ("THINGS", th), ("LINEDEFS", l), ("SIDEDEFS", sdb), ("VERTEXES", v), ("SECTORS", sec)]

def rnd_things(seed, mons, items, start=True):
    r = random.Random(seed); out = []
    if start: out.append((100, 100, 1, 7))
    for t, n in mons.items():
        for _ in range(n): out.append((r.randint(20, 2000), r.randint(20, 900), t, 7))
    for t, n in items.items():
        for _ in range(n): out.append((r.randint(20, 2000), r.randint(20, 900), t, 7))
    return out

def build(outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    # 1. gentle 3-map Doom 2 wad
    lumps = []
    for i in range(1, 4):
        th = rnd_things(i, {3004: 10, 9: 6, 3001: 5, 3002: 2}, {2011: 8, 2012: 4, 2007: 10, 2008: 6, 2018: 1, 2001: 1, 5: 1})
        lumps += room_map(f"MAP{i:02d}", th)
    (outdir / "gentle_v1.wad").write_bytes(lump_wad(lumps))
    # 2. slaughter single map
    th = rnd_things(9, {3001: 300, 3005: 80, 3003: 40, 66: 40, 67: 30, 64: 10, 16: 2}, {2049: 30, 2046: 30, 17: 12, 2003: 1, 2004: 1, 2006: 1, 2013: 4, 83: 4, 2019: 3})
    (outdir / "SLAUGHTER-TEST.wad").write_bytes(lump_wad(room_map("MAP01", th)))
    # 3. doom1 style episode with keys/secrets, few monsters
    lumps = []
    for i in range(1, 4):
        th = rnd_things(20 + i, {3004: 4, 3001: 3}, {5: 1, 6: 1, 13: 1, 2012: 3, 2007: 3})
        lumps += room_map(f"E1M{i}", th, rooms=6)
    (outdir / "e1_walk.wad").write_bytes(lump_wad(lumps))
    # 4. resource wad
    (outdir / "resources.wad").write_bytes(lump_wad([("S_START", b""), ("TROOA1", b"x" * 10), ("S_END", b""), ("PLAYPAL", b"\0" * 768)]))
    # 5. pk3 with embedded wad
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("maps/test.wad", (outdir / "gentle_v1.wad").read_bytes())
        z.writestr("MAPINFO", 'map MAP01 "First Steps"\n{\n}\n')
    (outdir / "bundle.pk3").write_bytes(buf.getvalue())
    # 6. skill-dependent placement: 50% all skills, 30% medium+hard, 20% hard only
    r = random.Random(5); th = [(100, 100, 1, 7)]
    for _ in range(200):
        fl = r.choices([7, 6, 4], [5, 3, 2])[0]
        th.append((r.randint(20, 2000), r.randint(20, 900), r.choice([3004, 3001, 3002, 3005]), fl))
    (outdir / "skills.wad").write_bytes(lump_wad(room_map("MAP01", th)))
    # invalid files
    (outdir / "bad_magic.wad").write_bytes(b"XXXX" + b"\0" * 100)
    good = (outdir / "gentle_v1.wad").read_bytes()
    (outdir / "truncated.wad").write_bytes(good[:len(good) - 40])

if __name__ == "__main__":
    build(Path(sys.argv[1]))
