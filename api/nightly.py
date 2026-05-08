"""Vercel Cron entry — runs the nightly curation cycle.

Schedule lives in vercel.json. Vercel Cron sends GET with header
`Authorization: Bearer <CRON_SECRET>`, which we verify before running.
Returns JSON with a per-step status so the run is auditable in the
Function logs.

Long-running: this function needs a large maxDuration (set in vercel.json
under functions.api/nightly.py). On Pro with Fluid Compute, up to 800s.
"""

import os
import sys
import pathlib
import traceback
from datetime import datetime, timezone

from flask import Flask, request, jsonify

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

app = Flask(__name__)


def _authorized(req) -> bool:
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        # No secret configured → allow (useful only in dev). Vercel auto-injects
        # CRON_SECRET in production when configured under Project Settings.
        return True
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {expected}"


@app.route("/api/nightly", methods=["GET", "POST"])
def nightly():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    started = datetime.now(timezone.utc).isoformat()
    log: list[dict] = []

    def step(name: str, fn):
        t0 = datetime.now(timezone.utc)
        try:
            fn()
            log.append({"step": name, "ok": True,
                        "secs": (datetime.now(timezone.utc) - t0).total_seconds()})
        except Exception as e:
            log.append({"step": name, "ok": False, "error": str(e),
                        "trace": traceback.format_exc().splitlines()[-5:],
                        "secs": (datetime.now(timezone.utc) - t0).total_seconds()})

    # Local imports so a single failing module doesn't break authorization checks.
    from curator import curate
    from markets import fetch_markets, fetch_markets_main
    from spain import curate_spain
    from thinktanks import curate_thinktanks
    from papers import curate_papers
    from polls import fetch_and_process
    from briefing import generate_main, generate_thinktanks, generate_papers

    step("main_curate", curate)
    step("markets_main", fetch_markets_main)
    step("spain", curate_spain)
    step("thinktanks", curate_thinktanks)
    step("papers", curate_papers)
    step("polls", fetch_and_process)
    step("markets_spain", fetch_markets)
    step("briefing_main", generate_main)
    step("briefing_thinktanks", generate_thinktanks)
    step("briefing_papers", generate_papers)

    return jsonify({
        "ok": all(s["ok"] for s in log),
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "steps": log,
    })
