"""Kaderliste aktualisieren: EIN Abruf an stats.nba.com (nba_api PlayerIndex), schreibt data/rosters.json.
Nicht aktiviert, nicht im Zeitplan: nur von Hand starten:  venv/bin/python fetch_rosters.py"""
import sys

from data import rosters


def main() -> int:
    print("1 Abruf an stats.nba.com (PlayerIndex, Timeout 30 s, ein Versuch) …")
    try:
        d = rosters.refresh(progress=lambda f, t: print(f"  {int(f * 100):3d} %  {t}"))
    except rosters.RosterError as e:
        print("FEHLER:", e)
        return 1
    print(f"Gespeichert: {rosters.rosters_path()} ({sum(len(v) for v in d['teams'].values())} Spieler, {len(d['teams'])} Teams, Stand {d['fetched_at']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
