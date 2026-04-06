"""Claude-powered content curation: profile building + article ranking."""

import json
import os
import pathlib
import re

import anthropic
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from substack import load_articles
from reader import load_feed, load_recent

load_dotenv()

DATA_DIR = pathlib.Path(__file__).parent / "data"
PROFILE_FILE = DATA_DIR / "profile.json"
CURATED_FILE = DATA_DIR / "curated.json"
FEEDBACK_FILE = DATA_DIR / "feedback.json"

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


def _load_feedback_context() -> str:
    """Load user feedback and format it as context for curation prompts."""
    if not FEEDBACK_FILE.exists():
        return ""
    feedback = json.loads(FEEDBACK_FILE.read_text())
    if not feedback:
        return ""

    liked = [f for f in feedback if f.get("liked")]
    disliked = [f for f in feedback if not f.get("liked")]

    lines = ["FEEDBACK PREVIO DEL USUARIO (usa esto para afinar tus recomendaciones):"]
    if liked:
        lines.append("Le gustaron:")
        for f in liked[-15:]:  # last 15
            lines.append(f"  + \"{f['title']}\" [{f.get('tag', '')}]")
    if disliked:
        lines.append("NO le gustaron:")
        for f in disliked[-15:]:
            lines.append(f"  - \"{f['title']}\" [{f.get('tag', '')}]")

    return "\n".join(lines)


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


def _build_feedback_examples() -> str:
    """Build concrete liked/disliked examples for calibration."""
    if not FEEDBACK_FILE.exists():
        return ""
    feedback = json.loads(FEEDBACK_FILE.read_text())
    if not feedback:
        return ""

    liked = [f for f in feedback if f.get("liked") and f.get("section") == "feeds"]
    disliked = [f for f in feedback if not f.get("liked") and f.get("section") == "feeds"]

    if not liked and not disliked:
        return ""

    lines = ["EJEMPLOS DE CALIBRACIÓN (basados en feedback real del usuario):"]
    if liked:
        lines.append("Artículos que al usuario LE GUSTARON (deberían puntuar alto):")
        for f in liked[-8:]:
            lines.append(f"  BUENO: \"{f['title']}\" [{f.get('tag', '')}]")
    if disliked:
        lines.append("Artículos que al usuario NO le gustaron (deberían puntuar bajo):")
        for f in disliked[-8:]:
            lines.append(f"  MALO: \"{f['title']}\" [{f.get('tag', '')}]")

    return "\n".join(lines)


def _score_batch(profile: dict, articles: list[dict], batch_indices: list[int], prev_scores: dict) -> list[dict]:
    """Rank a batch of articles using rubric scoring + comparative ranking + feedback calibration."""
    feedback_ctx = _load_feedback_context()
    feedback_examples = _build_feedback_examples()

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

{feedback_ctx}

{feedback_examples}

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
    """Score and rank Reader feed articles against the author profile."""
    profile = build_profile()
    articles = load_recent(days=days, force_refresh=True)

    if not articles:
        print("No articles found in feed.")
        return {"articles": [], "generated_at": ""}

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
            article["score"] = s["score"]
            article["reason"] = s["reason_es"]
            article["tag"] = s["tag"]
            curated_articles.append(article)

    # Separate thinktank twitter lists from regular articles
    thinktank_ids = []
    regular_articles = []
    for a in curated_articles:
        if "thinktank" in (a.get("title") or "").lower() and "twitter" in (a.get("title") or "").lower():
            thinktank_ids.append(a.get("id", ""))
        else:
            regular_articles.append(a)
    curated_articles = regular_articles

    # Find outside-bubble (from thinktank lists) and abundance recommendations
    reader_urls = {a.get("source_url", "") for a in articles}
    thinktank = find_outside_bubble(profile, reader_urls, thinktank_ids)
    abundance = find_abundance(reader_urls)

    # Merge with pending articles from previous run (not yet marked Sí/No)
    feedback_urls = set()
    if FEEDBACK_FILE.exists():
        for f in json.loads(FEEDBACK_FILE.read_text()):
            if f.get("source_url"):
                feedback_urls.add(f["source_url"])

    new_urls = {a.get("source_url", "") for a in curated_articles}

    if CURATED_FILE.exists():
        prev = json.loads(CURATED_FILE.read_text())
        for old_article in prev.get("articles", []):
            old_url = old_article.get("source_url", "")
            # Keep if: not already in new batch AND not yet marked with feedback
            if old_url and old_url not in new_urls and old_url not in feedback_urls:
                curated_articles.append(old_article)

    # Re-sort everything by score
    curated_articles.sort(key=lambda a: a.get("score", 0), reverse=True)

    from datetime import datetime, timezone
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "article_count_total": len(articles),
        "thinktank": thinktank,
        "abundance": abundance,
        "articles": curated_articles,
    }

    CURATED_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Curated {len(curated_articles)} articles from {len(articles)} candidates.")
    return result


def _search_ddg(query: str, max_results: int = 8) -> list[dict]:
    """Search DuckDuckGo HTML and return results."""
    resp = httpx.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
        follow_redirects=True,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for r in soup.select(".result")[:max_results]:
        title_el = r.select_one(".result__title a")
        snippet_el = r.select_one(".result__snippet")
        if not title_el:
            continue
        href = title_el.get("href", "")
        # DDG wraps URLs in a redirect — extract the actual URL
        if "uddg=" in href:
            from urllib.parse import unquote, urlparse, parse_qs
            parsed = parse_qs(urlparse(href).query)
            href = unquote(parsed.get("uddg", [href])[0])
        results.append({
            "title": title_el.get_text(strip=True),
            "url": href,
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
        })
    return results


def find_outside_bubble(profile: dict, reader_urls: set[str], thinktank_ids: list[str]) -> list[dict]:
    """Extract interesting links from thinktank twitter list digests."""
    from reader import fetch_html_content

    if not thinktank_ids:
        print("No thinktank twitter lists found, skipping bubble.")
        return []

    # Fetch HTML from the most recent thinktank lists and extract tweet content
    all_tweet_text = []
    for doc_id in thinktank_ids[:3]:  # Last 3 digests
        try:
            html = fetch_html_content(doc_id)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                # Extract tweet text and any links
                for tweet in soup.select(".rw-embedded-tweet"):
                    text = tweet.get_text(separator=" ", strip=True)
                    links = [a["href"] for a in tweet.select("a[href]")
                             if a["href"].startswith("http") and "twitter.com" not in a["href"] and "t.co" not in a["href"]]
                    if text:
                        all_tweet_text.append({"text": text[:300], "links": links})
        except Exception as e:
            print(f"  Failed to fetch thinktank list {doc_id}: {e}")

    if not all_tweet_text:
        print("No tweet content extracted from thinktank lists.")
        return []

    # Have Claude pick the 2 most interesting shared items
    tweets_summary = "\n\n".join(
        f"[{i}] {t['text']}" + (f"\n  Links: {', '.join(t['links'][:3])}" if t['links'] else "")
        for i, t in enumerate(all_tweet_text[:40])
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": f"""Estos son tweets recientes de think tanks y analistas de políticas públicas. Selecciona los 4 más interesantes para un lector con perspectiva YIMBY/abundance que ya lee sobre economía, vivienda, IA y política europea.

Prioriza: debates intelectuales sustantivos, datos nuevos, perspectivas inesperadas. NUNCA recomiendes contenido anti-crecimiento o pro-degrowth. Los 4 deben ser de temas DIFERENTES entre sí.

{tweets_summary}

Para cada seleccionado, genera:
- El título del contenido compartido (extraído o inferido del tweet)
- La URL si hay link, o "" si no
- La fuente (quién tuiteó)
- reason_es: concepto corto 3-8 palabras
- tag: DEBE ser una de estas: {", ".join(TAGS)}

Responde SOLO JSON array, sin markdown:
[{{"title": "...", "url": "...", "source": "...", "reason_es": "...", "tag": "..."}}, ...]"""
        }],
    )

    picks_text = response.content[0].text.strip()
    if picks_text.startswith("```"):
        picks_text = picks_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    picks = json.loads(picks_text)

    bubble_articles = []
    for p in picks[:4]:
        url = p.get("url", "")
        bubble_articles.append({
            "title": p.get("title", ""),
            "source_url": url,
            "site_name": p.get("source", "Twitter"),
            "reason": p.get("reason_es", ""),
            "tag": p.get("tag", ""),
        })

    print(f"Found {len(bubble_articles)} thinktank articles.")
    return bubble_articles


def find_abundance(reader_urls: set[str]) -> list[dict]:
    """Search for 3 articles from the YIMBY/abundance world, always including Works in Progress."""
    from urllib.parse import urlparse

    # Dedicated WiP query + diverse abundance queries
    wip_query = "site:worksinprogress.co"
    general_queries = [
        "abundance agenda supply side progressivism analysis",
        "YIMBY housing reform Europe Spain UK results",
        "Institute for Progress Niskanen Center abundance infrastructure energy",
    ]

    reader_domains = {re.sub(r'^www\.', '', urlparse(u).netloc) for u in reader_urls if u}

    def _collect(queries):
        results = []
        for q in queries:
            try:
                hits = _search_ddg(q)
                for h in hits:
                    domain = re.sub(r'^www\.', '', urlparse(h["url"]).netloc)
                    if domain not in reader_domains and h["url"] not in reader_urls:
                        h["query"] = q
                        results.append(h)
            except Exception as e:
                print(f"Abundance search failed for '{q}': {e}")
        return results

    # Get WiP results separately to guarantee one
    wip_results = _collect([wip_query])
    general_results = _collect(general_queries)

    if not wip_results and not general_results:
        print("No abundance results found.")
        return []

    # Pick 1 from WiP
    wip_article = None
    if wip_results:
        wip_results_text = "\n".join(
            f'[{i}] "{r["title"]}" — {r["url"]}\n    {r["snippet"]}'
            for i, r in enumerate(wip_results)
        )
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""Elige el mejor artículo de Works in Progress:

{wip_results_text}

Responde SOLO con JSON, sin markdown:
{{"index": 0, "reason_es": "concepto corto 3-8 palabras", "tag": "una de: {", ".join(TAGS)}"}}"""
            }],
        )
        pick_text = response.content[0].text.strip()
        if pick_text.startswith("```"):
            pick_text = pick_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        pick = json.loads(pick_text)
        idx = pick["index"]
        if 0 <= idx < len(wip_results):
            r = wip_results[idx]
            wip_article = {
                "title": r["title"],
                "source_url": r["url"],
                "site_name": "Works in Progress",
                "reason": pick["reason_es"],
                "tag": pick["tag"],
                "snippet": r["snippet"],
            }

    # Pick 2 from general
    general_articles = []
    if general_results:
        results_text = "\n".join(
            f'[{i}] "{r["title"]}" — {r["url"]}\n    {r["snippet"]}'
            for i, r in enumerate(general_results)
        )
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""De estos resultados, elige los 2 mejores artículos del mundo YIMBY/abundance agenda.

Criterios estrictos:
- Análisis sustantivos PRO-CRECIMIENTO, pro-construcción, pro-abundancia
- NUNCA recomiendes contenido degrowth, anti-crecimiento, o anti-desarrollo
- Los 2 deben ser de temas DIFERENTES (no repitas país ni temática)
- Prioriza: think tanks (Niskanen, IFP, Works in Progress), casos europeos, reformas concretas
- Evita repetir siempre los mismos países (varía entre EEUU, UK, Europa, Asia, LatAm)

{_load_feedback_context()}

{results_text}

Tag DEBE ser una de: {", ".join(TAGS)}

Responde SOLO con un JSON array, sin markdown:
[
  {{"index": 0, "reason_es": "concepto corto 3-8 palabras", "tag": "..."}},
  {{"index": 1, "reason_es": "concepto corto 3-8 palabras", "tag": "..."}}
]"""
            }],
        )
        picks_text = response.content[0].text.strip()
        if picks_text.startswith("```"):
            picks_text = picks_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        picks = json.loads(picks_text)
        for p in picks[:2]:
            idx = p["index"]
            if 0 <= idx < len(general_results):
                r = general_results[idx]
                general_articles.append({
                    "title": r["title"],
                    "source_url": r["url"],
                    "site_name": re.sub(r'^www\.', '', urlparse(r["url"]).netloc),
                    "reason": p["reason_es"],
                    "tag": p["tag"],
                    "snippet": r["snippet"],
                })

    abundance_articles = []
    if wip_article:
        abundance_articles.append(wip_article)
    abundance_articles.extend(general_articles)

    print(f"Found {len(abundance_articles)} abundance articles.")
    return abundance_articles


if __name__ == "__main__":
    print("Building profile...")
    p = build_profile(force_refresh=True)
    print(json.dumps(p, ensure_ascii=False, indent=2))
    print("\nCurating...")
    c = curate()
    for a in c["articles"][:5]:
        print(f"  [{a['score']}] {a['title']} — {a['reason']}")
