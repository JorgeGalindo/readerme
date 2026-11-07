"""España tab: foreign press about Spain and a political-risk radar.

The nightly on Vercel only fetches feeds; it never calls a model. It writes
spain.json with the candidate articles and, as the radar, the latest political
headlines from each paper in turn. Each morning `spain_ai.py` runs on the Mac
mini with `claude -p` (Jorge's subscription, not the API), picks the ten that
matter for political risk, writes a short text briefing and overwrites the
radar. If the mini doesn't run, the page still updates, without the selection.
"""

from datetime import datetime, timezone
import time
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup

import storage

RADAR_SIZE = 10

# International feeds — direct Spain tags, no AI needed
FEEDS_INTL = {
    "The Economist": "https://www.economist.com/europe/rss.xml",
    "Financial Times": "https://www.ft.com/spain?format=rss",
    "Politico Europe": "https://www.politico.eu/feed/",
    "The Guardian Europe": "https://www.theguardian.com/world/europe-news/rss",
}

FEEDS_ES = {
    "El País (España)": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/espana/portada",
    "El País (Economía)": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada",
    "El Confidencial": "https://rss.elconfidencial.com/espana/",
    "El Mundo": "https://e00-elmundo.uecdn.es/elmundo/rss/espana.xml",
    "eldiario.es": "https://www.eldiario.es/rss/politica/",
}

NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
}


def _fetch_feed(url: str) -> str:
    """Fetch raw XML from a feed URL."""
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  Failed to fetch {url}: {e}")
        return ""


def _parse_rss(xml_text: str, source_name: str) -> list[dict]:
    """Parse RSS 2.0 feed."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            author = (item.findtext("dc:creator", namespaces=NS) or
                      item.findtext("author") or "").strip()
            desc = item.findtext("description") or ""
            # Strip HTML from description
            summary = BeautifulSoup(desc, "html.parser").get_text(strip=True)[:300]
            pub_date = (item.findtext("pubDate") or "").strip()

            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "author": author,
                    "summary": summary,
                    "date": pub_date,
                    "source": source_name,
                })
    except ET.ParseError as e:
        print(f"  XML parse error for {source_name}: {e}")
    return items


def _parse_atom(xml_text: str, source_name: str) -> list[dict]:
    """Parse Atom feed (El Confidencial)."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            title = (entry.findtext("a:title", namespaces=ns) or "").strip()
            link_el = entry.find("a:link[@rel='alternate']", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            author = (entry.findtext("a:author/a:name", namespaces=ns) or "").strip()
            summary_el = entry.findtext("a:summary", namespaces=ns) or ""
            summary = BeautifulSoup(summary_el, "html.parser").get_text(strip=True)[:300]
            pub_date = (entry.findtext("a:published", namespaces=ns) or "").strip()

            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "author": author,
                    "summary": summary,
                    "date": pub_date,
                    "source": source_name,
                })
    except ET.ParseError as e:
        print(f"  Atom parse error for {source_name}: {e}")
    return items


def _load_seen_intl() -> set:
    data = storage.read_json("seen_intl.json")
    return set(data) if data else set()


def _save_seen_intl(seen: set):
    storage.write_json("seen_intl.json", list(seen))


def fetch_intl_spain() -> list[dict]:
    """Fetch Economist and FT articles about Spain. No AI — just fetch, filter new, show."""
    seen = _load_seen_intl()
    spain_articles = []

    for source, url in FEEDS_INTL.items():
        print(f"  Fetching {source}...")
        xml = _fetch_feed(url)
        if not xml:
            continue
        items = _parse_rss(xml, source)

        for item in items:
            if item["link"] in seen:
                continue
            # Hard filter: 2026+ only
            date_str = (item.get("date") or "").lower()
            if "2025" in date_str or "2024" in date_str or "2023" in date_str:
                continue

            if source == "Financial Times":
                # FT has a Spain-specific feed, no keyword filter needed
                ft_count = sum(1 for a in spain_articles if a["source"] == "Financial Times")
                if ft_count >= 3:
                    continue
                spain_articles.append(item)
                seen.add(item["link"])
            else:
                # General Europe feeds — filter for Spain mentions
                text = f"{item['title']} {item['summary']}".lower()
                if any(kw in text for kw in ("spain", "spanish", "españa", "madrid", "barcelona", "sánchez", "sanchez", "rajoy", "vox ", "podemos", "catalon")):
                    spain_articles.append(item)
                    seen.add(item["link"])
        time.sleep(0.5)

    _save_seen_intl(seen)
    return spain_articles


def fetch_spanish_media() -> list[dict]:
    """Fetch articles from Spanish national media."""
    all_articles = []
    for source, url in FEEDS_ES.items():
        print(f"  Fetching {source}...")
        xml = _fetch_feed(url)
        if not xml:
            continue

        if "elconfidencial" in url:
            items = _parse_atom(xml, source)
        else:
            items = _parse_rss(xml, source)

        all_articles.extend(items[:20])  # Max 20 per source
        time.sleep(0.5)

    return all_articles


def rss_radar(candidates: list[dict], size: int = RADAR_SIZE) -> list[dict]:
    """Fallback radar without a model: newest item from each paper in turn."""
    by_source: dict[str, list[dict]] = {}
    for item in candidates:
        by_source.setdefault(item["source"], []).append(item)
    radar, seen_titles = [], set()
    while len(radar) < size and any(by_source.values()):
        for items in by_source.values():
            if not items or len(radar) >= size:
                continue
            item = items.pop(0)
            key = item["title"].strip().lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            radar.append({**item, "risk_summary": item.get("summary", "")})
    return radar


def curate_spain() -> dict:
    """Fetch every source and store the day's candidates. No model involved."""
    print("Fetching international sources...")
    intl = fetch_intl_spain()
    print(f"  {len(intl)} international articles about Spain")

    print("Fetching Spanish media...")
    candidates = fetch_spanish_media()
    print(f"  {len(candidates)} Spanish media articles")

    curated_intl = []
    for a in intl:
        date_str = (a.get("date") or "").lower()
        if "2025" in date_str or "2024" in date_str or "2023" in date_str:
            continue
        a["risk_summary"] = a["summary"]
        curated_intl.append(a)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "intl": curated_intl,
        "candidates": candidates,
        "spanish": rss_radar(candidates),
        "radar_source": "rss",
    }
    storage.write_json("spain.json", result)
    print(f"Spain stored: {len(curated_intl)} intl + {len(candidates)} candidates")
    return result


if __name__ == "__main__":
    curate_spain()
