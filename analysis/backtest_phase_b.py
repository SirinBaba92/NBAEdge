"""
Phase-B-Backtest (ELO_ANALYSE.md, Abschnitt 3). Liest nur data/cache, keine API-Calls, keine Dateien
ausserhalb von analysis/results werden geschrieben.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_phase_b.py

Ablauf
1. Alte Engine nachgebaut (analysis/old_engine_replica.py, geprueft gegen das gespeicherte Modell).
2. Neues Modell (models/points_rating.py) mit Parametergitter, jeweils ueber alle Spiele laufen lassen.
3. Fuer jede Test-Saison S werden Parameter NUR mit inneren Walk-forward-Folds (Saisons 2017..S-1)
   gewaehlt. Ratings/hca/sigma sind ohnehin kausal (nur Daten vor dem jeweiligen Spiel).
4. Test: erste 20 Spiele je Team (Regular Season, beide Teams <20 Spiele) und alle Regular-Season-Spiele.
5. Vergleich: (a) altes Modell unveraendert (Spread = ELO-Diff/25, Isotonik, kein Clip),
              (b) altes Modell mit Faktor 50 + Clip [0.03, 0.97] (wie aktuell im Dashboard).
"""
import itertools, json, sys, time
from pathlib import Path
import numpy as np
import warnings
warnings.filterwarnings("ignore")
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import (load_games, window, logloss, boot_diff, reliability, RESULTS, phi)
from bt_v2 import run_v2, win_prob
import old_engine_replica as old

PRIMARY = [2023, 2024, 2025]
EXTRA = [2021, 2022]
INNER_FIRST = 2017
CLIP = (0.03, 0.97)

R_GRID = [dict(r=r, k=k, cap=c) for r in (0.2, 0.3, 0.4, 0.5, 0.6)
          for k in (0.03, 0.04, 0.05, 0.07, 0.09) for c in (20.0, 25.0, 35.0, 50.0, 80.0)]
T_GRID = (
    [dict(tmode="dev", t_alpha=a, t_rc=rc, t_po=po, L_alpha=la)
     for a in (0.05, 0.10, 0.15, 0.20, 0.30) for rc in (0.0, 0.3, 0.5, 0.7, 1.0) for po in (False, True)
     for la in (0.01, 0.02, 0.04)]
    + [dict(tmode="ema", t_alpha=a, t_rc=rc, t_po=po)
       for a in (0.05, 0.10, 0.15, 0.20, 0.30) for rc in (0.0, 0.3, 0.5, 0.7, 1.0) for po in (False, True)]
)


def key(d):
    return json.dumps(d, sort_keys=True)


# --------------------------------------------------------------------------- #
#  Auswahl-Kriterien (nur innere Folds)                                         #
# --------------------------------------------------------------------------- #
def inner_mask(arr, folds):
    return np.isin(arr["season"], folds) & (arr["post"] == 0)


def rating_score(arr, folds):
    p = win_prob(arr, *CLIP)
    y = (arr["margin"] > 0).astype(float)
    err = (p - y) ** 2
    m = inner_mask(arr, folds)
    e = m & (arr["gp_h"] < 20) & (arr["gp_a"] < 20)
    return 0.5 * err[e].mean() + 0.5 * err[m].mean()          # Brier: 50 % erste 20 Spiele, 50 % alle


def total_score(arr, folds):
    err = np.abs(arr["total"] - arr["total_pred"])
    m = inner_mask(arr, folds)
    e = m & (arr["gp_h"] < 20) & (arr["gp_a"] < 20)
    return 0.5 * err[e].mean() + 0.5 * err[m].mean()          # Total-MAE: 50 % erste 20 Spiele, 50 % alle


# --------------------------------------------------------------------------- #
#  Altes Modell: Walk-forward-Wahrscheinlichkeit wie die Engine-Pipeline         #
# --------------------------------------------------------------------------- #
def old_probs(o, season):
    X = np.c_[o["diff"], o["fdiff"], o["rdiff"]]
    y = o["hw"]
    tr = o["season"] < season
    sc = StandardScaler().fit(X[tr])
    lr = CalibratedClassifierCV(LogisticRegression(max_iter=1000), cv=5, method="isotonic")
    lr.fit(sc.transform(X[tr]), y[tr])
    te = o["season"] == season
    p = np.full(len(y), np.nan)
    p[te] = lr.predict_proba(sc.transform(X[te]))[:, 1]
    return p


def main():
    t0 = time.time()
    games = load_games()
    print(f"{len(games)} Spiele aus dem Cache (2015-2025)")
    o, _ = old.run(games)
    assert np.array_equal(o["season"], np.array([g["season"] for g in games], float))

    # --- Gitter laufen lassen -------------------------------------------------
    print(f"Rating-Gitter: {len(R_GRID)} Laeufe ...")
    r_runs = {key(p): run_v2(games, p)[0] for p in R_GRID}
    print(f"Total-Gitter: {len(T_GRID)} Laeufe ...  ({time.time()-t0:.0f}s)")
    t_runs = {key(p): run_v2(games, p)[0] for p in T_GRID}
    default_arr, default_model = run_v2(games, {})

    # --- Parameterwahl je Test-Saison (nur innere Folds) ------------------------
    chosen = {}
    for S in PRIMARY + EXTRA + [2026]:
        folds = list(range(INNER_FIRST, S))
        rs = sorted(((rating_score(r_runs[key(p)], folds), p) for p in R_GRID), key=lambda x: x[0])
        ts = sorted(((total_score(t_runs[key(p)], folds), p) for p in T_GRID), key=lambda x: x[0])
        chosen[S] = {"rating": rs[0][1], "rating_score": rs[0][0], "rating_top5": [(round(a, 5), b) for a, b in rs[:5]],
                     "total": ts[0][1], "total_score": ts[0][0], "total_top5": [(round(a, 4), b) for a, b in ts[:5]]}
        print(f"S={S}: Rating {rs[0][1]} (innerer Brier {rs[0][0]:.4f}) | Total {ts[0][1]} (innere MAE {ts[0][0]:.2f})")

    # --- Test-Vorhersagen sammeln ----------------------------------------------
    def collect(seasons, early):
        out = {k: [] for k in ["a_sp", "b_sp", "v_sp", "v0_sp", "a_p", "b_p", "v_p", "v0_p", "y",
                               "a_tot", "v_tot", "fix_tot", "total", "season", "margin"]}
        for S in seasons:
            m = window(o, S, early)
            pa = old_probs(o, S)[m]
            rv = r_runs[key(chosen[S]["rating"])]
            tv = t_runs[key(chosen[S]["total"])]
            out["a_sp"].append(o["diff"][m] / 25.0)
            out["b_sp"].append(o["diff"][m] / 50.0)
            out["a_p"].append(pa)
            out["b_p"].append(np.clip(pa, *CLIP))
            out["v_sp"].append((rv["rdiff"] + rv["hca"])[m])
            out["v_p"].append(win_prob(rv, *CLIP)[m])
            out["v0_sp"].append((default_arr["rdiff"] + default_arr["hca"])[m])
            out["v0_p"].append(win_prob(default_arr, *CLIP)[m])
            out["y"].append((o["margin"][m] > 0).astype(float))
            out["margin"].append(o["margin"][m])
            out["a_tot"].append(o["exp_total"][m])
            out["v_tot"].append(tv["total_pred"][m])
            out["total"].append(o["total"][m])
            out["season"].append(np.full(m.sum(), S))
        return {k: np.concatenate(v) for k, v in out.items() if v}

    def metrics(c, tag):
        p, sp, y, mg = c[tag + "_p"], c[tag + "_sp"], c["y"], c["margin"]
        tot = c["a_tot"] if tag in ("a", "b") else c["v_tot"]
        return {
            "n": int(len(y)),
            "spread_mae": float(np.mean(np.abs(mg - sp))),
            "total_mae": float(np.mean(np.abs(c["total"] - tot))),
            "total_bias": float(np.mean(c["total"] - tot)),
            "brier": float(np.mean((p - y) ** 2)),
            "logloss": float(np.mean(logloss(p, y))),
            "extreme_pct": float(100 * np.mean((p > 0.9) | (p < 0.1))),
            "exact01": int(np.sum((p <= 0) | (p >= 1))),
            "acc": float(np.mean((p > 0.5) == (y > 0.5))),
        }

    def vectors(c, tag):
        p, sp, y, mg = c[tag + "_p"], c[tag + "_sp"], c["y"], c["margin"]
        tot = c["a_tot"] if tag in ("a", "b") else c["v_tot"]
        return {"spread_mae": np.abs(mg - sp), "total_mae": np.abs(c["total"] - tot),
                "brier": (p - y) ** 2, "logloss": logloss(p, y),
                "extreme_pct": 100.0 * ((p > 0.9) | (p < 0.1)).astype(float)}

    results = {"chosen": {str(k): v for k, v in chosen.items()}}
    verdicts = {}
    for name, seasons in (("primary", PRIMARY), ("extra5", EXTRA + PRIMARY)):
        for early in (True, False):
            c = collect(seasons, early)
            label = f"{name}_{'early20' if early else 'all'}"
            res = {t: metrics(c, t) for t in ("a", "b", "v", "v0")}
            vec = {t: vectors(c, t) for t in ("a", "b", "v", "v0")}
            diffs = {}
            for ref in ("a", "b"):
                for new in ("v", "v0"):
                    diffs[f"{new}-{ref}"] = {m: boot_diff(vec[new][m], vec[ref][m]) for m in vec[new]}
            # Totals: nur Total-Teil (auch alt-vs-neu)
            res["tot_diff_v_vs_a"] = boot_diff(vec["v"]["total_mae"], vec["a"]["total_mae"])
            res["reliability"] = {
                t: reliability(c[t + "_p"], c["y"], [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0]
                               if not early else [0, .2, .4, .6, .8, 1.0]) for t in ("a", "b", "v")}
            results[label] = {"metrics": res, "diffs": diffs}
            # per-season (nur fuer primary)
            if name == "primary":
                results[label]["per_season"] = {}
                for S in seasons:
                    cs = collect([S], early)
                    results[label]["per_season"][str(S)] = {t: metrics(cs, t) for t in ("a", "b", "v")}

    # --- Totals-Ablationen (feste Varianten, ohne Auswahl) ----------------------
    abl_defs = {
        "A alt (EMA a=0.1, inkl. Playoffs, keine Uebernahme)": None,
        "B EMA ohne Playoffs, keine Uebernahme": dict(tmode="ema", t_alpha=0.10, t_rc=0.0, t_po=False),
        "C EMA ohne Playoffs, Uebernahme 50 % zum Ligamittel": dict(tmode="ema", t_alpha=0.10, t_rc=0.5, t_po=False),
        "D Liga-Niveau + Team-Abw. ohne Playoffs, Uebernahme 50 %": dict(tmode="dev", t_alpha=0.10, t_rc=0.5, t_po=False, L_alpha=0.02),
        "E wie D, aber MIT Playoffs": dict(tmode="dev", t_alpha=0.10, t_rc=0.5, t_po=True, L_alpha=0.02),
        "F wie D, keine Team-Uebernahme (rc=0)": dict(tmode="dev", t_alpha=0.10, t_rc=0.0, t_po=False, L_alpha=0.02),
    }
    abl = {}
    for early in (True, False):
        tag = "early20" if early else "all"
        abl[tag] = {}
        vecs = {}
        names = list(abl_defs) + ["G verschachtelt gewaehlt"]
        for nm in names:
            es = []
            for S in PRIMARY:
                m = window(o, S, early)
                if nm.startswith("G"):
                    pred = t_runs[key(chosen[S]["total"])]["total_pred"][m]
                else:
                    prm = abl_defs[nm]
                    pred = o["exp_total"][m] if prm is None else run_v2(games, prm)[0]["total_pred"][m]
                es.append(o["total"][m] - pred)
            vecs[nm] = np.concatenate(es)
        ref = vecs[names[0]]
        for nm in names:
            e = vecs[nm]
            entry = {"total_mae": float(np.abs(e).mean()), "bias": float(e.mean()), "n": int(len(e))}
            if nm != names[0]:
                entry["mae_diff_vs_A"] = boot_diff(np.abs(e), np.abs(ref))
                entry["bias_diff_vs_A"] = boot_diff(e, ref)
            abl[tag][nm] = entry
    results["total_ablation"] = abl

    # --- Endmodell: Parameterwahl mit allen Saisons bis 2025 ------------------------
    results["final_params"] = {"rating": chosen[2026]["rating"], "total": chosen[2026]["total"]}
    results["default_model_calibration"] = {"hca": default_model.hca, "sigma": default_model.sigma}

    # --- Uebernahmeregel (primary, early20; Kontrolle: alle Spiele) ------------------
    def rule(label):
        r = results[label]
        out = {}
        for ref in ("a", "b"):
            d = r["diffs"][f"v-{ref}"]
            m_new, m_ref = r["metrics"]["v"], r["metrics"][ref]
            not_worse = d["brier"][0] <= 0 and d["spread_mae"][0] <= 0
            sig = [m for m in ("brier", "spread_mae", "total_mae", "logloss") if d[m][2] < 0]
            extreme_down = m_new["extreme_pct"] < m_ref["extreme_pct"]
            out[ref] = {"brier_nicht_schlechter": d["brier"][0] <= 0, "spread_nicht_schlechter": d["spread_mae"][0] <= 0,
                        "signifikant_besser": sig, "extremquote_sinkt": extreme_down,
                        "ok": bool(not_worse and sig and extreme_down)}
        return out

    results["rule_early20"] = rule("primary_early20")
    results["rule_all"] = rule("primary_all")
    (RESULTS / "phase_b_results.json").write_text(json.dumps(results, indent=1, default=float))
    print(f"fertig in {time.time()-t0:.0f}s -> analysis/results/phase_b_results.json")
    print(json.dumps({"rule_early20": results["rule_early20"], "rule_all": results["rule_all"]}, indent=1))


if __name__ == "__main__":
    main()
