"""WAD / PK3 reading, validation and map extraction.

Supported:
  * IWAD / PWAD containers (header + directory validation)
  * PK3 (zip) containers, including embedded WADs and UDMF maps/*.wad / maps/*.txt
  * Map formats: Doom binary, Hexen binary, UDMF (TEXTMAP)
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple

MAX_LUMPS = 400_000
MAX_EMBEDDED_WAD_BYTES = 300 * 1024 * 1024

MAP_NAME_RE = re.compile(r"^(E[1-9]M[1-9]|MAP\d\d)$")
BINARY_MAP_LUMPS = {
    "THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS", "SSECTORS",
    "NODES", "SECTORS", "REJECT", "BLOCKMAP", "BEHAVIOR", "SCRIPTS",
}


class WadError(Exception):
    """Raised when a file is not a valid WAD / PK3."""


@dataclass
class Lump:
    name: str
    offset: int
    size: int


@dataclass
class Thing:
    x: int
    y: int
    type: int
    skills: int      # bitmask: 1=easy(HNTR/ITYTD), 2=medium(HMP), 4=hard(UV/NM)
    ambush: bool
    single: bool     # appears in single player


@dataclass
class MapData:
    name: str
    fmt: str                                   # doom | hexen | udmf
    things: List[Thing] = field(default_factory=list)
    vertices: List[Tuple[float, float]] = field(default_factory=list)
    # (v1, v2, flags, special, tag, right_sidedef, left_sidedef)
    linedefs: List[Tuple[int, int, int, int, int, int, int]] = field(default_factory=list)
    sidedef_sector: List[int] = field(default_factory=list)
    # (floor_h, ceil_h, special, tag)
    sectors: List[Tuple[int, int, int, int]] = field(default_factory=list)
    title: Optional[str] = None
    source: str = ""                          # which (embedded) file it came from


class WadFile:
    """Random-access reader over a WAD container (file object or bytes)."""

    def __init__(self, fh: BinaryIO, label: str = "wad"):
        self.fh = fh
        self.label = label
        fh.seek(0, io.SEEK_END)
        self.size = fh.tell()
        fh.seek(0)
        self.warnings: List[str] = []
        self.ident, self.lumps = self._read_directory()

    # -- validation ------------------------------------------------------
    def _read_directory(self) -> Tuple[str, List[Lump]]:
        if self.size < 12:
            raise WadError("File is smaller than a WAD header (12 bytes).")
        self.fh.seek(0)
        header = self.fh.read(12)
        ident = header[:4]
        if ident not in (b"IWAD", b"PWAD"):
            raise WadError(f"Bad magic {ident!r}: expected 'IWAD' or 'PWAD'.")
        numlumps, dirofs = struct.unpack("<ii", header[4:])
        if numlumps < 0 or numlumps > MAX_LUMPS:
            raise WadError(f"Implausible lump count ({numlumps}).")
        if dirofs < 12 or dirofs + numlumps * 16 > self.size:
            raise WadError("Directory lies outside the file (truncated or corrupt WAD).")
        self.fh.seek(dirofs)
        raw = self.fh.read(numlumps * 16)
        if len(raw) != numlumps * 16:
            raise WadError("Could not read the full lump directory.")
        lumps: List[Lump] = []
        bad = 0
        for i in range(numlumps):
            off, size, name = struct.unpack_from("<ii8s", raw, i * 16)
            name = name.split(b"\0", 1)[0].decode("latin-1").upper()
            if size < 0 or (size > 0 and (off < 12 or off + size > self.size)):
                bad += 1
                size = 0
            lumps.append(Lump(name, off, size))
        if bad:
            self.warnings.append(f"{bad} lump(s) point outside the file and were ignored.")
            if numlumps and bad / numlumps > 0.25:
                raise WadError("More than 25% of lumps are corrupt.")
        return ident.decode(), lumps

    def read(self, lump: Lump) -> bytes:
        if lump.size <= 0:
            return b""
        self.fh.seek(lump.offset)
        return self.fh.read(lump.size)

    # -- maps ------------------------------------------------------------
    def iter_map_slices(self) -> Iterator[Tuple[str, str, Dict[str, Lump]]]:
        """Yield (map_name, fmt_hint, {lumpname: Lump}) for each map found."""
        L = self.lumps
        n = len(L)
        seen = set()
        for i, lump in enumerate(L):
            if not MAP_NAME_RE.match(lump.name) or lump.name in seen:
                continue
            group: Dict[str, Lump] = {}
            j = i + 1
            udmf = False
            while j < n and j <= i + 40:
                nm = L[j].name
                if nm == "TEXTMAP":
                    udmf = True
                    group["TEXTMAP"] = L[j]
                elif nm == "ENDMAP":
                    break
                elif nm in BINARY_MAP_LUMPS and not udmf:
                    group.setdefault(nm, L[j])
                elif udmf and nm in ("ZNODES", "BEHAVIOR", "SCRIPTS", "DIALOGUE", "REJECT", "BLOCKMAP", "SECTORS", "SIDEDEFS", "LINEDEFS", "VERTEXES", "SEGS", "SSECTORS", "NODES", "THINGS"):
                    pass
                else:
                    break
                j += 1
            if "TEXTMAP" in group:
                seen.add(lump.name)
                yield lump.name, "udmf", group
            elif {"THINGS", "LINEDEFS", "VERTEXES"} <= set(group):
                seen.add(lump.name)
                yield lump.name, ("hexen" if "BEHAVIOR" in group else "doom"), group

    def lump_names(self) -> List[str]:
        return [l.name for l in self.lumps]

    def find(self, name: str) -> Optional[Lump]:
        for l in self.lumps:
            if l.name == name:
                return l
        return None

    def load_maps(self) -> Iterator[MapData]:
        for name, fmt, group in self.iter_map_slices():
            try:
                if fmt == "udmf":
                    m = parse_udmf(name, self.read(group["TEXTMAP"]).decode("utf-8", "replace"))
                else:
                    m = parse_binary_map(name, fmt, {k: self.read(v) for k, v in group.items()
                                                      if k in ("THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SECTORS")})
            except Exception as exc:  # corrupt single map should not kill the whole WAD
                self.warnings.append(f"{name}: could not parse ({exc}).")
                continue
            m.source = self.label
            yield m


# ---------------------------------------------------------------------------
# Binary map parsing
# ---------------------------------------------------------------------------

def parse_binary_map(name: str, fmt: str, data: Dict[str, bytes]) -> MapData:
    m = MapData(name=name, fmt=fmt)

    raw = data.get("VERTEXES", b"")
    for i in range(len(raw) // 4):
        x, y = struct.unpack_from("<hh", raw, i * 4)
        m.vertices.append((x, y))

    raw = data.get("LINEDEFS", b"")
    if fmt == "hexen":
        # flags(h) special(B) args(5B) v1 v2 (H) right left (H)... actual: v1,v2,flags,special,a0-a4,right,left
        sz = 16
        for i in range(len(raw) // sz):
            v1, v2, flags, special, a0, a1, a2, a3, a4, r, l = struct.unpack_from("<HHHBBBBBBHH", raw, i * sz)
            m.linedefs.append((v1, v2, flags, special, a0, _sd(r), _sd(l)))
    else:
        sz = 14
        for i in range(len(raw) // sz):
            v1, v2, flags, special, tag, r, l = struct.unpack_from("<HHHHHHH", raw, i * sz)
            m.linedefs.append((v1, v2, flags, special, tag, _sd(r), _sd(l)))

    raw = data.get("SIDEDEFS", b"")
    for i in range(len(raw) // 30):
        sector = struct.unpack_from("<H", raw, i * 30 + 28)[0]
        m.sidedef_sector.append(sector)

    raw = data.get("SECTORS", b"")
    for i in range(len(raw) // 26):
        fl, ce = struct.unpack_from("<hh", raw, i * 26)
        special, tag = struct.unpack_from("<HH", raw, i * 26 + 22)
        m.sectors.append((fl, ce, special, tag))

    raw = data.get("THINGS", b"")
    if fmt == "hexen":
        sz = 20
        for i in range(len(raw) // sz):
            tid, x, y, z, ang, typ, flags = struct.unpack_from("<hhhhhhH", raw, i * sz)
            m.things.append(Thing(x, y, typ, flags & 7, bool(flags & 8), bool(flags & 0x100)))
    else:
        sz = 10
        for i in range(len(raw) // sz):
            x, y, ang, typ, flags = struct.unpack_from("<hhhhH", raw, i * sz)
            m.things.append(Thing(x, y, typ, flags & 7, bool(flags & 8), not (flags & 16)))
    return m


def _sd(v: int) -> int:
    return -1 if v == 0xFFFF else v


# ---------------------------------------------------------------------------
# UDMF
# ---------------------------------------------------------------------------
_BLOCK_RE = re.compile(r"(thing|vertex|linedef|sidedef|sector)\s*\{([^}]*)\}", re.I)
_PROP_RE = re.compile(r'(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]+?)\s*;')
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _val(s: str):
    s = s.strip()
    if s.startswith('"'):
        return s[1:-1]
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if low.startswith("0x"):
            return int(low, 16)
        return float(s) if ("." in s or "e" in low) else int(s)
    except ValueError:
        return s


def parse_udmf(name: str, text: str) -> MapData:
    text = _COMMENT_RE.sub("", text)
    m = MapData(name=name, fmt="udmf")
    for blk in _BLOCK_RE.finditer(text):
        kind = blk.group(1).lower()
        props = {k.lower(): _val(v) for k, v in _PROP_RE.findall(blk.group(2))}
        if kind == "vertex":
            m.vertices.append((float(props.get("x", 0)), float(props.get("y", 0))))
        elif kind == "linedef":
            flags = 0
            if props.get("twosided"):
                flags |= 4
            if props.get("blocking"):
                flags |= 1
            m.linedefs.append((int(props.get("v1", 0)), int(props.get("v2", 0)), flags,
                               int(props.get("special", 0) or 0), int(props.get("id", 0) or 0),
                               int(props.get("sidefront", -1)), int(props.get("sideback", -1))))
        elif kind == "sidedef":
            m.sidedef_sector.append(int(props.get("sector", 0)))
        elif kind == "sector":
            m.sectors.append((int(props.get("heightfloor", 0) or 0), int(props.get("heightceiling", 0) or 0),
                              int(props.get("special", 0) or 0), int(props.get("id", 0) or 0)))
        elif kind == "thing":
            skills = 0
            has_skill_key = any(f"skill{i}" in props for i in range(1, 6))
            if not has_skill_key:
                skills = 7
            else:
                if props.get("skill1") or props.get("skill2"):
                    skills |= 1
                if props.get("skill3"):
                    skills |= 2
                if props.get("skill4") or props.get("skill5"):
                    skills |= 4
            single = props.get("single", True)
            m.things.append(Thing(int(props.get("x", 0)), int(props.get("y", 0)),
                                  int(props.get("type", 0)), skills,
                                  bool(props.get("ambush", False)), bool(single)))
    return m


# ---------------------------------------------------------------------------
# Container handling (WAD or PK3)
# ---------------------------------------------------------------------------

@dataclass
class Container:
    kind: str                       # IWAD | PWAD | PK3
    size: int
    maps: List[MapData]
    lump_names: List[str]           # union of lump/entry names (upper-case)
    warnings: List[str]
    text_lumps: Dict[str, str]      # MAPINFO / UMAPINFO / DEHACKED / etc (decoded, truncated)
    custom_code: List[str]          # DECORATE, ZSCRIPT, DEHACKED, ...
    embedded_wads: int = 0


_TEXT_LUMPS = ("MAPINFO", "UMAPINFO", "ZMAPINFO", "GAMEINFO")
_CODE_LUMPS = ("DECORATE", "ZSCRIPT", "DEHACKED", "DEHACKED.LMP", "ACTORS", "MODELDEF", "GLDEFS")


def sniff(fh: BinaryIO) -> str:
    fh.seek(0)
    head = fh.read(4)
    fh.seek(0)
    if head in (b"IWAD", b"PWAD"):
        return "WAD"
    if head[:2] == b"PK":
        return "PK3"
    return "UNKNOWN"


def open_container(fh: BinaryIO, max_zip_uncompressed: int = 1 << 30) -> Container:
    """Validate and parse a WAD or PK3. Raises WadError when invalid."""
    kind = sniff(fh)
    if kind == "WAD":
        w = WadFile(fh, "main")
        return _from_wad(w, w.ident)
    if kind == "PK3":
        return _from_pk3(fh, max_zip_uncompressed)
    raise WadError("Not a WAD or PK3: file signature is neither IWAD/PWAD nor ZIP.")


def _from_wad(w: WadFile, kind: str) -> Container:
    names = w.lump_names()
    text, code = {}, []
    for nm in _TEXT_LUMPS:
        l = w.find(nm)
        if l:
            text[nm] = w.read(l)[:200_000].decode("utf-8", "replace")
    for nm in _CODE_LUMPS:
        if w.find(nm):
            code.append(nm)
    maps = sorted(w.load_maps(), key=_map_sort_key)   # E1M1..E4M9, then MAP01..MAP99
    _apply_titles(maps, text)
    return Container(kind, w.size, maps, names, list(w.warnings), text, code)


def _from_pk3(fh: BinaryIO, limit: int) -> Container:
    try:
        zf = zipfile.ZipFile(fh)
    except zipfile.BadZipFile as exc:
        raise WadError(f"Invalid PK3 (zip) archive: {exc}")
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise WadError("PK3 archive is empty.")
    if sum(i.file_size for i in infos) > limit:
        raise WadError("PK3 expands to more than the allowed size (possible zip bomb).")
    fh.seek(0, io.SEEK_END)
    size = fh.tell()
    names, maps, warnings, text, code = [], [], [], {}, []
    embedded = 0

    for info in infos:
        path = info.filename.replace("\\", "/")
        base = path.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0].upper()
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        names.append(stem)
        top = path.split("/", 1)[0].lower()

        if stem in _TEXT_LUMPS and stem not in text:
            text[stem] = zf.read(info)[:200_000].decode("utf-8", "replace")
        if stem in _CODE_LUMPS or base.upper() in _CODE_LUMPS:
            code.append(stem)

        if ext == "wad" and info.file_size <= MAX_EMBEDDED_WAD_BYTES:
            try:
                w = WadFile(io.BytesIO(zf.read(info)), path)
                embedded += 1
                names.extend(w.lump_names())
                for m in w.load_maps():
                    maps.append(m)
                warnings.extend(f"{path}: {x}" for x in w.warnings)
            except WadError as exc:
                warnings.append(f"Embedded {path} is not a valid WAD: {exc}")
        elif top == "maps" and ext in ("txt", "udmf", "map"):
            # Loose UDMF map: maps/MAP01.txt  (TEXTMAP content directly)
            raw = zf.read(info)
            if MAP_NAME_RE.match(stem) and b"namespace" in raw[:400].lower():
                try:
                    m = parse_udmf(stem, raw.decode("utf-8", "replace"))
                    m.source = path
                    maps.append(m)
                except Exception as exc:
                    warnings.append(f"{path}: could not parse ({exc}).")

    # de-duplicate maps by name (later entries override earlier ones, like a real load order)
    uniq: Dict[str, MapData] = {}
    for m in maps:
        uniq[m.name] = m
    maps = sorted(uniq.values(), key=_map_sort_key)
    _apply_titles(maps, text)
    return Container("PK3", size, maps, names, warnings, text, sorted(set(code)), embedded)


def _map_sort_key(m: MapData):
    mm = re.match(r"E(\d)M(\d)", m.name)
    if mm:
        return (0, int(mm.group(1)), int(mm.group(2)))
    return (1, int(m.name[3:]), 0)


def _apply_titles(maps: List[MapData], text: Dict[str, str]) -> None:
    titles: Dict[str, str] = {}
    for src in (text.get("MAPINFO", ""), text.get("ZMAPINFO", "")):
        for mm in re.finditer(r'(?im)^\s*map\s+(\w+)\s+"([^"]+)"', src):
            titles[mm.group(1).upper()] = mm.group(2)
    um = text.get("UMAPINFO", "")
    for mm in re.finditer(r'(?is)map\s*=\s*(\w+)\s*\{(.*?)\}', um):
        t = re.search(r'(?i)levelname\s*=\s*"([^"]+)"', mm.group(2))
        if t:
            titles[mm.group(1).upper()] = t.group(1)
    for m in maps:
        m.title = titles.get(m.name)
