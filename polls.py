"""Fetch Spanish election polling trends from colmenadedatos.com (Datawrapper)."""

import csv
import json
import pathlib
from io import StringIO

import httpx

DATA_DIR = pathlib.Path(__file__).parent / "data"
POLLS_FILE = DATA_DIR / "polls.json"

DATAWRAPPER_CSV = "https://datawrapper.dwcdn.net/7zFyg/17/dataset.csv"

PARTIES = ["PP", "PSOE", "VOX", "SUMAR", "PODEMOS"]


def fetch_and_process() -> dict:
    """Fetch trend estimates from colmenadedatos/Datawrapper and compute bloc analysis."""
    print("Fetching polling trends from colmenadedatos.com...")
    resp = httpx.get(DATAWRAPPER_CSV, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()

    reader = csv.DictReader(StringIO(resp.text), delimiter="\t")
    rows = list(reader)
    print(f"  {len(rows)} data points")

    dates = []
    averages = {p: [] for p in PARTIES}

    for row in rows:
        # Parse date DD/MM/YYYY → YYYY-MM-DD
        date_raw = row.get("Promedio", "").strip()
        if not date_raw:
            continue
        parts = date_raw.split("/")
        if len(parts) != 3:
            continue
        date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        dates.append(date)

        for party in PARTIES:
            val = row.get(party, "").strip().replace(",", ".")
            try:
                averages[party].append(float(val))
            except (ValueError, TypeError):
                averages[party].append(None)

    # Bloc analysis from latest data point
    latest = {p: averages[p][-1] for p in PARTIES if averages[p][-1] is not None}
    pp = latest.get("PP", 0)
    vox = latest.get("VOX", 0)
    right_bloc = round(pp + vox, 1)

    # Left bloc: PSOE + Sumar + Podemos + ~7% for regional parties (ERC, Junts, PNV, Bildu)
    psoe = latest.get("PSOE", 0)
    sumar = latest.get("SUMAR", 0)
    podemos = latest.get("PODEMOS", 0)
    regional_estimate = 7.0  # Approximate combined regional left-aligned parties
    left_bloc = round(psoe + sumar + podemos + regional_estimate, 1)

    gap = round(right_bloc - left_bloc, 1)

    if right_bloc >= 50:
        prob = "alta"
    elif right_bloc >= 46:
        prob = "media"
    else:
        prob = "baja"

    bloc = {
        "pp": pp,
        "vox": vox,
        "right_bloc": right_bloc,
        "left_bloc": left_bloc,
        "gap": gap,
        "gap_label": f"{'derecha' if gap > 0 else 'izquierda'} +{abs(gap)}",
        "majority_prob": prob,
    }

    result = {
        "dates": dates,
        "averages": averages,
        "bloc": bloc,
        "n_polls": len(dates),
        "source": "colmenadedatos.com / Datawrapper",
    }

    DATA_DIR.mkdir(exist_ok=True)
    POLLS_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"  Bloc: derecha {right_bloc}% vs izquierda {left_bloc}%")
    print(f"  Gap: {bloc['gap_label']} | Mayoría PP+Vox: {prob}")
    return result


if __name__ == "__main__":
    fetch_and_process()
