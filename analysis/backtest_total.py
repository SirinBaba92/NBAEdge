"""
Ist-Stand des Total-Modells (Gesamtpunkte), Regular Season 2025-26. NUR LESEND: data/cache, schreibt nur analysis/reports/total_2025-26.txt. Keine API-Calls, am Produktivmodell wird nichts geaendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_total.py

Replay: analysis/replica_tunable.run (Produktivparameter K 20, Heimvorteil 100, MoV heute, total_alpha 0,1), walk-forward ueber alle Spiele ab 2015, Auswertung nur 2025-26 Regular Season.
Reines Modell ohne Markt-Mischung, nur echte Ergebnisse. Modell-Total mu = total_pred (Off/Def-EMA, auf 0,1 gerundet), Fehler = Ist-Total (inkl. Verlaengerung) minus mu.
Over-Chance fuer Linie L: p = 1 - Phi((L - mu) / sigma), Ereignis Total > L (wie engine/line_probabilities.over_under_rows). Linien A: L = mu + k, k = -5..+5 (k = 0 Hauptlinie; k < 0 darunter = Over wahrscheinlicher;
k > 0 darueber zur Kontrolle); Linien B: ganzzahlig L = Runde(mu) + k. Push (Total genau auf der Linie) = eigenes Ergebnis, aus Trefferquote und Kalibrierung herausgenommen.
Verlaengerung (OT): BallDontLie-Feld period > 4 bzw. home_ot1 gesetzt. Intervalle 95 %: Bootstrap nach Spielen (2000 Ziehungen; Kalibrierung/Rekalibrierung 1000).
Maßstab: Ø-Abweichung ueber 5-%-Stufen (gewichtet, Stufen >= 20 Zeilen) unter ca. 3 PP und keine Stufe mit >= 100 Zeilen mehr als ca. 6 PP daneben; Stufen unter 20 Zeilen nicht aussagekraeftig.
Ausfaelle (Punkt 6): Mass wie analysis/backtest_winner_injuries.py (absences(): Stammspieler = Top 8 nach Minuten, Ausfall-Anteil an Teampunkten bzw. Minuten/240), hier SUMME beider Teams.
Wer fehlte, ist Wissen aus der Zukunft: Ergebnisse sind eine OBERGRENZE.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy.special import ndtr
from scipy.stats import kurtosis, skew

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from bt_common import load_games  # noqa: E402
import replica_tunable as rt  # noqa: E402
import backtest_winner_injuries as inj  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402

OUT = HERE / "reports" / "total_2025-26.txt"
SIG, SIG_T = lp.TOTAL_SIGMA, lp.TEAM_TOTAL_SIGMA
B, BC = 2000, 1000
KS = np.arange(-5, 6)
GRID = [round(15.0 + 0.5 * i, 1) for i in range(13)]
FIRST_N = 15
EDGES = np.round(np.arange(0, 1.0001, 0.05), 2)

games = load_games(2015, 2025)
rows, _, _, _ = rt.run(games, K=20.0, hca=100.0, mov="cur")
keep = (rows["season"] == 2025) & (rows["post"] == 0)
ix = np.where(keep)[0]
mu = np.round(rows["total_pred"][keep], 1)
tot = rows["total"][keep]
spread = np.round(rows["diff"][keep] / 50.0, 1)
margin = rows["margin"][keep]
gh, ga = rows["gp_h"][keep], rows["gp_a"][keep]
ot = np.array([bool((games[i].get("period") or 4) > 4 or games[i].get("home_ot1") is not None) for i in ix])
n = len(mu)
err = tot - mu
first = (gh < FIRST_N) & (ga < FIRST_N)
h1 = np.arange(n) < n // 2
h2 = ~h1
ALL = np.ones(n, bool)


def fmt(t, d=2, s=True):
    return (f"{t[0]:+.{d}f} [{t[1]:+.{d}f}; {t[2]:+.{d}f}]" if s else f"{t[0]:.{d}f} [{t[1]:.{d}f}; {t[2]:.{d}f}]")


def boot_stat(fn, mask, seed, b=B):
    idx = np.where(mask)[0]
    if len(idx) < 3:
        return (float("nan"),) * 3
    draws = np.random.default_rng(seed).integers(0, len(idx), (b, len(idx)))
    vals = np.array([fn(idx[d]) for d in draws])
    return float(fn(idx)), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def pair_boot(d, seed):
    idx = np.random.default_rng(seed).integers(0, len(d), (B, len(d)))
    return float(d.mean()), *np.percentile(d[idx].mean(axis=1), [2.5, 97.5])


# ---- Linien, Ergebnisse, Wahrscheinlichkeiten
LA, LB = mu[:, None] + KS[None, :], np.rint(mu)[:, None] + KS[None, :]


def outcome(L):
    y = np.where(tot[:, None] > L + 1e-9, 1.0, 0.0)
    push = np.abs(tot[:, None] - L) < 1e-9
    y[push] = np.nan
    return y, push


def prob(L, sigma=SIG):
    return 1.0 - ndtr((L - mu[:, None]) / sigma)


YA, PUA = outcome(LA)
YB, PUB = outcome(LB)

W = []
P = W.append
P("TOTAL-MODELL: IST-STAND (Gesamtpunkte, Regular Season 2025-26, reines Modell, walk-forward)")
P(f"Messskript analysis/backtest_total.py (liest nur). Replay analysis/replica_tunable.run; Spiele {n}, davon Verlaengerung {int(ot.sum())} ({100*ot.mean():.1f} %), erste {FIRST_N} Teamspiele {int(first.sum())}.")
P(f"Sigma im Code: TOTAL_SIGMA = {SIG}, TEAM_TOTAL_SIGMA = {SIG_T} (engine/line_probabilities.py Z. 27/28, sigmas_version 2). Sigma 18,6 ist das Log-Loss-Minimum aus analysis/sigma_check.py (2017-25: 18,6 [18,2; 19,0]); Team Total 11,6 [11,4; 11,8] separat bestimmt.")
rho_code = SIG ** 2 / (2 * SIG_T ** 2) - 1
P(f"Passen beide zusammen? Bei unabhaengigen Fehlern: {SIG_T} x Wurzel 2 = {SIG_T*np.sqrt(2):.1f}. Der Code hat {SIG}; das entspricht einer Korrelation der Team-Fehler von rho = {rho_code:.2f} (18,6^2 = 2 x 11,6^2 x (1 + rho)). Gemessen siehe 2c.")
P("")

# ================================================================== 1 Genauigkeit
P("1 GENAUIGKEIT (Fehler = Ist-Total minus Modell-Total; + = es fiel mehr als das Modell denkt)")
P(f"  {'Gruppe':36s} {'n':>5s}  {'Mittelwert (Bias) Pkt [95 %]':>30s}  {'mittlerer Betrag Pkt [95 %]':>30s}")
groups = [("alle", ALL), ("Modell-Total unter 220", mu < 220), ("Modell-Total 220 bis 235", (mu >= 220) & (mu < 235)), ("Modell-Total ab 235", mu >= 235),
          ("mit Verlaengerung", ot), ("ohne Verlaengerung", ~ot), (f"erste {FIRST_N} Teamspiele", first), ("Rest der Saison", ~first), ("Haelfte 1", h1), ("Haelfte 2", h2)]
for i, (nm, mk) in enumerate(groups):
    m = boot_stat(lambda ix_: err[ix_].mean(), mk, 10 + i)
    a = boot_stat(lambda ix_: np.abs(err[ix_]).mean(), mk, 40 + i)
    P(f"  {nm:36s} {mk.sum():5d}  {fmt(m):>30s}  {fmt(a, s=False):>30s}")
P(f"  Ø Modell-Total {mu.mean():.2f}, Ø Ist-Total {tot.mean():.2f}; Ø Ist-Total ohne Verlaengerung {tot[~ot].mean():.2f}, mit {tot[ot].mean():.2f}.")
P("")

# ================================================================== 2 Sigma
P("2 SIGMA")
P("2a Streuung des Fehlers gegen das Sigma im Code")
P(f"  {'Gruppe':36s} {'Std. des Fehlers [95 %]':>26s}  {'Std. aus MAD':>12s}")
for i, (nm, mk) in enumerate(groups):
    s = boot_stat(lambda ix_: err[ix_].std(ddof=1), mk, 70 + i, b=1000)
    mad = 1.4826 * np.median(np.abs(err[mk] - np.median(err[mk])))
    P(f"  {nm:36s} {fmt(s, s=False):>26s}  {mad:12.2f}")
P(f"  Sigma im Code: {SIG}.")
P("")
# 2c Team-Total-Fehler
mu_h, mu_a = (mu + spread) / 2, (mu - spread) / 2
# Heim-/Gastpunkte
hp = (tot + margin) / 2
ap = (tot - margin) / 2
eh, ea = hp - mu_h, ap - mu_a
rho = float(np.corrcoef(eh, ea)[0, 1])
rb = boot_stat(lambda ix_: np.corrcoef(eh[ix_], ea[ix_])[0, 1], ALL, 90, b=1000)
sh, sa = eh.std(ddof=1), ea.std(ddof=1)
implied = float(np.sqrt(sh ** 2 + sa ** 2 + 2 * rho * sh * sa))
P("2c TEAM-TOTAL-FEHLER UND DER ZUSAMMENHANG MIT DEM TOTAL (Team-Mittel = (Total +- Spread) / 2 wie in der App)")
P(f"  Std. Fehler Heim-Team-Total {sh:.2f}, Gast {sa:.2f} (Code: {SIG_T}); Korrelation der beiden Fehler rho = {rb[0]:.2f} [{rb[1]:.2f}; {rb[2]:.2f}] (unabhaengig waere 0).")
P(f"  Daraus Std. des Totals = Wurzel(sh^2 + sa^2 + 2 rho sh sa) = {implied:.2f}; gemessen {err.std(ddof=1):.2f}; Code {SIG}. Ohne Verlaengerung: Team-Std {eh[~ot].std(ddof=1):.2f}/{ea[~ot].std(ddof=1):.2f}, rho {np.corrcoef(eh[~ot], ea[~ot])[0,1]:.2f}, Total-Std {err[~ot].std(ddof=1):.2f}.")
P(f"  Unabhaengig (rho = 0) waeren {np.sqrt(sh**2+sa**2):.1f}; die positive Korrelation (gemeinsames Tempo, Verlaengerung) erklaert den Abstand zu 16,4.")
P("")

# 2b Sigma-Test
def brier_game(sigma):
    p = prob(LA, sigma)
    ok = ~np.isnan(YA)
    se = np.where(ok, (p - np.nan_to_num(YA)) ** 2, 0.0)
    return se.sum(axis=1) / np.maximum(ok.sum(axis=1), 1)


P("2b SIGMA-TEST (Brier der Over-Chance ueber die Linien A, k = -5..+5; Mittel je Spiel)")
bg = {s: brier_game(s) for s in GRID + [SIG]}
P(f"  {'Sigma':>6s} {'Brier ganze Saison':>19s} {'Haelfte 1':>10s} {'Haelfte 2':>10s}")
for s in GRID:
    P(f"  {s:6.1f} {bg[s].mean():19.5f} {bg[s][h1].mean():10.5f} {bg[s][h2].mean():10.5f}")
P(f"  {SIG:6.1f} {bg[SIG].mean():19.5f} {bg[SIG][h1].mean():10.5f} {bg[SIG][h2].mean():10.5f}   <- Code")
best_all = min(GRID, key=lambda s: bg[s].mean())
P(f"  Bestes Sigma der Gitterwerte (ganze Saison): {best_all} (Brier {bg[best_all].mean():.5f}); Code 18,6: {bg[SIG].mean():.5f}")
res_ok = []
for nm, tr, te, sd in (("einstellen auf Haelfte 1, pruefen auf Haelfte 2", h1, h2, 100), ("einstellen auf Haelfte 2, pruefen auf Haelfte 1", h2, h1, 101)):
    sb = min(GRID, key=lambda s: bg[s][tr].mean())
    m, lo, hi = pair_boot(bg[sb][te] - bg[SIG][te], sd)
    res_ok.append(m < 0)
    P(f"  {nm}: bestes Sigma {sb}; Pruefhaelfte Brier-Differenz (neu minus 18,6) {m*1000:+.3f} x10^-3 [{lo*1000:+.3f}; {hi*1000:+.3f}] -> {'besser' if m < 0 else 'nicht besser'}{' (Intervall ohne 0)' if m < 0 and hi < 0 else ''}")
P(f"  => Ein neues Sigma zaehlt nur, wenn es auf BEIDEN Pruefhaelften besser ist: {'JA' if all(res_ok) else 'NEIN, das heutige 18,6 bleibt'}")
P("")

# ================================================================== 3 Verteilung
P("3 VERTEILUNG DES FEHLERS")
z_ = (err - err.mean())
sk = boot_stat(lambda ix_: skew(err[ix_]), ALL, 110, b=1000)
ku = boot_stat(lambda ix_: kurtosis(err[ix_]), ALL, 111, b=1000)
P(f"  Schiefe {fmt(sk)} (Normal 0), Ueberschuss-Kurtosis {fmt(ku)} (Normal 0). Ohne Verlaengerung: Schiefe {skew(err[~ot]):+.2f}, Kurtosis {kurtosis(err[~ot]):+.2f}; nur Verlaengerung: Mittel {err[ot].mean():+.1f}.")
P(f"  Ränder: Chance, 10 Punkte oder mehr ueber/unter dem Modell-Total zu liegen (Normalverteilung N(0, sigma) mit Code-Sigma {SIG} und mit gemessener Std. {err.std(ddof=1):.1f}):")
P(f"    {'Rand':26s} {'echt [95 %]':>26s} {'Normal (18,6)':>14s} {'Normal (gemessen)':>18s}")
sd_m = err.std(ddof=1)
for nm, fn, normal in (("Ist >= Modell + 10", lambda e: (e >= 10), lambda s: 1 - ndtr(10 / s)), ("Ist <= Modell - 10", lambda e: (e <= -10), lambda s: ndtr(-10 / s)),
                       ("|Fehler| >= 10", lambda e: (np.abs(e) >= 10), lambda s: 2 * (1 - ndtr(10 / s))), ("Ist >= Modell + 20", lambda e: (e >= 20), lambda s: 1 - ndtr(20 / s)),
                       ("Ist <= Modell - 20", lambda e: (e <= -20), lambda s: ndtr(-20 / s)), ("Ist >= Modell + 30", lambda e: (e >= 30), lambda s: 1 - ndtr(30 / s)),
                       ("Ist <= Modell - 30", lambda e: (e <= -30), lambda s: ndtr(-30 / s))):
    t = boot_stat(lambda ix_: fn(err[ix_]).mean(), ALL, 120 + int(abs(hash(nm)) % 50), b=1000)
    P(f"    {nm:26s} {100*t[0]:6.1f} % [{100*t[1]:.1f}; {100*t[2]:.1f}] {100*normal(SIG):13.1f}% {100*normal(sd_m):17.1f}%")
for nm, fn, normal in (("ohne Verlaengerung: >= +10", lambda e: (e >= 10), lambda s: 1 - ndtr(10 / s)), ("ohne Verlaengerung: <= -10", lambda e: (e <= -10), lambda s: ndtr(-10 / s))):
    e2 = err[~ot]
    P(f"    {nm:26s} {100*fn(e2).mean():6.1f} %                {100*normal(SIG):13.1f}% (gemessene Std ohne OT {e2.std(ddof=1):.1f}: {100*normal(e2.std(ddof=1)):.1f} %)")
P("")

# ================================================================== 4 Kalibrierung
def fit_w(z, y, w, iters=40):
    X = np.column_stack([np.ones_like(z), z]); beta = np.array([0.0, 1.0])
    for _ in range(iters):
        m = 1 / (1 + np.exp(-X @ beta)); Wt = np.clip(m * (1 - m), 1e-9, None) * w
        step = np.linalg.solve(X.T @ (X * Wt[:, None]) + 1e-9 * np.eye(2), X.T @ (w * (y - m)))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


def calib_block(title, L, Y, PU, gmask, kmask, seed, detail=True):
    p = prob(L); ok = ~np.isnan(Y) & kmask[None, :]
    o = ok & gmask[:, None]
    P(f"  {title}   (Spiele {gmask.sum()}, Zeilen ohne Push {o.sum()}, Pushes {int((PU & gmask[:, None] & kmask[None, :]).sum())})")
    nb = len(EDGES) - 1
    b = np.clip(np.digitize(p, EDGES[1:-1]), 0, nb - 1)
    cnt = np.zeros((n, nb)); sp = np.zeros((n, nb)); sy = np.zeros((n, nb))
    for j in range(nb):
        mk = (b == j) & o
        cnt[:, j] = mk.sum(axis=1); sp[:, j] = np.where(mk, p, 0).sum(axis=1); sy[:, j] = np.where(mk, np.nan_to_num(Y), 0).sum(axis=1)
    r = np.random.default_rng(seed)
    gi = np.where(gmask)[0]
    Wm = np.zeros((BC, n))
    for t in range(BC):
        Wm[t, gi] = np.bincount(r.integers(0, len(gi), len(gi)), minlength=len(gi))
    C, SP, SY = cnt.sum(0), sp.sum(0), sy.sum(0)
    bC, bSP, bSY = Wm @ cnt, Wm @ sp, Wm @ sy
    if detail:
        P(f"    {'Stufe':>9s} {'n':>6s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s} {'95 %-Intervall':>17s}  Hinweis")
    devs, ws, big = [], [], []
    for j in range(nb):
        if C[j] == 0:
            continue
        pm, hr = SP[j] / C[j], SY[j] / C[j]
        with np.errstate(invalid="ignore", divide="ignore"):
            bd = (bSY[:, j] - bSP[:, j]) / bC[:, j] * 100
        lo, hi = np.nanpercentile(bd, [2.5, 97.5]); dev = (hr - pm) * 100
        if C[j] >= 20:
            devs.append(abs(dev)); ws.append(C[j])
        if C[j] >= 100 and abs(dev) > 6:
            big.append(f"{int(round(EDGES[j]*100))}-{int(round(EDGES[j+1]*100))} %")
        if detail:
            P(f"    {int(round(EDGES[j]*100)):>3d}-{int(round(EDGES[j+1]*100)):<3d}% {int(C[j]):6d} {pm:7.3f} {hr:8.3f} {dev:+8.2f} [{lo:+6.2f}; {hi:+6.2f}]  {'nicht aussagekraeftig (< 20)' if C[j] < 20 else ''}")
    mad = float(np.average(devs, weights=ws)) if devs else float("nan")
    okm = mad < 3.0 and not big
    pv, yv = p[o], Y[o]; gidx = np.nonzero(o)[0]
    zz = np.log(np.clip(pv, 1e-6, 1 - 1e-6) / (1 - np.clip(pv, 1e-6, 1 - 1e-6)))
    base = fit_w(zz, yv, np.ones(len(yv)))
    bs = np.array([fit_w(zz, yv, Wm[t][gidx]) for t in range(0, BC, 2)])
    la, lb = np.percentile(bs[:, 0], [2.5, 97.5]), np.percentile(bs[:, 1], [2.5, 97.5])
    P(f"    Ø-Abweichung (gewichtet, Stufen >= 20): {mad:.2f} PP; Stufen >= 100 Zeilen mit > 6 PP: {', '.join(big) if big else 'keine'} -> Massstab {'ERFUELLT' if okm else 'NICHT erfuellt'}; "
      f"Rekalibrierung b = {base[1]:.2f} [{lb[0]:.2f}; {lb[1]:.2f}] ({'1 im Intervall' if lb[0] <= 1 <= lb[1] else '1 AUSSERHALB'}), a = {base[0]:+.3f} [{la[0]:+.3f}; {la[1]:+.3f}] ({'0 im Intervall' if la[0] <= 0 <= la[1] else '0 AUSSERHALB'})")
    return mad, okm


def per_k(title, L, Y, PU, gmask, seed):
    p = prob(L)
    P(f"  {title}: je Linie (k = Abstand zur Hauptlinie; k < 0 darunter; Treffer = Over, ohne Pushes)")
    P(f"    {'k':>3s} {'n':>6s} {'Pushes':>7s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s} {'95 %-Intervall':>17s}")
    idx = np.where(gmask)[0]
    for ki, k in enumerate(KS):
        ok = ~np.isnan(Y[:, ki]) & gmask

        def f(ix_):
            o2 = ok[ix_]
            return (Y[ix_, ki][o2].mean() - p[ix_, ki][o2].mean()) * 100 if o2.any() else 0.0
        draws = np.random.default_rng(seed + ki).integers(0, len(idx), (BC, len(idx)))
        vals = np.array([f(idx[d]) for d in draws])
        lo, hi = np.percentile(vals, [2.5, 97.5])
        P(f"    {k:+3d} {ok.sum():6d} {int((PU[:, ki] & gmask).sum()):7d} {p[ok, ki].mean():7.3f} {Y[ok, ki].mean():8.3f} {f(idx):+8.2f} [{lo:+6.2f}; {hi:+6.2f}]")


P("4 KALIBRIERUNG DER OVER-CHANCE (Sigma 18,6)")
P("4a Je Linie")
per_k("alle Spiele", LA, YA, PUA, ALL, 200)
P("")
below = KS <= 0                    # Hauptlinie und 1..5 darunter
above = KS > 0                     # Kontrolle: 1..5 darueber
P("4b 5-%-Stufen: Hauptlinie und 1 bis 5 Punkte DARUNTER (k = -5..0)")
verd = {}
for nm, gm, sd, det in (("GANZE SAISON", ALL, 300, True), ("HAELFTE 1", h1, 310, False), ("HAELFTE 2", h2, 320, False), ("MODELL-TOTAL AB 235", mu >= 235, 330, True),
                        ("MODELL-TOTAL 220-235", (mu >= 220) & (mu < 235), 340, False), ("MODELL-TOTAL UNTER 220", mu < 220, 350, False)):
    verd[nm] = calib_block(nm, LA, YA, PUA, gm, below, sd, detail=det)
    if gm.sum() < 100:
        P(f"    HINWEIS: nur {int(gm.sum())} Spiele (Zeilen eines Spiels sind nicht unabhaengig) -> nicht aussagekraeftig, Massstab nicht bewertbar.")
        verd[nm] = (verd[nm][0], None)
    P("")
P("4c 5-%-Stufen: KONTROLLE 1 bis 5 Punkte DARUEBER (k = +1..+5)")
for nm, gm, sd, det in (("GANZE SAISON (Kontrolle)", ALL, 360, True), ("HAELFTE 1 (Kontrolle)", h1, 370, False), ("HAELFTE 2 (Kontrolle)", h2, 380, False), ("MODELL-TOTAL AB 235 (Kontrolle)", mu >= 235, 390, False)):
    verd[nm] = calib_block(nm, LA, YA, PUA, gm, above, sd, detail=det)
    P("")

# ================================================================== 5 Push
P("5 PUSH (ganzzahlige Linien B: Runde(Modell-Total) + k)")
tot_cells = n * len(KS)
P(f"  Zeilen {tot_cells}, davon Pushes {int(PUB.sum())} ({100*PUB.sum()/tot_cells:.1f} %). Je Linie:")
P(f"    {'k':>3s} {'Pushes':>7s} {'Anteil':>7s} {'Modell-Push':>12s} {'n ohne Push':>12s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s}")
pB = prob(LB)
for ki, k in enumerate(KS):
    pu = PUB[:, ki]; ok = ~pu
    pp = (ndtr((LB[:, ki] + 0.5 - mu) / SIG) - ndtr((LB[:, ki] - 0.5 - mu) / SIG)).mean()
    P(f"    {k:+3d} {pu.sum():7d} {100*pu.mean():6.1f}% {100*pp:11.1f}% {ok.sum():12d} {pB[ok, ki].mean():7.3f} {YB[ok, ki].mean():8.3f} {100*(YB[ok, ki].mean()-pB[ok, ki].mean()):+8.2f}")
P("  (Die App rechnet ganzzahlige Linien ohne Push mit P(X > Linie).) Hauptlinien A mit Dezimalwert: Pushes siehe 4a.")
P("")
calib_block("Linien B, k = -5..0, ganze Saison (ohne Pushes)", LB, YB, PUB, ALL, below, 400, detail=True)
P("")

# ================================================================== 6 Ausfaelle
P("6 AUSFAELLE (Summe beider Teams; Obergrenze mit Wissen aus der Zukunft)")
ab, pgames, gdate = inj.absences()
gid_by = {(gdate[g], frozenset(t)): g for g, t in pgames.items()}
msel, Sp, Sm = [], [], []
for j, i in enumerate(ix):
    g = games[i]
    gid = gid_by.get((g["date"][:10], frozenset((g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"]))))
    if gid is None:
        continue
    ah, aa = ab[(gid, g["home_team"]["abbreviation"])], ab[(gid, g["visitor_team"]["abbreviation"])]
    if ah["n_prior"] < inj.MIN_GAMES or aa["n_prior"] < inj.MIN_GAMES:
        continue
    msel.append(j)
    Sp.append(sum(m[2] for m in ah["miss"]) + sum(m[2] for m in aa["miss"]))
    Sm.append(sum(m[3] for m in ah["miss"]) + sum(m[3] for m in aa["miss"]))
msel = np.array(msel); Sp = np.array(Sp); Sm = np.array(Sm)
order = np.argsort(msel)
mu6, tot6, err6, ot6 = mu[msel], tot[msel], err[msel], ot[msel]
n6 = len(msel); hh = n6 // 2
hv = {"ganze Saison": np.ones(n6, bool), "Haelfte 1": np.arange(n6) < hh, "Haelfte 2": np.arange(n6) >= hh}
P(f"  Bewertete Spiele {n6} von {n} (ab dem {inj.MIN_GAMES + 1}. Teamspiel beider Teams, mit Spielerdaten). Ø Summe Ausfall-Anteil: Punkte {Sp.mean():.3f}, Minuten {Sm.mean():.3f}, Std. {Sp.std():.3f} / {Sm.std():.3f}. Erwartung: Steigung NEGATIV (mehr Ausfaelle, weniger Punkte).")


def ols(x, y):
    xm = x.mean(); sxx = ((x - xm) ** 2).sum()
    return float(((x - xm) * (y - y.mean())).sum() / sxx) if sxx > 0 else 0.0


def slope_ci(x, y, seed):
    idx = np.random.default_rng(seed).integers(0, len(x), (B, len(x)))
    bs = np.array([ols(x[i], y[i]) for i in idx])
    return ols(x, y), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


P(f"  {'Mass':8s} {'Zeitraum':14s} {'n':>5s} {'Steigung Punkte je 1,0 Anteil [95 %]':>40s} {'R2':>7s}")
for mi, (mn, D) in enumerate((("Punkte", Sp), ("Minuten", Sm))):
    for hi_, (hn, hm) in enumerate(hv.items()):
        s, lo, hi = slope_ci(D[hm], err6[hm], 500 + mi * 10 + hi_)
        P(f"  {mn:8s} {hn:14s} {hm.sum():5d} {f'{s:+.1f} [{lo:+.1f}; {hi:+.1f}]':>40s} {np.corrcoef(D[hm], err6[hm])[0,1]**2:7.3f}")
nm_ot = ~ot6
s, lo, hi = slope_ci(Sp[nm_ot], err6[nm_ot], 530)
P(f"  Punkte, ohne Verlaengerung (ganze Saison) n {nm_ot.sum()}: {s:+.1f} [{lo:+.1f}; {hi:+.1f}]")
P("  Korrektur Total' = Total + Steigung x (Mass - Ø Mass der Bestimm-Haelfte) (zentriert, damit nur der Ausfall-Effekt und kein Mittelwert-Versatz wirkt); Steigung auf einer Haelfte bestimmt, auf der anderen geprueft (und umgekehrt). Linien bleiben L = Modell-Total + k (k = -5..+5),")
P("  Over-Chance neu = 1 - Phi((L - Total') / 18,6). Differenz Brier / Log-Loss neu minus heute, x10^-3 (negativ = besser), gepaarter Bootstrap:")
P(f"  {'Mass':8s} {'bestimmt -> geprueft':24s} {'Steigung':>9s} {'dBrier [95 %]':>26s} {'dLog-Loss [95 %]':>28s}")
y6 = YA[msel]; L6 = LA[msel]
okc = ~np.isnan(y6)


def game_scores(mu_shift):
    p = 1.0 - ndtr((L6 - (mu6 + mu_shift)[:, None]) / SIG)
    p = np.clip(p, 1e-6, 1 - 1e-6)
    yy = np.nan_to_num(y6)
    se = np.where(okc, (p - yy) ** 2, 0).sum(axis=1) / okc.sum(axis=1)
    ll = np.where(okc, -(yy * np.log(p) + (1 - yy) * np.log(1 - p)), 0).sum(axis=1) / okc.sum(axis=1)
    return se, ll


b0, l0 = game_scores(np.zeros(n6))
for mi, (mn, D) in enumerate((("Punkte", Sp), ("Minuten", Sm))):
    for k_, (a_, b_) in enumerate((("Haelfte 1", "Haelfte 2"), ("Haelfte 2", "Haelfte 1"))):
        A, Bm = hv[a_], hv[b_]
        beta = ols(D[A], err6[A])
        b1, l1 = game_scores(beta * (D - D[A].mean()))       # zentriert: nur der Ausfall-Effekt, kein Mittelwert-Versatz
        mb, lb_, hb_ = pair_boot((b1 - b0)[Bm], 600 + mi * 10 + k_)
        ml, ll_, hl_ = pair_boot((l1 - l0)[Bm], 700 + mi * 10 + k_)
        P(f"  {mn:8s} {a_ + ' -> ' + b_:24s} {beta:>+9.1f} {f'{mb*1000:+.2f} [{lb_*1000:+.2f}; {hb_*1000:+.2f}]':>26s} {f'{ml*1000:+.2f} [{ll_*1000:+.2f}; {hl_*1000:+.2f}]':>28s}")
P("")

# ================================================================== Zusammenfassung
P("ZUSAMMENFASSUNG")
mb_ = boot_stat(lambda ix_: err[ix_].mean(), ALL, 10); ma_ = boot_stat(lambda ix_: np.abs(err[ix_]).mean(), ALL, 40)
P(f"  Bias {fmt(mb_)} Pkt, mittlerer Betrag {fmt(ma_, s=False)}, Std. {err.std(ddof=1):.2f} (Code {SIG}); ohne Verlaengerung Std. {err[~ot].std(ddof=1):.2f}. Schiefe {sk[0]:+.2f}, Kurtosis {ku[0]:+.2f}.")
P(f"  Sigma-Test: {'neues Sigma auf beiden Haelften besser' if all(res_ok) else 'kein neues Sigma besteht die Zwei-Haelften-Regel; 18,6 bleibt'}. Team-Fehler-Korrelation rho {rb[0]:.2f} (Code impliziert {rho_code:.2f}).")
P("  Massstab: " + "; ".join(f"{k}: {'nicht aussagekraeftig' if v[1] is None else 'erfuellt' if v[1] else 'NICHT erfuellt'} ({v[0]:.1f} PP)" for k, v in verd.items()))
OUT.write_text("\n".join(W) + "\n", encoding="utf-8")
print("\n".join(W))
