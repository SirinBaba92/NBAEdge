"""
EINMALIGER Abruf der Spielerzeilen einer Saison (Standard 2024-25, mit --season JJJJ-JJ jede andere, z. B. 2023-24; Regular Season) fuer den Backtest. Schreibt NUR
data/cache/backtest_player_games_<Saison>.json (bewusst nicht player_games_*.json,
damit kein Glob und keine Produktivfunktion die Datei findet). data/player_history.py (SEASONS_TO_LOAD, player_games_*.json, player_games_status.json), die App und das Produktivmodell
bleiben unveraendert; es werden nur die vorhandenen Bausteine importiert (default_fetcher, parse_league_log, atomic_write_json).

Aufruf (aus dem Projektordner):  venv/bin/python analysis/fetch_player_games_2024_25.py [--season 2023-24]
Ein Abruf bei NBA.com (nba_api leaguegamelog, Timeout 60 s). Bei einem Fehler hoechstens 3 Wiederholungen mit Pausen von 30, 60, 120 s, danach Abbruch mit Meldung (nicht endlos).
Existiert die Datei schon, passiert nichts (kein zweiter Abruf). Geschrieben wird erst nach vollstaendigem Erfolg (Temp-Datei, os.replace); keine Schluessel, keine Kopfzeilen in Datei oder Ausgabe.
"""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from data import player_history as ph  # noqa: E402


def season_arg(argv) -> str:
    """Saison aus --season JJJJ-JJ (Startjahr und die zwei Endziffern der Folgejahres muessen zusammenpassen), Standard 2024-25."""
    s = argv[argv.index("--season") + 1] if "--season" in argv and argv.index("--season") + 1 < len(argv) else "2024-25"
    m = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        raise SystemExit(f"Ungueltige Saison {s!r}: erwartet z. B. 2023-24.")
    return s


SEASON = season_arg(sys.argv)
TARGET = ph.cache_dir() / f"backtest_player_games_{SEASON}.json"
PAUSES = (30, 60, 120)                          # Wartezeit vor Wiederholung 1, 2, 3
MIN_ROWS = 20000                                # Plausibilitaet: eine volle Saison hat ca. 26 000 Zeilen


def fetch_once() -> list[dict]:
    payload = ph.default_fetcher(SEASON)
    return ph.parse_league_log(payload, SEASON)


def main() -> int:
    if TARGET.exists():
        print(f"Datei existiert bereits, kein Abruf: {TARGET}")
        return 0
    t0 = time.time()
    last = None
    for attempt in range(1 + len(PAUSES)):
        if attempt:
            print(f"Wiederholung {attempt} von {len(PAUSES)} nach {PAUSES[attempt - 1]} s ({last}) ...", flush=True)
            time.sleep(PAUSES[attempt - 1])
        try:
            rows = fetch_once()
            if len(rows) < MIN_ROWS:
                raise ValueError(f"zu wenige Zeilen ({len(rows)} < {MIN_ROWS}), nichts geschrieben")
            ph.atomic_write_json(TARGET, {"version": ph.VERSION, "format": ph.FORMAT, "season": SEASON, "fetched_at": ph.iso_now(), "source": ph.SOURCE, "rows": rows})
            print(f"Gespeichert: {TARGET} ({len(rows)} Zeilen) in {time.time() - t0:.1f} s, Versuche: {attempt + 1}")
            return 0
        except Exception as e:                                    # nur Fehlerart und kurze Meldung ausgeben
            last = f"{type(e).__name__}: {str(e)[:150]}"
            print(f"Versuch {attempt + 1} fehlgeschlagen: {last}", flush=True)
    print("ABBRUCH: dauerhafter Fehler nach allen Versuchen, nichts geschrieben.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
