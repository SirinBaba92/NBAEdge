"""
Kontrolle des Live-Modells (engine/live_model.py) an echten Viertelstaenden (Baustein 2). Nur lesend: data/cache, keine API-Calls, keine Produktivdatei geaendert.
Schreibt nur analysis/results/live_model_check.json (klein).

Fuer jedes Regular-Season-Spiel 2017-2025 (Vorab-Prognose wie die Engine: Marge = Rating-Differenz / 50, Total = Off/Def-EMA) wird an den Viertelgrenzen (nach Q1, Q2 = Halbzeit, Q3)
die Wahrscheinlichkeit gerechnet, dass (a) Spread Heim bei der Linie = gerundete Vorab-Marge, (b) Total Over bei der gerundeten Vorab-Summe, (c) Team Total Heim Over bei den gerundeten
Vorab-Punkten eintritt, und mit dem Ausgang (Endstand incl. Verlaengerung) verglichen: Brier-Wert und Kalibrierungs-Steigung (1,0 = ideal, <1 = zu sicher) fuer verschiedene Streuungen.
Aufruf:  venv/bin/python analysis/live_model_check.py
"""
import json, sys, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import RESULTS, load_games  # noqa: E402
import replica_tunable as rt  # noqa: E402
from engine import game_clock as gc, live_model as lm  # noqa: E402

CHECK = {"nach_Q1": 720.0, "Halbzeit": 1440.0, "nach_Q3": 2160.0}
SIGMAS = {"vorab_10_5_18_12_5": (10.5, 18.0, 12.5), "spread_12": (12.0, 18.0, 12.5), "spread_13_5": (13.5, 18.0, 12.5), "alle_gemessen_13_9_18_8_11_7": (13.9, 18.8, 11.7)}


def rh(x):
    return np.floor(np.asarray(x) * 2 + 0.5) / 2


def main():
    games = load_games(2015, 2025)
    r, _, _, _ = rt.run(games)
    mu_m, mu_s = r["diff"] / 50.0, r["total_pred"]
    rows = []
    for i, g in enumerate(games):
        if g.get("postseason") or g["season"] < 2017 or None in [g.get(f"home_q{k}") for k in (1, 2, 3, 4)] or None in [g.get(f"visitor_q{k}") for k in (1, 2, 3, 4)]:
            continue
        hq = [int(g[f"home_q{k}"]) for k in (1, 2, 3, 4)]
        vq = [int(g[f"visitor_q{k}"]) for k in (1, 2, 3, 4)]
        rows.append((i, hq, vq, int(g["home_team_score"]), int(g["visitor_team_score"])))
    out = {"n_spiele": len(rows)}
    for sname, (sm, st, sh) in SIGMAS.items():
        res = {}
        for cname, t in CHECK.items():
            k = int(t // 720)
            clock = gc.build_game_clock(2, "", k, "PT00M00.00S") if k != 2 else gc.build_game_clock(2, "Halftime", 2, "")
            P, Y = {"spread": [], "total": [], "team": []}, {"spread": [], "total": [], "team": []}
            for i, hq, vq, hf, af in rows:
                ms, mm = float(mu_s[i]), float(mu_m[i])
                mh = (ms + mm) / 2
                an = lm.Anchor(ms, mm, mh, ms - mh, 0.5, sigma_spread=sm, sigma_total=st, sigma_team=sh)
                proj = lm.project(an, clock, sum(hq[:k]), sum(vq[:k]))
                ls, lt, lh = float(rh(-mm)), float(rh(ms)), float(rh(mh))
                P["spread"].append(proj.p_spread("home", ls)); Y["spread"].append(float((hf - af) + ls > 0))
                P["total"].append(proj.p_over_total(lt)); Y["total"].append(float(hf + af > lt))
                P["team"].append(proj.p_over_team("home", lh)); Y["team"].append(float(hf > lh))
            res[cname] = {}
            for mk in P:
                p, y = np.clip(np.array(P[mk]), 1e-4, 1 - 1e-4), np.array(Y[mk])
                x = np.log(p / (1 - p))
                slope = float(np.cov(x, y)[0, 1] / np.var(x, ddof=1)) if np.var(x) > 0 else None     # lineare Kalibrierung (1 = ideal)
                res[cname][mk] = {"brier": float(np.mean((p - y) ** 2)), "mittel_p": float(p.mean()), "mittel_ausgang": float(y.mean()), "mittel_abweichung_p_nahe_0_5": float(np.mean(np.abs(p - 0.5) < 0.1)),
                                  "steigung_linear_p_auf_ausgang": float(np.cov(p, y)[0, 1] / np.var(p, ddof=1))}
        out[sname] = res
    p = RESULTS / "live_model_check.json"
    p.write_text(json.dumps(out, indent=1))
    for sname in SIGMAS:
        print(sname)
        for cname in CHECK:
            print("  ", cname, {mk: (round(v["brier"], 4), round(v["steigung_linear_p_auf_ausgang"], 3)) for mk, v in out[sname][cname].items()})
    print("geschrieben:", p, f"({p.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
