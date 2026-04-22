"""Minimal Flask server for the readerme microsite."""

import json
import pathlib
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify, send_file

from reader import fetch_html_content

DATA_DIR = pathlib.Path(__file__).parent / "data"

app = Flask(__name__)


def _scrape_web_content(url: str) -> str:
    """Try to scrape readable HTML from a URL."""
    if not url:
        return ""
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise
        for tag in soup.select("script, style, nav, header, footer, aside, .sidebar, .comments, .ad"):
            tag.decompose()

        # Try common article selectors
        article = (
            soup.select_one("article") or
            soup.select_one("[role='main']") or
            soup.select_one(".post-content") or
            soup.select_one(".entry-content") or
            soup.select_one(".article-body") or
            soup.select_one("main")
        )
        if article:
            return str(article)

        # Fallback: grab all paragraphs
        paragraphs = soup.select("p")
        if len(paragraphs) >= 3:
            return "".join(str(p) for p in paragraphs)

        return ""
    except Exception:
        return ""


@app.route("/")
def index():
    curated_file = DATA_DIR / "curated.json"
    if not curated_file.exists():
        return render_template("index.html", articles=[], thinktank=[], abundance=[], generated_at="Run 'python run.py' first", total=0)

    data = json.loads(curated_file.read_text())

    generated_at = data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    return render_template(
        "index.html",
        articles=data.get("articles", []),
        thinktank=data.get("thinktank", []),
        abundance=data.get("abundance", []),
        generated_at=generated_at,
        total=data.get("article_count_total", 0),
    )


@app.route("/espana")
def espana():
    spain_file = DATA_DIR / "spain.json"
    polls_file = DATA_DIR / "polls.json"

    spain_data = {}
    if spain_file.exists():
        spain_data = json.loads(spain_file.read_text())

    polls_data = {}
    if polls_file.exists():
        polls_data = json.loads(polls_file.read_text())

    markets_file = DATA_DIR / "markets.json"
    markets_data = {}
    if markets_file.exists():
        markets_data = json.loads(markets_file.read_text())

    generated_at = spain_data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    has_audio = (DATA_DIR / "briefing.mp3").exists()

    return render_template(
        "espana.html",
        intl=spain_data.get("intl", []),
        spanish=spain_data.get("spanish", []),
        polls=polls_data,
        markets=markets_data,
        generated_at=generated_at,
        has_audio=has_audio,
    )


@app.route("/thinktanks")
def thinktanks():
    tt_file = DATA_DIR / "thinktanks.json"
    tt_data = {}
    if tt_file.exists():
        tt_data = json.loads(tt_file.read_text())

    generated_at = tt_data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    # Group by source
    by_source = {}
    for a in tt_data.get("articles", []):
        src = a.get("source", "Other")
        by_source.setdefault(src, []).append(a)

    return render_template(
        "thinktanks.html",
        by_source=by_source,
        generated_at=generated_at,
    )


@app.route("/api/briefing.mp3")
def briefing_audio():
    audio_file = DATA_DIR / "briefing.mp3"
    if not audio_file.exists():
        return jsonify({"ok": False}), 404
    return send_file(audio_file, mimetype="audio/mpeg")


@app.route("/api/content/<doc_id>")
def content(doc_id):
    html = fetch_html_content(doc_id)
    if html:
        return jsonify({"ok": True, "html": html})
    return jsonify({"ok": False, "html": ""})


@app.route("/api/scrape")
def scrape():
    url = request.args.get("url", "")
    html = _scrape_web_content(url)
    if html:
        return jsonify({"ok": True, "html": html})
    return jsonify({"ok": False, "html": ""})



@app.route("/api/share-text", methods=["POST"])
def share_text():
    """Generate a ready-to-share LinkedIn/X post based on an article."""
    import anthropic
    from dotenv import load_dotenv
    load_dotenv()

    data = request.get_json()
    title = data.get("title", "")
    url = data.get("url", "")
    content_snippet = data.get("content", "")[:3000]

    # Load author profile for voice
    profile_file = DATA_DIR / "profile.json"
    profile = {}
    if profile_file.exists():
        profile = json.loads(profile_file.read_text())

    client = anthropic.Anthropic(timeout=120.0, max_retries=2)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": f"""Escribe un texto corto para compartir en LinkedIn o X (Twitter). El autor es Jorge Galindo, analista de políticas públicas con perspectiva YIMBY/abundance.

PERFIL: {json.dumps(profile, ensure_ascii=False)}

ARTÍCULO:
Título: {title}
URL: {url}
Contenido: {content_snippet}

INSTRUCCIONES:
- Tono: analítico pero accesible, directo, sin florituras. Como alguien que comparte algo que le ha hecho pensar.
- NO resumas el artículo. Extrae 1-2 takeaways o reflexiones propias que conecten con su perspectiva.
- Puede ser en español o inglés según el artículo y la audiencia natural.
- Incluye el link al final.
- Longitud: 2-4 frases. Máximo 280 caracteres para X o un párrafo corto para LinkedIn.
- NO uses hashtags, NO uses emojis, NO empieces con "Interesante artículo" ni fórmulas genéricas.
- Ready to copy-paste. Solo el texto, nada más."""
        }],
    )

    text = response.content[0].text.strip()
    return jsonify({"ok": True, "text": text})
