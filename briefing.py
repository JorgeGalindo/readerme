"""Speech synthesis utility (OpenAI gpt-4o-mini-tts).

Used by spain.py to turn the daily Spain briefing text into mp3.
"""

import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "nova")
TTS_INSTRUCTIONS = (
    "Habla en español de España con tono de periodista de boletín informativo: "
    "ritmo natural, frases claras, factual, sin opinión, sin entusiasmo forzado. "
    "Pronuncia con naturalidad las siglas en inglés (AI, ECB, NATO, NBER) y los "
    "nombres propios extranjeros."
)
TTS_MAX_CHARS = 3500  # OpenAI TTS hard limit is 4096 — leave a margin.

_openai_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


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
