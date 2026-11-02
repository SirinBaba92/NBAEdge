"""Rueckvergleich (nur lesend, ohne Netz): unser Elo (models/elo.py) gegen eine Paine-artige Variante (Sommer-Uebertrag, linearer Margin-Update, anderer Heimvorteil).
Trainiert/kalibriert auf Saisons 2015-2019, getestet auf 2020-2025 (data/cache/games_*.json). Aufruf: venv/bin/python analysis/backtest_elo_paine.py"""
import json, math, sys, warnings
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
warnings.filterwarnings("ignore")
ROOT = Path("/Users/baranalturk/Desktop/NBAEdge"); sys.path.insert(0, str(ROOT))
from models.elo import EloEngine, _parse_date

seasons = {}
for y in range(2015, 2026):
    g = [x for x in json.load(open(ROOT / f"data/cache/games_{y}.json")) if x.get("status") == "Final" and x.get("home_team_score") is not None and not x.get("postponed")]
    g.sort(key=lambda x: (x["date"], x["id"]))
    seasons[y] = g

def ours():
    e = EloEngine(); out = []
    for y, gs in seasons.items():
        for i, g in enumerate(gs):
            h, a = g["home_team"]["full_name"], g["visitor_team"]["full_name"]; d = _parse_date(g["date"])
            hr = e.ratings.get(h, 1500.0) + e.hca + e._rest_factor(h, d) + (e._form_score(h) - .5) * 40
            ar = e.ratings.get(a, 1500.0) + e._rest_factor(a, d) + (e._form_score(a) - .5) * 40
            out.append((y, i, g["postseason"], hr - ar, int(g["home_team_score"] > g["visitor_team_score"])))
            e.process_game(g)
    return out

def paine(carry, hca, kp, regseason_only_score=True):
    r = {}; out = []
    for y, gs in seasons.items():
        for t in r: r[t] = 1500 + carry * (r[t] - 1500)
        for i, g in enumerate(gs):
            h, a = g["home_team"]["full_name"], g["visitor_team"]["full_name"]
            diff = r.get(h, 1500.) + hca - r.get(a, 1500.)
            out.append((y, i, g["postseason"], diff, int(g["home_team_score"] > g["visitor_team_score"])))
            m = g["home_team_score"] - g["visitor_team_score"]; exp = 1 / (1 + 10 ** (-diff / 400))
            delta = kp * m * 0 + kp * (abs(m)) * ((1 if m > 0 else 0) - exp)       # linear in margin
            r[h] = r.get(h, 1500.) + delta; r[a] = r.get(a, 1500.) - delta
    return out

def evaluate(rows, train=range(2015, 2020), test=range(2020, 2026), early=150):
    tr = [(d, o) for y, i, p, d, o in rows if y in train and not p]
    lr = LogisticRegression(C=1e6).fit(np.array([[d] for d, _ in tr]), [o for _, o in tr])
    def br(sel):
        sel = list(sel)
        if not sel: return float("nan")
        p = lr.predict_proba(np.array([[d] for _, _, _, d, _ in sel]))[:, 1]
        return float(np.mean((p - np.array([o for *_, o in sel])) ** 2))
    reg = [x for x in rows if x[0] in test and not x[2]]
    return br(reg), br([x for x in reg if x[1] < early]), br([x for x in reg if x[1] < 400 and x[1] >= 150]), lr.coef_[0][0]

o = ours()
print("Unser Modell (Engine, K=20, log-MOV, HCA 100, ohne Sommerregression), nur Skala neu kalibriert:")
print("  Brier gesamt %.4f | erste 150 Spiele/Saison %.4f | Spiele 150-400 %.4f" % evaluate(o)[:3])
best = None
for carry in (1.0, 0.8, 0.61):
    for hca in (41, 100):
        for kp in (0.5, 1.0, 1.5, 2.0, 3.0):
            res = evaluate(paine(carry, hca, kp), train=range(2015, 2020))
            if best is None or res[0] < best[0][0]: pass
            print("Paine-artig carry %.2f hca %3d kp %.1f: gesamt %.4f | frueh %.4f | 150-400 %.4f" % (carry, hca, kp, *res[:3]))

print("\n--- gepaarter Vergleich auf Testsaisons 2020-2025 (Paine-artig carry 0,61 / hca 41 / kp 2,0 gegen unser Modell) ---")
def probs(rows, train=range(2015, 2020), test=range(2020, 2026)):
    tr = [(d, o) for y, i, p, d, o in rows if y in train and not p]
    lr = LogisticRegression(C=1e6).fit(np.array([[d] for d, _ in tr]), [o for _, o in tr])
    reg = [x for x in rows if x[0] in test and not x[2]]
    p = lr.predict_proba(np.array([[x[3]] for x in reg]))[:, 1]
    return np.array([(pp - x[4]) ** 2 for pp, x in zip(p, reg)]), np.array([x[1] for x in reg]), np.array([x[0] for x in reg])
bo, idx, yy = probs(o); bp, _, _ = probs(paine(0.61, 41, 2.0))
for name, m in (("alle", np.ones(len(bo), bool)), ("erste 150 Spiele je Saison", idx < 150)):
    d = (bo - bp)[m]; rng = np.random.default_rng(1); bs = [rng.choice(d, len(d)).mean() for _ in range(2000)]
    print(f"{name}: n={m.sum()}  Brier unser - Paine-artig = {d.mean():+.4f}  95%-Intervall [{np.percentile(bs,2.5):+.4f}, {np.percentile(bs,97.5):+.4f}]")
print("pro Testsaison (unser | Paine-artig):", {int(y): (round(float(bo[yy==y].mean()),4), round(float(bp[yy==y].mean()),4)) for y in sorted(set(yy))})
