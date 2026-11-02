"""Fairer Elo-Vergleich (nur lesend, ohne Netz): jede Tagessicherung data/model_history/elo_model_<Tag>.pkl sagt DIESELBEN beendeten Spiele voraus.

  venv/bin/python analysis/trend_elo_fair.py [Testbeginn JJJJ-MM-TT]

Testmenge: beendete Spiele aus data/tracking/projection_snapshots.json mit Spieldatum >= Testbeginn (Standard 2026-10-27). Verglichen werden nur Staende, deren letztes
verarbeitetes Spiel (ratings_as_of) VOR dem Testbeginn liegt, damit kein Stand ein Testspiel schon kennt. Je Stand: Brier-Wert, Log-Loss, Trefferquote des Siegers.
Zum Vergleich: die damals gezeigte Prognose (Snapshot) und die Konstante 'Heimquote der Testmenge'. Aendert nichts."""
import json, math, pickle, sys, warnings
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
    if r and vs and g["game_date"] >= start and (vs[-1].get("projection") or {}).get("home_win_prob") is not None:
        games.append((g["game_date"], g["home"], g["away"], 1 if r["home_points"] > r["away_points"] else 0, vs[-1]["projection"]["home_win_prob"]))
n = len(games)

def score(ps, ys):
    eps = 1e-4
    br = sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ys)
    ll = -sum(math.log(max(eps, min(1 - eps, p if y else 1 - p))) for p, y in zip(ps, ys)) / len(ys)
    acc = sum(1 for p, y in zip(ps, ys) if (p > .5) == bool(y)) / len(ys)
    return br, ll, acc

ys = [g[3] for g in games]
print(f"Testmenge: {n} beendete Spiele ab {start}; Heimsiege {sum(ys)} ({sum(ys)/n*100:.0f} %)")
print("Stand (Sicherung)   Stand bis   Brier   LogLoss  Treffer   mittl. Heimchance")
for f in sorted((ROOT / "data/model_history").glob("elo_model_*.pkl")):
    try:
        m = pickle.load(open(f, "rb"))
    except Exception as e:
        print(f.stem, "nicht ladbar:", type(e).__name__); continue
    asof = m.ratings_as_of()
    if asof is None or asof.isoformat() >= start:
        print(f"{f.stem[10:]:18s}  {asof}   (kennt Testspiele, ausgelassen)")
        continue
    ps, ok = [], True
    for d, h, a, y, _ in games:
        try:
            ps.append(m.predict(h, a, date.fromisoformat(d))["home_win_prob"])
        except Exception:
            ok = False; break
    if not ok:
        print(f"{f.stem[10:]:18s}  {asof}   (Vorhersage nicht moeglich)"); continue
    br, ll, acc = score(ps, ys)
    print(f"{f.stem[10:]:18s}  {asof}   {br:.4f}  {ll:.4f}   {acc*100:4.0f} %    {sum(ps)/n:.3f}")
br, ll, acc = score([g[4] for g in games], ys)
print(f"{'Snapshot (gezeigt)':18s}  {'':10s} {br:.4f}  {ll:.4f}   {acc*100:4.0f} %    {sum(g[4] for g in games)/n:.3f}")
h = sum(ys) / n
br, ll, acc = score([h] * n, ys)
print(f"{'Konstante Heimquote':18s}  {'':10s} {br:.4f}  {ll:.4f}   {acc*100:4.0f} %    {h:.3f}")
print("Hinweis: kleine Testmenge; Brier-Unterschiede unter ca. 0,01 sind Rauschen.")
