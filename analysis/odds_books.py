"""Nur lesen: Welche Bookmaker stecken im Odds-Cache (data/odds_cache.json) und was aendert sich am
Markt-Durchschnitt (Total, Spread), wenn man nur bestimmte Bookmaker nimmt (z. B. nur US-Buecher)?
Kein Netzwerkzugriff, keine Credits. Aufruf: venv/bin/python analysis/odds_books.py [bookmaker,...]
Ohne Argument: Vergleich 'alle Bookmaker' gegen 'nur SOFT_BOOKS aus config/settings.py' (US-Buecher)."""
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import SOFT_BOOKS
from data.odds_client import cache_path, describe_age
import json
import time


def main(argv):
    path = cache_path()
    if not path.exists():
        print(f"Kein Cache unter {path}. Erst einmal 'Refresh Odds' in der App ausfuehren.")
        return 1
    entry = json.loads(path.read_text()).get("entries", {}).get("totals_spreads")
    if not entry:
        print("Cache enthaelt keine Totals/Spreads.")
        return 1
    keep = set(argv[0].split(",")) if argv else set(SOFT_BOOKS)
    print(f"Totals/Spreads {describe_age(time.time() - entry['fetched_at'])}, Maerkte {entry['markets']}, Regionen {entry['regions']}")
    books = Counter(b["key"] for ev in entry["data"] for b in ev.get("bookmakers", []))
    print("Bookmaker in der Antwort (Anzahl Spiele):", ", ".join(f"{k} ({n})" for k, n in sorted(books.items())))
    print("(Die Antwort nennt die Region je Bookmaker nicht. Die Zuordnung steht in der Dokumentation der Odds API.)")
    print(f"\nVergleich: alle Bookmaker gegen nur {sorted(keep)}")
    print("Spiel | Total alle (n) | Total nur gewaehlte (n) | Diff | Spread(Heim) alle | gewaehlte | Diff")
    def avg(ev, only, market):
        vals = []
        for b in ev.get("bookmakers", []):
            if only is not None and b["key"] not in only: continue
            for m in b.get("markets", []):
                if m["key"] != market: continue
                for o in m["outcomes"]:
                    if market == "totals" and o["name"] == "Over": vals.append(o.get("point"))
                    if market == "spreads" and o["name"] == ev["home_team"]: vals.append(-o.get("point"))
        return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)
    for ev in entry["data"]:
        ta, na = avg(ev, None, "totals"); tk, nk = avg(ev, keep, "totals")
        sa, _ = avg(ev, None, "spreads"); sk, _ = avg(ev, keep, "spreads")
        f = lambda x: "-" if x is None else f"{x:.1f}"
        d = lambda a, b: "-" if a is None or b is None else f"{b - a:+.1f}"
        print(f"{ev['away_team']} @ {ev['home_team']} | {f(ta)} ({na}) | {f(tk)} ({nk}) | {d(ta, tk)} | {f(sa)} | {f(sk)} | {d(sa, sk)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
