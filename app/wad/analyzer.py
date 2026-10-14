"""Per-map and per-WAD statistics plus heuristic classification.

All numbers are computed for the Ultra-Violence skill unless stated otherwise,
single-player only. Classification is heuristic - see README for the rules.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional

from . import things as T
from .parser import Container, MapData

SKILLS = {"hntr": 1, "hmp": 2, "uv": 4}  # label -> thing skill bit
# Doom has 5 skill levels but only 3 distinct thing sets: 1+2 share a flag, 4+5 share a flag.
SKILL_NAMES = {"hntr": "I'm Too Young To Die / Hey, Not Too Rough",
               "hmp": "Hurt Me Plenty",
               "uv": "Ultra-Violence / Nightmare"}
SKILL_SHORT = {"hntr": "ITYTD / HNTR", "hmp": "HMP", "uv": "UV / NM"}


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# per-map
# ---------------------------------------------------------------------------

def _skill_stats(m: MapData, bit: int) -> dict:
    mon = Counter()
    tiers = Counter()
    hp = threat = 0.0
    drops = 0.0
    bosses = 0
    other_special = Counter()
    ammo_units = Counter()
    health = armor = 0
    weapons = set()
    keys = set()
    powerups = Counter()
    unknown = Counter()
    ambush = 0

    for t in m.things:
        if not (t.skills & bit) or not t.single:
            continue
        ty = t.type
        mo = T.MONSTERS.get(ty)
        if mo:
            mon[mo.name] += 1
            tiers[mo.tier] += 1
            hp += mo.hp
            threat += mo.threat
            drops += mo.drop
            ambush += 1 if t.ambush else 0
            if mo.boss:
                bosses += 1
        elif ty in T.SPECIAL:
            other_special[T.SPECIAL[ty]] += 1
            if ty == 88:
                bosses += 1
        elif ty in T.AMMO:
            _, kind, n = T.AMMO[ty]
            ammo_units[kind] += n
        elif ty in T.WEAPONS:
            name, kind, n = T.WEAPONS[ty]
            weapons.add(name)
            if kind:
                ammo_units[kind] += n
        elif ty in T.KEYS:
            keys.add(T.KEYS[ty])
        elif ty in T.POWERUPS:
            powerups[T.POWERUPS[ty]] += 1
        elif ty not in T.PLAYER_STARTS and ty != T.DM_START and ty != T.TELEPORT_DEST:
            unknown[ty] += 1
        if ty in T.HEALTH:
            health += T.HEALTH[ty][1]
        if ty in T.ARMOR:
            armor += T.ARMOR[ty][1]

    ammo_dmg = sum(T.DMG_PER[k] * n for k, n in ammo_units.items())
    n_mon = sum(mon.values())
    return {
        "monsters": n_mon,
        "by_type": dict(mon),
        "tiers": {str(k): tiers.get(k, 0) for k in (1, 2, 3, 4)},
        "hp": int(hp),
        "threat": round(threat, 1),
        "bosses": bosses,
        "ambush": ambush,
        "specials": dict(other_special),
        "ammo_units": dict(ammo_units),
        "ammo_dmg": int(ammo_dmg),
        "drop_dmg": int(drops),
        "health": health,
        "armor": armor,
        "weapons": sorted(weapons),
        "keys": sorted(keys),
        "powerups": dict(powerups),
        "unknown_things": dict(unknown),
    }


START_AMMO_DMG = 50 * T.DMG_PER["bullet"]  # pistol start


def analyze_map(m: MapData, skill: str = "uv") -> dict:
    s = {k: _skill_stats(m, b) for k, b in SKILLS.items()}
    uv = s[skill]   # stats of the selected skill group
    secrets = sum(1 for sec in m.sectors if sec[2] == 9)
    dm_starts = sum(1 for t in m.things if t.type == T.DM_START)
    p_starts = sum(1 for t in m.things if t.type in T.PLAYER_STARTS)
    n_mon = uv["monsters"]
    hp = uv["hp"]
    total_dmg = uv["ammo_dmg"] + uv["drop_dmg"] + START_AMMO_DMG
    coverage = total_dmg / hp if hp else None
    heavy = uv["tiers"]["3"] + uv["tiers"]["4"]
    heavy_share = heavy / n_mon if n_mon else 0.0

    # per-map slaughter score
    ms = clamp((n_mon - 100) / 400)
    hs = clamp((heavy_share - 0.10) / 0.40)
    ts = clamp((uv["threat"] - 300) / 1500)
    slaughter = round(100 * (0.5 * ms + 0.2 * hs + 0.3 * ts), 1)
    is_slaughter = (n_mon >= 250 and slaughter >= 45) or n_mon >= 400

    # per-map exploration score
    keys = len(uv["keys"])
    sectors = len(m.sectors)
    ks = clamp(keys / 3)
    ss = clamp(secrets / 6)
    sz = clamp((sectors - 300) / 1200)
    ds = 1 - clamp(n_mon / 200)
    exploration = round(100 * (0.30 * ks + 0.20 * ss + 0.35 * sz + 0.15 * ds), 1)

    return {
        "name": m.name,
        "title": m.title,
        "format": m.fmt,
        "source": m.source,
        "sectors": sectors,
        "linedefs": len(m.linedefs),
        "things": len(m.things),
        "secrets": secrets,
        "player_starts": p_starts,
        "dm_starts": dm_starts,
        "skills": s,
        "coverage": round(coverage, 2) if coverage is not None else None,
        "heavy_share": round(heavy_share, 3),
        "slaughter_score": slaughter,
        "is_slaughter": is_slaughter,
        "exploration_score": exploration,
    }


# ---------------------------------------------------------------------------
# WAD level
# ---------------------------------------------------------------------------
LENGTH_LABELS = [(1, "Single map"), (5, "Short (2-5 maps)"), (12, "Medium (6-12 maps)"),
                 (24, "Long (13-24 maps)"), (10**9, "Megawad (25+ maps)")]


def length_label(n: int) -> str:
    if n == 0:
        return "No maps"
    for lim, lab in LENGTH_LABELS:
        if n <= lim:
            return lab
    return "Megawad (25+ maps)"


def detect_game(map_names: List[str]) -> str:
    d1 = any(re.match(r"E\dM\d$", n) for n in map_names)
    d2 = any(n.startswith("MAP") for n in map_names)
    if d1 and d2:
        return "mixed"
    if d1:
        return "doom1"
    if d2:
        return "doom2"
    return "unknown"


def difficulty(avg_threat: float, resource_label: str, heavy_share: float):
    base = avg_threat
    if resource_label == "Scarce":
        base *= 1.35
    elif resource_label == "Tight":
        base *= 1.15
    elif resource_label == "Generous":
        base *= 0.85
    if heavy_share > 0.30:
        base *= 1.15
    import math
    score = 1 + 4 * clamp(math.log(max(base, 100) / 100) / math.log(2200 / 100))
    if base < 150:
        lab = "Easy"
    elif base < 450:
        lab = "Moderate"
    elif base < 1000:
        lab = "Hard"
    elif base < 2200:
        lab = "Very Hard"
    else:
        lab = "Extreme"
    return round(score, 2), lab


def resource_label(cov: Optional[float]) -> str:
    if cov is None:
        return "n/a"
    if cov >= 3.0:
        return "Generous"
    if cov >= 1.5:
        return "Balanced"
    if cov >= 0.8:
        return "Tight"
    return "Scarce"


def analyze_container(c: Container, skill: str = "uv") -> dict:
    maps = [analyze_map(m, skill) for m in c.maps]
    n = len(maps)
    names = [m["name"] for m in maps]
    game = detect_game(names)
    res: dict = {
        "skill": skill,
        "container": c.kind,
        "size": c.size,
        "map_count": n,
        "game": game,
        "length": length_label(n),
        "warnings": c.warnings,
        "custom_code": c.custom_code,
        "map_formats": sorted({m["format"] for m in maps}),
        "maps": maps,
    }

    # lump-content hints
    names_u = set(c.lump_names)
    res["has_sprites"] = any(x in names_u for x in ("S_START", "SS_START"))
    res["has_music"] = any(x.startswith("D_") for x in names_u)
    res["has_textures"] = any(x in names_u for x in ("TEXTURE1", "TEXTURE2", "PNAMES"))
    res["has_flats"] = any(x in names_u for x in ("F_START", "FF_START"))

    if n == 0:
        res.update(_empty_stats())
        res["category"], res["tags"], res["category_reason"] = _classify_empty(c, res)
        res["difficulty_score"], res["difficulty"] = None, "n/a"
        return res

    mons = [m["skills"][skill]["monsters"] for m in maps]
    total = sum(mons)
    by_type: Counter = Counter()
    tiers = Counter()
    for m in maps:
        by_type.update(m["skills"][skill]["by_type"])
        for k, v in m["skills"][skill]["tiers"].items():
            tiers[int(k)] += v
    bosses = sum(m["skills"][skill]["bosses"] for m in maps)
    hp = sum(m["skills"][skill]["hp"] for m in maps)
    threat = sum(m["skills"][skill]["threat"] for m in maps)
    health = sum(m["skills"][skill]["health"] for m in maps)
    armor = sum(m["skills"][skill]["armor"] for m in maps)
    ammo_dmg = sum(m["skills"][skill]["ammo_dmg"] + m["skills"][skill]["drop_dmg"] for m in maps) + START_AMMO_DMG * n
    ammo_units: Counter = Counter()
    for m in maps:
        ammo_units.update(m["skills"][skill]["ammo_units"])
    weapons = sorted({w for m in maps for w in m["skills"][skill]["weapons"]})
    secrets = sum(m["secrets"] for m in maps)
    keys_avg = sum(len(m["skills"][skill]["keys"]) for m in maps) / n
    dm_starts = sum(m["dm_starts"] for m in maps)
    unknown: Counter = Counter()
    for m in maps:
        unknown.update({int(k): v for k, v in m["skills"][skill]["unknown_things"].items()})

    strong = tiers[2] + tiers[3] + tiers[4]
    avg_m = total / n
    avg_threat = threat / n
    heavy_share = (tiers[3] + tiers[4]) / total if total else 0.0
    coverage = ammo_dmg / hp if hp else None
    rlabel = resource_label(coverage)
    dscore, dlabel = difficulty(avg_threat, rlabel, heavy_share)

    slaughter_maps = [m["name"] for m in maps if m["is_slaughter"]]
    slaughter_share = len(slaughter_maps) / n
    avg_slaughter = sum(m["slaughter_score"] for m in maps) / n
    max_slaughter = max(m["slaughter_score"] for m in maps)
    slaughter_score = round(max(avg_slaughter, 0.7 * max_slaughter), 1)
    exploration = round(sum(m["exploration_score"] for m in maps) / n, 1)

    hntr_total = sum(m["skills"]["hntr"]["monsters"] for m in maps)
    hmp_total = sum(m["skills"]["hmp"]["monsters"] for m in maps)
    uv_total = sum(m["skills"]["uv"]["monsters"] for m in maps)

    res.update({
        "total_monsters": total,
        "avg_monsters": round(avg_m, 1),
        "max_monsters": max(mons),
        "max_monsters_map": maps[mons.index(max(mons))]["name"],
        "monsters_by_type": dict(by_type.most_common()),
        "tier_counts": {T.TIER_NAMES[k]: tiers[k] for k in (1, 2, 3, 4)},
        "weak_share": round(tiers[1] / total, 3) if total else 0,
        "medium_share": round(tiers[2] / total, 3) if total else 0,
        "strong_share": round(tiers[3] / total, 3) if total else 0,
        "boss_share": round(tiers[4] / total, 3) if total else 0,
        "weak_to_strong_ratio": round(tiers[1] / strong, 2) if strong else None,
        "boss_count": bosses,
        "total_hp": hp,
        "total_threat": round(threat, 1),
        "avg_threat": round(avg_threat, 1),
        "ammo_units": dict(ammo_units),
        "ammo_dmg_total": int(ammo_dmg),
        "health_total": health,
        "armor_total": armor,
        "ammo_coverage": round(coverage, 2) if coverage is not None else None,
        "ammo_per_monster": round(ammo_dmg / total, 1) if total else None,
        "health_per_monster": round(health / total, 2) if total else None,
        "armor_per_monster": round(armor / total, 2) if total else None,
        "resource_label": rlabel,
        "weapons": weapons,
        "secrets": secrets,
        "keys_avg": round(keys_avg, 2),
        "dm_starts": dm_starts,
        "slaughter_maps": slaughter_maps,
        "slaughter_share": round(slaughter_share, 3),
        "slaughter_score": slaughter_score,
        "exploration_score": exploration,
        "difficulty_score": dscore,
        "difficulty": dlabel,
        "easy_skill_ratio": round(hntr_total / uv_total, 2) if uv_total else None,
        "skill_monsters": {"hntr": hntr_total, "hmp": hmp_total, "uv": uv_total},
        "unknown_things": dict(unknown.most_common(15)),
    })
    cat, tags, reason = classify(res)
    res["category"], res["tags"], res["category_reason"] = cat, tags, reason
    return res


def _empty_stats() -> dict:
    return {"total_monsters": 0, "avg_monsters": 0, "max_monsters": 0, "max_monsters_map": None,
            "monsters_by_type": {}, "tier_counts": {}, "boss_count": 0, "weak_share": 0,
            "medium_share": 0, "strong_share": 0, "boss_share": 0, "weak_to_strong_ratio": None,
            "avg_threat": 0, "ammo_coverage": None, "resource_label": "n/a",
            "slaughter_score": 0, "slaughter_share": 0, "slaughter_maps": [], "exploration_score": 0,
            "secrets": 0, "keys_avg": 0, "dm_starts": 0, "weapons": [], "unknown_things": {},
            "health_total": 0, "armor_total": 0, "ammo_dmg_total": 0, "ammo_units": {}}


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
CATEGORIES = {
    "slaughter": "Slaughter",
    "boss-rush": "Boss Rush",
    "deathmatch": "Deathmatch / Multiplayer",
    "exploration": "Exploration / Adventure",
    "combat": "Combat / Action Heavy",
    "classic": "Classic / Balanced",
    "casual": "Light / Casual",
    "atmospheric": "Atmospheric / Low Combat",
    "resource-pack": "Resource Pack",
    "iwad": "IWAD (commercial game data)",
}


def _classify_empty(c: Container, res: dict):
    if c.kind == "IWAD":
        return "iwad", ["iwad"], "IWAD container without extractable PWAD maps"
    return "resource-pack", ["resource-pack"], "No maps found; contains only resources (graphics, sounds, music, code)"


def classify(r: dict):
    n = r["map_count"]
    avg_m = r["avg_monsters"]
    tags: List[str] = []
    reason = ""

    # -- secondary tags
    if r["slaughter_maps"]:
        tags.append("has-slaughter-maps")
    if r["boss_count"] >= 1:
        tags.append("has-bosses")
    if r["resource_label"] in ("Scarce", "Tight"):
        tags.append("tight-resources")
    elif r["resource_label"] == "Generous":
        tags.append("generous-resources")
    if r["secrets"] >= max(3, n * 2):
        tags.append("secret-heavy")
    if r["keys_avg"] >= 2:
        tags.append("key-hunting")
    if r["custom_code"]:
        tags.append("custom-actors")
    if "udmf" in r["map_formats"]:
        tags.append("udmf")
    if "hexen" in r["map_formats"]:
        tags.append("hexen-format")
    if r["weak_share"] >= 0.7 and avg_m >= 40:
        tags.append("mostly-weak-enemies")
    if r["strong_share"] + r["boss_share"] >= 0.25:
        tags.append("heavy-hitters")
    tags.append(r["difficulty"].lower().replace(" ", "-"))
    tags.append({1: "single-map"}.get(n, "megawad" if n >= 25 else "multi-map"))
    tags.append(r["game"])

    # -- primary category (ordered rules)
    if r["dm_starts"] >= 4 * max(n, 1) and avg_m < 15:
        cat, reason = "deathmatch", f"{r['dm_starts']} deathmatch starts and very few monsters"
    elif r["boss_count"] >= max(3, 1.5 * n) and avg_m < 80:
        cat, reason = "boss-rush", f"{r['boss_count']} bosses across {n} map(s)"
    elif r["slaughter_share"] >= 0.5 or (n <= 3 and r["slaughter_maps"]):
        cat, reason = "slaughter", (f"{len(r['slaughter_maps'])}/{n} maps are slaughter-scale "
                                    f"(avg {avg_m:.0f} monsters, max {r['max_monsters']})")
    elif r["exploration_score"] >= 55 and avg_m < 180:
        cat, reason = "exploration", (f"exploration score {r['exploration_score']:.0f}: large maps, "
                                      f"{r['keys_avg']:.1f} keys/map, {r['secrets']} secrets")
    elif avg_m >= 140 or r["avg_threat"] >= 600:
        cat, reason = "combat", f"high monster density ({avg_m:.0f}/map, threat {r['avg_threat']:.0f}/map)"
    elif avg_m < 30:
        if r["exploration_score"] >= 35:
            cat, reason = "atmospheric", f"few monsters ({avg_m:.0f}/map) with sizeable, key-driven maps"
        else:
            cat, reason = "casual", f"few monsters ({avg_m:.0f}/map)"
    else:
        cat, reason = "classic", f"moderate density ({avg_m:.0f} monsters/map) and mixed enemy tiers"

    tags.insert(0, cat)
    # keep order, drop dupes
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return cat, out, reason
