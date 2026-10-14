# Doom WAD Analyzer

Single-page web app: upload one Doom 1 / Doom 2 `.wad` or `.pk3`, get validation, analysis, a category estimate,
a description and rendered map pictures. No database, no accounts/login, no search, no external network calls;
the uploaded file is analyzed in memory and discarded.

## Run
    pip install pillow
    python3 server.py            # http://127.0.0.1:8000   (--host / --port available)

Test files: `python3 tests/make_test_wads.py /tmp/testwads` creates small synthetic WADs/PK3s (incl. invalid ones).

## What it does
- Validation: IWAD/PWAD header + directory bounds; PK3 zip integrity, zip-bomb limit, embedded WADs, loose UDMF maps.
- Map formats: Doom, Hexen and UDMF; map titles from MAPINFO/UMAPINFO.
- Difficulty switcher: all numbers, the category/difficulty estimate and the map markers follow the selected skill (ITYTD/HNTR, HMP, UV/NM; default UV). Everything is computed in one pass, so switching is instant.
- Stats (for the selected skill, single-player): monster count/distribution, tiers (weak/medium/strong/boss), weak:strong ratio,
  boss count, health/armor/ammo vs. monster HP ("ammo coverage"), secrets, keys, per-skill monster counts, per-map table.
- Category (heuristic): Slaughter, Boss Rush, Deathmatch, Exploration, Combat, Classic, Light/Casual, Atmospheric,
  Resource Pack (+ tags and a 1-5 difficulty estimate). Rules live in `app/wad/analyzer.py` (`classify`).
- Description: template-based, from the computed stats. Doom Wiki: a search link only (no request is made).
- Maps drawn as automap-style PNGs with monster/item markers (first 64 maps).

## Limits
Custom monsters (DECORATE/ZScript/DEHACKED) and remapped editor numbers are not recognized; Heretic/Hexen/Strife
content is not analyzed as such. Thresholds are heuristics; tune them in `app/wad/analyzer.py` and `things.py`.

## Docker
    docker build -t doom-wad-analyzer .
    docker run --rm -p 8000:8000 doom-wad-analyzer        # http://localhost:8000
Hardened run (nothing is written to disk, so a read-only filesystem works):

    docker run --rm -p 127.0.0.1:8000:8000 --read-only --cap-drop ALL --security-opt no-new-privileges doom-wad-analyzer
The image runs as a non-root user and the app makes no outgoing connections.

### Docker Compose
Save as `docker-compose.yml` next to the `Dockerfile`:

```yaml
services:
  wad-analyzer:
    build: .
    image: doom-wad-analyzer
    container_name: wad-analyzer
    ports:
      - "127.0.0.1:8000:8000"   # drop "127.0.0.1:" to expose on your network
    restart: unless-stopped
    read_only: true             # the app never writes to disk
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    mem_limit: 1g               # uploads (max 200 MB) are processed in memory
```
Start with `docker compose up -d --build`, stop with `docker compose down`. Open http://localhost:8000.
If you put it behind a reverse proxy, raise the proxy's upload size limit to at least 200 MB.
