"""
Ist die Verzerrung des Spread-Modells fuer Heimteam-Aussenseiter (2025-26: Fehler -1,35 Punkte, Deckungs-Chance zu hoch) auch in frueheren Saisons da?
NUR LESEND: data/cache, schreibt nur analysis/reports/spread_seasons.txt. Keine API-Calls, am Produktivmodell wird nichts geaendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_spread_seasons.py

Aufbau wie analysis/backtest_spread.py (gleiche Definitionen): Replay analysis/replica_tunable.run ueber games_2015..2025 (Produktivparameter), je Saison 2017 bis 2025 (2025 = 2025-26) nur Regular Season,
reines Modell ohne Markt. Modell-Spread mu = Elo-Differenz / 50 auf 0,1 gerundet (positiv = Heim staerker); Fehler = Ist-Spread minus mu.
Heimteam-Favorit: mu > 0, Heimteam-Aussenseiter: mu < 0 (mu = 0 gehoert zu keiner der beiden Gruppen). Hälften je Saison chronologisch (Datum, ID).
Deckungs-Chance Heim fuer Linien L = mu + k, k = -5..+5, p = 1 - Phi((L - mu) / 13,2); Pushes (Marge genau auf der Linie) ausgenommen. Kalibrierung: Abweichung = Trefferquote minus Modell in PP
(vorzeichenbehaftet, ueber alle Zeilen; dazu Ø-Betrag ueber 5-%-Stufen mit >= 20 Zeilen, gewichtet), Rekalibrierung logit P(deckt) = a + b logit(p) mit Intervall (Bootstrap nach Spielen).
Intervalle 95 %: Bootstrap nach Spielen, 2000 Ziehungen (Rekalibrierung 500 bzw. 1000 beim Gesamtbild).
Entscheidungsregel: Echter Modellfehler nur, wenn das Vorzeichen des Aussenseiter-Fehlers in mindestens 6 von 9 Saisons wie in 2025-26 (negativ) ist UND das Intervall ueber alle Saisons die 0 nicht einschliesst.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy.special import ndtr

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from bt_common import load_games  # noqa: E402
import replica_tunable as rt  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402

OUT = HERE / "reports" / "spread_seasons.txt"
SIG = lp.SPREAD_SIGMA
B = 2000
KS = np.arange(-5, 6)
SEASONS = list(range(2017, 2026))
EDGES = np.round(np.arange(0, 1.0001, 0.05), 2)

games = load_games(2015, 2025)
rows, _, _, _ = rt.run(games, K=20.0, hca=100.0, mov="cur")
RS = rows["post"] == 0
sea_all = rows["season"]
mu_all = np.round(rows["diff"] / 50.0, 1)
mg_all = rows["margin"]


def label(s):
    return f"{s}-{str(s + 1)[-2:]}"


def boot_mean(v, seed, b=B):
    v = np.asarray(v, float)
    if len(v) < 2:
        return (float(v.mean()) if len(v) else float("nan"), float("nan"), float("nan"))
    idx = np.random.default_rng(seed).integers(0, len(v), (b, len(v)))
    m = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def fmt(t, d=2):
    return f"{t[0]:+.{d}f} [{t[1]:+.{d}f}; {t[2]:+.{d}f}]"


def fit_w(z, y, w, iters=40):
    X = np.column_stack([np.ones_like(z), z]); beta = np.array([0.0, 1.0])
    for _ in range(iters):
        m = 1 / (1 + np.exp(-X @ beta)); Wt = np.clip(m * (1 - m), 1e-9, None) * w
        step = np.linalg.solve(X.T @ (X * Wt[:, None]) + 1e-9 * np.eye(2), X.T @ (w * (y - m)))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


def calib(mu, mg, seed, bc):
    """Kalibrierung der Deckungs-Chance (Linien A) fuer eine Spielgruppe: (n Zeilen, vorzeichenbeh. Abweichung PP, Ø-Betrag ueber Stufen PP, a, b, CI a, CI b)."""
    n = len(mu)
    L = mu[:, None] + KS[None, :]
    p = 1.0 - ndtr((L - mu[:, None]) / SIG)
    y = (mg[:, None] > L + 1e-9).astype(float)
    ok = np.abs(mg[:, None] - L) >= 1e-9
    gi, ki = np.nonzero(ok)
    pv, yv = p[gi, ki], y[gi, ki]
    z = np.log(np.clip(pv, 1e-6, 1 - 1e-6) / (1 - np.clip(pv, 1e-6, 1 - 1e-6)))
    signed = (yv.mean() - pv.mean()) * 100
    bins = np.clip(np.digitize(pv, EDGES[1:-1]), 0, len(EDGES) - 2)
    devs, ws = [], []
    for j in range(len(EDGES) - 1):
        m = bins == j
        if m.sum() >= 20:
            devs.append(abs(yv[m].mean() - pv[m].mean()) * 100); ws.append(m.sum())
    mad = float(np.average(devs, weights=ws)) if devs else float("nan")
    base = fit_w(z, yv, np.ones(len(yv)))
    r = np.random.default_rng(seed)
    bs = []
    for _ in range(bc):
        wg = np.bincount(r.integers(0, n, n), minlength=n).astype(float)
        bs.append(fit_w(z, yv, wg[gi]))
    bs = np.array(bs)
    return len(yv), signed, mad, base[0], base[1], np.percentile(bs[:, 0], [2.5, 97.5]), np.percentile(bs[:, 1], [2.5, 97.5])


W = []
P = W.append
P("SPREAD: AUSSENSEITER-FEHLER IN FRUEHEREN SAISONS (2017 bis 2025-26, Regular Season, reines Modell, walk-forward)")
P("Messskript analysis/backtest_spread_seasons.py (liest nur, aufbauend auf analysis/backtest_spread.py). Fehler = Ist-Spread minus Modell-Spread (Heim-Sicht). Negativ beim Aussenseiter = Heimteam-Aussenseiter schneidet schlechter ab als das Modell denkt.")
P("")

per = {}
masks = {}
for s in SEASONS:
    m = RS & (sea_all == s)
    mu, mg = mu_all[m], mg_all[m]
    n = len(mu)
    half = np.arange(n) < n // 2
    per[s] = dict(mu=mu, mg=mg, err=mg - mu, half=half, n=n)

# ============================================================ 1 und 2
P("1 FEHLER JE SAISON (Mittelwert Punkte [95 %]) UND VORZEICHEN")
P(f"  {'Saison':8s} {'n':>5s} | {'Heimteam Favorit: n':>19s} {'Fehler':>24s} | {'Heimteam Aussenseiter: n':>24s} {'Fehler':>24s} Vorz.")
dog_signs = {}
for s in SEASONS:
    d = per[s]; e, mu = d["err"], d["mu"]
    fv, dg = mu > 0, mu < 0
    tf = boot_mean(e[fv], 1000 + s); td = boot_mean(e[dg], 2000 + s)
    dog_signs[s] = np.sign(td[0])
    P(f"  {label(s):8s} {d['n']:5d} | {fv.sum():19d} {fmt(tf):>24s} | {dg.sum():24d} {fmt(td):>24s}  {'-' if td[0] < 0 else '+'}")
allmu = np.concatenate([per[s]["mu"] for s in SEASONS]); allerr = np.concatenate([per[s]["err"] for s in SEASONS]); allmg = np.concatenate([per[s]["mg"] for s in SEASONS])
fv, dg = allmu > 0, allmu < 0
tf, td = boot_mean(allerr[fv], 11), boot_mean(allerr[dg], 12)
P(f"  {'alle':8s} {len(allmu):5d} | {fv.sum():19d} {fmt(tf):>24s} | {dg.sum():24d} {fmt(td):>24s}  {'-' if td[0] < 0 else '+'}")
P("")
P("2 FEHLER JE HAELFTE DER SAISON (Mittelwert Punkte [95 %])")
P(f"  {'Saison':8s} {'Haelfte':>7s} | {'Favorit n':>9s} {'Fehler':>24s} | {'Aussenseiter n':>14s} {'Fehler':>24s}")
hs_neg = 0
for s in SEASONS:
    d = per[s]; e, mu, h = d["err"], d["mu"], d["half"]
    for nm, hm in (("1", h), ("2", ~h)):
        fv_, dg_ = (mu > 0) & hm, (mu < 0) & hm
        tf_, td_ = boot_mean(e[fv_], 3000 + s * 10 + int(nm)), boot_mean(e[dg_], 4000 + s * 10 + int(nm))
        hs_neg += td_[0] < 0
        P(f"  {label(s):8s} {nm:>7s} | {fv_.sum():9d} {fmt(tf_):>24s} | {dg_.sum():14d} {fmt(td_):>24s}")
P(f"  Aussenseiter-Fehler negativ in {hs_neg} von {2 * len(SEASONS)} Halbsaisons.")
P("")

# ============================================================ 3 Kalibrierung
P("3 KALIBRIERUNG DER DECKUNGS-CHANCE (Linien mu + k, k = -5..+5, ohne Pushes; Abw. = Trefferquote minus Modell in PP; a, b der Rekalibrierung mit 95 %-Intervall)")
P(f"  {'Gruppe':26s} {'Zeilen':>7s} {'Abw. PP':>8s} {'Ø|Stufe| PP':>11s} {'a (Achsenabschnitt)':>26s} {'b (Steigung)':>22s}")
cal_dog = {}
for s in SEASONS:
    d = per[s]
    for nm, gm in (("Favorit", d["mu"] > 0), ("Aussenseiter", d["mu"] < 0)):
        n_, sg, mad, a, b, ca, cb = calib(d["mu"][gm], d["mg"][gm], 5000 + s + (7 if nm == "Aussenseiter" else 0), 500)
        if nm == "Aussenseiter":
            cal_dog[s] = (sg, a, ca)
        P(f"  {label(s) + ' ' + nm:26s} {n_:7d} {sg:+8.2f} {mad:11.2f} {a:+8.3f} [{ca[0]:+.3f}; {ca[1]:+.3f}] {b:6.2f} [{cb[0]:.2f}; {cb[1]:.2f}]")
for nm, gm in (("Favorit", allmu > 0), ("Aussenseiter", allmu < 0)):
    n_, sg, mad, a, b, ca, cb = calib(allmu[gm], allmg[gm], 6000 + (7 if nm == "Aussenseiter" else 0), 1000)
    P(f"  {'alle Saisons ' + nm:26s} {n_:7d} {sg:+8.2f} {mad:11.2f} {a:+8.3f} [{ca[0]:+.3f}; {ca[1]:+.3f}] {b:6.2f} [{cb[0]:.2f}; {cb[1]:.2f}]")
P("")

# ============================================================ 4 Zusammenfassung
P("4 ZUSAMMENFASSUNG")
neg = sum(1 for s in SEASONS if dog_signs[s] < 0)
P(f"  Vorzeichen des Aussenseiter-Fehlers wie 2025-26 (negativ): {neg} von {len(SEASONS)} Saisons (" + ", ".join(f"{label(s)} {'-' if dog_signs[s] < 0 else '+'}" for s in SEASONS) + ").")
P(f"  Ueber alle Saisons: Aussenseiter-Fehler {fmt(td)} Punkte (n {dg.sum()}), Favorit {fmt(tf)} (n {fv.sum()}). Ohne 2025-26: " + fmt(boot_mean(np.concatenate([per[s]['err'][per[s]['mu'] < 0] for s in SEASONS[:-1]]), 13)) + " (Aussenseiter), " + fmt(boot_mean(np.concatenate([per[s]['err'][per[s]['mu'] > 0] for s in SEASONS[:-1]]), 14)) + " (Favorit).")
P("  Zusammenhang Fehler und Modell-Spread (OLS, Punkte Fehler je Punkt Modell-Spread; Bootstrap nach Spielen):")
nz = allmu != 0
rngb = np.random.default_rng(15)


def ols(mu_, e_, kind):
    if kind == "linear":
        X = np.column_stack([np.ones(len(mu_)), mu_])
    else:
        X = np.column_stack([np.ones(len(mu_)), np.minimum(mu_, 0), np.maximum(mu_, 0)])
    return np.linalg.lstsq(X, e_, rcond=None)[0]


for kind, names in (("linear", ["Achsenabschnitt", "Steigung"]), ("zwei", ["Achsenabschnitt", "Steigung Aussenseiter-Seite (mu<0)", "Steigung Favoriten-Seite (mu>0)"])):
    base = ols(allmu[nz], allerr[nz], kind)
    nn = nz.sum(); bs = []
    for _ in range(1000):
        i = rngb.integers(0, nn, nn)
        bs.append(ols(allmu[nz][i], allerr[nz][i], kind))
    bs = np.array(bs)
    P("    " + ("eine Gerade (alle Saisons): " if kind == "linear" else "zwei Steigungen (Knick bei 0): ") + "; ".join(f"{nm} {base[j]:+.3f} [{np.percentile(bs[:, j], 2.5):+.3f}; {np.percentile(bs[:, j], 97.5):+.3f}]" for j, nm in enumerate(names)))
sl = []
for s in SEASONS:
    d = per[s]; k = d["mu"] != 0
    sl.append(ols(d["mu"][k], d["err"][k], "linear")[1])
P("    Steigung je Saison: " + ", ".join(f"{label(s)} {v:+.3f}" for s, v in zip(SEASONS, sl)) + f"  (negativ in {sum(v < 0 for v in sl)} von {len(sl)})")
P("  Fehler nach Modell-Spread-Klassen (alle Saisons, Punkte [95 %]):")
cl = [(-99, -8), (-8, -4), (-4, 0), (0, 4), (4, 8), (8, 99)]
for lo, hi in cl:
    m = (allmu > lo) & (allmu < hi) if lo != -4 else (allmu >= lo) & (allmu < hi)
    m = (allmu > lo) & (allmu <= hi) if hi > 0 and lo >= 0 else ((allmu >= lo) & (allmu < hi) if hi <= 0 else m)
    P(f"    Modell-Spread {('<' + str(hi)) if lo == -99 else ('>=' + str(lo)) if hi == 99 else (str(lo) + ' bis ' + str(hi))}: n {m.sum():5d}, Fehler {fmt(boot_mean(allerr[m], 20 + hi))}")
P("")
cond_sign = neg >= 6
cond_ci = td[2] < 0
P("ENTSCHEIDUNG (Regel: Vorzeichen in >= 6 von 9 Saisons wie 2025-26 UND Intervall ueber alle Saisons ohne 0)")
P(f"  Vorzeichen: {neg} von 9 -> {'erfuellt' if cond_sign else 'NICHT erfuellt'}; Intervall alle Saisons {fmt(td)} -> {'schliesst 0 aus' if cond_ci else 'schliesst 0 ein'}.")
P(f"  => {'ECHTER MODELLFEHLER' if cond_sign and cond_ci else 'kein echter Modellfehler: gilt als Zufall dieser Saison'}.")
OUT.write_text("\n".join(W) + "\n", encoding="utf-8")
print("\n".join(W))
