"""The lead headline on each newspaper's public home page, fetched on demand.

Selectors refer to the opening story, not tickers, related links or RSS order.
Checked against the public home pages on 2026-09-12. No model or paid API.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx


@dataclass(frozen=True)
class Newspaper:
    id: str
    name: str
    url: str
    selector: str


NEWSPAPERS = (
    Newspaper("elpais", "El País", "https://elpais.com/", "article.c-d .c_t"),
    Newspaper("elmundo", "El Mundo", "https://www.elmundo.es/", ".ue-c-cover-content__headline"),
    Newspaper("elconfidencial", "El Confidencial", "https://www.elconfidencial.com/", "article.teaser .teaser__titleLink"),
    Newspaper("theobjective", "The Objective", "https://theobjective.com/", ".tno-blocks-article-top__title, .tno-article-block__title"),
    Newspaper("abc", "ABC", "https://www.abc.es/", "article .v-a-t"),
    Newspaper("eldiario", "elDiario.es", "https://www.eldiario.es/", "article .ni-title"),
    Newspaper("larazon", "La Razón", "https://www.larazon.es/", "article .article__title"),
    Newspaper("lavanguardia", "La Vanguardia", "https://www.lavanguardia.com/", "article.article-module .title"),
    Newspaper("elperiodico", "El Periódico", "https://www.elperiodico.com/es/", ".ft-org-cardHome__mainTitle"),
    Newspaper("epe", "El Periódico de España", "https://www.epe.es/es/", ".ft-org-cardHome__mainTitle"),
    Newspaper("ara", "ARA", "https://www.ara.cat/", ".combo-title--article .combo-title-wrapper"),
    Newspaper("elespanol", "El Español", "https://www.elespanol.com/", "article.art .art__title"),
    Newspaper("publico", "Público", "https://www.publico.es/", "article h2.title"),
    Newspaper("20minutos", "20minutos", "https://www.20minutos.es/", "article .c-article__title"),
    Newspaper("infolibre", "infoLibre", "https://www.infolibre.es/", ".ni-title"),
    Newspaper("vozpopuli", "Vozpópuli", "https://www.vozpopuli.com/", "article .block-post-title h2"),
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Readerme/1.0)",
    "Accept-Language": "es-ES,es;q=0.9,ca;q=0.8",
    "Cache-Control": "no-cache, no-store",
    "Pragma": "no-cache",
}
logger = logging.getLogger(__name__)


def extract_headline(html: str, paper: Newspaper) -> tuple[str, str] | None:
    soup = BeautifulSoup(html, "lxml")
    for node in soup.select(paper.selector):
        if node.find_parent(["nav", "footer", "template", "aside"]):
            continue
        if any(p.has_attr("hidden") or p.get("aria-hidden") == "true"
               for p in [node, *node.parents]):
            continue
        link = node if node.name == "a" else node.find("a", href=True) or node.find_parent("a", href=True)
        if link is None or not link.get("href"):
            continue
        title = " ".join(node.stripped_strings)
        url = urljoin(paper.url, link["href"])
        parsed = urlsplit(url)
        if not title or parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        if parsed.path in ("", "/", "/es/", "/ca/"):
            continue
        return title, url
    return None


def fetch_headline(paper: Newspaper, client: httpx.Client) -> dict:
    result = {"id": paper.id, "name": paper.name, "home": paper.url,
              "title": None, "url": None}
    try:
        response = client.get(paper.url)
        response.raise_for_status()
        headline = extract_headline(response.text, paper)
        if headline:
            result["title"], result["url"] = headline
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Portada %s unavailable: %s", paper.id, type(exc).__name__)
    return result


def fetch_headlines() -> dict:
    # Independent requests: one unavailable newspaper doesn't block the others.
    with httpx.Client(headers=HEADERS, timeout=8, follow_redirects=True, max_redirects=3) as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            headlines = list(pool.map(lambda paper: fetch_headline(paper, client), NEWSPAPERS))
    return {"updated_at": datetime.now(timezone.utc).isoformat(), "headlines": headlines}
