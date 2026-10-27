"""
Backtest der Team-Maerkte fuer die Saison 2025-26 (Walk-forward). NUR LESEND: liest data/cache (games_2015 bis games_2025), schreibt nur
analysis/results/backtest_team_2025-26.json und analysis/results/backtest_team_2025-26.txt. Keine API-Calls, Produktivcode und Produktivdateien bleiben unveraendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_team_markets.py            Selbsttest:  venv/bin/python analysis/backtest_team_markets.py --selftest

WICHTIG (Grenzen): Bewertet wird NUR das REINE MODELL ohne Markt-Mischung. Die App mischt den Markt dazu (Spread 25 %, Total 32 bis 55 %); der Fehler der angezeigten Zahlen ist dadurch
eher kleiner. Historische Quoten/Linien gibt es nicht; die Linien sind ein Raster um den Modell-Mittelwert (Hauptlinie = Mittelwert auf x,5 gerundet, +-1 bis +-5 Punkte).

Verfahren
- Replay: analysis/replica_tunable.run (Produktivparameter = Standardwerte, kausaler Nachbau der ELO-Engine ueber alle Spiele ab 2015; Kontrolle gegen old_engine_replica). Vor jedem Spiel
  liefert er diff (ELO-Differenz inkl. Heimvorteil, Ruhetage, Form) und total_pred (Off/Def-EMA, Playoffs nicht eingerechnet wie in models/elo.py).
- Spread-Mittelwert = diff / ELO_TO_SPREAD_FACTOR (50), Total-Mittelwert = total_pred, Teampunkte = (Total +- Spread) / 2 (wie engine/projection.compute_projection ohne Markt).
- Streuungen: engine/line_probabilities (SIGMAS_VERSION 2): Spread 13,2, Total 18,6, Team Total 11,6. Siegwahrscheinlichkeit = lp.win_prob_home(round(Spread, 1)) wie in der App.
- Ereignis je Linie L: Spread "Heim deckt" = Marge > L, Total/Team Total "Over" = Wert > L; p = 1 - Phi((L - Mittelwert) / Sigma).
- Hauptauswertung Regular Season (postseason = false; enthaelt die NBA-Cup-Finalspiele, die das Modell wie alle Spiele verarbeitet), Playoffs (postseason = true) getrennt als Zusatz.
- Bootstrap nach Spielen (Bias/MAE 2000 Ziehungen, Stufenabweichung 1000, Kalibrierungs-Steigung 200). Zeilen eines Spiels (verschiedene Linien) sind nicht unabhaengig.
Reine Beschreibung der Messung, keine Empfehlungen zu Produktivparametern.
"""
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
from scipy import optimize, stats
from scipy.special import expit, ndtr

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from bt_common import load_games, reliability, boot_diff, logloss  # noqa: E402,F401
import replica_tunable as rt  # noqa: E402
import old_engine_replica as old  # noqa: E402
from sigma_check import cal_slope, thresholds, ll  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402

RESULTS = HERE / "results"
OUT_JSON, OUT_TXT = "backtest_team_2025-26.json", "backtest_team_2025-26.txt"
SEASON = 2025                                       # Saison 2025-26 in den Cache-Dateien
KS = list(range(-5, 6))
B_ERR, B_STAGE, B_SLOPE = 2000, 1000, 200
THRESH = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
MAD_MAX_PP, DEV_MAX_PP, MIN_ROWS = 3.0, 6.0, 100
MARKETS = {"spread": ("Spread (Heim deckt)", lp.SPREAD_SIGMA), "total": ("Gesamt-Total (Over)", lp.TOTAL_SIGMA),
           "tt_home": ("Team-Total Heim (Over)", lp.TEAM_TOTAL_SIGMA), "tt_away": ("Team-Total Gast (Over)", lp.TEAM_TOTAL_SIGMA)}
PRODUCTION = dict(K=20.0, hca=100.0, mov="cur", total_alpha=0.1)


# ----------------------------------------------------------------------------------------------- Bausteine
def pr(x, d=4):
    return None if x is None else round(float(x), d)


def boot_mean_ci(v, B=None, seed=0):
    B = B or B_ERR
    v = np.asarray(v, float)
    if len(v) == 0:
        return None, None, None
    idx = np.random.default_rng(seed).integers(0, len(v), (B, len(v)))
    m = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def point_errors(mu, x):
    """Bias (Modell minus Ergebnis) und MAE mit Bootstrap nach Spielen."""
    b, bl, bh = boot_mean_ci(mu - x, seed=1)
    m, ml, mh = boot_mean_ci(np.abs(mu - x), seed=2)
    return {"n": int(len(mu)), "bias": pr(b), "bias_ci95": [pr(bl), pr(bh)], "mae": pr(m), "mae_ci95": [pr(ml), pr(mh)], "mittel_modell": pr(np.mean(mu)), "mittel_ergebnis": pr(np.mean(x))}


def line_probs(mu, sigma, ks=KS):
    """(L, p_over) je Spiel und Linie; L = floor(mu) + 0,5 + k (Hauptlinie = Mittelwert auf x,5 gerundet)."""
    L = thresholds(mu, ks)
    return L, 1.0 - ndtr((L - mu[:, None]) / sigma)


def slope_fit(p, y):
    """Kalibrierungs-Steigung (Logistik des Ausgangs auf logit(p)); None, wenn die Wahrscheinlichkeiten zu wenig streuen."""
    p = np.clip(np.asarray(p, float).ravel(), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float).ravel()
    z = np.log(p / (1 - p))
    if len(z) < 30 or z.std() < 0.05:
        return None
    f = lambda b: float(np.mean(ll(expit(b[0] + b[1] * z), y)))
    r = optimize.minimize(f, [0.0, 1.0], method="BFGS")
    return float(r.x[1])


def bins_table(q, hit, edges, labels):
    out = []
    for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
        m = (q >= lo) & (q < hi)
        if m.sum():
            out.append({"stufe": lab, "n": int(m.sum()), "mittel_modell": pr(q[m].mean()), "trefferquote": pr(hit[m].mean()), "abweichung_pp": pr(100 * (hit[m].mean() - q[m].mean()), 2)})
    return out


def predicted_side_bins(p, y):
    """Stufen der Wahrscheinlichkeit der vorhergesagten Seite (50-55 ... 85-90, 90+): Trefferquote der vorhergesagten Seite."""
    p, y = np.asarray(p, float).ravel(), np.asarray(y, float).ravel()
    q = np.maximum(p, 1 - p)
    hit = np.where(p >= 0.5, y, 1 - y)
    edges = [0.5, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.0001]
    labels = ["50-55 %", "55-60 %", "60-65 %", "65-70 %", "70-75 %", "75-80 %", "80-85 %", "85-90 %", "90+ %"]
    return bins_table(q, hit, edges, labels)


def over_side_bins(p, y):
    p, y = np.asarray(p, float).ravel(), np.asarray(y, float).ravel()
    edges = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
    labels = ["0-10 %", "10-20 %", "20-30 %", "30-40 %", "40-50 %", "50-60 %", "60-70 %", "70-80 %", "80-90 %", "90-100 %"]
    return bins_table(p, y, edges, labels)


def coverage(bins):
    """Schwellen der Modell-Wahrscheinlichkeit (vorhergesagte Seite >= t), die die Kriterien erfuellen: mittlere Abweichung (nach Zeilen gewichtet) < 3 PP und keine Stufe mit >= 100 Zeilen
    mehr als 6 PP daneben. Stufen = 5er-Stufen der vorhergesagten Seite (ab 50 %)."""
    res = {}
    for t in THRESH:
        sel = [b for b in bins if float(b["stufe"].split("-")[0].replace("+", "").split()[0]) / 100.0 >= t - 1e-9]
        n = sum(b["n"] for b in sel)
        if n < MIN_ROWS:
            res[str(t)] = {"n": n, "pruefbar": False, "gedeckt": None}
            continue
        mad = sum(b["n"] * abs(b["abweichung_pp"]) for b in sel) / n
        big = [b for b in sel if b["n"] >= MIN_ROWS]
        mx = max((abs(b["abweichung_pp"]) for b in big), default=0.0)
        res[str(t)] = {"n": n, "pruefbar": True, "mittlere_abweichung_pp": pr(mad, 2), "max_abweichung_pp_ab100": pr(mx, 2), "gedeckt": bool(mad < MAD_MAX_PP and mx <= DEV_MAX_PP)}
    return res


def stage_table(mu, x, sigma, ks=KS, seed=3, with_ci=True):
    L, p = line_probs(mu, sigma, ks)
    y = (x[:, None] > L).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(mu), (B_STAGE, len(mu))) if with_ci else None
    rows = []
    for j, k in enumerate(ks):
        pj, yj = p[:, j], y[:, j]
        row = {"k": k, "linie_beispiel": pr(L[0, j], 1), "n": int(len(mu)), "mittel_modell": pr(pj.mean()), "trefferquote": pr(yj.mean()), "abweichung_pp": pr(100 * (yj.mean() - pj.mean()), 2),
               "brier": pr(((pj - yj) ** 2).mean()), "logloss": pr(ll(pj, yj).mean()), "steigung": pr(slope_fit(pj, yj), 3)}
        if with_ci:
            d = 100 * (yj[idx].mean(axis=1) - pj[idx].mean(axis=1))
            row["abweichung_ci95_pp"] = [pr(np.percentile(d, 2.5), 2), pr(np.percentile(d, 97.5), 2)]
        rows.append(row)
    return rows


def pooled_slope_ci(mu, x, sigma, seed=4):
    L, p = line_probs(mu, sigma)
    y = (x[:, None] > L).astype(float)
    est = slope_fit(p, y)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(B_SLOPE):
        i = rng.integers(0, len(mu), len(mu))
        s = slope_fit(p[i], y[i])
        if s is not None:
            bs.append(s)
    return est, (float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))) if bs else (None, None)


def market_report(mu, x, sigma, full=True):
    """Vollstaendiger Bericht eines Punkte-Markts (Fehler, Stufen je Linie, Wahrscheinlichkeitsstufen, Abdeckung)."""
    L, p = line_probs(mu, sigma)
    y = (x[:, None] > L).astype(float)
    slope, ci = pooled_slope_ci(mu, x, sigma)
    side = predicted_side_bins(p, y)
    rep = {"fehler": point_errors(mu, x), "gesamt_ueber_linien": {"brier": pr(((p - y) ** 2).mean()), "logloss": pr(ll(p, y).mean()), "steigung": pr(slope, 3),
                                                                  "steigung_ci95": [pr(ci[0], 3), pr(ci[1], 3)] if ci[0] is not None else None,
                                                                  "mittlere_abweichung_stufen_pp": pr(sum(b["n"] * abs(b["abweichung_pp"]) for b in side) / max(1, sum(b["n"] for b in side)), 2)},
           "stufen_je_linie": stage_table(mu, x, sigma), "wahrscheinlichkeitsstufen_vorhergesagte_seite": side, "wahrscheinlichkeitsstufen_over_seite": over_side_bins(p, y),
           "abdeckung_schwellen": coverage(side)}
    return rep


def light_report(mu, x, sigma):
    """Kurzbericht fuer Aufteilungen: n, Bias, MAE, Hauptlinie (k = 0) Modell gegen Trefferquote, Steigung ueber alle Linien, mittlere Stufenabweichung."""
    if len(mu) < 5:
        return {"n": int(len(mu))}
    L, p = line_probs(mu, sigma)
    y = (x[:, None] > L).astype(float)
    k0 = KS.index(0)
    side = predicted_side_bins(p, y)
    return {"n": int(len(mu)), "bias": pr((mu - x).mean(), 2), "mae": pr(np.abs(mu - x).mean(), 2), "hauptlinie_mittel_modell": pr(p[:, k0].mean(), 3), "hauptlinie_trefferquote": pr(y[:, k0].mean(), 3),
            "steigung": pr(slope_fit(p, y), 3), "mittlere_abweichung_stufen_pp": pr(sum(b["n"] * abs(b["abweichung_pp"]) for b in side) / max(1, sum(b["n"] for b in side)), 2)}


def win_report(mu_s, margin):
    """Sieg: p = lp.win_prob_home(round(Spread, 1)) wie in der App; hit = Heim gewinnt."""
    p = np.array([lp.win_prob_home(round(float(m), 1)) for m in mu_s])
    y = (margin > 0).astype(float)
    pf = np.maximum(p, 1 - p)
    hitf = np.where(p >= 0.5, y, 1 - y)
    side = predicted_side_bins(p, y)
    fav = bins_table(pf, hitf, [0.5, 0.6, 0.7, 0.8, 1.0001], ["50-60 %", "60-70 %", "70-80 %", "80+ %"])
    return {"n": int(len(p)), "mittel_p_heim": pr(p.mean(), 3), "heimsieg_quote": pr(y.mean(), 3), "brier": pr(((p - y) ** 2).mean()), "brier_referenz_immer_50": 0.25, "logloss": pr(ll(p, y).mean()),
            "trefferquote_favorit": pr(hitf.mean(), 3), "steigung": pr(slope_fit(p, y), 3), "heim_p_stufen": over_side_bins(p, y), "favorit_stufen": fav,
            "wahrscheinlichkeitsstufen_vorhergesagte_seite": side, "abdeckung_schwellen": coverage(side)}, p, y


def win_light(mu_s, margin):
    if len(mu_s) < 5:
        return {"n": int(len(mu_s))}
    p = np.array([lp.win_prob_home(round(float(m), 1)) for m in mu_s]); y = (margin > 0).astype(float)
    return {"n": int(len(p)), "mittel_p_heim": pr(p.mean(), 3), "heimsieg_quote": pr(y.mean(), 3), "brier": pr(((p - y) ** 2).mean()), "logloss": pr(ll(p, y).mean()), "trefferquote_favorit": pr(np.where(p >= .5, y, 1 - y).mean(), 3),
            "steigung": pr(slope_fit(p, y), 3)}


def split_report(d, mask):
    """Alle Maerkte kurz fuer eine Teilmenge (mask auf den Spielen der Auswertung)."""
    s = lambda a: a[mask]
    return {"sieg": win_light(s(d["mu_s"]), s(d["margin"])), "spread": light_report(s(d["mu_s"]), s(d["margin"]), lp.SPREAD_SIGMA), "total": light_report(s(d["mu_t"]), s(d["total"]), lp.TOTAL_SIGMA),
            "tt_home": light_report(s(d["mu_h"]), s(d["pts_h"]), lp.TEAM_TOTAL_SIGMA), "tt_away": light_report(s(d["mu_a"]), s(d["pts_a"]), lp.TEAM_TOTAL_SIGMA)}


def total_special(d):
    mu, x = d["mu_t"], d["total"]
    res = x - mu                                                   # Ergebnis minus Modell
    q = np.percentile(res, [5, 25, 50, 75, 95])
    ot = d["ot"].astype(bool)
    out = {"residuum_definition": "Ergebnis minus Modell-Total", "n": int(len(res)), "mittel": pr(res.mean(), 2), "sd": pr(res.std(), 2), "sigma_modell": lp.TOTAL_SIGMA, "schiefe": pr(stats.skew(res), 3),
           "ueberschuss_woelbung": pr(stats.kurtosis(res), 3), "quantile_5_25_50_75_95": [pr(v, 2) for v in q], "quantile_normal_bei_sd_modell": [pr(float(stats.norm.ppf(c) * lp.TOTAL_SIGMA + res.mean()), 2) for c in (.05, .25, .5, .75, .95)]}
    groups = {"modell_total_unter_225": mu < 225, "modell_total_225_bis_235": (mu >= 225) & (mu < 235), "modell_total_ab_235": mu >= 235}
    hi = {}
    for name, m in groups.items():
        if m.sum() < 5:
            hi[name] = {"n": int(m.sum())}
            continue
        L, p = line_probs(mu[m], lp.TOTAL_SIGMA)
        y = (x[m][:, None] > L).astype(float)
        k0 = KS.index(0)
        hi[name] = {"n": int(m.sum()), "mittel_modell_total": pr(mu[m].mean(), 1), "mittel_ergebnis_total": pr(x[m].mean(), 1), "bias_modell_minus_ergebnis": pr((mu[m] - x[m]).mean(), 2),
                    "hauptlinie_over_modell": pr(p[:, k0].mean(), 3), "hauptlinie_over_trefferquote": pr(y[:, k0].mean(), 3), "alle_linien_over_modell": pr(p.mean(), 3), "alle_linien_over_trefferquote": pr(y.mean(), 3),
                    "steigung": pr(slope_fit(p, y), 3)}
    out["nach_modell_total"] = hi
    out["overtime"] = {"anteil_spiele": pr(ot.mean(), 3), "n_ot": int(ot.sum()), "mittel_ergebnis_total_ot": pr(x[ot].mean(), 1) if ot.any() else None, "mittel_ergebnis_total_ohne_ot": pr(x[~ot].mean(), 1),
                       "mittel_residuum_ot": pr(res[ot].mean(), 2) if ot.any() else None, "mittel_residuum_ohne_ot": pr(res[~ot].mean(), 2),
                       "bias_gesamt": pr((mu - x).mean(), 2), "bias_ohne_ot_spiele": pr((mu[~ot] - x[~ot]).mean(), 2)}
    return out


# ----------------------------------------------------------------------------------------------- Replay, Daten, Kontrollen
def prepare(games, rows):
    """Arrays der Auswertung (Saison SEASON) aus Replay-Spalten und Spielen."""
    sel = np.where(rows["season"] == SEASON)[0]
    g = [games[i] for i in sel]
    mu_s = rows["diff"][sel] / ELO_TO_SPREAD_FACTOR
    mu_t = rows["total_pred"][sel]
    margin, total = rows["margin"][sel], rows["total"][sel]
    return {"idx": sel, "mu_s": mu_s, "mu_t": mu_t, "mu_h": (mu_t + mu_s) / 2, "mu_a": (mu_t - mu_s) / 2, "margin": margin, "total": total, "pts_h": (total + margin) / 2, "pts_a": (total - margin) / 2,
            "post": rows["post"][sel].astype(int), "gp_h": rows["gp_h"][sel], "gp_a": rows["gp_a"][sel], "ot": np.array([int((x.get("period") or 4) > 4) for x in g]), "dates": [x["date"][:10] for x in g],
            "ids": [x["id"] for x in g]}


def subset(d, m):
    return {k: (np.asarray(v)[m] if isinstance(v, (np.ndarray, list)) and len(v) == len(m) else v) for k, v in d.items()}


def causality_check(games, rows, positions, run=rt.run):
    """Spot-Check: Prognose vor Spiel i aus NUR den Spielen bis i (Spiel i selbst und die Zukunft abgeschnitten) muss gleich der Prognose des vollen Laufs sein."""
    res = []
    for i in positions:
        part, *_ = run(games[:i + 1])
        res.append({"position": int(i), "diff_abweichung": float(abs(part["diff"][-1] - rows["diff"][i])), "total_abweichung": float(abs(part["total_pred"][-1] - rows["total_pred"][i]))})
    ok = all(r["diff_abweichung"] < 1e-9 and r["total_abweichung"] < 1e-9 for r in res)
    return {"ok": ok, "stichproben": res}


def build_report(games, rows, d_all, controls):
    rs, po = d_all["post"] == 0, d_all["post"] == 1
    d = subset(d_all, rs)
    out = {"version": 1, "saison": "2025-26", "hinweis": "REINES MODELL ohne Markt-Mischung (die App mischt den Markt dazu); Linien = Raster um den Modell-Mittelwert (keine historischen Quoten).",
           "sigmas": {"version": lp.SIGMAS_VERSION, "spread": lp.SPREAD_SIGMA, "total": lp.TOTAL_SIGMA, "team_total": lp.TEAM_TOTAL_SIGMA}, "kontrollen": controls,
           "stichprobe": {"regular_season": int(rs.sum()), "playoffs": int(po.sum()), "ot_regular_season": int(d["ot"].sum())}}
    sieg, p_win, y_win = win_report(d["mu_s"], d["margin"])
    out["regular_season"] = {"sieg": sieg}
    for key, (name, sigma) in MARKETS.items():
        mu = {"spread": d["mu_s"], "total": d["mu_t"], "tt_home": d["mu_h"], "tt_away": d["mu_a"]}[key]
        x = {"spread": d["margin"], "total": d["total"], "tt_home": d["pts_h"], "tt_away": d["pts_a"]}[key]
        out["regular_season"][key] = {"name": name, "sigma": sigma, **market_report(mu, x, sigma)}
    n_rs = len(d["mu_s"])
    order = np.arange(n_rs)
    h1 = order < n_rs // 2
    first15 = (d["gp_h"] < 15) & (d["gp_a"] < 15)
    ot = d["ot"].astype(bool)
    out["aufteilungen"] = {"erste_saisonhaelfte": split_report(d, h1), "zweite_saisonhaelfte": split_report(d, ~h1), "erste_15_spiele_je_team": split_report(d, first15), "rest": split_report(d, ~first15),
                           "mit_overtime": split_report(d, ot), "ohne_overtime": split_report(d, ~ot),
                           "heim_gegen_gast": {"team_total_heim": light_report(d["mu_h"], d["pts_h"], lp.TEAM_TOTAL_SIGMA), "team_total_gast": light_report(d["mu_a"], d["pts_a"], lp.TEAM_TOTAL_SIGMA),
                                               "heimvorteil_spread": {"mittel_modell": pr(d["mu_s"].mean(), 2), "mittel_ergebnis": pr(d["margin"].mean(), 2)},
                                               "sieg": {"mittel_p_heim": sieg["mittel_p_heim"], "heimsieg_quote": sieg["heimsieg_quote"]}}}
    out["total_speziell"] = total_special(d)
    dp = subset(d_all, po)
    out["playoffs_zusatz"] = split_report(dp, np.ones(len(dp["mu_s"]), bool)) if po.sum() >= 5 else {"n": int(po.sum())}
    out["playoffs_zusatz"]["fehler"] = {"spread": point_errors(dp["mu_s"], dp["margin"]), "total": point_errors(dp["mu_t"], dp["total"]), "tt_home": point_errors(dp["mu_h"], dp["pts_h"]),
                                        "tt_away": point_errors(dp["mu_a"], dp["pts_a"])} if po.sum() >= 5 else None
    return out


# ----------------------------------------------------------------------------------------------- Text
def verdict_slope(rep):
    s, ci = rep["gesamt_ueber_linien"]["steigung"], rep["gesamt_ueber_linien"].get("steigung_ci95")
    if s is None or not ci:
        return "Steigung nicht bestimmbar"
    if ci[1] < 1:
        return f"zu sicher (Steigung {s:.2f} [{ci[0]:.2f}; {ci[1]:.2f}]: Ausgang weniger extrem als die Prognose)"
    if ci[0] > 1:
        return f"zu vorsichtig (Steigung {s:.2f} [{ci[0]:.2f}; {ci[1]:.2f}]: Ausgang extremer als die Prognose)"
    return f"gut kalibriert (Steigung {s:.2f} [{ci[0]:.2f}; {ci[1]:.2f}], 1 liegt im Intervall)"


def covered_text(cov):
    ok = [float(t) for t, v in cov.items() if v.get("gedeckt")]
    chk = [float(t) for t, v in cov.items() if v.get("pruefbar")]
    if not chk:
        return "keine Schwelle prüfbar (zu wenige Zeilen)"
    if not ok:
        return f"keine Schwelle gedeckt (geprüft {int(100 * min(chk))} bis {int(100 * max(chk))} %)"
    if ok == [t for t in chk if t >= min(ok)]:
        return f"gedeckt ab {int(round(100 * min(ok)))} % bis {int(round(100 * max(chk)))} % (darüber zu wenige Zeilen)" if max(chk) < max(THRESH) else f"gedeckt ab {int(round(100 * min(ok)))} %"
    return "gedeckt bei " + ", ".join(f"{int(round(100 * t))} %" for t in ok) + " (nicht lückenlos)"


def summary_lines(rep):
    st, rs = rep["stichprobe"], rep["regular_season"]
    L = [f"ZUSAMMENFASSUNG (Saison 2025-26, Regular Season n = {st['regular_season']}, Playoffs n = {st['playoffs']} getrennt). REINES MODELL ohne Markt-Mischung; die App mischt den Markt dazu.",
         f"Plausibilität: Heim-Siegwahrscheinlichkeit Ø {rs['sieg']['mittel_p_heim']:.3f} gegen Heimsiegquote {rs['sieg']['heimsieg_quote']:.3f}; Modell-Total Ø {rs['total']['fehler']['mittel_modell']} gegen echter Ø {rs['total']['fehler']['mittel_ergebnis']}."]
    s = rs["sieg"]
    L += [f"Sieg: Brier {s['brier']:.4f} (Referenz 0,25), Log-Loss {s['logloss']:.3f}, Favorit gewinnt {100 * s['trefferquote_favorit']:.1f} %; Heim-p Ø {s['mittel_p_heim']:.3f} gegen Heimsiegquote {s['heimsieg_quote']:.3f}.",
          f"  Kalibrierung: Steigung {s['steigung']:.2f}; Favorit-Stufen " + ", ".join(f"{b['stufe']}: Modell {100 * b['mittel_modell']:.0f} % / Treffer {100 * b['trefferquote']:.0f} % (n {b['n']})" for b in s["favorit_stufen"]) + ".",
          f"  Schwellen: {covered_text(s['abdeckung_schwellen'])}."]
    for key in ("spread", "total", "tt_home", "tt_away"):
        m = rs[key]
        f = m["fehler"]
        bias_sig = f["bias_ci95"][0] > 0 or f["bias_ci95"][1] < 0
        side = "Modell höher als Ergebnis" if f["bias"] > 0 else "Modell niedriger als Ergebnis"
        worst = max(m["stufen_je_linie"], key=lambda r: abs(r["abweichung_pp"]))
        L += [f"{m['name']}: Bias {f['bias']:+.2f} [{f['bias_ci95'][0]:+.2f}; {f['bias_ci95'][1]:+.2f}] Pkt (" + (f"Verzerrung nachweisbar: {side}" if bias_sig else "keine Verzerrung nachweisbar") + f"), MAE {f['mae']:.2f}.",
              f"  Kalibrierung: {verdict_slope(m)}; mittlere Stufenabweichung {m['gesamt_ueber_linien']['mittlere_abweichung_stufen_pp']:.1f} PP; größte Linien-Abweichung {worst['abweichung_pp']:+.1f} PP bei Hauptlinie {worst['k']:+d}.",
              f"  Schwellen: {covered_text(m['abdeckung_schwellen'])}."]
    L.append("Nur Beschreibung der Messung; keine Empfehlungen zu Produktivparametern.")
    return L


def table(rows, cols, head):
    w = [max(len(h), max((len(str(r[c])) for r in rows), default=0)) for c, h in zip(cols, head)]
    line = lambda vals: "  ".join(str(v).rjust(wi) for v, wi in zip(vals, w))
    return [line(head), line(["-" * wi for wi in w])] + [line([r[c] for c in cols]) for r in rows]


def fp(x, d=3):
    return "-" if x is None else f"{x:.{d}f}"


def render_text(rep, runtime):
    L = summary_lines(rep)
    L += ["", "=" * 110, f"Backtest Team-Märkte 2025-26 (Walk-forward). Laufzeit {runtime:.1f} s. Rechenweg: siehe Kopf von analysis/backtest_team_markets.py.", "=" * 110, ""]
    c = rep["kontrollen"]
    L += ["KONTROLLEN", f"  Spiele insgesamt im Replay (2015-2025): {c['spiele_replay']}; ausgewertet Saison 2025-26: {c['spiele_saison']} (Regular Season {rep['stichprobe']['regular_season']}, Playoffs {rep['stichprobe']['playoffs']}).",
          f"  Kausalität (Replay nur bis Spiel i, ohne Spiel i und Zukunft = voller Lauf): {'OK' if c['kausalitaet']['ok'] else 'FEHLER'} bei {len(c['kausalitaet']['stichproben'])} Stichproben, größte Abweichung "
          f"{max(max(r['diff_abweichung'], r['total_abweichung']) for r in c['kausalitaet']['stichproben']):.2e}.",
          f"  Parität replica_tunable gegen old_engine_replica (diff, alle Spiele): größte Abweichung {c['paritaet_diff_max']:.2e}. Spiele chronologisch (Datum, ID): {'ja' if c['chronologisch'] else 'NEIN'}.",
          f"  Sigmas Version {rep['sigmas']['version']}: Spread {rep['sigmas']['spread']}, Total {rep['sigmas']['total']}, Team Total {rep['sigmas']['team_total']}; Spread = diff / {ELO_TO_SPREAD_FACTOR}.", ""]
    s = rep["regular_season"]["sieg"]
    L += ["SIEG (Regular Season)", f"  n {s['n']}, Brier {s['brier']:.4f} (Referenz immer 50 %: 0,25), Log-Loss {s['logloss']:.3f}, Favorit gewinnt {100 * s['trefferquote_favorit']:.1f} %, Steigung {fp(s['steigung'], 2)}",
          "  Heim-Siegwahrscheinlichkeit nach Stufen:"] + ["    " + t for t in table(s["heim_p_stufen"], ["stufe", "n", "mittel_modell", "trefferquote", "abweichung_pp"], ["Stufe", "n", "Modell", "Treffer", "Abw. PP"])]
    L += ["  Favorit nach Stufen:"] + ["    " + t for t in table(s["favorit_stufen"], ["stufe", "n", "mittel_modell", "trefferquote", "abweichung_pp"], ["Stufe", "n", "Modell", "Treffer", "Abw. PP"])]
    L += ["  Vorhergesagte Seite nach 5er-Stufen:"] + ["    " + t for t in table(s["wahrscheinlichkeitsstufen_vorhergesagte_seite"], ["stufe", "n", "mittel_modell", "trefferquote", "abweichung_pp"], ["Stufe", "n", "Modell", "Treffer", "Abw. PP"])] + [""]
    for key in ("spread", "total", "tt_home", "tt_away"):
        m = rep["regular_season"][key]
        f = m["fehler"]
        g = m["gesamt_ueber_linien"]
        L += [f"{m['name'].upper()}  (Sigma {m['sigma']})", f"  n {f['n']}; Ø Modell {f['mittel_modell']:.2f}, Ø Ergebnis {f['mittel_ergebnis']:.2f}; Bias (Modell minus Ergebnis) {f['bias']:+.2f} [{f['bias_ci95'][0]:+.2f}; {f['bias_ci95'][1]:+.2f}]; "
                                                         f"MAE {f['mae']:.2f} [{f['mae_ci95'][0]:.2f}; {f['mae_ci95'][1]:.2f}]",
              f"  über alle Linien: Brier {g['brier']:.4f}, Log-Loss {g['logloss']:.4f}, Steigung {fp(g['steigung'], 2)} [{fp(g['steigung_ci95'][0], 2) if g['steigung_ci95'] else '-'}; {fp(g['steigung_ci95'][1], 2) if g['steigung_ci95'] else '-'}]",
              "  je Linie (Hauptlinie k = 0; Abweichung = Trefferquote minus Modell, Ereignis Heim deckt / Over):"]
        L += ["    " + t for t in table([{**r, "ci": f"[{r['abweichung_ci95_pp'][0]:+.1f}; {r['abweichung_ci95_pp'][1]:+.1f}]"} for r in m["stufen_je_linie"]],
                                         ["k", "n", "mittel_modell", "trefferquote", "abweichung_pp", "ci", "brier", "logloss", "steigung"], ["k", "n", "Modell", "Treffer", "Abw. PP", "95 %-Intervall", "Brier", "LogLoss", "Steigung"])]
        L += ["  vorhergesagte Seite nach 5er-Stufen (alle Linien, Zeilen eines Spiels nicht unabhängig):"] + ["    " + t for t in table(m["wahrscheinlichkeitsstufen_vorhergesagte_seite"], ["stufe", "n", "mittel_modell", "trefferquote", "abweichung_pp"], ["Stufe", "n", "Modell", "Treffer", "Abw. PP"])]
        L += ["  Over-/Heim-Seite nach 10er-Stufen (alle Linien):"] + ["    " + t for t in table(m["wahrscheinlichkeitsstufen_over_seite"], ["stufe", "n", "mittel_modell", "trefferquote", "abweichung_pp"], ["Stufe", "n", "Modell", "Treffer", "Abw. PP"])]
        L += [f"  Schwellen (Kriterium: mittlere Abweichung < {MAD_MAX_PP:g} PP und keine Stufe mit >= {MIN_ROWS} Zeilen über {DEV_MAX_PP:g} PP daneben): {covered_text(m['abdeckung_schwellen'])}", ""]
    L += ["AUFTEILUNGEN (Regular Season; je Markt n / Bias / MAE bzw. Brier / Hauptlinie Modell gegen Treffer / Steigung über alle Linien / mittlere Stufenabweichung PP)"]
    for name, blk in rep["aufteilungen"].items():
        if name == "heim_gegen_gast":
            continue
        L.append(f"  [{name}]")
        for mk in ("sieg", "spread", "total", "tt_home", "tt_away"):
            r = blk[mk]
            if mk == "sieg":
                L.append(f"    Sieg        n {r['n']:>4}  Heim-p Ø {fp(r.get('mittel_p_heim'))} / Heimsiegquote {fp(r.get('heimsieg_quote'))}  Brier {fp(r.get('brier'), 4)}  Favorit {fp(r.get('trefferquote_favorit'))}  Steigung {fp(r.get('steigung'), 2)}")
            else:
                L.append(f"    {mk:<11} n {r['n']:>4}  Bias {fp(r.get('bias'), 2):>6}  MAE {fp(r.get('mae'), 2):>5}  Hauptlinie {fp(r.get('hauptlinie_mittel_modell'))} / {fp(r.get('hauptlinie_trefferquote'))}  Steigung {fp(r.get('steigung'), 2)}  Abw. {fp(r.get('mittlere_abweichung_stufen_pp'), 1)}")
    h = rep["aufteilungen"]["heim_gegen_gast"]
    L += ["  [Heim gegen Gast]", f"    Team-Total Heim: Bias {fp(h['team_total_heim']['bias'], 2)}, MAE {fp(h['team_total_heim']['mae'], 2)}, Steigung {fp(h['team_total_heim']['steigung'], 2)};  Gast: Bias {fp(h['team_total_gast']['bias'], 2)}, MAE {fp(h['team_total_gast']['mae'], 2)}, Steigung {fp(h['team_total_gast']['steigung'], 2)}",
          f"    Heimvorteil: Ø Spread Modell {h['heimvorteil_spread']['mittel_modell']:+.2f} gegen Ø Marge {h['heimvorteil_spread']['mittel_ergebnis']:+.2f}; Heim-p Ø {fp(h['sieg']['mittel_p_heim'])} gegen Heimsiegquote {fp(h['sieg']['heimsieg_quote'])}", ""]
    t = rep["total_speziell"]
    L += ["TOTAL SPEZIELL", f"  Residuum ({t['residuum_definition']}): Ø {t['mittel']:+.2f}, SD {t['sd']:.2f} (Modell-Sigma {t['sigma_modell']}), Schiefe {t['schiefe']:+.2f}, Überschuss-Wölbung {t['ueberschuss_woelbung']:+.2f}",
          f"  Quantile 5/25/50/75/95 %: {t['quantile_5_25_50_75_95']}   (Normal mit SD {t['sigma_modell']}: {t['quantile_normal_bei_sd_modell']})", "  nach Höhe des Modell-Totals:"]
    for k, v in t["nach_modell_total"].items():
        L.append(f"    {k:<26} n {v['n']:>4}" + ("" if v["n"] < 5 else f"  Ø Modell {v['mittel_modell_total']}  Ø Ergebnis {v['mittel_ergebnis_total']}  Bias {v['bias_modell_minus_ergebnis']:+.2f}  Over Hauptlinie Modell {v['hauptlinie_over_modell']:.3f} / Treffer {v['hauptlinie_over_trefferquote']:.3f}  alle Linien {v['alle_linien_over_modell']:.3f} / {v['alle_linien_over_trefferquote']:.3f}  Steigung {fp(v['steigung'], 2)}"))
    o = t["overtime"]
    L += [f"  Overtime: {o['n_ot']} Spiele ({100 * o['anteil_spiele']:.1f} %), Ø Total mit OT {o['mittel_ergebnis_total_ot']} gegen ohne {o['mittel_ergebnis_total_ohne_ot']}; Residuum Ø mit OT {o['mittel_residuum_ot']:+.2f}, ohne {o['mittel_residuum_ohne_ot']:+.2f}; "
          f"Bias gesamt {o['bias_gesamt']:+.2f}, ohne OT-Spiele {o['bias_ohne_ot_spiele']:+.2f}", ""]
    p = rep["playoffs_zusatz"]
    L += ["PLAYOFFS (Zusatz, kleine Stichprobe, nur Fehler)"]
    if p.get("fehler"):
        for k, v in p["fehler"].items():
            L.append(f"  {k:<8} n {v['n']}  Bias {v['bias']:+.2f} [{v['bias_ci95'][0]:+.2f}; {v['bias_ci95'][1]:+.2f}]  MAE {v['mae']:.2f}")
        L.append(f"  Sieg: Heim-p Ø {fp(p['sieg'].get('mittel_p_heim'))}, Heimsiegquote {fp(p['sieg'].get('heimsieg_quote'))}, Brier {fp(p['sieg'].get('brier'), 4)}")
    else:
        L.append(f"  zu wenige Spiele (n = {p['n']})")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------- Hauptprogramm, Selbsttest
def run_all():
    t0 = time.time()
    games = load_games(2015, 2025)
    rows, _, _, _ = rt.run(games, **PRODUCTION)
    d_all = prepare(games, rows)
    dates = [(g["date"][:10], g["id"]) for g in games]
    old_rows, _ = old.run(games, K=20.0, hca=100.0, mov="cur", carry=0.0, kboost=0.0, post_w=1.0, total_alpha=0.1)
    pos_all = np.where(rows["season"] == SEASON)[0]
    rng = np.random.default_rng(7)
    positions = sorted(int(i) for i in rng.choice(pos_all, 4, replace=False)) + [int(pos_all[0]), int(pos_all[-1])]
    controls = {"spiele_replay": int(len(games)), "spiele_saison": int(len(pos_all)), "chronologisch": dates == sorted(dates), "paritaet_diff_max": float(np.max(np.abs(np.asarray(old_rows["diff"]) - rows["diff"]))),
                "kausalitaet": causality_check(games, rows, positions)}
    rep = build_report(games, rows, d_all, controls)
    runtime = time.time() - t0
    rep["laufzeit_sekunden"] = round(runtime, 1)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / OUT_JSON).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (RESULTS / OUT_TXT).write_text(render_text(rep, runtime), encoding="utf-8")
    return rep, runtime


def synthetic(n, seed, sigma_s_true, sigma_t_true, sigma_tt_true):
    rng = np.random.default_rng(seed)
    mu_s = rng.normal(2.0, 5.0, n); mu_t = rng.normal(228.0, 6.0, n)
    margin = mu_s + rng.normal(0, sigma_s_true, n); total = mu_t + rng.normal(0, sigma_t_true, n)
    return {"mu_s": mu_s, "mu_t": mu_t, "mu_h": (mu_t + mu_s) / 2, "mu_a": (mu_t - mu_s) / 2, "margin": margin, "total": total, "pts_h": (total + margin) / 2, "pts_a": (total - margin) / 2}


def selftest():
    global B_ERR, B_STAGE, B_SLOPE
    B_ERR, B_STAGE, B_SLOPE = 300, 200, 40                                    # Selbsttest: wenige Ziehungen, kleine Stichproben (schnell)
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    # 1) wohlkalibrierte kuenstliche Daten: Steigung ~1, Abweichungen klein, Schwellen gedeckt
    d = synthetic(2500, 1, lp.SPREAD_SIGMA, lp.TOTAL_SIGMA, lp.TEAM_TOTAL_SIGMA)
    rep = market_report(d["mu_s"], d["margin"], lp.SPREAD_SIGMA)
    g = rep["gesamt_ueber_linien"]
    check("kalibriert: Steigung nahe 1 und 1 im Intervall", abs(g["steigung"] - 1) < 0.12 and g["steigung_ci95"][0] <= 1 <= g["steigung_ci95"][1], g)
    check("kalibriert: Bias nahe 0, Stufenabweichung klein", abs(rep["fehler"]["bias"]) < 0.5 and g["mittlere_abweichung_stufen_pp"] < 3.0, (rep["fehler"]["bias"], g["mittlere_abweichung_stufen_pp"]))
    check("kalibriert: Schwellen ab 55 % gedeckt", covered_text(rep["abdeckung_schwellen"]).startswith("gedeckt ab"), covered_text(rep["abdeckung_schwellen"]))
    check("Linienraster: 11 Linien, Hauptlinie = x,5 nahe am Mittelwert", len(rep["stufen_je_linie"]) == 11 and all(abs(thresholds(d["mu_s"], [0])[:, 0] - d["mu_s"]) <= 0.5 + 1e-9), "")
    # 2) zu sicheres Modell (wahre Streuung 17 statt 13,2): Steigung deutlich unter 1
    d2 = synthetic(2500, 2, 17.0, lp.TOTAL_SIGMA, lp.TEAM_TOTAL_SIGMA)
    r2 = market_report(d2["mu_s"], d2["margin"], lp.SPREAD_SIGMA)
    check("zu sicher: Steigung < 0.9, Urteil 'zu sicher'", r2["gesamt_ueber_linien"]["steigung"] < 0.9 and verdict_slope(r2).startswith("zu sicher"), verdict_slope(r2))
    # 3) zu vorsichtig (wahre Streuung 10)
    d3 = synthetic(2500, 3, 10.0, lp.TOTAL_SIGMA, lp.TEAM_TOTAL_SIGMA)
    r3 = market_report(d3["mu_s"], d3["margin"], lp.SPREAD_SIGMA)
    check("zu vorsichtig: Steigung > 1.1, Urteil 'zu vorsichtig'", r3["gesamt_ueber_linien"]["steigung"] > 1.1 and verdict_slope(r3).startswith("zu vorsichtig"), verdict_slope(r3))
    # 4) Verzerrung wird gefunden
    r4 = point_errors(d["mu_t"] + 3.0, d["total"])
    check("Verzerrung +3 Punkte: Bias-Intervall schliesst 0 aus", r4["bias_ci95"][0] > 2 and abs(r4["bias"] - 3) < 0.6, r4["bias"])
    # 5) Sieg und Favorit-Stufen
    s, p, y = win_report(d["mu_s"], d["margin"])
    check("Sieg: Brier unter 0.25, Steigung nahe 1, Favorit-Stufen vorhanden", s["brier"] < 0.25 and abs(s["steigung"] - 1) < 0.2 and len(s["favorit_stufen"]) >= 3, (s["brier"], s["steigung"]))
    # 6) Abdeckung: kuenstlich verschobene Stufe wird erkannt
    bins = [{"stufe": "50-55 %", "n": 500, "abweichung_pp": 1.0}, {"stufe": "55-60 %", "n": 500, "abweichung_pp": -1.0}, {"stufe": "60-65 %", "n": 300, "abweichung_pp": 8.0}, {"stufe": "90+ %", "n": 20, "abweichung_pp": 20.0}]
    cv = coverage(bins)
    check("Abdeckung: Stufe mit >= 100 Zeilen und 8 PP daneben -> Schwelle nicht gedeckt; Stufe mit 20 Zeilen zaehlt nicht fuer das Kriterium", cv["0.55"]["gedeckt"] is False and cv["0.9"]["pruefbar"] is False, cv["0.6"])
    # 7) Kausalitaetskontrolle des Replays mit kuenstlichen Spielen
    rng = np.random.default_rng(5)
    teams = [f"Team {i}" for i in range(6)]
    games = []
    for i in range(120):
        h, a = rng.choice(6, 2, replace=False)
        games.append({"id": i, "date": f"2025-{1 + i // 30:02d}-{1 + i % 28:02d}", "season": 2025, "postseason": False, "status": "Final", "home_team": {"full_name": teams[h]}, "visitor_team": {"full_name": teams[a]},
                      "home_team_score": int(rng.normal(112, 10)), "visitor_team_score": int(rng.normal(110, 10)), "period": 4})
    games.sort(key=lambda g: (g["date"], g["id"]))
    rows, _, _, _ = rt.run(games, **PRODUCTION)
    c = causality_check(games, rows, [10, 60, 119])
    check("Replay kausal (kuenstliche Spiele): Teil-Lauf bis Spiel i = voller Lauf an Stelle i", c["ok"], c["stichproben"])
    games2 = [dict(g) for g in games]
    games2[-1]["home_team_score"] += 50                                     # ein SPAETERES Ergebnis aendern
    rows2, _, _, _ = rt.run(games2, **PRODUCTION)
    check("Aenderung eines spaeteren Ergebnisses veraendert keine fruehere Prognose", np.allclose(rows["diff"][:-1], rows2["diff"][:-1]) and np.allclose(rows["total_pred"][:-1], rows2["total_pred"][:-1]))
    # 8) Zusammenfassung/Text laeuft mit Kunstdaten durch
    dd = dict(d); dd.update(post=np.zeros(len(d["mu_s"]), int), gp_h=np.full(len(d["mu_s"]), 20), gp_a=np.full(len(d["mu_s"]), 20), ot=(np.random.default_rng(9).random(len(d["mu_s"])) < 0.07).astype(int))
    dd["gp_h"][:600] = 5
    rep_all = build_report([], {}, dd, {"spiele_replay": 0, "spiele_saison": len(dd["mu_s"]), "chronologisch": True, "paritaet_diff_max": 0.0, "kausalitaet": c})
    txt = render_text(rep_all, 0.0)
    check("Textbericht: Zusammenfassung <= 20 Zeilen, Abschnitte vorhanden", len(summary_lines(rep_all)) <= 20 and "TOTAL SPEZIELL" in txt and "AUFTEILUNGEN" in txt, len(summary_lines(rep_all)))
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    rep, rt_s = run_all()
    print("\n".join(summary_lines(rep)))
    print(f"\nErgebnisse: {RESULTS / OUT_JSON}\n            {RESULTS / OUT_TXT}\nLaufzeit: {rt_s:.1f} s")
