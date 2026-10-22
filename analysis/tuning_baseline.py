"""
Modell-Tuning, Schritt 1: Baseline messen (keine Parametersuche). Nur lesend: liest data/cache und das Pickle (nur Pruefung), schreibt nur
analysis/results/tuning_baseline.json. Keine API-Calls, Produktivdateien bleiben unveraendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/tuning_baseline.py

Gemessen wird die produktive ELO-Engine (K = 20, Heimvorteil 100, MOV 2,2 * ln(Marge + 1), keine Sommer-Regression, Faktor 50, Clip 3-97 %) ueber
analysis/old_engine_replica.run. Alle Vorhersagen entstehen chronologisch VOR dem Spiel: Ratings/Form/Ruhetage stehen vor dem Update; die
Siegwahrscheinlichkeit (Logistik + Isotonik wie in der Engine) wird je Test-Saison nur auf frueheren Saisons trainiert.

Total: Die produktive Engine nimmt Playoff-Spiele aus den Off/Def-Werten heraus (models/elo.py). Der Nachbau old_engine_replica rechnet sie noch mit
(Stand vor dem Fix); deshalb berechnet dieses Skript die Total-Prognose selbst mit derselben Regel wie die Engine (und prueft sie gegen das Pickle).

Fenster: (a) erste 20 Spiele je Team 2023-25, (b) alle Regular-Season-Spiele 2023-25, (c) Kontrolle 2021/22 (erste 20 Spiele und alle Spiele).
"""
import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import ROOT, RESULTS, load_games, window, logloss  # noqa: E402
import old_engine_replica as old  # noqa: E402

PRODUCTION = dict(K=20.0, hca=100.0, mov="cur", carry=0.0, kboost=0.0, post_w=1.0, total_alpha=0.1)   # = models/elo.py + config/settings.py
SPREAD_FACTOR = 50.0
CLIP = (0.03, 0.97)
N_BOOT = 2000
WINDOWS = [("a_erste20_2023-25", [2023, 2024, 2025], True),
           ("b_alle_2023-25", [2023, 2024, 2025], False),
           ("c1_kontrolle_erste20_2021-22", [2021, 2022], True),
           ("c2_kontrolle_alle_2021-22", [2021, 2022], False)]


# --------------------------------------------------------------------------- #
#  Pruefung gegen das Pickle                                                    #
# --------------------------------------------------------------------------- #
def total_predictions(games, alpha=0.1):
    """Total-Prognose vor jedem Spiel wie models/elo.py: Off/Def-EMA, Playoff-Spiele werden NICHT eingerechnet. Rueckgabe: (Array, off, def)."""
    off, de = defaultdict(float), defaultdict(float)
    pred = np.zeros(len(games))
    for i, g in enumerate(games):
        h, a = g["home_team"]["full_name"], g["visitor_team"]["full_name"]
        pred[i] = (off[h] + de[a]) / 2 + (off[a] + de[h]) / 2
        if g.get("postseason", False):
            continue
        hp, ap = int(g["home_team_score"]), int(g["visitor_team_score"])
        off[h] = (1 - alpha) * off[h] + alpha * hp
        de[h] = (1 - alpha) * de[h] + alpha * ap
        off[a] = (1 - alpha) * off[a] + alpha * ap
        de[a] = (1 - alpha) * de[a] + alpha * hp
    return pred, off, de


def check_against_pickle(games, season_end, off, de):
    """Der Nachbau muss zum Pickle passen. Das Pickle kennt evtl. neuere Spiele als der Cache (Saison 2026/27): Teams dieser Spiele duerfen bei den
    ELO-Ratings abweichen (hoechstens 2 je Spiel), alle anderen muessen exakt stimmen. Off/Def muessen fuer diese anderen Teams exakt stimmen."""
    from models.elo import EloEngine
    eng = EloEngine.load()
    ids = {g["id"] for g in games}
    extra = eng.processed_ids - ids
    missing = ids - eng.processed_ids
    last = season_end[max(season_end)]
    dev = {t: abs(last[t] - eng.ratings[t]) for t in eng.ratings}
    differing = sorted(t for t, v in dev.items() if v > 1e-6)
    same = [t for t in eng.ratings if dev[t] <= 1e-6]
    dev_off = max(abs(off[t] - eng.off_ratings[t]) for t in same)
    dev_def = max(abs(de[t] - eng.def_ratings[t]) for t in same)
    ok = (not missing) and len(differing) <= 2 * len(extra) and max((dev[t] for t in same), default=0) < 1e-9 and dev_off < 1e-9 and dev_def < 1e-9
    return {"ok": bool(ok), "pickle_stand": str(eng.ratings_as_of()), "pickle_spiele": len(eng.processed_ids), "cache_spiele": len(ids),
            "im_pickle_nicht_im_cache": len(extra), "im_cache_nicht_im_pickle": len(missing), "teams_mit_abweichung": differing,
            "teams_exakt": len(same), "max_abw_rating": float(max((dev[t] for t in same), default=0)), "max_abw_off": float(dev_off), "max_abw_def": float(dev_def)}


# --------------------------------------------------------------------------- #
#  Siegwahrscheinlichkeit wie die Engine-Pipeline, je Saison nur auf frueher     #
# --------------------------------------------------------------------------- #
def walk_forward_probs(o, seasons):
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    X = np.c_[o["diff"], o["fdiff"], o["rdiff"]]
    y = o["hw"]
    p = np.full(len(y), np.nan)
    for S in seasons:
        tr, te = o["season"] < S, o["season"] == S
        sc = StandardScaler().fit(X[tr])
        lr = CalibratedClassifierCV(LogisticRegression(max_iter=1000), cv=5, method="isotonic")
        lr.fit(sc.transform(X[tr]), y[tr])
        p[te] = lr.predict_proba(sc.transform(X[te]))[:, 1]
    return np.clip(p, *CLIP)


def prev_home_rate(o, season):
    m = (o["season"] == season - 1) & (o["post"] == 0)
    return float(o["hw"][m].mean())


# --------------------------------------------------------------------------- #
#  Kennzahlen mit Bootstrap                                                     #
# --------------------------------------------------------------------------- #
def boot(fn, arrays, n=N_BOOT, seed=0):
    """fn(*Arrays) -> Zahl; Punktwert und 95-%-Intervall ueber Ziehen von Spielen mit Zuruecklegen."""
    rng = np.random.default_rng(seed)
    n_obs = len(arrays[0])
    idx = rng.integers(0, n_obs, (n, n_obs))
    vals = np.array([fn(*[a[i] for a in arrays]) for i in idx])
    return float(fn(*arrays)), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def metrics_for(c):
    """c: dict mit p, y, ref, sp, margin, tp, total (Arrays eines Fensters)."""
    p, y, ref = c["p"], c["y"], c["ref"]
    sp_err = c["sp"] - c["margin"]                                    # Prognose minus Ergebnis, Heimsicht
    t_err = c["tp"] - c["total"]
    home_pred, away_pred = (c["tp"] + c["sp"]) / 2, (c["tp"] - c["sp"]) / 2
    home_act, away_act = (c["total"] + c["margin"]) / 2, (c["total"] - c["margin"]) / 2
    h_err, a_err = home_pred - home_act, away_pred - away_act
    brier = lambda pp, yy: float(np.mean((pp - yy) ** 2))
    out = {
        "n": int(len(y)),
        "trefferquote": boot(lambda pp, yy: float(np.mean((pp > 0.5) == (yy > 0.5))), (p, y)),
        "trefferquote_immer_heim": float(np.mean(y)),
        "brier": boot(brier, (p, y)),
        "logloss": boot(lambda pp, yy: float(np.mean(logloss(pp, yy))), (p, y)),
        "brier_referenz_immer_heimquote_vorsaison": brier(ref, y),
        "brier_skill": boot(lambda pp, rr, yy: 1 - brier(pp, yy) / brier(rr, yy), (p, ref, y)),
        "spread_mae": boot(lambda e: float(np.mean(np.abs(e))), (sp_err,)),
        "spread_bias": boot(lambda e: float(np.mean(e)), (sp_err,)),
        "total_mae": boot(lambda e: float(np.mean(np.abs(e))), (t_err,)),
        "total_bias": boot(lambda e: float(np.mean(e)), (t_err,)),
        "heim_punkte_bias": boot(lambda e: float(np.mean(e)), (h_err,)),
        "heim_punkte_mae": boot(lambda e: float(np.mean(np.abs(e))), (h_err,)),
        "gast_punkte_bias": boot(lambda e: float(np.mean(e)), (a_err,)),
        "gast_punkte_mae": boot(lambda e: float(np.mean(np.abs(e))), (a_err,)),
        "extremquote": float(np.mean((p > 0.9) | (p < 0.1))),
    }
    out["bias_je_saison"] = {}
    for s in sorted(set(c["season"])):
        m = c["season"] == s
        out["bias_je_saison"][str(int(s))] = {
            "n": int(m.sum()), "heim_bias": float(h_err[m].mean()), "gast_bias": float(a_err[m].mean()),
            "spread_bias": float(sp_err[m].mean()), "total_bias": float(t_err[m].mean()),
            "echte_heim_marge": float(c["margin"][m].mean()), "prognose_heim_marge": float(c["sp"][m].mean())}
    edges = np.linspace(0, 1, 11)
    cal = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & ((p < hi) if hi < 1 else (p <= hi))
        if m.sum():
            cal.append({"von": round(float(lo), 1), "bis": round(float(hi), 1), "n": int(m.sum()), "mittleres_p": float(p[m].mean()), "tatsaechlich": float(y[m].mean())})
    out["kalibrierung"] = cal
    return out


# --------------------------------------------------------------------------- #
#  Ausgabe                                                                      #
# --------------------------------------------------------------------------- #
def fmt(t, d=3, pct=False):
    v, lo, hi = t
    if pct:
        return f"{v * 100:6.1f} % [{lo * 100:5.1f}; {hi * 100:5.1f}]"
    return f"{v:+.{d}f} [{lo:+.{d}f}; {hi:+.{d}f}]" if d != 0 else f"{v}"


def fmt_pos(t, d=3):
    v, lo, hi = t
    return f"{v:.{d}f} [{lo:.{d}f}; {hi:.{d}f}]"


def print_report(res, write=print):
    for name, m in res["fenster"].items():
        write(f"\n=== {name}  (n = {m['n']}) ===")
        write(f"  Trefferquote Siegerseite       {fmt(m['trefferquote'], pct=True)}   (immer Heim: {m['trefferquote_immer_heim'] * 100:.1f} %)")
        write(f"  Brier                          {fmt_pos(m['brier'], 4)}   Referenz immer Heimquote Vorsaison: {m['brier_referenz_immer_heimquote_vorsaison']:.4f}")
        write(f"  Brier-Skill gegen Referenz     {fmt(m['brier_skill'], 4)}")
        write(f"  Log-Loss                       {fmt_pos(m['logloss'], 4)}")
        write(f"  Spread-MAE                     {fmt_pos(m['spread_mae'], 2)}")
        write(f"  Spread-Bias (Prog. - Erg.)     {fmt(m['spread_bias'], 2)}")
        write(f"  Total-MAE                      {fmt_pos(m['total_mae'], 2)}")
        write(f"  Total-Bias (Prog. - Erg.)      {fmt(m['total_bias'], 2)}")
        write(f"  Heim-Punkte  Bias / MAE        {fmt(m['heim_punkte_bias'], 2)}  /  {fmt_pos(m['heim_punkte_mae'], 2)}")
        write(f"  Gast-Punkte  Bias / MAE        {fmt(m['gast_punkte_bias'], 2)}  /  {fmt_pos(m['gast_punkte_mae'], 2)}")
        write("  Bias je Saison (Prognose minus Ergebnis):")
        write(f"    {'Saison':<8}{'n':>6}{'Heim':>9}{'Gast':>9}{'Spread':>9}{'Total':>9}{'echte Marge':>13}{'Prog.-Marge':>13}")
        for s, b in m["bias_je_saison"].items():
            write(f"    {s:<8}{b['n']:>6}{b['heim_bias']:>+9.2f}{b['gast_bias']:>+9.2f}{b['spread_bias']:>+9.2f}{b['total_bias']:>+9.2f}{b['echte_heim_marge']:>+13.2f}{b['prognose_heim_marge']:>+13.2f}")
        write("  Kalibrierung (Siegwahrscheinlichkeit Heim):")
        write(f"    {'Klasse':<11}{'n':>6}{'mittleres p':>13}{'tatsaechlich':>14}{'Differenz':>11}")
        for r in m["kalibrierung"]:
            write(f"    {r['von']:.1f}-{r['bis']:.1f}   {r['n']:>6}{r['mittleres_p']:>13.3f}{r['tatsaechlich']:>14.3f}{r['tatsaechlich'] - r['mittleres_p']:>+11.3f}")


def main(write=print):
    t0 = time.perf_counter()
    games = load_games()
    t_load = time.perf_counter()
    o, season_end = old.run(games, **PRODUCTION)
    t_run = time.perf_counter()
    tp, off, de = total_predictions(games, PRODUCTION["total_alpha"])
    pickle_before = (ROOT / "data" / "elo_model.pkl").stat().st_mtime_ns
    chk = check_against_pickle(games, season_end, off, de)
    write("Pruefung Nachbau gegen Pickle: " + ("OK" if chk["ok"] else "FEHLER") + f" | Pickle-Stand {chk['pickle_stand']}, {chk['pickle_spiele']} Spiele im Pickle, "
          f"{chk['cache_spiele']} im Cache ({chk['im_pickle_nicht_im_cache']} neuer im Pickle) | Teams mit Abweichung (nur Spiele ab {chk['pickle_stand']}): {len(chk['teams_mit_abweichung'])} | "
          f"max. Abweichung der uebrigen {chk['teams_exakt']} Teams: Rating {chk['max_abw_rating']:.1e}, Off {chk['max_abw_off']:.1e}, Def {chk['max_abw_def']:.1e}")
    if not chk["ok"]:
        write("ABBRUCH: Der Nachbau passt nicht zum Pickle, die Baseline waere nicht die Produktivengine.")
        return 2
    t_check = time.perf_counter()
    seasons = sorted({s for _n, ss, _e in WINDOWS for s in ss})
    p_all = walk_forward_probs(o, seasons)
    t_prob = time.perf_counter()
    ref_all = np.full(len(p_all), np.nan)
    for S in seasons:
        ref_all[o["season"] == S] = prev_home_rate(o, S)
    sp_all = o["diff"] / SPREAD_FACTOR
    res = {"version": 1, "parameter": {**PRODUCTION, "spread_faktor": SPREAD_FACTOR, "clip": CLIP, "mov": "2,2 * ln(Marge + 1)", "sommer_regression": 0.0},
           "pruefung_pickle": chk, "bootstrap": {"ziehungen": N_BOOT, "intervall": "95 %"}, "fenster": {}}
    for name, ss, early in WINDOWS:
        m = np.zeros(len(p_all), bool)
        for S in ss:
            m |= window(o, S, early)
        c = {"p": p_all[m], "y": o["hw"][m], "ref": ref_all[m], "sp": sp_all[m], "margin": o["margin"][m], "tp": tp[m], "total": o["total"][m], "season": o["season"][m]}
        res["fenster"][name] = metrics_for(c)
    t_end = time.perf_counter()
    res["laufzeit_sekunden"] = {"laden": round(t_load - t0, 2), "nachbau": round(t_run - t_load, 2), "pickle_pruefung": round(t_check - t_run, 2),
                                "wahrscheinlichkeiten": round(t_prob - t_check, 2), "kennzahlen_bootstrap": round(t_end - t_prob, 2), "gesamt": round(t_end - t0, 2)}
    print_report(res, write)
    out = RESULTS / "tuning_baseline.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    write(f"\nLaufzeit gesamt {res['laufzeit_sekunden']['gesamt']} s {res['laufzeit_sekunden']}")
    write(f"Geschrieben: {out.relative_to(ROOT)} ({out.stat().st_size / 1024:.0f} KB)")
    assert (ROOT / "data" / "elo_model.pkl").stat().st_mtime_ns == pickle_before
    return 0


if __name__ == "__main__":
    sys.exit(main())
