"""Test fuer analysis/garbage_time.py an kleinen kuenstlichen Spielen (Abstand waechst, ein Ausreisser, eine Verlaengerung). Ohne Netz, nur Temp-Ordner.
Aufruf aus dem Projektordner: venv/bin/python tests/test_garbage_time.py"""
import csv, gzip, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import garbage_time as gt

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
near = lambda a, b, tol=1e-6: abs(a - b) < tol

# ---- Spiel 1: Heim fuehrt, Abstand waechst, Ausreisser (21 -> 17 -> 22), Ende +25 (keine Verlaengerung)
TL1 = [(0, 0, 0), (1000, 40, 30), (1500, 50, 34), (1700, 63, 42), (1800, 60, 43), (2000, 66, 44), (2300, 80, 56), (2600, 85, 60)]
L1 = 2880.0
check("G1: Abstand dauerhaft >= 20 erst ab 2000 s (der Ausreisser 21 bei 1700 s zaehlt nicht), bis zum Spielende, Heim fuehrt", gt.gt_permanent(TL1, L1, 20) == [(2000, 2880.0, "home")], str(gt.gt_permanent(TL1, L1, 20)))
check("G2: dauerhaft >= 15 ab 1500 s (Abstand 16, nie darunter)", gt.gt_permanent(TL1, L1, 15) == [(1500, 2880.0, "home")], str(gt.gt_permanent(TL1, L1, 15)))
check("G3: letzte 6 Minuten von Viertel 4 (2520 bis 2880 s) mit Abstand >= 20: ein Abschnitt, 6 Minuten", gt.gt_window(TL1, L1, 20) == [(2520, 2880, "home")], str(gt.gt_window(TL1, L1, 20)))
check("vor Periode 3 erreicht und dauerhaft: Beginn erst bei 1440 s (Periodenbeginn)", gt.gt_permanent([(0, 0, 0), (1000, 40, 18), (2000, 60, 38)], 2880.0, 20) == [(1440, 2880.0, "home")])
check("Gast fuehrt: Fuehrungsseite 'away'", gt.gt_permanent([(0, 0, 0), (1600, 20, 45)], 2880.0, 20) == [(1600, 2880.0, "away")])
check("Spielende unter dem Schwellenwert: kein G1/G2, auch wenn der Abstand zwischendurch gross war", gt.gt_permanent([(0, 0, 0), (1600, 50, 20), (2700, 60, 55)], 2880.0, 20) == [])

# ---- Spiel 2: mit Verlaengerung (Laenge 3180 s), Abstand 22 bei 2600 s, Aufholjagd, Gleichstand nach Viertel 4, Ende +2
TL2 = [(0, 0, 0), (1000, 40, 30), (2400, 70, 50), (2600, 73, 51), (2800, 75, 65), (2880, 77, 77), (3100, 79, 77)]
L2 = 3180.0
check("Verlaengerung: Spiellaenge 3180 s (2880 + 300)", L2 == gt.bl.game_length(5))
check("G1/G2 mit Aufholjagd und Verlaengerung: keine Garbage Time (Ende +2)", gt.gt_permanent(TL2, L2, 20) == [] and gt.gt_permanent(TL2, L2, 15) == [])
check("G3 unabhaengig vom spaeteren Verlauf: 2520 bis 2800 s mit Abstand >= 20 (Abstand 20, dann 22, zusammengefasst), 280 s", gt.gt_window(TL2, L2, 20) == [(2520, 2800, "home")], str(gt.gt_window(TL2, L2, 20)))
check("G3 endet mit dem 4. Viertel (nichts aus der Verlaengerung)", all(e <= 2880 for _, e, _ in gt.gt_window([(0, 0, 0), (2700, 60, 30)], 3180.0, 20)))

# ---- Summen
def stint(team, nr, start, end, players): return {"team": team, "nr": nr, "start": float(start), "end": float(end), "players": players}
ST1 = [stint("HHH", 1, 0, 1440, [1, 2, 3, 4, 5]), stint("HHH", 2, 1440, 2880, [1, 2, 3, 6, 7]), stint("AAA", 1, 0, 2400, [11, 12, 13, 14, 15]), stint("AAA", 2, 2400, 2880, [11, 12, 16, 17, 18])]
ST2 = [stint("HHH", 1, 0, 3180, [1, 2, 3, 4, 5]), stint("AAA", 1, 0, 3180, [11, 12, 13, 14, 15])]
loc1 = {**{p: 30.0 for p in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15)}, **{p: 10.0 for p in (6, 7, 16, 17, 18)}}
loc2 = {**{p: 25.0 for p in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15)}, **{p: 15.0 for p in (6, 7)}}
info1 = {"timeline": [(float(t), h, a) for t, h, a in TL1], "length": L1, "home_tri": "HHH", "away_tri": "AAA",
         "scoring": [(100.0, 2, 1), (500.0, 1, 2), (2100.0, 1, 3), (2200.0, 11, 2), (2300.0, 6, 2)]}          # Starter 2 (1 Pkt) und 1 (2 Pkt) vor der GT, 1 (3) und 11 (2) in G1, Nicht-Starter 6 (2)
info2 = {"timeline": [(float(t), h, a) for t, h, a in TL2], "length": L2, "home_tri": "HHH", "away_tri": "AAA", "scoring": [(300.0, 1, 2)]}
acc = gt.new_acc()
gt.analyze_game(acc, ST1, info1, loc1)
gt.analyze_game(acc, ST2, info2, loc2)
g1, g2, g3 = acc["G1"], acc["G2"], acc["G3"]
check("Anteil der Spiele mit Garbage Time: G1 1 von 2, G2 1 von 2, G3 2 von 2", (g1["spiele_gt"], g1["spiele"]) == (1, 2) and g2["spiele_gt"] == 1 and (g3["spiele_gt"], g3["spiele"]) == (2, 2))
check("mittlere Dauer in Spielen mit Garbage Time: G1 880 s = 14,67 Min, G2 1380 s = 23 Min, G3 (360 + 280) / 2 s = 5,33 Min", near(g1["dauer_min"] / g1["spiele_gt"], 880 / 60) and near(g2["dauer_min"] / g2["spiele_gt"], 23.0) and near(g3["dauer_min"] / g3["spiele_gt"], 320 / 60))
check("Starter-Minuten in der GT (G1): fuehrend 44 von 192 Min, zurueckliegend 49,33 von 216 Min", near(g1["st_gt_min"]["fuehrend"], 44.0) and near(g1["st_alle_min"]["fuehrend"], 192.0) and near(g1["st_gt_min"]["zurueck"], 400 * 5 / 60 + 480 * 2 / 60) and near(g1["st_alle_min"]["zurueck"], 216.0), str((g1["st_gt_min"], g1["st_alle_min"])))
check("Anteile als Text: fuehrend 22,9 %, zurueckliegend 22,8 %", "fuehrend 22.9 %, zurueckliegend 22.8 %" in "\n".join(gt.text_for("t", acc)))
check("mittlere Minuten eines Starters (lokale Minuten): G1 mit GT 30, ohne GT 25; Nicht-Starter mit GT 10, ohne 15", near(g1["st_mit"]["sum"] / g1["st_mit"]["n"], 30) and near(g1["st_ohne"]["sum"] / g1["st_ohne"]["n"], 25)
      and near(g1["ns_mit"]["sum"] / g1["ns_mit"]["n"], 10) and near(g1["ns_ohne"]["sum"] / g1["ns_ohne"]["n"], 15) and g3["st_ohne"]["n"] == 0)
check("Punkte pro Minute (G1): in der GT 5 Pkt (nur Starter) in 93,33 Starter-Min, ausserhalb 3 Pkt in 314,67 Min; Spiel ohne GT: 2 Pkt in 530 Min; Nicht-Starter zaehlen nicht",
      g1["pkt_in"] == 5 and near(g1["min_in"], 44 + 400 * 5 / 60 + 480 * 2 / 60) and g1["pkt_out"] == 3 and near(g1["min_out"], 408 - g1["min_in"]) and g1["pkt_nogt"] == 2 and near(g1["min_nogt"], 530.0))
check("Spiele ohne Garbage Time kommen nicht in die GT-Minuten ein", g2["st_gt_min"]["fuehrend"] > 0 and acc["G2"]["spiele_gt"] == 1)
tot = gt.merge_acc(acc, acc)
check("Summen verschiedener Saisons lassen sich addieren (gesamt)", tot["G1"]["spiele"] == 4 and tot["G1"]["spiele_gt"] == 2 and near(tot["G1"]["st_gt_min"]["fuehrend"], 88.0) and tot["G1"]["pkt_in"] == 10)
# fehlende lokale Minuten: Stint-Minuten als Ersatz
acc_b = gt.new_acc(); gt.analyze_game(acc_b, ST1, info1, None)
check("ohne lokale Minuten: Minuten aus den Stints (Starter zusammen 408 Min, 10 Starter)", acc_b["G1"]["st_mit"]["n"] == 10 and near(acc_b["G1"]["st_mit"]["sum"], 408.0), str(acc_b["G1"]["st_mit"]))

# ---- Spielstand und Wuerfe aus dem Play-by-Play
def act(n, period, rem, typ, pid=0, tid=0, sh=0, sa=0, res=None, sub=""):
    m, s = divmod(rem, 60)
    return {"orderNumber": n * 10000, "actionNumber": n, "period": period, "clock": f"PT{int(m):02d}M{s:05.2f}S", "actionType": typ, "subType": sub, "personId": pid, "teamId": tid or None,
            "teamTricode": {100: "HHH", 200: "AAA"}.get(tid), "scoreHome": str(sh), "scoreAway": str(sa), "shotResult": res}
acts = [act(1, 1, 720, "period"), act(2, 1, 600, "2pt", 5, 100, 2, 0, "Made"), act(3, 1, 500, "3pt", 11, 200, 2, 3, "Made"), act(4, 1, 400, "3pt", 5, 100, 2, 3, "Missed"), act(5, 1, 300, "freethrow", 5, 100, 3, 3, "Made"),
        act(6, 2, 720, "period", sh=0, sa=0), act(7, 5, 300, "period"), act(8, 5, 100, "2pt", 5, 100, 5, 3, "Made")]
r = gt.timeline_and_scoring(acts)
check("Spielstand nur nach oben (Perioden-Ereignis mit 0:0 setzt nicht zurueck), Heimteam erkannt", r["home_tri"] == "HHH" and r["away_tri"] == "AAA" and r["timeline"] == [(0.0, 0, 0), (120.0, 2, 0), (220.0, 2, 3), (420.0, 3, 3), (2880 + 200.0, 5, 3)], str(r["timeline"]))
check("Wurf- und Freiwurf-Ereignisse mit Punktwert (2, 3, 1, 2), verworfene Wuerfe nicht; Spiellaenge mit Verlaengerung 3180", r["scoring"] == [(120.0, 5, 2), (220.0, 11, 3), (420.0, 5, 1), (3080.0, 5, 2)] and r["length"] == 3180.0, str(r["scoring"]))
# CSV lesen
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "lineups_2023-24.csv.gz"
    with gzip.open(p, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(gt.bl.CSV_HEAD); w.writerow(["0022300001", "HHH", 1, 1, "0", "360", 1, 2, 3, 4, 5, 0, 1, 0, 0, 1, 0]); w.writerow(["0022300001", "AAA", 1, 1, "0", "360", 11, 12, 13, 14, 15, 0, -1, 0, 0, 0, 1])
    d = gt.read_lineups(p)
    check("CSV der Stints gelesen (Team, Stint-Nr, Start, Ende, 5 Spieler)", d["0022300001"][0] == {"team": "HHH", "nr": 1, "start": 0.0, "end": 360.0, "players": [1, 2, 3, 4, 5]} and len(d["0022300001"]) == 2)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
