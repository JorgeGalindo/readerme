"""Fetch and curate Spanish political risk news."""

import json
import pathlib
import time
import xml.etree.ElementTree as ET

import anthropic
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = pathlib.Path(__file__).parent / "data"
SPAIN_FILE = DATA_DIR / "spain.json"
SEEN_INTL_FILE = DATA_DIR / "seen_intl.json"

client = anthropic.Anthropic(timeout=180.0, max_retries=3)

# International feeds — direct Spain tags, no AI needed
FEEDS_INTL = {
    "The Economist": "https://www.economist.com/europe/rss.xml",
    "Financial Times": "https://www.ft.com/spain?format=rss",
    "Politico Europe": "https://www.politico.eu/feed/",
    "The Guardian Europe": "https://www.theguardian.com/world/europe-news/rss",
}

FEEDS_ES = {
    "El País (España)": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/espana/portada",
    "El País (Economía)": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada",
    "El Confidencial": "https://rss.elconfidencial.com/espana/",
    "El Mundo": "https://e00-elmundo.uecdn.es/elmundo/rss/espana.xml",
    "eldiario.es": "https://www.eldiario.es/rss/politica/",
}

# eldiario supports inline reading
SCRAPEABLE_DOMAINS = {"eldiario.es"}

NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
}


def _fetch_feed(url: str) -> str:
    """Fetch raw XML from a feed URL."""
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  Failed to fetch {url}: {e}")
        return ""


def _parse_rss(xml_text: str, source_name: str) -> list[dict]:
    """Parse RSS 2.0 feed."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            author = (item.findtext("dc:creator", namespaces=NS) or
                      item.findtext("author") or "").strip()
            desc = item.findtext("description") or ""
            # Strip HTML from description
            summary = BeautifulSoup(desc, "html.parser").get_text(strip=True)[:300]
            pub_date = (item.findtext("pubDate") or "").strip()

            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "author": author,
                    "summary": summary,
                    "date": pub_date,
                    "source": source_name,
                })
    except ET.ParseError as e:
        print(f"  XML parse error for {source_name}: {e}")
    return items


def _parse_atom(xml_text: str, source_name: str) -> list[dict]:
    """Parse Atom feed (El Confidencial)."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            title = (entry.findtext("a:title", namespaces=ns) or "").strip()
            link_el = entry.find("a:link[@rel='alternate']", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            author = (entry.findtext("a:author/a:name", namespaces=ns) or "").strip()
            summary_el = entry.findtext("a:summary", namespaces=ns) or ""
            summary = BeautifulSoup(summary_el, "html.parser").get_text(strip=True)[:300]
            pub_date = (entry.findtext("a:published", namespaces=ns) or "").strip()

            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "author": author,
                    "summary": summary,
                    "date": pub_date,
                    "source": source_name,
                })
    except ET.ParseError as e:
        print(f"  Atom parse error for {source_name}: {e}")
    return items


def _load_seen_intl() -> set:
    if SEEN_INTL_FILE.exists():
        return set(json.loads(SEEN_INTL_FILE.read_text()))
    return set()


def _save_seen_intl(seen: set):
    DATA_DIR.mkdir(exist_ok=True)
    SEEN_INTL_FILE.write_text(json.dumps(list(seen)))


def fetch_intl_spain() -> list[dict]:
    """Fetch Economist and FT articles about Spain. No AI — just fetch, filter new, show."""
    seen = _load_seen_intl()
    spain_articles = []

    for source, url in FEEDS_INTL.items():
        print(f"  Fetching {source}...")
        xml = _fetch_feed(url)
        if not xml:
            continue
        items = _parse_rss(xml, source)

        for item in items:
            if item["link"] in seen:
                continue
            # Hard filter: 2026+ only
            date_str = (item.get("date") or "").lower()
            if "2025" in date_str or "2024" in date_str or "2023" in date_str:
                continue

            if source == "Financial Times":
                # FT has a Spain-specific feed, no keyword filter needed
                ft_count = sum(1 for a in spain_articles if a["source"] == "Financial Times")
                if ft_count >= 3:
                    continue
                spain_articles.append(item)
                seen.add(item["link"])
            else:
                # General Europe feeds — filter for Spain mentions
                text = f"{item['title']} {item['summary']}".lower()
                if any(kw in text for kw in ("spain", "spanish", "españa", "madrid", "barcelona", "sánchez", "sanchez", "rajoy", "vox ", "podemos", "catalon")):
                    spain_articles.append(item)
                    seen.add(item["link"])
        time.sleep(0.5)

    _save_seen_intl(seen)
    return spain_articles


def fetch_spanish_media() -> list[dict]:
    """Fetch articles from Spanish national media."""
    all_articles = []
    for source, url in FEEDS_ES.items():
        print(f"  Fetching {source}...")
        xml = _fetch_feed(url)
        if not xml:
            continue

        if "elconfidencial" in url:
            items = _parse_atom(xml, source)
        else:
            items = _parse_rss(xml, source)

        # Mark scrapeable
        for item in items:
            domain = ""
            if "eldiario.es" in (item.get("link") or ""):
                domain = "eldiario.es"
            item["scrapeable"] = domain in SCRAPEABLE_DOMAINS and domain != ""

        all_articles.extend(items[:20])  # Max 20 per source
        time.sleep(0.5)

    return all_articles


def curate_spain() -> dict:
    """Fetch all sources and curate for political risk analysis."""
    print("Fetching international sources...")
    intl = fetch_intl_spain()
    print(f"  {len(intl)} international articles about Spain")

    print("Fetching Spanish media...")
    spanish = fetch_spanish_media()
    print(f"  {len(spanish)} Spanish media articles")

    # Curate Spanish media: pick 10 most relevant for political risk
    curated_spanish = []
    if spanish:
        article_list = []
        for i, a in enumerate(spanish):
            article_list.append(
                f"[{i}] \"{a['title']}\" — {a['source']}\n"
                f"    {a['summary'][:200]}"
            )
        articles_text = "\n\n".join(article_list)

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": f"""Eres un analista de riesgo político de Eurasia Group especializado en España. De estas noticias de medios españoles, selecciona las 10 más relevantes para el análisis de riesgo político del país.

Prioriza:
- Movimientos políticos que afecten estabilidad gubernamental
- Cambios regulatorios o legislativos significativos
- Tensiones territoriales (Cataluña, etc.)
- Política fiscal y presupuestaria
- Relaciones con la UE
- Movimientos sindicales o protestas
- Cambios en encuestas o dinámicas electorales
- Nombramientos clave o dimisiones
- Política energética o industrial con impacto macro

NO priorices: sucesos, deportes, cultura, crónica social.

ARTÍCULOS ({len(spanish)}):
{articles_text}

Para cada seleccionado:
- index: el [N] original
- summary_es: UNA frase de resumen orientada a riesgo político (no descriptiva, analítica)

Responde SOLO JSON array, sin markdown:
[{{"index": 0, "summary_es": "..."}}, ...]"""
            }],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        picks = json.loads(text)

        for p in picks[:10]:
            idx = p["index"]
            if 0 <= idx < len(spanish):
                article = spanish[idx].copy()
                article["risk_summary"] = p["summary_es"]
                curated_spanish.append(article)

    # International: no AI needed — use RSS summary directly, filter 2026+
    curated_intl = []
    for a in intl:
        date_str = (a.get("date") or "").lower()
        if "2025" in date_str or "2024" in date_str or "2023" in date_str:
            continue
        a["risk_summary"] = a["summary"]
        curated_intl.append(a)

    from datetime import datetime, timezone
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "intl": curated_intl,
        "spanish": curated_spanish,
    }

    DATA_DIR.mkdir(exist_ok=True)
    SPAIN_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Spain curated: {len(curated_intl)} intl + {len(curated_spanish)} national")

    # Generate audio briefing
    generate_audio_briefing(curated_intl, curated_spanish)

    return result


def generate_audio_briefing(intl: list[dict], spanish: list[dict]):
    """Generate a spoken political risk briefing from curated news + markets."""
    import asyncio
    import edge_tts

    # Load markets data if available
    markets_file = DATA_DIR / "markets.json"
    markets = {}
    if markets_file.exists():
        markets = json.loads(markets_file.read_text())

    # Load polls data if available
    polls_file = DATA_DIR / "polls.json"
    polls = {}
    if polls_file.exists():
        polls = json.loads(polls_file.read_text())

    # Build context for Claude
    intl_lines = [f"- {a['title']} ({a['source']}): {a.get('risk_summary', '')}" for a in intl]
    spanish_lines = [f"- {a['title']} ({a['source']}): {a.get('risk_summary', '')}" for a in spanish]

    markets_lines = []
    for m in markets.values():
        markets_lines.append(f"- {m['title']}: {m['current']}%")

    polls_lines = []
    if polls.get("bloc"):
        bloc = polls["bloc"]
        avgs = polls.get("averages", {})
        # Get latest value for each party
        for party in ["PP", "PSOE", "VOX", "SUMAR", "PODEMOS"]:
            vals = avgs.get(party, [])
            latest = next((v for v in reversed(vals) if v is not None), None)
            if latest is not None:
                polls_lines.append(f"- {party}: {latest}%")
        polls_lines.append(f"- Bloque derecha (PP+VOX): {bloc.get('right_bloc', '?')}%")
        polls_lines.append(f"- Bloque izquierda (PSOE+Sumar+Podemos+regionales): {bloc.get('left_bloc', '?')}%")
        polls_lines.append(f"- Diferencia: {bloc.get('gap_label', '?')}")

    prompt = f"""Genera un briefing de audio sobre la situación política en España. Será leído por un TTS, así que escribe como se habla: frases claras, ritmo natural, sin bullet points ni formato.

ENCUESTAS DE INTENCIÓN DE VOTO (media de encuestas):
{chr(10).join(polls_lines) if polls_lines else "No disponibles."}

MERCADOS DE PREDICCIÓN:
{chr(10).join(markets_lines) if markets_lines else "No disponibles."}

PRENSA INTERNACIONAL SOBRE ESPAÑA:
{chr(10).join(intl_lines) if intl_lines else "Sin artículos hoy."}

PRENSA ESPAÑOLA:
{chr(10).join(spanish_lines)}

INSTRUCCIONES:
- Tono: periodista de agencia de noticias. Factual, directo, sin opinión.
- SOLO reporta hechos. NO interpretes, NO saques conclusiones, NO hagas valoraciones de riesgo, NO digas si la situación "se calienta" o "se enfría".
- Estructura: empieza con las encuestas (cifras de cada partido y bloques), luego mercados de predicción, luego las noticias más relevantes de la prensa.
- Cada noticia: qué ha pasado, quién lo ha dicho o hecho, y un dato concreto si lo hay. Nada más.
- NO conectes noticias entre sí con interpretaciones causales.
- Longitud: ~600-900 palabras (para ~3 minutos de audio).
- Idioma: español.
- NO uses encabezados, asteriscos, guiones ni ningún formato. Solo texto corrido con párrafos."""

    print("Generating audio briefing text...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    briefing_text = response.content[0].text.strip()

    # Save text version
    briefing_text_file = DATA_DIR / "briefing.txt"
    briefing_text_file.write_text(briefing_text)

    # Generate audio
    print("Converting to audio...")
    audio_file = DATA_DIR / "briefing.mp3"

    async def _tts():
        communicate = edge_tts.Communicate(briefing_text, "es-ES-AlvaroNeural")
        await communicate.save(str(audio_file))

    asyncio.run(_tts())
    size_kb = audio_file.stat().st_size // 1024
    print(f"  Audio briefing: {size_kb}KB")


if __name__ == "__main__":
    curate_spain()
