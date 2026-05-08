"""Generate audio briefings (text via Claude Opus 4.7, speech via edge-tts).

One function per tab: generate_main(), generate_thinktanks(). Each writes
data/briefing_<tab>.txt and data/briefing_<tab>.mp3.
"""

import asyncio
import os
import tempfile

import anthropic
from dotenv import load_dotenv

import storage

load_dotenv()

MODEL = "claude-opus-4-7"  # latest Opus; falls back to sonnet 4.6 if not provisioned

VOICE_ES = "es-ES-AlvaroNeural"

client = anthropic.Anthropic(timeout=240.0, max_retries=3)


def _claude_text(prompt: str, max_tokens: int = 2000) -> str:
    """Call Claude (latest Opus) for briefing text generation."""
    try:
        resp = client.messages.create(model=MODEL, max_tokens=max_tokens,
                                      messages=[{"role": "user", "content": prompt}])
    except (anthropic.NotFoundError, anthropic.BadRequestError):
        # Fallback chain: opus 4.7 -> sonnet 4.6 -> sonnet 4 (older known-good).
        for fallback in ("claude-sonnet-4-6", "claude-sonnet-4-20250514"):
            try:
                resp = client.messages.create(model=fallback, max_tokens=max_tokens,
                                              messages=[{"role": "user", "content": prompt}])
                print(f"  (fell back to {fallback})")
                break
            except (anthropic.NotFoundError, anthropic.BadRequestError):
                continue
        else:
            raise
    return resp.content[0].text.strip()


def _tts_to_bytes(text: str, voice: str) -> bytes:
    """Synthesize speech with edge-tts, return mp3 bytes."""
    import edge_tts
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        async def run():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(tmp.name)
        asyncio.run(run())
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _save_and_speak(tab: str, text: str, voice: str = VOICE_ES):
    storage.write_bytes(f"briefing_{tab}.txt", text.encode("utf-8"),
                        "text/plain; charset=utf-8")
    print(f"  generating {tab} audio…")
    audio = _tts_to_bytes(text, voice)
    storage.write_bytes(f"briefing_{tab}.mp3", audio, "audio/mpeg")
    print(f"  briefing_{tab}.mp3: {len(audio) // 1024} KB")


def generate_main(top_n: int = 30):
    """Briefing of the freshest items in main.json."""
    data = storage.read_json("main.json")
    if not data:
        print("  no main.json — skipping main briefing")
        return
    arts = data.get("articles", [])[:top_n]
    if not arts:
        print("  empty main — skipping briefing")
        return

    markets = storage.read_json("markets_main.json") or {}

    item_lines = [
        f"- [{a.get('site_name','?')}] {a.get('title','')[:160]}"
        + (f" — {a.get('summary','')[:240]}" if a.get('summary') else "")
        for a in arts
    ]
    market_lines = [f"- {m['title']}: {m.get('current', '?')}%" for m in markets.values()]

    prompt = f"""Genera un briefing de audio en español para un lector que sigue economía, política internacional, IA y tecnología. Será leído por un TTS, así que escribe como se habla: frases claras, ritmo natural, sin bullet points ni formato.

MERCADOS DE PREDICCIÓN (Polymarket):
{chr(10).join(market_lines) if market_lines else "Sin mercados."}

ARTÍCULOS RECIENTES DE LOS FEEDS DEL LECTOR ({len(arts)}):
{chr(10).join(item_lines)}

INSTRUCCIONES:
- Tono: como un periodista que lee un boletín. Factual, directo, sin opinión propia.
- Estructura: empieza con los mercados de predicción (cifras), luego un recorrido temático por los artículos: agrupa por tema (geopolítica, tecnología, economía, política nacional, otros) en lugar de leer fuente por fuente.
- Para cada tema: 2-4 piezas con qué dice cada autor o fuente, y por qué importa.
- NO inventes datos que no estén en los títulos/resúmenes. Si no hay sustancia, salta el ítem.
- NO uses encabezados, asteriscos, guiones ni ningún formato. Solo texto corrido en párrafos.
- Longitud: ~700-1100 palabras (3-4 minutos de audio).
- Idioma: español."""

    print("Generating Main briefing…")
    text = _claude_text(prompt, max_tokens=2500)
    _save_and_speak("main", text)


def generate_thinktanks():
    """Briefing of the freshest items in thinktanks.json, by subsection."""
    data = storage.read_json("thinktanks.json")
    if not data:
        print("  no thinktanks.json — skipping briefing")
        return
    arts = data.get("articles", [])
    if not arts:
        print("  empty thinktanks — skipping briefing")
        return

    by_sub: dict[str, list[dict]] = {}
    for a in arts:
        by_sub.setdefault(a.get("subtag", "other"), []).append(a)

    sections = []
    for sub, label in [("classic", "Classic"), ("spain", "España"), ("abundance", "Abundance")]:
        items = by_sub.get(sub, [])
        if not items:
            continue
        lines = [f"- [{a.get('source','?')}] {a.get('title','')[:160]}"
                 + (f" — {a.get('summary','')[:200]}" if a.get('summary') else "")
                 for a in items[:25]]
        sections.append(f"{label} ({len(items)} items):\n" + "\n".join(lines))

    if not sections:
        print("  no items in any subsection")
        return

    prompt = f"""Genera un briefing de audio en español sobre publicaciones recientes de think tanks. Será leído por un TTS, así que escribe como se habla.

PUBLICACIONES POR SECCIÓN:

{chr(10).join(sections)}

INSTRUCCIONES:
- Tono: analista de policy que digiere publicaciones. Factual, claro, sin opinión propia.
- Estructura: tres bloques en este orden: España, Classic, Abundance. Salta una sección si está vacía.
- Para cada bloque: introduce el ámbito en una frase y luego repasa 3-6 publicaciones, indicando think tank, tema, y por qué es relevante.
- NO inventes datos que no estén en los títulos/resúmenes. Si no hay sustancia, salta el ítem.
- NO uses encabezados, asteriscos, guiones ni ningún formato. Solo texto corrido en párrafos.
- Longitud: ~600-900 palabras (2-3 minutos).
- Idioma: español."""

    print("Generating Thinktanks briefing…")
    text = _claude_text(prompt, max_tokens=2200)
    _save_and_speak("thinktanks", text)


def generate_papers():
    """Briefing of the freshest items in papers.json, by source."""
    data = storage.read_json("papers.json")
    if not data:
        print("  no papers.json — skipping briefing")
        return
    arts = data.get("articles", [])
    if not arts:
        print("  empty papers — skipping briefing")
        return

    by_src: dict[str, list[dict]] = {}
    for a in arts:
        by_src.setdefault(a.get("source", "?"), []).append(a)

    sections = []
    for src, items in by_src.items():
        lines = [
            f"- {a.get('title','')[:160]}"
            + (f" ({a['author']})" if a.get('author') else "")
            + (f" — {a.get('summary','')[:200]}" if a.get('summary') else "")
            for a in items[:15]
        ]
        sections.append(f"{src} ({len(items)} papers):\n" + "\n".join(lines))

    prompt = f"""Genera un briefing de audio en español sobre papers académicos publicados recientemente. Será leído por un TTS, así que escribe como se habla.

PAPERS POR FUENTE:

{chr(10).join(sections)}

INSTRUCCIONES:
- Tono: investigador que digiere working papers para un colega no especialista. Factual, claro, sin opinión propia.
- Estructura: recorre fuente por fuente (NBER, IZA, Banco de España, VoxEU, etc.). Para cada bloque: 2-5 papers. Para cada paper: el qué (pregunta de investigación), el cómo (método/datos en una frase si está claro), y por qué importa.
- NO inventes resultados que no estén en el título/resumen. Si no hay sustancia, salta el paper.
- NO uses encabezados, asteriscos, guiones ni ningún formato. Solo texto corrido en párrafos.
- Longitud: ~600-1000 palabras (3 minutos).
- Idioma: español."""

    print("Generating Papers briefing…")
    text = _claude_text(prompt, max_tokens=2500)
    _save_and_speak("papers", text)


if __name__ == "__main__":
    generate_main()
    generate_thinktanks()
    generate_papers()
