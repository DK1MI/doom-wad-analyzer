#!/usr/bin/env python3
"""Doom WAD Analyzer - single-page web app.

Upload one Doom 1 / Doom 2 WAD or PK3, get a validation result, an analysis,
a category estimate, a description and rendered map pictures.

Nothing is stored (everything lives in memory for the duration of the request)
and the server makes no outgoing network calls.

Usage:  python3 server.py [--host 127.0.0.1] [--port 8000]
Needs:  Python 3.9+ and Pillow (pip install pillow)
"""
from __future__ import annotations

import argparse
import base64
import email.policy
import html
import io
import re
import tempfile
import urllib.parse
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.wad import analyzer, describe, parser, render, things as T

MAX_UPLOAD = 200 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED = 1024 * 1024 * 1024
MAX_RENDERED_MAPS = 64
MAP_IMAGE_PX = 1000

esc = html.escape

CSS = """
:root{--bg:#121214;--panel:#1c1c20;--line:#2e2e35;--fg:#e8e8ea;--mut:#9a9aa5;--acc:#e0482f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{padding:14px 24px;border-bottom:1px solid var(--line);font-weight:700;font-size:18px}
header a{color:var(--fg);text-decoration:none}main{max-width:1100px;margin:0 auto;padding:24px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:18px}
h1,h2,h3{margin:.2em 0 .5em}h2{font-size:18px;border-bottom:1px solid var(--line);padding-bottom:6px}
.btn{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:9px 18px;font-size:15px;cursor:pointer}
.btn:disabled{opacity:.6}input[type=file]{color:var(--fg);margin-right:10px}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;margin:0 6px 6px 0;background:#33333b}
.badge.cat{background:#7a2a1c}.badge.diff{background:#4a3b12}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:#232328;border-radius:8px;padding:10px 14px}.card b{display:block;font-size:22px}
.card span{color:var(--mut);font-size:13px}.mut{color:var(--mut)}.ok{color:#5fd07a}.bad{color:#ff6b5c}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bar{height:10px;background:#2a2a30;border-radius:5px;overflow:hidden;min-width:80px}.bar i{display:block;height:100%}
.stack{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:8px 0}.stack div{height:100%}
.legend span{margin-right:16px;font-size:13px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}
.maps{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.maps figure{margin:0;background:#0c0c0e;border:1px solid var(--line);border-radius:8px;padding:8px}
.maps img{width:100%;height:auto;display:block}.maps figcaption{font-size:13px;margin-top:4px}
.warn{background:#3a2f10;border:1px solid #6b5518;border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:14px}
.err{background:#3a1512;border:1px solid #7a2a1c;border-radius:8px;padding:12px 16px}
.scroll{overflow-x:auto}.maps img.zoom{cursor:zoom-in}
.maps .mstack{position:relative;cursor:zoom-in}.mstack img.base{width:100%;height:auto;display:block}
.mstack img.ov{position:absolute;left:0;top:0;width:100%;height:100%}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;overflow:auto;z-index:10;cursor:zoom-out;text-align:center}
#lb .mstack{display:inline-block;margin:2vh auto;cursor:inherit;background:#0c0c0e}
#lb .mstack img.base{max-width:96vw;max-height:96vh;width:auto}
#lb.full .mstack{margin:0}#lb.full .mstack img.base{max-width:none;max-height:none}
#lb span.hint{position:fixed;top:8px;right:16px;color:#aaa;font-size:13px}
.skillbar{position:sticky;top:0;z-index:5}.skillbtn{background:#2a2a30;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 12px;margin:0 6px 4px 0;cursor:pointer;font-size:14px}
body[data-skill="hntr"] .skillbtn[data-skill="hntr"],body[data-skill="hmp"] .skillbtn[data-skill="hmp"],body[data-skill="uv"] .skillbtn[data-skill="uv"]{background:var(--acc);border-color:var(--acc)}
small{color:var(--mut)}a{color:#79b8ff}
"""

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>{css}</style></head><body data-skill="uv">
<header><a href="/">&#9760; Doom WAD Analyzer</a></header><main>{body}</main>
<div id="lb"><span class="hint">click: toggle size &middot; Esc: close</span><div id="lbc"></div></div>
<script>(function(){{
var body=document.body,lb=document.getElementById('lb'),box=document.getElementById('lbc');
function setSkill(s){{body.dataset.skill=s;try{{sessionStorage.setItem('skill',s);}}catch(e){{}}}}
var saved=null;try{{saved=sessionStorage.getItem('skill');}}catch(e){{}}
setSkill(saved||'uv');
document.querySelectorAll('.skillbtn').forEach(function(b){{b.addEventListener('click',function(){{setSkill(b.dataset.skill);}});}});
document.querySelectorAll('.mstack.zoom').forEach(function(m){{m.addEventListener('click',function(){{
box.innerHTML='';var c=m.cloneNode(true);c.classList.remove('zoom');box.appendChild(c);lb.className='';lb.style.display='block';lb.scrollTop=0;}});}});
lb.addEventListener('click',function(e){{if(e.target.closest('.mstack')){{e.stopPropagation();lb.classList.toggle('full');}}else{{lb.style.display='none';}}}});
document.addEventListener('keydown',function(e){{if(e.key==='Escape')lb.style.display='none';}});}})();</script>
<script>document.querySelectorAll('form.up').forEach(f=>f.addEventListener('submit',()=>{{
var b=f.querySelector('button');b.disabled=true;b.textContent='Analyzing...';}}));</script>
</body></html>"""

FORM = """<div class="panel"><h2>Analyze a WAD</h2>
<p>Upload a Doom / Doom II <code>.wad</code> or <code>.pk3</code> (max {mb} MB). The file is validated, analyzed
and discarded; nothing is stored and no external services are contacted.</p>
<form class="up" method="post" action="/analyze" enctype="multipart/form-data">
<input type="file" name="wad" accept=".wad,.pk3,.zip" required>
<button class="btn" type="submit">Analyze</button></form></div>"""


# ---------------------------------------------------------------------------
# Rendering the result page
# ---------------------------------------------------------------------------
TIER_COL = {"Weak": "#5fd07a", "Medium": "#e6c04a", "Strong": "#e8773a", "Boss": "#d83a3a"}
SKILLS = list(analyzer.SKILLS)          # hntr, hmp, uv
DEFAULT_SKILL = "uv"
GAME_LABEL = {"doom1": "Doom 1", "doom2": "Doom 2", "mixed": "Doom 1 + 2", "unknown": "game unknown"}


def pct(x) -> str:
    return f"{x * 100:.0f}%"


def card(value, label) -> str:
    return f'<div class="card"><b>{esc(str(value))}</b><span>{esc(label)}</span></div>'


def bar(frac: float, color: str = "#e0482f") -> str:
    return f'<div class="bar"><i style="width:{max(0, min(1, frac)) * 100:.1f}%;background:{color}"></i></div>'


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def skill_css() -> str:
    """Show only the selected skill's sections / marker layers (selected via body[data-skill])."""
    rules = [".sv,.ov,.cap{display:none}"]
    for s in SKILLS:
        rules.append(f'body[data-skill="{s}"] .sv[data-skill="{s}"]{{display:block}}')
        rules.append(f'body[data-skill="{s}"] .ov[data-skill="{s}"]{{display:block}}')
        rules.append(f'body[data-skill="{s}"] .cap[data-skill="{s}"]{{display:inline}}')
    return "".join(rules)


def skill_view(skill: str, a: dict) -> str:
    """Everything that depends on the selected difficulty."""
    title = a["_title"]
    cat = a["category"]
    h = [f'<section class="sv" data-skill="{skill}">']

    h.append('<div class="panel">')
    h.append(f'<span class="badge cat">{esc(analyzer.CATEGORIES.get(cat, cat))}</span>')
    h.append(f'<span class="badge diff">Difficulty: {esc(a["difficulty"])} ({a["difficulty_score"]:.1f}/5)</span>')
    h.append(f'<span class="badge">{esc(a["length"])}</span>')
    h.append(f'<span class="badge">{esc(GAME_LABEL[a["game"]])}</span>')
    skip = {cat, "doom1", "doom2", "mixed", "unknown", a["difficulty"].lower().replace(" ", "-")}
    for t in a["tags"]:
        if t not in skip:
            h.append(f'<span class="badge">{esc(t)}</span>')
    h.append(f"<p>{esc(describe.describe(title, a))}</p>")
    h.append(f'<p class="mut">Why this category: {esc(a["category_reason"])}.</p></div>')

    ws = a["weak_to_strong_ratio"]
    sm = a["skill_monsters"]
    h.append(f'<div class="panel"><h2>Overview &ndash; {esc(analyzer.SKILL_NAMES[skill])}</h2><div class="cards">')
    h.append(card(a["map_count"], "maps"))
    h.append(card(a["total_monsters"], "monsters total"))
    h.append(card(f'{a["avg_monsters"]:.0f}', "avg monsters / map"))
    h.append(card(f'{a["max_monsters"]} ({a["max_monsters_map"]})', "biggest map"))
    h.append(card(a["boss_count"], "bosses"))
    h.append(card(f'{ws:.1f} : 1' if ws is not None else "n/a", "weak : medium+strong+boss"))
    h.append(card(a["secrets"], "secret sectors"))
    h.append(card(f'{a["keys_avg"]:.1f}', "keys / map (avg)"))
    h.append(card(f'{a["slaughter_score"]:.0f}/100', "slaughter score"))
    h.append(card(f'{a["exploration_score"]:.0f}/100', "exploration score"))
    h.append("</div>")
    h.append(f'<p class="mut">Total monsters by skill: ITYTD/HNTR {sm["hntr"]} &middot; HMP {sm["hmp"]} &middot; UV/NM {sm["uv"]}</p></div>')

    # tiers
    tc = a["tier_counts"]
    tot = max(a["total_monsters"], 1)
    h.append('<div class="panel"><h2>Enemy strength mix</h2><div class="stack">')
    for name in ("Weak", "Medium", "Strong", "Boss"):
        h.append(f'<div title="{name}: {tc.get(name, 0)}" style="width:{tc.get(name, 0) / tot * 100:.2f}%;background:{TIER_COL[name]}"></div>')
    h.append('</div><div class="legend">')
    for name in ("Weak", "Medium", "Strong", "Boss"):
        h.append(f'<span><i class="dot" style="background:{TIER_COL[name]}"></i>{name}: {tc.get(name, 0)} ({pct(tc.get(name, 0) / tot)})</span>')
    h.append("</div></div>")

    # distribution
    h.append('<div class="panel"><h2>Monster distribution</h2><div class="scroll"><table><tr><th>Monster</th><th>Tier</th><th class="n">Count</th><th class="n">Share</th><th></th></tr>')
    tier_of = {m.name: m.tier for m in T.MONSTERS.values()}
    top = max(a["monsters_by_type"].values(), default=1)
    for name, n in a["monsters_by_type"].items():
        t = T.TIER_NAMES.get(tier_of.get(name, 1), "?")
        h.append(f'<tr><td>{esc(name)}</td><td>{t}</td><td class="n">{n}</td><td class="n">{pct(n / tot)}</td><td>{bar(n / top, TIER_COL.get(t, "#888"))}</td></tr>')
    if not a["monsters_by_type"]:
        h.append('<tr><td colspan="5" class="mut">No recognized monsters on this skill level.</td></tr>')
    h.append("</table></div></div>")

    # resources
    au = a["ammo_units"]
    cov = a["ammo_coverage"]
    h.append('<div class="panel"><h2>Resources vs. enemy strength</h2><div class="cards">')
    h.append(card(a["resource_label"], "resource supply"))
    h.append(card(f"{cov:.1f}x" if cov is not None else "n/a", "ammo damage / monster HP"))
    h.append(card(a["health_total"], "health points available"))
    h.append(card(a["armor_total"], "armor points available"))
    h.append(card("n/a" if a["health_per_monster"] is None else f'{a["health_per_monster"]:.1f}', "health per monster"))
    h.append(card("n/a" if a["armor_per_monster"] is None else f'{a["armor_per_monster"]:.1f}', "armor per monster"))
    h.append("</div>")
    h.append(f'<p class="mut">Ammo placed: {esc(", ".join(f"{v} {k}s" for k, v in au.items()) or "none")}. '
             f'Weapons found: {esc(", ".join(a["weapons"]) or "none")}. '
             'Coverage counts placed ammo, monster drops and a 50-bullet pistol start per map, using rough effective damage per ammo unit.</p></div>')

    # per-map table
    h.append('<div class="panel"><h2>Per-map breakdown</h2><div class="scroll"><table><tr><th>Map</th><th class="n">Monsters</th><th></th>'
             '<th class="n">Weak</th><th class="n">Med</th><th class="n">Strong</th><th class="n">Boss</th>'
             '<th class="n">Health</th><th class="n">Armor</th><th class="n">Ammo cov.</th><th class="n">Secrets</th><th>Flags</th></tr>')
    mx = max(max(m["skills"][skill]["monsters"] for m in a["maps"]), 1)
    for m in a["maps"]:
        u = m["skills"][skill]
        tr = u["tiers"]
        label = esc(m["name"]) + (f' <small>{esc(m["title"])}</small>' if m["title"] else "")
        cv = "-" if m["coverage"] is None else "%.1fx" % m["coverage"]
        h.append(f'<tr><td>{label}</td><td class="n">{u["monsters"]}</td><td>{bar(u["monsters"] / mx)}</td>'
                 f'<td class="n">{tr["1"]}</td><td class="n">{tr["2"]}</td><td class="n">{tr["3"]}</td><td class="n">{tr["4"]}</td>'
                 f'<td class="n">{u["health"]}</td><td class="n">{u["armor"]}</td>'
                 f'<td class="n">{cv}</td><td class="n">{m["secrets"]}</td><td>{"slaughter" if m["is_slaughter"] else ""}</td></tr>')
    h.append("</table></div></div></section>")
    return "".join(h)


def map_gallery(c: parser.Container, per_skill: dict) -> str:
    """Layered map pictures; the marker layer follows the selected skill."""
    figs = []
    base = per_skill[DEFAULT_SKILL]["maps"]
    for i, m in enumerate(c.maps):
        if i >= MAX_RENDERED_MAPS:
            break
        try:
            layers = render.render_layers(m, analyzer.SKILLS, MAP_IMAGE_PX)
        except Exception:
            layers = None
        if not layers:
            continue
        geo, ovs = layers
        stack = f'<div class="mstack zoom"><img class="base" loading="lazy" src="{data_uri(geo)}" alt="{esc(m.name)}">'
        for s in SKILLS:
            stack += f'<img class="ov" data-skill="{s}" loading="lazy" src="{data_uri(ovs[s])}" alt="">'
        stack += "</div>"
        title = f" - {esc(m.title)}" if m.title else ""
        caps = "".join(f'<span class="cap" data-skill="{s}">{per_skill[s]["maps"][i]["skills"][s]["monsters"]} monsters</span>' for s in SKILLS)
        figs.append(f"<figure>{stack}<figcaption>{esc(m.name)}{title} &middot; {caps}</figcaption></figure>")
    if not figs:
        return ""
    out = ('<div class="panel"><h2>Maps</h2><p class="mut">Red: solid walls &middot; brown: floor steps &middot; yellow: ceiling steps &middot; '
           'cyan: special lines &middot; dots: monsters (red), ammo (orange), health (green), armor (blue), keys (white), starts (teal). '
           'Monster/item dots follow the selected difficulty. Click a map to enlarge it.</p><div class="maps">' + "".join(figs) + "</div>")
    if len(c.maps) > MAX_RENDERED_MAPS:
        out += f'<p class="mut">Only the first {MAX_RENDERED_MAPS} maps are drawn.</p>'
    return out + "</div>"


def result_page(filename: str, c: parser.Container, per_skill: dict) -> str:
    a0 = per_skill[DEFAULT_SKILL]
    title = describe.title_from_filename(filename)
    for a in per_skill.values():
        a["_title"] = title
    wiki = "https://doomwiki.org/w/index.php?search=" + urllib.parse.quote(title)
    h = ['<div class="panel">', f"<h1>{esc(title)}</h1>"]
    h.append(f'<p><a href="{esc(wiki)}" target="_blank" rel="noopener noreferrer">Search the Doom Wiki for this WAD &rarr;</a> '
             f'<small>(link only - no request is made by this app)</small></p>')
    h.append(f'<p class="ok">&#10003; Valid {esc(c.kind)} &middot; {c.size / 1048576:.2f} MB &middot; {len(c.lump_names)} lumps/files'
             f'{" &middot; map format: " + esc(", ".join(a0["map_formats"])) if a0["map_formats"] else ""}</p>')
    for w in a0["warnings"][:10]:
        h.append(f'<div class="warn">{esc(w)}</div>')
    if a0["custom_code"]:
        h.append('<div class="warn">This file contains custom code lumps (' + esc(", ".join(a0["custom_code"])) +
                 '). Custom monsters/items are not recognized, so the statistics may be incomplete.</div>')
    h.append("</div>")

    if a0["map_count"] == 0:
        h.append(f'<div class="panel"><span class="badge cat">{esc(analyzer.CATEGORIES.get(a0["category"], a0["category"]))}</span>'
                 f'<p>{esc(describe.describe(title, a0))}</p><p class="mut">No playable maps were found in this file.</p></div>')
        return "".join(h)

    # difficulty switcher
    h.append('<div class="panel skillbar"><b>Difficulty:</b> ')
    for s in SKILLS:
        h.append(f'<button type="button" class="skillbtn" data-skill="{s}">{esc(analyzer.SKILL_NAMES[s])}</button>')
    h.append('<p class="mut small">Doom has five skill levels but three monster sets: skills 1+2 share one, skill 3 has its own, '
             'and skills 4+5 share one (Nightmare! additionally has fast, respawning monsters, which is not modelled).</p></div>')
    for s in SKILLS:
        h.append(skill_view(s, per_skill[s]))
    h.append(map_gallery(c, per_skill))
    h.append(f"<style>{skill_css()}</style>")
    return "".join(h)


def error_page(msg: str) -> str:
    return FORM.format(mb=MAX_UPLOAD // 1048576) + f'<div class="err"><b>Could not analyze file.</b><br>{esc(msg)}</div>'


def analyze_bytes(filename: str, data: bytes) -> str:
    """Validate + analyze (all skill groups) + render -> HTML body fragment. Raises parser.WadError if invalid."""
    c = parser.open_container(io.BytesIO(data), MAX_ZIP_UNCOMPRESSED)
    per_skill = {s: analyzer.analyze_container(c, s) for s in SKILLS}
    return FORM.format(mb=MAX_UPLOAD // 1048576) + result_page(filename, c, per_skill)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

def parse_upload(content_type: str, body: bytes):
    msg = BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    for part in msg.iter_parts():
        if part.get_param("name", header="content-disposition") == "wad":
            return part.get_filename() or "upload.wad", part.get_payload(decode=True) or b""
    return None, b""


class Handler(BaseHTTPRequestHandler):
    server_version = "WadAnalyzer/1.0"

    def _send(self, code: int, body_html: str, title: str = "Doom WAD Analyzer"):
        out = PAGE.format(title=esc(title), css=CSS, body=body_html).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'")
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        if self.path.split("?")[0] == "/":
            self._send(200, FORM.format(mb=MAX_UPLOAD // 1048576))
        else:
            self._send(404, "<div class='panel'>Not found.</div>")

    def do_POST(self):
        if self.path != "/analyze":
            return self._send(404, "<div class='panel'>Not found.</div>")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        ctype = self.headers.get("Content-Type", "")
        if length <= 0 or not ctype.startswith("multipart/form-data"):
            return self._send(400, error_page("Expected a file upload."))
        if length > MAX_UPLOAD + 4096:
            return self._send(413, error_page(f"File exceeds the {MAX_UPLOAD // 1048576} MB limit."))
        body = self.rfile.read(length)
        filename, data = parse_upload(ctype, body)
        del body
        if not data:
            return self._send(400, error_page("No file received."))
        filename = Path(filename.replace("\\", "/")).name[:200]
        try:
            self._send(200, analyze_bytes(filename, data), f"{filename} - analysis")
        except parser.WadError as exc:
            self._send(422, error_page(f"Invalid WAD/PK3: {exc}"))
        except Exception as exc:  # never leak a traceback to the page
            self.log_error("analysis failed: %r", exc)
            self._send(500, error_page("Unexpected error while analyzing this file."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Doom WAD Analyzer running at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
