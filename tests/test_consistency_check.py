"""Test fuer analysis/consistency_check.py an einem kleinen kuenstlichen Beispiel (4 Spiele, 2 Spieler je Team, ein Spiel mit Verlaengerung). Erwartete Werte werden hier unabhaengig mit numpy
bzw. einer Schleife gerechnet. Ohne Netz, nur Temp-Ordner. Aufruf aus dem Projektordner: venv/bin/python tests/test_consistency_check.py"""
import gzip, itertools, os, sys, tempfile
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import consistency_check as cc

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
near = lambda a, b, tol=1e-9: abs(a - b) < tol

IDS = ["G1", "G2", "G3", "G4"]
home_act = [100, 110, 90, 120]; home_exp = [100.0] * 4                      # Teamfehler Heim: 0, 10, -10, 20
away_act = [90, 95, 85, 100]; away_exp = [90.0] * 4                         # Teamfehler Gast: 0, 5, -5, 10
home_p = [(20, 20), (25, 20), (15, 20), (30, 20)]                           # tatsaechliche Spielerpunkte Heim (Summe 40, 45, 35, 50); erwartet je 20 + 20 (A), B = 21 + 21
away_p = [(20, 15), (22, 18), (14, 16), (26, 18)]                           # Summe 35, 40, 30, 44 gegen A 18 + 18 = 36
teams = pd.DataFrame({"spiel_id": IDS, "datum": "2024-10-22", "heim": "HHH", "gast": "AAA", "abstand_erw": 0.0, "total_erw": 190.0, "punkte_erw_heim": home_exp, "punkte_erw_gast": away_exp,
                      "punkte_ist_heim": home_act, "punkte_ist_gast": away_act})
rows = []
for k, gid in enumerate(IDS):
    for team, acts, a_exp, b_exp, mins in (("HHH", home_p[k], 20.0, 21.0, (140, 125) if k == 3 else (40, 40)), ("AAA", away_p[k], 18.0, 19.0, (140, 125) if k == 3 else (38, 36))):
        for j in range(2):
            rows.append({"spiel_id": gid, "datum": "2024-10-22", "team": team, "spieler_id": 10 * (team == "AAA") + j, "minuten_ist": mins[j], "punkte_ist": acts[j], "minuten_erw_roh": 20.0,
                         "punkte_erw_roh": a_exp, "minuten_erw_teamabgleich": 20.0, "punkte_erw_teamabgleich": b_exp, "tspread": 0.0, "rotation": 1})
players = pd.DataFrame(rows)
g, p, info = cc.team_games(players, teams, "2024-25")
check("Team-Spiel-Tabelle: 8 Zeilen (4 Spiele x 2 Seiten), Summen A = 40 / 36, B = 42 / 38, Spielerpunkte, Teampunkte, Verlaengerung nur in G4", len(g) == 8 and set(g.loc[g["seite"] == "heim", "summe_a"]) == {40.0} and set(g.loc[g["seite"] == "gast", "summe_a"]) == {36.0}
      and set(g.loc[g["seite"] == "heim", "summe_b"]) == {42.0} and g[(g["spiel_id"] == "G2") & (g["seite"] == "heim")]["akt_spieler"].iloc[0] == 45 and g[(g["spiel_id"] == "G2") & (g["seite"] == "heim")]["akt_team"].iloc[0] == 110
      and list(g.loc[g["ot"], "spiel_id"].unique()) == ["G4"] and info == {"spieler_zeilen_ohne_teamspiel": 0, "team_spiele": 8, "spiele_ot": 1}, str(info))
res = cc.group_metrics(g, p)
h = res["seite"]["heim"]
cov = np.array(home_p).sum(axis=1) / np.array(home_act)
check("1. Abdeckung Heim: Mittel und Streuung der Anteile 40/100, 45/110, 35/90, 50/120", near(h["abdeckung_mittel"], cov.mean()) and near(h["abdeckung_sd"], cov.std(ddof=1)), f"{h['abdeckung_mittel']:.4f}")
sum_a = np.full(4, 40.0); act_cov = np.array(home_p).sum(axis=1)
d_a = sum_a - np.array(home_exp) * cov.mean()
check("2a. A gegen erwartete Teampunkte x mittlere Abdeckung: Mittel, Streuung (konstant = 0), Anteil > 5 (40 - 100 x 0,4 = ~0 Punkte)", near(h["a_gegen_team"]["mittel"], d_a.mean()) and near(h["a_gegen_team"]["sd"], d_a.std(ddof=1)) and h["a_gegen_team"]["anteil_gt5"] == float(np.mean(np.abs(d_a) > 5)))
d_i = sum_a - act_cov
check("2b. A gegen tatsaechliche Punkte derselben Spieler: Unterschiede 0, -5, 5, -10 -> Mittel -2,5, Streuung, Anteil > 5 = 25 % (nur -10)", near(h["a_gegen_ist"]["mittel"], -2.5) and near(h["a_gegen_ist"]["sd"], d_i.std(ddof=1)) and near(h["a_gegen_ist"]["anteil_gt5"], 0.25) and list(d_i) == [0, -5, 5, -10])
d_b = np.full(4, 42.0) - act_cov
check("2b. B (Teamabgleich) gegen tatsaechliche Punkte: Mittel +/-, Anteil > 5", near(h["b_gegen_ist"]["mittel"], d_b.mean()) and near(h["b_gegen_ist"]["anteil_gt5"], float(np.mean(np.abs(d_b) > 5))))
check("4a. Korrelation Teamfehler (0, 10, -10, 20) mit Summenfehler (0, 5, -5, 10) = 1 (Heim); Gast gegen eigene Zahlen", near(h["korr_team_summe_a"], 1.0)
      and near(res["seite"]["gast"]["korr_team_summe_a"], np.corrcoef(np.array(away_act) - 90.0, np.array(away_p).sum(axis=1) - 36.0)[0, 1]))
check("4c. Korrelation Teamfehler Heim (0, 10, -10, 20) und Gast (0, 5, -5, 10) = 1", near(res["korr_heim_gast"], 1.0))
# 4b unabhaengig: alle Paare je Team und Spiel, standardisierte Fehler
side_rows = []
for k in range(4):
    side_rows.append([home_p[0][0] * 0 + home_p[k][j] - 20.0 for j in range(2)])
z_src = np.array([e for r in side_rows for e in r])
z = (z_src - z_src.mean()) / z_src.std(ddof=0)
exp_pc = np.mean([z[2 * k] * z[2 * k + 1] for k in range(4)])
check("4b. paarweise Korrelation (gepoolt, 1 Paar je Team und Spiel, standardisierte Roh-Fehler)", near(h["paarkorr"], exp_pc) and h["paare"] == 4, f"{h['paarkorr']:.4f} gegen {exp_pc:.4f}")
a, b = cc.pair_corr(p[p["seite"] == "heim"])
check("Spieler unter 15 erwarteten Minuten zaehlen nicht (alle auf 10 gesetzt: keine Paare)", cc.pair_corr(p.assign(minuten_erw_roh=10.0))[1] == 0 and np.isnan(cc.pair_corr(p.assign(minuten_erw_roh=10.0))[0]))
# Verlaengerung
ev = cc.evaluate(g, p)
check("Gruppen: alle (4 Spiele), ohne Verlaengerung (3), mit Verlaengerung (1)", ev["alle"]["spiele"] == 4 and ev["ohne Verlaengerung"]["spiele"] == 3 and ev["mit Verlaengerung"]["spiele"] == 1)
check("ohne Verlaengerung (G1-G3): Abdeckung nur aus diesen Spielen; 4a mit 3 Spielen = 1", near(ev["ohne Verlaengerung"]["seite"]["heim"]["abdeckung_mittel"], cov[:3].mean()) and near(ev["ohne Verlaengerung"]["seite"]["heim"]["korr_team_summe_a"], 1.0))
check("mit Verlaengerung: ein Spiel, Korrelationen nicht berechenbar (-), kein Absturz", np.isnan(ev["mit Verlaengerung"]["korr_heim_gast"]) and np.isnan(ev["mit Verlaengerung"]["seite"]["heim"]["korr_team_summe_a"]))
# Lauf mit Dateien: zwei Saisons mit denselben Spiel-IDs, Bericht
with tempfile.TemporaryDirectory() as td:
    d = Path(td) / "derived"; d.mkdir()
    for s in ("2023-24", "2024-25", "2025-26"):
        with gzip.open(d / f"forecast_players_{s}.csv.gz", "wt", encoding="utf-8") as f:
            players.to_csv(f, index=False)
        with gzip.open(d / f"forecast_teams_{s}.csv.gz", "wt", encoding="utf-8") as f:
            teams.to_csv(f, index=False)
    text = cc.run(Path(td))
    check("Bericht: je Saison und gesamt, Heim und Gast, Gruppen alle / ohne / mit Verlaengerung, Hinweis zum fehlenden Teamabgleich-Faktor", all(w in text for w in ("=== 2023-24 ===", "=== 2025-26 ===", "=== gesamt ===", "ohne Verlaengerung", "mit Verlaengerung", "Heim", "Gast", "1. Abdeckung", "4b.", "4c.", "Faktor: steht nicht in den Dateien")), text[:200])
    check("gesamt: Spiele mehrerer Saisons mit gleichen Spiel-IDs werden nicht vermischt (3 x 4 Spiele = 12, nicht 4)", "Team-Spiele: Heim 12, Gast 12 (Spiele mit beiden Seiten: 12)" in text)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
