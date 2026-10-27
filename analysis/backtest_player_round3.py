"""
Spieler-Backtest, Runde 3: Verteilungsform und Mittelwert-Unsicherheit messen (NUR MESSEN, keine Empfehlung). Baut auf analysis/bt_player_adapter.py, backtest_player_markets.py und backtest_player_round2.py auf.
Produktivcode, App, Tests und bestehende Dateien bleiben unveraendert; Eingriffe nur zur LAUFZEIT im Prozess des Backtests (der Quelltext von forecast_player wird mit EINER Ergaenzung ausgefuehrt, die zusaetzliche
Verteilungen aus denselben Zwischenwerten berechnet; die rohe Verteilung A bleibt unveraendert und wird kontrolliert). Kein Netz. Liest/schreibt nichts in ~/NBAEdge_live_history, data/tracking, forecast_snapshots, day_bets.
Schreibt nur analysis/results/backtest_player_round3.json und .txt; Zwischenergebnisse liegen ausserhalb des Projekts (--stage-dir, Standard /tmp/nbaedge_round3).

Varianten (alle ausgehend von A = roh; Meilenstein-Zeilen: ganzzahlige k mit 5 % <= P(Punkte >= k) <= 95 % der jeweiligen Variante, Kader und Spieler wie Runde 1/2):
  A   roh                                                        v2-roh
  F   Kern-Breite: h = c x (1 + 0,05 x), c in {1,5 (Referenz Runde 2), 1,75, 2,0, 2,5, 3,0}                 v3-breite-c<c>
  H   Unsicherheit des Punkte-pro-Minute-Mittelwerts (siehe unten), Staerke k in {0,5, 1,0, 1,5, 2,0}         v3-ppm-unsicher-k<k>
  N   negative Binomialverteilung mit Mittelwert und Varianz x v der rohen Verteilung, v in {1,0, 1,2, 1,5}      v3-negbin-v<v>
  F+H, N+H  beste Parameter der Trainingssaison kombiniert (N+H: Mittelwert/Varianz der H-Verteilung)

Stelle von H (engine/player_forecast.py, forecast_player, Zeilen 166-191): game_weights() (Zeile 74) liefert die Spielgewichte (Halbwertszeit 8 Spiele, Schrumpfung zur Vorsaison); daraus entstehen
w_p (Zeile 185: nach Minuten gewichtet, normiert) und die wirksame Spielzahl n_eff = 1 / Summe(w_p^2). Die am wenigsten eingreifende Stelle ist der Glaettungskern (Zeile 189/191): Jeder Punktewert x = ppm_j x m_q
(Spiel j, Minutenquantil q) bekommt zusaetzlich die Varianz (k x SE_ppm x m_q)^2, d. h. Kernbreite h' = sqrt(h^2 + (k x SE_ppm x m_q)^2); SE_ppm = Standardabweichung der ppm / Wurzel(n_eff). Die Standardabweichung der ppm
wird (wie die Minutenstreuung in weighted_mean_sd) zu einem Vorwert geschrumpft: sd^2 = (n_eff x Var + 4 x 0,2^2) / (n_eff + 4) (Vorwert 0,2 Punkte/Minute und Gewicht 4 sind MEINE Annahmen, nicht aus dem Produktivcode;
ohne Schrumpfung waere die Unsicherheit bei einem einzigen Spiel 0). Erwartungswerte bleiben gleich (Faltung mit mittelwertfreier Normalverteilung), Minuten bleiben gleich.
N: pmf aus der rohen p_ge-Kurve (P(=n) = p_ge(n) - p_ge(n+1), P(0) = 1 - p_ge(1), Rest bei 60 gebuendelt); Rueckfall bei Varianz x v <= Mittelwert: die Eingabeverteilung bleibt UNVERAENDERT (Anteil wird berichtet).
Parameterwahl: nur auf der Trainingssaison (jeder 4. Spieltag), nach Brier-Differenz zu A auf gemeinsamen Zeilen (nur wenn < 0, sonst "keine"); Test auf der anderen Saison, BEIDE Richtungen; danach laufen die gewaehlten
Varianten auf allen Tagen der Testsaison. "beide" = beide Testsaisons mit jeweils ihren (anderswo gewaehlten) Parametern.
Bewertungsregel: Verbesserung nur, wenn Brier-Differenz zu A (Bootstrap nach Spielen) in der Testsaison negativ UND Intervall ohne 0 UND in beiden Richtungen dasselbe Vorzeichen; sonst "kein belastbarer Unterschied".
Aufruf (Hintergrund, nice): venv/bin/python analysis/backtest_player_round3.py --all     --pilot (Zeitmessung)   --report   --selftest
"""
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import nbinom

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_player_markets as bpm  # noqa: E402
import backtest_player_round2 as r2  # noqa: E402
import backtest_team_markets as btm  # noqa: E402
import bt_player_adapter as bpa  # noqa: E402
from bt_player_adapter import Adapter, p_array  # noqa: E402
from engine import player_forecast as pf  # noqa: E402

RESULTS = HERE / "results"
OUT_JSON, OUT_TXT = "backtest_player_round3.json", "backtest_player_round3.txt"
SEASONS = ("2024-25", "2025-26")
C_GRID, K_GRID, V_GRID = (1.5, 1.75, 2.0, 2.5, 3.0), (0.5, 1.0, 1.5, 2.0), (1.0, 1.2, 1.5)
P_LO, P_HI = bpm.P_LO, bpm.P_HI
SD_PRIOR, SD_PRIOR_W = 0.2, 4.0


# ----------------------------------------------------------------------------------------------- Laufzeit-Eingriff
def build_impl():
    import inspect
    src = inspect.getsource(bpa.ORIG_FORECAST)
    a1 = "    expected_points = float((w * x).sum())\n"
    a2 = '"games_used": dict(sorted(used.items())),'
    assert src.count(a1) == 1 and src.count(a2) == 1, "Quelltext von forecast_player hat sich geaendert"
    add = (a1 +
           "    n_eff_p = 1.0 / float((w_p ** 2).sum())\n"
           "    P_VAR = {}\n"
           "    if VSPEC:\n"
           "        ppm_bar = float((w_p * ppm).sum())\n"
           "        var_p = float((w_p * (ppm - ppm_bar) ** 2).sum())\n"
           "        sd_p = math.sqrt((n_eff_p * var_p + SD_PRIOR_W * SD_PRIOR ** 2) / (n_eff_p + SD_PRIOR_W))\n"
           "        se_ppm = sd_p / math.sqrt(n_eff_p)\n"
           "        m_rep = np.tile(m_k, len(ppm_idx))\n"
           "        for (c_, k_) in VSPEC:\n"
           "            hh = c_ * h\n"
           "            if k_:\n"
           "                hh = np.sqrt(hh ** 2 + (k_ * se_ppm * m_rep) ** 2)\n"
           "            pv = (w[None, :] * (1.0 - ndtr((ns[:, None] - 0.5 - x[None, :]) / hh[None, :]))).sum(axis=1)\n"
           "            P_VAR[(c_, k_)] = np.minimum.accumulate(np.clip(pv, 0.0, 1.0))\n")
    src = src.replace(a1, add).replace(a2, '"p_var": P_VAR, "n_games": len(games), "n_eff": n_eff_p, ' + a2)
    g = dict(vars(pf))
    g.update(VSPEC=[], SD_PRIOR=SD_PRIOR, SD_PRIOR_W=SD_PRIOR_W)
    exec(compile(src, "<forecast_player_runde3>", "exec"), g)
    return g["forecast_player"], g


IMPL, IMPL_G = build_impl()
bpa.ORIG_FORECAST = IMPL                                           # nur im Prozess; ohne VSPEC identisch zum Original (kontrolliert)


def set_vspec(pairs):
    IMPL_G["VSPEC"] = list(pairs)


def nb_p(p, v):
    """Negative Binomialverteilung mit Mittelwert und Varianz x v der Verteilung p (P(>= n), n = 1..60). Rueckgabe (p_neu, rueckfall)."""
    ps = np.r_[1.0, p]
    pmf = np.r_[ps[:-1] - ps[1:], p[-1]]
    n = np.arange(len(pmf))
    m = float((n * pmf).sum())
    var = float((n * n * pmf).sum()) - m * m
    s = v * var
    if not (s > m * (1 + 1e-9) and m > 0):
        return p, True
    r = m * m / (s - m)
    q = r / (r + m)
    out = np.minimum.accumulate(np.clip(nbinom.sf(np.arange(0, len(p)), r, q), 0.0, 1.0))
    return out, False


def variant_arrays(fc, spec):
    """spec: {name: (kind, params)} -> {name: p-Array}; Rueckfaelle werden in 'fallback' gezaehlt."""
    out, fb = {}, {}
    base = p_array(fc)
    for name, (kind, par) in spec.items():
        if kind == "A":
            out[name] = base
        elif kind == "PV":                                          # (c, k)
            out[name] = fc["p_var"][par]
        elif kind == "N":                                           # (v, (c,k) der Eingabeverteilung)
            v, key = par
            src = base if key == (1.0, 0) else fc["p_var"][key]
            out[name], fb[name] = nb_p(src, v)
    return out, fb


# ----------------------------------------------------------------------------------------------- Lauf
class Acc3:
    def __init__(self, spec):
        self.spec = spec
        self.names = list(spec)
        self.pg = defaultdict(list)
        self.rows = {v: defaultdict(list) for v in self.names}
        self.n_pg = 0
        self.fallback = defaultdict(int)
        self.played = self.skipped = 0

    def add(self, g, side, r, fc):
        i = self.n_pg
        self.n_pg += 1
        d = {"game": g["gi"], "ot": g["ot"], "team_gp": g["gp"][side], "min": r["minutes"], "pts": r["points"], "pid": r["person_id"], "emin": fc["minutes"]["mean"], "epts": fc["expected_points"],
             "n_games": fc["n_games"], "n_eff": fc["n_eff"]}
        for k, val in d.items():
            self.pg[k].append(val)
        arrs, fb = variant_arrays(fc, self.spec)
        for v, n_ in fb.items():
            self.fallback[v] += int(n_)
        for v in self.names:
            p = arrs[v]
            m = (p >= P_LO) & (p <= P_HI)
            ks = np.nonzero(m)[0] + 1
            if len(ks):
                R = self.rows[v]
                R["pg"].append(np.full(len(ks), i, np.int32)); R["k"].append(ks.astype(np.int16)); R["p"].append(p[m]); R["y"].append((r["points"] >= ks).astype(np.int8))

    def arrays(self):
        pg = {k: np.asarray(v) for k, v in self.pg.items()}
        rows = {v: {k: (np.concatenate(self.rows[v][k]) if self.rows[v][k] else np.array([])) for k in ("pg", "k", "p", "y")} for v in self.names}
        return pg, rows

    def save(self, stage, tag):
        stage.mkdir(parents=True, exist_ok=True)
        pg, rows = self.arrays()
        np.savez_compressed(stage / f"pg_{tag}.npz", **pg)
        for v in self.names:
            np.savez_compressed(stage / f"rows_{tag}_{v}.npz", **rows[v])
        (stage / f"meta_{tag}.json").write_text(json.dumps({"n_pg": self.n_pg, "played": self.played, "skipped": self.skipped, "fallback": dict(self.fallback),
                                                            "spec": {k: [x[0], str(x[1])] for k, x in self.spec.items()}, "names": self.names}), encoding="utf-8")


def run(season, spec, vpairs, days=None, log=True):
    """Alle Spiele der Saison (nur Tage in days). spec = Varianten, vpairs = (c,k)-Paare fuer den Kern-Zusatz."""
    flat, store, sg, ctl = r2.load_games(season)
    adapter = Adapter(store)
    set_vspec(vpairs)
    acc = Acc3(spec)
    gp = defaultdict(int)
    t0 = time.time(); done = 0
    for gi, g in enumerate(sg):
        g["gi"] = gi
        g["gp"] = {"home": gp[g["home"]], "away": gp[g["away"]]}
        gp[g["home"]] += 1; gp[g["away"]] += 1
        if days is not None and g["date"] not in days:
            continue
        adapter.set_day(g["date"], (g["home"], g["away"]))
        for side, team, is_home in (("home", g["home"], True), ("away", g["away"], False)):
            for r in [r for r in g["rows"] if r["team"] == team and r["minutes"] > 0]:
                acc.played += 1
                fc = adapter.forecast_player(r["person_id"], g["date"], home=is_home, exp_spread=g["ctx"]["exp_spread"], exp_total=g["ctx"]["exp_total"], name=r["name"])
                if not fc["ok"]:
                    acc.skipped += 1
                    continue
                acc.add(g, side, r, fc)
        done += 1
        if log and done % 100 == 0:
            print(f"  {season}: {done} Spiele, {acc.n_pg} Spielerzeilen, {time.time() - t0:.0f} s", flush=True)
    set_vspec([])
    return acc, sg


def days_of(sg):
    return set(sorted({g["date"] for g in sg})[::4])


def grid_spec():
    spec = {"A": ("A", None)}
    for c in C_GRID:
        spec[f"F{c:g}"] = ("PV", (c, 0))
    for k in K_GRID:
        spec[f"H{k:g}"] = ("PV", (1.0, k))
    for v in V_GRID:
        spec[f"N{v:g}"] = ("N", (v, (1.0, 0)))
    return spec, [(c, 0) for c in C_GRID] + [(1.0, k) for k in K_GRID]


def common_idx(RA, RV):
    kA = RA["pg"].astype(np.int64) * 64 + RA["k"]
    kV = RV["pg"].astype(np.int64) * 64 + RV["k"]
    _, ia, iv = np.intersect1d(kA, kV, return_indices=True)
    return ia, iv


def mode_grid(season, stage):
    spec, pairs = grid_spec()
    t0 = time.time()
    flat, store, sg, ctl = r2.load_games(season)
    days = days_of(sg)
    del flat, store, sg
    acc, _ = run(season, spec, pairs, days=days)
    pg, rows = acc.arrays()
    out = {"tage": len(days), "spielerzeilen": int(acc.n_pg), "fallback": dict(acc.fallback), "varianten": {}, "laufzeit_s": round(time.time() - t0)}
    RA = rows["A"]
    out["brier_A_alle_zeilen"] = float(((RA["p"] - RA["y"]) ** 2).mean())
    for v in spec:
        if v == "A":
            continue
        ia, iv = common_idx(RA, rows[v])
        y = RA["y"][ia].astype(float)
        d = (rows[v]["p"][iv] - y) ** 2 - (RA["p"][ia] - y) ** 2
        dl = btm.ll(rows[v]["p"][iv], y) - btm.ll(RA["p"][ia], y)
        out["varianten"][v] = {"brier_diff": float(d.mean()), "logloss_diff": float(dl.mean()), "zeilen": int(len(rows[v]["p"])), "gemeinsame_zeilen": int(len(d))}
    stage.mkdir(parents=True, exist_ok=True)
    (stage / f"grid_{season}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"Raster {season} ({time.time() - t0:.0f} s): " + ", ".join(f"{v} {x['brier_diff']:+.5f}" for v, x in out["varianten"].items()), flush=True)


def choose(grid):
    """Beste Parameter je Familie aus dem Raster einer Trainingssaison (nur wenn Differenz < 0)."""
    res = {}
    for fam, key in (("F", "c"), ("H", "k"), ("N", "v")):
        cand = {v: x["brier_diff"] for v, x in grid["varianten"].items() if v[0] == fam}
        best = min(cand, key=cand.get)
        res[fam] = {key: float(best[1:]) if cand[best] < 0 else None, "differenz": cand[best], "raster": cand}
    return res


def run_spec(ch):
    """Varianten der Testsaison aus den gewaehlten Parametern (Trainingssaison)."""
    c, k, v = ch["F"]["c"], ch["H"]["k"], ch["N"]["v"]
    spec, pairs = {"A": ("A", None), "F1.5": ("PV", (1.5, 0))}, [(1.5, 0)]
    if c is not None:
        spec["F"] = ("PV", (c, 0)); pairs.append((c, 0))
    if k is not None:
        spec["H"] = ("PV", (1.0, k)); pairs.append((1.0, k))
    if c is not None and k is not None:
        spec["FH"] = ("PV", (c, k)); pairs.append((c, k))
    if v is not None:
        spec["N"] = ("N", (v, (1.0, 0)))
        if k is not None:
            spec["NH"] = ("N", (v, (1.0, k)))
    return spec, sorted(set(pairs))


def mode_run(season, stage):
    train = SEASONS[0] if season == SEASONS[1] else SEASONS[1]
    ch = choose(json.loads((stage / f"grid_{train}.json").read_text()))
    spec, pairs = run_spec(ch)
    t0 = time.time()
    acc, _ = run(season, spec, pairs)
    acc.save(stage, season)
    (stage / f"choice_{season}.json").write_text(json.dumps({"trainingssaison": train, "wahl": ch, "varianten": {k: [x[0], str(x[1])] for k, x in spec.items()}}, indent=1), encoding="utf-8")
    print(f"Lauf {season} fertig: {acc.n_pg} Spielerzeilen, {time.time() - t0:.0f} s, Rueckfaelle {dict(acc.fallback)}", flush=True)


def mode_pilot(stage):
    spec, pairs = grid_spec()
    flat, store, sg, ctl = r2.load_games("2025-26")
    days = set(sorted({g["date"] for g in sg})[:8])
    games = sum(1 for g in sg if g["date"] in days)
    del flat, store, sg
    t0 = time.time()
    acc, _ = run("2025-26", spec, pairs, days=days, log=False)
    dt = time.time() - t0
    per = dt / max(1, games)
    print(f"Pilot: {games} Spiele, {acc.n_pg} Spielerzeilen in {dt:.0f} s (inkl. Laden Teil davon) = {per:.2f} s je Spiel; Raster (1/4 der Tage, ca. 310 Spiele je Saison): ca. {per * 310 / 60:.0f} min; "
          f"voller Lauf (1230 Spiele, weniger Varianten): ca. {per * 1230 / 60 * 0.8:.0f} min je Saison")
    # Kontrollen
    ok = True
    A = acc.rows["A"]
    print("Zeilen A:", len(A["p"][0]) if len(A["p"]) and hasattr(A["p"][0], "__len__") else "-")
    print("Rueckfaelle N:", dict(acc.fallback))


# ----------------------------------------------------------------------------------------------- Bericht
def load_run(stage, season):
    pg = dict(np.load(stage / f"pg_{season}.npz"))
    meta = json.loads((stage / f"meta_{season}.json").read_text())
    rows = {v: dict(np.load(stage / f"rows_{season}_{v}.npz")) for v in meta["names"]}
    return pg, rows, meta, json.loads((stage / f"choice_{season}.json").read_text())


def merge(parts):
    pgs, rows, off_g, off_pg = [], defaultdict(list), 0, 0
    names = [v for v in parts[0][1] if all(v in p[1] for p in parts)]
    for pg, rw in parts:
        p2 = dict(pg); p2["game"] = pg["game"] + off_g; pgs.append(p2)
        for v in names:
            r_ = dict(rw[v]); r_["pg"] = rw[v]["pg"] + off_pg; rows[v].append(r_)
        off_g += int(pg["game"].max()) + 1; off_pg += len(pg["game"])
    return {k: np.concatenate([p[k] for p in pgs]) for k in pgs[0]}, {v: {k: np.concatenate([r_[k] for r_ in rows[v]]) for k in ("pg", "k", "p", "y")} for v in names}


def seg_flags(R):
    """Je Zeile: niedrigster Meilenstein, Hauptlinie (Chance am naechsten bei 50 %), hoechster Meilenstein des Spielers im Spiel."""
    pg = R["pg"]
    start = np.r_[True, pg[1:] != pg[:-1]]
    last = np.r_[pg[1:] != pg[:-1], True]
    idx = np.nonzero(start)[0]
    dev = np.abs(R["p"] - 0.5)
    mn = np.minimum.reduceat(dev, idx)
    cnt = np.diff(np.r_[idx, len(pg)])
    main = dev == np.repeat(mn, cnt)
    first_main = main & (np.cumsum(main) - np.repeat(np.cumsum(main)[idx] - main[idx], cnt) == 1)
    return start, first_main, last


def boot_mean(vals, gg, G, seed):
    cnt = bpm.group_sums(gg, np.ones(len(vals)), G)
    return bpm.boot_ratio(bpm.group_sums(gg, vals, G), cnt, seed=seed)


def compare(RA, RV, pg, G):
    ia, iv = common_idx(RA, RV)
    y = RA["y"][ia].astype(float)
    gg = pg["game"][RA["pg"][ia]]
    d = (RV["p"][iv] - y) ** 2 - (RA["p"][ia] - y) ** 2
    dl = btm.ll(RV["p"][iv], y) - btm.ll(RA["p"][ia], y)
    eb, el = boot_mean(d, gg, G, 9), boot_mean(dl, gg, G, 10)
    return {"gemeinsame_zeilen": int(len(d)), "differenz": bpm.pr(eb[0], 5), "ci95": [bpm.pr(eb[1], 5), bpm.pr(eb[2], 5)], "logloss_differenz": bpm.pr(el[0], 5), "logloss_ci95": [bpm.pr(el[1], 5), bpm.pr(el[2], 5)]}, ia, iv


def slices(pg, RA, RV, ia, iv):
    """Aufteilungen auf den gemeinsamen Zeilen: Brier-Differenz zu A, Abweichung (Treffer minus Modell) der Variante und von A in PP."""
    st, mn, last = seg_flags(RA)
    pga = RA["pg"][ia]
    y = RA["y"][ia].astype(float)
    pa, pv = RA["p"][ia], RV["p"][iv]
    emin, epts, ng, ot = pg["emin"][pga], pg["epts"][pga], pg["n_games"][pga], pg["ot"][pga]
    defs = {"min_unter_20": emin < 20, "min_20_28": (emin >= 20) & (emin <= 28), "min_ueber_28": emin > 28, "stars_epts_ab_20": epts >= 20, "rest_epts_unter_20": epts < 20,
            "wenig_vorgeschichte_unter_15": ng < 15, "viel_vorgeschichte": ng >= 15, "niedrigster_meilenstein": st[ia], "hauptlinie": mn[ia], "hoechster_meilenstein": last[ia],
            "overtime": ot == 1, "ohne_overtime": ot == 0}
    out = {}
    for nm, m in defs.items():
        if m.sum() < 30:
            out[nm] = {"n": int(m.sum())}
            continue
        out[nm] = {"n": int(m.sum()), "diff_brier": bpm.pr((((pv - y) ** 2) - ((pa - y) ** 2))[m].mean(), 5), "abw_pp": bpm.pr(100 * (y[m].mean() - pv[m].mean()), 2), "abw_pp_A": bpm.pr(100 * (y[m].mean() - pa[m].mean()), 2)}
    return out


def metrics(v, R, pg, G):
    m = bpm.row_metrics(R, pg["game"], G)
    m["stufen10"] = r2.calib10(pg["game"][R["pg"]], R["p"], R["y"].astype(float), G)
    return m


def verdict(per):
    neg = all(s["differenz"] < 0 and s["ci95"][1] < 0 for s in per.values())
    pos = all(s["differenz"] > 0 and s["ci95"][0] > 0 for s in per.values())
    return "Verbesserung gegenüber A" if neg else ("schlechter als A" if pos else "kein belastbarer Unterschied")


def build_report(stage):
    runs = {s: load_run(stage, s) for s in SEASONS}
    grids = {s: json.loads((stage / f"grid_{s}.json").read_text()) for s in SEASONS}
    r1 = json.loads((RESULTS / "backtest_player.json").read_text(encoding="utf-8"))
    r2j = json.loads((RESULTS / "backtest_player_round2.json").read_text(encoding="utf-8"))
    parts = {s: (runs[s][0], runs[s][1]) for s in SEASONS}
    datasets = {s: parts[s] for s in SEASONS}
    datasets["beide"] = merge([parts[s] for s in SEASONS])
    rep = {"version": 3, "hinweis": "Runde 3: nur Messung, keine Empfehlung.", "raster": grids, "wahl": {s: runs[s][3] for s in SEASONS}, "rueckfaelle_negbin": {s: runs[s][2]["fallback"] for s in SEASONS},
           "uebersprungen": {s: {"gespielt": runs[s][2]["played"], "uebersprungen": runs[s][2]["skipped"]} for s in SEASONS}, "saisons": {}, "kontrolle": {}}
    for s in SEASONS:
        pg, rows = parts[s]
        G = int(pg["game"].max()) + 1
        bA = bpm.row_metrics(rows["A"], pg["game"], G, with_ci=False)["brier"]
        b15 = bpm.row_metrics(rows["F1.5"], pg["game"], G, with_ci=False)["brier"]
        rep["kontrolle"][s] = {"A_runde3": bA, "A_runde1": r1["saisons"][s]["varianten"]["A"]["brier"], "A_runde2": r2j["saisons"][s]["varianten"]["A"]["brier"], "F1.5_runde3": b15, "F1.5_runde2": r2j["saisons"][s]["varianten"]["F1.5"]["brier"]}
    rep["kontrolle_ok"] = all(abs(x["A_runde3"] - x["A_runde1"]) < 5e-5 and abs(x["A_runde3"] - x["A_runde2"]) < 5e-5 and abs(x["F1.5_runde3"] - x["F1.5_runde2"]) < 5e-5 for x in rep["kontrolle"].values())
    for s, (pg, rows) in datasets.items():
        G = int(pg["game"].max()) + 1
        blk = {"spielerzeilen": int(len(pg["game"])), "spiele": G, "varianten": {}, "n_eff_mittel": bpm.pr(float(pg["n_eff"].mean()), 2)}
        for v, R in rows.items():
            m = metrics(v, R, pg, G)
            if v != "A":
                cmp_, ia, iv = compare(rows["A"], R, pg, G)
                m["vergleich_zu_A"] = cmp_
                m["aufteilung"] = slices(pg, rows["A"], R, ia, iv)
            blk["varianten"][v] = m
        rep["saisons"][s] = blk
    vd = {}
    for v in ("F1.5", "F", "H", "N", "FH", "NH"):
        if all(v in runs[s][1] for s in SEASONS):
            per = {s: rep["saisons"][s]["varianten"][v]["vergleich_zu_A"] for s in SEASONS}
            vd[v] = {"je_testsaison": per, "urteil": verdict(per)}
    rep["urteile"] = vd
    edge = {}
    for s in SEASONS:
        w = runs[s][3]["wahl"]
        edge[s] = {"c": w["F"]["c"], "k": w["H"]["k"], "v": w["N"]["v"],
                   "rand": [f"{lab}: Optimum eventuell darüber" for lab, val, mx in (("c", w["F"]["c"], max(C_GRID)), ("k", w["H"]["k"], max(K_GRID)), ("v", w["N"]["v"], max(V_GRID))) if val is not None and val == mx]
                           + [f"{lab}: Optimum eventuell darunter" for lab, val, mn in (("c", w["F"]["c"], min(C_GRID)), ("k", w["H"]["k"], min(K_GRID)), ("v", w["N"]["v"], min(V_GRID))) if val is not None and val == mn]}
    rep["raender_raster"] = edge
    return rep


def label(rep, s, v):
    w = rep["wahl"][s]["wahl"]
    c, k, vv = w["F"]["c"], w["H"]["k"], w["N"]["v"]
    return {"A": "v2-roh", "F1.5": "v3-breite-c1.5", "F": f"v3-breite-c{c:.1f}" if c else "-", "H": f"v3-ppm-unsicher-k{k:.1f}" if k else "-", "N": f"v3-negbin-v{vv:.1f}" if vv else "-",
            "FH": f"v3-breite-c{c:.1f}+ppm-unsicher-k{k:.1f}" if c and k else "-", "NH": f"v3-negbin-v{vv:.1f}+ppm-unsicher-k{k:.1f}" if vv and k else "-"}[v]


def th(n):
    return bpm.th(n)


def edge_txt(m):
    st = {b["stufe"]: b for b in m["stufen10"]}
    f = lambda k: f"{100 * st[k]['modell']:.0f}/{100 * st[k]['treffer']:.0f}" if k in st else "-"
    return f"0-10 %: {f('0-10 %')}, 90-100 %: {f('90-100 %')}"


def summary(rep, runtime=None):
    B = rep["saisons"]["beide"]; V = B["varianten"]
    L = ["ZUSAMMENFASSUNG Runde 3 (nur Messung; KEINE Änderung am Produktivmodell, KEINE Parameter-Empfehlung für die App)",
         f"Kontrolle A = Runde 1/2 und F1.5 = Runde 2 (Brier je Saison, 4 Stellen): {'ja' if rep['kontrolle_ok'] else 'NEIN'}. Bewertete Zeilen (beide Testsaisons, Meilenstein-Zeilen): " + ", ".join(f"{v} {th(m['n'])}" for v, m in V.items()) + "."]
    for s in SEASONS:
        w = rep["wahl"][s]["wahl"]
        L.append(f"Gewählt auf {rep['wahl'][s]['trainingssaison']} (Test {s}): c = {w['F']['c']}, k = {w['H']['k']}, v = {w['N']['v']} (None = kein Parameter besser als roh)." + (" Rand: " + "; ".join(rep["raender_raster"][s]["rand"]) if rep["raender_raster"][s]["rand"] else ""))
    for v, x in rep["urteile"].items():
        L.append(f"  {v:<5} " + "; ".join(f"{s}: ΔBrier {d['differenz']:+.5f} [{d['ci95'][0]:+.5f}; {d['ci95'][1]:+.5f}], ΔLogLoss {d['logloss_differenz']:+.5f}" for s, d in x["je_testsaison"].items()) + f" => {x['urteil']}")
    A = V["A"]
    L.append(f"Gesamt (beide Testsaisons): Brier/Log-Loss A {A['brier']:.4f}/{A['logloss']:.4f}" + "".join(f"; {v} {m['brier']:.4f}/{m['logloss']:.4f}" for v, m in V.items() if v != "A") + ".")
    L.append("Ränder (Modell %/Treffer %): A " + edge_txt(A) + "".join(f" | {v} {edge_txt(m)}" for v, m in V.items() if v not in ("A",)) + ".")
    if "H" in V:
        a = lambda v, k: V[v]["aufteilung"].get(k, {})
        L.append("H bei wenig Vorgeschichte (<15 Spiele) / viel: ΔBrier " + f"{a('H','wenig_vorgeschichte_unter_15').get('diff_brier')}" + " / " + f"{a('H','viel_vorgeschichte').get('diff_brier')}" + f"; Abweichung PP (A {a('H','wenig_vorgeschichte_unter_15').get('abw_pp_A')} -> H {a('H','wenig_vorgeschichte_unter_15').get('abw_pp')}).")
    for v in ("F", "N", "FH"):
        if v in V:
            a = V[v]["aufteilung"]
            L.append(f"{v}: ΔBrier Stars {a['stars_epts_ab_20'].get('diff_brier')}, Rest {a['rest_epts_unter_20'].get('diff_brier')}, Bank (<20 Min.) {a['min_unter_20'].get('diff_brier')}, niedrigster Meilenstein {a['niedrigster_meilenstein'].get('diff_brier')} (Abw. PP A {a['niedrigster_meilenstein'].get('abw_pp_A')} -> {a['niedrigster_meilenstein'].get('abw_pp')}), Hauptlinie {a['hauptlinie'].get('diff_brier')}, höchster {a['hoechster_meilenstein'].get('diff_brier')}.")
    L.append("Einschränkungen: Konstanten (Blowout-Kurve, league_ppm, Sigmas) für 2025-26 teils in-sample, für 2024-25 aus der Zukunft; Ausfälle unbekannt; Overtime nicht modelliert; Kader aus den letzten 10 Teamspielen; Raster nur jeder 4. Spieltag; Vorwert der ppm-Streuung (0,2 / Gewicht 4) ist eine Annahme; Zeilen eines Spiels korreliert (Bootstrap nach Spielen).")
    if runtime:
        L.append(f"Laufzeit Bericht {runtime:.0f} s.")
    return L


def render(rep, runtime):
    L = summary(rep, runtime)
    L += ["", "=" * 130, "Spieler-Backtest Runde 3. Details: Kopf von analysis/backtest_player_round3.py.", "=" * 130, ""]
    L += ["1. VERSIONEN (je Testsaison)"] + [f"  {s}: " + "; ".join(f"{v} = {label(rep, s, v)}" for v in rep["saisons"][s]["varianten"]) for s in SEASONS] + [""]
    L += ["2. KONTROLLE (Brier je Saison)"] + [f"  {s}: " + ", ".join(f"{k} {x:.4f}" for k, x in c.items()) for s, c in rep["kontrolle"].items()] + [""]
    L += ["3. RASTER auf der Trainingssaison (jeder 4. Spieltag; Brier-Differenz zu A auf gemeinsamen Zeilen, negativ = besser)"]
    for s, g in rep["raster"].items():
        L.append(f"  Training {s} ({g['tage']} Tage, {th(g['spielerzeilen'])} Spielerzeilen, Rückfälle NegBin {g['fallback']}): " + "; ".join(f"{v} {x['brier_diff']:+.5f} (LL {x['logloss_diff']:+.5f})" for v, x in g["varianten"].items()))
    L += [""]
    L += ["4. BEWERTUNGSREGEL (negativ UND Intervall ohne 0 in der Testsaison UND in beiden Richtungen dasselbe Vorzeichen)"]
    for v, x in rep["urteile"].items():
        L.append(f"  {v:<5} " + "; ".join(f"{s} ({label(rep, s, v)}): {d['differenz']:+.5f} [{d['ci95'][0]:+.5f}; {d['ci95'][1]:+.5f}]" for s, d in x["je_testsaison"].items()) + f"  => {x['urteil']}")
    L += [""]
    for s in list(SEASONS) + ["beide"]:
        blk = rep["saisons"][s]
        L += [f"=== Testsaison {s}: {blk['spiele']} Spiele, {th(blk['spielerzeilen'])} Spielerzeilen, mittlere wirksame Spielzahl {blk['n_eff_mittel']} ==="]
        rows = []
        for v, m in blk["varianten"].items():
            d = m.get("vergleich_zu_A")
            rows.append({"v": v, "n": th(m["n"]), "b": f"{m['brier']:.4f}", "ci": f"[{m['brier_ci95'][0]:.4f}; {m['brier_ci95'][1]:.4f}]", "l": f"{m['logloss']:.4f}", "p": f"{100 * m['mittel_modell']:.1f}", "t": f"{100 * m['trefferquote']:.1f}", "s": f"{m['steigung']}",
                         "d": f"{d['differenz']:+.5f}" if d else "-", "dc": f"[{d['ci95'][0]:+.5f}; {d['ci95'][1]:+.5f}]" if d else "-", "dl": f"{d['logloss_differenz']:+.5f}" if d else "-"})
        L += ["  " + t for t in bpm.fmt_table(rows, ["v", "n", "b", "ci", "l", "p", "t", "s", "d", "dc", "dl"], ["Variante", "Zeilen", "Brier", "95 %-Intervall", "Log-Loss", "Ø Chance %", "Treffer %", "Steigung", "Diff Brier zu A", "95 %-Intervall", "Diff LogLoss"])]
        L += ["  Kalibrierung nach 10-PP-Stufen (Modell % / Treffer % / Abweichung PP / n):"]
        for v, m in blk["varianten"].items():
            L.append(f"    {v:<5} " + " | ".join(f"{b['stufe'].split(' ')[0]}: {100 * b['modell']:.0f}/{100 * b['treffer']:.0f}/{b['abweichung_pp']:+.1f}/{b['n']}" for b in m["stufen10"]))
        L += ["  Aufteilung (ΔBrier zu A / Abweichung Treffer minus Modell in PP der Variante; in Klammern A):"]
        keys = list(next(m for v, m in blk["varianten"].items() if v != "A")["aufteilung"])
        rows = []
        for v, m in blk["varianten"].items():
            if v == "A":
                continue
            rows.append({"v": v, **{k: (f"{m['aufteilung'][k]['diff_brier']:+.5f} / {m['aufteilung'][k]['abw_pp']:+.1f} ({m['aufteilung'][k]['abw_pp_A']:+.1f})" if "diff_brier" in m["aufteilung"][k] else "-") for k in keys}})
        for k in keys:
            L.append(f"    {k:<30} n={max((m['aufteilung'][k]['n'] for v, m in blk['varianten'].items() if v != 'A'), default=0):>8}  " + " | ".join(f"{r['v']}: {r[k]}" for r in rows))
        L += [""]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------- Ablauf
def nice_popen(args, log):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve())] + args, stdout=open(log, "w"), stderr=subprocess.STDOUT)


def mode_all(stage):
    t0 = time.time()
    stage.mkdir(parents=True, exist_ok=True)
    for phase, args in (("grid", lambda s: ["--grid", s]), ("run", lambda s: ["--run", s])):
        procs = [nice_popen(args(s) + ["--stage-dir", str(stage)], stage / f"log_{phase}_{s}.txt") for s in SEASONS]
        codes = [p.wait() for p in procs]
        if any(codes):
            print(f"Abbruch in Stufe {phase}: Rückgabecodes {codes}; Logs in {stage}", flush=True)
            return 1
        print(f"Stufe {phase} fertig nach {time.time() - t0:.0f} s", flush=True)
    return mode_report(stage, t0)


def mode_report(stage, t0=None):
    t0 = t0 or time.time()
    rep = build_report(stage)
    runtime = time.time() - t0
    rep["laufzeit_sekunden_bericht"] = round(runtime)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / OUT_JSON).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (RESULTS / OUT_TXT).write_text(render(rep, runtime), encoding="utf-8")
    print("\n".join(summary(rep, runtime)))
    print(f"\nErgebnisse: {RESULTS / OUT_JSON}\n            {RESULTS / OUT_TXT}")
    return 0


def selftest():
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    from bt_player_adapter import _fake_rows
    store = bpa.HistoryStore(_fake_rows())
    ad = Adapter(store)
    day = "2024-11-15"
    ad.set_day(day, ("AAA", "BBB"))
    rows = [r for r in _fake_rows() if r["date"] == day and r["team"] == "AAA"][:6]
    orig = pf.forecast_player
    set_vspec([(1.0, 0), (1.5, 0), (2.0, 0), (1.0, 1.0), (1.0, 2.0), (2.0, 1.0)])
    fcs = [ad.forecast_player(r["person_id"], day, home=True, exp_spread=3.0, exp_total=224.0, name="x") for r in rows]
    fcs = [f for f in fcs if f["ok"]]
    check("Spieler mit Prognose vorhanden", len(fcs) > 0, len(fcs))
    f = fcs[0]
    pv = f["p_var"]
    check("c = 1, k = 0 identisch zu A (Kern unveraendert)", np.allclose(pv[(1.0, 0)], p_array(f), atol=1e-12))
    ref = bpa.ORIG_FORECAST
    mean = lambda p: float(p.sum())
    check("breiter: Erwartungswert (Summe P(>=n)) praktisch gleich, Raender breiter", abs(mean(pv[(2.0, 0)]) - mean(pv[(1.0, 0)])) < 0.25 and pv[(2.0, 0)][-1] >= pv[(1.0, 0)][-1] - 1e-12 and pv[(2.0, 0)][0] <= pv[(1.0, 0)][0] + 1e-12)
    check("H: k = 2 breiter als k = 1 (Ende der Kurve), Mittelwert gleich", pv[(1.0, 2.0)][-1] >= pv[(1.0, 1.0)][-1] - 1e-12 and abs(mean(pv[(1.0, 2.0)]) - mean(pv[(1.0, 0)])) < 0.25)
    check("H-Unsicherheit wirkt: Kurve weicht von A ab", not np.allclose(pv[(1.0, 1.0)], pv[(1.0, 0)]))
    p = p_array(f)
    q, fb = nb_p(p, 1.5)
    pmf = lambda a: np.r_[1.0, a][:-1] - np.r_[1.0, a][1:]
    n = np.arange(60)
    m0, m1 = (n * pmf(p)).sum(), (n * pmf(q)).sum()
    check("NegBin: Mittelwert bleibt (bis auf Abschneiden bei 60)", fb or abs(m0 - m1) < 0.15, (m0, m1, fb))
    check("NegBin: monoton fallend, 0..1", bool(np.all(np.diff(q) <= 1e-12) and q.min() >= 0 and q.max() <= 1))
    check("NegBin-Rueckfall bei Varianz <= Mittelwert (Eingabe unveraendert)", nb_p(np.r_[np.ones(10), np.zeros(50)], 1.0)[1])
    check("Konstanten zurueckgestellt", pf.F_MIN == 0.6 and pf.F_MAX == 1.4 and pf.TEAM_MATCH_STRENGTH == 1.0)
    set_vspec([])
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv
    try:
        os.nice(max(0, 15 - os.nice(0)))                       # niedrige Prioritaet (falls nicht schon per nice gestartet)
    except OSError:
        pass
    stage = Path(a[a.index("--stage-dir") + 1]) if "--stage-dir" in a else Path("/tmp/nbaedge_round3")
    if "--selftest" in a:
        sys.exit(selftest())
    if "--pilot" in a:
        mode_pilot(stage); sys.exit(0)
    if "--grid" in a:
        mode_grid(a[a.index("--grid") + 1], stage); sys.exit(0)
    if "--run" in a:
        mode_run(a[a.index("--run") + 1], stage); sys.exit(0)
    if "--report" in a:
        sys.exit(mode_report(stage))
    if "--all" in a:
        sys.exit(mode_all(stage))
    print(__doc__)
