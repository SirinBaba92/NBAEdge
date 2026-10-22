"""
Pruefung der Streuungen (Sigma) in engine/line_probabilities.py: SPREAD_SIGMA 10,5, TOTAL_SIGMA 18,0, TEAM_TOTAL_SIGMA 12,5. Nur lesend: data/cache, keine API-Calls,
keine Produktivdatei wird veraendert. Schreibt nur analysis/results/sigma_check.json (klein).

Aufruf (aus dem Projektordner):  venv/bin/python analysis/sigma_check.py

Daten: Regular Season 2017-2025, Nachbau der produktiven ELO-Engine (Walk-forward: jede Prognose entsteht vor dem Spiel aus frueheren Spielen).
  Spread-Prognose mu = Rating-Differenz / 50 (wie die Engine OHNE Markt-Mischung), Total = Off/Def-EMA wie models/elo.py, Teampunkte (Total +- Spread) / 2,
  Siegwahrscheinlichkeit = Logistik + Isotonik je Saison nur auf frueheren Saisons (wie tuning_baseline.py). Ausgang = Endstand incl. Verlaengerung.
Fenster wie die frueheren Analysen: alle 2017-2025 | a erste 20 Spiele je Team 2023-25 | b alle 2023-25 | c1 erste 20 Spiele 2021/22 | c2 alle 2021/22.
Ereignis "Heim deckt Linie L": Marge > L mit L = floor(mu) + 0,5 + k, k = -8..+8 (Spread); Total Over mit L = floor(mu) + 0,5 + k, k = -16..16 (Schritt 2); Team Total Over k = -10..10 (Schritt 2).
Wahrscheinlichkeit = 1 - Phi((L - mu) / sigma). Bewertung: Log-Loss ueber alle Linien (Mittel je Spiel), Kalibrierungs-Steigung (Logistik des Ausgangs auf logit(p); 1 = ideal, < 1 = zu sicher).
Intervalle: Bootstrap ueber Spiele (95 %, 1000 Ziehungen).
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy import optimize, stats
from scipy.special import expit, ndtr, ndtri

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import RESULTS, load_games, window  # noqa: E402
import old_engine_replica as old  # noqa: E402
import tuning_baseline as tb  # noqa: E402

N_BOOT = 1000
SIGMA_GRID = np.round(np.arange(8.0, 28.0001, 0.2), 2)
WINDOWS = [("alle_2017-25", None, False), ("a_erste20_2023-25", [2023, 2024, 2025], True), ("b_alle_2023-25", [2023, 2024, 2025], False),
           ("c1_erste20_2021-22", [2021, 2022], True), ("c2_alle_2021-22", [2021, 2022], False)]


def ll(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def thresholds(mu, ks):
    return np.floor(mu)[:, None] + 0.5 + np.asarray(ks, float)[None, :]


def loss_matrix(mu, x, ks, sigmas):
    """Mittleres Log-Loss je Spiel (ueber die Linien) fuer jedes Sigma: Form (n, len(sigmas)). Ereignis: x > L."""
    L = thresholds(mu, ks)
    y = (x[:, None] > L).astype(float)
    out = np.empty((len(mu), len(sigmas)))
    for j, s in enumerate(sigmas):
        p = 1.0 - ndtr((L - mu[:, None]) / s)
        out[:, j] = ll(p, y).mean(axis=1)
    return out


def cal_slope(mu, x, ks, sigma):
    """Kalibrierungs-Steigung und -Achsenabschnitt (Logistik des Ausgangs auf logit(p)); 1 / 0 = ideal."""
    L = thresholds(mu, ks)
    y = (x[:, None] > L).astype(float).ravel()
    p = np.clip(1.0 - ndtr((L - mu[:, None]) / sigma), 1e-6, 1 - 1e-6).ravel()
    z = np.log(p / (1 - p))
    f = lambda b: float(np.mean(ll(expit(b[0] + b[1] * z), y)))
    r = optimize.minimize(f, [0.0, 1.0], method="BFGS")
    return float(r.x[1]), float(r.x[0])


def boot_argmin(M, grid, seed=0):
    """Sigma, das das Log-Loss minimiert, mit 95-%-Bootstrap-Intervall (Ziehen von Spielen)."""
    rng = np.random.default_rng(seed)
    n = M.shape[0]
    best = grid[int(np.argmin(M.mean(axis=0)))]
    draws = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, n, n)
        draws.append(grid[int(np.argmin(M[idx].mean(axis=0)))])
    return float(best), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def boot_mean(v, seed=0):
    rng = np.random.default_rng(seed)
    n = len(v)
    m = [v[rng.integers(0, n, n)].mean() for _ in range(N_BOOT)]
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def normality(e):
    s = float(np.std(e))
    z = e / s
    return {"mittel": float(e.mean()), "sd": s, "schiefe": float(stats.skew(e)), "ueberschuss_woelbung": float(stats.kurtosis(e)),
            "anteil_ueber_2sd": float(np.mean(np.abs(z) > 2)), "normal_2sd": 0.0455, "anteil_ueber_3sd": float(np.mean(np.abs(z) > 3)), "normal_3sd": 0.0027,
            "sd_aus_mad": float(1.4826 * np.median(np.abs(e - np.median(e)))), "mae": float(np.mean(np.abs(e))),
            "quantile_z": {str(q): [float(np.quantile(z, q)), float(ndtri(q))] for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)}}


def level_dependence(level, e, edges, signed_by=None):
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (level >= lo) & (level < hi)
        if m.sum() < 20:
            continue
        ee = e[m] * (np.sign(signed_by[m]) if signed_by is not None else 1.0)
        rows.append({"von": float(lo), "bis": float(hi), "n": int(m.sum()), "mittlerer_fehler": float(ee.mean()), "sd": float(e[m].std()), "mae": float(np.abs(e[m]).mean())})
    sl = float(np.polyfit(level, e ** 2, 1)[0])
    return {"klassen": rows, "steigung_fehler_quadrat_auf_niveau": sl, "levene_p": float(stats.levene(*[e[(level >= lo) & (level < hi)] for lo, hi in zip(edges[:-1], edges[1:]) if ((level >= lo) & (level < hi)).sum() >= 20]).pvalue)}


def eval_market(name, mu, x, ks, named, extra_dep=None, signed=None, edges=None):
    M = loss_matrix(mu, x, ks, SIGMA_GRID)
    res = {"n": int(len(mu)), "fehler": normality(x - mu)}
    best, lo, hi = boot_argmin(M, SIGMA_GRID)
    res["sigma_min_logloss"] = {"wert": best, "ci95": [lo, hi]}
    sig = {}
    for s in sorted(set(named) | {round(best, 1)}):
        j = int(np.argmin(np.abs(SIGMA_GRID - s)))
        v = M[:, j]
        slope, icpt = cal_slope(mu, x, ks, float(SIGMA_GRID[j]))
        sig[str(s)] = {"logloss": boot_mean(v), "kalibrierung_steigung": slope, "achsenabschnitt": icpt}
    res["sigma_vergleich"] = sig
    if edges is not None:
        res["abhaengigkeit_vom_niveau"] = level_dependence(signed if signed is not None else mu, x - mu, edges, signed_by=mu if signed is not None else None)
    return res


def main():
    games = load_games()
    o, _ = old.run(games, **tb.PRODUCTION)
    tp, _, _ = tb.total_predictions(games, tb.PRODUCTION["total_alpha"])
    seasons = list(range(2017, 2026))
    p_all = tb.walk_forward_probs(o, seasons)
    mu_m = o["diff"] / 50.0
    margin, total, hw = o["margin"], o["total"], o["hw"]
    mu_h, mu_a = (tp + mu_m) / 2, (tp - mu_m) / 2
    act_h, act_a = (total + margin) / 2, (total - margin) / 2
    out = {"version": 1, "ereignis_linien": {"spread": "-8..8 Schritt 1", "total": "-16..16 Schritt 2", "team_total": "-10..10 Schritt 2"}, "fenster": {}}
    for wname, ss, early in WINDOWS:
        base = (o["post"] == 0) & (o["season"] >= 2017)
        if ss is not None:
            m = np.zeros(len(base), bool)
            for S in ss:
                m |= window(o, S, early)
            base = m
        W = {"n_spiele": int(base.sum())}
        # ---------------- 1. Spread
        mu, x = mu_m[base], margin[base]
        W["spread"] = eval_market("spread", mu, x, range(-8, 9), (10.5, 12.0, 13.0, 13.9))
        W["spread"]["abhaengigkeit_vom_niveau"] = level_dependence(np.abs(mu), x - mu, np.array([0, 2, 4, 6, 8, 100.0]), signed_by=mu)
        # ---------------- 2. Siegwahrscheinlichkeit gegen Normalverteilung um den Spread (Linie 0)
        p, y = p_all[base], hw[base]
        ok = ~np.isnan(p)
        mu2, y2, p2 = mu[ok], y[ok], p[ok]
        win = {"n": int(ok.sum()), "logistik_kalibriert": {"logloss": boot_mean(ll(p2, y2)), "brier": float(np.mean((p2 - y2) ** 2)), "mittel_p": float(p2.mean()), "heimquote": float(y2.mean())}}
        Mw = np.column_stack([ll(1 - ndtr(-mu2 / s), y2) for s in SIGMA_GRID])
        sbest, slo, shi = boot_argmin(Mw, SIGMA_GRID, seed=1)
        win["sigma_min_logloss_siegwahrscheinlichkeit"] = {"wert": sbest, "ci95": [slo, shi]}
        for s in sorted({10.5, 12.0, 13.0, 13.9, round(sbest, 1)}):
            pn = ndtr(mu2 / s)
            win[f"normal_sigma_{s}"] = {"logloss": boot_mean(ll(pn, y2)), "brier": float(np.mean((pn - y2) ** 2)), "mittel_p": float(pn.mean()),
                                        "mittlere_abw_zu_logistik": float(np.mean(np.abs(pn - p2))), "max_abw_zu_logistik": float(np.max(np.abs(pn - p2)))}
        edges = np.array([-100, -10, -6, -3, 0, 3, 6, 10, 100.0])
        tab = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            mk = (mu2 >= lo) & (mu2 < hi)
            if mk.sum() < 20:
                continue
            tab.append({"spread_von": float(lo), "bis": float(hi), "n": int(mk.sum()), "tatsaechlich_heimsieg": float(y2[mk].mean()), "logistik_mittel_p": float(p2[mk].mean()),
                        "normal_10_5": float(ndtr(mu2[mk] / 10.5).mean()), "normal_13_9": float(ndtr(mu2[mk] / 13.9).mean()), f"normal_{round(sbest, 1)}": float(ndtr(mu2[mk] / round(sbest, 1)).mean())})
        win["tabelle_nach_spread"] = tab
        near = (mu2 >= 7.1) & (mu2 <= 9.1)
        win["beispiel_spread_8_1"] = {"n": int(near.sum()), "tatsaechlich_heimsieg": float(y2[near].mean()), "logistik_mittel_p": float(p2[near].mean()),
                                      "normal_10_5": float(ndtr(8.1 / 10.5)), "normal_13_9": float(ndtr(8.1 / 13.9)), f"normal_{round(sbest, 1)}": float(ndtr(8.1 / round(sbest, 1)))}
        sg = 13.2
        pn = ndtr(mu2 / sg)
        d = np.abs(pn - p2)
        mu_eff = sg * ndtri(np.clip(p2, 1e-6, 1 - 1e-6))
        win["konsistenz_sigma_13_2"] = {"anteil_verschiedene_seite_50": float(np.mean((pn > 0.5) != (p2 > 0.5))), "abw_mittel": float(d.mean()), "abw_p50": float(np.quantile(d, .5)),
                                        "abw_p90": float(np.quantile(d, .9)), "abw_p99": float(np.quantile(d, .99)), "abw_max": float(d.max()),
                                        "effektive_marge_abw_mittel": float(np.mean(np.abs(mu_eff - mu2))), "effektive_marge_abw_p90": float(np.quantile(np.abs(mu_eff - mu2), .9)),
                                        "effektive_marge_abw_p99": float(np.quantile(np.abs(mu_eff - mu2), .99)), "logistik_minus_normal_mittel": float(np.mean(p2 - pn))}
        W["siegwahrscheinlichkeit"] = win
        # ---------------- 3. Total und Team Total
        mt, xt = tp[base], total[base]
        W["total"] = eval_market("total", mt, xt, range(-16, 17, 2), (18.0,), edges=np.r_[np.quantile(mt, [0, .2, .4, .6, .8]), np.quantile(mt, 1.0) + 1e-6])
        W["total"]["regression_ergebnis_auf_prognose"] = {"steigung": float(np.polyfit(mt, xt, 1)[0]), "achsenabschnitt": float(np.polyfit(mt, xt, 1)[1])}
        mm = np.concatenate([mu_h[base], mu_a[base]])
        xx = np.concatenate([act_h[base], act_a[base]])
        W["team_total"] = eval_market("team_total", mm, xx, range(-10, 11, 2), (12.5,), edges=np.r_[np.quantile(mm, [0, .2, .4, .6, .8]), np.quantile(mm, 1.0) + 1e-6])
        out["fenster"][wname] = W
        print(f"{wname}: n={W['n_spiele']}  spread sigma*={W['spread']['sigma_min_logloss']['wert']:.1f} ci={W['spread']['sigma_min_logloss']['ci95']}  "
              f"sieg sigma*={sbest:.1f}  total sigma*={W['total']['sigma_min_logloss']['wert']:.1f}  team sigma*={W['team_total']['sigma_min_logloss']['wert']:.1f}", flush=True)
    p = RESULTS / "sigma_check.json"
    p.write_text(json.dumps(out, indent=1))
    print("geschrieben:", p, f"({p.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
