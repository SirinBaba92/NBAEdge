"""Test fuer analysis/backtest_opp_pace.py an einem kleinen kuenstlichen Beispiel (Teamverlauf nur vor dem Spieltag und derselben Saison, D/P/H, Fit, Bootstrap, Korrektur, Regel). Ohne Netz.
Aufruf: venv/bin/python tests/test_opp_pace.py"""
import os, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import backtest_opp_pace as op

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
near = lambda a, b, t=1e-9: abs(a - b) < t

# zwei Teams A, B: je Spiel zwei Spielerzeilen (Teampunkte = Summe); A erzielt 100, B 90 (A zugelassen 90, B zugelassen 100); 6 Spiele ab 2024-01-01
rows = []
def add(gid, day, team, opp, home, pts, season="2023-24"):
    rows.append({"game_id": gid, "date": f"2024-01-{day:02d}", "season": season, "team": team, "opponent": opp, "home": home, "points": pts // 2, "person_id": hash((gid, team, 1)) % 99999})
    rows.append({"game_id": gid, "date": f"2024-01-{day:02d}", "season": season, "team": team, "opponent": opp, "home": home, "points": pts - pts // 2, "person_id": hash((gid, team, 2)) % 99999})
for i in range(6):
    add(f"g{i}", i + 1, "A", "B", True, 100); add(f"g{i}", i + 1, "B", "A", False, 90)
# frueherer Saisonwert (andere Saison) darf nicht zaehlen
add("old", 1, "A", "B", True, 150, season="2022-23"); add("old", 1, "B", "A", False, 150, season="2022-23")
ts = op.TeamStats(op.team_games(rows))
D0 = 20240107
n, f, a = ts.team("2023-24", "A", D0)
check("Teamverlauf: 6 Spiele, Punkte fuer 600 / gegen 540 (nur diese Saison)", n == 6 and f == 600 and a == 540, (n, f, a))
check("vor dem 4. Tag nur 3 Spiele (Spieltag selbst nicht)", ts.team("2023-24", "A", 20240104)[0] == 3)
check("Liga-Schnitt = 95", near(ts.league_mean("2023-24", D0), 95.0))
ft = op.features(ts, "2023-24", "A", "B", True, D0)
# D fuer Gegner B: zugelassen 100, Liga 95 -> +5, mal 6/16; P: Gesamtpunkte beider 190, Liga-Total 190 -> 0
check("D = (n/(n+10)) * (zugelassen - Liga)", near(ft[0], 6 / 16 * 5.0), ft)
check("P = Gesamtpunkte beider Teams minus Liga-Total", near(ft[1], 0.0))
check("H = 1 Heim, 0 Auswaerts", ft[2] == 1.0 and op.features(ts, "2023-24", "B", "A", False, D0)[2] == 0.0)
check("weniger als 5 Spiele -> None", op.features(ts, "2023-24", "A", "B", True, 20240104) is None)
check("andere Saison ohne Verlauf -> None", op.features(ts, "2024-25", "A", "B", True, D0) is None)

# Fit: e = 0.02 + 0.01 D - 0.005 P + 0.03 H exakt
rng = np.random.default_rng(3)
n = 600
X = np.column_stack([rng.normal(0, 3, n), rng.normal(0, 8, n), rng.integers(0, 2, n).astype(float)])
y = 0.02 + X @ np.array([0.01, -0.005, 0.03])
b = op.ols(X, y)
check("OLS findet Koeffizienten", np.allclose(b, [0.02, 0.01, -0.005, 0.03]))
bw = op.ols(X, y, np.ones(n) * 3)
check("gewichteter Fit mit gleichen Gewichten = ungewichtet", np.allclose(bw, b))
yn = y + rng.normal(0, 0.1, n)
gi = np.arange(n) // 3
ci = op.bootstrap_ci(X, yn, gi, 200, np.random.default_rng(5))
bn = op.ols(X, yn)
check("Bootstrap-Intervall enthaelt den Schaetzer, lo < hi", np.all(ci[0] < bn) and np.all(bn < ci[1]) and np.all(ci[0] < ci[1]))
check("nur a: Fit ohne Faktoren", np.allclose(op.ols(np.zeros((n, 0)), yn), [yn.mean()]))
# Korrektur
ep = np.array([10.0, 20.0])
Xc = np.array([[2.0, 0.0, 1.0], [0.0, 0.0, 0.0]])
bt = np.array([0.1, 0.01, 0.0, 0.05])
check("Korrektur = erwartete Punkte x (1 + Fit)", np.allclose(op.corrected(ep, Xc, bt), [10 * (1 + 0.1 + 0.02 + 0.05), 20 * 1.1]))
check("Korrektur ohne Faktoren", np.allclose(op.corrected(ep, np.zeros((2, 0)), np.array([0.1])), [11, 22]))
st = op.err_stats(np.array([10.0, 12.0]), np.array([12.0, 9.0]))
check("RMSE/Verzerrung", near(st["rmse"], np.sqrt(13 / 2)) and near(st["bias"], -0.5) and st["n"] == 2)
# Regel
d1 = op.decide_factor(True, True, {"Starter": 0, "Bank": 1})
d2 = op.decide_factor(True, True, {"Starter": 0, "Bank": 2})
d3 = op.decide_factor(False, True, {"Starter": 0})
d4 = op.decide_factor(True, False, {"Starter": 0})
check("Regel: erfuellt / Gruppe in 2 Saisons schlechter / Vorzeichen / Starter", d1["Regel"] and not d2["Regel"] and not d3["Regel"] and not d4["Regel"])
print("ALLES OK" if ok else "FEHLER"); sys.exit(0 if ok else 1)
