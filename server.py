"""Minimal Flask server for the readerme microsite.

No route calls a model: the only AI step (España radar + briefing) runs on the
Mac mini with `claude -p`, see spain_ai.py.
"""

import os
import traceback
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify

import markets
import read_store
import storage
import portadas

app = Flask(__name__)


def _es_number(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


@app.template_filter("pct")
def pct(value) -> str:
    """87.5 -> «87,5%»; under 1 % is shown as «<1%»."""
    if not isinstance(value, (int, float)):
        return ""
    if 0 < value < 1:
        return "<1%"
    return _es_number(value) + "%"


@app.template_filter("pp")
def pp(value) -> str:
    """Weekly change in points: +3.5 -> «+3,5»; tiny or missing -> «=» / «»."""
    if not isinstance(value, (int, float)):
        return ""
    if abs(value) < 0.5:
        return "="
    return ("+" if value > 0 else "−") + _es_number(abs(value))


def _stamp(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return ""


@app.route("/")
def front_pages():
    return render_template("portadas.html", newspapers=portadas.NEWSPAPERS)


@app.route("/api/portadas/<paper_id>")
def api_front_page(paper_id: str):
    result = portadas.fetch_one(paper_id)
    if result is None:
        return jsonify({"ok": False, "error": "unknown newspaper"}), 404
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/main")
def index():
    data = storage.read_json("main.json")
    if not data:
        return render_template("index.html", articles=[], markets=[],
                               generated_at="Run 'python run.py' first", total=0)

    generated_at = data.get("generated_at", "")
    if generated_at:
        dt = datetime.fromisoformat(generated_at)
        generated_at = dt.strftime("%d %b %Y, %H:%M")

    articles = read_store.filter_unread(data.get("articles", []))
    return render_template(
        "index.html",
        articles=articles,
        markets=markets.load("markets_main.json"),
        generated_at=generated_at,
        total=len(articles),
        has_items=bool(data.get("articles")),
    )


@app.route("/espana")
def espana():
    spain_data = storage.read_json("spain.json") or {}
    polls_data = storage.read_json("polls.json") or {}

    # The briefing only counts if it was written for today's candidates.
    fresh_ai = spain_data.get("radar_source") == "claude" and \
        spain_data.get("ai_for") == spain_data.get("generated_at")
    briefing = spain_data.get("briefing", "") if fresh_ai else ""

    return render_template(
        "espana.html",
        intl=spain_data.get("intl", []),
        spanish=spain_data.get("spanish", []),
        radar_source="claude" if fresh_ai else "rss",
        briefing=[p.strip() for p in briefing.split("\n\n") if p.strip()],
        briefing_at=_stamp(spain_data.get("ai_at", "")) if fresh_ai else "",
        polls=polls_data,
        markets=markets.load("markets.json"),
        generated_at=_stamp(spain_data.get("generated_at", "")),
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

    return render_template(
        "thinktanks.html",
        sections=sections,
        generated_at=generated_at,
        has_items=bool(tt_data.get("articles")),
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
                           generated_at=generated_at, has_items=bool(data.get("articles")))


@app.route("/api/read", methods=["POST"])
def api_read_mark():
    """Mark an item as read so it disappears from feeds permanently."""
    data = request.get_json(silent=True)
    url = data.get("url") if isinstance(data, dict) else None
    if not isinstance(url, str) or not url.strip():
        return jsonify({"ok": False, "error": "missing url"}), 400
    try:
        read_store.mark(url.strip())
    except Exception:
        app.logger.warning("Read ledger unavailable while marking an article")
        return jsonify({"ok": False, "error": "read ledger unavailable"}), 503
    return jsonify({"ok": True})


@app.route("/api/read/clear", methods=["POST"])
def api_read_clear():
    """Wipe the read ledger."""
    try:
        read_store.clear()
    except Exception:
        app.logger.warning("Read ledger unavailable while clearing")
        return jsonify({"ok": False, "error": "read ledger unavailable"}), 503
    return jsonify({"ok": True})


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
    """Nightly cycle: fetch + store everything. No model is called here; the
    España radar and briefing are added later by spain_ai.py on the mini."""
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
