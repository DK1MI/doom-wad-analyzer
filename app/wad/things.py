"""Doom thing tables (editor numbers) used for analysis.

Tiers:  1 = weak, 2 = medium, 3 = strong, 4 = boss
threat: rough "danger points" per monster (used for difficulty / slaughter heuristics)
hp:     vanilla hit points
drop:   approximate damage-potential of ammo the monster drops on death
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Monster:
    name: str
    tier: int
    hp: int
    threat: float
    drop: float = 0.0
    boss: bool = False


MONSTERS = {
    3004: Monster("Zombieman", 1, 20, 1.0, 40),
    9:    Monster("Shotgun Guy", 1, 30, 2.0, 140),
    3001: Monster("Imp", 1, 60, 2.0),
    3006: Monster("Lost Soul", 1, 100, 1.5),
    84:   Monster("Wolfenstein SS", 1, 50, 2.5, 40),
    3002: Monster("Demon", 2, 150, 3.0),
    58:   Monster("Spectre", 2, 150, 3.5),
    65:   Monster("Chaingunner", 2, 70, 3.5, 80),
    3005: Monster("Cacodemon", 2, 400, 5.0),
    66:   Monster("Revenant", 2, 300, 5.5),
    69:   Monster("Hell Knight", 3, 500, 7.0),
    3003: Monster("Baron of Hell", 3, 1000, 9.0),
    67:   Monster("Mancubus", 3, 600, 9.0),
    68:   Monster("Arachnotron", 3, 500, 7.0),
    71:   Monster("Pain Elemental", 3, 400, 6.0),
    64:   Monster("Arch-vile", 3, 700, 14.0),
    16:   Monster("Cyberdemon", 4, 4000, 40.0, boss=True),
    7:    Monster("Spider Mastermind", 4, 3000, 40.0, boss=True),
}
# Icon of Sin / Commander Keen are special: counted separately.
SPECIAL = {88: "Boss Brain (Icon of Sin)", 72: "Commander Keen"}

TIER_NAMES = {1: "Weak", 2: "Medium", 3: "Strong", 4: "Boss"}

# ---- items -----------------------------------------------------------------
# Effective damage-potential per ammo unit (includes a realistic hit factor).
DMG_PER = {"bullet": 8.0, "shell": 35.0, "rocket": 100.0, "cell": 18.0}

AMMO = {  # type: (name, kind, units)
    2007: ("Clip", "bullet", 10),
    2048: ("Box of Bullets", "bullet", 50),
    2008: ("Shotgun Shells", "shell", 4),
    2049: ("Box of Shells", "shell", 20),
    2010: ("Rocket", "rocket", 1),
    2046: ("Box of Rockets", "rocket", 5),
    2047: ("Energy Cell", "cell", 20),
    17:   ("Energy Cell Pack", "cell", 100),
    8:    ("Backpack", "bullet", 10),  # + half-ish bonus, simplified
}
# Weapon pick-ups also supply some ammo.
WEAPONS = {
    2001: ("Shotgun", "shell", 8),
    82:   ("Super Shotgun", "shell", 8),
    2002: ("Chaingun", "bullet", 20),
    2003: ("Rocket Launcher", "rocket", 2),
    2004: ("Plasma Rifle", "cell", 40),
    2006: ("BFG 9000", "cell", 40),
    2005: ("Chainsaw", None, 0),
}

HEALTH = {  # type: (name, hp)
    2014: ("Health Bonus", 1),
    2011: ("Stimpack", 10),
    2012: ("Medikit", 25),
    2013: ("Soulsphere", 100),
    83:   ("Megasphere", 200),
}
ARMOR = {
    2015: ("Armor Bonus", 1),
    2018: ("Green Armor", 100),
    2019: ("Blue Armor", 200),
    83:   ("Megasphere", 200),
}
KEYS = {5: "Blue Keycard", 6: "Yellow Keycard", 13: "Red Keycard",
        38: "Red Skull", 39: "Yellow Skull", 40: "Blue Skull"}
POWERUPS = {2022: "Invulnerability", 2023: "Berserk", 2024: "Invisibility",
            2025: "Radiation Suit", 2026: "Computer Map", 2045: "Light Amp Goggles"}

PLAYER_STARTS = {1, 2, 3, 4}
DM_START = 11
TELEPORT_DEST = 14

# Draw colours / classes for thing rendering
def thing_class(t: int) -> str:
    if t in MONSTERS or t in SPECIAL:
        return "monster"
    if t in AMMO or t in WEAPONS:
        return "ammo"
    if t in HEALTH:
        return "health"
    if t in ARMOR:
        return "armor"
    if t in KEYS:
        return "key"
    if t in PLAYER_STARTS:
        return "start"
    return "other"
