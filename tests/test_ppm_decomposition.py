"""Test fuer analysis/ppm_decomposition.py an einem kleinen kuenstlichen Beispiel (Verlauf nur vor dem Spieltag, Fenster, Zug zum Ligamittel, Fehlerkennzahlen, Gruppen, Parameterwahl, Regel). Ohne Netz.
Aufruf: venv/bin/python tests/test_ppm_decomposition.py"""
import os, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import ppm_decomposition as pd_

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
near = lambda a, b, t=1e-9: abs(a - b) < t

def row(pid, day, mins, fga, fgm, fg3m, fta, ftm, gid=None):
    return {"person_id": pid, "date": f"2024-01-{day:02d}", "game_id": gid or f"g{pid}{day}", "season": "2023-24", "minutes": mins, "fga": fga, "fgm": fgm, "fg3a": 0, "fg3m": fg3m, "fta": fta, "ftm": ftm,
            "points": 2 * fgm + fg3m + ftm}
# Spieler 1: drei Spiele; Spieler 2: ein Spiel; Spiel am 5. Tag = Prognosetag
rows = [row(1, 1, 30, 10, 5, 2, 4, 3), row(1, 2, 20, 6, 2, 0, 2, 2), row(1, 3, 10, 2, 1, 0, 0, 0), row(2, 1, 20, 8, 4, 1, 2, 1), row(1, 5, 30, 9, 4, 1, 3, 2)]
D5 = 20240105
h = pd_.History(rows)
a = h.player(1, D5, "alle")
# Summen vor Tag 5: min 60, fga 18, ptsfg = (2*5+2)+(2*2+0)+(2*1+0) = 12+4+2 = 18, fta 6, ftm 5, n 3
check("Verlauf nur vor dem Spieltag (Tag 5 nicht dabei)", list(a) == [60, 18, 18, 6, 5, 3], list(a))
check("Spieltag selbst ausgeschlossen (Tag 3 -> nur Tag 1 und 2)", h.player(1, D5 - 2, "alle")[5] == 2)
check("kein Verlauf -> Nullen", list(h.player(9, D5, "alle")) == [0] * 6 and h.player(1, D5 - 4, "alle")[5] == 0)
check("Fenster letzte 20 = alle bei < 20 Spielen", list(h.player(1, D5, "l20")) == list(a))
many = [row(7, d, 10, 1, 1, 0, 0, 0) for d in range(1, 29)] + [row(8, 1, 10, 1, 1, 0, 0, 0)]
hm = pd_.History(many)
check("letzte 20 Spiele", hm.player(7, D5 + 24, "l20")[5] == 20 and hm.player(7, D5 + 24, "alle")[5] == 28)
lg = h.league(D5)
check("Liga vor Tag 5", list(lg) == [60 + 20, 18 + 8, 18 + (2 * 4 + 1), 6 + 2, 5 + 1, 4], list(lg))

# Vorhersage ohne Zug (k=0, kmin=0): emin * (fga/min * ptsfg/fga + fta/min * ftm/fta)
emin = np.array([30.0])
p0 = pd_.predict(a[None, :], lg[None, :], emin, 0, 0)[0]
check("S0 = Minuten x (FGA/Min x Pkt/FGA + FTA/Min x Pkt/FTA)", near(p0, 30 * (18 / 60 * 18 / 18 + 6 / 60 * 5 / 6)), p0)
# mit Zug
k, km = 50, 100
Lfga, Lfta, Lpf, Lpt = lg[1] / lg[0], lg[3] / lg[0], lg[2] / lg[1], lg[4] / lg[3]
r_fga = (60 * (18 / 60) + km * Lfga) / (60 + km); r_fta = (60 * (6 / 60) + km * Lfta) / (60 + km)
pf_ = (18 * (18 / 18) + k * Lpf) / (18 + k); pt_ = (6 * (5 / 6) + k * Lpt) / (6 + k)
check("S mit Zug zum Ligamittel", near(pd_.predict(a[None, :], lg[None, :], emin, k, km)[0], 30 * (r_fga * pf_ + r_fta * pt_)))
check("starker Zug (grosses k, k_min) -> Ligamittel", abs(pd_.predict(a[None, :], lg[None, :], emin, 1e9, 1e9)[0] - 30 * (Lfga * Lpf + Lfta * Lpt)) < 1e-3)
# Spieler ohne Freiwurfversuche: Punkte/FTA = Ligamittel (k > 0)
z = np.array([[10.0, 2, 2, 0, 0, 1]])
check("keine Versuche -> Ligawert, kein NaN", np.isfinite(pd_.predict(z, lg[None, :], emin, 50, 100)).all() and np.isfinite(pd_.predict(z, lg[None, :], emin, 0, 0)).all())

# Kennzahlen
st = pd_.err_stats(np.array([10.0, 12.0]), np.array([12.0, 9.0]))
check("MAE/RMSE/Verzerrung", near(st["mae"], 2.5) and near(st["rmse"], np.sqrt((4 + 9) / 2)) and near(st["bias"], -0.5) and st["n"] == 2)
gm = pd_.group_masks(np.array([1, 9, 10, 29, 30, 50]), np.array([20, 29, 20, 30, 28, 28.1]))
check("Gruppen", list(gm["1-9 Spiele"]) == [1, 1, 0, 0, 0, 0] and list(gm["10-29 Spiele"]) == [0, 0, 1, 1, 0, 0] and list(gm["ab 30 Spiele"]) == [0, 0, 0, 0, 1, 1] and list(gm["Starter"]) == [0, 1, 0, 1, 0, 1])

# Entscheidungsregel
def st_(r): return {"rmse": r}
res = {"R": {s: {"1-9 Spiele": st_(5.0), "ab 30 Spiele": st_(6.0)} for s in "abc"},
       "A": {s: {"1-9 Spiele": st_(4.9), "ab 30 Spiele": st_(6.0)} for s in "abc"},
       "B": {**{s: {"1-9 Spiele": st_(4.9), "ab 30 Spiele": st_(6.0)} for s in "ab"}, "c": {"1-9 Spiele": st_(5.0), "ab 30 Spiele": st_(6.0)}},
       "C": {s: {"1-9 Spiele": st_(4.0), "ab 30 Spiele": st_(6.01)} for s in "abc"}}
d = pd_.decide(res)
check("Regel: A erfuellt, B nicht (eine Saison gleich), C nicht (ab 30 schlechter)", d["A"]["Regel erfuellt"] and not d["B"]["Regel erfuellt"] and not d["C"]["Regel erfuellt"] and d["C"]["1-9 besser in allen Saisons"])

# Parameterwahl: kuenstliche Tabelle, Trainingssaison "a", ohne Verlaengerung
n = 40
rng = np.random.default_rng(1)
agg = np.tile(np.array([100.0, 40, 40, 10, 8, 5]), (n, 1)); lgm = np.tile(np.array([1000.0, 400, 400, 100, 80, 50]), (n, 1))
T = {"agg": {"alle": agg, "l20": agg}, "lg": lgm, "emin": np.full(n, 30.0), "season": np.array(["a"] * n), "ot": np.zeros(n, bool), "ngames": np.array([5] * 20 + [40] * 20),
     "act": rng.normal(10, 1, n)}
T["epts"] = T["act"] + 1.0
k, km, note = pd_.choose_params(T, ["a"], "alle")
check("Parameterwahl liefert Gitterwerte", k in pd_.KS and km in pd_.KMINS)
print("ALLES OK" if ok else "FEHLER"); sys.exit(0 if ok else 1)
