# readerme

Curador personal de contenido que aprende de lo que escribes y filtra lo que lees. Reemplaza Readwise Reader como interfaz diaria de lectura.

## Cómo funciona

```
Tu Substack (90+ artículos) → perfil de escritor → sesgo YIMBY/abundance
                                                          ↓
Readwise Reader (feed RSS + newsletters) ──→ Claude rankea todo ──→ microsite
                                                          ↑
Thinktank Twitter Lists ──→ sección Thinktank      Botón "Leído" (localStorage)
DuckDuckGo + WiP ──→ sección Mundo Abundancia
RSS medios españoles ──→ sección España             Audio briefing diario
Politico/Economist/FT/Guardian ──→ prensa intl      Encuestas + mercados
Elcano/Fedea/BBVA Research ──→ pestaña Thinktanks
```

## Tres pestañas

### Mundo (`/`)
- **Thinktank** — artículos enlazados en tu lista de Twitter de think tanks (extraídos de los digests de Reader)
- **Mundo abundancia** — búsqueda web en el ecosistema YIMBY/abundance (siempre 1 de Works in Progress)
- **Desde tus fuentes** — todo tu feed de Reader, rankeado por relevancia

Cada card tiene:
- Botón **Leer** para contenido inline (Reader API o scraping)
- Botón **Escuchar** (aparece al expandir) — TTS con detección automática de idioma (español/inglés)
- Botón **Compartir** genera texto listo para LinkedIn/X con link
- Botón **Leído** oculta el artículo (persiste en localStorage)

### España (`/espana`)
- **Briefing de hoy** — audio de ~3 min generado con Claude + edge-tts. Factual: encuestas, mercados de predicción, noticias clave
- **Cómo va el voto** — gráfico de tendencias electorales (datos de colmenadedatos.com)
- **Mercados de predicción** — Polymarket: probabilidad de elecciones anticipadas
- **Lo que se dice fuera** — Economist, FT, Politico Europe, The Guardian sobre España
- **Radar político** — 10 noticias de medios españoles curadas con Claude

### Thinktanks (`/thinktanks`)
- **Real Instituto Elcano** — geopolítica, política exterior, seguridad
- **Fedea** — economía, políticas públicas, mercado laboral
- **BBVA Research** — macro España, análisis sectorial

## Ciclo diario

1. **Madrugada (4AM Madrid)**: GitHub Action ejecuta nightly → vacía Reader feed → puntúa todo → archiva en Reader → genera briefing audio → commit + push → Render redeploy
2. **Durante el día**: lees desde readerme, marcas como Leído lo que vas leyendo
3. **Siguiente madrugada**: artículos no leídos se arrastran (máx 7 días), los nuevos se añaden

## Setup

```bash
cd readerme
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Crea `.env`:
```
READWISE_TOKEN=tu_token_de_readwise
ANTHROPIC_API_KEY=tu_api_key_de_anthropic
```

## Uso

```bash
# Ciclo nocturno completo (mundo + españa + thinktanks)
.venv/bin/python run.py nightly

# Solo curar mundo
.venv/bin/python run.py curate --days 7 --top 10

# Solo curar España
.venv/bin/python run.py curate-spain

# Solo servir lo ya curado
.venv/bin/python run.py serve --port 8080
```

## Ranking

- Rúbrica de 4 dimensiones: relevancia (0-30), sustantividad (0-25), alineación YIMBY (0-25), novedad (0-20)
- Ranking comparativo: ordena primero, puntúa después
- Cache de scores: max ±10 puntos entre pasadas para estabilidad
- Artículos no leídos se arrastran entre curaciones (máx 7 días)

## Deploy

- **Render** (auto-deploy desde `main`)
- **GitHub Actions** (`.github/workflows/nightly.yml`): cron 4AM Madrid → curación + commit + push

## Estructura

```
readerme/
├── run.py          # CLI: curate / serve / curate-spain / nightly
├── curator.py      # perfil + ranking + thinktank + abundance
├── reader.py       # Readwise Reader API (fetch, archive, content)
├── substack.py     # scraper de Substack (perfil de autor)
├── spain.py        # RSS medios españoles + intl + audio briefing
├── thinktanks.py   # Elcano, Fedea, BBVA Research
├── polls.py        # encuestas electorales (colmenadedatos)
├── markets.py      # Polymarket prediction markets
├── nightly.py      # ciclo nocturno (mundo + españa + thinktanks)
├── server.py       # Flask: páginas + API (content, scrape, share, audio)
├── templates/
│   ├── index.html      # Mundo
│   ├── espana.html     # España
│   └── thinktanks.html # Thinktanks
├── static/style.css
├── data/           # cache, scores, audio (committed via GitHub Actions)
├── Procfile        # Render web process
└── requirements.txt
```

## API endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/` | GET | Página Mundo |
| `/espana` | GET | Página España |
| `/thinktanks` | GET | Página Thinktanks |
| `/api/content/<doc_id>` | GET | Contenido HTML de artículo Reader |
| `/api/scrape?url=...` | GET | Scraping de artículo web |
| `/api/share-text` | POST | Generar texto para compartir |
| `/api/briefing.mp3` | GET | Audio briefing político |

## Fuentes bloqueadas

Configuradas en `curator.py`: `BLOCKED_SOURCES = ["cleo abram", "ft shorts"]`

## Stack

Python 3.13 · Flask + Gunicorn · Claude Sonnet (curación, briefing, compartir) · Readwise Reader API · DuckDuckGo · edge-tts · Chart.js · Polymarket CLOB API · httpx + BeautifulSoup
