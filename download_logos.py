"""
Laedt die 30 NBA-Teamlogos einmalig nach data/logos/<KUERZEL>.svg.

  python download_logos.py --probe    # ein einziger Abruf (Adressmuster pruefen)
  python download_logos.py            # alle fehlenden Logos holen

- Team-IDs und Kuerzel kommen aus nba_api.stats.static.teams (lokale Daten, kein Netzwerk).
- Abruf nur von cdn.nba.com mit dem Header-Set NBA_HEADERS aus data/nba_live.py.
- Hoechstens MAX_REQUESTS Abrufe pro Lauf. Bei 403 oder jeder anderen Ablehnung wird sofort abgebrochen
  (kein Umgehen, keine weiteren Versuche).
- Bereits vorhandene Dateien werden nicht erneut geladen.
Die Logos sind NBA-Marken: nur fuer dieses lokale Dashboard, nicht weitergeben.
"""
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.nba_live import NBA_HEADERS

LOGO_URL = "https://cdn.nba.com/logos/nba/{team_id}/global/L/logo.svg"
LOGO_DIR = Path(__file__).resolve().parent / "data" / "logos"
MAX_REQUESTS = 35
PAUSE_SECONDS = 0.5


def teams():
    from nba_api.stats.static import teams as static_teams
    return sorted(static_teams.get_teams(), key=lambda t: t["abbreviation"])


def looks_like_svg(content: bytes) -> bool:
    head = content[:400].lstrip().lower()
    return b"<svg" in content[:2000].lower() or head.startswith(b"<?xml")


def main(argv) -> int:
    probe = "--probe" in argv
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    todo = [t for t in teams() if not (LOGO_DIR / f"{t['abbreviation']}.svg").exists()]
    if probe:
        todo = todo[:1]
    print(f"{len(todo)} Logo(s) zu laden (Limit {MAX_REQUESTS} Abrufe).")
    requests_made = 0
    for t in todo:
        if requests_made >= MAX_REQUESTS:
            print("Abrufgrenze erreicht, Abbruch.")
            return 1
        url = LOGO_URL.format(team_id=t["id"])
        requests_made += 1
        try:
            r = requests.get(url, headers=NBA_HEADERS, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"Netzwerkfehler bei {t['abbreviation']} ({type(e).__name__}). Abbruch ohne weitere Versuche.")
            return 1
        if r.status_code != 200 or not looks_like_svg(r.content):
            print(f"{t['abbreviation']}: HTTP {r.status_code}, "
                  f"{'kein SVG' if r.status_code == 200 else 'abgelehnt'}. Abbruch ohne weitere Versuche.")
            return 1
        (LOGO_DIR / f"{t['abbreviation']}.svg").write_bytes(r.content)
        print(f"{t['abbreviation']}: {len(r.content)} Bytes gespeichert")
        time.sleep(PAUSE_SECONDS)
    have = len(list(LOGO_DIR.glob("*.svg")))
    print(f"Fertig: {requests_made} Abruf(e), {have} Logo(s) in {LOGO_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
