"""Test fuer analysis/minutes_tail.py an einem kleinen kuenstlichen Beispiel. Ohne Netz, nur Temp-Ordner. Aufruf: venv/bin/python tests/test_minutes_tail.py"""
import csv, gzip, os, sys, tempfile
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import minutes_tail as mt

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

e = list(range(-10, 11))                                    # -10..10, 21 Werte
d = mt.dist_stats(e)
check("Mittel/Median/Schiefe", d["mean"] == 0 and d["median"] == 0 and abs(d["skew"]) < 1e-12)
check("Streuung ddof=1", abs(d["sd"] - np.std(e, ddof=1)) < 1e-12)
check("Quantile", abs(d["q"][25] + 5) < 1e-12 and abs(d["q"][75] - 5) < 1e-12 and abs(d["q"][1] + 9.8) < 1e-9, d["q"][1])
s = mt.shares(e)
check("Anteile", s["<=-5"] == 6 / 21 and s["<=-10"] == 1 / 21 and s[">=+5"] == 6 / 21 and s[">=+10"] == 1 / 21)
nt = mt.normal_tails(e)
sd = np.std(e, ddof=1)
check("Normalvergleich", nt["unter -1.64"] == sum(x < -1.64 * sd for x in e) / 21 and nt["ueber +2.33"] == sum(x > 2.33 * sd for x in e) / 21, nt)
e2 = [0.0] * 98 + [-30.0, 30.0]
nt2 = mt.normal_tails(e2)
check("Normalvergleich mit Ausreissern", nt2["unter -1.64"] == 0.01 and nt2["ueber +2.33"] == 0.01, nt2)
check("Fouls", dict(mt.foul_counts([{"actionType": "foul", "personId": 7}, {"actionType": "foul", "personId": 7}, {"actionType": "foul"}, {"actionType": "2pt", "personId": 7}])) == {7: 2})
check("letzter Abgang", mt.last_exit([{"players": [1, 2], "end": 100.0}, {"players": [1], "end": 500.0}]) == {1: 500.0, 2: 100.0})
c = mt.classify_loss({}, False, 5, 3000.0); check("Ursache Fouls", c["fouls"] and not c["gt"] and not c["frueh"] and not c["rest"])
c = mt.classify_loss({}, False, 2, 1000.0); check("Ursache frueh", c["frueh"] and not c["rest"])
c = mt.classify_loss({}, False, 2, 3000.0); check("Ursache Rest", c["rest"])
c = mt.classify_loss({}, True, 0, 2160.0); check("Abgang genau zu Viertel 4 zaehlt nicht als frueh", c["gt"] and not c["frueh"])

with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    head = ["spiel_id", "datum", "team", "spieler_id", "minuten_ist", "punkte_ist", "minuten_erw_roh", "punkte_erw_roh", "minuten_erw_teamabgleich", "punkte_erw_teamabgleich", "tspread", "rotation"]
    data = [["G1", "x", "AAA", 1, 20, 6, 32, 18, 32, 18, 3.0, 1],      # Teamsumme 20+34+220 = 274 > 245 -> Verlaengerung, alle drei raus
            ["G1", "x", "AAA", 2, 34, 20, 33, 20, 33, 20, 3.0, 1],
            ["G1", "x", "AAA", 3, 220, 5, 20, 5, 20, 5, 3.0, 1],
            ["G2", "x", "BBB", 4, 20, 9, 32, 9, 32, 9, 3.0, 1],         # Starter, Verlust 12
            ["G2", "x", "BBB", 6, 34, 9, 30, 9, 30, 9, 3.0, 1],         # Starter, +4
            ["G3", "x", "CCC", 5, 5, 0, 15, 5, 15, 5, 3.0, 1],          # kein Starter
            ["0022400061", "x", "DDD", 9, 10, 1, 40, 20, 40, 20, 0.0, 1]]
    with gzip.open(p / "f.csv.gz", "wt", newline="") as f:
        w = csv.writer(f); w.writerow(head); w.writerows(data)
    rows = mt.load_starters(p / "f.csv.gz")
    check("Starter-Auswahl (ohne OT, ohne Ausschluss, ohne Nicht-Starter)", [r["pid"] for r in rows] == [4, 6], [r["pid"] for r in rows])
    res = {"2023-24": {"rows": [dict(r, err=r["act"] - r["exp"]) for r in rows], "causes": [], "pbp_fehlt": 0}}
    res["2023-24"]["causes"] = [dict(res["2023-24"]["rows"][0], cause=mt.classify_loss({}, True, 0, 3000.0))]
    text = mt.build_report(res)
    check("Bericht: Punkte mit Verlust 9.0/9.0, Anzahl 1", "mit grossem Minutenverlust" in text and "9.0/9.0 (n=1)" in text)
    check("Bericht: GT-Anteil 100 %", "in Spiel mit GT G1" in text and "100.0 %" in text)
print("ALLES OK" if ok else "FEHLER"); sys.exit(0 if ok else 1)
