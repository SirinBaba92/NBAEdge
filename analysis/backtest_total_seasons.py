"""
Anfangs-Bias des Total-Modells (2025-26: in den ersten 15 Teamspielen liegt das Ist-Total etwa +3 Punkte ueber dem Modell-Total) in frueheren Saisons?
NUR LESEND: data/cache, schreibt nur analysis/reports/total_seasons.txt. Keine API-Calls, am Produktivmodell wird nichts geaendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_total_seasons.py

Aufbau wie analysis/backtest_total.py (gleiche Definitionen): Replay analysis/replica_tunable.run (Produktivparameter) ueber games_2015..2025, je Saison 2017-18 bis 2025-26 nur Regular Season, reines Modell ohne Markt.
Modell-Total mu = total_pred auf 0,1 gerundet, Fehler = Ist-Total minus mu. Phase "erste N" = beide Teams haben vor dem Spiel weniger als N Spiele (gp_h, gp_a < N, wie analysis/backtest_winner.py), N = 15
(Kontrolle 10 und 20); "danach" = alle uebrigen. Verlaengerung: Feld home_ot1 der Spieldaten ist in ALLEN Saisons gesetzt (anders als gedacht erkennbar); Hauptauswertung wie verlangt mit allen Spielen,
zusaetzlich Mittelwert ohne Verlaengerung. Intervalle 95 %: Bootstrap nach Spielen (2000 Ziehungen; Kalibrierung 500/1000). Teamspiel-Nummer eines Spiels = max(gp_h, gp_a) + 1.
Entscheidungsregel: Echter Modellfehler nur, wenn das Vorzeichen des Mittelwerts der Phase "erste 15" in mindestens 6 von 9 Saisons wie 2025-26 (positiv) ist UND das gepoolte Intervall die 0 nicht einschliesst.
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

OUT = HERE / "reports" / "total_seasons.txt"
SIG = lp.TOTAL_SIGMA
B = 2000
KS = np.arange(-5, 1)               # Hauptlinie und 1..5 darunter
SEASONS = list(range(2017, 2026))
EDGES = np.round(np.arange(0, 1.0001, 0.05), 2)

games = load_games(2015, 2025)
rows, _, _, _ = rt.run(games, K=20.0, hca=100.0, mov="cur")
RS = rows["post"] == 0
OT_ALL = np.array([games[i].get("home_ot1") is not None or (games[i].get("period") or 4) > 4 for i in range(len(games))])


def label(s):
    return f"{s}-{str(s + 1)[-2:]}"


def boot(v, fn, seed, b=B):
    v = np.asarray(v, float)
    if len(v) < 3:
        return (float(fn(v)) if len(v) else float("nan"), float("nan"), float("nan"))
    idx = np.random.default_rng(seed).integers(0, len(v), (b, len(v)))
    vals = np.array([fn(v[i]) for i in idx])
    return float(fn(v)), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def fmt(t, d=2):
    return f"{t[0]:+.{d}f} [{t[1]:+.{d}f}; {t[2]:+.{d}f}]"


def diff_ci(a, b, fn, seed, nb=1000):
    r = np.random.default_rng(seed)
    vals = [fn(a[r.integers(0, len(a), len(a))]) - fn(b[r.integers(0, len(b), len(b))]) for _ in range(nb)]
    return float(fn(a) - fn(b)), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


D = {}
for s in SEASONS:
    m = RS & (rows["season"] == s)
    mu = np.round(rows["total_pred"][m], 1)
    D[s] = dict(mu=mu, tot=rows["total"][m], err=rows["total"][m] - mu, gh=rows["gp_h"][m], ga=rows["gp_a"][m], ot=OT_ALL[m], n=int(m.sum()))
    D[s]["num"] = np.maximum(D[s]["gh"], D[s]["ga"]) + 1


def phase(d, thr):
    return (d["gh"] < thr) & (d["ga"] < thr)


W = []
P = W.append
P("TOTAL: ANFANGS-BIAS IN FRUEHEREN SAISONS (2017-18 bis 2025-26, Regular Season, reines Modell, walk-forward)")
P("Messskript analysis/backtest_total_seasons.py (liest nur, aufbauend auf analysis/backtest_total.py). Fehler = Ist-Total minus Modell-Total (+ = es fiel mehr als das Modell denkt).")
P("Verlaengerungen sind in den Daten in allen Saisons ueber home_ot1 erkennbar; die Hauptzeilen enthalten alle Spiele (wie verlangt), 'ohne OT' ist zusaetzlich ausgewiesen.")
P("")

# ============================================================ 1+2 je Saison
signs = {}
for thr in (15, 10, 20):
    P(f"{'1/2' if thr == 15 else 'K'} PHASE 'ERSTE {thr}' GEGEN 'DANACH' JE SAISON" + ("" if thr == 15 else "  (Kontrolle)"))
    P(f"  {'Saison':8s} | {'n erste':>7s} {'Mittelwert [95 %]':>24s} {'Median [95 %]':>24s} {'ohne OT: Mittel':>16s} V. | {'n danach':>8s} {'Mittelwert [95 %]':>24s} {'Median [95 %]':>24s}")
    for s in SEASONS:
        d = D[s]; ph = phase(d, thr)
        e1, e2 = d["err"][ph], d["err"][~ph]
        m1, md1 = boot(e1, np.mean, 100 + s + thr), boot(e1, np.median, 200 + s + thr)
        m2, md2 = boot(e2, np.mean, 300 + s + thr), boot(e2, np.median, 400 + s + thr)
        e1n = d["err"][ph & ~d["ot"]]
        if thr == 15:
            signs[s] = np.sign(m1[0])
        P(f"  {label(s):8s} | {ph.sum():7d} {fmt(m1):>24s} {fmt(md1):>24s} {e1n.mean():+16.2f} {'+' if m1[0] > 0 else '-'}  | {(~ph).sum():8d} {fmt(m2):>24s} {fmt(md2):>24s}")
    allp = np.concatenate([D[s]["err"][phase(D[s], thr)] for s in SEASONS]); alll = np.concatenate([D[s]["err"][~phase(D[s], thr)] for s in SEASONS])
    allp_n = np.concatenate([D[s]["err"][phase(D[s], thr) & ~D[s]["ot"]] for s in SEASONS]); alll_n = np.concatenate([D[s]["err"][~phase(D[s], thr) & ~D[s]["ot"]] for s in SEASONS])
    pm, pmd = boot(allp, np.mean, 500 + thr), boot(allp, np.median, 510 + thr)
    lm, lmd = boot(alll, np.mean, 520 + thr), boot(alll, np.median, 530 + thr)
    dm, dmd = diff_ci(allp, alll, np.mean, 540 + thr), diff_ci(allp, alll, np.median, 550 + thr)
    P(f"  {'GEPOOLT':8s} | {len(allp):7d} {fmt(pm):>24s} {fmt(pmd):>24s} {allp_n.mean():+16.2f} {'+' if pm[0] > 0 else '-'}  | {len(alll):8d} {fmt(lm):>24s} {fmt(lmd):>24s}")
    P(f"  Gepoolt, Differenz 'erste {thr}' minus 'danach': Mittelwert {fmt(dm)}, Median {fmt(dmd)}; ohne OT: Mittelwert {allp_n.mean() - alll_n.mean():+.2f}")
    if thr == 15:
        pooled15 = (pm, pmd, dm, dmd)
        sign_pos = sum(1 for s in SEASONS if signs[s] > 0)
        sign_pos_med = sum(1 for s in SEASONS if np.median(D[s]["err"][phase(D[s], 15)]) > 0)
        pos_ex_ot = sum(1 for s in SEASONS if D[s]["err"][phase(D[s], 15) & ~D[s]["ot"]].mean() > 0)
        pos_excl2425 = pm
    P("")

# ============================================================ 4 Verlauf
P("4 VERLAUF: MITTLERER FEHLER NACH TEAMSPIEL-NUMMER (gepoolt 2017-18 bis 2025-26; Nummer = max(gp_h, gp_a) + 1)")
num = np.concatenate([D[s]["num"] for s in SEASONS]); err_all = np.concatenate([D[s]["err"] for s in SEASONS]); ot_all = np.concatenate([D[s]["ot"] for s in SEASONS])
blocks = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 30), (31, 99)]
P(f"  {'Spiel-Nr.':>10s} {'n':>6s} {'Mittelwert [95 %]':>24s} {'Median [95 %]':>24s} {'ohne OT: Mittel':>16s} {'Ø Modell-Total':>15s}")
mu_all = np.concatenate([D[s]["mu"] for s in SEASONS])
for i, (lo, hi) in enumerate(blocks):
    mk = (num >= lo) & (num <= hi)
    t1, t2 = boot(err_all[mk], np.mean, 600 + i), boot(err_all[mk], np.median, 610 + i)
    P(f"  {(str(lo) + '-' + str(hi)) if hi < 99 else '31+ (danach)':>10s} {mk.sum():6d} {fmt(t1):>24s} {fmt(t2):>24s} {err_all[mk & ~ot_all].mean():+16.2f} {mu_all[mk].mean():15.1f}")
P("  Je Saison, Mittelwert der Bloecke 1-5 / 6-10 / 11-15 / 16-20 / 21-30 / 31+:")
for s in SEASONS:
    d = D[s]
    P(f"    {label(s)}: " + " / ".join((f"{d['err'][(d['num'] >= lo) & (d['num'] <= hi)].mean():+.1f}" if ((d['num'] >= lo) & (d['num'] <= hi)).any() else "n/a") for lo, hi in blocks))
P("")


# ============================================================ 5 Kalibrierung
def fit_w(z, y, w, iters=40):
    X = np.column_stack([np.ones_like(z), z]); beta = np.array([0.0, 1.0])
    for _ in range(iters):
        m = 1 / (1 + np.exp(-X @ beta)); Wt = np.clip(m * (1 - m), 1e-9, None) * w
        step = np.linalg.solve(X.T @ (X * Wt[:, None]) + 1e-9 * np.eye(2), X.T @ (w * (y - m)))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


def calib(mu, tot, seed, bc=500):
    n = len(mu)
    L = mu[:, None] + KS[None, :]
    p = 1.0 - ndtr((L - mu[:, None]) / SIG)
    y = (tot[:, None] > L + 1e-9).astype(float)
    ok = np.abs(tot[:, None] - L) >= 1e-9
    gi, ki = np.nonzero(ok)
    pv, yv = p[gi, ki], y[gi, ki]
    z = np.log(np.clip(pv, 1e-6, 1 - 1e-6) / (1 - np.clip(pv, 1e-6, 1 - 1e-6)))
    signed = (yv.mean() - pv.mean()) * 100
    bins = np.clip(np.digitize(pv, EDGES[1:-1]), 0, len(EDGES) - 2)
    devs, ws, big, detail = [], [], [], []
    for j in range(len(EDGES) - 1):
        m = bins == j
        if m.sum() > 0:
            dv = (yv[m].mean() - pv[m].mean()) * 100
            detail.append((EDGES[j], EDGES[j + 1], int(m.sum()), pv[m].mean(), yv[m].mean(), dv))
            if m.sum() >= 20:
                devs.append(abs(dv)); ws.append(m.sum())
            if m.sum() >= 100 and abs(dv) > 6:
                big.append(f"{int(round(EDGES[j]*100))}-{int(round(EDGES[j+1]*100))} %")
    base = fit_w(z, yv, np.ones(len(yv)))
    r = np.random.default_rng(seed)
    bs = np.array([fit_w(z, yv, np.bincount(r.integers(0, n, n), minlength=n).astype(float)[gi]) for _ in range(bc)])
    return dict(n=len(yv), games=n, signed=signed, mad=float(np.average(devs, weights=ws)) if devs else float("nan"), big=big, a=base[0], b=base[1],
                ca=np.percentile(bs[:, 0], [2.5, 97.5]), cb=np.percentile(bs[:, 1], [2.5, 97.5]), detail=detail)


P("5 KALIBRIERUNG DER OVER-CHANCE IN DER PHASE 'ERSTE 15' (Hauptlinie und 1 bis 5 Punkte darunter, ohne Pushes, Sigma 18,6)")
pm_tr = np.concatenate([D[s]["mu"][phase(D[s], 15)] for s in SEASONS[:-1]]); pt_tr = np.concatenate([D[s]["tot"][phase(D[s], 15)] for s in SEASONS[:-1]])
pm_te, pt_te = D[2025]["mu"][phase(D[2025], 15)], D[2025]["tot"][phase(D[2025], 15)]
for nm, m_, t_, sd, bc in (("GEPOOLT 2017-18 bis 2024-25", pm_tr, pt_tr, 700, 500), ("2025-26", pm_te, pt_te, 710, 1000)):
    c = calib(m_, t_, sd, bc)
    P(f"  {nm}: Spiele {c['games']}, Zeilen {c['n']}")
    P(f"    {'Stufe':>9s} {'n':>6s} {'Modell':>7s} {'Treffer':>8s} {'Abw. PP':>8s}  Hinweis")
    for lo, hi, nn, pmean, hr, dv in c["detail"]:
        P(f"    {int(round(lo*100)):>3d}-{int(round(hi*100)):<3d}% {nn:6d} {pmean:7.3f} {hr:8.3f} {dv:+8.2f}  {'nicht aussagekraeftig (< 20)' if nn < 20 else ''}")
    ok = c["mad"] < 3 and not c["big"]
    P(f"    Abweichung gesamt {c['signed']:+.2f} PP, Ø |Stufe| (>= 20) {c['mad']:.2f} PP; Stufen >= 100 Zeilen mit > 6 PP: {', '.join(c['big']) or 'keine'} -> Massstab {'ERFUELLT' if ok else 'NICHT erfuellt'}")
    P(f"    Rekalibrierung: b = {c['b']:.2f} [{c['cb'][0]:.2f}; {c['cb'][1]:.2f}] ({'1 im Intervall' if c['cb'][0] <= 1 <= c['cb'][1] else '1 AUSSERHALB'}), a = {c['a']:+.3f} [{c['ca'][0]:+.3f}; {c['ca'][1]:+.3f}] ({'0 im Intervall' if c['ca'][0] <= 0 <= c['ca'][1] else '0 AUSSERHALB'})")
P("")

# ============================================================ Entscheidung
pm, pmd, dm, dmd = pooled15
cond_sign = sign_pos >= 6
cond_ci = pm[1] > 0                 # Intervall muss die 0 ausschliessen UND positiv sein (Richtung wie 2025-26)
opposite = pm[2] < 0
P("4/ZUSAMMENFASSUNG UND ENTSCHEIDUNG")
P("  Vorzeichen des Mittelwerts 'erste 15' je Saison: " + ", ".join(f"{label(s)} {'+' if signs[s] > 0 else '-'}" for s in SEASONS) + f"  -> positiv (wie 2025-26) in {sign_pos} von 9 (Median: {sign_pos_med} von 9; ohne OT: {pos_ex_ot} von 9).")
P(f"  Gepoolt 'erste 15': Mittelwert {fmt(pm)}, Median {fmt(pmd)}; Differenz zu 'danach': Mittelwert {fmt(dm)}, Median {fmt(dmd)}.")
pre = np.concatenate([D[s]["err"][phase(D[s], 15)] for s in SEASONS[:-1]])
P(f"  Gepoolt nur 2017-18 bis 2024-25 'erste 15': Mittelwert {fmt(boot(pre, np.mean, 900))}, Median {fmt(boot(pre, np.median, 901))} (n {len(pre)}).")
P(f"  Regel: Vorzeichen in >= 6 von 9: {'erfuellt' if cond_sign else 'NICHT erfuellt'}; gepooltes Intervall {'schliesst 0 aus UND ist positiv' if cond_ci else ('schliesst 0 aus, aber mit UMGEKEHRTEM Vorzeichen (negativ: frueh weniger Punkte als das Modell denkt)' if opposite else 'schliesst 0 ein')}.")
passed = cond_sign and cond_ci
P(f"  => {'ECHTER MODELLFEHLER' if passed else 'kein echter Modellfehler: gilt als Zufall von 2025-26'}.")
P("")
if passed:
    P("6 KORREKTURTEST (Aufschlag auf das Modell-Total in den ersten 15 Spielen, bestimmt auf 2017-2024, geprueft auf 2025-26; nur Spiele der Phase)")
    add = float(np.concatenate([D[s]["err"][phase(D[s], 15)] for s in SEASONS[:-1]]).mean())
    L = pm_te[:, None] + KS[None, :]
    yy = (pt_te[:, None] > L + 1e-9).astype(float); okc = np.abs(pt_te[:, None] - L) >= 1e-9

    def sc(shift):
        p = np.clip(1.0 - ndtr((L - (pm_te + shift)[:, None]) / SIG), 1e-6, 1 - 1e-6)
        return np.where(okc, (p - yy) ** 2, 0).sum(1) / okc.sum(1), np.where(okc, -(yy * np.log(p) + (1 - yy) * np.log(1 - p)), 0).sum(1) / okc.sum(1)
    b0, l0 = sc(0.0); b1, l1 = sc(add)
    db, dl = b1 - b0, l1 - l0
    r = np.random.default_rng(800)
    ix = r.integers(0, len(db), (B, len(db)))
    P(f"  Aufschlag {add:+.2f} Punkte (Mittel 2017-24, Phase 'erste 15'); Spiele 2025-26 in der Phase: {len(db)}")
    P(f"  Brier neu minus heute {db.mean()*1000:+.2f} x10^-3 [{np.percentile(db[ix].mean(1), 2.5)*1000:+.2f}; {np.percentile(db[ix].mean(1), 97.5)*1000:+.2f}], Log-Loss {dl.mean()*1000:+.2f} [{np.percentile(dl[ix].mean(1), 2.5)*1000:+.2f}; {np.percentile(dl[ix].mean(1), 97.5)*1000:+.2f}]")
else:
    P("6 KORREKTURTEST: nicht durchgefuehrt (Regel nicht bestanden).")
OUT.write_text("\n".join(W) + "\n", encoding="utf-8")
print("\n".join(W))
