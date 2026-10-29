"""Test fuer analysis/export_forecasts.py an einem kleinen kuenstlichen Beispiel (Verbindung ueber Spieler-ID und Datum, Spaltenreihenfolge, Teampunkte-Pruefung). Ohne Netz, nur Temp-Ordner.
Aufruf aus dem Projektordner: venv/bin/python tests/test_export_forecasts.py"""
import csv, gzip, os, sys, tempfile
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
from analysis import export_forecasts as ef

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

# Spielerzeilen (lokal): Spiel 1 am 2024-10-22 HHH (Heim) gegen AAA, Spiel 2 am 2024-10-23 AAA gegen BBB
loc = [{"game_id": "0022400001", "date": "2024-10-22", "person_id": 1, "team": "HHH", "opponent": "AAA", "minutes": 30.0, "points": 20},
       {"game_id": "0022400001", "date": "2024-10-22", "person_id": 2, "team": "HHH", "opponent": "AAA", "minutes": 18.0, "points": 8},
       {"game_id": "0022400001", "date": "2024-10-22", "person_id": 11, "team": "AAA", "opponent": "HHH", "minutes": 34.0, "points": 25},
       {"game_id": "0022400002", "date": "2024-10-23", "person_id": 11, "team": "AAA", "opponent": "BBB", "minutes": 20.0, "points": 9}]
idx = ef.index_local(loc)
check("Index: Spiel ueber (Datum, beide Teams), Teampunkte = Summe der Spielerpunkte (HHH 28, AAA 25 + 9 im zweiten Spiel getrennt)", idx["games"][(20241022, frozenset(("HHH", "AAA")))] == "0022400001"
      and idx["team_pts"][("0022400001", "HHH")] == 28 and idx["team_pts"][("0022400001", "AAA")] == 25 and idx["team_pts"][("0022400002", "AAA")] == 9)
arr = {"pid": np.array([1, 2, 11, 99]), "date": np.array([20241022, 20241022, 20241022, 20241022]), "min": np.array([30.0, 18.0, 34.0, 5.0]), "pts": np.array([20, 8, 25, 2]),
       "emin_A": np.array([29.0, 17.5, 33.0, 6.0]), "epts_A": np.array([18.5, 7.0, 24.0, 2.5]), "emin_B": np.array([30.0, np.nan, 34.0, 6.0]), "epts_B": np.array([19.0, np.nan, 25.0, 2.0]),
       "tspread": np.array([3.5, 3.5, -3.5, 3.5]), "in_rot": np.array([1, 0, 1, 0])}
rows, c = ef.players_table(arr, idx)
check("Spaltenreihenfolge der Spieler-CSV: spiel_id, datum, team, spieler_id, Ist, erwartet roh, erwartet Teamabgleich, tspread, Rotation", ef.PLAYER_COLS == ["spiel_id", "datum", "team", "spieler_id", "minuten_ist", "punkte_ist", "minuten_erw_roh", "punkte_erw_roh",
      "minuten_erw_teamabgleich", "punkte_erw_teamabgleich", "tspread", "rotation"])
check("Verbindung ueber (Spieler-ID, Datum): 3 von 4 Zeilen geloest (Spieler 99 ohne lokale Zeile), Spiel-ID, Datum und Team uebernommen", (c["zeilen"], c["geloest"]) == (4, 3) and rows[0][:4] == ["0022400001", "2024-10-22", "HHH", 1] and rows[2][:4] == ["0022400001", "2024-10-22", "AAA", 11])
check("Werte in der Reihenfolge: Ist 30/20, roh 29/18.5, Teamabgleich 30/19, tspread 3.5, Rotation 1; NaN (Spieler 2, Teamabgleich) bleibt leer", rows[0][4:] == ["30", "20", "29", "18.5", "30", "19", "3.5", 1] and rows[1][8] == "" and rows[1][9] == "" and len(rows[0]) == len(ef.PLAYER_COLS), str(rows[0]))
check("Ist-Werte stimmen mit den lokalen Spielerdaten ueberein (keine Abweichung gezaehlt)", c["min_abweichung"] == 0 and c["pkt_abweichung"] == 0)
arr2 = dict(arr); arr2["pts"] = np.array([21, 8, 25, 2])
check("Abweichung der Ist-Punkte wird gezaehlt", ef.players_table(arr2, idx)[1]["pkt_abweichung"] == 1)

# Teams: zwei BDL-Spiele + Playoffspiel + andere Saison + ein Spiel ohne lokale Spielerzeilen
games = [{"date": "2024-10-22T00:00:00.000Z", "home_team": {"abbreviation": "HHH"}, "visitor_team": {"abbreviation": "AAA"}},
         {"date": "2024-10-25", "home_team": {"abbreviation": "XXX"}, "visitor_team": {"abbreviation": "YYY"}},
         {"date": "2025-04-20", "home_team": {"abbreviation": "HHH"}, "visitor_team": {"abbreviation": "AAA"}},
         {"date": "2023-12-01", "home_team": {"abbreviation": "HHH"}, "visitor_team": {"abbreviation": "AAA"}}]
res = {"season": np.array([2024, 2024, 2024, 2023]), "post": np.array([0, 0, 1, 0]), "diff": np.array([175.0, -50.0, 0.0, 0.0]), "total_pred": np.array([226.0, 220.0, 0.0, 0.0]),
       "margin": np.array([3.0, -4.0, 0.0, 0.0]), "total": np.array([53.0, 200.0, 0.0, 0.0])}
trows, tc, info = ef.teams_table(games, res, 2024, idx, 50.0)
check("Spaltenreihenfolge der Team-CSV: spiel_id, datum, heim, gast, Abstand, Total, Teampunkte Heim/Gast erwartet, Teampunkte Heim/Gast tatsaechlich", ef.TEAM_COLS == ["spiel_id", "datum", "heim", "gast", "abstand_erw", "total_erw", "punkte_erw_heim", "punkte_erw_gast", "punkte_ist_heim", "punkte_ist_gast"])
check("nur Regular Season der Saison (2 Spiele), eines verbunden, eines ohne Spiel-ID (leer)", (tc["spiele"], tc["verbunden"], tc["ohne_spiel_id"]) == (2, 1, 1) and trows[0][0] == "0022400001" and trows[1][0] == "", str(trows))
check("Abstand = Elo-Differenz / 50 (3,5), Total 226, erwartete Teampunkte (226 +- 3,5) / 2 = 114,75 / 111,25, tatsaechliche Punkte aus Total und Abstand ((53 +- 3) / 2)", trows[0][4:] == ["3.5", "226", "114.75", "111.25", "28", "25"], str(trows[0]))
check("Plausibilitaet: Teampunkte (28 / 25) gleich der Summe der Spielerpunkte, keine Abweichung", ef.check_team_points(trows, idx) == [])
bad = [list(trows[0])]; bad[0][8] = "29"
check("Abweichung (Spielstand 29 statt Summe 28) wird genannt", len(ef.check_team_points(bad, idx)) == 1 and "HHH" in ef.check_team_points(bad, idx)[0])
d = ef.tspread_diffs(rows, info)
check("tspread aus Sicht des Spielerteams: Heim +3,5, Gast -3,5 gegen den Abstand des Replays (Abweichung 0)", d and max(d) < 1e-9 and len(d) == 3, str(d))
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "x" / "forecast_players_2024-25.csv.gz"
    ef.write_csv(p, ef.PLAYER_COLS, rows)
    back = list(csv.reader(gzip.open(p, "rt", encoding="utf-8")))
    check("CSV (gz) geschrieben und gelesen: Kopfzeile in der festgelegten Reihenfolge, 3 Zeilen, keine Temp-Datei uebrig", back[0] == ef.PLAYER_COLS and len(back) == 4 and back[1][3] == "1" and not list(p.parent.glob("*.tmp")))
check("fnum: ganze Zahlen ohne Nachkomma, NaN/None leer", ef.fnum(30.0) == "30" and ef.fnum(float("nan")) == "" and ef.fnum(None) == "" and ef.fnum(1 / 3) == "0.3333")
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
