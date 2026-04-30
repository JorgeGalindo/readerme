# readerme

Lector de feeds RSS personal con cuatro pestañas (Main, España, Thinktanks, Papers), audio briefings y mercados de predicción.

## Cómo funciona

```
data/feeds.json (RSS taggeados main / thinktank / papers)
        │
        ├─► rss.py (delta por feed) ─────► curator.py ────► main.json   ─┐
        │                                  (sin scoring)                 │
        │                                                                ├─► /
        ├─► fetch_latest_by_tag (sin estado) ──► thinktanks.py ─► thinktanks.json ─► /thinktanks
        │                                       papers.py    ─► papers.json     ─► /papers
        │
        └─► spain.py (RSS medios + Claude political-risk pick) ─► spain.json ─► /espana

markets.py (Polymarket CLOB API) ──► markets.json + markets_main.json
polls.py   (colmenadedatos)      ──► polls.json
briefing.py (Claude Opus 4.7 + edge-tts) ─► briefing_main.mp3, briefing_thinktanks.mp3
spain.py también escribe briefing.mp3 (legacy path)
```

## Pestañas

### Main (`/`)
- **Briefing de hoy** — ~3 min, generado con Claude Opus 4.7 + edge-tts.
- **Mercados de predicción (Polymarket)** — Iran régimen, Russia-Ukraine, Fed cut, China-Taiwan.
- **Artículos** — orden cronológico. No hay scoring: lo que entra por RSS aparece aquí.
- Cada card: **Leer** (scrape vía `/api/scrape`), **Escuchar** (TTS browser-side), **Compartir** (LinkedIn/X), **Leído** (oculta + localStorage).

### España (`/espana`)
- **Briefing** factual (encuestas, mercados, noticias).
- **Cómo va el voto** — Chart.js con datos de colmenadedatos.
- **Mercados** — elecciones anticipadas (Polymarket).
- **Lo que se dice fuera** — Economist, FT, Politico Europe, Guardian (filtro España).
- **Radar político** — 10 noticias picadas con Claude Sonnet desde RSS de medios españoles.

### Thinktanks (`/thinktanks`)
- **Briefing** ~3 min sobre publicaciones recientes, agrupado por subsección.
- 3 subsecciones:
  - **Classic**: Tony Blair Institute (sitemap parser), European Policy Centre (HTML scraper).
  - **España**: Elcano, Fedea, BBVA Research (scraper).
  - **Abundance**: Progress Ireland, Abundance Institute, Center for Growth and Opportunity.

### Papers (`/papers`)
- NBER (Education / Children / Political Economy), IZA Discussion Papers, Banco de España, VoxEU/CEPR. Lista cronológica por fuente, sin scoring.

## Ciclo diario

GitHub Actions a las 04:00 Madrid → `nightly.py` →
1. Main RSS deltas → main.json
2. Polymarket Main → markets_main.json
3. España (RSS + Claude pick + briefing.mp3)
4. Thinktanks (RSS por subtag + scrape BBVA)
5. Papers (RSS)
6. Briefings audio (Main + Thinktanks)
7. Commit + push → Render redeploy

## Setup

```bash
cd readerme
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`.env`:
```
ANTHROPIC_API_KEY=...
```

## Uso

```bash
.venv/bin/python run.py nightly   # ciclo completo
.venv/bin/python run.py curate    # solo Main
.venv/bin/python run.py curate-spain
.venv/bin/python run.py serve --port 8080
```

## Estructura

```
readerme/
├── run.py            # CLI
├── curator.py        # Main: RSS deltas → main.json
├── rss.py            # parsers (RSS/Atom + sitemap_tbi + scrape_epc)
├── thinktanks.py     # /thinktanks
├── papers.py         # /papers
├── spain.py          # /espana (RSS + Claude pick + briefing audio)
├── polls.py          # encuestas
├── markets.py        # Polymarket (Spain + Main)
├── briefing.py       # Claude Opus 4.7 + edge-tts (Main, Thinktanks)
├── nightly.py        # ciclo nocturno
├── server.py         # Flask
├── templates/        # index, espana, thinktanks, papers
├── static/style.css
├── data/             # feeds.json + outputs (commiteados por nightly)
├── Procfile          # Render web process
└── requirements.txt
```

## API endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/` | GET | Main |
| `/espana` | GET | España |
| `/thinktanks` | GET | Thinktanks |
| `/papers` | GET | Papers |
| `/api/scrape?url=...` | GET | Scrape de un artículo web |
| `/api/share-text` | POST | Texto para compartir (Claude) |
| `/api/briefing.mp3` | GET | Briefing España (legacy) |
| `/api/briefing/<tab>.mp3` | GET | Briefing Main / Thinktanks |

## Stack

Python 3.13 · Flask + Gunicorn · Claude Opus 4.7 (briefings) + Sonnet (España pick + share-text) · edge-tts · Chart.js · Polymarket CLOB · httpx + BeautifulSoup + lxml.
