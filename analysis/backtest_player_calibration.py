"""
Kalibrierung und Streuung der Spieler-Punkte-Chancen (Meilensteine P(Punkte >= k)), roh (A) als Basis, dazu Varianten V1-V4 NUR im Replay. NUR LESEND, Produktivmodell unveraendert.
Schreibt nur analysis/reports/player_calibration.txt (Zwischenstaende im Temp-Ordner).

Aufruf (aus dem Projektordner):
  venv/bin/python analysis/backtest_player_calibration.py run        Replay 2024-25 und 2025-26 + Varianten-Rechnung (Zwischenstaende)
  venv/bin/python analysis/backtest_player_calibration.py report     Auswertung und Bericht
  venv/bin/python analysis/backtest_player_calibration.py run2       weiteres Suchgitter fuer V1 (zwei Lesarten) und V2 (nach run)
  venv/bin/python analysis/backtest_player_calibration.py report3    Verbreiterung nur fuer Nicht-Starter (W1-W4, Bericht player_calibration3.txt)
  venv/bin/python analysis/backtest_player_calibration.py report2    Auswertung der Varianten V1/V2 nach Gruppen (Bericht player_calibration2.txt)
  venv/bin/python analysis/backtest_player_calibration.py --selftest

Aufbau wie analysis/backtest_player_markets.py (setup, prepare_games) und analysis/bt_player_adapter.py (Verlauf nur vor Spieltag D). Je Spielerzeile (Prognose vorhanden UND Minuten > 0) werden die
Bausteine der Verteilung (ppm je Spiel, Gewichte, Minutenquantile) mitgespeichert; daraus rechnet `core_arrays` die Verteilung genau wie engine/player_forecast.forecast_player (wird je Zeile gegen
die Produktivfunktion geprueft, Abweichung > 1e-9 bricht ab). Varianten (Kern h = Breite der Normalglaettung je Punktewert x):
 A  roh:  h = 1 + 0,05 x
 V1 breiterer Kern: h = c (1 + 0,05 x) mit c = 2,0 (Faktor auf den Produktivkern)
 V2 Mittelwert-Unsicherheit: h^2 = (1 + 0,05 x)^2 + (tau_n x)^2, tau_n = c / sqrt(n), n = Spiele des Spielers im Verlauf mit mind. 8 Minuten (c auf einer Haelfte eingestellt)
 V3 V1 und V2 zusammen: h^2 = (2 (1 + 0,05 x))^2 + (tau_n x)^2
 V4 negative Binomialverteilung mit Mittel = erwartete Punkte und Varianz mu + mu^2 / r (r auf einer Haelfte eingestellt)
Meilensteine: alle ganzzahligen k von 5 bis 40 fuer jede Zeile (Zeile = Spieler x Meilenstein-Paar). Bootstrap IMMER nach Spielen (beide Teams eines Spiels zusammen).
"""
import glob
import sys
import time
import warnings
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.special import expit, ndtr, ndtri
from scipy.stats import nbinom

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

SEASONS = ["2024-25", "2025-26"]
KS = np.arange(5, 41)
NK = len(KS)
C_GRID = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
R_GRID = [4, 6, 8, 10, 14, 20, 30, 60]
TMP = Path("/private/tmp/claude-501/-Users-baranalturk-Desktop-NBAEdge/17d61728-2adb-4f84-baf0-b13cbf48640f/scratchpad/pcal")
OUT = HERE / "reports" / "player_calibration.txt"
NB = 400
MIN_ROWS, DEV_MAX_PP = 100, 6.0


# ------------------------------------------------------------------------------------------------ Kern (wie forecast_player)
def core_parts(pf, ph, games, day, home, exp_spread):
    """Bausteine der Verteilung exakt wie engine/player_forecast.forecast_player (ohne Override/Skalierung). games: Zeilen vor day. None, wenn die Produktivfunktion nicht ok waere."""
    games = [g for g in games if g["date"] < day]
    games.sort(key=lambda g: (g["date"], g["game_id"]), reverse=True)
    if not games:
        return None
    season = ph.season_of_date(day)
    weights = pf.game_weights(games, season)
    minutes = [g["minutes"] for g in games]
    mu0, sd0 = pf.weighted_mean_sd(minutes, weights)
    ppm_idx = [i for i, g in enumerate(games) if g["minutes"] >= pf.MIN_PPM_MINUTES]
    if not ppm_idx:
        return None
    team_spread = float(exp_spread) if home in (True, None) else -float(exp_spread)
    mu = min(pf.MAX_MINUTES, mu0 * pf.blowout_factor(mu0, team_spread))
    z = ndtri((np.arange(pf.MINUTE_POINTS) + 0.5) / pf.MINUTE_POINTS)
    m_k = np.clip(mu + sd0 * z, 0.0, pf.MAX_MINUTES)
    w_p = np.array([weights[i] * games[i]["minutes"] for i in ppm_idx]); w_p = w_p / w_p.sum()
    ppm = np.array([games[i]["points"] / games[i]["minutes"] for i in ppm_idx])
    n_cur = sum(1 for g in games if g["season"] == season)
    return {"ppm": ppm, "w_p": w_p, "m_k": m_k, "mu": mu, "mu0": mu0, "n": len(ppm_idx), "n_hist": len(games), "n_cur": n_cur}


def xw(ppm, w_p, m_k):
    x = (ppm[:, None] * m_k[None, :]).ravel()
    w = (w_p[:, None] * np.full(len(m_k), 1.0 / len(m_k))[None, :]).ravel()
    return x, w


def probs(x, w, ns, h):
    p = (w[None, :] * ndtr(-(ns[:, None] - 0.5 - x[None, :]) / h[None, :])).sum(axis=1)
    return np.minimum.accumulate(np.clip(p, 0.0, 1.0))


def variant_probs(x, w, n, grid_c, grid_r):
    """Alle Varianten fuer eine Zeile: Rueckgabe Array [Variante, NK] (Reihenfolge: A, V1, V2 je c, V3 je c, V4 je r) und Modellvarianz der Punkte (A)."""
    ns = np.arange(1, 41)
    h0 = 1.0 + 0.05 * x
    out = [probs(x, w, ns, h0)]
    out.append(probs(x, w, ns, 2.0 * h0))
    for c in grid_c:
        out.append(probs(x, w, ns, np.sqrt(h0 ** 2 + (c / np.sqrt(n) * x) ** 2)))
    for c in grid_c:
        out.append(probs(x, w, ns, np.sqrt((2.0 * h0) ** 2 + (c / np.sqrt(n) * x) ** 2)))
    mu = float((w * x).sum())
    for r in grid_r:
        pn = r / (r + max(mu, 0.05))
        out.append(np.minimum.accumulate(nbinom.sf(ns - 1, r, pn)))
    return np.array(out)[:, 4:40]


def chunk_worker(args):
    sl, ppm_cat, wp_cat, off, mk, nn = args
    res = np.zeros((2 + 2 * len(C_GRID) + len(R_GRID), len(sl), NK), np.float32)
    for j, i in enumerate(sl):
        a, b = off[i], off[i + 1]
        x, w = xw(ppm_cat[a:b], wp_cat[a:b], mk[i])
        res[:, j, :] = variant_probs(x, w, nn[i], C_GRID, R_GRID)
    return res


C1_GRID = [1.0 + 0.25 * i for i in range(13)]                      # V1: c = 1,0 .. 4,0
C2_GRID = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]             # V2: bis zum Fuenffachen des alten Maximums (1,0)
V2NAMES = [f"V1f c={c:g}" for c in C1_GRID] + [f"V1c c={c:g}" for c in C1_GRID] + [f"V2 c={c:g}" for c in C2_GRID]


def variant2_probs(x, w, n):
    """Zweites Gitter: V1f (h = c (1+0,05x)), V1c (fester Kern h = c), V2 (Mittelwert-Unsicherheit, weites Gitter). Rueckgabe [Variante, NK]."""
    ns = np.arange(1, 41)
    h0 = 1.0 + 0.05 * x
    out = [probs(x, w, ns, c * h0) for c in C1_GRID]
    out += [probs(x, w, ns, np.full_like(x, c)) for c in C1_GRID]
    out += [probs(x, w, ns, np.sqrt(h0 ** 2 + (c / np.sqrt(n) * x) ** 2)) for c in C2_GRID]
    return np.array(out)[:, 4:40]


def chunk_worker2(args):
    sl, ppm_cat, wp_cat, off, mk, nn = args
    res = np.zeros((len(V2NAMES), len(sl), NK), np.float32)
    for j, i in enumerate(sl):
        a, b = off[i], off[i + 1]
        x, w = xw(ppm_cat[a:b], wp_cat[a:b], mk[i])
        res[:, j, :] = variant2_probs(x, w, nn[i])
    return res


def run2():
    t0 = time.time()
    for s in SEASONS:
        if (TMP / f"var2_{s}.npy").exists():
            continue
        d = np.load(TMP / f"rows_{s}.npz")
        idx = np.array_split(np.arange(len(d["gi"])), 64)
        jobs = [(sl, d["ppm_cat"], d["wp_cat"], d["off"], d["mk"], d["n"]) for sl in idx]
        with Pool(8) as pool:
            parts = pool.map(chunk_worker2, jobs)
        np.save(TMP / f"var2_{s}.npy", np.concatenate(parts, axis=1))
        print(f"Gitter 2 {s} fertig ({time.time() - t0:.0f} s)", flush=True)


VNAMES = ["A"] + ["V1"] + [f"V2 c={c}" for c in C_GRID] + [f"V3 c={c}" for c in C_GRID] + [f"V4 r={r}" for r in R_GRID]


# ------------------------------------------------------------------------------------------------ Stufe 1: Replay
def run_season(season):
    import backtest_player_markets as bpm
    from bt_player_adapter import Adapter
    from data import player_history as ph
    from engine import player_forecast as pf
    t0 = time.time()
    all_rows, flat, store, games, replay = bpm.setup()
    adapter = Adapter(store)
    sg, ctl = bpm.prepare_games(all_rows[season], season, games, replay)
    gp = defaultdict(int)
    M = defaultdict(list)
    ppm_l, wp_l, off = [], [], [0]
    maxdiff = 0.0
    for gi, g in enumerate(sg):
        day = g["date"]; sp = g["ctx"]["exp_spread"]
        gp_by = {g["home"]: gp[g["home"]], g["away"]: gp[g["away"]]}
        gp[g["home"]] += 1; gp[g["away"]] += 1
        for r in g["rows"]:
            if r["minutes"] <= 0:
                continue
            is_home = r["team"] == g["home"]
            fc = adapter.forecast_player(r["person_id"], day, home=is_home, exp_spread=sp, exp_total=g["ctx"].get("exp_total"), name=r["name"])      # Produktivpfad (mit Assertion: nur Vergangenheit)
            if not fc["ok"]:
                continue
            cp = core_parts(pf, ph, store.history(r["person_id"], day), day, is_home, sp)
            x, w = xw(cp["ppm"], cp["w_p"], cp["m_k"])
            pA = probs(x, w, np.arange(1, 41), 1.0 + 0.05 * x)[4:40]
            d = float(np.max(np.abs(pA - np.array([fc["p_ge"][k] for k in KS]))))
            maxdiff = max(maxdiff, d, abs(float((w * x).sum()) - fc["expected_points"]))
            assert maxdiff < 1e-9, f"Kern weicht von forecast_player ab: {maxdiff}"
            ppm_l.append(cp["ppm"]); wp_l.append(cp["w_p"]); off.append(off[-1] + len(cp["ppm"]))
            M["mk"].append(cp["m_k"]); M["n"].append(cp["n"]); M["n_hist"].append(cp["n_hist"]); M["n_cur"].append(cp["n_cur"])
            M["gi"].append(gi); M["date"].append(int(day.replace("-", ""))); M["pid"].append(r["person_id"]); M["home"].append(int(is_home))
            M["min"].append(r["minutes"]); M["pts"].append(r["points"]); M["emin"].append(fc["minutes"]["mean"]); M["mu0"].append(cp["mu0"]); M["epts"].append(fc["expected_points"])
            M["ot"].append(g["ot"]); M["margin"].append(abs(g["margin"])); M["ntg"].append(gp_by[r["team"]])
            nm = bpm.naive_mu(store, r["person_id"], day)
            M["naive"].append(np.nan if nm is None else nm)
    arr = {k: np.asarray(v) for k, v in M.items()}
    arr["ppm_cat"] = np.concatenate(ppm_l); arr["wp_cat"] = np.concatenate(wp_l); arr["off"] = np.array(off)
    arr["n_games"] = np.array([len(sg)]); arr["maxdiff"] = np.array([maxdiff])
    np.savez_compressed(TMP / f"rows_{season}.npz", **arr)
    return season, len(M["gi"]), len(sg), maxdiff, time.time() - t0


def run():
    TMP.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    todo = [s for s in SEASONS if not (TMP / f"rows_{s}.npz").exists()]
    if todo:
        with Pool(len(todo), maxtasksperchild=1) as pool:
            for res in pool.imap_unordered(run_season, todo):
                print(f"Replay fertig {res[0]}: {res[1]} Zeilen, {res[2]} Spiele, max. Abweichung Kern gegen Produktivfunktion {res[3]:.1e}, {res[4]:.0f} s", flush=True)
    for s in SEASONS:
        if (TMP / f"var_{s}.npy").exists():
            continue
        d = np.load(TMP / f"rows_{s}.npz")
        n = len(d["gi"])
        idx = np.array_split(np.arange(n), 64)
        jobs = [(sl, d["ppm_cat"], d["wp_cat"], d["off"], d["mk"], d["n"]) for sl in idx]
        with Pool(8) as pool:
            parts = pool.map(chunk_worker, jobs)
        np.save(TMP / f"var_{s}.npy", np.concatenate(parts, axis=1))
        print(f"Varianten {s} fertig ({time.time() - t0:.0f} s)", flush=True)


# ------------------------------------------------------------------------------------------------ Statistik-Helfer
def selftest():
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    from bt_player_adapter import ORIG_FORECAST, _fake_rows, HistoryStore
    from data import player_history as ph
    from engine import player_forecast as pf
    rows = _fake_rows()
    st = HistoryStore(rows)
    day = "2024-11-20"
    worst = 0.0
    for pid in (1000, 1003, 2001, 3005):
        g = st.history(pid, day)
        fc = ORIG_FORECAST(pid, day, home=True, exp_spread=3.0, exp_total=224.0, games=list(g), name="x")
        cp = core_parts(pf, ph, g, day, True, 3.0)
        x, w = xw(cp["ppm"], cp["w_p"], cp["m_k"])
        pA = probs(x, w, np.arange(1, 41), 1.0 + 0.05 * x)
        worst = max(worst, float(np.max(np.abs(pA - np.array([fc["p_ge"][k] for k in range(1, 41)])))))
    check("Kern = forecast_player (p_ge fuer N = 1..40)", worst < 1e-9, f"{worst:.1e}")
    cp = core_parts(pf, ph, st.history(1000, day), day, True, 3.0)
    x, w = xw(cp["ppm"], cp["w_p"], cp["m_k"])
    V = variant_probs(x, w, cp["n"], C_GRID, R_GRID)
    check("Form [Varianten, 36], monoton fallend, in [0,1]", V.shape == (2 + 2 * len(C_GRID) + len(R_GRID), NK) and np.all(np.diff(V, axis=1) <= 1e-9) and V.min() >= 0 and V.max() <= 1)
    check("V1 (breiter) hat bei hohem k mehr Masse als A, bei tiefem weniger", V[1, -1] >= V[0, -1] - 1e-12 and V[1, 0] <= V[0, 0] + 1e-12)
    V2g = variant2_probs(x, w, cp["n"])
    check("Gitter 2: Form, monoton, V1f c=1,0 = A", V2g.shape == (len(V2NAMES), NK) and np.all(np.diff(V2g, axis=1) <= 1e-9) and np.allclose(V2g[0], V[0], atol=1e-12))
    check("V1c (fester Kern c = 2) hat bei hohem k weniger Masse als V1f (c = 2) (schmaler bei hohem x)", V2g[13 + 4, -1] <= V2g[4, -1] + 1e-12)
    pn = 10 / (10 + 20.0)
    ks = np.arange(0, 400)
    pm = nbinom.pmf(ks, 10, pn)
    check("NB: Mittel = mu, Varianz = mu + mu^2/r", abs((pm * ks).sum() - 20.0) < 1e-6 and abs((pm * ks ** 2).sum() - 400 - 60.0) < 1e-3)
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "run2" in sys.argv:
        run2()
        sys.exit(0)
    if "report3" in sys.argv:
        import backtest_player_calibration3_report  # noqa: F401
        sys.exit(0)
    if "report2" in sys.argv:
        import backtest_player_calibration2_report  # noqa: F401
        sys.exit(0)
    if "run" in sys.argv:
        run()
        sys.exit(0)
    if "report" in sys.argv:
        import backtest_player_calibration_report  # noqa: F401
        sys.exit(0)
    print(__doc__)
