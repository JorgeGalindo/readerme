"""Generate the Thinktanks audio briefing (text via Claude Sonnet 4.6,
speech via OpenAI gpt-4o-mini-tts).

Spain has its own briefing inside spain.py (bundled with curation).
Main and Papers no longer have audio briefings.
"""

import os
import re

import anthropic
from dotenv import load_dotenv
from openai import OpenAI

import storage

load_dotenv()

MODEL = "claude-sonnet-4-6"  # falls back to older sonnet if not provisioned

TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "nova")
TTS_INSTRUCTIONS = (
    "Habla en español de España con tono de periodista de boletín informativo: "
    "ritmo natural, frases claras, factual, sin opinión, sin entusiasmo forzado. "
    "Pronuncia con naturalidad las siglas en inglés (AI, ECB, NATO, NBER) y los "
    "nombres propios extranjeros."
)
TTS_MAX_CHARS = 3500  # OpenAI TTS hard limit is 4096 — leave a margin.

client = anthropic.Anthropic(timeout=240.0, max_retries=3)

_openai_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def _claude_text(prompt: str, max_tokens: int = 2000) -> str:
    """Call Claude Sonnet 4.6 for briefing text generation."""
    try:
        resp = client.messages.create(model=MODEL, max_tokens=max_tokens,
                                      messages=[{"role": "user", "content": prompt}])
    except (anthropic.NotFoundError, anthropic.BadRequestError):
        resp = client.messages.create(model="claude-sonnet-4-20250514",
                                      max_tokens=max_tokens,
                                      messages=[{"role": "user", "content": prompt}])
        print("  (fell back to claude-sonnet-4-20250514)")
    return resp.content[0].text.strip()


def _split_for_tts(text: str, max_chars: int = TTS_MAX_CHARS) -> list[str]:
    """Split text into chunks <= max_chars, preferring sentence boundaries."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    sents = re.split(r'(?<=[.!?…])\s+', text)
    chunks: list[str] = []
    cur = ""
    for s in sents:
        if not s:
            continue
        if len(cur) + len(s) + 1 > max_chars and cur:
            chunks.append(cur.strip())
            cur = s
        else:
            cur = (cur + " " + s) if cur else s
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _tts_to_bytes(text: str) -> bytes:
    """Synthesize speech with OpenAI TTS, return concatenated mp3 bytes.
    MP3 frames are independent so naive byte concatenation plays back fine."""
    out = bytearray()
    for chunk in _split_for_tts(text):
        resp = _openai().audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=chunk,
            instructions=TTS_INSTRUCTIONS,
            response_format="mp3",
        )
        out.extend(resp.content)
    return bytes(out)


def _save_and_speak(tab: str, text: str):
    storage.write_bytes(f"briefing_{tab}.txt", text.encode("utf-8"),
                        "text/plain; charset=utf-8")
    print(f"  generating {tab} audio…")
    audio = _tts_to_bytes(text)
    storage.write_bytes(f"briefing_{tab}.mp3", audio, "audio/mpeg")
    print(f"  briefing_{tab}.mp3: {len(audio) // 1024} KB")


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


if __name__ == "__main__":
    generate_thinktanks()
