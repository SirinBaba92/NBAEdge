"""Prüft, ob für alle Spiele eines US-Spieltags eine Prognose (Snapshot) existiert.
Nur lesend, kein Netzabruf. Spielplan: data/upcoming_cache.json (hält die Betano-Automatik stündlich aktuell),
Prognosen: analysis/results/forecast_snapshots/<Tag>.json.
Aufruf: venv/bin/python analysis/check_prognosen.py [US-Tag]   (Standard: heutiger US-Tag)
Rückgabe: 0 = alle Spiele haben eine Prognose vor Anpfiff, 1 = es fehlt etwas oder sie kam nach Anpfiff, 2 = Spielplan nicht verfügbar."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _short(name: str) -> str:
    return str(name).split()[-1]


def check(day: str, cache_file: Path | None = None, snapshot_dir: Path | None = None, now: float | None = None) -> dict:
    """Liefert {'status': 'ok'|'fehlt'|'kein_spielplan', 'spiele': n, 'fehlt': [...], 'nach_anpfiff': [...], 'cache_alter_min': m}."""
    from data import fetcher
    from engine import player_snapshots as ps

    now = time.time() if now is None else now
    cache_file = cache_file or fetcher._upcoming_cache_path()
    snapshot_dir = snapshot_dir or ps.snapshot_dir()
    try:
        cache = json.loads(Path(cache_file).read_text(encoding="utf-8"))
        games = [g for g in cache.get("games", []) if str(g.get("date", ""))[:10] == day and not g.get("postponed")]
        age_min = int((now - cache.get("fetched_at", now)) / 60)
    except (OSError, ValueError):
        return {"status": "kein_spielplan", "spiele": 0, "fehlt": [], "nach_anpfiff": [], "cache_alter_min": None}
    if not games:
        return {"status": "kein_spielplan", "spiele": 0, "fehlt": [], "nach_anpfiff": [], "cache_alter_min": age_min}

    try:
        snaps = json.loads((Path(snapshot_dir) / f"{day}.json").read_text(encoding="utf-8")).get("games", {})
    except (OSError, ValueError):
        snaps = {}
    have = {}
    for key, entry in snaps.items():
        parts = key.split("|")
        if len(parts) >= 4:
            have[(parts[2], parts[3])] = bool(entry.get("created_after_start"))

    fehlt, spaet = [], []
    for g in games:
        home, away = g["home_team"]["full_name"], g["visitor_team"]["full_name"]
        label = f"{_short(away)} @ {_short(home)}"
        if (home, away) not in have:
            fehlt.append(label)
        elif have[(home, away)]:
            spaet.append(label)
    return {"status": "ok" if not fehlt and not spaet else "fehlt", "spiele": len(games), "fehlt": fehlt, "nach_anpfiff": spaet, "cache_alter_min": age_min}


def render(day: str, res: dict) -> str:
    if res["status"] == "kein_spielplan":
        alter = f" (Zwischenspeicher {res['cache_alter_min']} Min. alt)" if res["cache_alter_min"] is not None else ""
        return f"Prognosen {day}: Spielplan für diesen Tag nicht im Zwischenspeicher{alter}. Nicht geprüft."
    n, ok = res["spiele"], res["spiele"] - len(res["fehlt"]) - len(res["nach_anpfiff"])
    if res["status"] == "ok":
        return f"Prognosen {day}: {n} von {n} Spielen haben eine Prognose vor Anpfiff. (Spielplan {res['cache_alter_min']} Min. alt)"
    L = [f"Prognosen {day}: {ok} von {n} Spielen mit Prognose vor Anpfiff. (Spielplan {res['cache_alter_min']} Min. alt)"]
    if res["fehlt"]:
        L.append("  FEHLT: " + ", ".join(res["fehlt"]))
    if res["nach_anpfiff"]:
        L.append("  Nach Anpfiff erstellt (zählt in der Auswertung nicht): " + ", ".join(res["nach_anpfiff"]))
    return "\n".join(L)


def main(argv) -> int:
    if argv:
        day = argv[0]
    else:
        from data.game_updates import us_today
        day = us_today().isoformat()
    datetime.strptime(day, "%Y-%m-%d")
    res = check(day)
    print(render(day, res))
    return {"ok": 0, "fehlt": 1, "kein_spielplan": 2}[res["status"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
