"""
Team-Test Runde 2 (NUR MESSEN, keine Empfehlung, kein Eingriff in das Produktivmodell). Baut auf analysis/bt_common.py, replica_tunable.py, backtest_team_markets.py auf (Replay, Linien-Raster, Berichte).
Schreibt nur analysis/results/backtest_team_round2.json und .txt; Zwischenergebnisse je Teil liegen ausserhalb des Projekts (--stage-dir, Standard /tmp/nbaedge_team2). Kein Netz.
Teil 6 liest Kopien von data/tracking/projection_snapshots.json und pre_match_entries.json (nach /tmp kopiert, nie am Original gearbeitet).

Aufbau
- Daten: games_2015..2025 (Cache). Auswertung: Regular Season der Saisons 2017-18 bis 2025-26 (9 Saisons, 2019-20 und 2020-21 verkuerzt). Referenz A = aktuelles Modell (Replay mit Produktivparametern,
  Sigmas 13,2 / 18,6 / 11,6, Siegchance = lp.win_prob_home).
- Training/Test: zwei Saison-Gruppen, ungerade Startjahre G1 = 2017, 2019, 2021, 2023, 2025 und gerade G2 = 2018, 2020, 2022, 2024. Parameter werden NUR auf der Trainingsgruppe gewaehlt/geschaetzt,
  getestet auf der anderen Gruppe, BEIDE Richtungen (G1 -> G2 und G2 -> G1). Der ELO-Replay selbst ist kausal (Spiel fuer Spiel); die Parameter/Koeffizienten stammen aber aus der anderen Gruppe (teils aus der
  Zukunft des Testspiels) - gemessen wird die Stabilitaet, nicht ein Live-Test. Teil 3 (Ausfaelle) hat nur Daten fuer 2024-25 und 2025-26: Richtungen 2024-25 -> 2025-26 und umgekehrt.
- Maerkte (Brier je Spiel, gemittelt ueber das Linien-Raster -5..+5 um den Modell-Mittelwert der REFERENZ A; alle Varianten werden an denselben Linien bewertet): Sieger, Spread (Heim deckt),
  Gesamt-Total (Over), Team-Total (Heim und Gast, Over). Bootstrap nach SPIELEN (1000 Ziehungen).
- Bewertungsregel je Variante und Markt: Verbesserung nur, wenn die Brier-Differenz (Variante minus A) in der Testgruppe negativ ist UND das Intervall die 0 nicht einschliesst UND in beiden Richtungen
  dasselbe Vorzeichen hat; Gegenteil (positiv, Intervall ohne 0, beide Richtungen) = schlechter; sonst "kein belastbarer Unterschied". Kalibrierung gut: mittlere Abweichung < 3 PP und keine Stufe mit >= 100
  Zeilen mehr als 6 PP daneben (Stufen der vorhergesagten Seite, gepoolte Testzeilen).
- Teil 1 K/MOV/Saisonuebergang (Replay-Varianten), Teil 2 Ruhe/Reise/Hoehe (additiv auf Spread/Total, OLS im Training), Teil 3 Star-Ausfaelle (Obergrenze: Ausfaelle nachtraeglich bekannt), Teil 4 Form
  (Zusatzterm, N = 5/10/15/20) plus Schattenvariante, Teil 5 Streuung/Verteilung, Teil 6 Modell gegen Markt (--market-vs-model, wiederholbar).
Aufruf (von aussen mit nice -n 15 starten):  venv/bin/python analysis/backtest_team_round2.py --all      oder --part N, --report, --market-vs-model, --selftest
"""
import json
import math
import shutil
import subprocess
import sys
import time
import warnings
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
from scipy import optimize, stats
from scipy.special import ndtr

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_team_markets as btm  # noqa: E402
from backtest_team_markets import KS, PRODUCTION, predicted_side_bins, coverage, rt, lp, ll  # noqa: E402
from sigma_check import thresholds  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR, MIN_WIN_PROB, MAX_WIN_PROB  # noqa: E402

ROOT = HERE.parent
RESULTS = HERE / "results"
OUT_JSON, OUT_TXT = "backtest_team_round2.json", "backtest_team_round2.txt"
SEASONS = list(range(2017, 2026))
MK = ("win", "spread", "total", "tt")
MNAME = {"win": "Sieger", "spread": "Spread", "total": "Total", "tt": "Teamtotal"}
B_BOOT = 1000
DIRS = (("G1->G2", 1, 0), ("G2->G1", 0, 1))             # (Name, Trainingsgruppe, Testgruppe) mit Gruppe 1 = ungerade Startjahre
VERS = {}


def pr(x, d=5):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


# ----------------------------------------------------------------------------------------------- Kontext, Bewertung
class Ctx:
    def __init__(self):
        self.games = btm.load_games(2015, 2025)
        self.rowsA, _, _, _ = rt.run(self.games, **PRODUCTION)
        r = self.rowsA
        self.E = np.where((r["post"] == 0) & (r["season"] >= SEASONS[0]))[0]
        self.n = len(self.E)
        self.season = r["season"][self.E].astype(int)
        self.grp = (self.season % 2 == 1).astype(int)                  # 1 = ungerade Startjahre (G1)
        self.margin, self.total = r["margin"][self.E], r["total"][self.E]
        self.pts_h, self.pts_a = (self.total + self.margin) / 2, (self.total - self.margin) / 2
        self.mu_s, self.mu_t = r["diff"][self.E] / ELO_TO_SPREAD_FACTOR, r["total_pred"][self.E]
        self.mu_h, self.mu_a = (self.mu_t + self.mu_s) / 2, (self.mu_t - self.mu_s) / 2
        self.dates = [self.games[i]["date"][:10] for i in self.E]
        self.month = np.array([int(d[5:7]) for d in self.dates])
        self.gp = np.minimum(r["gp_h"][self.E], r["gp_a"][self.E])
        self.L = {"s": thresholds(self.mu_s, KS), "t": thresholds(self.mu_t, KS), "h": thresholds(self.mu_h, KS), "a": thresholds(self.mu_a, KS)}   # Linien der Referenz A
        self.Y = {"s": self.margin[:, None] > self.L["s"], "t": self.total[:, None] > self.L["t"], "h": self.pts_h[:, None] > self.L["h"], "a": self.pts_a[:, None] > self.L["a"]}
        self.ywin = (self.margin > 0).astype(float)
        off = np.array([-2.0, -1.5, -1.0, 1.0, 1.5, 2.0])                       # Raender: Linien bei +-1 bis 2 Sigma um den Modell-Mittelwert (Chancen ca. 2-16 % und 84-98 %)
        sg = {"s": lp.SPREAD_SIGMA, "t": lp.TOTAL_SIGMA, "h": lp.TEAM_TOTAL_SIGMA, "a": lp.TEAM_TOTAL_SIGMA}
        mus = {"s": self.mu_s, "t": self.mu_t, "h": self.mu_h, "a": self.mu_a}
        xs = {"s": self.margin, "t": self.total, "h": self.pts_h, "a": self.pts_a}
        self.LT = {k: np.floor(mus[k])[:, None] + 0.5 + np.round(sg[k] * off)[None, :] for k in sg}
        self.YT = {k: xs[k][:, None] > self.LT[k] for k in sg}
        self.cache = {}

    def run(self, **kw):
        """Replay-Variante (gecached): Rueckgabe (mu_s, mu_t) auf den Auswertungsspielen."""
        key = tuple(sorted(kw.items()))
        if key not in self.cache:
            rows, _, _, _ = rt.run(self.games, **kw)
            self.cache[key] = (rows["diff"][self.E] / ELO_TO_SPREAD_FACTOR, rows["total_pred"][self.E])
        return self.cache[key]


def cdf(z, dist):
    return ndtr(z) if dist is None else stats.t.cdf(z, dist)


class Score:
    """Wahrscheinlichkeiten/Ausgaenge einer Variante an den festen Linien der Referenz; Brier und Log-Loss je Spiel."""

    def __init__(self, ctx, mu_s, mu_t, sig=None, dist=None, idx=None):
        sig = sig or {}
        dist = dist or {}
        ss, st, stt = sig.get("s", lp.SPREAD_SIGMA), sig.get("t", lp.TOTAL_SIGMA), sig.get("tt", lp.TEAM_TOTAL_SIGMA)
        mu_h, mu_a = (mu_t + mu_s) / 2, (mu_t - mu_s) / 2
        col = lambda v: v[:, None] if isinstance(v, np.ndarray) else v
        self.p = {"s": 1 - cdf((ctx.L["s"] - mu_s[:, None]) / col(ss), dist.get("s")), "t": 1 - cdf((ctx.L["t"] - mu_t[:, None]) / col(st), dist.get("t")),
                  "h": 1 - cdf((ctx.L["h"] - mu_h[:, None]) / col(stt), dist.get("tt")), "a": 1 - cdf((ctx.L["a"] - mu_a[:, None]) / col(stt), dist.get("tt"))}
        self.pt = {"s": 1 - cdf((ctx.LT["s"] - mu_s[:, None]) / col(ss), dist.get("s")), "t": 1 - cdf((ctx.LT["t"] - mu_t[:, None]) / col(st), dist.get("t")),
                   "h": 1 - cdf((ctx.LT["h"] - mu_h[:, None]) / col(stt), dist.get("tt")), "a": 1 - cdf((ctx.LT["a"] - mu_a[:, None]) / col(stt), dist.get("tt"))}
        pw = cdf(np.round(mu_s, 1) / ss, dist.get("s"))
        self.pwin = np.clip(pw, MIN_WIN_PROB, MAX_WIN_PROB)
        yb = lambda k: ctx.Y[k].astype(float)
        self.brier, self.ll = {}, {}
        for m, ks in (("spread", ("s",)), ("total", ("t",)), ("tt", ("h", "a"))):
            self.brier[m] = np.mean([((self.p[k] - yb(k)) ** 2).mean(axis=1) for k in ks], axis=0)
            self.ll[m] = np.mean([ll(self.p[k], yb(k)).mean(axis=1) for k in ks], axis=0)
        self.brier["win"] = (self.pwin - ctx.ywin) ** 2
        self.ll["win"] = ll(self.pwin, ctx.ywin)


def boot_ci(d, B=B_BOOT, seed=0):
    n = len(d)
    if n < 10:
        return float(d.mean()) if n else None, None, None
    idx = np.random.default_rng(seed).integers(0, n, (B, n))
    m = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def compare(V, A, mask, seed=1):
    out = {"n_spiele": int(mask.sum())}
    for m in MK:
        d = (V.brier[m] - A.brier[m])[mask]
        e = boot_ci(d, seed=seed)
        dl = boot_ci((V.ll[m] - A.ll[m])[mask], seed=seed + 100)
        out[m] = {"brier_A": pr(A.brier[m][mask].mean()), "brier_V": pr(V.brier[m][mask].mean()), "differenz": pr(e[0], 6), "ci95": [pr(e[1], 6), pr(e[2], 6)], "logloss_differenz": pr(dl[0], 6), "logloss_ci95": [pr(dl[1], 6), pr(dl[2], 6)]}
    return out


def verdict(per_dir):
    """Bewertungsregel je Markt ueber beide Richtungen."""
    out = {}
    for m in MK:
        rs = [x[m] for x in per_dir.values()]
        if any(r["ci95"][0] is None for r in rs):
            out[m] = "nicht bewertbar"
        elif all(r["differenz"] < 0 and r["ci95"][1] < 0 for r in rs):
            out[m] = "Verbesserung"
        elif all(r["differenz"] > 0 and r["ci95"][0] > 0 for r in rs):
            out[m] = "schlechter"
        else:
            out[m] = "kein belastbarer Unterschied"
    return out


def cal_check(p, y):
    """Kalibrierung nach der Regel (Stufen der vorhergesagten Seite, gepoolt): mittlere Abweichung und groesste Abweichung einer Stufe mit >= 100 Zeilen."""
    side = predicted_side_bins(p, y)
    if not side:
        return None
    n = sum(b["n"] for b in side)
    mad = sum(b["n"] * abs(b["abweichung_pp"]) for b in side) / n
    mx = max((abs(b["abweichung_pp"]) for b in side if b["n"] >= 100), default=0.0)
    p = np.asarray(p).ravel(); y = np.asarray(y).ravel()
    lo, hi = p < 0.15, p > 0.85
    edge = {"unter_15": {"n": int(lo.sum()), "modell": pr(p[lo].mean(), 3) if lo.any() else None, "treffer": pr(y[lo].mean(), 3) if lo.any() else None},
            "ueber_85": {"n": int(hi.sum()), "modell": pr(p[hi].mean(), 3) if hi.any() else None, "treffer": pr(y[hi].mean(), 3) if hi.any() else None}}
    return {"mittlere_abweichung_pp": pr(mad, 2), "max_stufe_ab100_pp": pr(mx, 2), "gut": bool(mad < 3 and mx <= 6), "raender": edge}


def pooled_cal(ctx, V, masks):
    sel = np.zeros(ctx.n, bool)
    for m in masks:
        sel |= m
    out = {}
    for name, ks in (("spread", ("s",)), ("total", ("t",)), ("tt", ("h", "a"))):
        p = np.concatenate([V.p[k][sel].ravel() for k in ks]); y = np.concatenate([ctx.Y[k][sel].astype(float).ravel() for k in ks])
        out[name] = cal_check(p, y)
    return out


def evaluate(ctx, name, version, make, A, note=""):
    """make(train_mask) -> (Score, params). Bewertet beide Richtungen und fasst nach der Regel zusammen."""
    res = {"name": name, "version": version, "hinweis": note, "richtungen": {}, "parameter": {}}
    tests, Vs = [], {}
    for dname, tr, te in DIRS:
        train, test = ctx.grp == tr, ctx.grp == te
        V, par = make(train)
        res["richtungen"][dname] = compare(V, A, test, seed=3)
        res["parameter"][dname] = par
        tests.append(test)
        Vs[dname] = V
    res["urteil"] = verdict(res["richtungen"])
    # Kalibrierung auf gepoolten Testzeilen (jede Richtung mit ihren eigenen Parametern)
    sel_p = {}
    for name_k, ks in (("spread", ("s",)), ("total", ("t",)), ("tt", ("h", "a"))):
        pv = np.concatenate([Vs[d].p[k][t].ravel() for (d, _, _), t in zip(DIRS, tests) for k in ks])
        pa = np.concatenate([A.p[k][t].ravel() for (d, _, _), t in zip(DIRS, tests) for k in ks])
        y = np.concatenate([ctx.Y[k][t].astype(float).ravel() for (d, _, _), t in zip(DIRS, tests) for k in ks])
        sel_p[name_k] = {"A": cal_check(pa, y), "V": cal_check(pv, y)}
    res["kalibrierung"] = sel_p
    res["raender"] = {}
    for name_k, ks in (("spread", ("s",)), ("total", ("t",)), ("tt", ("h", "a"))):
        pv = np.concatenate([Vs[d].pt[k][t].ravel() for (d, _, _), t in zip(DIRS, tests) for k in ks]); pa = np.concatenate([A.pt[k][t].ravel() for (d, _, _), t in zip(DIRS, tests) for k in ks])
        y = np.concatenate([ctx.YT[k][t].astype(float).ravel() for (d, _, _), t in zip(DIRS, tests) for k in ks])
        cell = lambda p: {"brier_raender": pr(((p - y) ** 2).mean(), 5), "logloss_raender": pr(ll(p, y).mean(), 5),
                          "unter_15": {"n": int((p < .15).sum()), "modell": pr(p[p < .15].mean(), 4) if (p < .15).any() else None, "treffer": pr(y[p < .15].mean(), 4) if (p < .15).any() else None},
                          "ueber_85": {"n": int((p > .85).sum()), "modell": pr(p[p > .85].mean(), 4) if (p > .85).any() else None, "treffer": pr(y[p > .85].mean(), 4) if (p > .85).any() else None}}
        res["raender"][name_k] = {"A": cell(pa), "V": cell(pv)}
    return res


# ----------------------------------------------------------------------------------------------- Hilfen: OLS
def ols(X, y):
    X1 = np.c_[np.ones(len(X)), X]
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    r = y - X1 @ beta
    s2 = (r @ r) / max(1, len(y) - X1.shape[1])
    cov = s2 * np.linalg.pinv(X1.T @ X1)
    return beta, np.sqrt(np.diag(cov))


def additive_variant(ctx, F, names, train, sep_total=True):
    """Additive Anpassung: Spread-/Total-Rest auf Merkmale F (zentriert am Training) per OLS im Training. Rueckgabe (mu_s, mu_t, Parameter)."""
    mean = np.nanmean(F[train], axis=0)
    Fc = np.where(np.isnan(F), 0.0, F - mean)
    bs, ses = ols(Fc[train], (ctx.margin - ctx.mu_s)[train])
    bt, set_ = ols(Fc[train], (ctx.total - ctx.mu_t)[train]) if sep_total else (np.zeros(F.shape[1] + 1), np.ones(F.shape[1] + 1))
    mu_s = ctx.mu_s + Fc @ bs[1:]
    mu_t = ctx.mu_t + (Fc @ bt[1:] if sep_total else 0.0)
    par = {"spread": {n: [pr(b, 3), pr(s, 3)] for n, b, s in zip(names, bs[1:], ses[1:])}, "total": {n: [pr(b, 3), pr(s, 3)] for n, b, s in zip(names, bt[1:], set_[1:])}}
    return mu_s, mu_t, par


# ----------------------------------------------------------------------------------------------- Teil 1: K, MOV, Saisonuebergang
def effective_k(ctx, K, mov):
    m = np.abs(ctx.margin)
    if mov == "cur":
        return float(np.mean(K * 2.2 * np.log(m + 1)))
    return float(np.mean(K * ((m + 3) ** 0.8) / 7.5))


def part1(ctx, A):
    t0 = time.time()
    cands = {f"cur-K{K}": dict(K=float(K), mov="cur") for K in (6, 8, 10, 12, 16, 20, 24, 28)}
    cands.update({f"538-K{K}": dict(K=float(K), mov="538") for K in (40, 60, 80, 100, 120, 150)})
    out = {"teil": 1, "varianten": [], "raster_training": {}}
    sc = {n: Score(ctx, *ctx.run(**{**PRODUCTION, **kw})) for n, kw in cands.items()}
    out["effektives_k"] = {n: pr(effective_k(ctx, kw["K"], kw["mov"]), 1) for n, kw in cands.items()}
    out["hinweis_k"] = "effektives K = mittlere Update-Staerke pro Spiel: cur = K x 2,2 x ln(Marge+1) (Produktiv: K = 20, MOV-Multiplikator vorhanden); 538 = K x (Marge+3)^0.8 / (7,5 + 0,006 x Rating-Vorsprung des Siegers) (Autokorrelations-Korrektur)."

    def pick(train, pool, market="spread"):
        vals = {n: float(s.brier[market][train].mean()) for n, s in pool.items()}
        return min(vals, key=vals.get), vals

    # 1a: K und MOV-Form
    def make_k(train):
        best, vals = pick(train, sc)
        names = list(sc)
        par = {"gewaehlt": best, "effektives_k": out["effektives_k"][best], "raster_brier_spread_training": {n: pr(v, 6) for n, v in vals.items()}, "am_rand": best in ("cur-K6", "cur-K28", "538-K40", "538-K150")}
        return sc[best], par
    out["varianten"].append(evaluate(ctx, "K und MOV-Form (Raster cur K=6..28 [eff. K ca. 31-143], 538 K=40..150; Raster nach unten erweitert)", "v3-elo-k-mov", make_k, A))
    # 1b: Saisonuebergang (Rueckfall zum Mittel) am Produktiv-K
    keeps = (1.0, 0.9, 0.8, 0.7, 0.6)
    sk = {k: Score(ctx, *ctx.run(**{**PRODUCTION, "keep": k})) for k in keeps}

    def make_keep(train):
        vals = {k: float(s.brier["spread"][train].mean()) for k, s in sk.items()}
        best = min(vals, key=vals.get)
        return sk[best], {"keep": best, "raster_brier_spread_training": {str(k): pr(v, 6) for k, v in vals.items()}, "am_rand": best in (1.0, 0.6)}
    out["varianten"].append(evaluate(ctx, "Saisonuebergang Rating (keep 1,0..0,6; 1,0 = Produktiv)", "v3-elo-keep", make_keep, A))
    # 1c: Saisonuebergang der Total-Werte (Off/Def)
    tks = (1.0, 0.85, 0.7, 0.55)
    stk = {k: Score(ctx, *ctx.run(**{**PRODUCTION, "total_keep": k})) for k in tks}

    def make_tkeep(train):
        vals = {k: float(s.brier["total"][train].mean()) for k, s in stk.items()}
        best = min(vals, key=vals.get)
        return stk[best], {"total_keep": best, "raster_brier_total_training": {str(k): pr(v, 6) for k, v in vals.items()}, "am_rand": best in (1.0, 0.55)}
    out["varianten"].append(evaluate(ctx, "Saisonuebergang Total (total_keep 1,0..0,55)", "v3-total-keep", make_tkeep, A))
    # 1d: Kombination der in der Trainingsgruppe gewaehlten Parameter (eigener Replay je Richtung)

    def make_comb(train):
        bk, _ = pick(train, sc)
        kw = {**PRODUCTION, **cands[bk]}
        vals = {k: float(Score(ctx, *ctx.run(**{**kw, "keep": k})).brier["spread"][train].mean()) for k in keeps}
        bkeep = min(vals, key=vals.get)
        tvals = {k: float(stk[k].brier["total"][train].mean()) for k in tks}
        btk = min(tvals, key=tvals.get)
        mu_s, _ = ctx.run(**{**kw, "keep": bkeep})
        _, mu_t = ctx.run(**{**PRODUCTION, "total_keep": btk})
        return Score(ctx, mu_s, mu_t), {"k_mov": bk, "keep": bkeep, "total_keep": btk}
    out["varianten"].append(evaluate(ctx, "Kombination K/MOV + keep + total_keep (Training-Wahl)", "v3-elo-kombi", make_comb, A))
    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Teil 2: Ruhe, Reise, Hoehe
ARENA = {"ATL": (33.76, -84.39, 0), "BKN": (40.68, -73.97, 0), "BOS": (42.37, -71.06, 0), "CHA": (35.23, -80.84, 0), "CHI": (41.88, -87.67, -1), "CLE": (41.50, -81.69, 0), "DAL": (32.79, -96.81, -1),
         "DEN": (39.75, -105.0, -2), "DET": (42.34, -83.06, 0), "GSW": (37.77, -122.39, -3), "HOU": (29.75, -95.36, -1), "IND": (39.76, -86.16, 0), "LAC": (34.04, -118.27, -3), "LAL": (34.04, -118.27, -3),
         "MEM": (35.14, -90.05, -1), "MIA": (25.78, -80.19, 0), "MIL": (43.04, -87.92, -1), "MIN": (44.98, -93.28, -1), "NOP": (29.95, -90.08, -1), "NYK": (40.75, -73.99, 0), "OKC": (35.46, -97.52, -1),
         "ORL": (28.54, -81.38, 0), "PHI": (39.90, -75.17, 0), "PHX": (33.45, -112.07, -2), "POR": (45.53, -122.67, -3), "SAC": (38.58, -121.50, -3), "SAS": (29.43, -98.44, -1), "TOR": (43.64, -79.38, 0),
         "UTA": (40.77, -111.90, -2), "WAS": (38.90, -77.02, 0)}


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def schedule_features(ctx):
    """Merkmale je Auswertungsspiel (Spalten siehe FEAT_NAMES). Zustand je Team wird chronologisch ueber ALLE Spiele (inkl. Playoffs, ab 2015) gefuehrt."""
    state = {}
    feats = {}
    for gi, g in enumerate(ctx.games):
        h, a = g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"]
        d = date.fromisoformat(g["date"][:10])
        venue = ARENA[h]
        row = {}
        for side, t, away in (("h", h, False), ("a", a, True)):
            st = state.get(t)
            if st is None:
                rest, b2b, three, trip, dist, tz = 4, 0, 0, 0, 0.0, 0.0
            else:
                rest = min(4, (d - st["date"]).days)
                b2b = int(rest == 1)
                three = int(sum(1 for x in st["last"] if (d - x).days <= 3) >= 2)
                trip = st["trip"] if away else 0
                dist = km(ARENA[st["venue"]], venue) / 1000.0
                tz = float(venue[2] - ARENA[st["venue"]][2])
            row[side] = (rest, b2b, three, trip, dist, tz)
        feats[gi] = (row["h"], row["a"], int(h in ("DEN", "UTA")))
        for t, away in ((h, False), (a, True)):
            st = state.setdefault(t, {"date": d, "venue": h, "last": [], "trip": 0})
            st["last"] = [x for x in st["last"] + [d] if (d - x).days <= 3]
            st["trip"] = st["trip"] + 1 if away else 0
            st["date"], st["venue"] = d, h
    F = np.zeros((ctx.n, 11))
    for j, gi in enumerate(ctx.E):
        fh, fa, alt = feats[gi]
        F[j] = [fh[1], fa[1], fh[2], fa[2], fh[0] - fa[0], fa[3], fa[4], fh[4], fa[5], fh[5], alt]
    return F


FEAT_NAMES = ["b2b_heim", "b2b_gast", "3in4_heim", "3in4_gast", "ruhetage_heim_minus_gast", "auswaertsserie_gast_spiel", "reise_gast_1000km", "reise_heim_1000km", "zeitzone_gast_ost+", "zeitzone_heim_ost+", "hoehe_DEN_UTA_heim"]


def part2(ctx, A):
    t0 = time.time()
    F = schedule_features(ctx)
    out = {"teil": 2, "varianten": [], "hinweis": "additive Anpassung auf Spread und Total (OLS der Modell-Residuen im Training, Merkmale am Training zentriert); das Produktivmodell enthaelt bereits Ruhetage-Terme "
                                                "(Back-to-Back -1,5 ELO, >= 3 Tage +0,45 ELO, d. h. ca. 0,03 Punkte).", "merkmal_mittelwerte": {n: pr(float(F[:, i].mean()), 3) for i, n in enumerate(FEAT_NAMES)}}
    groups = {"Ruhe (b2b, 3-in-4, Ruhetage)": [0, 1, 2, 3, 4], "Reise (Auswaertsserie, km, Zeitzone)": [5, 6, 7, 8, 9], "Hoehe (Denver/Utah)": [10], "alles zusammen": list(range(11))}
    for gname, cols in groups.items():
        def make(train, cols=cols):
            mu_s, mu_t, par = additive_variant(ctx, F[:, cols], [FEAT_NAMES[c] for c in cols], train)
            return Score(ctx, mu_s, mu_t), par
        out["varianten"].append(evaluate(ctx, gname, "v3-zeitplan-" + gname.split()[0].lower(), make, A))
    # Effektstaerke in Punkten (Spread): Koeffizienten auf allen Spielen (Information, keine Bewertung)
    bs, ses = ols(F, ctx.margin - ctx.mu_s)
    bt, set_ = ols(F, ctx.total - ctx.mu_t)
    out["koeffizienten_alle_spiele"] = {n: {"spread_pkt": [pr(bs[i + 1], 3), pr(ses[i + 1], 3)], "total_pkt": [pr(bt[i + 1], 3), pr(set_[i + 1], 3)]} for i, n in enumerate(FEAT_NAMES)}
    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Teil 3: Star-Ausfaelle
def load_player_rows():
    rows = []
    for f in ("backtest_player_games_2023-24.json", "backtest_player_games_2024-25.json", "player_games_2025-26.json"):
        p = ROOT / "data" / "cache" / f
        if p.exists():
            rows += json.loads(p.read_text())["rows"]
    return rows


def absence_features(ctx):
    """Je Auswertungsspiel (nur 2024-25, 2025-26): abwesende Top-3-Rotationsspieler (nach Minuten der letzten 10 Teamspiele) je Seite. Rueckgabe (F, gueltig-Maske)."""
    rows = load_player_rows()
    by_team = defaultdict(lambda: defaultdict(list))                   # team -> (date, game_id) -> [(pid, min)]
    for r in rows:
        by_team[r["team"]][(r["date"], r["game_id"])].append((r["person_id"], r["minutes"]))
    seq = {t: sorted(g) for t, g in by_team.items()}
    pos = {t: {k: i for i, k in enumerate(v)} for t, v in seq.items()}
    tg_by_date = {}
    for t, v in seq.items():
        for (d, gid) in v:
            tg_by_date[(t, d)] = (d, gid)

    def absent(team, d):
        k = tg_by_date.get((team, d))
        if k is None:
            return None
        i = pos[team][k]
        if i < 10:
            return None
        mins = defaultdict(float)
        for kk in seq[team][i - 10:i]:
            for pid, m in by_team[team][kk]:
                mins[pid] += m
        top = [p for p, _ in sorted(mins.items(), key=lambda x: -x[1])[:3]]
        played = {pid for pid, m in by_team[team][k] if m > 0}
        return [int(p not in played) for p in top] + [0] * (3 - len(top))
    F = np.full((ctx.n, 6), np.nan)
    for j, gi in enumerate(ctx.E):
        g = ctx.games[gi]
        d = g["date"][:10]
        ah, aa = absent(g["home_team"]["abbreviation"], d), absent(g["visitor_team"]["abbreviation"], d)
        if ah is not None and aa is not None:
            F[j] = ah + aa
    ok = ~np.isnan(F[:, 0])
    return F, ok


def part3(ctx, A):
    t0 = time.time()
    F, ok = absence_features(ctx)
    names = ["heim_Rang1_fehlt", "heim_Rang2_fehlt", "heim_Rang3_fehlt", "gast_Rang1_fehlt", "gast_Rang2_fehlt", "gast_Rang3_fehlt"]
    seas = {"2024-25": ctx.season == 2024, "2025-26": ctx.season == 2025}
    out = {"teil": 3, "varianten": [], "hinweis": "OBERGRENZE: Ausfaelle sind hier nachtraeglich aus dem tatsaechlichen Einsatz bekannt (wer von den Top-3 der letzten 10 Teamspiele nicht gespielt hat); vor dem Spiel sind sie nur teilweise bekannt. "
                                                "Daten nur fuer 2024-25 und 2025-26 (2023-24 nur als Vorlauf). Richtungen: 2024-25 -> 2025-26 und umgekehrt.",
           "abdeckung": {k: {"spiele": int((m & ok).sum()), "mit_ausfall_heim": int(((F[:, :3].sum(1) > 0) & m & ok).sum()), "mit_ausfall_gast": int(((F[:, 3:].sum(1) > 0) & m & ok).sum())} for k, m in seas.items()}}
    dirs = (("24-25->25-26", "2024-25", "2025-26"), ("25-26->24-25", "2025-26", "2024-25"))
    res = {"name": "Star-Ausfaelle Top-3 (Rolle 1/2/3), Anpassung Spread und Total", "version": "v3-ausfaelle-top3", "richtungen": {}, "parameter": {}}
    Vs, tests = {}, []
    for dname, tr, te in dirs:
        train, test = seas[tr] & ok, seas[te] & ok
        mean = np.zeros(6)                                              # nicht zentrieren: Merkmale sind 0/1, Nullpunkt = niemand fehlt
        Fz = np.where(np.isnan(F), 0.0, F)
        X = np.c_[Fz[:, :3] - Fz[:, 3:], Fz[:, :3] + Fz[:, 3:]]         # Spread: Heim-Ausfall minus Gast-Ausfall je Rolle; Total: Summe je Rolle
        bs, ses = ols(X[train][:, :3], (ctx.margin - ctx.mu_s)[train])
        bt, set_ = ols(X[train][:, 3:], (ctx.total - ctx.mu_t)[train])
        mu_s = ctx.mu_s + X[:, :3] @ bs[1:]
        mu_t = ctx.mu_t + X[:, 3:] @ bt[1:]
        V = Score(ctx, mu_s, mu_t)
        res["richtungen"][dname] = compare(V, A, test, seed=5)
        res["parameter"][dname] = {"spread_pkt_je_Rolle(Heim-Ausfall)": [[pr(b, 2), pr(s, 2)] for b, s in zip(bs[1:], ses[1:])], "total_pkt_je_Rolle(beide Seiten)": [[pr(b, 2), pr(s, 2)] for b, s in zip(bt[1:], set_[1:])],
                                   "zeilen_training": int(train.sum())}
        Vs[dname] = V; tests.append(test)
    res["urteil"] = verdict(res["richtungen"])
    res["kalibrierung"] = {}
    for name_k, ks in (("spread", ("s",)), ("total", ("t",)), ("tt", ("h", "a"))):
        pv = np.concatenate([Vs[d].p[k][t].ravel() for (d, _, _), t in zip(dirs, tests) for k in ks]); pa = np.concatenate([A.p[k][t].ravel() for (d, _, _), t in zip(dirs, tests) for k in ks])
        y = np.concatenate([ctx.Y[k][t].astype(float).ravel() for (d, _, _), t in zip(dirs, tests) for k in ks])
        res["kalibrierung"][name_k] = {"A": cal_check(pa, y), "V": cal_check(pv, y)}
    out["varianten"].append(res)
    # Effekt in Punkten auf allen Spielen mit Daten (Information)
    Fz = np.where(np.isnan(F), 0.0, F)
    m = ok
    bs, ses = ols((Fz[:, :3] - Fz[:, 3:])[m], (ctx.margin - ctx.mu_s)[m])
    bt, set_ = ols((Fz[:, :3] + Fz[:, 3:])[m], (ctx.total - ctx.mu_t)[m])
    out["effekt_alle_spiele"] = {"spiele": int(m.sum()), "spread_pkt_je_Rolle": [[pr(b, 2), pr(s, 2)] for b, s in zip(bs[1:], ses[1:])], "total_pkt_je_Rolle": [[pr(b, 2), pr(s, 2)] for b, s in zip(bt[1:], set_[1:])]}
    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Teil 4: Form
def form_features(ctx, Ns=(5, 10, 15, 20, 30, 40)):
    """Mittlere Punktedifferenz (Teamsicht) und mittleres Spiel-Total der letzten N Spiele je Team vor dem Spiel (ueber Saisongrenzen, ab 3 Spielen)."""
    hist = defaultdict(list)
    fm = {N: np.zeros(ctx.n) for N in Ns}
    ft = {N: np.full(ctx.n, np.nan) for N in Ns}
    pos = {gi: j for j, gi in enumerate(ctx.E)}
    for gi, g in enumerate(ctx.games):
        h, a = g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"]
        if gi in pos:
            j = pos[gi]
            for N in Ns:
                hh, ha = hist[h][-N:], hist[a][-N:]
                if len(hh) >= 3 and len(ha) >= 3:
                    fm[N][j] = np.mean([x[0] for x in hh]) - np.mean([x[0] for x in ha])
                    ft[N][j] = (np.mean([x[1] for x in hh]) + np.mean([x[1] for x in ha])) / 2
        mg = int(g["home_team_score"]) - int(g["visitor_team_score"])
        tot = int(g["home_team_score"]) + int(g["visitor_team_score"])
        hist[h].append((mg, tot)); hist[a].append((-mg, tot))
    return fm, ft


def part4(ctx, A):
    t0 = time.time()
    fm, ft = form_features(ctx)
    Ns = (5, 10, 15, 20)
    out = {"teil": 4, "varianten": [], "hinweis": "Zusatzterm auf den ELO-Spread: Koeffizient x (mittlere Punktedifferenz der letzten N Spiele Heim minus Gast), beim Total Koeffizient x mittleres Total der letzten N Spiele "
                                                  "(OLS im Training, zentriert). Das Produktivmodell enthaelt schon einen Form-Term (gewichtete Siegquote der letzten 10 Spiele x 40 ELO)."}
    pool = {}
    for N in (5, 10, 15, 20, 30, 40):
        pool[N] = np.c_[fm[N], ft[N]]

    def make(train):
        best, vals = None, {}
        for N in Ns:
            mu_s, mu_t, par = additive_variant(ctx, pool[N], ["form_diff", "form_total"], train)
            vals[N] = (float(Score(ctx, mu_s, mu_t).brier["spread"][train].mean()) + float(Score(ctx, mu_s, mu_t).brier["total"][train].mean()), (mu_s, mu_t, par))
        best = min(vals, key=lambda n: vals[n][0])
        mu_s, mu_t, par = vals[best][1]
        par = {**par, "N": best, "raster_brier_summe_training": {str(n): pr(v[0], 6) for n, v in vals.items()}, "am_rand": best in (5, 20)}
        return Score(ctx, mu_s, mu_t), par
    out["varianten"].append(evaluate(ctx, "Form-Zusatzterm (N = 5/10/15/20, gewaehlt im Training)", "v3-form-n", make, A))
    for N in (5, 10, 15, 20, 30, 40):                                  # jedes N einzeln (Information; 30 und 40 = Raster-Erweiterung, nicht Teil der Wahl)
        def mk(train, N=N):
            mu_s, mu_t, par = additive_variant(ctx, pool[N], ["form_diff", "form_total"], train)
            return Score(ctx, mu_s, mu_t), par
        out["varianten"].append(evaluate(ctx, f"Form-Zusatzterm N = {N}", f"v3-form-n{N}", mk, A))

    # Schattenvariante (keine Kandidatin): einfache Form-Rating-Formel (die "DeepSeek-Formel" ist nicht auffindbar: Desktop-Datei deepseek_markdown_20261022_d8c5bd.md ist nur eine To-do-Liste)
    def mk_sh(train):
        N = 10
        Fz = np.where(np.isnan(pool[N]), np.nanmean(pool[N][train], axis=0), pool[N])
        bs, _ = ols(Fz[train][:, :1], ctx.margin[train])                # Spread = a + s x Form-Differenz (Heimvorteil a im Training)
        bt, _ = ols(Fz[train][:, 1:], ctx.total[train])
        return Score(ctx, bs[0] + bs[1] * Fz[:, 0], bt[0] + bt[1] * Fz[:, 1]), {"spread": f"{bs[0]:.2f} + {bs[1]:.3f} x Form10", "total": f"{bt[0]:.1f} + {bt[1]:.3f} x Total10"}
    sh = evaluate(ctx, "Schatten: Form-Rating-Formel allein (Punktedifferenz der letzten 10 Spiele, Spread = a + s x Differenz, Total = a + b x mittleres Total)", "v3-form-schatten", mk_sh, A,
                  note="NUR mitlaufen lassen, keine Kandidatin. Formel nicht auffindbar, einfache Ersatzformel.")
    out["varianten"].append(sh)

    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Teil 5: Streuung, Verteilung
def diag(res, label):
    return {"n": int(len(res)), "mittel": pr(res.mean(), 3), "sd": pr(res.std(), 3), "schiefe": pr(stats.skew(res), 3), "ueberschuss_kurtosis": pr(stats.kurtosis(res), 3),
            "quantile_1_5_50_95_99": [pr(v, 2) for v in np.percentile(res, [1, 5, 50, 95, 99])], "anteil_ueber_2sd": pr(float((np.abs(res - res.mean()) > 2 * res.std()).mean()), 4)}


def part5(ctx, A):
    t0 = time.time()
    R = {"spread": ctx.margin - ctx.mu_s, "total": ctx.total - ctx.mu_t, "tt": np.concatenate([ctx.pts_h - ctx.mu_h, ctx.pts_a - ctx.mu_a])}
    out = {"teil": 5, "verteilung": {}, "streuung_nach": {}, "varianten": []}
    for k, r in R.items():
        out["verteilung"][k] = {"alle": diag(r, k), "G1": diag(r[np.r_[ctx.grp == 1] if k != "tt" else np.r_[ctx.grp == 1, ctx.grp == 1]], k), "G2": diag(r[np.r_[ctx.grp == 0] if k != "tt" else np.r_[ctx.grp == 0, ctx.grp == 0]], k)}
    def sd_by(vals, edges, labels, r):
        o = {}
        for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
            m = (vals >= lo) & (vals < hi)
            if m.sum() >= 50:
                o[lab] = {"n": int(m.sum()), "sd": pr(r[m].std(), 2), "mittel": pr(r[m].mean(), 2)}
        return o
    qs = np.percentile(ctx.mu_t, [33, 67])
    fav = np.abs(ctx.mu_s)
    out["streuung_nach"]["spread"] = {"nach_favoritenstaerke_|Spread|": sd_by(fav, [0, 3, 6, 9, 99], ["0-3", "3-6", "6-9", "9+"], R["spread"]), "nach_modell_total(Tempo)": sd_by(ctx.mu_t, [0, qs[0], qs[1], 999], ["niedrig", "mittel", "hoch"], R["spread"]),
                                      "nach_monat": {str(m): {"n": int((ctx.month == m).sum()), "sd": pr(R["spread"][ctx.month == m].std(), 2)} for m in (10, 11, 12, 1, 2, 3, 4)}}
    out["streuung_nach"]["total"] = {"nach_modell_total(Linie/Tempo)": sd_by(ctx.mu_t, [0, qs[0], qs[1], 999], ["niedrig", "mittel", "hoch"], R["total"]), "nach_favoritenstaerke_|Spread|": sd_by(fav, [0, 3, 6, 9, 99], ["0-3", "3-6", "6-9", "9+"], R["total"]),
                                     "nach_monat": {str(m): {"n": int((ctx.month == m).sum()), "sd": pr(R["total"][ctx.month == m].std(), 2), "mittel": pr(R["total"][ctx.month == m].mean(), 2)} for m in (10, 11, 12, 1, 2, 3, 4)}}
    mu_tt = np.concatenate([ctx.mu_h, ctx.mu_a])
    out["streuung_nach"]["tt"] = {"nach_erwarteten_Teampunkten": sd_by(mu_tt, [0, 108, 112, 116, 999], ["<108", "108-112", "112-116", "116+"], R["tt"])}

    # Anpassung von Sigma/Verteilung (Training): Maximum-Likelihood
    def fit(mkey, train, dyn, tdist):
        r = R[mkey][train if mkey != "tt" else np.r_[train, train]]
        if mkey == "spread":
            z = np.c_[np.abs(ctx.mu_s), ctx.mu_t - 226.0][train]
        elif mkey == "total":
            z = np.c_[ctx.mu_t - 226.0, np.abs(ctx.mu_s)][train]
        else:
            zz = np.c_[np.concatenate([ctx.mu_h, ctx.mu_a]) - 113.0, np.concatenate([np.abs(ctx.mu_s)] * 2)]
            z = zz[np.r_[train, train]]
        base = {"spread": lp.SPREAD_SIGMA, "total": lp.TOTAL_SIGMA, "tt": lp.TEAM_TOTAL_SIGMA}[mkey]
        zc = z - z.mean(axis=0)

        def nll(th):
            ls = th[0] + (zc @ th[1:3] if dyn else 0.0)
            sg = np.exp(ls)
            if tdist:
                nu = 2.0 + math.exp(th[3])
                return float(-(stats.t.logpdf(r / sg, nu) - np.log(sg)).sum())
            return float((np.log(sg) + 0.5 * (r / sg) ** 2).sum())
        x0 = np.array([math.log(base), 0.0, 0.0, math.log(10.0)])
        o = optimize.minimize(nll, x0, method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-4, "fatol": 1e-4})
        return o.x, z.mean(axis=0), base

    def make_variant(dyn, tdist):
        def make(train):
            sig, dist, par = {}, {}, {}
            for mkey, sk in (("spread", "s"), ("total", "t"), ("tt", "tt")):
                th, zm, base = fit(mkey, train, dyn, tdist)
                if mkey == "spread":
                    z = np.c_[np.abs(ctx.mu_s), ctx.mu_t - 226.0]
                elif mkey == "total":
                    z = np.c_[ctx.mu_t - 226.0, np.abs(ctx.mu_s)]
                else:
                    z = None
                if mkey == "tt":
                    zh = np.c_[ctx.mu_h - 113.0, np.abs(ctx.mu_s)]
                    za = np.c_[ctx.mu_a - 113.0, np.abs(ctx.mu_s)]
                    zm_ = zm
                    sigma = np.exp(th[0] + ((zh - zm_) @ th[1:3] if dyn else 0.0))                      # eine Sigma je Spiel fuer Heim; Gast mit eigenem z unten gemittelt
                    sigma_a = np.exp(th[0] + ((za - zm_) @ th[1:3] if dyn else 0.0))
                    sg = (sigma + sigma_a) / 2 if dyn else float(np.exp(th[0]))
                else:
                    sg = np.exp(th[0] + ((z - zm) @ th[1:3] if dyn else 0.0)) if dyn else float(np.exp(th[0]))
                sig[sk] = sg
                if tdist:
                    dist[sk] = 2.0 + math.exp(th[3])
                par[mkey] = {"sigma_basis": pr(float(np.exp(th[0])), 3), "koeff_log_sigma": [pr(x, 4) for x in th[1:3]] if dyn else None, "df": pr(2.0 + math.exp(th[3]), 2) if tdist else None, "sigma_produktiv": base}
            return Score(ctx, ctx.mu_s, ctx.mu_t, sig=sig, dist=dist), par
        return make
    for dyn, tdist, name, ver in ((False, False, "Sigma neu geschaetzt (statisch, Normal)", "v3-sigma-statisch"), (True, False, "dynamische Sigma (Favoritenstaerke, Tempo) Normal", "v3-sigma-dynamisch"),
                                  (False, True, "Student-t (statisch, df im Training)", "v3-student-t"), (True, True, "dynamische Sigma + Student-t", "v3-sigma-dynamisch-t")):
        out["varianten"].append(evaluate(ctx, name, ver, make_variant(dyn, tdist), A))
    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Teil 6: Modell gegen Markt
def devig(o1, o2):
    a, b = 1.0 / o1, 1.0 / o2
    return a / (a + b)


def market_vs_model(src_dir: Path, tmp_dir: Path = Path("/tmp/nbaedge_team2_copy"), since="2026-10-22"):
    """Wiederholbar: kopiert projection_snapshots.json und pre_match_entries.json nach tmp_dir und wertet die Spiele ab `since` mit Ergebnis aus."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for f in ("projection_snapshots.json", "pre_match_entries.json"):
        shutil.copy2(src_dir / f, tmp_dir / f)
    snaps = json.loads((tmp_dir / "projection_snapshots.json").read_text())["games"]
    entries = json.loads((tmp_dir / "pre_match_entries.json").read_text())["entries"]
    ent_idx = {(v["start_utc"], v["home"], v["away"]): v for v in entries.values()}
    SIG = {"s": lp.SPREAD_SIGMA, "t": lp.TOTAL_SIGMA, "tt": lp.TEAM_TOTAL_SIGMA}
    recs = {k: [] for k in ("win", "spread", "total", "tt")}
    used = skipped = 0
    for key, g in snaps.items():
        res = g.get("result") or {}
        if not res or g["game_date"] < since:
            continue
        e = ent_idx.get((g["start_utc"], g["home"], g["away"]))
        start = g["start_utc"]
        vers = [v for v in g["versions"] if datetime.fromisoformat(v["saved_at"]).astimezone().timestamp() < datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()]
        if not vers or e is None:
            skipped += 1
            continue
        pj = vers[-1]["projection"]
        hp, ap = res["home_points"], res["away_points"]
        mk = e["markets"]
        used += 1
        w = mk.get("winner_incl_ot")
        if w:
            recs["win"].append((pj["home_win_prob"], devig(w["home_odds"], w["away_odds"]), float(hp > ap)))
        for ln in (mk.get("spread") or {}).get("lines", []):
            if ln.get("active", True) and ln.get("home_odds") and ln.get("away_odds"):
                p = 1 - ndtr((-ln["line_home"] - pj["exp_spread"]) / SIG["s"])              # Heim deckt: Marge + Linie > 0
                recs["spread"].append((float(p), devig(ln["home_odds"], ln["away_odds"]), float((hp - ap) + ln["line_home"] > 0)))
        for ln in (mk.get("total") or {}).get("lines", []):
            if ln.get("active", True) and ln.get("over_odds") and ln.get("under_odds"):
                recs["total"].append((float(1 - ndtr((ln["line"] - pj["exp_total"]) / SIG["t"])), devig(ln["over_odds"], ln["under_odds"]), float(hp + ap > ln["line"])))
        tt = mk.get("team_totals") or {}
        for side, mu, pts in (("home", pj["home_score"], hp), ("away", pj["away_score"], ap)):
            for ln in (tt.get(side) or {}).get("lines", []):
                if ln.get("active", True) and ln.get("over_odds") and ln.get("under_odds"):
                    recs["tt"].append((float(1 - ndtr((ln["line"] - mu) / SIG["tt"])), devig(ln["over_odds"], ln["under_odds"]), float(pts > ln["line"])))
    out = {"warnung": "ZU WENIG DATEN FUER SCHLUESSE (wenige Spiele, Zeilen eines Spiels korreliert, kein Intervall belastbar). Nur Beschreibung. Das Modell ist hier die ANGEZEIGTE Projektion (mit Markt-Mischung "
                      "Spread 25 %, Total 32-55 %), nicht das reine Modell; die Betano-Chance ist ohne Marge (1/Quote normiert).", "spiele_verwendet": used, "spiele_ohne_version_oder_eintrag": skipped, "maerkte": {}}
    for m, rows in recs.items():
        if not rows:
            out["maerkte"][m] = {"zeilen": 0}
            continue
        a = np.array(rows)
        pm, pb, y = a[:, 0], a[:, 1], a[:, 2]
        d = {"zeilen": len(a), "brier_modell": pr(((pm - y) ** 2).mean(), 4), "brier_betano": pr(((pb - y) ** 2).mean(), 4), "differenz_modell_minus_betano": pr((((pm - y) ** 2) - ((pb - y) ** 2)).mean(), 4),
             "mittel_modell": pr(pm.mean(), 3), "mittel_betano": pr(pb.mean(), 3), "trefferquote": pr(y.mean(), 3)}
        for t in (3, 5, 8):
            sel = (pm - pb) * 100 >= t
            d[f"modell_ueber_betano_ab_{t}pp"] = {"zeilen": int(sel.sum()), "trefferquote": pr(y[sel].mean(), 3) if sel.any() else None, "mittel_betano": pr(pb[sel].mean(), 3) if sel.any() else None}
        out["maerkte"][m] = d
    return out


def mode_market(stage):
    rep = market_vs_model(ROOT / "data" / "tracking")
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "part6.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=float)[:3000])


# ----------------------------------------------------------------------------------------------- Ablauf, Bericht
PARTS = {1: part1, 2: part2, 3: part3, 4: part4, 5: part5}


def mode_part(n, stage):
    t0 = time.time()
    ctx = Ctx()
    A = Score(ctx, ctx.mu_s, ctx.mu_t)
    out = PARTS[n](ctx, A)
    out["spiele_auswertung"] = ctx.n
    out["spiele_je_gruppe"] = {"G1": int((ctx.grp == 1).sum()), "G2": int((ctx.grp == 0).sum())}
    out["brier_A"] = {m: pr(A.brier[m].mean(), 5) for m in MK}
    stage.mkdir(parents=True, exist_ok=True)
    (stage / f"part{n}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"Teil {n} fertig in {time.time() - t0:.0f} s", flush=True)


def nice_popen(args, log):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve())] + args, stdout=open(log, "w"), stderr=subprocess.STDOUT)


def mode_all(stage):
    t0 = time.time()
    stage.mkdir(parents=True, exist_ok=True)
    mode_market(stage)
    for batch in ((1, 2), (3, 4), (5,)):
        procs = [nice_popen(["--part", str(n), "--stage-dir", str(stage)], stage / f"log_part{n}.txt") for n in batch]
        codes = [p.wait() for p in procs]
        if any(codes):
            print(f"Abbruch in Teilen {batch}: Codes {codes}; Logs in {stage}", flush=True)
            return 1
        print(f"Teile {batch} fertig nach {time.time() - t0:.0f} s", flush=True)
    return mode_report(stage, t0)


def f5(x, sign=True):
    return "-" if x is None else f"{x:+.5f}" if sign else f"{x:.5f}"


def var_line(v):
    pd = v["richtungen"]
    parts = []
    for m in MK:
        ds = [f"{pd[d][m]['differenz']:+.5f} [{pd[d][m]['ci95'][0]:+.5f}; {pd[d][m]['ci95'][1]:+.5f}]" for d in pd if pd[d][m]["ci95"][0] is not None]
        parts.append(f"{MNAME[m]} {' | '.join(ds)} => {v['urteil'][m]}")
    return parts


def summary(parts, runtime):
    L = ["ZUSAMMENFASSUNG Team-Test Runde 2 (nur Messung; KEINE Änderung am Produktivmodell, KEINE Empfehlung für die App; Referenz A = aktuelles Modell, reines Modell ohne Markt-Mischung)",
         "Regel: Verbesserung nur bei negativer Brier-Differenz zu A in der Testgruppe, Intervall ohne 0 und gleichem Vorzeichen in BEIDEN Richtungen (G1->G2, G2->G1; Gruppen = ungerade/gerade Saisonstartjahre 2017-2025)."]
    better, none = [], []
    for n in sorted(parts):
        for v in parts[n].get("varianten", []):
            imp = [MNAME[m] for m in MK if v["urteil"][m] == "Verbesserung"]
            bad = [MNAME[m] for m in MK if v["urteil"][m] == "schlechter"]
            (better if imp else none).append((n, v, imp, bad))
    L.append(f"Belastbar besser als A (nach Regel): " + ("; ".join(f"Teil {n} '{v['name'][:60]}' bei {', '.join(imp)}" for n, v, imp, bad in better) if better else "KEINE Variante.") )
    for n, v, imp, bad in better:
        L.append(f"   Teil {n} {v['version']}: " + "; ".join(f"{MNAME[m]} Δ " + " / ".join(f"{r[m]['differenz']:+.5f}" for r in v['richtungen'].values()) for m in MK if v['urteil'][m] == 'Verbesserung') + " (beide Richtungen, Intervall ohne 0).")
    if none:
        L.append("Kein belastbarer Unterschied/schlechter: " + "; ".join(f"T{n} {v['version']}" + (f" (schlechter: {', '.join(bad)})" if bad else "") for n, v, imp, bad in none) + ".")
    if 1 in parts:
        v = next(x for x in parts[1]["varianten"] if x["version"] == "v3-elo-k-mov")
        L.append("Teil 1 K/MOV: gewählt " + ", ".join(f"{d}: {x['gewaehlt']} (eff. K {x['effektives_k']}, Rand: {'ja' if x['am_rand'] else 'nein'})" for d, x in v["parameter"].items()) + f" gegen Produktiv cur-K20 (eff. K {parts[1]['effektives_k']['cur-K20']}); der MOV-Multiplikator (ln) ist schon vorhanden, die 538-Form war nie besser. Saisonübergang (keep 0,9) und total_keep: kein belastbarer Unterschied. Wirkt nur auf Sieger/Spread/Teamtotal (Total hängt nicht an K). Vorsicht: Sigma 13,2 wurde mit K = 20 bestimmt.")
    if 4 in parts:
        vv = {x["version"]: x for x in parts[4]["varianten"]}
        L.append("Teil 4 Form: gewähltes N = " + ", ".join(f"{d}: {x['N']}" for d, x in vv["v3-form-n"]["parameter"].items()) + " = Rand des Rasters (Optimum eventuell darüber; N = 30: " + "/".join(vv["v3-form-n30"]["urteil"][m] for m in ("win", "spread")) + " bei Sieger/Spread; N = 40 nur Sieger). Das Modell hat schon einen Form-Term; der Gewinn ist klein (Brier -0,0004 bis -0,0013).")
    if 5 in parts:
        vv5 = {x["version"]: x for x in parts[5]["varianten"]}
        t = vv5["v3-student-t"]["raender"]["spread"]
        L.append(f"Teil 5 Ränder (Linien bei ±1..2 Sigma, Spread): A <15 %: Modell {t['A']['unter_15']['modell']}/Treffer {t['A']['unter_15']['treffer']}, >85 %: {t['A']['ueber_85']['modell']}/{t['A']['ueber_85']['treffer']} (A leicht zu sicher an den Rändern, ca. 0,7 PP); Student-t df ca. 15 und dynamische Sigma ändern Brier/Log-Loss nur in der 5. Stelle (kein belastbarer Unterschied). Statisch geschätzte Sigma Spread ca. 13,9 statt 13,2 (Total 18,8, Teamtotal 11,7).")
    if 2 in parts:
        k = parts[2]["koeffizienten_alle_spiele"]
        L.append("Teil 2 Effekte auf den Spread in Punkten (alle Spiele, Koeffizient ± SE; positiv = Heim besser als Modell): " + ", ".join(f"{n} {k[n]['spread_pkt'][0]:+.2f}±{k[n]['spread_pkt'][1]:.2f}" for n in ("b2b_heim", "b2b_gast", "3in4_heim", "3in4_gast", "reise_gast_1000km", "hoehe_DEN_UTA_heim")) + ".")
    if 3 in parts:
        e = parts[3]["effekt_alle_spiele"]
        L.append(f"Teil 3 Star-Ausfälle (Obergrenze, nachträglich bekannt; {e['spiele']} Spiele 2024-26): Spread je fehlendem Heim-Top-Spieler Rang 1/2/3: " + "/".join(f"{x[0]:+.1f}±{x[1]:.1f}" for x in e["spread_pkt_je_Rolle"]) + "; Total je Ausfall (beide Seiten): " + "/".join(f"{x[0]:+.1f}±{x[1]:.1f}" for x in e["total_pkt_je_Rolle"]) + ".")
    if 5 in parts:
        vd = parts[5]["verteilung"]
        L.append("Teil 5 Residuen (alle Spiele): Schiefe/Überschusskurtosis Spread " + f"{vd['spread']['alle']['schiefe']}/{vd['spread']['alle']['ueberschuss_kurtosis']}, Total {vd['total']['alle']['schiefe']}/{vd['total']['alle']['ueberschuss_kurtosis']}, Teamtotal {vd['tt']['alle']['schiefe']}/{vd['tt']['alle']['ueberschuss_kurtosis']} (Normal = 0/0).")
    if 4 in parts:
        sh = next((v for v in parts[4]["varianten"] if "schatten" in v["version"]), None)
        if sh:
            L.append("Teil 4 Schattenvariante (Form-Formel allein, Ersatzformel; keine Kandidatin): " + " ; ".join(var_line(sh)) + ".")
    p6 = parts.get(6)
    if p6:
        L.append("Teil 6 Treffer bei Modell > Betano um >= 3/5/8 PP (Zeilen: Trefferquote; Betano-Chance im Mittel): " + "; ".join(f"{m} " + "/".join(f"{x[f'modell_ueber_betano_ab_{t}pp']['zeilen']}: {x[f'modell_ueber_betano_ab_{t}pp']['trefferquote']}" for t in (3, 5, 8)) for m, x in p6["maerkte"].items() if x.get("zeilen")) + " (Spiele ab 22.10.2026, `--market-vs-model` wiederholbar).")
        mm = p6["maerkte"]
        L.append(f"Teil 6 Modell gegen Markt (ZU WENIG DATEN FÜR SCHLÜSSE, {p6['spiele_verwendet']} Spiele): " + "; ".join(f"{m}: n={x['zeilen']}, Brier Modell {x.get('brier_modell')} / Betano {x.get('brier_betano')}" for m, x in mm.items() if x.get("zeilen")) + ".")
    L.append(f"Einschränkungen: Konstanten/Sigmas/ELO-Parameter wurden teils auf denselben Saisons abgestimmt (nicht vollständig unabhängig); Parameter kommen aus der jeweils anderen Gruppe (auch aus der Zukunft); Ausfälle Teil 3 nachträglich bekannt; Linien = Raster um den Modell-Mittelwert (keine historischen Quoten). Laufzeit {runtime:.0f} s.")
    return L


def render(parts, runtime):
    L = summary(parts, runtime)
    L += ["", "=" * 130, "Team-Test Runde 2. Details: Kopf von analysis/backtest_team_round2.py", "=" * 130, ""]
    for n in sorted(parts):
        p = parts[n]
        if n == 6:
            L += ["TEIL 6: MODELL GEGEN MARKT (--market-vs-model)", "  " + p["warnung"], f"  Spiele verwendet {p['spiele_verwendet']}, ohne Version/Eintrag {p['spiele_ohne_version_oder_eintrag']}"]
            for m, x in p["maerkte"].items():
                L.append(f"  {m}: " + json.dumps(x, ensure_ascii=False))
            L.append("")
            continue
        L += [f"TEIL {n} (Laufzeit {p.get('laufzeit_s')} s; {p['spiele_auswertung']} Auswertungsspiele, G1 {p['spiele_je_gruppe']['G1']}, G2 {p['spiele_je_gruppe']['G2']}; Brier A {p['brier_A']})"]
        if p.get("hinweis"):
            L.append("  " + p["hinweis"])
        if p.get("hinweis_k"):
            L.append("  " + p["hinweis_k"]); L.append("  effektives K: " + json.dumps(p["effektives_k"]))
        if p.get("abdeckung"):
            L.append("  Abdeckung: " + json.dumps(p["abdeckung"]))
        if p.get("koeffizienten_alle_spiele"):
            L.append("  Koeffizienten (Punkte ± SE, alle Spiele): " + "; ".join(f"{k}: Spread {x['spread_pkt'][0]:+.2f}±{x['spread_pkt'][1]:.2f}, Total {x['total_pkt'][0]:+.2f}±{x['total_pkt'][1]:.2f}" for k, x in p["koeffizienten_alle_spiele"].items()))
        if p.get("effekt_alle_spiele"):
            L.append("  Effekt alle Spiele: " + json.dumps(p["effekt_alle_spiele"]))
        if n == 5:
            for k, x in p["verteilung"].items():
                L.append(f"  Residuen {k}: " + json.dumps(x["alle"], ensure_ascii=False))
            for k, x in p["streuung_nach"].items():
                L.append(f"  Streuung Residuen {k}: " + json.dumps(x, ensure_ascii=False))
        for v in p["varianten"]:
            L += ["", f"  VARIANTE {v['version']}: {v['name']}" + (f"  [{v['hinweis']}]" if v.get("hinweis") else "")]
            for d, r in v["richtungen"].items():
                L.append(f"    {d} (Testspiele {r['n_spiele']}): " + " | ".join(f"{MNAME[m]} A {r[m]['brier_A']:.4f} V {r[m]['brier_V']:.4f} Δ {f5(r[m]['differenz'])} [{f5(r[m]['ci95'][0])}; {f5(r[m]['ci95'][1])}] ΔLL {f5(r[m]['logloss_differenz'])}" for m in MK))
            L.append("    Urteil: " + "; ".join(f"{MNAME[m]}: {v['urteil'][m]}" for m in MK))
            for d, par in v["parameter"].items():
                L.append(f"    Parameter {d}: " + json.dumps(par, ensure_ascii=False)[:700])
            for m, c in v["kalibrierung"].items():
                if c and c["A"] and c["V"]:
                    L.append(f"    Kalibrierung {m} (gepoolte Testzeilen, Hauptraster): A mittl. Abw. {c['A']['mittlere_abweichung_pp']} PP / max Stufe {c['A']['max_stufe_ab100_pp']} PP ({'gut' if c['A']['gut'] else 'nicht gut'}); V {c['V']['mittlere_abweichung_pp']} / {c['V']['max_stufe_ab100_pp']} ({'gut' if c['V']['gut'] else 'nicht gut'})")
            for m, c in v.get("raender", {}).items():
                a_, v_ = c["A"], c["V"]
                fm = lambda x: f"<15 %: {x['unter_15']['modell']}/{x['unter_15']['treffer']} (n {x['unter_15']['n']}); >85 %: {x['ueber_85']['modell']}/{x['ueber_85']['treffer']} (n {x['ueber_85']['n']})"
                L.append(f"    Ränder {m} (Linien bei ±1..2 Sigma; Modell/Treffer): A {fm(a_)} Brier {a_['brier_raender']} LL {a_['logloss_raender']} | V {fm(v_)} Brier {v_['brier_raender']} LL {v_['logloss_raender']}")
        L.append("")
    return "\n".join(L) + "\n"


def mode_report(stage, t0=None):
    t0 = t0 or time.time()
    parts = {}
    for n in (1, 2, 3, 4, 5, 6):
        f = stage / f"part{n}.json"
        if f.exists():
            parts[n] = json.loads(f.read_text())
    runtime = time.time() - t0 + sum(p.get("laufzeit_s", 0) for p in parts.values() if isinstance(p, dict)) * 0
    rep = {"version": 1, "hinweis": "Team-Test Runde 2: nur Messung, keine Empfehlung.", "teile": {str(n): p for n, p in parts.items()}, "laufzeit_sekunden_bericht": round(runtime)}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / OUT_JSON).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (RESULTS / OUT_TXT).write_text(render(parts, runtime), encoding="utf-8")
    print("\n".join(summary(parts, runtime)))
    print(f"\nErgebnisse: {RESULTS / OUT_JSON}\n            {RESULTS / OUT_TXT}")
    return 0


def selftest():
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    ctx = Ctx()
    A = Score(ctx, ctx.mu_s, ctx.mu_t)
    r1 = json.loads((RESULTS / "backtest_team_multiseason.json").read_text(encoding="utf-8"))
    check("Auswertungsspiele = Regular Season 2017-2025", ctx.n == sum(1 for g in ctx.games if g["season"] >= 2017 and not g.get("postseason")), ctx.n)
    check("A reproduziert Replay (Spread-Mittel = diff/50)", np.allclose(ctx.mu_s, ctx.rowsA["diff"][ctx.E] / 50))
    V = Score(ctx, ctx.mu_s, ctx.mu_t)
    check("Variante = A -> Differenz 0", all(abs((V.brier[m] - A.brier[m]).sum()) < 1e-12 for m in MK))
    d = compare(V, A, ctx.grp == 1)
    check("Bewertungsregel: identische Variante = kein belastbarer Unterschied", verdict({"a": d, "b": d})["spread"] == "kein belastbarer Unterschied")
    fake = {"a": {m: {"differenz": -0.01, "ci95": [-0.02, -0.001]} for m in MK}, "b": {m: {"differenz": -0.01, "ci95": [-0.02, -0.001]} for m in MK}}
    check("Regel: beide Richtungen negativ mit Intervall ohne 0 = Verbesserung", verdict(fake)["win"] == "Verbesserung")
    fake["b"]["win"] = {"differenz": 0.01, "ci95": [0.001, 0.02]}
    check("Regel: Vorzeichen verschieden = kein belastbarer Unterschied", verdict(fake)["win"] == "kein belastbarer Unterschied")
    ps = lambda m: float(((ctx.rowsA["margin"][ctx.E] > 0) == (ctx.mu_s > 0)).mean())
    check("Referenz-Brier Sieg plausibel (0,15..0,25)", 0.15 < A.brier["win"].mean() < 0.25, A.brier["win"].mean())
    F = schedule_features(ctx)
    check("Ruhe-Merkmale: b2b-Anteil plausibel (10..25 %)", 0.10 < F[:, 0].mean() < 0.25, F[:, 0].mean())
    check("Hoehe: Anteil Heimspiele DEN/UTA ca. 2/30", 0.05 < F[:, 10].mean() < 0.09, F[:, 10].mean())
    fm, ft = form_features(ctx)
    check("Form-Merkmal nutzt nur Vergangenheit (erstes Auswertungsspiel hat Wert)", np.isfinite(fm[10]).all())
    snaps = market_vs_model(ROOT / "data" / "tracking", Path("/tmp/nbaedge_team2_copy_selftest"))
    check("Teil 6 liefert Kopie und Zeilen", snaps["spiele_verwendet"] > 0, snaps["spiele_verwendet"])
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv
    stage = Path(a[a.index("--stage-dir") + 1]) if "--stage-dir" in a else Path("/tmp/nbaedge_team2")
    if "--selftest" in a:
        sys.exit(selftest())
    if "--market-vs-model" in a:
        mode_market(stage); sys.exit(0)
    if "--part" in a:
        mode_part(int(a[a.index("--part") + 1]), stage); sys.exit(0)
    if "--report" in a:
        sys.exit(mode_report(stage))
    if "--all" in a:
        sys.exit(mode_all(stage))
    print(__doc__)
