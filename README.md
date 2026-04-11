# readerme

Curador personal de contenido que aprende de lo que escribes y filtra lo que lees. Reemplaza Readwise Reader como interfaz diaria de lectura.

## Cómo funciona

```
Tu Substack (90+ artículos) → perfil de escritor → sesgo YIMBY/abundance
                                                          ↓
Readwise Reader (feed RSS + newsletters) ──→ Claude rankea todo ──→ microsite
                                                          ↑
Thinktank Twitter Lists ──→ sección Thinktank      Feedback Sí/No
DuckDuckGo + WiP ──→ sección Mundo Abundancia      (entrena el ranking)
RSS medios españoles ──→ sección España             Audio briefing diario
Polymarket + encuestas ──→ mercados/gráficos
```

## Dos páginas

### Mundo (`/`)
Tres secciones:
- **Thinktank** — lo que comparten los think tanks en Twitter (extraído de listas de Twitter en Reader)
- **Mundo abundancia** — búsqueda web en el ecosistema YIMBY/abundance (siempre 1 de Works in Progress)
- **Desde tus fuentes** — todo tu feed de Reader, rankeado por relevancia

Cada card tiene:
- Botones **Sí/No** siempre visibles (collapsed y expanded). Persisten visualmente al recargar. Cuando se expande el artículo, se mueven abajo
- Botón **Leer** para contenido inline (Reader API o scraping)
- Botón **Compartir** (visible al expandir) genera texto listo para LinkedIn/X con tono Jorge Galindo + link. Copy-paste directo
- **Marcar resto como No** al final de la página: marca todos los no marcados como No de golpe

### España (`/espana`)
- **Briefing de hoy** — audio de ~4 min generado con Claude + edge-tts (voz es-ES-AlvaroNeural). Síntesis de mercados de predicción + radar de riesgo político + prensa internacional. Sin encuestas
- **Cómo va el voto** — gráfico de tendencias electorales (datos de colmenadedatos.com/Datawrapper)
- **Mercados de predicción** — Polymarket: probabilidad de elecciones anticipadas
- **Lo que se dice fuera** — FT y Economist sobre España (filtrado por keywords, sin IA)
- **Radar de riesgo político** — 10 noticias de medios españoles curadas con Claude (lente Eurasia Group)

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

- Readwise token: https://readwise.io/access_token
- Anthropic key: https://console.anthropic.com/settings/keys

## Uso

```bash
# Curar mundo + servir
.venv/bin/python run.py

# Solo curar mundo
.venv/bin/python run.py curate --days 7 --top 10

# Solo curar España (noticias + encuestas + mercados + audio)
.venv/bin/python run.py curate-spain

# Solo servir lo ya curado
.venv/bin/python run.py serve --port 8080

# Ciclo nocturno completo (feedback + mundo + españa)
.venv/bin/python run.py nightly

# Solo rebuild del perfil de autor
.venv/bin/python run.py curate --profile-only
```

Desde el iPad u otro dispositivo en la misma red, abre la IP local que muestra al arrancar (ej: `http://192.168.1.68:5555`).

## Ciclo diario

1. **Madrugada**: GitHub Action ejecuta nightly (curación mundo + españa + polls + markets) → commit + push → Render redeploy
2. **Durante el día**: lees desde readerme, marcas Sí/No, compartes lo bueno. El feedback persiste visualmente al recargar la página
3. **Siguiente madrugada**: repite

## Ranking: cómo funciona

- Rúbrica de 4 dimensiones: relevancia (0-30), sustantividad (0-25), alineación YIMBY (0-25), novedad (0-20)
- Ranking comparativo: ordena primero, puntúa después
- Cache de scores: max ±10 puntos entre pasadas para estabilidad
- Feedback como calibración: ejemplos concretos de Sí/No inyectados en el prompt
- Feed persistente: artículos no marcados se arrastran entre curaciones

## Deploy

- Hosted en **Render** (auto-deploy desde `main` en GitHub)
- `Procfile`: `web: gunicorn server:app --bind 0.0.0.0:$PORT`
- `runtime.txt`: Python 3.13.1
- **GitHub Actions** (`.github/workflows/nightly.yml`): cron a las 4:00 AM Madrid → curación mundo + españa + polls + markets + commit + push → Render redeploy automático

## Stack

- Python 3.13
- Flask + Gunicorn (servidor)
- Anthropic API / Claude Sonnet (curación, briefing, compartir)
- Readwise Reader API (fuente de lectura, bidireccional)
- DuckDuckGo (búsqueda web para abundance — queries rotativas por fuente/tema/geografía)
- edge-tts (text-to-speech para briefing, gratis, sin API key)
- Chart.js (gráficos de encuestas y mercados)
- Polymarket CLOB API (mercados de predicción)
- httpx + BeautifulSoup (scraping + RSS parsing)

## Estructura

```
readerme/
├── run.py          # CLI: curate / serve / curate-spain / nightly
├── curator.py      # perfil + ranking + búsquedas (thinktank, abundance)
├── reader.py       # Readwise Reader API (fetch, archive, save)
├── substack.py     # scraper de jorgegalindo.substack.com (perfil de autor)
├── spain.py        # RSS medios españoles + FT/Economist + audio briefing
├── polls.py        # encuestas electorales (colmenadedatos → Datawrapper CSV)
├── markets.py      # Polymarket prediction markets
├── nightly.py      # ciclo nocturno (feedback + re-curación mundo + españa)
├── server.py       # Flask: páginas + API (content, scrape, feedback, share, audio)
├── .github/
│   └── workflows/
│       └── nightly.yml  # GitHub Action: cron 4AM Madrid, curación + push
├── templates/
│   ├── index.html  # página Mundo
│   └── espana.html # página España (charts, audio, radar)
├── static/
│   └── style.css   # Roboto Mono Light, responsive, dark mode
├── data/           # cache, feedback, scores, audio (committed via GitHub Actions)
├── Procfile        # Render web process
├── runtime.txt     # Python version for Render
├── requirements.txt
└── .env            # (gitignored) READWISE_TOKEN, ANTHROPIC_API_KEY
```

## API endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/` | GET | Página Mundo |
| `/espana` | GET | Página España |
| `/api/content/<doc_id>` | GET | Contenido HTML de artículo Reader |
| `/api/scrape?url=...` | GET | Scraping de artículo web |
| `/api/feedback` | POST | Registrar Sí/No + sync a Reader |
| `/api/share-text` | POST | Generar texto para compartir en LinkedIn/X |
| `/api/briefing.mp3` | GET | Audio briefing político |

## Costes estimados

- **Anthropic API**: ~$0.10-0.20/día (curación mundo + españa + briefing + compartir esporádico)
- **edge-tts**: gratis
- **Render**: plan free o starter
- **Readwise Reader**: tu suscripción existente
