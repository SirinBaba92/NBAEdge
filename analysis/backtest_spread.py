"""
Ist-Stand des Spread-Modells, Regular Season 2025-26. NUR LESEND: data/cache, schreibt nur analysis/reports/spread_2025-26.txt. Keine API-Calls, am Produktivmodell wird nichts geaendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_spread.py

Replay: analysis/replica_tunable.run (Produktivparameter K 20, Heimvorteil 100, MoV heute), walk-forward ueber alle Spiele ab 2015, Auswertung nur 2025-26 Regular Season (ohne Playoffs).
Reines Modell ohne Markt-Mischung, nur echte Ergebnisse, keine Quoten. Modell-Spread mu = Elo-Differenz / 50, auf 0,1 gerundet (= angezeigter Spread, positiv = Heim staerker).
Fehler = Ist-Spread (Heimpunkte minus Gastpunkte) minus mu. Deckungs-Chance Heim fuer Linie L: p = 1 - Phi((L - mu) / sigma) (wie engine/line_probabilities.prob_above/spread_rows).
Linien: A) L = mu + k, k = -5..+5 (k = 0 ist die Hauptlinie = Modell-Spread selbst); B) ganzzahlige Linien L = Runde(mu) + k, k = -5..+5 (hier treten Pushes auf).
Push: Marge genau auf der Linie = eigenes Ergebnis, kein Treffer/Fehlschlag, aus Trefferquote und Kalibrierung herausgenommen (gezaehlt wird getrennt).
Intervalle 95 %: Bootstrap nach Spielen (Zeilen eines Spiels sind nicht unabhaengig), 2000 Ziehungen (Kalibrierung/Rekalibrierung 1000). Saisonhaelften: chronologisch (Datum, ID).
Maßstab: Ø-Abweichung (gewichtet nach Spielen, Stufen mit >= 20 Zeilen) unter ca. 3 PP und keine Stufe mit >= 100 Zeilen mehr als ca. 6 PP daneben; Stufen unter 20 Zeilen nicht aussagekraeftig.
Sigma-Test: 9,0 bis 14,5 in 0,5er-Schritten nach Brier der Deckungs-Chance (Linien A); auf einer Haelfte einstellen, auf der anderen gegen das heutige 13,2 pruefen, und umgekehrt.
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

OUT = HERE / "reports" / "spread_2025-26.txt"
B, BC = 2000, 1000
SIG = lp.SPREAD_SIGMA
KS = np.arange(-5, 6)
GRID = [round(9.0 + 0.5 * i, 1) for i in range(12)]
FIRST_N = 15
rng0 = np.random.default_rng(7)

games = load_games(2015, 2025)
rows, _, _, _ = rt.run(games, K=20.0, hca=100.0, mov="cur")
keep = (rows["season"] == 2025) & (rows["post"] == 0)
mu = np.round(rows["diff"][keep] / 50.0, 1)
mg = rows["margin"][keep]
gh, ga = rows["gp_h"][keep], rows["gp_a"][keep]
n = len(mu)
err = mg - mu
first = (gh < FIRST_N) & (ga < FIRST_N)
fav, dog, even = mu > 0, mu < 0, mu == 0
h1 = np.arange(n) < n // 2
h2 = ~h1


def cp(p, d=2):
    return f"{100 * p:.{d}f}"


def boot_stat(fn, mask, seed, b=B):
    idx = np.where(mask)[0]
    r = np.random.default_rng(seed)
    draws = r.integers(0, len(idx), (b, len(idx)))
    vals = np.array([fn(idx[d]) for d in draws])
    return float(fn(idx)), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def fmt(t, d=2, s=True):
    return (f"{t[0]:+.{d}f} [{t[1]:+.{d}f}; {t[2]:+.{d}f}]" if s else f"{t[0]:.{d}f} [{t[1]:.{d}f}; {t[2]:.{d}f}]")


# ---- Linien und Ergebnisse
def lines_A():
    return mu[:, None] + KS[None, :]


def lines_B():
    return np.rint(mu)[:, None] + KS[None, :]


def outcome(L):
    """y = 1 Heim deckt, 0 nicht, nan = Push."""
    y = np.where(mg[:, None] > L + 1e-9, 1.0, 0.0)
    push = np.abs(mg[:, None] - L) < 1e-9
    y[push] = np.nan
    return y, push


def prob(L, sigma=SIG):
    return 1.0 - ndtr((L - mu[:, None]) / sigma)


LA, LB = lines_A(), lines_B()
YA, PUA = outcome(LA)
YB, PUB = outcome(LB)

W = []
P = W.append
P("SPREAD-MODELL: IST-STAND (Regular Season 2025-26, reines Modell, walk-forward)")
P(f"Messskript analysis/backtest_spread.py (liest nur). Replay analysis/replica_tunable.run; Spiele {n} (Heimteam-Favorit {fav.sum()}, Heimteam-Aussenseiter {dog.sum()}, Spread 0,0 {even.sum()}); erste {FIRST_N} Teamspiele (beide Teams < {FIRST_N}): {first.sum()}, danach {(~first).sum()}.")
P(f"Sigma im Code: SPREAD_SIGMA = {SIG} (engine/line_probabilities.py Z. 26, sigmas_version 2 seit 23.10.2026). Das frueher benutzte 10,5 (Version 1) steckt nur noch im Kommentar und in der Rueckfall-Regel fuer alte Schnappschuesse ohne Feld sigmas_version.")
P("Dasselbe Sigma 13,2 gilt fuer den Spread-Balken (spread_rows), die Siegchance (win_prob_home, engine/projection.py) und die Spieler-/Live-Modelle (SPREAD_SIGMA importiert). Die Value-Bets-Siegchance (Logistik) nutzt kein Sigma.")
P("")

# ================================================================== 1 Genauigkeit
P("1 GENAUIGKEIT (Fehler = Ist-Spread minus Modell-Spread, Heim-Sicht; + = Heim besser als Modell)")
P(f"  {'Gruppe':44s} {'n':>5s}  {'Mittelwert (Bias) Pkt [95 %]':>30s}  {'mittlerer Betrag Pkt [95 %]':>30s}")
groups = [("alle", np.ones(n, bool)), ("Heimteam Favorit (Spread > 0)", fav), ("Heimteam Aussenseiter (Spread < 0)", dog),
          (f"erste {FIRST_N} Teamspiele", first), ("Rest der Saison", ~first), ("Haelfte 1", h1), ("Haelfte 2", h2)]
for i, (nm, mk) in enumerate(groups):
    m = boot_stat(lambda ix: err[ix].mean(), mk, 10 + i)
    a = boot_stat(lambda ix: np.abs(err[ix]).mean(), mk, 30 + i)
    P(f"  {nm:44s} {mk.sum():5d}  {fmt(m):>30s}  {fmt(a, s=False):>30s}")
P("  Zum Vergleich: mittlerer Fehler im Modell-Spread gegen den Betrag |Ist-Spread|: mittlerer Betrag Ist-Spread = %.2f Pkt (Ø Modell-Spread 'Betrag' = %.2f)." % (np.abs(mg).mean(), np.abs(mu).mean()))
P("")

# ================================================================== 2 Sigma
P("2 SIGMA (Streuung des Fehlers gegen das Sigma im Code)")
P(f"  {'Gruppe':44s} {'Std. des Fehlers [95 %]':>26s}  {'Std. aus MAD (robust)':>22s}")
for i, (nm, mk) in enumerate(groups):
    s = boot_stat(lambda ix: err[ix].std(ddof=1), mk, 50 + i, b=1000)
    mad = 1.4826 * np.median(np.abs(err[mk] - np.median(err[mk])))
    P(f"  {nm:44s} {fmt(s, s=False):>26s}  {mad:22.2f}")
P(f"  Sigma im Code: {SIG}. Ob das passt, zeigt der Brier-Test unten (Std. des Fehlers allein ist nicht dasselbe wie das Brier-Optimum, weil Linien in den Randbereichen anders gewichten).")
P("")


def brier_game(sigma, mask_games=None):
    p = prob(LA, sigma)
    ok = ~np.isnan(YA)
    se = np.where(ok, (p - np.nan_to_num(YA)) ** 2, 0.0)
    return se.sum(axis=1) / np.maximum(ok.sum(axis=1), 1)


def pair_boot(d, seed):
    r = np.random.default_rng(seed)
    idx = r.integers(0, len(d), (B, len(d)))
    return float(d.mean()), *np.percentile(d[idx].mean(axis=1), [2.5, 97.5])


P("2b SIGMA-TEST (Brier der Deckungs-Chance ueber die Linien A, k = -5..+5; Mittel je Spiel)")
bg = {s: brier_game(s) for s in GRID + [SIG]}
P(f"  {'Sigma':>6s} {'Brier ganze Saison':>19s} {'Haelfte 1':>10s} {'Haelfte 2':>10s}")
for s in GRID:
    P(f"  {s:6.1f} {bg[s].mean():19.5f} {bg[s][h1].mean():10.5f} {bg[s][h2].mean():10.5f}" + ("   <- naechste Stufe am Code-Wert 13,2" if s == 13.0 else ""))
P(f"  {SIG:6.1f} {bg[SIG].mean():19.5f} {bg[SIG][h1].mean():10.5f} {bg[SIG][h2].mean():10.5f}   <- Code")
best_all = min(GRID, key=lambda s: bg[s].mean())
P(f"  Bestes Sigma der Gitterwerte ganze Saison: {best_all} (Brier {bg[best_all].mean():.5f}); Code 13,2: {bg[SIG].mean():.5f}")
res_ok = []
for nm, tr, te, sd in (("einstellen auf Haelfte 1, pruefen auf Haelfte 2", h1, h2, 70), ("einstellen auf Haelfte 2, pruefen auf Haelfte 1", h2, h1, 71)):
    sb = min(GRID, key=lambda s: bg[s][tr].mean())
    d = bg[sb][te] - bg[SIG][te]
    m, lo, hi = pair_boot(d, sd)
    better = m < 0
    res_ok.append(better)
    P(f"  {nm}: bestes Sigma {sb}; auf der Pruefhaelfte Brier-Differenz (neu minus 13,2) {m*1000:+.3f} x10^-3 [{lo*1000:+.3f}; {hi*1000:+.3f}] -> {'besser' if better else 'nicht besser'}{' (Intervall ohne 0)' if better and hi < 0 else ''}")
P(f"  => Ein neues Sigma zaehlt nur, wenn es auf BEIDEN Pruefhaelften besser ist: {'JA' if all(res_ok) else 'NEIN, das heutige 13,2 bleibt'}")
P("")

# ================================================================== 3/4 Kalibrierung
EDGES = np.round(np.arange(0, 1.0001, 0.05), 2)


def bin_arrays(p, y, ok, gmask):
    """Je Spiel und Stufe: Anzahl, Summe p, Summe y (nur gueltige Zeilen)."""
    nb = len(EDGES) - 1
    b = np.clip(np.digitize(p, EDGES[1:-1]), 0, nb - 1)
    cnt = np.zeros((n, nb)); sp = np.zeros((n, nb)); sy = np.zeros((n, nb))
    for j in range(nb):
        mk = (b == j) & ok & gmask[:, None]
        cnt[:, j] = mk.sum(axis=1)
        sp[:, j] = np.where(mk, p, 0).sum(axis=1)
        sy[:, j] = np.where(mk, np.nan_to_num(y), 0).sum(axis=1)
    return cnt, sp, sy


def fit_w(z, y, w, iters=40):
    X = np.column_stack([np.ones_like(z), z]); beta = np.array([0.0, 1.0])
    for _ in range(iters):
        m = 1 / (1 + np.exp(-X @ beta)); Wt = np.clip(m * (1 - m), 1e-9, None) * w
        step = np.linalg.solve(X.T @ (X * Wt[:, None]) + 1e-9 * np.eye(2), X.T @ (w * (y - m)))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


def calib_block(title, L, Y, PU, gmask, seed, detail=True):
    p = prob(L); ok = ~np.isnan(Y)
    o = ok & gmask[:, None]
    P(f"  {title}   (Spiele {gmask.sum()}, Zeilen ohne Push {o.sum()}, Pushes {int((PU & gmask[:, None]).sum())})")
    cnt, sp, sy = bin_arrays(p, Y, ok, gmask)
    r = np.random.default_rng(seed)
    gi = np.where(gmask)[0]
    # Gewichte je Ziehung (Haeufigkeit jedes Spiels)
    Wm = np.zeros((BC, n))
    for t in range(BC):
        Wm[t, gi] = np.bincount(r.integers(0, len(gi), len(gi)), minlength=len(gi))
    C, SP, SY = cnt.sum(0), sp.sum(0), sy.sum(0)
    bC, bSP, bSY = Wm @ cnt, Wm @ sp, Wm @ sy
    P(f"    {'Stufe':>9s} {'n':>6s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s} {'95 %-Intervall':>17s}  Hinweis")
    devs, ws, maxbig = [], [], []
    for j in range(len(EDGES) - 1):
        if C[j] == 0:
            continue
        pm, hr = SP[j] / C[j], SY[j] / C[j]
        with np.errstate(invalid="ignore", divide="ignore"):
            bd = (bSY[:, j] / bC[:, j] - bSP[:, j] / bC[:, j]) * 100
        lo, hi = np.nanpercentile(bd, [2.5, 97.5])
        dev = (hr - pm) * 100
        note = "nicht aussagekraeftig (< 20)" if C[j] < 20 else ""
        if C[j] >= 20:
            devs.append(abs(dev)); ws.append(C[j])
        if C[j] >= 100 and abs(dev) > 6:
            maxbig.append(f"{int(EDGES[j]*100)}-{int(EDGES[j+1]*100)} %")
        if detail:
            P(f"    {int(round(EDGES[j]*100)):>3d}-{int(round(EDGES[j+1]*100)):<3d}% {int(C[j]):6d} {pm:7.3f} {hr:8.3f} {dev:+8.2f} [{lo:+6.2f}; {hi:+6.2f}]  {note}")
    mad = float(np.average(devs, weights=ws)) if devs else float("nan")
    ok1, ok2 = mad < 3.0, not maxbig
    P(f"    Ø-Abweichung (gewichtet, Stufen >= 20): {mad:.2f} PP -> {'unter 3 PP' if ok1 else 'UEBER 3 PP'}; Stufen mit >= 100 Zeilen und > 6 PP daneben: {', '.join(maxbig) if maxbig else 'keine'} -> Massstab {'ERFUELLT' if ok1 and ok2 else 'NICHT erfuellt'}")
    # Rekalibrierung
    zz = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))[o]; yy = Y[o]
    gidx = np.nonzero(o)[0]
    base = fit_w(zz, yy, np.ones(len(yy)))
    bs = np.array([fit_w(zz, yy, Wm[t][gidx]) for t in range(0, BC, 2)])
    la, lb = np.percentile(bs[:, 0], [2.5, 97.5]), np.percentile(bs[:, 1], [2.5, 97.5])
    P(f"    Rekalibrierung logit P(deckt) = a + b logit(p): b = {base[1]:.2f} [{lb[0]:.2f}; {lb[1]:.2f}] ({'1 im Intervall' if lb[0] <= 1 <= lb[1] else '1 AUSSERHALB'}), a = {base[0]:+.3f} [{la[0]:+.3f}; {la[1]:+.3f}] ({'0 im Intervall' if la[0] <= 0 <= la[1] else '0 AUSSERHALB'})")
    return mad, ok1 and ok2


def per_k(title, L, Y, PU, gmask, seed):
    p = prob(L); out = []
    P(f"  {title}: je Linie (k = Abstand zur Hauptlinie in Punkten; Treffer = Heim deckt, ohne Pushes)")
    P(f"    {'k':>3s} {'n':>6s} {'Pushes':>7s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s} {'95 %-Intervall':>17s}")
    for ki, k in enumerate(KS):
        ok = ~np.isnan(Y[:, ki]) & gmask
        idx = np.where(gmask)[0]
        r = np.random.default_rng(seed + ki)
        def f(ix):
            o2 = ok[ix]
            return (Y[ix, ki][o2].mean() - p[ix, ki][o2].mean()) * 100 if o2.any() else 0.0
        draws = r.integers(0, len(idx), (BC, len(idx)))
        vals = np.array([f(idx[d]) for d in draws])
        lo, hi = np.percentile(vals, [2.5, 97.5])
        P(f"    {k:+3d} {ok.sum():6d} {int((PU[:, ki] & gmask).sum()):7d} {p[ok, ki].mean():7.3f} {Y[ok, ki].mean():8.3f} {f(idx):+8.2f} [{lo:+6.2f}; {hi:+6.2f}]")


P("3 KALIBRIERUNG (Modell-Chance, dass das Heimteam die Linie deckt, gegen die Trefferquote; Sigma 13,2)")
P("")
all_g = np.ones(n, bool)
verd = {}
P("3a LINIEN A (Hauptlinie = Modell-Spread, dazu +-1 bis +-5 Punkte)")
per_k("alle Spiele", LA, YA, PUA, all_g, 100)
P("")
for nm, gm, sd in (("GANZE SAISON", all_g, 200), ("HAELFTE 1", h1, 210), ("HAELFTE 2", h2, 220), ("HEIMTEAM FAVORIT", fav, 230), ("HEIMTEAM AUSSENSEITER", dog, 240),
                   ("FAVORIT, Haelfte 1", fav & h1, 250), ("FAVORIT, Haelfte 2", fav & h2, 260), ("AUSSENSEITER, Haelfte 1", dog & h1, 270), ("AUSSENSEITER, Haelfte 2", dog & h2, 280)):
    verd[nm] = calib_block(nm, LA, YA, PUA, gm, sd, detail=nm in ("GANZE SAISON", "HEIMTEAM FAVORIT", "HEIMTEAM AUSSENSEITER"))
    P("")
P("3b FAVORIT UND AUSSENSEITER JE LINIE")
per_k("Heimteam Favorit", LA, YA, PUA, fav, 300)
P("")
per_k("Heimteam Aussenseiter", LA, YA, PUA, dog, 320)
P("")

# ================================================================== 4 Push
P("4 PUSH (ganzzahlige Linien B: Runde(Modell-Spread) + k)")
tot_cells = n * len(KS)
P(f"  Zeilen {tot_cells}, davon Pushes {int(PUB.sum())} ({100*PUB.sum()/tot_cells:.1f} %). Je Linie:")
P(f"    {'k':>3s} {'Pushes':>7s} {'Anteil':>7s} {'Modell-Push':>12s} {'n ohne Push':>12s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s}")
for ki, k in enumerate(KS):
    pu = PUB[:, ki]; ok = ~pu
    pm = prob(LB)[:, ki]
    # Push-Wahrscheinlichkeit des Modells bei ganzzahligen Margen: Phi((L+.5-mu)/s) - Phi((L-.5-mu)/s)
    pp = (ndtr((LB[:, ki] + 0.5 - mu) / SIG) - ndtr((LB[:, ki] - 0.5 - mu) / SIG)).mean()
    P(f"    {k:+3d} {pu.sum():7d} {100*pu.mean():6.1f}% {100*pp:11.1f}% {ok.sum():12d} {pm[ok].mean():7.3f} {YB[ok, ki].mean():8.3f} {100*(YB[ok, ki].mean()-pm[ok].mean()):+8.2f}")
P("  (Die App rechnet ganzzahlige Linien ohne Push mit P(X > Linie); die Push-Wahrscheinlichkeit wird nicht ausgewiesen.)")
P("")
calib_block("Linien B, ganze Saison (ohne Pushes)", LB, YB, PUB, all_g, 400, detail=True)
P("")
mad_all, ok_all = verd["GANZE SAISON"]

# ================================================================== Zusammenfassung
P("ZUSAMMENFASSUNG")
mb = boot_stat(lambda ix: err[ix].mean(), np.ones(n, bool), 10)
ma = boot_stat(lambda ix: np.abs(err[ix]).mean(), np.ones(n, bool), 30)
P(f"  Bias {fmt(mb)} Pkt, mittlerer Betrag {fmt(ma, s=False)} Pkt, Std. des Fehlers {err.std(ddof=1):.2f} (Code-Sigma {SIG}).")
P(f"  Sigma-Test: {'neues Sigma auf beiden Haelften besser' if all(res_ok) else 'kein neues Sigma besteht die Zwei-Haelften-Regel; 13,2 bleibt'}.")
P("  Massstab (Ø < 3 PP und keine grosse Stufe > 6 PP): " + "; ".join(f"{k}: {'erfuellt' if v[1] else 'NICHT erfuellt'} ({v[0]:.1f} PP)" for k, v in verd.items()))
OUT.write_text("\n".join(W) + "\n", encoding="utf-8")
print("\n".join(W))
