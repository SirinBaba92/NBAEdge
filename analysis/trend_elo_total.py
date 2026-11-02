"""Fairer Elo-Vergleich fuer die Punktesumme (nur lesend, ohne Netz): jede Sicherung data/model_history/elo_model_<Tag>.pkl sagt dieselben beendeten Spiele voraus.

  venv/bin/python analysis/trend_elo_total.py [Testbeginn JJJJ-MM-TT]

Je Stand: mittlere Verzerrung (Prognose minus tatsaechliche Summe) und mittlerer Fehler der Summe (MAE) aus predict()['expected_total']; zum Vergleich die Marktlinie
(market_total aus dem Snapshot). Nur Staende mit ratings_as_of vor dem Testbeginn. Aendert nichts."""
import json, pickle, sys, warnings
from datetime import date
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
start = sys.argv[1] if len(sys.argv) > 1 else "2026-10-27"
snap = json.loads((ROOT / "data/tracking/projection_snapshots.json").read_text())
games = []
for g in snap["games"].values():
    r, vs = g.get("result"), g.get("versions")
    if r and vs and g["game_date"] >= start:
        games.append((g["game_date"], g["home"], g["away"], r["home_points"] + r["away_points"], (vs[-1].get("projection") or {}).get("market_total")))
n = len(games)
act = [g[3] for g in games]
print(f"Testmenge: {n} beendete Spiele ab {start}; mittlere tatsaechliche Summe {sum(act)/n:.1f}")
print("Stand (Sicherung)   Stand bis   Verzerrung   MAE   mittl. Prognose")
for f in sorted((ROOT / "data/model_history").glob("elo_model_*.pkl")):
    m = pickle.load(open(f, "rb")); asof = m.ratings_as_of()
    if asof is None or asof.isoformat() >= start:
        continue
    try:
        ps = [m.predict(h, a, date.fromisoformat(d))["expected_total"] for d, h, a, _, _ in games]
    except Exception:
        print(f.stem[10:], "Vorhersage nicht moeglich"); continue
    bias = sum(p - y for p, y in zip(ps, act)) / n
    mae = sum(abs(p - y) for p, y in zip(ps, act)) / n
    print(f"{f.stem[10:]:18s}  {asof}   {bias:+6.1f}     {mae:5.1f}   {sum(ps)/n:6.1f}")
mk = [(g[4], g[3]) for g in games if g[4] is not None]
print(f"{'Marktlinie':18s}  {'':10s}   {sum(a-b for a,b in mk)/len(mk):+6.1f}     {sum(abs(a-b) for a,b in mk)/len(mk):5.1f}   {sum(a for a,_ in mk)/len(mk):6.1f}   (n={len(mk)})")
