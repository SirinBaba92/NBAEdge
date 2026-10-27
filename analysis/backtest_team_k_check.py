"""
Team-Modell, Nachtest zu K (NUR MESSEN, keine Empfehlung, kein Eingriff in das Produktivmodell). Baut auf analysis/backtest_team_round2.py, bt_common.py, replica_tunable.py, backtest_team_markets.py auf.
Schreibt nur analysis/results/backtest_team_k_check.json und .txt; Zwischenergebnisse ausserhalb des Projekts (--stage-dir, Standard /tmp/nbaedge_kcheck). Kein Netz, keine Zugriffe auf Recorder-/Tracking-Daten.

Stand im Produktivcode (models/elo.py, config/settings.py): K = 20, MOV-Multiplikator 2,2 x ln(Marge + 1) (effektives K im Mittel ca. 102), Heimvorteil 100, KEIN Saisonuebergang (Ratings werden unveraendert
in die naechste Saison genommen = keep 1,0), Spread = ELO-Differenz / 50, Sigma Spread 13,2 (auch fuer die Siegchance, lp.win_prob_home).
Verfahren: Replay mit replica_tunable.run (kausal). Bewertet werden Sieger (Siegchance = Phi(round(Spread,1) / Sigma), begrenzt 3-97 %) und Spread (Heim deckt, Linien-Raster -5..+5 um den Modell-Mittelwert
der REFERENZ A, fuer alle Varianten dieselben Linien), Brier je Spiel. Referenz A = aktuelles Modell (K 20, keep 1,0, Heimvorteil 100, Sigma 13,2). A' = A mit nur aus dem Training neu gewaehltem Sigma
(trennt den Sigma-Effekt vom K-Effekt). V = gewaehlte Variante (K, keep, Sigma, im Teil 2 auch Heimvorteil).
Raster: K = 6, 8, 10, 12, 14, 16, 20, 24 (effektives K ca. 31, 41, 51, 61, 72, 82, 102, 123), keep (Anteil des Rating-Abstands zu 1500, der beim Saisonwechsel bleibt) 1,0 / 0,9 / 0,75 / 0,6,
Heimvorteil 80 / 100 / 120 (nur Teil 2/3), Sigma 11,5 bis 15,5 in 0,1er Schritten. Gewaehlt wird nach dem Brier der Spread-Linien auf den Trainingssaisons (je (K, keep[, Heimvorteil]) mit dem besten Sigma).
Teil 1 rollierend: Testsaison T = 2019-20 bis 2025-26, Training = Saisons 2016-17 bis T-1 (Regular Season). Regel: Verbesserung nur, wenn die mittlere Differenz ueber die Testsaisons negativ ist, das
Bootstrap-Intervall (nach Spielen, alle Testspiele gepoolt) die 0 nicht einschliesst und mindestens 5 von 7 Einzelsaisons negativ sind (je Markt Sieger und Spread); sonst "kein belastbarer Unterschied".
Teil 2 strenger Holdout: Wahl nur aus 2016-17 bis 2024-25 (inkl. Heimvorteil-Raster), Test 2025-26 (plus laufende Saison 2026-27 aus data/cache/player_games_2026-27.json, Teamergebnis = Summe der
Spielerpunkte, nur zur Information, wenige Spiele). Teil 3 Gitter K x keep und K x Heimvorteil (beschreibend, Saisons 2017-2025). Teil 4 frueh/Kaltstart und Kaderkontinuitaet (nur 2024-25/2025-26 ableitbar).
Teil 5 Wirkung in der App (Spread-Mischung 25 %: Differenz x 0,75, Markt = A angenommen). Teil 6 Kalibrierung.
EINSCHRAENKUNGEN: Sigmas, Heimvorteil, ELO-Parameter, Blowout-Kurve und league_ppm stammen teils aus Abstimmungen auf denselben Saisons (nicht vollstaendig unabhaengig); keine historischen Linien (Linien = Raster
um den Modell-Mittelwert); Teamergebnis 2026-27 aus Spielerpunkten; Zeilen eines Spiels korreliert (Bootstrap nach Spielen).
Aufruf (von aussen mit nice -n 15):  venv/bin/python analysis/backtest_team_k_check.py --all     --report    --selftest
"""
import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.special import ndtr

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_team_markets as btm  # noqa: E402
from backtest_team_markets import KS, PRODUCTION, rt, lp, ll, predicted_side_bins, over_side_bins, slope_fit  # noqa: E402
from sigma_check import thresholds  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR, MIN_WIN_PROB, MAX_WIN_PROB  # noqa: E402

ROOT = HERE.parent
RESULTS = HERE / "results"
OUT_JSON, OUT_TXT = "backtest_team_k_check.json", "backtest_team_k_check.txt"
KS_BASE = (6, 8, 10, 12, 14, 16, 20, 24)
KEEPS = (1.0, 0.9, 0.75, 0.6)
HCAS = (80.0, 100.0, 120.0)
SIGMAS = np.round(np.arange(11.5, 15.55, 0.1), 1)
TEST_SEASONS = tuple(range(2019, 2026))
FIRST_TRAIN = 2016
B_BOOT = 1000
S0 = lp.SPREAD_SIGMA


def pr(x, d=5):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


def ml(a):
    return {k: float(v) for k, v in a.items()}


# ----------------------------------------------------------------------------------------------- Daten
def current_season_games(base_games):
    """Spiele der laufenden Saison 2026-27 aus data/cache/player_games_2026-27.json (Teamergebnis = Summe der Spielerpunkte)."""
    p = ROOT / "data" / "cache" / "player_games_2026-27.json"
    if not p.exists():
        return []
    rows = json.loads(p.read_text())["rows"]
    full = {}
    for g in base_games[::-1]:
        for k in ("home_team", "visitor_team"):
            full.setdefault(g[k]["abbreviation"], g[k]["full_name"])
    by = defaultdict(list)
    for r in rows:
        by[r["game_id"]].append(r)
    out = []
    for gid, rs in by.items():
        h = [r for r in rs if r["home"]]
        a = [r for r in rs if not r["home"]]
        if not h or not a or h[0]["team"] not in full or a[0]["team"] not in full:
            continue
        out.append({"id": 9_000_000_000 + int(gid), "date": rs[0]["date"], "season": 2026, "status": "Final", "postseason": False, "postponed": False,
                    "home_team": {"full_name": full[h[0]["team"]], "abbreviation": h[0]["team"]}, "visitor_team": {"full_name": full[a[0]["team"]], "abbreviation": a[0]["team"]},
                    "home_team_score": sum(r["points"] for r in h), "visitor_team_score": sum(r["points"] for r in a), "period": 4})
    return out


class Data:
    def __init__(self):
        base = btm.load_games(2015, 2025)
        cur = current_season_games(base)
        self.games = sorted(base + cur, key=lambda g: (g["date"][:10], g["id"]))
        self.rowsA, _, _, _ = rt.run(self.games, **PRODUCTION)
        r = self.rowsA
        self.E = np.where((r["post"] == 0) & (r["season"] >= FIRST_TRAIN))[0]
        self.n = len(self.E)
        self.season = r["season"][self.E].astype(int)
        self.margin = r["margin"][self.E]
        self.gp = np.minimum(r["gp_h"][self.E], r["gp_a"][self.E])
        self.ywin = (self.margin > 0).astype(float)
        self.mu_A = r["diff"][self.E] / ELO_TO_SPREAD_FACTOR
        self.L = thresholds(self.mu_A, KS)
        self.Y = (self.margin[:, None] > self.L).astype(float)
        self.cache = {}
        self.seasons_all = sorted(set(self.season.tolist()))
        self.n_cur = int((self.season == 2026).sum())

    def mu(self, K, keep=1.0, hca=100.0):
        key = (K, keep, hca)
        if key not in self.cache:
            rows, _, _, _ = rt.run(self.games, K=float(K), hca=float(hca), mov="cur", total_alpha=0.1, keep=float(keep))
            self.cache[key] = rows["diff"][self.E] / ELO_TO_SPREAD_FACTOR
        return self.cache[key]

    def eff_k(self, K):
        m = np.abs(self.margin[self.season < 2026])
        return float(np.mean(K * 2.2 * np.log(m + 1)))

    # Bewertung
    def p_lines(self, mu, sigma):
        return 1 - ndtr((self.L - mu[:, None]) / sigma)

    def p_win(self, mu, sigma):
        return np.clip(ndtr(np.round(mu, 1) / sigma), MIN_WIN_PROB, MAX_WIN_PROB)

    def brier_spread(self, mu, sigma):
        return ((self.p_lines(mu, sigma) - self.Y) ** 2).mean(axis=1)

    def brier_win(self, mu, sigma):
        return (self.p_win(mu, sigma) - self.ywin) ** 2

    def ll_spread(self, mu, sigma):
        return ll(self.p_lines(mu, sigma), self.Y).mean(axis=1)

    def ll_win(self, mu, sigma):
        return ll(self.p_win(mu, sigma), self.ywin)


# ----------------------------------------------------------------------------------------------- Auswahl
def season_sums(D, cands):
    """S[cand][i_sigma] = Array Summe Brier(Spread) je Saison; N = Spiele je Saison."""
    sidx = np.searchsorted(np.array(D.seasons_all), D.season)
    N = np.bincount(sidx, minlength=len(D.seasons_all)).astype(float)
    S = {}
    for c in cands:
        mu = D.mu(*c)
        S[c] = np.array([np.bincount(sidx, weights=D.brier_spread(mu, sg), minlength=len(D.seasons_all)) for sg in SIGMAS])
    return S, N


def choose(S, N, D, cands, train_seasons):
    """Bestes (Kandidat, Sigma) nach dem mittleren Brier(Spread) der Trainingssaisons."""
    cols = [i for i, s in enumerate(D.seasons_all) if s in train_seasons]
    best, bv = None, 1e9
    table = {}
    for c in cands:
        tot = S[c][:, cols].sum(axis=1) / N[cols].sum()
        j = int(np.argmin(tot))
        table[c] = (float(SIGMAS[j]), float(tot[j]))
        if tot[j] < bv:
            best, bv = (c, float(SIGMAS[j])), float(tot[j])
    return best, table


def boot(d, B=B_BOOT, seed=0):
    n = len(d)
    if n < 10:
        return float(d.mean()) if n else None, None, None
    idx = np.random.default_rng(seed).integers(0, n, (B, n))
    m = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def diff_stat(a, b, mask, seed=1):
    """a, b: dict markt -> Brier je Spiel. Rueckgabe je Markt: n, Brier a, b, Differenz b minus a, Intervall."""
    out = {"n": int(mask.sum())}
    for m in ("win", "spread"):
        e = boot((b[m] - a[m])[mask], seed=seed)
        out[m] = {"brier_a": pr(a[m][mask].mean()), "brier_b": pr(b[m][mask].mean()), "diff": pr(e[0], 6), "ci95": [pr(e[1], 6), pr(e[2], 6)]}
    return out


def scores(D, mu, sigma):
    return {"win": D.brier_win(mu, sigma), "spread": D.brier_spread(mu, sigma)}


SIGW = np.round(np.arange(9.0, 15.55, 0.1), 1)


def win_sigma(D, mu, train):
    """Eigenes Sigma fuer die Siegchance (nur Sieger-Brier der Trainingssaisons)."""
    m = np.isin(D.season, list(train))
    best = min(SIGW, key=lambda sg: float(((np.clip(ndtr(np.round(mu[m], 1) / sg), MIN_WIN_PROB, MAX_WIN_PROB) - D.ywin[m]) ** 2).mean()))
    return float(best)


def dwin(a, b, mask, seed=1):
    e = boot((b - a)[mask], seed=seed)
    return {"n": int(mask.sum()), "brier_a": pr(a[mask].mean()), "brier_b": pr(b[mask].mean()), "diff": pr(e[0], 6), "ci95": [pr(e[1], 6), pr(e[2], 6)]}


def edge_flags(c, sigma):
    K, keep, hca = c
    return {"K_am_rand": K in (KS_BASE[0], KS_BASE[-1]), "keep_am_rand": keep in (KEEPS[0], KEEPS[-1]), "hca_am_rand": hca in (HCAS[0], HCAS[-1]), "sigma_am_rand": sigma in (float(SIGMAS[0]), float(SIGMAS[-1]))}


# ----------------------------------------------------------------------------------------------- Teil 1
def part1(D, S, N):
    t0 = time.time()
    cands = [(K, kp, 100.0) for K in KS_BASE for kp in KEEPS]
    A = scores(D, D.mu_A, S0)
    rows, wrows = {}, {}
    allmask = np.zeros(D.n, bool)
    per = {}
    for T in TEST_SEASONS:
        train = set(range(FIRST_TRAIN, T))
        (c, sg), tab = choose(S, N, D, cands, train)
        (c0, sg0), _ = choose(S, N, D, [(20, 1.0, 100.0)], train)
        V = scores(D, D.mu(*c), sg)
        Ap = scores(D, D.mu_A, sg0)
        test = D.season == T
        per[T] = {"gewaehlt": {"K": c[0], "effektives_k": pr(D.eff_k(c[0]), 1), "keep": c[1], "sigma": sg, "ränder": edge_flags(c, sg)}, "sigma_A_prime": sg0, "trainingssaisons": f"{FIRST_TRAIN}..{T - 1}",
                  "V_gegen_A": diff_stat(A, V, test, seed=T), "A_prime_gegen_A": diff_stat(A, Ap, test, seed=T + 50), "V_gegen_A_prime": diff_stat(Ap, V, test, seed=T + 100)}
        sw, sw0 = win_sigma(D, D.mu(*c), train), win_sigma(D, D.mu_A, train)
        W2, Wp = D.brier_win(D.mu(*c), sw), D.brier_win(D.mu_A, sw0)
        per[T]["eigenes_sieger_sigma"] = {"V2_sigma": sw, "A_prime_w_sigma": sw0, "V2_gegen_A": dwin(A["win"], W2, test, T + 200), "A_prime_w_gegen_A": dwin(A["win"], Wp, test, T + 250), "V2_gegen_A_prime_w": dwin(Wp, W2, test, T + 300)}
        wrows[T] = (W2, Wp)
        allmask |= test
        rows[T] = (V, Ap)
    # gepoolt
    def pooled_stat(which):
        vs = {m: np.zeros(D.n) for m in ("win", "spread")}
        for T in TEST_SEASONS:
            t = D.season == T
            for m in vs:
                vs[m][t] = rows[T][0 if which == "V" else 1][m][t]
        return vs
    PV, PAp = pooled_stat("V"), pooled_stat("A'")
    res = {"teil": 1, "je_saison": {str(T): per[T] for T in TEST_SEASONS}, "gepoolt": {"V_gegen_A": diff_stat(A, PV, allmask, seed=7), "A_prime_gegen_A": diff_stat(A, PAp, allmask, seed=8), "V_gegen_A_prime": diff_stat(PAp, PV, allmask, seed=9)}}
    def rule(key):
        out = {}
        for m in ("win", "spread"):
            ds = [per[T][key][m]["diff"] for T in TEST_SEASONS]
            g = res["gepoolt"][key][m]
            neg = sum(1 for x in ds if x < 0)
            mean = float(np.mean(ds))
            ok = mean < 0 and g["ci95"][1] < 0 and neg >= 5
            bad = mean > 0 and g["ci95"][0] > 0 and (len(ds) - neg) >= 5
            out[m] = {"mittel_der_saisons": pr(mean, 6), "gepoolt": g["diff"], "ci95": g["ci95"], "saisons_negativ": neg, "von": len(ds), "urteil": "Verbesserung" if ok else ("schlechter" if bad else "kein belastbarer Unterschied")}
        return out
    res["regel"] = {"V_gegen_A": rule("V_gegen_A"), "A_prime_gegen_A": rule("A_prime_gegen_A"), "V_gegen_A_prime": rule("V_gegen_A_prime")}
    PW2, PWp = np.zeros(D.n), np.zeros(D.n)
    for T in TEST_SEASONS:
        t = D.season == T
        PW2[t], PWp[t] = wrows[T][0][t], wrows[T][1][t]
    res["eigenes_sieger_sigma"] = {"hinweis": "Siegchance mit eigenem Sigma (nur Sieger-Brier der Trainingssaisons gewaehlt); Spread unveraendert wie oben."}
    for key, (a_, b_) in (("V2_gegen_A", (A["win"], PW2)), ("A_prime_w_gegen_A", (A["win"], PWp)), ("V2_gegen_A_prime_w", (PWp, PW2))):
        g = dwin(a_, b_, allmask, seed=60 + len(key))
        ds = [per[T]["eigenes_sieger_sigma"][key]["diff"] for T in TEST_SEASONS]
        neg = sum(1 for x in ds if x < 0)
        mean = float(np.mean(ds))
        ok = mean < 0 and g["ci95"][1] < 0 and neg >= 5
        bad = mean > 0 and g["ci95"][0] > 0 and (len(ds) - neg) >= 5
        res["eigenes_sieger_sigma"][key] = {"gepoolt": g, "saisons_negativ": neg, "von": len(ds), "urteil": "Verbesserung" if ok else ("schlechter" if bad else "kein belastbarer Unterschied")}
    res["laufzeit_s"] = round(time.time() - t0)
    return res, rows


# ----------------------------------------------------------------------------------------------- Teil 2
def part2(D, S2, N2):
    t0 = time.time()
    cands = [(K, kp, h) for K in KS_BASE for kp in KEEPS for h in HCAS]
    train = set(range(FIRST_TRAIN, 2025))
    (c, sg), tab = choose(S2, N2, D, cands, train)
    (c1, sg1), _ = choose(S2, N2, D, [(K, kp, 100.0) for K in KS_BASE for kp in KEEPS], train)
    (c0, sg0), _ = choose(S2, N2, D, [(20, 1.0, 100.0)], train)
    A = scores(D, D.mu_A, S0)
    muV, muV1 = D.mu(*c), D.mu(*c1)
    V, V1, Ap = scores(D, muV, sg), scores(D, muV1, sg1), scores(D, D.mu_A, sg0)
    out = {"teil": 2, "trainingssaisons": f"{FIRST_TRAIN}..2024", "gewaehlt_volles_raster": {"K": c[0], "effektives_k": pr(D.eff_k(c[0]), 1), "keep": c[1], "heimvorteil": c[2], "sigma": sg, "ränder": edge_flags(c, sg)},
           "gewaehlt_ohne_heimvorteil": {"K": c1[0], "effektives_k": pr(D.eff_k(c1[0]), 1), "keep": c1[1], "heimvorteil": 100.0, "sigma": sg1}, "sigma_A_prime": sg0,
           "top5_kandidaten_training": [{"K": k[0], "keep": k[1], "hca": k[2], "sigma": v[0], "brier_spread_training": pr(v[1], 6)} for k, v in sorted(tab.items(), key=lambda kv: kv[1][1])[:5]], "test": {}}
    for label, mask in (("2025-26", D.season == 2025), ("2026-27 (laufend, nur Information)", D.season == 2026)):
        if mask.sum() < 5:
            continue
        out["test"][label] = {"spiele": int(mask.sum()), "V_gegen_A": diff_stat(A, V, mask, seed=21), "V_ohne_hca_gegen_A": diff_stat(A, V1, mask, seed=22), "A_prime_gegen_A": diff_stat(A, Ap, mask, seed=23),
                              "logloss_diff_V_gegen_A": {m: pr((ll_fun(D, muV, sg)[m] - ll_fun(D, D.mu_A, S0)[m])[mask].mean(), 6) for m in ("win", "spread")}}
    sw = win_sigma(D, muV, train)
    out["eigenes_sieger_sigma"] = {"sigma": sw}
    for label, mask in (("2025-26", D.season == 2025), ("2026-27 (laufend, nur Information)", D.season == 2026)):
        if mask.sum() >= 5:
            out["eigenes_sieger_sigma"][label] = dwin(A["win"], D.brier_win(muV, sw), mask, seed=27)
    out["V"], out["A_prime"] = V, Ap
    out["laufzeit_s"] = round(time.time() - t0)
    return out, (c, sg)


def ll_fun(D, mu, sigma):
    return {"win": D.ll_win(mu, sigma), "spread": D.ll_spread(mu, sigma)}


# ----------------------------------------------------------------------------------------------- Teil 3
def part3(D, S2, N2):
    t0 = time.time()
    seasons_ev = [s for s in D.seasons_all if 2017 <= s <= 2025]
    colsets = {"2017-2025": seasons_ev, "2017-2021": [s for s in seasons_ev if s <= 2021], "2022-2025": [s for s in seasons_ev if s >= 2022]}
    def cell(c, cols, fixed=False):
        ci = [i for i, s in enumerate(D.seasons_all) if s in cols]
        if fixed:
            j = int(np.where(SIGMAS == S0)[0][0])
            return float(S2[c][j, ci].sum() / N2[ci].sum()), S0
        tot = S2[c][:, ci].sum(axis=1) / N2[ci].sum()
        j = int(np.argmin(tot))
        return float(tot[j]), float(SIGMAS[j])
    out = {"teil": 3, "hinweis": "beschreibend (kein Test): Brier(Spread) gemittelt ueber die Saisons; je Zelle mit bestem Sigma (in-sample) und mit festem Sigma 13,2."}
    for name, cols in colsets.items():
        grid_k_keep = {f"keep{kp}": {f"K{K}(eff {D.eff_k(K):.0f})": {"brier_bestes_sigma": pr(cell((K, kp, 100.0), cols)[0], 6), "sigma": cell((K, kp, 100.0), cols)[1], "brier_sigma_13_2": pr(cell((K, kp, 100.0), cols, True)[0], 6)} for K in KS_BASE} for kp in KEEPS}
        grid_k_hca = {f"hca{int(h)}": {f"K{K}(eff {D.eff_k(K):.0f})": {"brier_bestes_sigma": pr(cell((K, 1.0, h), cols)[0], 6), "sigma": cell((K, 1.0, h), cols)[1], "brier_sigma_13_2": pr(cell((K, 1.0, h), cols, True)[0], 6)} for K in KS_BASE} for h in HCAS}
        opt_keep = {kp: min(KS_BASE, key=lambda K: cell((K, kp, 100.0), cols)[0]) for kp in KEEPS}
        opt_hca = {int(h): min(KS_BASE, key=lambda K: cell((K, 1.0, h), cols)[0]) for h in HCAS}
        opt_hca_keep9 = {int(h): min(KS_BASE, key=lambda K: cell((K, 0.9, h), cols)[0]) for h in HCAS}
        out[name] = {"K_x_keep": grid_k_keep, "K_x_hca_keep1.0": grid_k_hca, "optimum_K_je_keep": {str(k): v for k, v in opt_keep.items()}, "optimum_K_je_hca_keep1.0": {str(k): v for k, v in opt_hca.items()},
                     "optimum_K_je_hca_keep0.9": {str(k): v for k, v in opt_hca_keep9.items()}}
    # Beleg fuer "warum kleineres K": Steigung Marge ~ Spread-Prognose und Streuung der Prognosen (Saisons 2017-2025)
    m = (D.season >= 2017) & (D.season <= 2025)
    ev = {}
    for K in KS_BASE:
        mu = D.mu(K, 1.0, 100.0)[m]
        x = D.margin[m]
        b = float(np.cov(mu, x)[0, 1] / mu.var())
        ev[f"K{K}(eff {D.eff_k(K):.0f})"] = {"sd_prognose": pr(mu.std(), 3), "steigung_marge_auf_prognose": pr(b, 3), "mae_prognose": pr(float(np.abs(x - mu).mean()), 3)}
    out["beleg_steigung"] = ev
    out["beleg_keep"] = {f"keep{kp}": {f"K{K}": pr(float(np.cov(D.mu(K, kp, 100.0)[m], D.margin[m])[0, 1] / D.mu(K, kp, 100.0)[m].var()), 3) for K in (10, 20)} for kp in KEEPS}
    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Teil 4
def continuity(D):
    """Kaderkontinuitaet je (Saison, Team): Anteil der Minuten der Vorsaison (Team) von Spielern, die in dieser Saison fuer das Team gespielt haben. Nur 2024-25 und 2025-26."""
    files = {"2023-24": "backtest_player_games_2023-24.json", "2024-25": "backtest_player_games_2024-25.json", "2025-26": "player_games_2025-26.json"}
    rows = {}
    for s, f in files.items():
        p = ROOT / "data" / "cache" / f
        if p.exists():
            rows[s] = json.loads(p.read_text())["rows"]
    out = {}
    for s, prev in (("2024-25", "2023-24"), ("2025-26", "2024-25")):
        if s not in rows or prev not in rows:
            continue
        mp = defaultdict(lambda: defaultdict(float))
        for r in rows[prev]:
            mp[r["team"]][r["person_id"]] += r["minutes"]
        now = defaultdict(set)
        for r in rows[s]:
            if r["minutes"] > 0:
                now[r["team"]].add(r["person_id"])
        for t, d in mp.items():
            tot = sum(d.values())
            out[(int(s[:4]), t)] = sum(m for p_, m in d.items() if p_ in now[t]) / tot if tot else None
    return out


def part4(D, rows):
    t0 = time.time()
    A = scores(D, D.mu_A, S0)
    PV = {m: np.zeros(D.n) for m in ("win", "spread")}
    PAp = {m: np.zeros(D.n) for m in ("win", "spread")}
    test = np.zeros(D.n, bool)
    for T in TEST_SEASONS:
        t = D.season == T
        test |= t
        for m in PV:
            PV[m][t] = rows[T][0][m][t]; PAp[m][t] = rows[T][1][m][t]
    out = {"teil": 4, "nach_teamspielen": {}}
    for name, mk in (("erste 15 Spiele (gp < 15)", D.gp < 15), ("Spiele 16 bis 40 (15 <= gp < 40)", (D.gp >= 15) & (D.gp < 40)), ("danach (gp >= 40)", D.gp >= 40)):
        m = test & mk
        out["nach_teamspielen"][name] = {"V_gegen_A": diff_stat(A, PV, m, seed=31), "A_prime_gegen_A": diff_stat(A, PAp, m, seed=32), "V_gegen_A_prime": diff_stat(PAp, PV, m, seed=33)}
    # Kaderkontinuitaet
    cont = continuity(D)
    ab = {}
    for gi, ei in enumerate(D.E):
        g = D.games[ei]
        ab[gi] = (g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"])
    c = np.full(D.n, np.nan)
    for j in range(D.n):
        s = int(D.season[j])
        if (s, ab[j][0]) in cont and (s, ab[j][1]) in cont and cont[(s, ab[j][0])] is not None and cont[(s, ab[j][1])] is not None:
            c[j] = (cont[(s, ab[j][0])] + cont[(s, ab[j][1])]) / 2
    early = test & (D.gp < 15) & ~np.isnan(c)
    if early.sum() >= 100:
        q = np.percentile(c[early], [33, 67])
        out["kaderkontinuitaet"] = {"hinweis": "Kontinuitaet = Anteil der Vorsaison-Minuten des Teams von Spielern, die in dieser Saison fuer das Team gespielt haben (Mittel Heim/Gast), nur 2024-25 und 2025-26, nur erste 15 Teamspiele; nachtraeglich bekannt (Obergrenze).",
                                    "schwellen_terzile": [pr(q[0], 3), pr(q[1], 3)], "spiele": int(early.sum())}
        for name, mk in (("niedrig (grosser Kaderwechsel)", c <= q[0]), ("mittel", (c > q[0]) & (c <= q[1])), ("hoch", c > q[1])):
            m = early & mk
            out["kaderkontinuitaet"][name] = {"V_gegen_A": diff_stat(A, PV, m, seed=41), "V_gegen_A_prime": diff_stat(PAp, PV, m, seed=42)}
    else:
        out["kaderkontinuitaet"] = {"hinweis": "nicht ableitbar (zu wenige Spiele mit Daten)"}
    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Teil 5
def part5(D, choice):
    t0 = time.time()
    (c, sg) = choice
    muV, muA = D.mu(*c), D.mu_A
    out = {"teil": 5, "variante": {"K": c[0], "effektives_k": pr(D.eff_k(c[0]), 1), "keep": c[1], "heimvorteil": c[2], "sigma": sg},
           "hinweis": "Mischung: App rechnet Spread = 0,75 x Modell + 0,25 x Markt (Spread-Anteil 25 %). Rechnerisch bleibt von der Modell-Differenz 75 % im Spread; Markt hier = Spread von A (Annahme, keine historischen Linien). "
                      "Siegchance aus dem gemischten Spread mit dem Sigma der jeweiligen Variante (A: 13,2).", "saisons": {}}
    for label, s in (("2025-26", 2025), ("2026-27 (laufend)", 2026)):
        m = D.season == s
        if m.sum() < 5:
            continue
        d = muV[m] - muA[m]
        pA, pV = D.p_win(muA[m], S0), D.p_win(muV[m], sg)
        bA, bV = D.p_win(0.75 * muA[m] + 0.25 * muA[m], S0), D.p_win(0.75 * muV[m] + 0.25 * muA[m], sg)
        out["saisons"][label] = {"spiele": int(m.sum()), "spread_mittel_abs_diff_pkt": pr(np.abs(d).mean(), 3), "spiele_ueber_2_pkt": int((np.abs(d) > 2).sum()), "spiele_ueber_1_pkt": int((np.abs(d) > 1).sum()),
                                 "spread_mittel_diff_vorzeichen": pr(d.mean(), 3), "max_abs_diff_pkt": pr(np.abs(d).max(), 2), "siegchance_mittel_abs_diff_pp": pr(100 * np.abs(pV - pA).mean(), 2), "siegchance_max_abs_diff_pp": pr(100 * np.abs(pV - pA).max(), 2),
                                 "nach_mischung": {"spread_mittel_abs_diff_pkt": pr(0.75 * np.abs(d).mean(), 3), "spiele_ueber_2_pkt": int((0.75 * np.abs(d) > 2).sum()), "siegchance_mittel_abs_diff_pp": pr(100 * np.abs(bV - bA).mean(), 2)},
                                 "mittel_abs_spread_A": pr(np.abs(muA[m]).mean(), 2), "mittel_abs_spread_V": pr(np.abs(muV[m]).mean(), 2)}
    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Teil 6
def cal_block(p, y):
    p, y = np.asarray(p, float).ravel(), np.asarray(y, float).ravel()
    side = predicted_side_bins(p, y)
    mad = sum(b["n"] * abs(b["abweichung_pp"]) for b in side) / max(1, sum(b["n"] for b in side))
    mx = max((abs(b["abweichung_pp"]) for b in side if b["n"] >= 100), default=0.0)
    lo, hi = p < 0.15, p > 0.85
    return {"n": int(len(p)), "steigung": pr(slope_fit(p, y), 3), "mittel_modell": pr(p.mean(), 4), "trefferquote": pr(y.mean(), 4), "mittlere_abweichung_stufen_pp": pr(mad, 2), "max_stufe_ab100_pp": pr(mx, 2),
            "gut": bool(mad < 3 and mx <= 6), "stufen_10pp": over_side_bins(p, y),
            "raender": {"unter_15": {"n": int(lo.sum()), "modell": pr(p[lo].mean(), 4) if lo.any() else None, "treffer": pr(y[lo].mean(), 4) if lo.any() else None},
                        "ueber_85": {"n": int(hi.sum()), "modell": pr(p[hi].mean(), 4) if hi.any() else None, "treffer": pr(y[hi].mean(), 4) if hi.any() else None}}}


def part6(D, S, N):
    t0 = time.time()
    cands = [(K, kp, 100.0) for K in KS_BASE for kp in KEEPS]
    out = {"teil": 6, "hinweis": "V = je Saison die rollierend gewaehlte Variante aus Teil 1 (Wahl nur aus frueheren Saisons); Spread-Stufen ueber das Linien-Raster der Referenz A; Sieger-Stufen = Heimsiegchance.", "saisons": {}}
    PA = {"win": [], "spread": []}; PV = {"win": [], "spread": []}; YW, YS = [], []; V2 = []
    for T in TEST_SEASONS:
        (c, sg), _ = choose(S, N, D, cands, set(range(FIRST_TRAIN, T)))
        t = D.season == T
        muV = D.mu(*c)
        a = {"win": D.p_win(D.mu_A[t], S0), "spread": D.p_lines(D.mu_A, S0)[t]}
        v = {"win": D.p_win(muV[t], sg), "spread": D.p_lines(muV, sg)[t]}
        y = {"win": D.ywin[t], "spread": D.Y[t]}
        sw = win_sigma(D, muV, set(range(FIRST_TRAIN, T)))
        v2 = D.p_win(muV[t], sw)
        out["saisons"][str(T)] = {"K": c[0], "keep": c[1], "sigma": sg, "sieger_sigma_eigen": sw, "win_V2": cal_block(v2, y["win"]), **{m: {"A": cal_block(a[m], y[m]), "V": cal_block(v[m], y[m])} for m in ("win", "spread")}}
        V2.append(v2)
        for m in ("win", "spread"):
            PA[m].append(a[m].ravel()); PV[m].append(v[m].ravel())
        YW.append(y["win"]); YS.append(y["spread"].ravel())
    y_all = {"win": np.concatenate(YW), "spread": np.concatenate(YS)}
    out["gemeinsam"] = {m: {"A": cal_block(np.concatenate(PA[m]), y_all[m]), "V": cal_block(np.concatenate(PV[m]), y_all[m])} for m in ("win", "spread")}
    out["gemeinsam"]["win_V2"] = cal_block(np.concatenate(V2), y_all["win"])
    out["laufzeit_s"] = round(time.time() - t0)
    return out


# ----------------------------------------------------------------------------------------------- Ablauf
def run_all(stage):
    t0 = time.time()
    stage.mkdir(parents=True, exist_ok=True)
    D = Data()
    print(f"Daten: {D.n} Regular-Season-Spiele {FIRST_TRAIN}-{D.seasons_all[-1]} (davon laufende Saison {D.n_cur})", flush=True)
    cands2 = [(K, kp, h) for K in KS_BASE for kp in KEEPS for h in HCAS]
    S2, N2 = season_sums(D, cands2)
    print(f"Replays und Raster fertig nach {time.time() - t0:.0f} s", flush=True)
    res = {}
    res[1], rows = part1(D, S2, N2)
    res[2], choice = part2(D, S2, N2)
    res[2] = {k: v for k, v in res[2].items() if k not in ("V", "A_prime")}
    res[3] = part3(D, S2, N2)
    res[4] = part4(D, rows)
    res[5] = part5(D, choice)
    res[6] = part6(D, S2, N2)
    for n, r in res.items():
        (stage / f"teil{n}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
        print(f"Teil {n} gespeichert ({r.get('laufzeit_s')} s)", flush=True)
    (stage / "meta.json").write_text(json.dumps({"spiele": D.n, "spiele_je_saison": {str(s): int((D.season == s).sum()) for s in D.seasons_all}, "laufzeit_s": round(time.time() - t0)}), encoding="utf-8")
    return report(stage)


def f6(x):
    return "-" if x is None else f"{x:+.5f}"


def summary(R, meta):
    p1, p2, p4, p5 = R[1], R[2], R[4], R[5]
    reg = p1["regel"]
    L = ["ZUSAMMENFASSUNG K-Nachtest (nur Messung; KEINE Änderung am Produktivmodell, KEINE Empfehlung für die App). Referenz A = aktuelles Modell (K 20 = eff. ca. 102, kein Saisonübergang, Sigma 13,2).",
         f"Teil 1 rollierend (Testsaisons 2019-20..2025-26, Wahl nur aus früheren Saisons; {sum(p1['je_saison'][str(T)]['V_gegen_A']['n'] for T in TEST_SEASONS)} Testspiele): V gegen A, gepoolt Sieger {f6(p1['gepoolt']['V_gegen_A']['win']['diff'])} [{f6(p1['gepoolt']['V_gegen_A']['win']['ci95'][0])}; {f6(p1['gepoolt']['V_gegen_A']['win']['ci95'][1])}], Spread {f6(p1['gepoolt']['V_gegen_A']['spread']['diff'])} [{f6(p1['gepoolt']['V_gegen_A']['spread']['ci95'][0])}; {f6(p1['gepoolt']['V_gegen_A']['spread']['ci95'][1])}].",
         f"Regel (Mittel negativ, Intervall ohne 0, >= 5 von 7 Saisons): Sieger {reg['V_gegen_A']['win']['urteil']} ({reg['V_gegen_A']['win']['saisons_negativ']} von 7 negativ); Spread {reg['V_gegen_A']['spread']['urteil']} ({reg['V_gegen_A']['spread']['saisons_negativ']} von 7 negativ).",
         "Gewählt je Testsaison (K/eff. K, keep, Sigma): " + "; ".join(f"{T}: K{p1['je_saison'][str(T)]['gewaehlt']['K']}/{p1['je_saison'][str(T)]['gewaehlt']['effektives_k']:.0f}, {p1['je_saison'][str(T)]['gewaehlt']['keep']}, {p1['je_saison'][str(T)]['gewaehlt']['sigma']}" for T in TEST_SEASONS) + ".",
         f"Zerlegung: nur neues Sigma (A' gegen A) Sieger {reg['A_prime_gegen_A']['win']['urteil']} / Spread {reg['A_prime_gegen_A']['spread']['urteil']}; K/keep zusätzlich (V gegen A') Sieger {reg['V_gegen_A_prime']['win']['urteil']} ({f6(p1['gepoolt']['V_gegen_A_prime']['win']['diff'])}) / Spread {reg['V_gegen_A_prime']['spread']['urteil']} ({f6(p1['gepoolt']['V_gegen_A_prime']['spread']['diff'])}).",
         f"Mit eigenem Sieger-Sigma (V2): Sieger gegen A {f6(p1['eigenes_sieger_sigma']['V2_gegen_A']['gepoolt']['diff'])} [{f6(p1['eigenes_sieger_sigma']['V2_gegen_A']['gepoolt']['ci95'][0])}; {f6(p1['eigenes_sieger_sigma']['V2_gegen_A']['gepoolt']['ci95'][1])}] => {p1['eigenes_sieger_sigma']['V2_gegen_A']['urteil']} ({p1['eigenes_sieger_sigma']['V2_gegen_A']['saisons_negativ']} von 7); nur neues Sieger-Sigma bei K20: {p1['eigenes_sieger_sigma']['A_prime_w_gegen_A']['urteil']}; Sigma Sieger gewählt {', '.join(str(p1['je_saison'][str(T)]['eigenes_sieger_sigma']['V2_sigma']) for T in TEST_SEASONS)}.",
         "Einzelsaisons V gegen A (Sieger | Spread): " + "; ".join(f"{T} {p1['je_saison'][str(T)]['V_gegen_A']['win']['diff']:+.4f} | {p1['je_saison'][str(T)]['V_gegen_A']['spread']['diff']:+.4f}" for T in TEST_SEASONS) + "."]
    g = p2["gewaehlt_volles_raster"]
    t25 = p2["test"]["2025-26"]
    L.append(f"Teil 2 strenger Holdout (Wahl nur bis 2024-25: K{g['K']}/eff. {g['effektives_k']:.0f}, keep {g['keep']}, Heimvorteil {g['heimvorteil']:.0f}, Sigma {g['sigma']}; Ränder: " + (", ".join(k for k, v in g["ränder"].items() if v) or "keine") + f"): 2025-26 ({t25['spiele']} Spiele) Sieger {f6(t25['V_gegen_A']['win']['diff'])} [{f6(t25['V_gegen_A']['win']['ci95'][0])}; {f6(t25['V_gegen_A']['win']['ci95'][1])}], Spread {f6(t25['V_gegen_A']['spread']['diff'])} [{f6(t25['V_gegen_A']['spread']['ci95'][0])}; {f6(t25['V_gegen_A']['spread']['ci95'][1])}].")
    cur = p2["test"].get("2026-27 (laufend, nur Information)")
    if cur:
        L.append(f"   Laufende Saison 2026-27 ({cur['spiele']} Spiele, nur Information): Sieger {f6(cur['V_gegen_A']['win']['diff'])} [{f6(cur['V_gegen_A']['win']['ci95'][0])}; {f6(cur['V_gegen_A']['win']['ci95'][1])}], Spread {f6(cur['V_gegen_A']['spread']['diff'])} [{f6(cur['V_gegen_A']['spread']['ci95'][0])}; {f6(cur['V_gegen_A']['spread']['ci95'][1])}].")
    p3 = R[3]["2017-2025"]
    L.append("Teil 3 Optimum K je keep (2017-2025, in-sample): " + ", ".join(f"keep {k}: K{v}" for k, v in p3["optimum_K_je_keep"].items()) + "; je Heimvorteil (keep 1,0): " + ", ".join(f"{k}: K{v}" for k, v in p3["optimum_K_je_hca_keep1.0"].items()) + "; Hälften 2017-21 / 2022-25 (keep 1,0): K" + f"{R[3]['2017-2021']['optimum_K_je_keep']['1.0']} / K{R[3]['2022-2025']['optimum_K_je_keep']['1.0']}.")
    sl = R[3]["beleg_steigung"]
    k20, k10 = sl["K20(eff 102)"], sl["K10(eff 51)"]
    L.append(f"   Zum Warum (nur was belegt ist): Steigung echte Marge auf Prognose bei K20 {k20['steigung_marge_auf_prognose']} (SD Prognose {k20['sd_prognose']}) = Prognosen nicht zu weit gestreut; bei K10 {k10['steigung_marge_auf_prognose']} (SD {k10['sd_prognose']}) zu eng. Der Gewinn kommt also NICHT aus 'K20 zu gestreut', sondern aus dem Zusammenspiel von engerer Prognose und kleinerem Sigma (V gegen A' bleibt auch nach Sigma-Neuwahl negativ); eine Ursache (MOV-Multiplikator, Rückfall) ist nicht belegt - keep hilft nie.")
    early = p4["nach_teamspielen"]
    L.append("Teil 4 V gegen A nach Teamspielen (Sieger | Spread): " + "; ".join(f"{k.split(' (')[0]} {v['V_gegen_A']['win']['diff']:+.4f} | {v['V_gegen_A']['spread']['diff']:+.4f} (n {v['V_gegen_A']['n']})" for k, v in early.items()) + ".")
    kc = p4.get("kaderkontinuitaet", {})
    if kc.get("niedrig (grosser Kaderwechsel)"):
        L.append("   Kaderwechsel (nur 2024-26, erste 15 Spiele, Obergrenze): niedrige / mittlere / hohe Kontinuität V gegen A Spread " + " / ".join(f"{kc[k]['V_gegen_A']['spread']['diff']:+.4f}" for k in ("niedrig (grosser Kaderwechsel)", "mittel", "hoch")) + ".")
    s25 = p5["saisons"]["2025-26"]
    L.append(f"Teil 5 App-Wirkung 2025-26 ({s25['spiele']} Spiele): mittlere |Spread-Differenz| {s25['spread_mittel_abs_diff_pkt']} Pkt, {s25['spiele_ueber_2_pkt']} Spiele > 2 Pkt, Siegchance {s25['siegchance_mittel_abs_diff_pp']} PP; nach 25 %-Mischung (75 % bleiben): {s25['nach_mischung']['spread_mittel_abs_diff_pkt']} Pkt, {s25['nach_mischung']['spiele_ueber_2_pkt']} Spiele > 2 Pkt, {s25['nach_mischung']['siegchance_mittel_abs_diff_pp']} PP.")
    s26 = p5["saisons"].get("2026-27 (laufend)")
    if s26:
        L.append(f"   Laufende Saison ({s26['spiele']} Spiele): {s26['spread_mittel_abs_diff_pkt']} Pkt, {s26['spiele_ueber_2_pkt']} Spiele > 2 Pkt, {s26['siegchance_mittel_abs_diff_pp']} PP; nach Mischung {s26['nach_mischung']['spread_mittel_abs_diff_pkt']} Pkt / {s26['nach_mischung']['siegchance_mittel_abs_diff_pp']} PP.")
    c6 = R[6]["gemeinsam"]
    L.append("Teil 6 Kalibrierung gemeinsam (Steigung, mittl. Abweichung PP, Ränder <15 %/>85 % Modell/Treffer): Sieger A " + f"{c6['win']['A']['steigung']}, {c6['win']['A']['mittlere_abweichung_stufen_pp']}, {c6['win']['A']['raender']['unter_15']['modell']}/{c6['win']['A']['raender']['unter_15']['treffer']}, {c6['win']['A']['raender']['ueber_85']['modell']}/{c6['win']['A']['raender']['ueber_85']['treffer']}" + " | V " + f"{c6['win']['V']['steigung']}, {c6['win']['V']['mittlere_abweichung_stufen_pp']}, {c6['win']['V']['raender']['unter_15']['modell']}/{c6['win']['V']['raender']['unter_15']['treffer']}, {c6['win']['V']['raender']['ueber_85']['modell']}/{c6['win']['V']['raender']['ueber_85']['treffer']}"
             + f" | V2 (eigenes Sieger-Sigma) {c6['win_V2']['steigung']}, {c6['win_V2']['mittlere_abweichung_stufen_pp']}, {c6['win_V2']['raender']['unter_15']['modell']}/{c6['win_V2']['raender']['unter_15']['treffer']}, {c6['win_V2']['raender']['ueber_85']['modell']}/{c6['win_V2']['raender']['ueber_85']['treffer']}" + "; Spread A " + f"{c6['spread']['A']['steigung']}, {c6['spread']['A']['mittlere_abweichung_stufen_pp']}" + " | V " + f"{c6['spread']['V']['steigung']}, {c6['spread']['V']['mittlere_abweichung_stufen_pp']}.")
    L.append("Einschränkungen: Sigma/Heimvorteil/ELO-Parameter/Blowout-Kurve/league_ppm teils auf denselben Saisons abgestimmt; keine historischen Linien (Linien = Raster um den Modell-Mittelwert); 2026-27 aus Spielerpunkten; Kaderwechsel nachträglich bekannt und nur 2 Saisons; Zeilen eines Spiels korreliert (Bootstrap nach Spielen). Alles Messung, keine Empfehlung.")
    return L


def render(R, meta):
    L = summary(R, meta)
    L += ["", "=" * 130, f"K-Nachtest, Laufzeit {meta['laufzeit_s']} s; Spiele je Saison (Regular Season): " + json.dumps(meta["spiele_je_saison"]), "=" * 130, ""]
    p1 = R[1]
    L += ["TEIL 1 ROLLIEREND (Brier-Differenz b minus a, negativ = besser; Intervall nach Spielen)"]
    for T in TEST_SEASONS:
        s = p1["je_saison"][str(T)]
        g = s["gewaehlt"]
        L.append(f"  {T}-{(T + 1) % 100:02d} (Training {s['trainingssaisons']}): K{g['K']} (eff. {g['effektives_k']}), keep {g['keep']}, Sigma {g['sigma']} (A': Sigma {s['sigma_A_prime']}); Ränder {[k for k, v in g['ränder'].items() if v]}")
        for key in ("V_gegen_A", "A_prime_gegen_A", "V_gegen_A_prime"):
            d = s[key]
            L.append(f"      {key:<16} n {d['n']}: Sieger {f6(d['win']['diff'])} [{f6(d['win']['ci95'][0])}; {f6(d['win']['ci95'][1])}] (A {d['win']['brier_a']:.4f} -> {d['win']['brier_b']:.4f}) | Spread {f6(d['spread']['diff'])} [{f6(d['spread']['ci95'][0])}; {f6(d['spread']['ci95'][1])}] (A {d['spread']['brier_a']:.4f} -> {d['spread']['brier_b']:.4f})")
    L += ["  gepoolt:"]
    for key in ("V_gegen_A", "A_prime_gegen_A", "V_gegen_A_prime"):
        d = p1["gepoolt"][key]
        r = p1["regel"][key]
        L.append(f"      {key:<16} n {d['n']}: Sieger {f6(d['win']['diff'])} [{f6(d['win']['ci95'][0])}; {f6(d['win']['ci95'][1])}] => {r['win']['urteil']} ({r['win']['saisons_negativ']}/7 Saisons negativ) | Spread {f6(d['spread']['diff'])} [{f6(d['spread']['ci95'][0])}; {f6(d['spread']['ci95'][1])}] => {r['spread']['urteil']} ({r['spread']['saisons_negativ']}/7)")
    L += ["  Eigenes Sieger-Sigma (V2 = K/keep wie V, Sigma nur aus Sieger-Brier): " + json.dumps({k: v for k, v in p1["eigenes_sieger_sigma"].items()}, ensure_ascii=False)]
    p2 = R[2]
    L += ["", "TEIL 2 STRENGER HOLDOUT", "  " + json.dumps({k: v for k, v in p2.items() if k not in ("test", "teil", "laufzeit_s")}, ensure_ascii=False)]
    for lab, t in p2["test"].items():
        L.append(f"  {lab} ({t['spiele']} Spiele): " + " | ".join(f"{k} Sieger {f6(t[k]['win']['diff'])} [{f6(t[k]['win']['ci95'][0])}; {f6(t[k]['win']['ci95'][1])}] Spread {f6(t[k]['spread']['diff'])} [{f6(t[k]['spread']['ci95'][0])}; {f6(t[k]['spread']['ci95'][1])}]" for k in ("V_gegen_A", "V_ohne_hca_gegen_A", "A_prime_gegen_A")) + f" | Log-Loss-Differenz V gegen A {t['logloss_diff_V_gegen_A']}")
    L.append("  Eigenes Sieger-Sigma im Holdout: " + json.dumps(p2["eigenes_sieger_sigma"], ensure_ascii=False))
    p3 = R[3]
    L += ["", "TEIL 3 WECHSELWIRKUNGEN (Brier Spread, bestes Sigma je Zelle / Sigma 13,2; Zahl = Brier)"]
    for name in ("2017-2025", "2017-2021", "2022-2025"):
        L += [f"  Saisons {name}: Optimum K je keep {p3[name]['optimum_K_je_keep']}, je Heimvorteil (keep 1,0) {p3[name]['optimum_K_je_hca_keep1.0']}, je Heimvorteil (keep 0,9) {p3[name]['optimum_K_je_hca_keep0.9']}"]
    for name in ("2017-2025",):
        for kp, row in p3[name]["K_x_keep"].items():
            L.append(f"    {kp:<8} " + " | ".join(f"{k}: {v['brier_bestes_sigma']:.5f} (σ {v['sigma']})" for k, v in row.items()))
        for h, row in p3[name]["K_x_hca_keep1.0"].items():
            L.append(f"    {h:<8} (keep 1,0) " + " | ".join(f"{k}: {v['brier_bestes_sigma']:.5f} (σ {v['sigma']})" for k, v in row.items()))
    L.append("  Beleg (Steigung Marge auf Prognose, SD Prognose, MAE; keep 1,0): " + json.dumps(p3["beleg_steigung"], ensure_ascii=False))
    L.append("  Beleg Steigung bei K10/K20 je keep: " + json.dumps(p3["beleg_keep"]))
    p4 = R[4]
    L += ["", "TEIL 4 FRÜHE SAISON (gepoolt Testsaisons 2019-2025; Brier-Differenz)"]
    for k, v in p4["nach_teamspielen"].items():
        L.append(f"  {k}: " + " | ".join(f"{key} n {v[key]['n']} Sieger {f6(v[key]['win']['diff'])} [{f6(v[key]['win']['ci95'][0])}; {f6(v[key]['win']['ci95'][1])}] Spread {f6(v[key]['spread']['diff'])} [{f6(v[key]['spread']['ci95'][0])}; {f6(v[key]['spread']['ci95'][1])}]" for key in ("V_gegen_A", "A_prime_gegen_A", "V_gegen_A_prime")))
    L.append("  Kaderkontinuität: " + json.dumps(p4["kaderkontinuitaet"], ensure_ascii=False)[:1800])
    L += ["", "TEIL 5 WIRKUNG IN DER APP", "  " + json.dumps(R[5], ensure_ascii=False)]
    p6 = R[6]
    L += ["", "TEIL 6 KALIBRIERUNG (A gegen V; Steigung, mittl. Abweichung PP, max. Stufe PP, gut?)"]
    for lab, blk in list(p6["saisons"].items()) + [("gemeinsam", p6["gemeinsam"])]:
        for m in ("win", "spread"):
            a, v = blk[m]["A"], blk[m]["V"]
            L.append(f"  {lab} {m}: A Steigung {a['steigung']}, {a['mittlere_abweichung_stufen_pp']} PP, max {a['max_stufe_ab100_pp']} ({'gut' if a['gut'] else 'nicht gut'}); V Steigung {v['steigung']}, {v['mittlere_abweichung_stufen_pp']} PP, max {v['max_stufe_ab100_pp']} ({'gut' if v['gut'] else 'nicht gut'})" + (f" [K{blk['K']}, keep {blk['keep']}, σ {blk['sigma']}]" if 'K' in blk and m == 'win' else ""))
    for m in ("win", "spread"):
        for who in ("A", "V"):
            b = p6["gemeinsam"][m][who]
            L.append(f"  gemeinsam {m} {who} Stufen (Modell %/Treffer %/n): " + " | ".join(f"{x['stufe'].split(' ')[0]}: {100 * x['mittel_modell']:.0f}/{100 * x['trefferquote']:.0f}/{x['n']}" for x in b["stufen_10pp"]) + f" | Ränder {b['raender']}")
    return "\n".join(L) + "\n"


def report(stage):
    R = {n: json.loads((stage / f"teil{n}.json").read_text()) for n in range(1, 7)}
    meta = json.loads((stage / "meta.json").read_text())
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / OUT_JSON).write_text(json.dumps({"version": 1, "hinweis": "K-Nachtest: nur Messung, keine Empfehlung.", "meta": meta, "teile": {str(k): v for k, v in R.items()}}, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (RESULTS / OUT_TXT).write_text(render(R, meta), encoding="utf-8")
    print("\n".join(summary(R, meta)))
    print(f"\nErgebnisse: {RESULTS / OUT_JSON}\n            {RESULTS / OUT_TXT}")
    return 0


def selftest():
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    D = Data()
    check("Referenz A = Produktiv (K20, keep 1,0, hca 100) aus dem Cache", np.allclose(D.mu(20, 1.0, 100.0), D.mu_A))
    check("effektives K: K20 ca. 102", abs(D.eff_k(20) - 102.4) < 1.5, D.eff_k(20))
    check("laufende Saison 2026-27 vorhanden (Spiele)", D.n_cur > 10, D.n_cur)
    check("Testsaisons 2019..2025 haben je > 1000 Spiele (2020/21 verkuerzt: > 600)", all((D.season == T).sum() > 600 for T in TEST_SEASONS), {T: int((D.season == T).sum()) for T in TEST_SEASONS})
    b = D.brier_spread(D.mu_A, S0)
    check("A: Spread-Brier plausibel (0,23..0,26)", 0.23 < b.mean() < 0.26, b.mean())
    mu_k = D.mu(10, 1.0, 100.0)
    check("kleineres K: Prognosen weniger gestreut", mu_k.std() < D.mu_A.std())
    E = D.season < 2025
    same = np.allclose(rt.run(D.games[:int(D.E[(D.season == 2024)].max()) + 1], K=20.0, hca=100.0, mov="cur", total_alpha=0.1, keep=1.0)[0]["diff"][D.E[(D.season == 2024)]] / 50, D.mu_A[D.season == 2024])
    check("Replay kausal: Abschneiden nach 2024 aendert Prognosen 2024 nicht", same)
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv
    stage = Path(a[a.index("--stage-dir") + 1]) if "--stage-dir" in a else Path("/tmp/nbaedge_kcheck")
    if "--selftest" in a:
        sys.exit(selftest())
    if "--report" in a:
        sys.exit(report(stage))
    if "--all" in a:
        sys.exit(run_all(stage))
    print(__doc__)
