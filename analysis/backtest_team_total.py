"""
Ist-Stand des Team-Total-Modells (Punkte eines einzelnen Teams), Regular Season 2025-26. NUR LESEND: data/cache, schreibt nur analysis/reports/team_total_2025-26.txt.
Keine API-Calls, am Produktivmodell wird nichts geaendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_team_total.py

Replay: analysis/replica_tunable.run (Produktivparameter), walk-forward ueber alle Spiele ab 2015, Auswertung nur 2025-26 Regular Season, reines Modell ohne Markt-Mischung, nur echte Ergebnisse.
Je Spiel zwei Mannschaftszeilen (Heim, Gast). Modell-Punkte des Teams: mu = (Total +- Spread) / 2 mit Total = total_pred und Spread = Elo-Differenz / 50 (beide auf 0,1 gerundet), Heim +, Gast -.
Fehler = Ist-Punkte minus mu. Over-Chance fuer Linie L: p = 1 - Phi((L - mu) / sigma), sigma = TEAM_TOTAL_SIGMA (11,6). Linien A: L = mu + k, k = -5..+5 (k = 0 Hauptlinie, k < 0 darunter, k > 0 Kontrolle);
Linien B: ganzzahlig L = Runde(mu) + k. Push (Punkte genau auf der Linie) = eigenes Ergebnis, aus Trefferquote und Kalibrierung herausgenommen.
Verlaengerung: Feld home_ot1 des Spiels. Beide Zeilen eines Spiels sind korreliert (rho ca. 0,25): ALLE Intervalle (95 %) sind Bootstrap NACH SPIELEN (beide Zeilen zusammen), 2000 Ziehungen.
Ausfaelle: Mass wie analysis/backtest_winner_injuries.py (absences(): Stammspieler = Top 8 nach Minuten, Ausfall-Anteil an den Teampunkten), Wissen aus der Zukunft -> Obergrenze.
team-2 (engine/team_injury.py): delta = 0,5 x (-14,4) x (Mass Heim - Mass Gast) auf den Heim-Spread; Heim-Punkte +delta/2, Gast-Punkte -delta/2 (Total bleibt).
Maßstab: Ø-Abweichung ueber 5-%-Stufen (gewichtet, Stufen >= 20 Zeilen) unter ca. 3 PP, keine Stufe mit >= 100 Zeilen mehr als ca. 6 PP daneben; Stufen unter 20 Zeilen nicht aussagekraeftig.
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
import backtest_winner_injuries as inj  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402
from engine import team_injury as t2  # noqa: E402

OUT = HERE / "reports" / "team_total_2025-26.txt"
SIG = lp.TEAM_TOTAL_SIGMA
B = 2000
KS = np.arange(-5, 6)
GRID = [round(10.0 + 0.5 * i, 1) for i in range(10)]
FIRST_N = 15
EDGES = np.round(np.arange(0, 1.0001, 0.05), 2)

games = load_games(2015, 2025)
rows, _, _, _ = rt.run(games, K=20.0, hca=100.0, mov="cur")
keep = (rows["season"] == 2025) & (rows["post"] == 0)
ix = np.where(keep)[0]
T = np.round(rows["total_pred"][keep], 1)
S = np.round(rows["diff"][keep] / 50.0, 1)
tot, mg = rows["total"][keep], rows["margin"][keep]
n = len(ix)
gh, ga = rows["gp_h"][keep], rows["gp_a"][keep]
ot_g = np.array([games[i].get("home_ot1") is not None or (games[i].get("period") or 4) > 4 for i in ix])
first_g = (gh < FIRST_N) & (ga < FIRST_N)
h1_g = np.arange(n) < n // 2

# Mannschaftszeilen: erst alle Heim-, dann alle Gast-Zeilen
mu = np.concatenate([(T + S) / 2, (T - S) / 2])
pts = np.concatenate([(tot + mg) / 2, (tot - mg) / 2])
side = np.r_[np.zeros(n, int), np.ones(n, int)]            # 0 Heim, 1 Gast
g = np.r_[np.arange(n), np.arange(n)]
err = pts - mu
OT, FIRST, H1 = ot_g[g], first_g[g], h1_g[g]
ALLR = np.ones(2 * n, bool)
H, A = side == 0, side == 1

rngW = np.random.default_rng(2026)
WB = np.stack([np.bincount(rngW.integers(0, n, n), minlength=n) for _ in range(B)]).astype(float)   # B x n Spielgewichte


def gsum(x, mask):
    out = np.zeros(n)
    np.add.at(out, g[mask], x[mask])
    return out


def ci_ratio(num, den, W=WB):
    pt = num.sum() / den.sum()
    bs = (W @ num) / (W @ den)
    return float(pt), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def mean_ci(x, mask):
    return ci_ratio(gsum(x, mask), gsum(np.ones_like(x), mask))


def sd_ci(x, mask):
    s1, s2, c = gsum(x, mask), gsum(x * x, mask), gsum(np.ones_like(x), mask)
    f = lambda a, b, d: np.sqrt(np.maximum((b - a * a / d) / (d - 1), 0))
    pt = f(s1.sum(), s2.sum(), c.sum())
    bs = f(WB @ s1, WB @ s2, WB @ c)
    return float(pt), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def fmt(t, d=2, s=True):
    return (f"{t[0]:+.{d}f} [{t[1]:+.{d}f}; {t[2]:+.{d}f}]" if s else f"{t[0]:.{d}f} [{t[1]:.{d}f}; {t[2]:.{d}f}]")


# ---- Linien
LA = mu[:, None] + KS[None, :]
LB = np.rint(mu)[:, None] + KS[None, :]


def outcome(L):
    y = np.where(pts[:, None] > L + 1e-9, 1.0, 0.0)
    push = np.abs(pts[:, None] - L) < 1e-9
    y[push] = np.nan
    return y, push


YA, PUA = outcome(LA)
YB, PUB = outcome(LB)


def prob(L, sigma=SIG):
    return 1.0 - ndtr((L - mu[:, None]) / sigma)


W_ = []
P = W_.append
P("TEAM-TOTAL-MODELL: IST-STAND (Punkte eines Teams, Regular Season 2025-26, reines Modell, walk-forward)")
P(f"Messskript analysis/backtest_team_total.py (liest nur). Replay analysis/replica_tunable.run; {n} Spiele = {2*n} Mannschaftszeilen (Heim {n}, Gast {n}); Verlaengerung {int(ot_g.sum())} Spiele; erste {FIRST_N} Teamspiele {int(first_g.sum())} Spiele.")
P(f"Sigma im Code: TEAM_TOTAL_SIGMA = {SIG} (engine/line_probabilities.py Z. 28; Optimum aus analysis/sigma_check.py 2017-25: 11,6 [11,4; 11,8], Fenster 11,6/11,8/11,6/11,4). TOTAL_SIGMA = 18,6.")
P("Hinweis zur Messung: Gegen total_2025-26.txt (Team-Streuung Heim 12,25, Gast 11,89) siehe 2a; die Zeilen eines Spiels sind korreliert, daher alle Intervalle nach Spielen.")
P("")

# ================================================================== 1
P("1 GENAUIGKEIT (Fehler = Ist-Punkte minus Modell-Punkte)")
P(f"  {'Gruppe':34s} {'Zeilen':>6s}  {'Mittelwert (Bias) [95 %]':>26s}  {'mittlerer Betrag [95 %]':>26s}")
grp = [("alle Zeilen", ALLR), ("Heim", H), ("Gast", A), ("Modell-Punkte unter 105", mu < 105), ("Modell-Punkte 105 bis 115", (mu >= 105) & (mu < 115)), ("Modell-Punkte ab 115", mu >= 115),
       ("mit Verlaengerung", OT), ("ohne Verlaengerung", ~OT), (f"erste {FIRST_N} Teamspiele", FIRST), ("Rest der Saison", ~FIRST), ("Haelfte 1", H1), ("Haelfte 2", ~H1),
       ("Heim ohne Verlaengerung", H & ~OT), ("Gast ohne Verlaengerung", A & ~OT)]
for nm, mk in grp:
    m = mean_ci(err, mk); a = mean_ci(np.abs(err), mk)
    P(f"  {nm:34s} {mk.sum():6d}  {fmt(m):>26s}  {fmt(a, s=False):>26s}" + ("   (< 100 Zeilen: nicht aussagekraeftig)" if mk.sum() < 100 else ""))
P(f"  Ø Modell-Punkte Heim {mu[H].mean():.2f}, Gast {mu[A].mean():.2f}; Ø Ist-Punkte Heim {pts[H].mean():.2f}, Gast {pts[A].mean():.2f}.")
P("")

# ================================================================== 2
P("2 SIGMA")
P("2a Streuung des Fehlers gegen das Sigma im Code (11,6)")
P(f"  {'Gruppe':34s} {'Std. [95 %]':>22s}  {'Std. aus MAD':>12s}")
for nm, mk in grp:
    mad = 1.4826 * np.median(np.abs(err[mk] - np.median(err[mk])))
    P(f"  {nm:34s} {fmt(sd_ci(err, mk), s=False):>22s}  {mad:12.2f}")
rho = float(np.corrcoef(err[H], err[A])[0, 1])
P(f"  Korrelation der beiden Fehler eines Spiels rho = {rho:.2f} (Ohne Verlaengerung {np.corrcoef(err[H & ~OT], err[A & ~OT])[0,1]:.2f}).")
P("")


def brier_rows(sigma, mask):
    p = prob(LA, sigma); ok = ~np.isnan(YA)
    se = np.where(ok, (p - np.nan_to_num(YA)) ** 2, 0.0).sum(1) / np.maximum(ok.sum(1), 1)
    return gsum(se, mask), gsum(np.ones(2 * n), mask)


def sigma_block(title, mask, seed):
    P(f"2b SIGMA-TEST: {title} (Brier der Over-Chance ueber die Linien A, k = -5..+5; Mittel je Zeile)")
    sc = {s: brier_rows(s, mask) for s in GRID + [SIG]}
    c = sc[SIG][1]
    f = lambda s, hm: sc[s][0][hm].sum() / c[hm].sum()
    P(f"  {'Sigma':>6s} {'ganze Saison':>13s} {'Haelfte 1':>10s} {'Haelfte 2':>10s}")
    for s in GRID:
        P(f"  {s:6.1f} {f(s, np.ones(n, bool)):13.5f} {f(s, h1_g):10.5f} {f(s, ~h1_g):10.5f}")
    P(f"  {SIG:6.1f} {f(SIG, np.ones(n, bool)):13.5f} {f(SIG, h1_g):10.5f} {f(SIG, ~h1_g):10.5f}   <- Code")
    best = min(GRID, key=lambda s: f(s, np.ones(n, bool)))
    P(f"  Bestes Sigma (Gitter, ganze Saison): {best}")
    res = []
    for nm, tr, te, sd in (("einstellen auf Haelfte 1, pruefen auf Haelfte 2", h1_g, ~h1_g, 0), ("einstellen auf Haelfte 2, pruefen auf Haelfte 1", ~h1_g, h1_g, 1)):
        sb = min(GRID, key=lambda s: f(s, tr))
        num = sc[sb][0] - sc[SIG][0]
        Wt = WB * te[None, :]
        pt = num[te].sum() / c[te].sum()
        bs = (Wt @ num) / (Wt @ c)
        lo, hi = np.percentile(bs, [2.5, 97.5])
        res.append(pt < 0)
        P(f"  {nm}: bestes Sigma {sb}; Pruefhaelfte Brier-Differenz (neu minus 11,6) {pt*1000:+.3f} x10^-3 [{lo*1000:+.3f}; {hi*1000:+.3f}] -> {'besser' if pt < 0 else 'nicht besser'}{' (Intervall ohne 0)' if pt < 0 and hi < 0 else ''}")
    P(f"  => neues Sigma nur, wenn auf BEIDEN Pruefhaelften besser: {'JA' if all(res) else 'NEIN, 11,6 bleibt'}")
    P("")
    return all(res)


ok_all = sigma_block("beide Seiten", ALLR, 0)
ok_h = sigma_block("nur Heim", H, 1)
ok_a = sigma_block("nur Gast", A, 2)
ok_n = sigma_block("ohne Verlaengerungsspiele (Kontrolle)", ~OT, 3)

# ================================================================== 3 Kalibrierung
def fit_w(z, y, w, iters=40):
    X = np.column_stack([np.ones_like(z), z]); beta = np.array([0.0, 1.0])
    for _ in range(iters):
        m = 1 / (1 + np.exp(-X @ beta)); Wt = np.clip(m * (1 - m), 1e-9, None) * w
        step = np.linalg.solve(X.T @ (X * Wt[:, None]) + 1e-9 * np.eye(2), X.T @ (w * (y - m)))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


def cells(L, Y, rmask, kmask):
    p = prob(L); ok = ~np.isnan(Y) & kmask[None, :] & rmask[:, None]
    ri, ki = np.nonzero(ok)
    return p[ri, ki], Y[ri, ki], g[ri]


def calib_block(title, L, Y, PU, rmask, kmask, detail=True, special=False):
    pv, yv, gv = cells(L, Y, rmask, kmask)
    npush = int((PU & rmask[:, None] & kmask[None, :]).sum())
    P(f"  {title}   (Zeilen {int(rmask.sum())}, Linien-Zeilen ohne Push {len(yv)}, Pushes {npush})")
    nb = len(EDGES) - 1
    b = np.clip(np.digitize(pv, EDGES[1:-1]), 0, nb - 1)
    cnt = np.zeros((n, nb)); sp = np.zeros((n, nb)); sy = np.zeros((n, nb))
    np.add.at(cnt, (gv, b), 1.0); np.add.at(sp, (gv, b), pv); np.add.at(sy, (gv, b), yv)
    C, SP, SY = cnt.sum(0), sp.sum(0), sy.sum(0)
    bC, bSP, bSY = WB @ cnt, WB @ sp, WB @ sy
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
    zz = np.log(np.clip(pv, 1e-6, 1 - 1e-6) / (1 - np.clip(pv, 1e-6, 1 - 1e-6)))
    base = fit_w(zz, yv, np.ones(len(yv)))
    bs = np.array([fit_w(zz, yv, WB[t][gv]) for t in range(0, B, 4)])
    la, lb = np.percentile(bs[:, 0], [2.5, 97.5]), np.percentile(bs[:, 1], [2.5, 97.5])
    P(f"    Ø-Abweichung (gewichtet, Stufen >= 20): {mad:.2f} PP; Stufen >= 100 Zeilen mit > 6 PP: {', '.join(big) if big else 'keine'} -> Massstab {'ERFUELLT' if okm else 'NICHT erfuellt'}; "
      f"b = {base[1]:.2f} [{lb[0]:.2f}; {lb[1]:.2f}] ({'1 im Intervall' if lb[0] <= 1 <= lb[1] else '1 AUSSERHALB'}), a = {base[0]:+.3f} [{la[0]:+.3f}; {la[1]:+.3f}] ({'0 im Intervall' if la[0] <= 0 <= la[1] else '0 AUSSERHALB'})")
    return mad, okm


def band(title, rmask):
    """Bereich 60-70 % (Hauptlinie und 1-5 darunter)."""
    pv, yv, gv = cells(LA, YA, rmask, KS <= 0)
    m = (pv >= 0.60) & (pv < 0.70)
    if m.sum() == 0:
        P(f"    {title}: keine Zeilen"); return
    num_p, num_y = gsum_cells(pv[m], gv[m]), gsum_cells(yv[m], gv[m]); cn = gsum_cells(np.ones(m.sum()), gv[m])
    ptp, ptlo, pthi = ci_ratio(num_p, cn); ptv = ci_ratio(num_y, cn)
    d = (WB @ num_y - WB @ num_p) / (WB @ cn) * 100
    P(f"    {title:28s} Zeilen {int(m.sum()):5d}  Ø Modell-Chance {100*ptp:5.1f} %  Trefferquote {100*ptv[0]:5.1f} % [{100*ptv[1]:.1f}; {100*ptv[2]:.1f}]  Differenz {100*(ptv[0]-ptp):+.1f} PP [{np.percentile(d, 2.5):+.1f}; {np.percentile(d, 97.5):+.1f}]")


def gsum_cells(x, gv):
    out = np.zeros(n); np.add.at(out, gv, x); return out


def per_k(title, L, Y, PU, rmask):
    p = prob(L)
    P(f"  {title}: je Linie (k < 0 unter der Hauptlinie; Treffer = Over, ohne Pushes)")
    P(f"    {'k':>3s} {'n':>6s} {'Pushes':>7s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s} {'95 %-Intervall':>17s}")
    for ki, k in enumerate(KS):
        ok = ~np.isnan(Y[:, ki]) & rmask
        num_d = gsum(np.where(ok, Y[:, ki] - p[:, ki], 0.0), ok | ~ok if False else np.ones(2 * n, bool))
        cn = gsum(ok.astype(float), np.ones(2 * n, bool))
        pt = num_d.sum() / cn.sum() * 100
        bs = (WB @ num_d) / (WB @ cn) * 100
        lo, hi = np.percentile(bs, [2.5, 97.5])
        P(f"    {k:+3d} {ok.sum():6d} {int((PU[:, ki] & rmask).sum()):7d} {p[ok, ki].mean():7.3f} {Y[ok, ki].mean():8.3f} {pt:+8.2f} [{lo:+6.2f}; {hi:+6.2f}]")


P("3 KALIBRIERUNG DER OVER-CHANCE (Sigma 11,6)")
P("3a Je Linie")
per_k("alle Zeilen", LA, YA, PUA, ALLR)
P("")
below, above = KS <= 0, KS > 0
P("3b 5-%-Stufen: Hauptlinie und 1 bis 5 Punkte DARUNTER (k = -5..0)")
verd = {}
for nm, rm, det in (("GANZE SAISON", ALLR, True), ("HAELFTE 1", H1, False), ("HAELFTE 2", ~H1, False), ("NUR HEIM", H, False), ("NUR GAST", A, False), ("OHNE VERLAENGERUNG", ~OT, False)):
    verd[nm] = calib_block(nm, LA, YA, PUA, rm, below, detail=det)
    P("")
P("3c 5-%-Stufen: KONTROLLE 1 bis 5 Punkte DARUEBER (k = +1..+5)")
for nm, rm, det in (("GANZE SAISON (Kontrolle)", ALLR, True), ("HAELFTE 1 (Kontrolle)", H1, False), ("HAELFTE 2 (Kontrolle)", ~H1, False)):
    verd[nm] = calib_block(nm, LA, YA, PUA, rm, above, detail=det)
    P("")
P("3d BEREICH 60-70 % (frueher zu sicher: Treffer nur ca. 55 %), Linien A k = -5..0")
for nm, rm in (("ganze Saison", ALLR), ("Haelfte 1", H1), ("Haelfte 2", ~H1), ("nur Heim", H), ("nur Gast", A), ("ohne Verlaengerung", ~OT)):
    band(nm, rm)
P("")

# ================================================================== 4 Push
P("4 PUSH (ganzzahlige Linien B: Runde(mu) + k)")
cells_tot = 2 * n * len(KS)
P(f"  Zeilen {cells_tot}, davon Pushes {int(PUB.sum())} ({100*PUB.sum()/cells_tot:.1f} %). Je Linie:")
P(f"    {'k':>3s} {'Pushes':>7s} {'Anteil':>7s} {'Modell-Push':>12s} {'n ohne Push':>12s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s}")
pB = prob(LB)
for ki, k in enumerate(KS):
    pu = PUB[:, ki]; ok = ~pu
    pp = (ndtr((LB[:, ki] + 0.5 - mu) / SIG) - ndtr((LB[:, ki] - 0.5 - mu) / SIG)).mean()
    P(f"    {k:+3d} {pu.sum():7d} {100*pu.mean():6.1f}% {100*pp:11.1f}% {ok.sum():12d} {pB[ok, ki].mean():7.3f} {YB[ok, ki].mean():8.3f} {100*(YB[ok, ki].mean()-pB[ok, ki].mean()):+8.2f}")
P("  (Die App rechnet ganzzahlige Linien ohne Push mit P(X > Linie).) Hauptlinien A mit Dezimalwert: Pushes siehe 3a.")
P("")
calib_block("Linien B, k = -5..0, ganze Saison (ohne Pushes)", LB, YB, PUB, ALLR, below, detail=True)
P("")

# ================================================================== 5 Ausfaelle
P("5 AUSFAELLE (Obergrenze, Wissen aus der Zukunft)")
ab, pgames, gdate = inj.absences()
gid_by = {(gdate[x], frozenset(t)): x for x, t in pgames.items()}
sel, Mh, Ma = [], [], []
for j, i in enumerate(ix):
    gm = games[i]; ha, aa_ = gm["home_team"]["abbreviation"], gm["visitor_team"]["abbreviation"]
    gid = gid_by.get((gm["date"][:10], frozenset((ha, aa_))))
    if gid is None:
        continue
    a1, a2 = ab[(gid, ha)], ab[(gid, aa_)]
    if a1["n_prior"] < inj.MIN_GAMES or a2["n_prior"] < inj.MIN_GAMES:
        continue
    sel.append(j); Mh.append(sum(m[2] for m in a1["miss"])); Ma.append(sum(m[2] for m in a2["miss"]))
sel = np.array(sel); Mh = np.array(Mh); Ma = np.array(Ma)
in_sel = np.zeros(n, bool); in_sel[sel] = True
own = np.full(2 * n, np.nan); opp = np.full(2 * n, np.nan)
own[sel], opp[sel] = Mh, Ma
own[sel + n], opp[sel + n] = Ma, Mh
RS_ = in_sel[g]
P(f"  Bewertete Spiele {len(sel)} von {n} (ab dem {inj.MIN_GAMES + 1}. Teamspiel beider Teams, mit Spielerdaten) = {2*len(sel)} Zeilen. Ø eigenes Ausfall-Mass {np.nanmean(own):.3f} (Std. {np.nanstd(own):.3f}).")


def ols_w(x, y, w):
    xm = (w * x).sum() / w.sum(); ym = (w * y).sum() / w.sum()
    sxx = (w * (x - xm) ** 2).sum()
    return float((w * (x - xm) * (y - ym)).sum() / sxx) if sxx > 0 else 0.0


def slope_boot(x, y, rmask, seed=0):
    idx = np.where(rmask)[0]
    gi = g[idx]
    base = ols_w(x[idx], y[idx], np.ones(len(idx)))
    bs = np.array([ols_w(x[idx], y[idx], WB[t][gi]) for t in range(0, B, 2)])
    return base, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


P("5a Erklaert das Ausfall-Mass des EIGENEN Teams den Fehler der Team-Punkte? (Steigung = Punkte je 1,0 Ausfall-Anteil; Erwartung negativ)")
P(f"  {'Mass':34s} {'Zeitraum':14s} {'Zeilen':>6s} {'Steigung [95 %]':>26s}")
for nm, x in (("eigenes Team", own), ("Gegner (zur Kontrolle)", opp), ("eigenes minus Gegner (wie team-2)", own - opp)):
    for hn, hm in (("ganze Saison", RS_), ("Haelfte 1", RS_ & H1), ("Haelfte 2", RS_ & ~H1)):
        s_ = slope_boot(x, err, hm)
        P(f"  {nm:34s} {hn:14s} {hm.sum():6d} {fmt(s_, d=1):>26s}")
P("  nur Heim-Zeilen / nur Gast-Zeilen, eigenes Team, ganze Saison: " + "; ".join(f"{nm} {fmt(slope_boot(own, err, RS_ & sm), d=1)}" for nm, sm in (("Heim", H), ("Gast", A))))
P("")

# 5b team-2
P("5b team-2: Verschiebung der Team-Punkte (Heim +delta/2, Gast -delta/2, delta = 0,5 x (-14,4) x (Mass Heim - Mass Gast)) gegen heute: Brier der Over-Chance (Linien A, k = -5..+5)")
FACT = t2.FACTOR * t2.SLOPE                       # -7,2
shift_prod = np.zeros(2 * n)
shift_prod[:n][sel] = FACT * (Mh - Ma) / 2
shift_prod[n:][sel] = -FACT * (Mh - Ma) / 2


def brier_cells(shift):
    p = np.clip(1.0 - ndtr((LA - (mu + shift)[:, None]) / SIG), 1e-6, 1 - 1e-6)
    ok = ~np.isnan(YA); yy = np.nan_to_num(YA)
    se = np.where(ok, (p - yy) ** 2, 0).sum(1) / np.maximum(ok.sum(1), 1)
    ll = np.where(ok, -(yy * np.log(p) + (1 - yy) * np.log(1 - p)), 0).sum(1) / np.maximum(ok.sum(1), 1)
    return se, ll


b0, l0 = brier_cells(np.zeros(2 * n))


def paired_rows(shift, mask_games, seed):
    b1, l1 = brier_cells(shift)
    rm = np.zeros(2 * n, bool); rm[:] = mask_games[g] & RS_
    cnt = gsum(np.ones(2 * n), rm)
    out = []
    for d in (b1 - b0, l1 - l0):
        num = gsum(d, rm)
        Wt = WB * mask_games[None, :]
        pt = num.sum() / cnt.sum()
        bs = (Wt @ num) / (Wt @ cnt)
        out.append((pt * 1000, np.percentile(bs, 2.5) * 1000, np.percentile(bs, 97.5) * 1000))
    return out


P(f"  Produktivregel (feste Steigung -14,4, Faktor 0,5; Verschiebung je Team = {FACT/2:+.2f} x (eigenes Mass - Mass Gegner)), x10^-3 (negativ = besser):")
for nm, mg_ in (("ganze Saison", np.ones(n, bool)), ("Haelfte 1", h1_g), ("Haelfte 2", ~h1_g)):
    bb, ll = paired_rows(shift_prod, mg_, 0)
    P(f"    {nm:14s} dBrier {bb[0]:+.2f} [{bb[1]:+.2f}; {bb[2]:+.2f}]   dLog-Loss {ll[0]:+.2f} [{ll[1]:+.2f}; {ll[2]:+.2f}]")
P("  Neu bestimmte Steigung (eigenes minus Gegner-Mass), auf einer Haelfte bestimmt, auf der anderen geprueft:")
D_ = own - opp
for a_, b_, ma, mb in (("Haelfte 1", "Haelfte 2", h1_g, ~h1_g), ("Haelfte 2", "Haelfte 1", ~h1_g, h1_g)):
    rm = RS_ & ma[g]
    beta = ols_w(D_[rm], err[rm], np.ones(rm.sum()))
    sh = np.zeros(2 * n); ok_ = RS_; sh[ok_] = beta * (D_[ok_] - np.nanmean(D_[rm]))
    bb, ll = paired_rows(sh, mb, 0)
    P(f"    {a_} -> {b_}: Steigung {beta:+.2f} je Anteil; dBrier {bb[0]:+.2f} [{bb[1]:+.2f}; {bb[2]:+.2f}]   dLog-Loss {ll[0]:+.2f} [{ll[1]:+.2f}; {ll[2]:+.2f}]")
P("  Zum Vergleich die Produktivregel (-7,2 je Spread-Anteil) entspricht -3,6 Punkten je Team und Anteil; gemessen siehe 5a.")
P("")

# ================================================================== Zusammenfassung
P("ZUSAMMENFASSUNG")
P(f"  Bias {fmt(mean_ci(err, ALLR))} Punkte (Heim {fmt(mean_ci(err, H))}, Gast {fmt(mean_ci(err, A))}); mittlerer Betrag {fmt(mean_ci(np.abs(err), ALLR), s=False)}; Std. {sd_ci(err, ALLR)[0]:.2f} (Code {SIG}), ohne Verlaengerung {sd_ci(err, ~OT)[0]:.2f}.")
P(f"  Sigma-Test neues Sigma auf beiden Haelften besser: beide Seiten {'ja' if ok_all else 'nein'}, Heim {'ja' if ok_h else 'nein'}, Gast {'ja' if ok_a else 'nein'}, ohne Verlaengerung {'ja' if ok_n else 'nein'}.")
P("  Massstab: " + "; ".join(f"{k}: {'erfuellt' if v[1] else 'NICHT erfuellt'} ({v[0]:.1f} PP)" for k, v in verd.items()))
OUT.write_text("\n".join(W_) + "\n", encoding="utf-8")
print("\n".join(W_))
