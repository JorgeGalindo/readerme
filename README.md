# readerme

Lector de feeds RSS personal con cuatro pestañas (Main, España, Thinktanks, Papers), audio briefing (España) y mercados de predicción.

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
spain.py escribe además briefing.mp3 (briefing España, OpenAI gpt-4o-mini-tts)
```

## Pestañas

### Main (`/`)
- **Mercados de predicción (Polymarket)** — Iran régimen, Russia-Ukraine, Fed cut, China-Taiwan.
- **Artículos** — orden cronológico. No hay scoring: lo que entra por RSS aparece aquí.
- Cada card: el título enlaza **directamente a la fuente original** (sin página intermedia), **Compartir** (LinkedIn/X), **Leído** (oculta + ledger).

> **Por qué no es standalone en iOS.** Los templates omiten a propósito
> `apple-mobile-web-app-capable`. En modo standalone (icono en la pantalla de
> inicio) iOS abre todo enlace saliente en un web view embebido, donde los
> Universal Links no llegan nunca a la app de destino — comprobado en iPhone.
> Corriendo en Safari, en cambio, tocar un post de Substack abre la app de
> Substack: todos los dominios de `feeds.json`, también los propios
> (noahpinion.blog, astralcodexten.com…), sirven el `apple-app-site-association`
> con `/p/*`. En iOS 26 hay que añadir el icono con **"Abrir como app web"
> desactivado** para que abra en Safari.
>
> Por lo mismo, los enlaces de titular van **sin `target="_blank"`**: abrir en
> pestaña nueva es una causa documentada de que el Universal Link no llegue a
> la app. Y si iOS ya abrió un dominio en Safari una vez (tocando el nombre del
> dominio arriba a la derecha), se queda esa preferencia guardada: se restaura
> manteniendo pulsado el enlace y eligiendo *Abrir en "Substack"*.

### España (`/espana`)
- **Briefing** factual (encuestas, mercados, noticias).
- **Cómo va el voto** — Chart.js con datos de colmenadedatos.
- **Mercados** — elecciones anticipadas (Polymarket).
- **Lo que se dice fuera** — Economist, FT, Politico Europe, Guardian (filtro España).
- **Radar político** — 10 noticias picadas con Claude Sonnet desde RSS de medios españoles.

### Thinktanks (`/thinktanks`)
- 3 subsecciones:
  - **Classic**: Tony Blair Institute (sitemap parser), European Policy Centre (HTML scraper).
  - **España**: Elcano, Fedea, BBVA Research (scraper).
  - **Abundance**: Progress Ireland, Abundance Institute, Center for Growth and Opportunity.

### Papers (`/papers`)
- NBER (Education / Children / Political Economy), IZA Discussion Papers, Banco de España, VoxEU/CEPR. Lista cronológica por fuente, sin scoring.

## Ciclo diario

Vercel Cron, una sola fase bajo el límite de 300s por función:

- **02:00 UTC** → `/api/nightly/curate` (~165s)
  1. Main RSS deltas → main.json
  2. Polymarket Main → markets_main.json
  3. España (RSS + Claude pick + briefing.mp3)
  4. Thinktanks (RSS por subtag + scrape BBVA)
  5. Papers (RSS)
  6. Polls (colmenadedatos)
  7. Polymarket España

Disparable manualmente con `Authorization: Bearer $CRON_SECRET`.

## Setup

```bash
cd readerme
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`.env` (dev local — los datos viven en disco bajo `data/`):
```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...   # gpt-4o-mini-tts para el briefing de España
```

Producción en Vercel (`https://readerme.vercel.app`) usa:
- `BLOB_READ_WRITE_TOKEN` — Vercel Blob (jsons + mp3 generados por la nightly)
- `KV_REST_API_URL` / `KV_REST_API_TOKEN` — Upstash Redis (read ledger)
- `CRON_SECRET` — gate de `/api/nightly/*`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY` — TTS del briefing de España
- `OPENAI_TTS_VOICE` (opcional, default `nova`) — alloy / ash / ballad / coral / echo / fable / nova / onyx / sage / shimmer

Si no hay `BLOB_READ_WRITE_TOKEN` en el entorno, `storage.py` cae al filesystem
local automáticamente — `python run.py serve` y `python run.py nightly` siguen
funcionando igual sin tocar nada.

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
├── briefing.py       # OpenAI gpt-4o-mini-tts (utilidad de voz para spain.py)
├── nightly.py        # CLI nocturno (dev local)
├── server.py         # Flask + rutas /api/nightly/{curate,brief}
├── app.py            # entry point para Vercel (re-exporta server.app)
├── storage.py        # adaptador Blob (prod) / filesystem (dev)
├── read_store.py     # adaptador KV (prod) / JSON local (dev)
├── templates/        # index, espana, thinktanks, papers
├── static/style.css
├── data/             # feeds.json + profile.json (config); outputs en Blob
├── vercel.json       # cron schedule (02:00 UTC)
└── requirements.txt
```

## API endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/` | GET | Main |
| `/espana` | GET | España |
| `/thinktanks` | GET | Thinktanks |
| `/papers` | GET | Papers |
| `/api/share-text` | POST | Texto para compartir (Claude) |
| `/api/briefing.mp3` | GET | Briefing España |
| `/api/read` | POST | Marcar URL como leída (KV ledger) |
| `/api/read/clear` | POST | Vaciar ledger |
| `/api/nightly/curate` | GET | Cron nocturno — fetch + curate |

## Stack

Python 3.13 · Flask en Vercel Functions · Vercel Blob (artefactos) · Upstash Redis vía Vercel KV (read ledger) · Vercel Cron · Claude Sonnet 4.6 (briefing España + España pick + share-text) · OpenAI gpt-4o-mini-tts · Chart.js · Polymarket CLOB · httpx + BeautifulSoup + lxml.
