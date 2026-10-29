"""Test fuer analysis/build_lineups.py an einem kleinen kuenstlichen Spiel (zwei Teams, wenige Wechsel, ein Wechsel an der Periodengrenze, eine Verlaengerung). Ohne Netz, nur Temp-Ordner.
Aufruf aus dem Projektordner: venv/bin/python tests/test_build_lineups.py"""
import csv, gzip, json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import build_lineups as bl

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

A, B = 100, 200                                       # Team-IDs (A = Heim, B = Gast)
TRI = {A: "AAA", B: "BBB"}
actions, order = [], [0]
def clk(rem):
    m, s = divmod(rem, 60)
    return f"PT{int(m):02d}M{s:05.2f}S"
def ev(period, rem, typ, sub="", pid=0, tid=0, score=None, **extra):
    order[0] += 10000
    a = {"actionNumber": order[0] // 10000, "orderNumber": order[0], "period": period, "clock": clk(rem), "actionType": typ, "subType": sub, "personId": pid, "teamId": tid or None,
         "teamTricode": TRI.get(tid), "scoreHome": str(score[0] if score else sc["h"]), "scoreAway": str(score[1] if score else sc["a"])}
    a.update(extra); actions.append(a)
sc = {"h": 0, "a": 0}
def shot(period, rem, pid, tid, pts):
    sc["h" if tid == A else "a"] += pts
    ev(period, rem, "2pt" if pts == 2 else "3pt", "Jump Shot", pid, tid, (sc["h"], sc["a"]))
def sub(period, rem, tid, out, inn):
    ev(period, rem, "substitution", "out", out, tid, (sc["h"], sc["a"])); ev(period, rem, "substitution", "in", inn, tid, (sc["h"], sc["a"]))
def periods(p, rem_end=0):
    ev(p, rem_end, "period", "end")
# A: Starter 11-15, Bank 16, 17.  B: Starter 21-25, Bank 26.
ev(1, 720, "period", "start")
shot(1, 600, 11, A, 2)                                              # 2:0   (t=120)
shot(1, 480, 21, B, 3)                                              # 2:3   (t=240)
ev(1, 420, "rebound", "defensive", 22, B); ev(1, 400, "foul", "personal", 23, B, foulDrawnPersonId=12)
ev(1, 380, "turnover", "bad pass", 24, B, stealPersonId=13); ev(1, 370, "block", "", 25, B, assistPersonId=None)
ev(1, 365, "rebound", "offensive", 14, A, assistPersonId=15)
sub(1, 360, A, 12, 16)                                              # t=360: 12 raus, 16 rein
ev(1, 0, "period", "end")
sub(2, 720, A, 13, 17)                                              # Wechsel an der Periodengrenze (vor 'period start', t=720)
ev(2, 720, "period", "start")
shot(2, 300, 17, A, 2)                                              # 4:3
periods(2)
ev(3, 720, "period", "start"); periods(3)
ev(4, 720, "period", "start")
shot(4, 100, 21, B, 3)                                              # 4:6
shot(4, 5, 16, A, 2); shot(4, 2, 16, A, 0)                          # 6:6 -> Verlaengerung
periods(4)
ev(5, 300, "period", "start")                                       # Verlaengerung (5 Minuten)
sub(5, 120, A, 14, 12)                                              # OT t=2880+180=3060
shot(5, 60, 12, A, 2)
periods(5)
ev(5, 0, "game", "end")

g = bl.build_game(actions)
rows = g["rows"]
by = lambda tid: [r for r in rows if r["tid"] == tid]
check("Spielzeit: Perioden 1-4 je 720 s, Verlaengerung 300 s", bl.period_start(2) == 720 and bl.period_end(4) == 2880 and bl.period_start(5) == 2880 and bl.period_end(5) == 3180 and bl.game_length(5) == 3180 and bl.game_length(4) == 2880)
check("Heimteam aus dem Spielstand erkannt, Kuerzel", g["home"] == A and g["tri"] == TRI)
check("Starter aus den Ereignissen (auch Spieler, deren erste Sichtung 'substitution out', Assist, Steal, Foul gezogen ist): A 11-15, B 21-25", g["starters"][A] == {11, 12, 13, 14, 15} and g["starters"][B] == {21, 22, 23, 24, 25}, str(g["starters"]))
a_rows = by(A)
check("Team A: 7 Stints (P1: 2, P2: 1, P3: 1, P4: 1, OT: 2), Nummern 1..7", [(r["nr"], r["period"], r["start"], r["end"]) for r in a_rows] == [(1, 1, 0, 360), (2, 1, 360, 720), (3, 2, 720, 1440), (4, 3, 1440, 2160), (5, 4, 2160, 2880), (6, 5, 2880, 3060), (7, 5, 3060, 3180)], str([(r["nr"], r["period"], r["start"], r["end"]) for r in a_rows]))
check("Aufstellungen: vor dem Wechsel 11-15, danach 12 -> 16, Periodengrenze 13 -> 17 (gehoert zum Beginn von P2), OT-Wechsel 14 -> 12",
      [r["players"] for r in a_rows] == [[11, 12, 13, 14, 15], [11, 13, 14, 15, 16], [11, 14, 15, 16, 17], [11, 14, 15, 16, 17], [11, 14, 15, 16, 17], [11, 14, 15, 16, 17], [11, 12, 15, 16, 17]])
check("Wechsel zur Periodengrenze: kein Stint mit Dauer 0, Stint von P1 endet bei 720 und P2 beginnt bei 720 mit der neuen Aufstellung", all(r["end"] > r["start"] for r in rows) and a_rows[1]["end"] == 720 and a_rows[2]["start"] == 720 and 13 not in a_rows[2]["players"])
check("Team B: keine Wechsel, je Periode ein Stint (5), gleiche Spieler", [(r["period"], r["start"], r["end"]) for r in by(B)] == [(1, 0, 720), (2, 720, 1440), (3, 1440, 2160), (4, 2160, 2880), (5, 2880, 3180)] and all(r["players"] == [21, 22, 23, 24, 25] for r in by(B)))
check("Spielstand und Abstand (Team minus Gegner): A Stint 1 Beginn 0:0 / Ende 2:3 (-1), Stint 3 Beginn 2:3 -> hier 4:3 am Ende von P2", (a_rows[0]["score_start"], a_rows[0]["score_end"]) == ((0, 0), (2, 3)) and a_rows[2]["score_start"] == (2, 3) and a_rows[2]["score_end"] == (4, 3), str((a_rows[2]["score_start"], a_rows[2]["score_end"])))
check("Punkte je Team aus Sicht des Teams: B Stint 1 Ende 3 zu 2 (Abstand +1), Heimteam A sieht 2 zu 3", by(B)[0]["score_end"] == (3, 2) and a_rows[0]["score_end"] == (2, 3))
m = bl.minutes_from_rows(g)
check("Minuten je Spieler: 11 = 53, 12 = 8, 13 = 12, 14 = 51, 15 = 53, 16 = 47, 17 = 41 (Summe 265); B je 53", {p: round(m[p], 4) for p in (11, 12, 13, 14, 15, 16, 17)} == {11: 53, 12: 8, 13: 12, 14: 51, 15: 53, 16: 47, 17: 41} and all(abs(m[p] - 53) < 1e-9 for p in (21, 22, 23, 24, 25)))
check("Teamsumme 240 + 25 fuer die Verlaengerung = 265 je Team", all(abs(sum(5 * (r["end"] - r["start"]) / 60 for r in by(t)) - 265) < 1e-9 for t in (A, B)) and 5 * bl.game_length(g["max_period"]) / 60 == 265)
check("am Ende je Team genau 5 Spieler, keine Auffaelligkeiten", g["end_count"] == {A: 5, B: 5} and not g["anomalies"], str(dict(g["anomalies"])))

# CSV
rws = bl.csv_rows("0022300999", g)
check("CSV-Zeile: spiel_id, Kuerzel, Stint-Nr, Periode, Start, Ende, 5 Spieler, Abstand Start/Ende (+ 4 Punktespalten)", rws[0][:6] == ["0022300999", "AAA", 1, 1, "0", "360"] and rws[0][6:11] == [11, 12, 13, 14, 15] and rws[0][11:13] == [0, -1] and len(rws[0]) == len(bl.CSV_HEAD) and bl.CSV_HEAD[:6] == ["spiel_id", "team", "stint_nr", "periode", "start_s", "ende_s"], str(rws[0]))

# fehlender Starter ohne Ereignis: Ergaenzung aus den Minuten
acts2 = [a for a in actions if a.get("personId") != 15 and a.get("assistPersonId") != 15]
g2 = bl.build_game(acts2)
check("ohne Ereignis des Spielers 15: nur 4 Starter gefunden, Auffaelligkeit gemeldet, Stints mit 4 Spielern werden nicht geschrieben", g2["starters"][A] == {11, 12, 13, 14} and g2["anomalies"]["starter_zu_wenig"] == 1 and g2["anomalies"]["stint_nicht_5"] >= 1)
g3 = bl.build_game(acts2, {"AAA": {11, 12, 13, 14, 15, 16, 17}})
check("mit Minuten (15 spielte, nie ein Ereignis): ergaenzt, gleiche Stints wie im Ausgangsspiel", g3["starters"][A] == {11, 12, 13, 14, 15} and g3["anomalies"]["starter_ergaenzt"] == 1 and [(r["start"], r["end"], r["players"]) for r in g3["rows"]] == [(r["start"], r["end"], r["players"]) for r in rows])
# fehlender Wechsel 'in': am Ende nur 4 Spieler
acts4 = [a for a in actions if not (a["actionType"] == "substitution" and a["subType"] == "in" and a["personId"] == 12)]
g4 = bl.build_game(acts4)
check("fehlendes 'substitution in' (Spieler 12 im OT): am Ende 4 Spieler auf dem Feld, Auffaelligkeit", g4["end_count"][A] == 4 and g4["anomalies"]["stint_nicht_5"] >= 1)

# Dateien: Lesen, uebersprungene Dateien, Saison-Lauf, Pruefung der Minuten
with tempfile.TemporaryDirectory() as td:
    T = Path(td); pbp = T / "pbp" / "2023-24"; pbp.mkdir(parents=True)
    (pbp / "0022300999.json.gz").write_bytes(gzip.compress(json.dumps({"meta": {}, "game": {"gameId": "0022300999", "actions": actions}}).encode()))
    (pbp / "0022300998.json.gz").write_bytes(b"kaputt")                                                       # nicht lesbar
    (pbp / "0022300997.json.gz").write_bytes(gzip.compress(json.dumps({"game": {"gameId": "ANDERE", "actions": actions}}).encode()))      # falsche Spiel-ID
    cache = T / "cache"; cache.mkdir()
    local = [{"game_id": "0022300999", "person_id": p, "name": f"P{p}", "team": "AAA" if p < 20 else "BBB", "minutes": mins} for p, mins in {11: 53, 12: 8, 13: 12, 14: 51, 15: 53, 16: 47, 17: 40, 21: 53, 22: 53, 23: 53, 24: 53, 25: 53, 99: 3}.items()]
    (cache / "backtest_player_games_2023-24.json").write_text(json.dumps({"rows": local}))
    sm = bl.run_season("2023-24", T / "pbp", T / "out", cache_dir=cache, write=lambda *_: None)
    check("Saison-Lauf: 1 Spiel gelesen, 2 Dateien unlesbar/unpassend uebersprungen und gezaehlt", (sm["pbp_dateien"], sm["gelesen"], sm["nicht_lesbar"]) == (3, 1, 2), str((sm["pbp_dateien"], sm["gelesen"], sm["nicht_lesbar"])))
    check("Minutenvergleich: 13 Spieler-Spiele (12 mit Stints + Spieler 99 nur lokal); Abweichungen: Spieler 17 (1 Min), Spieler 99 (3 Min)", sm["spieler_spiele"] == 13 and sm["le05"] == 11 and sm["le10"] == 12 and sm["gt10"] == 1
          and [t[2] for t in sm["top"][:2]] == [99, 17], str(sm["top"][:3]))
    check("Spiele mit falscher Teamsumme / falschem Ende: keine", sm["spiele_ende_nicht_5"] == 0 and sm["spiele_teamsumme_falsch"] == 0)
    with gzip.open(T / "out" / "lineups_2023-24.csv.gz", "rt", encoding="utf-8") as f:
        table = list(csv.reader(f))
    check("CSV-Datei gelesen: Kopfzeile + 12 Stints (A 7 + B 5)", table[0] == bl.CSV_HEAD and len(table) == 13 and table[1][:6] == ["0022300999", "AAA", "1", "1", "0", "360"], str(table[1]))
    # zweiter Lauf: derselbe Zustand, keine Aenderung der Eingabe
    check("Eingabedateien unveraendert (nur gelesen)", (pbp / "0022300998.json.gz").read_bytes() == b"kaputt" and sorted(p.name for p in pbp.iterdir()) == ["0022300997.json.gz", "0022300998.json.gz", "0022300999.json.gz"])
    rep = bl.build_report(T / "out", None, seasons=("2023-24",))
    check("Bericht: Spiele gelesen, nicht lesbar, Anteile der Abweichungen, groesste Abweichungen, Ende, Teamsumme", all(w in rep for w in ("gelesen: 1", "nicht lesbar (uebersprungen): 2", "<= 0,5 Min", "<= 1 Min", "groesser als 1 Min", "10 groessten", "nicht genau 5 Spieler", "240 plus 25")))
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
