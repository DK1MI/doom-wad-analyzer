"""Rule-based natural-language description + title derivation."""
from __future__ import annotations

import re
from typing import Optional

from .analyzer import CATEGORIES, SKILL_NAMES

GAME_NAMES = {"doom1": "Doom (Ultimate Doom)", "doom2": "Doom II", "mixed": "Doom / Doom II", "unknown": "Doom"}

CAT_BLURB = {
    "slaughter": "a slaughtermap-style experience built around huge monster counts and heavy firepower",
    "boss-rush": "a boss-focused set of encounters",
    "deathmatch": "a multiplayer-oriented WAD with deathmatch arenas",
    "exploration": "an exploration-driven WAD with large, key-based levels and hidden areas",
    "combat": "an action-heavy WAD that emphasises sustained combat",
    "classic": "a classic-style WAD with balanced pacing and a mix of enemy types",
    "casual": "a light, relaxed WAD with comparatively few enemies",
    "atmospheric": "an atmospheric WAD that favours moving through its environments over combat",
    "resource-pack": "a resource pack that contains no playable maps",
    "iwad": "an IWAD (core game data)",
}


def title_from_filename(filename: str) -> str:
    stem = re.sub(r"\.(wad|pk3|zip)$", "", filename, flags=re.I)
    stem = re.sub(r"[_\-\.]+", " ", stem)
    stem = re.sub(r"\s+v?\d+(\s*\d+)*(\s*(beta|final|rc\d*|fix))?$", "", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem).strip()
    if stem and (stem.islower() or stem.isupper()) and len(stem) > 4:
        stem = stem.title()
    return stem or filename


def describe(title: str, a: dict) -> str:
    n = a["map_count"]
    cat = a["category"]
    game = GAME_NAMES.get(a["game"], "Doom")
    if n == 0:
        base = f"{title} is {CAT_BLURB[cat]}."
        extras = [k for k, v in (("custom sprites", a.get("has_sprites")), ("textures", a.get("has_textures")),
                                 ("flats", a.get("has_flats")), ("music", a.get("has_music"))) if v]
        if extras:
            base += " It includes " + ", ".join(extras) + "."
        return base

    s = []
    size = f"a {n}-map" if n > 1 else "a single-map"
    s.append(f"{title} is {size} {game} WAD, best described as {CAT_BLURB[cat]}.")
    s.append(
        f"On {SKILL_NAMES[a.get('skill', 'uv')]} it contains {a['total_monsters']} monsters in total "
        f"(about {a['avg_monsters']:.0f} per map, up to {a['max_monsters']} on {a['max_monsters_map']})."
    )
    if a["total_monsters"]:
        weak = round(a["weak_share"] * 100)
        mid = round(a["medium_share"] * 100)
        hi = round((a["strong_share"] + a["boss_share"]) * 100)
        s.append(f"The enemy mix is {weak}% weak, {mid}% medium and {hi}% strong or boss-tier")
        if a["boss_count"]:
            s[-1] += f", with {a['boss_count']} boss encounter{'s' if a['boss_count'] != 1 else ''}."
        else:
            s[-1] += ", with no bosses."
        top = list(a["monsters_by_type"].items())[:3]
        if top:
            s.append("The most common enemies are " + ", ".join(f"{k} ({v})" for k, v in top) + ".")
    rl = a["resource_label"]
    if rl != "n/a":
        cov = a["ammo_coverage"]
        s.append(f"Resources look {rl.lower()} relative to the enemy strength "
                 f"(ammo coverage {cov:.1f}x the monsters' total health, "
                 f"{a['health_total']} health and {a['armor_total']} armor points on the maps).")
    s.append(f"Estimated difficulty: {a['difficulty']} ({a['difficulty_score']:.1f}/5).")
    if a["slaughter_maps"]:
        s.append("Slaughter-scale maps: " + ", ".join(a["slaughter_maps"][:8]) + (" ..." if len(a["slaughter_maps"]) > 8 else "") + ".")
    if a["secrets"]:
        s.append(f"There {'is' if a['secrets']==1 else 'are'} {a['secrets']} secret sector{'' if a['secrets']==1 else 's'}.")
    if a["custom_code"]:
        s.append("It ships custom actor/code lumps (" + ", ".join(a["custom_code"]) +
                 "), so monster statistics may be incomplete.")
    return " ".join(s)
