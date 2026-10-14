"""Render a map in the classic automap colour scheme.

Output is layered so the page can switch skill levels without re-rendering:
  * one opaque PNG with the level geometry
  * one transparent PNG per skill group with the thing markers (monsters, items...)
All layers have identical pixel dimensions.
"""
from __future__ import annotations

import io
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw

from .parser import MapData
from .things import thing_class

BG = (14, 14, 16)
COL_WALL = (252, 0, 0)          # one-sided
COL_FLOOR = (188, 120, 72)      # floor height change
COL_CEIL = (252, 252, 0)        # ceiling height change only
COL_SAME = (92, 92, 100)        # two-sided, no change
COL_SPECIAL = (0, 200, 255)     # lines with specials (doors, switches, teleports)
COL_SECRET = (255, 0, 255)      # secret-flag lines
THING_COL = {
    "monster": (255, 70, 70),
    "ammo": (255, 170, 40),
    "health": (70, 220, 90),
    "armor": (70, 140, 255),
    "key": (255, 255, 255),
    "start": (0, 255, 200),
}
SS = 2  # supersampling factor


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def render_layers(m: MapData, skill_bits: Dict[str, int], size: int = 1000) -> Optional[Tuple[bytes, Dict[str, bytes]]]:
    """Return (geometry_png, {skill_key: things_png}) or None if the map has no drawable lines."""
    verts = m.vertices
    if not verts or not m.linedefs:
        return None
    nv = len(verts)
    used = {i for l in m.linedefs for i in (l[0], l[1])}
    pts = [verts[i] for i in used if 0 <= i < nv]
    if not pts:
        return None
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    w, h = max(maxx - minx, 1), max(maxy - miny, 1)

    pad = 24 * SS
    big = size * SS
    scale = (big - 2 * pad) / max(w, h)
    iw, ih = int(w * scale) + 2 * pad, int(h * scale) + 2 * pad
    out_size = (max(1, iw // SS), max(1, ih // SS))

    def tx(x, y):
        return ((x - minx) * scale + pad, (maxy - y) * scale + pad)

    # ---- geometry layer
    img = Image.new("RGB", (iw, ih), BG)
    d = ImageDraw.Draw(img)
    sectors, sd_sec = m.sectors, m.sidedef_sector
    lw = max(2, int(SS * (1 + min(w, h) / 6000)))
    order = {COL_SAME: 0, COL_CEIL: 1, COL_FLOOR: 2, COL_WALL: 3, COL_SECRET: 4, COL_SPECIAL: 5}
    lines = []
    for (v1, v2, flags, special, tag, r, l) in m.linedefs:
        if not (0 <= v1 < nv and 0 <= v2 < nv):
            continue
        col = COL_WALL
        if l >= 0 and r >= 0 and r < len(sd_sec) and l < len(sd_sec):
            sr, sl = sd_sec[r], sd_sec[l]
            if 0 <= sr < len(sectors) and 0 <= sl < len(sectors):
                a, b = sectors[sr], sectors[sl]
                col = COL_FLOOR if a[0] != b[0] else COL_CEIL if a[1] != b[1] else COL_SAME
            else:
                col = COL_SAME
            if flags & 0x20:          # "secret" flag: looks like a wall on the automap, mark it
                col = COL_SECRET
        if special:
            col = COL_SPECIAL
        lines.append((order[col], col, v1, v2))
    lines.sort(key=lambda t: t[0])
    for _, col, v1, v2 in lines:
        d.line([tx(*verts[v1]), tx(*verts[v2])], fill=col, width=lw)
    geometry = _png(img.resize(out_size, Image.LANCZOS))

    # ---- one things layer per skill group
    rad = max(2.5 * SS, min(w, h) * scale / 450)
    layers: Dict[str, bytes] = {}
    for key, bit in skill_bits.items():
        ov = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for t in m.things:
            if not (t.skills & bit) or not t.single:
                continue
            cls = thing_class(t.type)
            col = THING_COL.get(cls)
            if not col:
                continue
            x, y = tx(t.x, t.y)
            r = rad * (1.5 if cls == "monster" else 1.0)
            od.ellipse([x - r, y - r, x + r, y + r], fill=col + (255,))
        layers[key] = _png(ov.resize(out_size, Image.LANCZOS))
    return geometry, layers
