"""
Kalibrierung der Konstanten fuer engine/live_model.py (Baustein 2). Nur lesend: data/cache (Viertelpunkte) und ~/NBAEdge_live_history (Boxscore/Play-by-Play).
Keine API-Calls, keine Produktivdatei wird veraendert. Schreibt nur analysis/results/live_calibration.json (klein).

Aufruf (aus dem Projektordner):  venv/bin/python analysis/live_calibration.py

Teil A (Viertelpunkte, Regular Season 2017-2025, Vorab-Prognose wie die Engine: Marge = Rating-Differenz / ELO_TO_SPREAD_FACTOR, Total = Off/Def-EMA):
  1. Anteil der Punkte, der bis Viertel 1/2/3 faellt (Zeitverlauf des Erwartungswerts) und Anteil der Heimvorteil-Marge (Regression auf die Vorab-Marge).
  2. Streuung des Restes: Var(Rest-Abweichung) ~ r^alpha mit r = Restzeit-Anteil, fuer Total, Marge und Heim-Punkte. Prueft die Annahme "Vorab-Sigma mal Wurzel der Restzeit".
  3. Vorab-Streuung (Endstand incl. Verlaengerung) gegen die Konstanten in line_probabilities (Spread 10,5; Total 18,0; Team Total 12,5).
  4. Wahrscheinlichkeit eines Gleichstands nach 4 Vierteln (empirisch gegen Normalverteilung mit Vorab-Sigma) und Punkte einer Verlaengerung.
Teil B (Tempo aus Ballbesitzen, Spiele aus ~/NBAEdge_live_history): Liga-Pace P0, Streuung zwischen den Spielen und innerhalb eines Spiels (Viertel),
  daraus der Pseudo-Besitz K = (Besitze je Viertel) * Var_innerhalb / Var_zwischen (Bayes-Gewicht n / (n + K)).
"""
import gzip
import json
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import ROOT, RESULTS, load_games  # noqa: E402
import replica_tunable as rt  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR  # noqa: E402

SIGMA_SPREAD, SIGMA_TOTAL, SIGMA_TEAM = 10.5, 18.0, 12.5
FIRST_TEST_SEASON = 2017            # 2015/16 als Einlaufzeit fuer Off/Def und Ratings


def _q(g, side):
    return [g.get(f"{side}_q{i}") for i in (1, 2, 3, 4)]


def part_a():
    games = load_games(2015, 2025)
    r, _, _, _ = rt.run(games)
    mu_m = r["diff"] / ELO_TO_SPREAD_FACTOR
    mu_s = r["total_pred"]
    rows = []
    for i, g in enumerate(games):
        if g.get("postseason") or g["season"] < FIRST_TEST_SEASON:
            continue
        hq, vq = _q(g, "home"), _q(g, "visitor")
        if None in hq or None in vq:
            continue
        ot_h = sum(int(g.get(f"home_ot{k}") or 0) for k in (1, 2, 3))
        ot_v = sum(int(g.get(f"visitor_ot{k}") or 0) for k in (1, 2, 3))
        rows.append((i, hq, vq, ot_h, ot_v))
    idx = np.array([x[0] for x in rows])
    H = np.array([x[1] for x in rows], float)           # n x 4 Heim-Viertelpunkte
    V = np.array([x[2] for x in rows], float)
    OTH = np.array([x[3] for x in rows], float)
    OTV = np.array([x[4] for x in rows], float)
    mS, mM = mu_s[idx], mu_m[idx]
    n = len(idx)
    S_q, M_q = H + V, H - V
    S_cum, M_cum = np.cumsum(S_q, axis=1), np.cumsum(M_q, axis=1)
    S_reg, M_reg = S_cum[:, 3], M_cum[:, 3]
    S_fin, M_fin = S_reg + OTH + OTV, M_reg + OTH - OTV
    H_reg, H_fin = H.sum(axis=1), H.sum(axis=1) + OTH
    mH = (mS + mM) / 2
    out = {"n_spiele": int(n), "saisons": f"{FIRST_TEST_SEASON}-2025 (Regular Season)"}

    # 3. Vorab-Streuung des Endstands (incl. Verlaengerung), nach Abzug des mittleren Fehlers
    out["vorab_streuung"] = {
        "spread_sd": float(np.std(M_fin - mM)), "spread_konstante": SIGMA_SPREAD,
        "total_sd": float(np.std(S_fin - mS)), "total_konstante": SIGMA_TOTAL,
        "team_total_sd": float(np.std(H_fin - mH)), "team_total_konstante": SIGMA_TEAM,
        "mittlerer_fehler": {"spread": float(np.mean(M_fin - mM)), "total": float(np.mean(S_fin - mS))},
    }

    # 1. Zeitverlauf: Anteil der Punkte bis Viertel k; Anteil der Marge (Regression auf die Vorab-Marge, so wie der Heimvorteil wirkt)
    share_s = (S_cum.mean(axis=0) / S_reg.mean()).tolist()
    slope = lambda y, x: float(np.cov(y, x)[0, 1] / np.var(x, ddof=1))
    slopes = [slope(M_cum[:, k], mM) for k in range(4)]
    share_m = [s / slopes[3] for s in slopes]
    out["anteil_bis_viertel"] = {"punkte_total": share_s, "marge_regression_auf_vorab": share_m, "steigung_marge_ende_reg": slopes[3],
                                 "hinweis": "Anteil nach Viertel 1, 2, 3, 4; Total: Mittelwert der Punkte, Marge: Steigung der Marge bis dahin auf die Vorab-Marge geteilt durch die Steigung am Ende"}
    out["regulaere_punkte"] = {"mittel_total": float(S_reg.mean()), "mittel_vorab_total": float(mS.mean()),
                              "ot_punkte_je_spiel_mittel": float((OTH + OTV).mean()), "anteil_spiele_mit_ot": float(((OTH + OTV) > 0).mean())}
    # Mittelwerte der regulaeren Zeit (ohne OT) als Bezug fuer die Reste
    b_s = float(np.mean(S_reg - mS))
    out["regulaer_gegen_vorab_total"] = b_s

    # 2. Streuung des Rests: R_k = Rest-Punkte - (1 - Anteil_k) * (Vorab + mittlerer Fehler); Var(R_k) / Var(R_0) gegen r = Restzeit-Anteil
    r_time = [0.75, 0.5, 0.25]
    res = {}
    for name, X_reg, X_cum, mu, share in (
        ("total", S_reg, S_cum, mS + b_s, share_s),
        ("marge", M_reg, M_cum, mM * slopes[3], share_m),
        ("heim_punkte", H_reg, np.cumsum(H, axis=1), (mH + b_s / 2), [h / H.sum(axis=1).mean() for h in np.cumsum(H, axis=1).mean(axis=0)]),
    ):
        v0 = float(np.var(X_reg - mu))
        rows_ = []
        for k in range(3):
            rest = X_reg - X_cum[:, k]
            Rk = rest - (1 - share[k]) * mu
            vk = float(np.var(Rk))
            rows_.append({"nach_viertel": k + 1, "r_zeit": r_time[k], "r_punkte_anteil": float(1 - share[k]), "var_verhaeltnis": vk / v0,
                          "sd": float(np.sqrt(vk)), "sd_verhaeltnis_zu_wurzel_r": float(np.sqrt(vk / v0) / np.sqrt(r_time[k]))})
        # Anpassung var_verhaeltnis = r^alpha (Kleinste Quadrate im Log, ueber die drei Punkte)
        ratios = np.array([x["var_verhaeltnis"] for x in rows_])
        alpha = float(np.sum(np.log(r_time) * np.log(ratios)) / np.sum(np.log(r_time) ** 2))
        res[name] = {"sd_vorab_regulaer": float(np.sqrt(v0)), "punkte": rows_, "alpha": alpha}
    out["streuung_rest"] = res

    # 4. Gleichstand nach 4 Vierteln: empirisch gegen Normalverteilung (Vorab-Marge, Streuung = Spread-Konstante), diskrete Marge
    from scipy.special import ndtr
    mm = mM * slopes[3] + float(np.mean(M_reg - mM * slopes[3]))
    pt_model = float(np.mean(ndtr((0.5 - mm) / SIGMA_SPREAD) - ndtr((-0.5 - mm) / SIGMA_SPREAD)))
    sd_reg = float(np.std(M_reg - mM * slopes[3]))
    pt_model_sd_reg = float(np.mean(ndtr((0.5 - mm) / sd_reg) - ndtr((-0.5 - mm) / sd_reg)))
    out["gleichstand_nach_q4"] = {"empirisch": float(np.mean(M_reg == 0)), "normal_mit_sigma_10_5": pt_model, "normal_mit_regulaerer_sd": pt_model_sd_reg, "regulaere_sd_marge": sd_reg}
    ot = (OTH + OTV)[(OTH + OTV) > 0]
    first_ot = np.array([int(g.get("home_ot1") or 0) + int(g.get("visitor_ot1") or 0) for g in [games[i] for i in idx]], float)
    first_ot = first_ot[first_ot > 0]
    out["verlaengerung"] = {"punkte_beide_teams_erste_ot_mittel": float(first_ot.mean()), "punkte_beide_teams_ot_gesamt_mittel": float(ot.mean()),
                            "erwartet_nach_vorab_total_mal_5_48": float(np.mean(mS) * 5 / 48),
                            "anteil_ot_mit_zweiter_ot": float(np.mean([(int(games[i].get("home_ot2") or 0) + int(games[i].get("visitor_ot2") or 0)) > 0 for i in idx if (int(games[i].get("home_ot1") or 0) + int(games[i].get("visitor_ot1") or 0)) > 0]))}
    return out


# ----------------------------------------------------------------------------------------------- Teil B: Tempo
def possessions(box_team_stats):
    s = box_team_stats
    return s["fieldGoalsAttempted"] + 0.44 * s["freeThrowsAttempted"] - s["reboundsOffensive"] + s["turnoversTotal"]


def quarter_possessions(actions):
    """Besitze je Team und Viertel aus dem Play-by-Play (FGA + 0,44 FTA - OREB + TOV), nur reguläre Viertel."""
    per = {}
    for a in actions:
        p = int(a.get("period") or 0)
        if p < 1 or p > 4 or not a.get("teamTricode"):
            continue
        d = per.setdefault((p, a["teamTricode"]), 0.0)
        t, st = a.get("actionType"), str(a.get("subType") or "").lower()
        if t in ("2pt", "3pt"):
            d += 1
        elif t == "freethrow":
            d += 0.44
        elif t == "rebound" and st == "offensive":
            d -= 1
        elif t == "turnover":
            d += 1
        per[(p, a["teamTricode"])] = d
    return per


def part_b(root: Path):
    games = []
    for gd in sorted(root.glob("*/*/final_box.json.gz")):
        gdir = gd.parent
        if not (gdir / "final_pbp.json.gz").exists():
            continue
        box = json.loads(gzip.decompress(gd.read_bytes()))["game"]
        acts = json.loads(gzip.decompress((gdir / "final_pbp.json.gz").read_bytes()))["game"]["actions"]
        per = quarter_possessions(acts)
        teams = sorted({k[1] for k in per})
        if len(teams) != 2:
            continue
        q = np.array([[(per.get((p, t), 0.0)) for t in teams] for p in (1, 2, 3, 4)])     # 4 x 2
        qp = q.mean(axis=1)                                                              # Besitze je Team im Viertel (Mittel beider Teams)
        ot = max(int(box["homeTeam"]["periods"][-1]["period"]) - 4, 0) if box["homeTeam"].get("periods") else 0
        total_min = 48 + 5 * ot
        full = (possession_team := np.mean([possessions(box["homeTeam"]["statistics"]), possessions(box["awayTeam"]["statistics"])]))
        games.append({"id": gdir.name, "pace_box_je_48": float(full * 48 / total_min), "ot": ot, "q_poss": qp.tolist(), "q_pace": (qp * 4).tolist()})
    if len(games) < 3:
        return {"n_spiele": len(games), "hinweis": "zu wenige Spiele fuer eine Schaetzung"}
    pace = np.array([g["pace_box_je_48"] for g in games])
    qp = np.array([g["q_poss"] for g in games])            # n x 4
    qpace = qp * 4
    n = len(games)
    grand = qpace.mean()
    game_means = qpace.mean(axis=1)
    msw = float(np.sum((qpace - game_means[:, None]) ** 2) / (n * 3))              # Varianz innerhalb der Spiele (Viertel-Tempo)
    msb = float(4 * np.sum((game_means - grand) ** 2) / (n - 1))
    var_between = max((msb - msw) / 4, 0.0)                                         # Varianz der wahren Spieltempi
    nq = float(qp.mean())
    k = nq * msw / var_between if var_between > 0 else None
    return {"n_spiele": n, "pace_je_48_mittel": float(pace.mean()), "pace_je_48_sd_zwischen_spielen": float(pace.std(ddof=1)), "pace_je_48_se": float(pace.std(ddof=1) / np.sqrt(n)),
            "viertel_pace_var_innerhalb": msw, "viertel_pace_var_zwischen_geschaetzt": var_between, "besitze_je_team_und_viertel": nq,
            "K_aus_daten": k, "pace_boxscore_je_spiel": [round(float(x), 1) for x in pace]}


def main():
    out = {"teil_a_viertelpunkte": part_a()}
    root = Path.home() / "NBAEdge_live_history"
    out["teil_b_tempo"] = part_b(root) if root.exists() else {"hinweis": "kein ~/NBAEdge_live_history"}
    p = RESULTS / "live_calibration.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out, indent=1, ensure_ascii=False))
    print("\ngeschrieben:", p, f"({p.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
