"""Minimal Flask server for the readerme microsite."""

import io
import json
import os
import traceback
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify, send_file, redirect

import read_store
import storage

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
    data = storage.read_json("main.json")
    if not data:
        return render_template("index.html", articles=[], markets={},
                               generated_at="Run 'python run.py' first", total=0)

    generated_at = data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    markets = storage.read_json("markets_main.json") or {}

    articles = read_store.filter_unread(data.get("articles", []))
    return render_template(
        "index.html",
        articles=articles,
        markets=markets,
        generated_at=generated_at,
        total=len(articles),
    )


@app.route("/espana")
def espana():
    spain_data = storage.read_json("spain.json") or {}
    polls_data = storage.read_json("polls.json") or {}
    markets_data = storage.read_json("markets.json") or {}

    generated_at = spain_data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    has_audio = storage.exists("briefing.mp3")

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
    tt_data = storage.read_json("thinktanks.json") or {}

    generated_at = tt_data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    # Group by subtag, then by source. Subtags ordered: classic, spain, abundance.
    SUBTAG_ORDER = ["classic", "spain", "abundance"]
    SUBTAG_LABEL = {"classic": "Classic", "spain": "España", "abundance": "Abundance"}
    grouped: dict[str, dict[str, list]] = {}
    for a in read_store.filter_unread(tt_data.get("articles", [])):
        sub = a.get("subtag") or "classic"
        src = a.get("source", "Other")
        grouped.setdefault(sub, {}).setdefault(src, []).append(a)

    sections = []
    for sub in SUBTAG_ORDER:
        if sub in grouped:
            sections.append({"key": sub, "label": SUBTAG_LABEL[sub], "by_source": grouped[sub]})

    has_audio = storage.exists("briefing_thinktanks.mp3")
    return render_template(
        "thinktanks.html",
        sections=sections,
        has_audio=has_audio,
        generated_at=generated_at,
    )


@app.route("/papers")
def papers():
    data = storage.read_json("papers.json")
    if not data:
        return render_template("papers.html", by_source={}, generated_at="")

    generated_at = data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    # Group by source, preserving insertion order from feeds.json.
    by_source: dict[str, list] = {}
    for a in read_store.filter_unread(data.get("articles", [])):
        by_source.setdefault(a.get("source", "Other"), []).append(a)

    return render_template("papers.html", by_source=by_source,
                           generated_at=generated_at)


def _serve_audio(name: str):
    """Stream an mp3. In Blob mode, redirect to the public Blob URL (no
    bytes through the function); locally, send the file from disk."""
    url = storage.public_url(name)
    if url:
        return redirect(url, code=302)
    audio_bytes = storage.read_bytes(name)
    if audio_bytes is None:
        return jsonify({"ok": False}), 404
    return send_file(io.BytesIO(audio_bytes), mimetype="audio/mpeg",
                     download_name=name)


@app.route("/api/briefing.mp3")
def briefing_audio():
    """Legacy route — España briefing."""
    return _serve_audio("briefing.mp3")


@app.route("/api/briefing/<tab>.mp3")
def briefing_audio_tab(tab):
    """Per-tab briefing. Spain still uses /api/briefing.mp3 above."""
    if tab not in ("thinktanks",):
        return jsonify({"ok": False}), 404
    return _serve_audio(f"briefing_{tab}.mp3")


@app.route("/api/read", methods=["POST"])
def api_read_mark():
    """Mark an item as read so it disappears from feeds permanently."""
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "missing url"}), 400
    read_store.mark(url)
    return jsonify({"ok": True})


@app.route("/api/read/clear", methods=["POST"])
def api_read_clear():
    """Wipe the read ledger."""
    read_store.clear()
    return jsonify({"ok": True})


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

    profile = storage.read_json("profile.json") or {}

    client = anthropic.Anthropic(timeout=120.0, max_retries=2)
    response = client.messages.create(
        model="claude-sonnet-4-6",
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


def _cron_authorized() -> bool:
    """Vercel Cron sends `Authorization: Bearer <CRON_SECRET>`. If no secret
    is configured we allow it (dev convenience)."""
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        return True
    return request.headers.get("Authorization", "") == f"Bearer {expected}"


def _run_steps(steps: list[tuple[str, callable]]) -> dict:
    """Execute steps sequentially, logging timing + errors. Returns the response payload."""
    started = datetime.now(timezone.utc).isoformat()
    log: list[dict] = []
    for name, fn in steps:
        t0 = datetime.now(timezone.utc)
        try:
            fn()
            log.append({"step": name, "ok": True,
                        "secs": (datetime.now(timezone.utc) - t0).total_seconds()})
        except Exception as e:
            log.append({"step": name, "ok": False, "error": str(e),
                        "trace": traceback.format_exc().splitlines()[-5:],
                        "secs": (datetime.now(timezone.utc) - t0).total_seconds()})
    return {
        "ok": all(s["ok"] for s in log),
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "steps": log,
    }


@app.route("/api/nightly", methods=["GET", "POST"])
@app.route("/api/nightly/curate", methods=["GET", "POST"])
def api_nightly_curate():
    """Phase 1 of the nightly cycle: fetch + curate everything (also runs the
    Spain audio briefing, which is bundled inside curate_spain)."""
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    from curator import curate
    from markets import fetch_markets, fetch_markets_main
    from spain import curate_spain
    from thinktanks import curate_thinktanks
    from papers import curate_papers
    from polls import fetch_and_process

    return jsonify(_run_steps([
        ("main_curate", curate),
        ("markets_main", fetch_markets_main),
        ("spain", curate_spain),
        ("thinktanks", curate_thinktanks),
        ("papers", curate_papers),
        ("polls", fetch_and_process),
        ("markets_spain", fetch_markets),
    ]))


@app.route("/api/nightly/brief", methods=["GET", "POST"])
def api_nightly_brief():
    """Phase 2 of the nightly cycle: generate the Thinktanks audio briefing.
    Reads the JSON snapshots written by /api/nightly/curate."""
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    from briefing import generate_thinktanks

    return jsonify(_run_steps([
        ("briefing_thinktanks", generate_thinktanks),
    ]))
