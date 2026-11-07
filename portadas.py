"""The lead headline on each newspaper's public home page, fetched on demand.

Selectors refer to the opening story, not tickers, related links or RSS order.
Checked against the public home pages on 2026-11-07. No model or paid API.

El Periódico and El Periódico de España were dropped on 2026-11-07: both answer
406 to this client, so their rows only ever said «No disponible».
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx


@dataclass(frozen=True)
class Newspaper:
    id: str
    name: str
    url: str
    selector: str
    # Optional regex the link path must match. El Mundo puts a carousel of
    # games (crucigrama, sudoku…) above the opening with the same markup.
    article_path: str | None = None


NEWSPAPERS = (
    Newspaper("elpais", "El País", "https://elpais.com/", "article.c-d .c_t"),
    Newspaper("elmundo", "El Mundo", "https://www.elmundo.es/", ".ue-c-cover-content__headline",
              article_path=r"/\d{4}/\d{2}/\d{2}/"),
    Newspaper("elconfidencial", "El Confidencial", "https://www.elconfidencial.com/", "article.teaser .teaser__titleLink"),
    Newspaper("theobjective", "The Objective", "https://theobjective.com/", ".tno-blocks-article-top__title, .tno-article-block__title"),
    Newspaper("abc", "ABC", "https://www.abc.es/", "article .v-a-t"),
    Newspaper("eldiario", "elDiario.es", "https://www.eldiario.es/", "article .ni-title"),
    Newspaper("larazon", "La Razón", "https://www.larazon.es/", "article .article__title"),
    Newspaper("lavanguardia", "La Vanguardia", "https://www.lavanguardia.com/", "article.article-module .title"),
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
        if paper.article_path and not re.search(paper.article_path, parsed.path):
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


BY_ID = {paper.id: paper for paper in NEWSPAPERS}
TIMEOUT = httpx.Timeout(6, connect=3)


def _client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True, max_redirects=3)


def fetch_one(paper_id: str) -> dict | None:
    """One newspaper, for the page that fills each row as soon as it answers."""
    paper = BY_ID.get(paper_id)
    if paper is None:
        return None
    with _client() as client:
        result = fetch_headline(paper, client)
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result

