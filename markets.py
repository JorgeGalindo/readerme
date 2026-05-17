"""Fetch Polymarket prediction-market history for Spain (España tab) and
Main (global politics) tabs. Each set writes to its own JSON file.

Main shows 4 markets per day on a daily rotation: one from each of four
categories (geopolitics, economy, ai_tech, elections), drawn from a pool of
28 (7 per category). Each market reappears every 7 days."""

from datetime import datetime, timezone

import httpx

import storage

MARKETS_FILE_SPAIN = "markets.json"  # legacy filename
MARKETS_FILE_MAIN = "markets_main.json"


SPAIN_MARKETS = {
    "snap_june": {
        "title": "Elecciones anticipadas antes del 30 jun 2026",
        "token_id": "22727676348515372003751667928661129938953357934816532759741382381194930135311",
        "url": "https://polymarket.com/event/spain-snap-election-called-by/spain-snap-election-called-by-june-30-2026",
    },
    "snap_2026": {
        "title": "Elecciones anticipadas en 2026",
        "token_id": "59503554798824057287666406378885313688964980592517621433937122029072326338100",
        "url": "https://polymarket.com/event/spain-snap-election-called-in-2026",
    },
}


# ---------- Main rotation pool: 28 markets, 7 per category ----------

CATEGORIES = ("geopolitics", "economy", "ai_tech", "elections")

MAIN_MARKETS_POOL: dict[str, dict] = {
    # geopolitics
    "iran_us_invade": {
        "category": "geopolitics",
        "title": "EE.UU. invade Irán antes 2027",
        "token_id": "55115078421062885512539156303747803058407616201213034911037320915726138659123",
        "url": "https://polymarket.com/event/will-the-us-invade-iran-before-2027",
    },
    "china_taiwan": {
        "category": "geopolitics",
        "title": "Invasión china de Taiwán antes fin 2026",
        "token_id": "94559586571241563470235664821564670251180951772614764383113614156422396181162",
        "url": "https://polymarket.com/event/will-china-invade-taiwan-before-2027",
    },
    "netanyahu_jun": {
        "category": "geopolitics",
        "title": "Netanyahu fuera antes 30 jun",
        "token_id": "110540225177219524039862595475289990032643955968401089134377304882717624846278",
        "url": "https://polymarket.com/event/netanyahu-out-before-2027/netanyahu-out-by-june-30-383-244-575",
    },
    "putin_dec": {
        "category": "geopolitics",
        "title": "Putin fuera antes fin 2026",
        "token_id": "350977769852917329387037893294763093471844346281449484439085576212613048126",
        "url": "https://polymarket.com/event/putin-out-before-2027",
    },
    "zelensky_dec": {
        "category": "geopolitics",
        "title": "Zelensky fuera antes fin 2026",
        "token_id": "108187737663325442737199857734058032845728149267925579081973309839049299838520",
        "url": "https://polymarket.com/event/zelenskyy-out-as-ukraine-president-before-2027",
    },
    "iran_leader_dec": {
        "category": "geopolitics",
        "title": "Cambio liderazgo Irán antes 31 dic",
        "token_id": "18652479948917565296149340091675894865339012333173025944893512396354173886674",
        "url": "https://polymarket.com/event/iran-leadership-change-by",
    },
    "us_iran_nuclear": {
        "category": "geopolitics",
        "title": "Acuerdo nuclear EE.UU.-Irán antes 30 jun",
        "token_id": "68283792174293775430535402015214113701251372409839518501034763677920213819299",
        "url": "https://polymarket.com/event/us-iran-nuclear-deal-by-june-30",
    },

    # economy
    "fed_cut_25_jun": {
        "category": "economy",
        "title": "Fed baja 25 bps en junio 2026",
        "token_id": "65193234666628291664907888364936366210889305490897648116746073820519263548476",
        "url": "https://polymarket.com/event/fed-decision-in-june-825/will-the-fed-decrease-interest-rates-by-25-bps-after-the-june-2026-meeting",
    },
    "fed_no_cuts": {
        "category": "economy",
        "title": "Sin recortes Fed en 2026",
        "token_id": "12403602920039269077597917340921667997547115084613238528792639013246536343316",
        "url": "https://polymarket.com/event/how-many-fed-rate-cuts-in-2026/will-no-fed-rate-cuts-happen-in-2026",
    },
    "fed_hike_25_jul": {
        "category": "economy",
        "title": "Fed sube 25 bps en julio 2026",
        "token_id": "10547381015916960267379463101229159185405356924982461726471550099674011526491",
        "url": "https://polymarket.com/event/fed-decision-in-july-181/will-the-fed-increase-interest-rates-by-25-bps-after-the-july-2026-meeting",
    },
    "fed_4_cuts": {
        "category": "economy",
        "title": "4 recortes Fed en 2026",
        "token_id": "73197441127256680134600821323583356037261213281680365433623681075249556019477",
        "url": "https://polymarket.com/event/how-many-fed-rate-cuts-in-2026/will-4-fed-rate-cuts-happen-in-2026",
    },
    "us_recession_2026": {
        "category": "economy",
        "title": "Recesión EE.UU. antes fin 2026",
        "token_id": "100379208559626151022751801118534484742123694725746262280150222742563282755057",
        "url": "https://polymarket.com/event/us-recession-by-end-of-2026",
    },
    "fed_cut_50_jun": {
        "category": "economy",
        "title": "Fed baja 50+ bps en junio 2026",
        "token_id": "110884561568299698460551977852169332756450294345019257864587852438060900499251",
        "url": "https://polymarket.com/event/fed-decision-in-june-825/will-the-fed-decrease-interest-rates-by-50-bps-after-the-june-2026-meeting",
    },
    "fed_hike_50_jun": {
        "category": "economy",
        "title": "Fed sube 50+ bps en junio 2026",
        "token_id": "11019686559003253359318459636510036787281809199165975947920974072245914352862",
        "url": "https://polymarket.com/event/fed-decision-in-june-825/will-the-fed-increase-interest-rates-by-50-bps-after-the-june-2026-meeting",
    },

    # ai_tech
    "xai_best_jun": {
        "category": "ai_tech",
        "title": "xAI mejor modelo fin junio",
        "token_id": "111535169822707617708724803776230447684636442572401432413011961922458103225261",
        "url": "https://polymarket.com/event/which-company-has-best-ai-model-end-of-june/will-xai-have-the-best-ai-model-at-the-end-of-june-2026",
    },
    "anthropic_best_jun": {
        "category": "ai_tech",
        "title": "Anthropic mejor modelo fin junio",
        "token_id": "31257690721782087545855558909530748024291398703956697759040950846127149299962",
        "url": "https://polymarket.com/event/which-company-has-best-ai-model-end-of-june/will-anthropic-have-the-best-ai-model-at-the-end-of-june-2026",
    },
    "openai_best_may": {
        "category": "ai_tech",
        "title": "OpenAI mejor modelo fin mayo",
        "token_id": "99321540480563930395437102180161800415982867363326119900174086397411605035146",
        "url": "https://polymarket.com/event/which-company-has-the-best-ai-model-end-of-may/will-openai-have-the-best-ai-model-at-the-end-of-may-2026",
    },
    "openai_ipo_1t": {
        "category": "ai_tech",
        "title": "OpenAI IPO >$1T",
        "token_id": "2011448762453318924331890857436552502625185273746051467874416268100776921808",
        "url": "https://polymarket.com/event/openai-ipo-closing-market-cap-above",
    },
    "nvidia_top_jun": {
        "category": "ai_tech",
        "title": "NVIDIA mayor empresa 30 jun",
        "token_id": "114266735877811876021362945683127542532778925409590599016489267644246881997088",
        "url": "https://polymarket.com/event/largest-company-end-of-june-712/will-nvidia-be-the-largest-company-in-the-world-by-market-cap-on-june-30-824",
    },
    "tesla_top_jun": {
        "category": "ai_tech",
        "title": "Tesla mayor empresa 30 jun",
        "token_id": "29302012528838680690187789761162568894047228199221874292227996792731980008913",
        "url": "https://polymarket.com/event/largest-company-end-of-june-712/will-tesla-be-the-largest-company-in-the-world-by-market-cap-on-june-30",
    },
    "openai_acquired": {
        "category": "ai_tech",
        "title": "OpenAI adquirida antes 2027",
        "token_id": "32919655202731037203140231130939093798403278359599025499865606899485004387270",
        "url": "https://polymarket.com/event/which-companies-will-be-acquired-before-2027/will-openai-be-acquired-before-2027-859",
    },

    # elections (internacionales)
    "lula_brazil": {
        "category": "elections",
        "title": "Lula gana presidencial Brasil 2026",
        "token_id": "30630994248667897740988010928640156931882346081873066002335460180076741328029",
        "url": "https://polymarket.com/event/brazil-presidential-election/will-luiz-incio-lula-da-silva-win-the-2026-brazilian-presidential-election",
    },
    "starmer_dec": {
        "category": "elections",
        "title": "Starmer fuera antes fin 2026",
        "token_id": "42498579290170525937803365597001189493798686141769429176410526295573824619073",
        "url": "https://polymarket.com/event/starmer-out-in-2025/starmer-out-by-december-31-2026-936-416-977-234-134-475",
    },
    "akesson_sweden": {
        "category": "elections",
        "title": "Åkesson próximo PM Suecia",
        "token_id": "82283291912489202302595502692326101345632588904573705648995568317366762287152",
        "url": "https://polymarket.com/event/next-prime-minister-of-sweden/will-jimmie-kesson-be-the-next-prime-minister-of-sweden",
    },
    "farage_uk": {
        "category": "elections",
        "title": "Farage próximo PM Reino Unido 2026",
        "token_id": "50960260636990249013018697727132070044900034089108950792866072435222205165583",
        "url": "https://polymarket.com/event/next-uk-prime-minister-in-2026-122/will-nigel-farage-be-the-next-prime-minister-of-the-united-kingdom-in-2026-356",
    },
    "macron_jun": {
        "category": "elections",
        "title": "Macron fuera antes 30 jun 2026",
        "token_id": "16201530957950630406397949502319734794139620443510795733205872225099141120819",
        "url": "https://polymarket.com/event/macron-out-in-2025/macron-out-by-june-30-2026-273",
    },
    "lepen_2027": {
        "category": "elections",
        "title": "Le Pen gana presidencial Francia 2027",
        "token_id": "55764212211467781322980371912612507865974994976253196346176314491480419639168",
        "url": "https://polymarket.com/event/next-french-presidential-election/will-marine-le-pen-win-the-2027-french-presidential-election",
    },
    "burnham_uk": {
        "category": "elections",
        "title": "Burnham próximo PM Reino Unido 2026",
        "token_id": "22879769232544702309459734857825459980910104747937470036552736453122914481526",
        "url": "https://polymarket.com/event/next-uk-prime-minister-in-2026-122/will-andy-burnham-be-the-next-prime-minister-of-the-united-kingdom-in-2026-882",
    },
}


def _daily_keys() -> list[str]:
    """The 4 keys to show today — one per category, rotating every day.
    Each category has 7 markets, so each surfaces once a week."""
    by_cat: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    for k, m in MAIN_MARKETS_POOL.items():
        by_cat[m["category"]].append(k)
    for c in CATEGORIES:
        by_cat[c].sort()
    day = datetime.now(timezone.utc).toordinal()
    return [by_cat[c][day % len(by_cat[c])] for c in CATEGORIES]


def _fetch_one(token_id: str) -> tuple[list[str], list[float], float]:
    """Return (dates, prices, current) for one Polymarket token."""
    resp = httpx.get(
        "https://clob.polymarket.com/prices-history",
        params={"market": token_id, "interval": "all", "fidelity": 360},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    history = data.get("history", [])
    dates: list[str] = []
    prices: list[float] = []
    for point in history:
        ts = point.get("t", 0)
        price = float(point.get("p", 0))
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        dates.append(dt.strftime("%Y-%m-%d"))
        prices.append(round(price * 100, 1))
    current = prices[-1] if prices else 0
    return dates, prices, current


def _fetch_set(name: str, markets: dict, out_file: str) -> dict:
    print(f"Fetching Polymarket data ({name})…")
    out: dict = {}
    for key, market in markets.items():
        try:
            dates, prices, current = _fetch_one(market["token_id"])
            out[key] = {
                "title": market["title"],
                "url": market["url"],
                "dates": dates,
                "prices": prices,
                "current": current,
            }
            print(f"  {market['title']}: {current}% ({len(dates)} points)")
        except Exception as e:
            print(f"  Failed {key}: {e}")
    storage.write_json(out_file, out)
    return out


def fetch_markets() -> dict:
    return _fetch_set("spain", SPAIN_MARKETS, MARKETS_FILE_SPAIN)


def fetch_markets_main() -> dict:
    """Fetch only today's 4 rotating markets, one per category."""
    keys = _daily_keys()
    print(f"  Main rotation today ({datetime.now(timezone.utc).date()}): {keys}")
    selected = {k: MAIN_MARKETS_POOL[k] for k in keys}
    return _fetch_set("main", selected, MARKETS_FILE_MAIN)


if __name__ == "__main__":
    fetch_markets()
    fetch_markets_main()
