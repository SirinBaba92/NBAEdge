"""Test fuer analysis/redistribution.py an einem kleinen kuenstlichen Beispiel (Ausfall-Naeherung, Rueckfluss, Rollen, Ausschluesse). Ohne Netz.
Aufruf: venv/bin/python tests/test_redistribution.py"""
import os, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import redistribution as rd

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
near = lambda a, b, t=1e-9: abs(a - b) < t

def lrow(gid, day, pid, mins, pts, team="AAA", season="2023-24"):
    return {"game_id": gid, "date": f"2024-01-{day:02d}", "season": season, "team": team, "opponent": "BBB", "person_id": pid, "minutes": mins, "points": pts}
# Team AAA: Spieler 1 (30 Min./20 Pkt.), 2, 3, 4 spielen Tage 1-8; Spieler 1 fehlt an Tag 6 (kommt Tag 7 wieder)
rows = []
for d in range(1, 9):
    gid = f"g{d}"
    for pid, m, p in ((1, 30, 20), (2, 20, 10), (3, 10, 5), (4, 30, 15)):
        if pid == 1 and d == 6:
            continue
        rows.append(lrow(gid, d, pid, m, p))
# Spieler 5 fehlt Tag 4 (nur 8 Minuten Schnitt -> kein Kandidat), Spieler 6 wechselt (spielt nach Tag 3 nicht mehr fuer das Team -> kein Kandidat)
for d in range(1, 4):
    rows.append(lrow(f"g{d}", d, 6, 25, 8))
for d in range(1, 8):
    if d != 4:
        rows.append(lrow(f"g{d}", d, 5, 8, 2))
ro = rd.Rosters(rows)
c = rd.find_candidates(ro)
check("genau ein Kandidat: Spieler 1 am Tag 6", list(c) == [("2023-24", "AAA", "g6")] and [x[0] for x in c[("2023-24", "AAA", "g6")]] == [1], c)
pid, em, ep = c[("2023-24", "AAA", "g6")][0]
check("Erwartung = Mittel der letzten 10 Spiele (5 Spiele vor Tag 6)", near(em, 30) and near(ep, 20))
check("Wechsler (Spieler 6) und Kurzeinsatz-Spieler (5) sind keine Kandidaten", all(k[2] == "g6" for k in c))
# ohne Rueckkehr kein Kandidat
rows2 = [r for r in rows if not (r["person_id"] == 1 and r["game_id"] in ("g7", "g8"))]
check("ohne Rueckkehr innerhalb von 5 Spielen kein Kandidat", ("2023-24", "AAA", "g6") not in rd.find_candidates(rd.Rosters(rows2)))

# Prognosezeilen: Tag 6: Mitspieler 2,3,4 spielen mehr als erwartet
def frow(game, pid, emin, mact, epts, act, ot=False, team="AAA", season="2023-24"):
    return {"season": season, "game": game, "team": team, "pid": pid, "emin": emin, "mact": mact, "epts": epts, "act": act, "ot": ot}
fc = [frow("g6", 2, 20, 28, 10, 14), frow("g6", 3, 10, 14, 5, 8), frow("g6", 4, 30, 38, 15, 22),          # Starter 4: +8 Min, +7 Pkt.; mittel 2: +8, +4; Bank 3: +4, +3
      frow("g5", 2, 20, 20, 10, 10), frow("g5", 3, 10, 10, 5, 6)]                                           # ohne Kandidat: Summe +0 Min., +1 Pkt.
ev, base, multi = rd.events_and_baseline(fc, c)
check("ein Ereignis, eine Vergleichszeile", len(ev) == 1 and len(base) == 1 and multi == 0)
e = ev[0]
check("Summe der Mitspieler-Abweichungen Minuten 20, Punkte 14", near(e["dev_min"], 20) and near(e["dev_pts"], 14))
check("Rueckfluss Minuten = 20/30, Punkte = 14/20", near(e["dev_min"] / e["exp_min"], 20 / 30) and near(e["dev_pts"] / e["exp_pts"], 0.7))
check("Rollen: Starter 4 (>28), mittel 2, Bank 3", near(e["roles"]["Starter (>28)"][0], 8) and near(e["roles"]["mittlere (12-28)"][0], 8) and near(e["roles"]["Bank (<12)"][0], 4)
      and near(e["roles"]["Starter (>28)"][1], 7) and near(e["roles"]["mittlere (12-28)"][1], 4) and near(e["roles"]["Bank (<12)"][1], 3))
check("Vergleichszeile: Summe 0 Min., +1 Punkt", near(base[0]["dev_min"], 0) and near(base[0]["dev_pts"], 1))
# Verlaengerungsspiel wird ausgeschlossen
ev2, base2, _ = rd.events_and_baseline([dict(r, ot=True) for r in fc], c)
check("Verlaengerung ausgeschlossen", not ev2 and not base2)
# zwei Kandidaten -> kein Ereignis, gezaehlt
c2 = {("2023-24", "AAA", "g6"): [(1, 30, 20), (9, 25, 12)]}
ev3, b3, multi3 = rd.events_and_baseline(fc, c2)
check("zwei Kandidaten: ausgeschlossen und gezaehlt", not ev3 and multi3 == 1)
t = rd.ms([1.0, 3.0])
check("Mittel/Streuung (ddof=1)", t[0] == 2 and near(t[1], 2.0) and near(t[2], np.sqrt(2)))
# Bericht laeuft
txt = rd.build_report(ev + ev, base, {"gesamt": 0}, ["x"])
check("Bericht enthaelt Rollen und Groessen", "Starter (>28)" in txt and "ueber 28 Min." in txt and "20 bis 28 Min." in txt)
print("ALLES OK" if ok else "FEHLER"); sys.exit(0 if ok else 1)
