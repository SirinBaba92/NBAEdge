"""Test fuer analysis/backtest_ppm_hybrid.py an einem kleinen kuenstlichen Beispiel (Mittelwert nach H0 = S, Streuung, Kontrolle, Gruppe ab 10 identisch zu R, Kennzahlen, Regel). Ohne Netz.
Aufruf: venv/bin/python tests/test_ppm_hybrid.py"""
import os, sys
from pathlib import Path
import numpy as np
from scipy.special import ndtri
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import backtest_ppm_hybrid as hb

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
near = lambda a, b, t=1e-9: abs(a - b) < t

ppm = np.array([0.4, 0.5, 0.7]); w_p = np.array([0.2, 0.5, 0.3])
mk = np.clip(28 + 5 * ndtri((np.arange(9) + 0.5) / 9), 0, 48)
x, w = hb.mixture(ppm, w_p, mk)
er = float((w * x).sum())
check("Gewichte summieren zu 1, 27 Punktewerte", near(w.sum(), 1.0) and len(x) == 27)

# H0: Mittelwert genau S, Verhaeltnis der Streuung zum Mittelwert gleich
S = 11.0
x0 = hb.transform(x, w, "H", S, 1.0)
sd = lambda v: float(np.sqrt((w * (v - (w * v).sum()) ** 2).sum()))
check("H0: Mittelwert = S", near(float((w * x0).sum()), S))
check("H0: Variationskoeffizient wie R", near(sd(x0) / S, sd(x) / er))
# H1: Spreizung um S, Mittelwert S (ohne Begrenzung wirksam), Streuung w-fach
x1 = hb.transform(x, w, "H", S, 1.4)
check("H1: Mittelwert bleibt S (keine Begrenzung noetig)", x1.min() > 0 and near(float((w * x1).sum()), S, 1e-9))
check("H1: Streuung = 1,4-fach", near(sd(x1), 1.4 * sd(x0), 1e-9))
# Kontrolle: Mittelwert wie R, Streuung w-fach
xc = hb.transform(x, w, "C", S, 1.4)
check("Kontrolle: Mittelwert = E_R, Streuung 1,4-fach", near(float((w * xc).sum()), er, 1e-9) and near(sd(xc), 1.4 * sd(x), 1e-9))
# Begrenzung bei 0
xs = hb.transform(np.array([0.0, 10.0]), np.array([0.5, 0.5]), "H", 5.0, 1.6)
check("Begrenzung bei 0", xs.min() >= 0)
# unbrauchbares S -> wie R
check("S = NaN -> R", np.array_equal(hb.transform(x, w, "H", float("nan"), 1.4), x))

# Gruppe ab 10 Spielen: identisch zu R, auch bei anderem S und w
pR, eR = hb.variant_probs(ppm, w_p, mk, 25, "R", np.nan, 1.0)
for mode, s, spr in (("H", 7.0, 1.0), ("H", 7.0, 1.6), ("C", np.nan, 1.4)):
    p_, e_ = hb.variant_probs(ppm, w_p, mk, 12, mode, s, spr)
    check(f"ab 10 Spiele identisch zu R ({mode}, w={spr})", np.array_equal(p_, pR) and e_ == eR)
pH, eH = hb.variant_probs(ppm, w_p, mk, 5, "H", S, 1.0)
check("Gruppe 1-9: H0 weicht von R ab, erwartete Punkte = S", not np.allclose(pH, pR) and near(eH, S))
check("Chancen nicht steigend, in [0,1]", np.all(np.diff(pH) <= 1e-12) and pH.min() >= 0 and pH.max() <= 1)
# R-Rechenweg = be.milestone_probs (Stufe-1-Experiment)
from analysis import backtest_minutes_empirical as be
check("R = Chancenrechnung aus backtest_minutes_empirical", np.allclose(pR, be.milestone_probs(ppm, w_p, mk, hb.KS_ALL)))

# Kennzahlen und Regel
p = np.array([0.9, 0.85, 0.2, 0.95]); h = np.array([1.0, 0.0, 0.0, 1.0])
m = hb.metrics(p, h)
check("Brier/Log-Loss/Verzerrung", near(m["brier"], np.mean((p - h) ** 2)) and near(m["bias"], p.mean() - h.mean()) and near(m["ll"], -np.mean([np.log(.9), np.log(.15), np.log(.8), np.log(.95)])))
c = hb.calibration(p, h, 0.80)
check("Kalibrierung ab 80 %: 3 Zeilen", c[0] == 3 and near(c[1], (0.9 + 0.85 + 0.95) / 3) and near(c[2], 2 / 3))
check("Luecke ab 80 %", near(hb.gap80(p, h), abs((0.9 + 0.85 + 0.95) / 3 - 2 / 3)))
mk_ = lambda b, l, g: {"brier": b, "ll": l, "gap80": g}
per = {"R": {s: mk_(0.2, 0.6, 0.05) for s in "abc"},
       "A": {s: mk_(0.19, 0.58, 0.03) for s in "abc"},
       "B": {**{s: mk_(0.19, 0.58, 0.03) for s in "ab"}, "c": mk_(0.19, 0.58, 0.06)},
       "C": {**{s: mk_(0.19, 0.58, 0.03) for s in "ab"}, "c": mk_(0.19, 0.61, 0.03)}}
d = hb.decide(per)
check("Regel: A ja; B nein (Luecke); C nein (Log-Loss)", d["A"]["Regel"] and not d["B"]["Regel"] and not d["C"]["Regel"] and d["B"]["LL"] and not d["C"]["LL"])
print("ALLES OK" if ok else "FEHLER"); sys.exit(0 if ok else 1)
