"""Test fuer analysis/backtest_minutes_empirical.py an einem kleinen kuenstlichen Beispiel (die 9 Quantile, Begrenzung 0..48, Mittel, Chancen, Kennzahlen). Ohne Netz.
Aufruf: venv/bin/python tests/test_minutes_empirical.py"""
import os, sys
from pathlib import Path
import numpy as np
from scipy.special import ndtri
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import backtest_minutes_empirical as be
from engine import player_forecast as pf

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

err = np.arange(-18, 10, dtype=float)                       # 28 Fehler -18..9
off = be.quantile_offsets(err)
q = np.quantile(err, (np.arange(9) + 0.5) / 9)
check("9 Punkte", len(off) == 9)
check("Quantile entsprechen (i-0,5)/9", np.allclose(off + q.mean(), q))
check("Mittel der Verschiebungen = 0", abs(off.mean()) < 1e-12)
check("aufsteigend", np.all(np.diff(off) > 0))
sk = be.quantile_offsets(np.concatenate([np.linspace(-1, 4, 90), np.linspace(-20, -6, 10)]))   # linker Schwanz
check("schief: mittlerer Punkt ueber dem Mittel, linker Punkt weiter weg als rechter", sk[4] > 0 and abs(sk[0]) > abs(sk[8]), str(sk.round(2)))
pts = be.minute_points(40.0, off)
check("Mittel der Punkte = mu ohne Begrenzung", abs(be.minute_points(30.0, off).mean() - 30.0) < 1e-12)
check("Begrenzung 0..48", be.minute_points(47.0, np.array([-60, 0, 5.0] + [0] * 6)).max() <= 48 and be.minute_points(3.0, np.array([-60.0] + [0] * 8)).min() == 0.0 and pts.max() <= 48)
no = be.normal_offsets(err)
check("Normal-Kontrolle symmetrisch mit gleicher Streuung", np.allclose(no, -no[::-1]) and abs(no[8] - np.std(err, ddof=1) * ndtri(8.5 / 9)) < 1e-12)

# Chancen: gleiche Punkte wie das Produktivmodell (Normal-Variante) -> Funktion stimmt mit forecast_player-Formel ueberein
ppm = np.array([0.5, 0.6]); w = np.array([0.4, 0.6])
mk = np.clip(30 + 4.0 * ndtri((np.arange(9) + 0.5) / 9), 0, 48)
p = be.milestone_probs(ppm, w, mk, np.arange(1, 61))
x = (ppm[:, None] * mk[None, :]).ravel(); ww = (w[:, None] * np.full(9, 1 / 9)[None, :]).ravel()
check("Chancen nicht steigend, in [0,1]", np.all(np.diff(p) <= 1e-12) and p.min() >= 0 and p.max() <= 1)
from scipy.special import ndtr
ref = np.array([(ww * (1 - ndtr((n - 0.5 - x) / (1 + 0.05 * x)))).sum() for n in range(1, 61)])
check("Chancen = Formel", np.allclose(p, np.minimum.accumulate(ref)))
# E mit Fehler 0 entspricht Minuten ohne Streuung: alle 9 Punkte = mu
p0 = be.milestone_probs(ppm, w, be.minute_points(30.0, be.quantile_offsets(np.zeros(50))), np.arange(1, 61))
check("Fehler alle 0 -> alle Minutenpunkte = mu", np.allclose(be.minute_points(30.0, be.quantile_offsets(np.zeros(50))), 30.0))
check("Erwartung der Punkte bleibt (Mittel der Minuten gleich)", abs(float(((ppm[:, None] * be.minute_points(30.0, off)[None, :]).ravel() * (w[:, None] * np.full(9, 1 / 9)[None, :]).ravel()).sum()) - float((ppm * w).sum() * 30.0)) < 1e-9)

# Kennzahlen
pp = np.array([0.9, 0.1, 0.5, 0.8]); hh = np.array([1.0, 0.0, 1.0, 0.0])
m = be.metrics(pp, hh)
check("Brier", abs(m["brier"] - np.mean((pp - hh) ** 2)) < 1e-12)
check("Log-Loss", abs(m["ll"] - (-np.mean([np.log(0.9), np.log(0.9), np.log(0.5), np.log(0.2)]))) < 1e-12)
check("Verzerrung", abs(m["bias"] - (pp.mean() - hh.mean())) < 1e-12)
c = be.calibration(pp, hh, 0.5)
check("Kalibrierung ab 50 %: 3 Zeilen", c[0] == 3 and abs(c[1] - (0.9 + 0.5 + 0.8) / 3) < 1e-12 and abs(c[2] - 2 / 3) < 1e-12, c)
print("ALLES OK" if ok else "FEHLER"); sys.exit(0 if ok else 1)
