"""Vorher/Nachher des Totals-Fixes (Playoffs nicht in Off/Def) fuer drei Spiele.
Vorher = gespeichertes Pickle (nur gelesen). Nachher = Modell im Speicher aus data/cache neu aufgebaut
(wird NICHT gespeichert, kein Training ueber API). Aufruf: venv/bin/python tests/totals_fix_vorher_nachher.py"""
import datetime, json, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from models.elo import EloEngine
from data.odds import parse_totals_spreads
from engine.projection import compute_projection

games = []
for y in range(2015, 2026):
    games += json.loads((ROOT / "data" / "cache" / f"games_{y}.json").read_text())
games = [g for g in games if g.get("status") == "Final" and not g.get("postponed")]
games.sort(key=lambda g: g["date"])          # wie build_model (nur nach Datum)
new = EloEngine()
for g in games:
    new.process_game(g)
new.fit_lr()                                  # ohne save(): Pickle bleibt unberuehrt
old = EloEngine.load()

# (Heim, Gast, Handicap Heimteam laut Odds API, Markt-Total)
spiele = [("New York Knicks", "Philadelphia 76ers", -4.5, 232.0),
          ("San Antonio Spurs", "Oklahoma City Thunder", 0.2, 230.7),
          ("Detroit Pistons", "Boston Celtics", 1.5, 219.8)]
nick = lambda t: t.split()[-1]
print(f"Nachher-Modell im Speicher: {len(new.processed_ids)} Spiele, Ratings bis {new.ratings_as_of()}; "
      f"ELO-Ratings identisch zum Pickle: {all(abs(new.ratings[t]-old.ratings[t])<1e-9 for t in old.ratings)}")
print("\nSpiel | Variante | Modell-Total roh | Markt-Total | Marktgewicht | finaler Total | Score Gast-Heim | finaler Spread (Heim +)")
for h, a, pt, mt in spiele:
    ev = [{"home_team": h, "away_team": a, "bookmakers": [{"key": "x", "markets": [{"key": "spreads", "outcomes": [
        {"name": h, "point": pt, "price": 1.9}, {"name": a, "point": -pt, "price": 1.9}]}]}]}]
    ms = parse_totals_spreads(ev)[(nick(h).lower(), nick(a).lower())]["spread"]
    for name, eng in (("vorher", old), ("nachher", new)):
        pred = eng.predict(h, a, datetime.date(2026, 10, 20))
        p = compute_projection(pred, market_total=mt, market_spread=ms, game_date="2026-10-20")
        print(f"{nick(a)} @ {nick(h)} | {name} | {p['model_total']} | {mt} | {p['market_weight']} | {p['exp_total']} | "
              f"{p['away_score']}-{p['home_score']} | {p['exp_spread']:+}")
