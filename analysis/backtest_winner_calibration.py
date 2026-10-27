"""
Favoriten-Kalibrierung des Sieger-Modells (Moneyline), Regular Season 2025-26. NUR LESEND: data/cache, schreibt nur analysis/reports/winner_calibration_2025-26.txt.
Keine API-Calls, am Modell wird nichts geaendert. Baut auf analysis/backtest_winner.py auf (gleiches Replay der Produktiv-Engine, gleiche Siegchance = Normalverteilung um den
Spread, Sigma 13,2, 3-97 %, Spread auf 1 Nachkommastelle gerundet; nur Wissen vor dem Spiel). Reines Modell ohne Markt-Mischung, nur echte Ergebnisse, keine Quoten.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_winner_calibration.py

1 Favoriten-Sicht in 5-%-Stufen (50-100 %), Differenz Trefferquote minus Modell in PP mit Bootstrap-Intervall.
2 Logistische Rekalibrierung: logit P(Heim gewinnt) = a + b * logit(p_Modell), Maximum-Likelihood (Newton), Bootstrap-Intervalle (nach Spielen, 2000 Ziehungen). b > 1: Modell zu vorsichtig.
  Zusaetzlich b mit a = 0 (nur Steigung).
3 Zwei Haelften: Regular-Season-Spiele chronologisch (Datum, ID), erste Haelfte = erste n/2 Spiele. 1 und 2 je Haelfte.
4 Sigma-Test: Sigma 11,0 bis 14,5 (Schritt 0,5). Bestes Sigma nach Brier auf Haelfte A bestimmen, auf Haelfte B gegen 13,2 pruefen (Brier-Differenz mit gepaartem Bootstrap); dann vertauscht.
"""
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.stats import norm

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_winner as bw  # noqa: E402
from bt_common import load_games, logloss  # noqa: E402
import replica_tunable as rt  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR, MAX_WIN_PROB, MIN_WIN_PROB  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402

OUT = HERE / "reports" / "winner_calibration_2025-26.txt"
SIGMAS = [round(11.0 + 0.5 * i, 1) for i in range(8)]
B = 2000
BREF = lp.SPREAD_SIGMA


def pct(x, d=1):
    return f"{100 * x:.{d}f}"


def win_p(mu, sigma):
    return np.clip(norm.cdf(np.round(mu, 1) / sigma), MIN_WIN_PROB, MAX_WIN_PROB)


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_logistic(z, y, slope_only=False, iters=50):
    """MLE von P(y=1) = sigmoid(a + b z) bzw. sigmoid(b z). Rueckgabe (a, b)."""
    X = z[:, None] if slope_only else np.column_stack([np.ones_like(z), z])
    beta = np.zeros(X.shape[1])
    if slope_only:
        beta[0] = 1.0
    else:
        beta[1] = 1.0
    for _ in range(iters):
        mu = 1 / (1 + np.exp(-X @ beta))
        W = np.clip(mu * (1 - mu), 1e-9, None)
        H = X.T @ (X * W[:, None]) + 1e-9 * np.eye(len(beta))
        step = np.linalg.solve(H, X.T @ (y - mu))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return (0.0, float(beta[0])) if slope_only else (float(beta[0]), float(beta[1]))


def boot_idx(n, seed):
    return np.random.default_rng(seed).integers(0, n, (B, n))


def recal(p, y, seed=0):
    z = logit(p)
    a, b = fit_logistic(z, y)
    _, b0 = fit_logistic(z, y, slope_only=True)
    idx = boot_idx(len(p), seed)
    ab = np.array([fit_logistic(z[i], y[i]) for i in idx])
    b0s = np.array([fit_logistic(z[i], y[i], slope_only=True)[1] for i in idx])
    q = lambda v: (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
    return {"a": a, "a_ci": q(ab[:, 0]), "b": b, "b_ci": q(ab[:, 1]), "b0": b0, "b0_ci": q(b0s)}


def fav_table(p, y, seed=0):
    q, hit = np.maximum(p, 1 - p), np.where(p >= 0.5, y, 1 - y)
    edges = [round(0.5 + 0.05 * i, 2) for i in range(11)]
    rows = []
    for k, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        m = (q >= lo) & ((q < hi) if hi < 1.0 else (q <= hi))
        if m.sum():
            d = (hit[m] - q[m])
            idx = boot_idx(int(m.sum()), seed + k)
            bs = d[idx].mean(axis=1)
            rows.append((lo, hi, int(m.sum()), float(q[m].mean()), float(hit[m].mean()), float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))))
    return rows


def fav_lines(rows, title):
    out = [title, f"  {'Stufe':>10}{'Spiele':>8}{'Ø Modell %':>12}{'Treffer %':>11}{'Diff PP':>9}{'95 %-Intervall PP':>22}  Hinweis"]
    for lo, hi, n, pm, hr, d, l, h in rows:
        note = ("0 im Intervall" if l <= 0 <= h else ("Treffer ÜBER Modell" if d > 0 else "Treffer UNTER Modell")) + (", wenige Spiele (n < 20)" if n < 20 else "")
        out.append(f"  {pct(lo, 0) + '-' + pct(hi, 0) + ' %':>10}{n:>8}{pct(pm):>12}{pct(hr):>11}{100 * d:>+9.1f}{'[' + format(100 * l, '+.1f') + '; ' + format(100 * h, '+.1f') + ']':>22}  {note}")
    return out


def overall(p, y):
    q, hit = np.maximum(p, 1 - p), np.where(p >= 0.5, y, 1 - y)
    d = hit - q
    bs = d[boot_idx(len(p), 11)].mean(axis=1)
    return {"n": len(p), "brier": float(np.mean((p - y) ** 2)), "ll": float(np.mean(logloss(p, y))), "fav_q": float(q.mean()), "fav_hit": float(hit.mean()), "d": float(d.mean()),
            "d_ci": (float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)))}


def section(label, p, y, seed):
    o = overall(p, y)
    r = recal(p, y, seed)
    L = [f"{label}", f"  Spiele {o['n']}, Brier {o['brier']:.4f}, Log-Loss {o['ll']:.4f}",
         f"  Favorit: Ø Modell-Chance {pct(o['fav_q'])} %, Trefferquote {pct(o['fav_hit'])} %, Differenz {100 * o['d']:+.1f} PP [{100 * o['d_ci'][0]:+.1f}; {100 * o['d_ci'][1]:+.1f}]",
         f"  Rekalibrierung logit P(Heim) = a + b*logit(p):  Steigung b = {r['b']:.2f} [{r['b_ci'][0]:.2f}; {r['b_ci'][1]:.2f}],  Achsenabschnitt a = {r['a']:+.2f} [{r['a_ci'][0]:+.2f}; {r['a_ci'][1]:+.2f}]",
         f"  nur Steigung (a = 0):   b = {r['b0']:.2f} [{r['b0_ci'][0]:.2f}; {r['b0_ci'][1]:.2f}]   ({verdict(r['b_ci'])})", ""]
    L += fav_lines(fav_table(p, y, seed * 100), "  Favoriten-Sicht, 5-%-Stufen")
    L.append("")
    return L, r, o


def verdict(ci):
    return "1 liegt im Intervall: kalibriert" if ci[0] <= 1 <= ci[1] else ("Steigung ÜBER 1: Modell zu vorsichtig" if ci[0] > 1 else "Steigung UNTER 1: Modell zu sicher")


def brier_of(mu, y, s):
    return (win_p(mu, s) - y) ** 2


def sigma_block(name, mu_a, y_a, mu_b, y_b, seed):
    """Bestes Sigma nach Brier auf A, Pruefung auf B gegen BREF."""
    sc = {s: float(brier_of(mu_a, y_a, s).mean()) for s in SIGMAS}
    best = min(sc, key=sc.get)
    d = brier_of(mu_b, y_b, best) - brier_of(mu_b, y_b, BREF)
    bs = d[boot_idx(len(d), seed)].mean(axis=1)
    L = [f"  {name}: bestes Sigma auf der Anpassungs-Hälfte (n {len(y_a)}) nach Brier = {best:.1f} (Brier {sc[best]:.4f}; mit {BREF}: {sc.get(BREF, float(brier_of(mu_a, y_a, BREF).mean())):.4f})",
         f"    Prüfung auf der anderen Hälfte (n {len(y_b)}): Brier mit Sigma {best:.1f} = {float(brier_of(mu_b, y_b, best).mean()):.4f}, mit {BREF} = {float(brier_of(mu_b, y_b, BREF).mean()):.4f}; "
         f"Differenz (neu minus 13,2) {d.mean() * 1000:+.2f} x10^-3 [{np.percentile(bs, 2.5) * 1000:+.2f}; {np.percentile(bs, 97.5) * 1000:+.2f}] -> "
         + ("besser (Intervall unter 0)" if np.percentile(bs, 97.5) < 0 else "schlechter (Intervall über 0)" if np.percentile(bs, 2.5) > 0 else "nicht unterscheidbar (Intervall schließt 0 ein)") + ("; gleiches Sigma, keine Änderung" if best == BREF else "")]
    return L, best


def main():
    games = load_games(2015, 2025)
    rows, _, _, _ = rt.run(games, **bw.PRODUCTION)
    sel = np.where(rows["season"] == bw.SEASON)[0]
    sel = sel[rows["post"][sel].astype(int) == 0]
    order = sorted(range(len(sel)), key=lambda k: (games[sel[k]]["date"][:10], games[sel[k]]["id"]))
    sel = sel[order]
    mu = rows["diff"][sel] / ELO_TO_SPREAD_FACTOR
    y = (rows["margin"][sel] > 0).astype(float)
    dates = [games[i]["date"][:10] for i in sel]
    p = np.array([lp.win_prob_home(round(float(x), 1)) for x in mu])
    assert np.allclose(p, win_p(mu, BREF)), "Nachbau der Siegchance weicht von engine.line_probabilities ab"
    n = len(sel)
    h = (n + 1) // 2
    A, Bm = slice(0, h), slice(h, n)
    L = [f"FAVORITEN-KALIBRIERUNG DES SIEGER-MODELLS, REGULAR SEASON 2025-26 — erstellt {datetime.now():%Y-%m-%d %H:%M} (analysis/backtest_winner_calibration.py)",
         "Reines Modell ohne Markt-Mischung, Siegchance wie die App (Normalverteilung um den Spread, Sigma 13,2, 3-97 %), Replay der Produktiv-Engine, nur Wissen vor dem Spiel, nur echte Ergebnisse. Keine Änderung am Modell.",
         f"Spiele: {n}. Hälfte 1: {h} Spiele ({dates[0]} bis {dates[h - 1]}), Hälfte 2: {n - h} Spiele ({dates[h]} bis {dates[-1]}); geteilt nach Anzahl in Datumsreihenfolge (ein Spieltag kann an der Grenze geteilt sein).",
         "Intervalle: Bootstrap nach Spielen, 95 %, 2000 Ziehungen. Steigung b > 1 heißt: Modell zu vorsichtig (echte Chancen extremer als die Modell-Chancen); b < 1: Modell zu sicher.",
         "Stufen mit weniger als 20 Spielen: das Intervall ist nicht aussagekräftig (bei lauter Treffern schwankt nur noch die Modell-Chance), bitte ignorieren.", ""]
    res = {}
    for label, sl, sd in (("1+2. GANZE SAISON (Regular Season)", slice(0, n), 1), ("3a. HÄLFTE 1", A, 2), ("3b. HÄLFTE 2", Bm, 3)):
        ls, r, o = section(label, p[sl], y[sl], sd)
        L += ls
        res[label] = (r, o)
    r1, r2 = res["3a. HÄLFTE 1"][0], res["3b. HÄLFTE 2"][0]
    full = res["1+2. GANZE SAISON (Regular Season)"][0]
    L += ["ZWISCHENFAZIT (nur Beschreibung)",
          f"  Steigung b: ganze Saison {full['b']:.2f} [{full['b_ci'][0]:.2f}; {full['b_ci'][1]:.2f}], Hälfte 1 {r1['b']:.2f} [{r1['b_ci'][0]:.2f}; {r1['b_ci'][1]:.2f}], Hälfte 2 {r2['b']:.2f} [{r2['b_ci'][0]:.2f}; {r2['b_ci'][1]:.2f}]",
          f"  Bewertung: ganze Saison — {verdict(full['b_ci'])}; Hälfte 1 — {verdict(r1['b_ci'])}; Hälfte 2 — {verdict(r2['b_ci'])}", ""]
    L.append("4. SIGMA-TEST (Sigma 11,0 bis 14,5; Brier x10^-3, kleiner ist besser)")
    L.append(f"  {'Sigma':>6}{'Hälfte 1':>11}{'Hälfte 2':>11}{'Saison':>10}{'Log-Loss ges.':>15}")
    for s in SIGMAS + ([BREF] if BREF not in SIGMAS else []):
        b1, b2, ba = (float(brier_of(mu[sl], y[sl], s).mean()) * 1000 for sl in (A, Bm, slice(0, n)))
        ll = float(logloss(win_p(mu, s), y).mean())
        L.append(f"  {s:>6.1f}{b1:>11.2f}{b2:>11.2f}{ba:>10.2f}{ll:>15.4f}{'   <- aktuell (13,2)' if s == BREF else ''}")
    L.append("  (Sigma 13,2 liegt nicht im 0,5er-Raster und ist deshalb zusätzlich aufgeführt.)")
    L.append("")
    b_ab, best_ab = sigma_block("Anpassen auf Hälfte 1, prüfen auf Hälfte 2", mu[A], y[A], mu[Bm], y[Bm], 21)
    b_ba, best_ba = sigma_block("Vertauscht: anpassen auf Hälfte 2, prüfen auf Hälfte 1", mu[Bm], y[Bm], mu[A], y[A], 22)
    L += b_ab + b_ba
    L += ["", "Hinweis: reine Messung, keine Empfehlung und keine Änderung am Modell. Ein Sigma-Optimum auf einer Hälfte (~620 Spiele) ist selbst verrauscht; zählen sollte nur, was auf der jeweils anderen Hälfte hält."]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
