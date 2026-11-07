"""Radar and briefing for the España tab, written on the Mac mini.

Runs from launchd (ops/com.jorge.readerme-ia.plist) every morning after the
Vercel nightly. It reads spain.json, polls.json and markets.json from Vercel
Blob, asks `claude -p` (Jorge's Claude subscription, not the paid API) to pick
the ten articles that matter for political risk and to write a short factual
briefing, and writes spain.json back with both.

    .venv/bin/python spain_ai.py          # skip if today's file already has it
    .venv/bin/python spain_ai.py --force  # redo it anyway

Needs BLOB_READ_WRITE_TOKEN in .env.local (`vercel env pull .env.local`).
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

import storage

ROOT = pathlib.Path(__file__).resolve().parent

CLAUDE = os.environ.get("CLAUDE_BIN", str(pathlib.Path.home() / ".local/bin/claude"))
MODEL = os.environ.get("READERME_MODEL", "claude-sonnet-5-5")
RADAR_SIZE = 10

SCHEMA = {
    "type": "object",
    "properties": {
        "radar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "summary_es": {"type": "string"},
                },
                "required": ["index", "summary_es"],
                "additionalProperties": False,
            },
        },
        "briefing": {"type": "string"},
    },
    "required": ["radar", "briefing"],
    "additionalProperties": False,
}


def _poll_lines(polls: dict) -> list[str]:
    lines = []
    averages = polls.get("averages") or {}
    for party in ("PP", "PSOE", "VOX", "SUMAR", "PODEMOS"):
        latest = next((v for v in reversed(averages.get(party) or []) if v is not None), None)
        if latest is not None:
            lines.append(f"- {party}: {latest}%")
    bloc = polls.get("bloc") or {}
    if bloc:
        lines.append(f"- Bloque derecha (PP+Vox): {bloc.get('right_bloc', '?')}%")
        lines.append(f"- Bloque izquierda (PSOE+Sumar+Podemos+regionales): {bloc.get('left_bloc', '?')}%")
        lines.append(f"- Diferencia: {bloc.get('gap_label', '?')}")
    return lines


def _market_lines(markets: dict) -> list[str]:
    lines = []
    for event in (markets or {}).get("events", []):
        outcomes = "; ".join(f"{o['label'] or 'Sí'} {o['price']}%" for o in event.get("outcomes", []))
        lines.append(f"- {event['title']}: {outcomes}")
    return lines


def build_prompt(spain: dict, polls: dict, markets: dict) -> str:
    candidates = spain.get("candidates") or []
    articles = "\n\n".join(
        f"[{i}] \"{a['title']}\" — {a['source']}\n    {(a.get('summary') or '')[:200]}"
        for i, a in enumerate(candidates)
    )
    intl = "\n".join(f"- {a['title']} ({a['source']}): {a.get('summary', '')[:200]}"
                     for a in spain.get("intl") or []) or "Sin artículos nuevos hoy."
    return f"""Trabajas para un lector personal de noticias. Haz dos cosas con los datos de abajo y responde con el JSON pedido.

1. radar: elige las {RADAR_SIZE} noticias de medios españoles más relevantes para el análisis de riesgo político del país, como lo haría un analista de Eurasia Group. Prioriza estabilidad del Gobierno, cambios legislativos o regulatorios de calado, tensiones territoriales, política fiscal y presupuestaria, relación con la UE, conflictividad sindical, encuestas y dinámica electoral, nombramientos o dimisiones clave y política energética o industrial con impacto macro. Deja fuera sucesos, deportes, cultura y crónica social. Para cada una da su índice [N] y una frase en español orientada a riesgo político, analítica y no descriptiva.

2. briefing: un resumen escrito de la situación política de hoy, de 250 a 350 palabras como máximo, en español. Tono de agencia: factual, sin opinión ni valoraciones de riesgo, sin decir si la situación «se calienta». Primer párrafo: encuestas, con la cifra de cada partido y de los bloques. Segundo párrafo: de los mercados de predicción, solo las dos o tres cifras que más dicen, no todas. Después, las noticias más relevantes: qué ha pasado, quién lo ha dicho o hecho y un dato concreto si lo hay. No conectes noticias con interpretaciones causales. Escribe cifras con coma decimal y el signo % («31,2%»). Párrafos corridos separados por una línea en blanco, sin títulos, viñetas, negritas ni ningún otro formato.

ENCUESTAS (media):
{chr(10).join(_poll_lines(polls)) or "No disponibles."}

MERCADOS DE PREDICCIÓN (Polymarket):
{chr(10).join(_market_lines(markets)) or "No disponibles."}

PRENSA INTERNACIONAL SOBRE ESPAÑA:
{intl}

PRENSA ESPAÑOLA ({len(candidates)} artículos):
{articles}
"""


def ask_claude(prompt: str) -> dict:
    cmd = [CLAUDE, "-p", "--model", MODEL, "--output-format", "json",
           "--json-schema", json.dumps(SCHEMA), "--tools", "", "--strict-mcp-config",
           "--no-session-persistence"]
    run = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900, cwd=ROOT)
    if run.returncode:
        raise RuntimeError(f"claude -p failed ({run.returncode}): {run.stderr[-500:] or run.stdout[-500:]}")
    reply = json.loads(run.stdout)
    if reply.get("is_error") or not isinstance(reply.get("structured_output"), dict):
        raise RuntimeError(f"claude -p returned no structured output: {str(reply.get('result'))[:500]}")
    return reply["structured_output"]


def apply(spain: dict, answer: dict) -> dict:
    candidates = spain.get("candidates") or []
    radar, used = [], set()
    for pick in answer.get("radar", []):
        idx = pick.get("index")
        if not isinstance(idx, int) or not 0 <= idx < len(candidates) or idx in used:
            continue
        used.add(idx)
        radar.append({**candidates[idx], "risk_summary": pick.get("summary_es", "").strip()})
        if len(radar) == RADAR_SIZE:
            break
    if not radar:
        raise RuntimeError("Claude picked no valid articles")
    # Models sometimes escape the paragraph breaks inside the JSON string.
    briefing = (answer.get("briefing") or "").replace("\\n", "\n").strip()
    return {
        **spain,
        "spanish": radar,
        "radar_source": "claude",
        "briefing": briefing,
        "ai_at": datetime.now(timezone.utc).isoformat(),
        "ai_for": spain.get("generated_at"),
        "ai_model": MODEL,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="redo even if today's radar is done")
    args = parser.parse_args()

    # Only here, never at import: tests import this module and must not see
    # the production Blob token. storage reads the variable at call time.
    load_dotenv(ROOT / ".env.local")
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        print("BLOB_READ_WRITE_TOKEN missing: run `vercel env pull .env.local` in the repo", file=sys.stderr)
        return 2

    spain = storage.read_json("spain.json") or {}
    if not spain.get("candidates"):
        print("spain.json has no candidates yet (nightly not run with the new code?)")
        return 1
    if spain.get("ai_for") == spain.get("generated_at") and not args.force:
        print(f"Already done for {spain.get('generated_at')}")
        return 0

    polls = storage.read_json("polls.json") or {}
    markets = storage.read_json("markets.json") or {}
    print(f"{datetime.now():%Y-%m-%d %H:%M} — {len(spain['candidates'])} candidates, asking {MODEL}…")
    answer = ask_claude(build_prompt(spain, polls, markets))
    updated = apply(spain, answer)

    # The nightly may have rewritten the file while Claude was thinking.
    latest = storage.read_json("spain.json") or {}
    if latest.get("generated_at") != spain.get("generated_at"):
        print("spain.json changed meanwhile; run again to use the new candidates", file=sys.stderr)
        return 1
    storage.write_json("spain.json", updated)
    print(f"Radar: {len(updated['spanish'])} picks, briefing {len(updated['briefing'].split())} words")
    return 0


def notify(message: str) -> None:
    """macOS notification so a failed morning run doesn't go unnoticed."""
    subprocess.run(["/usr/bin/osascript", "-e", "on run argv", "-e",
                    "display notification (item 1 of argv) with title \"readerme\"", "-e", "end run",
                    message[:200]], capture_output=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"{datetime.now():%Y-%m-%d %H:%M} — failed: {exc}", file=sys.stderr)
        notify(f"Radar de España sin hacer: {exc}")
        sys.exit(1)
