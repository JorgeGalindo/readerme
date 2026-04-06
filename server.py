"""Minimal Flask server for the readerme microsite."""

import json
import os
import pathlib
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify

from reader import archive_article, save_url, fetch_html_content

DATA_DIR = pathlib.Path(__file__).parent / "data"
FEEDBACK_FILE = DATA_DIR / "feedback.json"

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

    generated_at = spain_data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    return render_template(
        "espana.html",
        intl=spain_data.get("intl", []),
        spanish=spain_data.get("spanish", []),
        polls=polls_data,
        generated_at=generated_at,
    )


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


@app.route("/api/feedback", methods=["POST"])
def feedback():
    data = request.get_json()
    liked = data.get("liked", True)
    doc_id = data.get("id", "")
    source_url = data.get("source_url", "")
    section = data.get("section", "")

    entry = {
        "title": data.get("title", ""),
        "tag": data.get("tag", ""),
        "section": section,
        "liked": liked,
        "id": doc_id,
        "source_url": source_url,
        "date": datetime.now(timezone.utc).isoformat(),
    }

    feedback_list = []
    if FEEDBACK_FILE.exists():
        feedback_list = json.loads(FEEDBACK_FILE.read_text())
    feedback_list.append(entry)
    FEEDBACK_FILE.write_text(json.dumps(feedback_list, ensure_ascii=False, indent=2))

    reader_synced = False
    if liked and section == "feeds" and doc_id:
        reader_synced = archive_article(doc_id)
    elif liked and section in ("thinktank", "abundance") and source_url:
        reader_synced = save_url(source_url)
    elif not liked and section == "feeds" and doc_id:
        reader_synced = archive_article(doc_id)

    return jsonify({"ok": True, "reader_synced": reader_synced})


@app.route("/api/post-idea", methods=["POST"])
def post_idea():
    """Generate a post idea using Opus based on an article."""
    import anthropic
    from dotenv import load_dotenv
    load_dotenv()

    data = request.get_json()
    title = data.get("title", "")
    content_snippet = data.get("content", "")[:3000]

    # Load author profile for voice/angle
    profile_file = DATA_DIR / "profile.json"
    profile = {}
    if profile_file.exists():
        profile = json.loads(profile_file.read_text())

    opus = anthropic.Anthropic(timeout=120.0, max_retries=2)
    response = opus.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"""Eres el asistente editorial de un analista de políticas públicas que escribe en Substack en español.

PERFIL DEL AUTOR:
{json.dumps(profile, ensure_ascii=False)}

ARTÍCULO QUE ACABA DE LEER:
Título: {title}
Contenido: {content_snippet}

Genera UNA idea de post para su Substack. La idea debe:
- Conectar este artículo con sus temas habituales y perspectiva YIMBY/abundance
- Proponer un ÁNGULO original, no un resumen del artículo
- Incluir una tesis clara y provocadora
- Sugerir 2-3 datos o fuentes que podría usar
- Estar en español

Formato:
**Título tentativo:** ...
**Tesis:** (1-2 frases)
**Ángulo:** (por qué esto importa desde su perspectiva)
**Datos a buscar:** (2-3 puntos concretos)
**Primera frase del post:** (un arranque potente)"""
        }],
    )

    idea = response.content[0].text
    return jsonify({"ok": True, "idea": idea})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5555))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None
    app.run(host="0.0.0.0", port=port, debug=debug)
