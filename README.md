# readerme

Lector personal con cinco pestañas (Portadas, Main, España, Thinktanks, Papers) y mercados de predicción.

Desde noviembre de 2026 nada de lo que corre en Vercel llama a una API de pago. La única parte con IA (elegir el radar de España y escribir su briefing) la hace el Mac mini cada mañana con `claude -p`, que va con la suscripción de Claude, no con créditos de la API. Si el mini no la hace, la pestaña se actualiza igual, sin esa selección. El audio del briefing (OpenAI TTS) y el texto generado del botón Compartir se quitaron.

## Cómo funciona

```
Vercel, 02:00 UTC (/api/nightly/curate, sin modelos)
  data/feeds.json ─► rss.py ─► curator.py ─► main.json ──────────────► /main
                            ├► thinktanks.py ─► thinktanks.json ─────► /thinktanks
                            └► papers.py ─► papers.json ─────────────► /papers
  spain.py (RSS medios + prensa internacional) ─► spain.json ────────► /espana
  markets.py (Polymarket Gamma + CLOB) ─► markets_main.json / markets.json
  polls.py (colmenadedatos) ─► polls.json

Mac mini, 07:00 y 09:30 (launchd com.jorge.readerme-ia)
  spain_ai.py: spain.json + polls.json + markets.json ─► claude -p ─► spain.json
               (radar de 10 noticias con su frase + briefing en texto)

Al abrir Portadas: /api/portadas/<medio>, una petición por periódico
```

## Pestañas

### Portadas (`/`)

La primera pestaña: medio y titular principal enlazado. Al abrirla, y al volver a la app, se consultan de nuevo las portadas si lo guardado tiene más de tres minutos; el botón **Actualizar** fuerza la consulta. Cada periódico es una petición propia (`/api/portadas/<id>`), así que cada fila se rellena en cuanto su medio responde y un medio lento no retiene a los demás. Mientras se actualiza, el titular anterior se ve atenuado. Si un medio no responde o cambia su HTML, se muestra «No disponible · abrir portada».

La última consulta se guarda en este navegador. En iOS, al volver a la app, se abre Portadas; lo mismo al regresar de una noticia.

Incluye El País, El Mundo, El Confidencial, The Objective, ABC, elDiario.es, La Razón, La Vanguardia, ARA, El Español, Público, 20minutos, infoLibre y Vozpópuli. El Periódico y El Periódico de España se quitaron el 7 de noviembre de 2026: responden 406 a este cliente y su fila solo decía «No disponible». Los selectores de apertura viven en `portadas.py`; El Mundo exige además que el enlace tenga fecha en la ruta, porque encima de la apertura pone un carrusel de juegos con el mismo marcado. No se sustituye la apertura por el último artículo de un RSS.

Las funciones corren en París (`cdg1`, en `vercel.json`): más cerca de los periódicos y de quien lee, y con IP europea, porque desde EE. UU. El País sirve su edición América.

### Main (`/main`)
- **Mercados de predicción**: ocho eventos de Polymarket, dos por tema (geopolítica, economía, elecciones, IA). Ver «Mercados».
- **Artículos**: orden cronológico. No hay scoring: lo que entra por RSS aparece aquí.
- Cada card: el título enlaza **directamente a la fuente original** (sin página intermedia), **Compartir** abre la hoja de compartir del sistema con título y enlace (o los copia si no la hay), **Leído** oculta la card y la apunta en el ledger.

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
> la app.
>
> **Y el AASA del dominio no basta.** El apretón de manos tiene dos lados: el
> dominio declara la app *y* la app declara el dominio (entitlement
> `Associated Domains`, lista fija dentro del binario). Substack sirve el AASA
> en cada dominio propio, pero su app solo puede reclamar `substack.com`,
> `*.substack.com` y `open.substack.com` — no los cientos de miles de dominios
> de sus publicaciones. Por eso `substack.py` reescribe los posts de dominio
> propio a `open.substack.com/pub/<publicación>/p/<slug>`, que sí abre la app
> y cae a la web si no está instalada. Los posts ya alojados en
> `*.substack.com` se dejan intactos: la app reclama ese comodín.

### España (`/espana`)
- **Briefing de hoy**: texto de 250-350 palabras escrito en el mini (encuestas, mercados, noticias). Solo aparece si es del ciclo de hoy.
- **Cómo va el voto**: Chart.js con datos de colmenadedatos.
- **Mercados**: los seis eventos de Polymarket sobre España con más volumen.
- **Lo que se dice fuera**: Economist, FT, Politico Europe, Guardian (filtro España).
- **Radar de riesgo político**: diez noticias de medios españoles. Con el mini, elegidas por Claude con una frase orientada a riesgo político; sin él, el último titular de cada medio por turnos, con un aviso.

### Thinktanks (`/thinktanks`)
- 3 subsecciones:
  - **Classic**: Tony Blair Institute (sitemap parser), European Policy Centre (HTML scraper).
  - **España**: Elcano, Fedea, BBVA Research (scraper).
  - **Abundance**: Progress Ireland, Abundance Institute, Center for Growth and Opportunity.

### Papers (`/papers`)
- NBER (Education / Children / Political Economy), IZA Discussion Papers, Banco de España, VoxEU/CEPR. Lista cronológica por fuente, sin scoring.

## Mercados

Hasta noviembre de 2026 los mercados eran una lista fija de *token ids*. Se resolvían («Fed baja en junio», «elecciones anticipadas antes del 30 de junio») y la página los seguía enseñando al 0 % con el gráfico vacío. Ahora `markets.py` pide cada noche a la API Gamma de Polymarket los eventos abiertos con más volumen en 24 horas de cada etiqueta (`geopolitics`, `economy`, `world-elections`, `ai`; `spain` para España) y aplica estas reglas:

- el evento debe seguir abierto, cerrar dentro de más de un día y superar un mínimo de volumen, así que el ruido del tipo «gas prices on November 7» se cae solo;
- se descartan los distritos de una elección («Spain General Election: Biscay Winner») y, en elecciones, las primarias de EE. UU. («Nominee»);
- dentro de un evento solo cuentan los mercados vivos: fuera los marcadores («Person H»), los cerrados y los que vencen en menos de un día, y en los de varias opciones las que no llegan al 1 %;
- cada tarjeta enseña hasta tres opciones, de más a menos probable. Las escaleras de fechas («Sánchez out by…?») son acumuladas y van en orden de calendario.

El histórico de 30 días sale del CLOB, de uno en uno con reintentos y una segunda pasada: en paralelo el CLOB corta conexiones. Si una noche no llega ningún evento, se conserva el fichero anterior.

## IA en el mini

`spain_ai.py` lee `spain.json`, `polls.json` y `markets.json` del Blob, manda las candidatas a `claude -p` (modelo `claude-sonnet-5-5`, sin herramientas, salida validada con `--json-schema`) y vuelve a escribir `spain.json` con el radar y el briefing. Si ya está hecho para el ciclo de hoy no repite (`--force` para rehacerlo). Si la nightly reescribe el fichero mientras Claude responde, no pisa nada y lo deja para la siguiente pasada. Un fallo deja una notificación en el Mac y una línea en `~/Library/Logs/readerme-ia.log`.

Instalación en el mini:

```bash
cd ~/repos/readerme
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
vercel env pull .env.local            # trae BLOB_READ_WRITE_TOKEN (entorno Development)
cp ops/com.jorge.readerme-ia.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jorge.readerme-ia.plist
.venv/bin/python spain_ai.py          # prueba a mano
```

## Ciclo diario

Vercel Cron, una sola llamada bajo el límite de 300 s por función:

- **02:00 UTC** → `/api/nightly/curate`
  1. Main RSS deltas → main.json
  2. Polymarket Main → markets_main.json
  3. España (RSS) → spain.json
  4. Thinktanks (RSS por subtag + scrape BBVA)
  5. Papers (RSS)
  6. Polls (colmenadedatos)
  7. Polymarket España → markets.json

Disparable manualmente con `Authorization: Bearer $CRON_SECRET`. Después, a las 07:00 hora local, el mini añade el radar y el briefing.

## Setup

```bash
cd readerme
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

En local no hace falta ninguna clave: los datos viven en disco bajo `data/`.

Producción en Vercel (`https://readerme.vercel.app`) usa:
- `BLOB_READ_WRITE_TOKEN`: Vercel Blob (los JSON de la nightly)
- `KV_REST_API_URL` / `KV_REST_API_TOKEN`: Upstash Redis (read ledger)
- `CRON_SECRET`: protege `/api/nightly/*`

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` y `OPENAI_TTS_VOICE` ya no se usan.

Si no hay `BLOB_READ_WRITE_TOKEN` en el entorno, `storage.py` cae al filesystem
local automáticamente: `python run.py serve` y `python run.py nightly` siguen
funcionando igual sin tocar nada.

El avance de los feeds RSS se confirma después de guardar `main.json`. Si falla ese guardado, las noticias se vuelven a recoger en el próximo intento; si falla la confirmación, se deduplican al reintentarlo. Los artefactos locales y el registro de lecturas se sustituyen de forma atómica para conservar la copia anterior ante una escritura fallida.

«Leído» guarda una cola pendiente en el navegador antes de ocultar la tarjeta. Las lecturas se envían en orden y se reintentan al abrir otra página, recuperar la conexión, volver a la pestaña o tras un fallo temporal. Si el navegador impide guardar datos locales, la tarjeta permanece visible hasta que el servidor confirme. Al terminar la lista aparece «Todo leído por ahora» y se ocultan las secciones vacías.

«Borrar leídos» espera al guardado en curso y comprueba que el servidor haya borrado el registro antes de eliminar la copia local y recargar. Si falla, conserva las lecturas y permite reintentar. En producción, un fallo de Redis devuelve un error recuperable: no se anuncia éxito guardando en un archivo temporal de la función. `static/read.js` comparte este comportamiento entre las cuatro páginas y normaliza las URL con los mismos casos de prueba que Python.

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
├── substack.py       # posts de dominio propio -> open.substack.com (Universal Links)
├── spain.py          # /espana: RSS y radar sin modelo
├── spain_ai.py       # radar + briefing con `claude -p`, corre en el mini
├── polls.py          # encuestas
├── markets.py        # Polymarket: selección automática (Main + España)
├── portadas.py       # titular de apertura de cada periódico
├── nightly.py        # CLI nocturno (dev local)
├── server.py         # Flask + rutas /api/portadas/<id>, /api/read, /api/nightly/curate
├── app.py            # entry point para Vercel (re-exporta server.app)
├── storage.py        # adaptador Blob (prod) / filesystem (dev)
├── read_store.py     # adaptador KV (prod) / JSON local (dev)
├── templates/        # portadas, index, espana, thinktanks, papers, _markets (macro)
├── static/           # style.css, portadas.js, markets.js, share.js, read.js, home.js
├── ops/              # plist de launchd del mini
├── data/             # feeds.json + profile.json (config); outputs en Blob
├── vercel.json       # región cdg1 + cron (02:00 UTC)
└── requirements.txt
```

## API endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/` | GET | Portadas, pestaña inicial |
| `/main` | GET | Main |
| `/api/portadas/<id>` | GET | Titular de apertura de un periódico, consultado ahora |
| `/espana` | GET | España |
| `/thinktanks` | GET | Thinktanks |
| `/papers` | GET | Papers |
| `/api/read` | POST | Marcar URL como leída (KV ledger) |
| `/api/read/clear` | POST | Vaciar ledger |
| `/api/nightly/curate` | GET | Cron nocturno — fetch + curate |

## Pruebas locales

Con las dependencias de Python instaladas y Node disponible:

```bash
python3 -B -m unittest discover -s tests -v
node --test tests/*.test.mjs
```

Estas pruebas simulan fallos de persistencia, cola de lecturas, reintentos, borrado, la hoja de compartir y acceso denegado al almacenamiento o al portapapeles, además de la carga de Portadas por medio, la selección de mercados y el paso del mini (sin llamar a `claude`). También comprueban las claves URL y los endpoints de lectura. Usan datos ficticios, sin llamadas a las APIs externas; los ficheros temporales permanecen dentro de `tests/`.

## Stack

Python 3.13 · Flask en Vercel Functions (cdg1) · Vercel Blob (artefactos) · Upstash Redis vía Vercel KV (read ledger) · Vercel Cron · `claude -p` en el Mac mini (radar y briefing de España) · Chart.js · Polymarket Gamma + CLOB · httpx + BeautifulSoup + lxml.
