"""Claude-powered content curation: profile building + article ranking."""

import json
import pathlib
from datetime import datetime, timedelta, timezone

import anthropic
from dotenv import load_dotenv

from substack import load_articles
from rss import fetch_by_tag

load_dotenv()

DATA_DIR = pathlib.Path(__file__).parent / "data"
PROFILE_FILE = DATA_DIR / "profile.json"
MAIN_FILE = DATA_DIR / "main.json"

client = anthropic.Anthropic(timeout=180.0, max_retries=3)

# Fixed tag corpus — all curation must use these
TAGS = [
    "vivienda", "urbanismo", "abundancia", "energía",
    "IA", "tecnología", "productividad",
    "economía", "mercado laboral", "desigualdad",
    "política europea", "geopolítica", "comercio",
    "demografía", "migración",
    "políticas públicas", "regulación",
    "datos", "metodología",
    "cultura", "medios",
]

# Sources to always exclude (matched case-insensitively against author and site_name)
BLOCKED_SOURCES = ["cleo abram", "ft shorts"]

# Articles below this score get dropped — removes noise, spam, off-topic
MIN_SCORE = 20



def build_profile(force_refresh: bool = False) -> dict:
    """Analyze Substack articles to build a reader/writer profile."""
    if PROFILE_FILE.exists() and not force_refresh:
        return json.loads(PROFILE_FILE.read_text())

    articles = load_articles()

    # Build a condensed corpus: title + subtitle + first 500 chars of body
    corpus_lines = []
    for a in articles:
        snippet = a["body_text"][:500]
        corpus_lines.append(f"## {a['title']}\n{a.get('subtitle', '')}\n{snippet}\n")

    corpus = "\n---\n".join(corpus_lines)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""Analiza estos {len(articles)} artículos de un autor de Substack y genera un perfil detallado en JSON.

Los artículos (título + subtítulo + extracto):

{corpus}

Genera un JSON con esta estructura exacta:
{{
  "core_topics": ["lista de 5-8 temas principales"],
  "perspectives": ["3-5 perspectivas/enfoques analíticos del autor"],
  "intellectual_style": "descripción breve del estilo intelectual",
  "recent_focus": ["3-4 temas recientes (últimos meses)"],
  "what_excites": "qué tipo de contenido entusiasmaría a este autor",
  "what_bores": "qué tipo de contenido NO le interesaría",
  "summary_es": "resumen de 2-3 frases del perfil en español"
}}

Responde SOLO con el JSON, sin markdown ni explicaciones."""
        }],
    )

    profile_text = response.content[0].text.strip()
    if profile_text.startswith("```"):
        profile_text = profile_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    profile = json.loads(profile_text)
    profile["article_count"] = len(articles)
    profile["total_words"] = sum(a["wordcount"] for a in articles)

    DATA_DIR.mkdir(exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2))
    print("Profile built and cached.")
    return profile


SCORES_CACHE_FILE = DATA_DIR / "scores_cache.json"


def _load_scores_cache() -> dict:
    """Load previous scores keyed by source_url."""
    if SCORES_CACHE_FILE.exists():
        return json.loads(SCORES_CACHE_FILE.read_text())
    return {}


def _save_scores_cache(cache: dict):
    DATA_DIR.mkdir(exist_ok=True)
    SCORES_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))



def _score_batch(profile: dict, articles: list[dict], batch_indices: list[int], prev_scores: dict) -> list[dict]:
    """Rank a batch of articles using rubric scoring + comparative ranking."""
    # Build article list with previous scores where available
    article_list = []
    for idx in batch_indices:
        a = articles[idx]
        line = (
            f"[{idx}] \"{a['title']}\" — {a['site_name'] or 'Unknown'}\n"
            f"    Summary: {(a.get('summary') or 'No summary')[:200]}\n"
            f"    Words: {a.get('word_count', '?')} | Author: {a.get('author', '?')}"
        )
        url = a.get("source_url", "")
        if url in prev_scores:
            line += f"\n    Score anterior: {prev_scores[url]}"
        article_list.append(line)
    articles_text = "\n\n".join(article_list)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": f"""Eres un curador de contenido personal. Tu tarea es ORDENAR y PUNTUAR todos los artículos para un lector con perspectiva YIMBY y de abundancia.

PERFIL: {json.dumps(profile, ensure_ascii=False)}

RÚBRICA DE PUNTUACIÓN (suma de 4 dimensiones):
- Relevancia directa a core topics del perfil (0-30): ¿trata sus temas?
- Sustantividad del análisis (0-25): ¿es análisis riguroso con datos/evidencia o es superficial/opinión?
- Alineación YIMBY/abundance (0-25): ¿conecta con crecimiento, construcción, desregulación, productividad?
- Novedad/sorpresa (0-20): ¿le haría pensar algo nuevo o ya lo sabe?

PROCESO:
1. Primero ORDENA mentalmente los artículos del más al menos interesante
2. Luego asigna puntuaciones según la rúbrica, respetando el orden
3. Si un artículo tiene "Score anterior", no lo cambies más de 10 puntos salvo que haya una razón clara

ARTÍCULOS ({len(batch_indices)}):
{articles_text}

Para CADA artículo (TODOS):
- index: el [N] original
- score: 0-100 (suma de la rúbrica)
- reason_es: CONCEPTO corto (3-8 palabras), gancho conceptual. Ej: "Crecimiento como motor de igualdad de género", "Coste real de la escasez artificial"
- tag: DEBE ser una de estas exactamente: {", ".join(TAGS)}

Responde SOLO JSON array con TODOS los artículos ordenados de mayor a menor score, sin markdown:
[{{"index": 0, "score": 95, "reason_es": "...", "tag": "..."}}, ...]"""
        }],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def curate(days: int = 2, top_n: int = 0) -> dict:
    """Fetch new RSS items (tag=main), score them, write data/main.json.

    State is delta-only: rss.py keeps track of last-seen-id per feed, so each run
    only sees items not seen before. main.json is the union of (new this run) +
    (previously curated, still recent). Read state in the UI is tracked per-URL
    in localStorage.
    """
    profile = build_profile()
    articles = fetch_by_tag("main")
    print(f"Fetched {len(articles)} new RSS items (main).")

    if not articles:
        print("No new RSS items.")
        if MAIN_FILE.exists():
            return json.loads(MAIN_FILE.read_text())
        return {"articles": [], "generated_at": ""}

    # Filter blocked sources
    before = len(articles)
    articles = [
        a for a in articles
        if not any(
            blocked in (a.get("author") or "").lower()
            or blocked in (a.get("site_name") or "").lower()
            or blocked in (a.get("title") or "").lower()
            for blocked in BLOCKED_SOURCES
        )
    ]
    if len(articles) < before:
        print(f"  Filtered {before - len(articles)} blocked sources.")

    # Load previous scores for stability
    prev_scores = _load_scores_cache()

    # Process in batches of 100
    batch_size = 100
    all_indices = list(range(len(articles)))
    candidates = []

    for i in range(0, len(all_indices), batch_size):
        batch = all_indices[i:i + batch_size]
        print(f"  Scoring batch {i//batch_size + 1} ({len(batch)} articles)...")
        try:
            picks = _score_batch(profile, articles, batch, prev_scores)
            candidates.extend(picks)
        except Exception as e:
            print(f"  Batch failed: {e}")

    if not candidates:
        print("No candidates scored.")
        return {"articles": [], "generated_at": ""}

    # Deduplicate by index if multiple batches
    if len(all_indices) > batch_size:
        seen = set()
        unique = []
        for c in candidates:
            if c["index"] not in seen:
                seen.add(c["index"])
                unique.append(c)
        candidates = unique

    candidates.sort(key=lambda x: x["score"], reverse=True)
    scores = candidates if top_n == 0 else candidates[:top_n]

    # Update scores cache for next run
    new_cache = {}
    for s in candidates:
        idx = s["index"]
        if 0 <= idx < len(articles):
            url = articles[idx].get("source_url", "")
            if url:
                new_cache[url] = s["score"]
    _save_scores_cache(new_cache)

    # Merge scores with article data
    curated_articles = []
    for s in scores:
        idx = s["index"]
        if 0 <= idx < len(articles):
            article = articles[idx].copy()
            article["score"] = s.get("score", 0)
            article["reason"] = s.get("reason_es", s.get("reason", ""))
            article["tag"] = s.get("tag", "")
            curated_articles.append(article)

    # Carry over previously-curated items still considered fresh (the user hasn't
    # marked them read in localStorage, but the server doesn't know that).
    # We use a 14-day window from when the item was first scored to bound growth.
    if MAIN_FILE.exists():
        try:
            prev = json.loads(MAIN_FILE.read_text())
            new_urls = {a.get("source_url", "") for a in curated_articles}
            new_titles = {(a.get("title") or "").strip().lower() for a in curated_articles}
            cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
            carried = 0
            for old in prev.get("articles", []):
                added = old.get("_added_at") or old.get("published_date") or ""
                if added and added < cutoff:
                    continue
                u = old.get("source_url", "")
                t = (old.get("title") or "").strip().lower()
                if u in new_urls or t in new_titles:
                    continue
                curated_articles.append(old)
                carried += 1
            if carried:
                print(f"  Carried over {carried} previously-curated items.")
        except Exception as e:
            print(f"  Carry-over skipped: {e}")

    # Stamp _added_at on items that don't have one (first time we see them)
    now_iso = datetime.now(timezone.utc).isoformat()
    for a in curated_articles:
        if not a.get("_added_at"):
            a["_added_at"] = now_iso

    # Deduplicate by source_url and normalized title
    seen_urls = set()
    seen_titles = set()
    deduped = []
    for a in curated_articles:
        url = a.get("source_url", "")
        title_norm = (a.get("title") or "").strip().lower()
        if url and url in seen_urls:
            continue
        if title_norm and title_norm in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title_norm:
            seen_titles.add(title_norm)
        deduped.append(a)
    if len(deduped) < len(curated_articles):
        print(f"  Removed {len(curated_articles) - len(deduped)} duplicates.")
    curated_articles = deduped

    # Drop low-score articles (spam, off-topic)
    before_score = len(curated_articles)
    curated_articles = [a for a in curated_articles if a.get("score", 0) >= MIN_SCORE]
    if len(curated_articles) < before_score:
        print(f"  Dropped {before_score - len(curated_articles)} articles below score {MIN_SCORE}.")

    # Re-sort everything by score
    curated_articles.sort(key=lambda a: a.get("score", 0), reverse=True)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "article_count_total": len(articles),
        "articles": curated_articles,
    }

    DATA_DIR.mkdir(exist_ok=True)
    MAIN_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Wrote {len(curated_articles)} articles to main.json (from {len(articles)} new candidates).")
    return result



if __name__ == "__main__":
    print("Building profile...")
    p = build_profile(force_refresh=True)
    print(json.dumps(p, ensure_ascii=False, indent=2))
    print("\nCurating...")
    c = curate()
    for a in c["articles"][:5]:
        print(f"  [{a['score']}] {a['title']} — {a['reason']}")
