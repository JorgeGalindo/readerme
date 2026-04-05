# readerme

Curador personal de contenido que aprende de lo que escribes y filtra lo que lees. Construido para reemplazar Readwise Reader como interfaz diaria de lectura.

## Cómo funciona

```
Tu Substack (90 artículos) → perfil de escritor → sesgo YIMBY/abundance
                                                          ↓
Readwise Reader (feed RSS + newsletters) ──→ Claude rankea todo ──→ microsite
                                                          ↑
Thinktank Twitter Lists ──→ sección Thinktank      Feedback Sí/No
DuckDuckGo + WiP ──→ sección Mundo Abundancia      (entrena el ranking)
```

Tres secciones:
- **Thinktank** — lo que comparten los think tanks en Twitter (extraído de tus listas de Twitter en Reader)
- **Mundo abundancia** — búsqueda web en el ecosistema YIMBY/abundance (siempre 1 de Works in Progress)
- **Desde tus fuentes** — todo tu feed de Reader, rankeado por relevancia

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
# Curar + servir (el combo completo)
.venv/bin/python run.py

# Solo curar sin servidor
.venv/bin/python run.py curate

# Solo servir lo ya curado
.venv/bin/python run.py serve

# Ciclo nocturno (procesa feedback + re-cura)
.venv/bin/python run.py nightly

# Opciones
.venv/bin/python run.py curate --days 7    # última semana
.venv/bin/python run.py serve --port 8080  # otro puerto
```

Desde el iPad u otro dispositivo en la misma red, abre la IP local que muestra al arrancar (ej: `http://192.168.1.68:5555`).

## Ciclo diario

1. **Madrugada**: `run.py nightly` procesa el feedback del día anterior (Sí → archiva en Reader, No → marca como visto) y genera una curación fresca
2. **Durante el día**: lees desde readerme, marcas Sí/No en cada artículo
3. **Siguiente madrugada**: repite

El ranking se estabiliza con el uso gracias a:
- Rúbrica explícita (relevancia 0-30, sustantividad 0-25, alineación YIMBY 0-25, novedad 0-20)
- Ranking comparativo (ordena primero, puntúa después)
- Cache de scores (max ±10 puntos entre pasadas)
- Feedback como calibración (ejemplos concretos de Sí/No en el prompt)

## Lectura inline

Botón "Leer" en cada artículo:
- Artículos de Reader → contenido completo vía API
- Artículos de búsqueda web → scraping (funciona en blogs y think tanks, no en paywalls)

Si el contenido no está disponible, el botón desaparece.

## Stack

- Python 3.10+
- Flask (servidor)
- Anthropic API / Claude Sonnet (curación)
- Readwise Reader API (fuente de lectura, bidireccional)
- DuckDuckGo (búsqueda web para abundance)
- httpx + BeautifulSoup (scraping)

## Estructura

```
readerme/
├── run.py          # CLI: curate / serve / nightly
├── curator.py      # perfil + ranking + búsquedas
├── reader.py       # Readwise Reader API (fetch, archive, save)
├── substack.py     # scraper de jorgegalindo.substack.com
├── server.py       # Flask + endpoints API
├── nightly.py      # ciclo nocturno (feedback + re-curación)
├── templates/
│   └── index.html  # microsite
├── static/
│   └── style.css   # Roboto Mono Light, responsive, dark mode
├── data/           # (gitignored) cache, feedback, scores
├── .env            # (gitignored) tokens
└── requirements.txt
```
