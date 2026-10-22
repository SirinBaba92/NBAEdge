"""Tests fuer data/player_history.py (lokaler Spielerverlauf). Nur kuenstliche Daten in Temp-Ordnern, KEIN Abruf, keine echten Dateien veraendert.
Aufruf aus dem Projektordner: venv/bin/python tests/test_player_history.py"""
import gzip, hashlib, json, math, os, sys, tempfile
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))

TMP = tempfile.TemporaryDirectory()
T = Path(TMP.name)
os.environ["NBAEDGE_PLAYER_CACHE_DIR"] = str(T / "cache")
os.environ["NBAEDGE_LIVE_DIR"] = str(T / "live")
os.environ["NBAEDGE_ROSTERS"] = str(T / "rosters.json")
from data import player_history as ph

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def snap():
    files = list((ROOT / "data" / "cache").glob("*")) + [ROOT / "data" / "rosters.json"] + [p for p in (ROOT / "data" / "tracking").glob("*.json")]
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = snap()

HEAD = ["SEASON_ID", "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "TEAM_NAME", "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "MIN", "FGM", "FGA", "FG_PCT",
        "FG3M", "FG3A", "FG3_PCT", "FTM", "FTA", "FT_PCT", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TOV", "PF", "PTS", "PLUS_MINUS", "FANTASY_PTS", "VIDEO_AVAILABLE"]
def lrow(pid, name, team, opp, gid, day, home, wl, mn, pts, fga=10, fta=4, pf=2, pm=3):
    m = f"{team} vs. {opp}" if home else f"{team} @ {opp}"
    return ["22025", pid, name, 1, team, team, gid, day, m, wl, mn, 4, fga, .4, 1, 3, .3, 2, fta, .5, 1, 4, 5, 3, 1, 1, 2, pf, pts, pm, 20.0, 1]
def payload(rows): return {"resultSets": [{"name": "LeagueGameLog", "headers": HEAD, "rowSet": rows}]}

# Spiele: Spieler 1 (AAA) mit Punkten 10,20,30,40,50,60 an Tagen 2025-11-01..06, Gegner BBB
P1 = [10, 20, 30, 40, 50, 60]
rows = []
for i, pts in enumerate(P1):
    gid, day = f"00225000{i+1}", f"2025-11-0{i+1}"
    rows.append(lrow(1, "Alpha Eins", "AAA", "BBB", gid, day, i % 2 == 0, "W", 30 + i, pts))
    rows.append(lrow(2, "Beta Zwei", "BBB", "AAA", gid, day, i % 2 != 0, "L", 20, 15))
PAY = payload(rows)
PAY26 = payload([lrow(50, "Neu Fuenfzig", "EEE", "FFF", "0022600001", "2026-10-20", True, "W", 20, 8), lrow(51, "Neu Einundfuenfzig", "FFF", "EEE", "0022600001", "2026-10-20", False, "L", 20, 7)])

# --- Minuten
check("Minuten: Zahl, Text, mm:ss, PT..M..S", ph.minutes_to_float(28) == 28.0 and ph.minutes_to_float("28") == 28.0 and ph.minutes_to_float("28:30") == 28.5
      and abs(ph.minutes_to_float("PT28M30.00S") - 28.5) < 1e-9 and ph.minutes_to_float("PT05M00.00S") == 5.0 and abs(ph.minutes_to_float("PT00M45.00S") - 0.75) < 1e-9)
check("Minuten: leer/ungueltig -> 0", all(ph.minutes_to_float(v) == 0.0 for v in (None, "", "abc", "PT", True, float("nan"))))

# --- Parser
parsed = ph.parse_league_log(PAY, "2025-26")
r0 = parsed[0]
check("Parser: Zeilenzahl und Felder", len(parsed) == 12 and r0["game_id"] == "002250001" or r0["game_id"] == "00225000" + "1")
check("Parser: Heim/Gast, Gegner, Minuten, Quelle", r0["home"] is True and r0["opponent"] == "BBB" and r0["minutes"] == 30.0 and r0["source"] == "league" and parsed[2]["home"] is False)
check("Parser: Teamdifferenz aus Punktesummen (10-15 = -5), Sieg-Kennzeichen aus WL", r0["margin"] == -5 and r0["win"] is True and parsed[1]["margin"] == 5 and parsed[1]["win"] is False)
for bad in ({}, {"resultSets": []}, {"resultSets": [{"headers": ["X"], "rowSet": []}]}):
    try:
        ph.parse_league_log(bad, "2025-26"); check("Parser: kaputte Antwort -> ValueError", False)
    except ValueError:
        check("Parser: kaputte Antwort -> ValueError", True)

# --- Abruf, Schreiben, Fehlerfaelle ohne Datenverlust
calls = []
def good(season): calls.append(season); return PAY
res = ph.refresh_season("2025-26", good, now=1.0)
f = ph.season_path("2025-26")
d = json.loads(f.read_text())
check("Abruf schreibt Datei mit Version, Format, Saison, 12 Zeilen", res["ok"] and d["version"] == 1 and d["format"] == "nbaedge-player-games" and d["season"] == "2025-26" and len(d["rows"]) == 12)
check("kein Temp-Rest im Ordner", not [p for p in f.parent.iterdir() if p.name.startswith(".")])
before = f.read_bytes()
def boom(season): raise TimeoutError("zu langsam")
def http(season): raise RuntimeError("403 Forbidden")
for label, fn in (("Timeout", boom), ("403", http), ("leere Antwort", lambda s: payload([])), ("kaputte Antwort", lambda s: {"x": 1}),
                  ("kleinere Antwort", lambda s: payload(rows[:4]))):
    r = ph.refresh_season("2025-26", fn, now=2.0)
    check(f"Fehlerfall {label}: ok=False, Datei bytegleich, keine Ausnahme", (not r["ok"]) and f.read_bytes() == before, r["message"][:60])
check("ohne vorhandene Datei: Fehler legt keine Datei an", (not ph.refresh_season("2024-25", boom)["ok"]) and not ph.season_path("2024-25").exists())
bigger = payload(rows + [lrow(1, "Alpha Eins", "AAA", "BBB", "002250099", "2025-11-09", True, "W", 31, 5), lrow(2, "Beta Zwei", "BBB", "AAA", "002250099", "2025-11-09", False, "L", 31, 5)])
check("groessere Antwort ersetzt den Bestand", ph.refresh_season("2025-26", lambda s: bigger, now=3.0)["ok"] and len(json.loads(f.read_text())["rows"]) == 14)
ph.refresh_season("2025-26", good, now=1.0)       # zurueck auf 12 geht nicht (kleiner) -> bleibt 14
check("kleinerer Bestand ueberschreibt den groesseren nicht", len(json.loads(f.read_text())["rows"]) == 14)
f.write_text("{kaputt")
check("defekte Datei: Lesen liefert leer statt Ausnahme", ph.league_file("2025-26") is None and ph.get_player_games(1, "2025-26") == [])
ph.refresh_season("2025-26", good, now=1.0)
check("defekte Datei wird beim naechsten Erfolg ersetzt", len(json.loads(f.read_text())["rows"]) == 12)

# --- refresh_current_season: Stunde und Pausenverdopplung
NOW = datetime(2026, 10, 22, 12, 0, 0).timestamp()
calls.clear()
def good26(season): calls.append(season); return PAY26
r = ph.refresh_current_season(good26, now=NOW)
check("laufende Saison = 2026-27, Erfolg", r["status"] == "aktualisiert" and r["season"] == "2026-27" and calls == ["2026-27"])
r = ph.refresh_current_season(good26, now=NOW + 1800)
check("nach 30 Min. kein neuer Abruf (hoechstens einmal pro Stunde)", r["status"] == "uebersprungen" and len(calls) == 1)
r = ph.refresh_current_season(good26, now=NOW + 3601)
check("nach einer Stunde wieder erlaubt", r["status"] == "aktualisiert" and len(calls) == 2)
t = NOW + 10000
waits = []
for i in range(6):
    r = ph.refresh_current_season(http, now=t)
    waits.append(r["wait_s"]); check(f"Fehler {i+1}: Status fehler, keine Ausnahme", r["status"] == "fehler"); t += r["wait_s"] + 1
check("Pause verdoppelt sich 30, 60, 120, 240, 300, 300", waits == [30, 60, 120, 240, 300, 300], str(waits))
r = ph.refresh_current_season(good26, now=t - 5)
check("waehrend der Pause kein Abruf", r["status"] == "uebersprungen")
ph.refresh_current_season(http, now=t + 1000)
cur = json.loads(ph.season_path("2026-27").read_text())
check("Fehler lassen die Saisondatei unveraendert (2 Zeilen)", len(cur["rows"]) == 2)
r = ph.refresh_current_season(good26, now=t + 1000 + 301)
st = ph.player_history_status()
check("Erfolg setzt Zaehler zurueck", r["status"] == "aktualisiert" and st["fail_count"] == 0 and st["last_error"] is None)
check("force umgeht die Wartezeit", ph.refresh_current_season(good26, now=t + 1000 + 302, force=True)["status"] == "aktualisiert")

# --- before_date, n, Reihenfolge
g = ph.get_player_games(1, "2025-26")
check("neueste zuerst", [x["date"] for x in g] == sorted([x["date"] for x in g], reverse=True) and g[0]["points"] == 60)
check("before_date schliesst den Stichtag selbst aus", [x["points"] for x in ph.get_player_games(1, "2025-26", before_date="2025-11-04")] == [30, 20, 10])
check("before_date als Datum/Zeitpunkt", len(ph.get_player_games(1, "2025-26", before_date=datetime(2025, 11, 4).date())) == 3)
check("before_date vor dem ersten Spiel -> leer", ph.get_player_games(1, "2025-26", before_date="2025-11-01") == [])
check("n begrenzt", [x["points"] for x in ph.get_player_games(1, "2025-26", n=2)] == [60, 50])
check("season=None: alle geladenen Saisons, unbekannter Spieler leer", len(ph.get_player_games(1)) >= 6 and ph.get_player_games(999) == [])

# --- Recorder-Zusammenfuehrung
def box(gid, home, away, hs, as_, players, status=3):
    return {"meta": {"code": 200}, "game": {"gameId": gid, "gameStatus": status, "homeTeam": {"teamTricode": home, "score": hs, "players": players[0]},
                                            "awayTeam": {"teamTricode": away, "score": as_, "players": players[1]}}}
def pl(pid, name, minutes, pts, fga=8): return {"personId": pid, "name": name, "statistics": {"minutes": minutes, "points": pts, "fieldGoalsAttempted": fga, "fieldGoalsMade": 3,
        "freeThrowsAttempted": 2, "freeThrowsMade": 1, "threePointersAttempted": 4, "threePointersMade": 1, "foulsPersonal": 3, "plusMinusPoints": 7}}
def put(day, gid, obj):
    p = T / "live" / day / gid; p.mkdir(parents=True, exist_ok=True)
    (p / "final_box.json.gz").write_bytes(gzip.compress(json.dumps(obj).encode()))
put("2026-10-21", "0022600004", box("0022600004", "AAA", "BBB", 110, 100, ([pl(1, "Alpha Eins", "PT28M30.00S", 25), pl(7, "Bank", "PT00M00.00S", 0)], [pl(2, "Beta Zwei", "PT30M00.00S", 12)])))
put("2026-10-21", "0022600005", box("0022600005", "CCC", "DDD", 90, 95, ([pl(5, "Fuenf", "PT20M00.00S", 9)], [pl(6, "Sechs", "PT22M00.00S", 11)]), status=2))
rs = ph.season_rows("2026-27")
rec = [r for r in rs if r["source"] == "recorder"]
check("Recorder-Spiel fehlt in Liga-Datei -> ergaenzt; Minuten PT28M30S = 28.5; ohne Einsatz (0 Min.) entfallen; laufendes Spiel (Status 2) nicht", sorted(r["person_id"] for r in rec) == [1, 2] and rec[0]["minutes"] in (28.5, 30.0), str([(r["person_id"], r["minutes"]) for r in rec]))
a = next(r for r in rec if r["person_id"] == 1)
check("Recorder-Zeile: Datum = Spieltag, Saison, Gegner, Heim, Sieg, Differenz, Fouls", (a["date"], a["season"], a["opponent"], a["home"], a["win"], a["margin"], a["fouls"], a["points"], a["fg3a"]) == ("2026-10-21", "2026-27", "BBB", True, True, 10, 3, 25, 4), str(a))
# Liga-Datei enthaelt das Spiel schon -> keine Doppelten
league_with = payload([lrow(1, "Alpha Eins", "AAA", "BBB", "0022600004", "2026-10-21", True, "W", 28.5, 25), lrow(2, "Beta Zwei", "BBB", "AAA", "0022600004", "2026-10-21", False, "L", 30, 12),
                       lrow(3, "Noch Einer", "AAA", "BBB", "0022600004", "2026-10-21", True, "W", 5, 2)])
ph.season_path("2026-27").unlink()
ph.refresh_season("2026-27", lambda s: league_with, now=NOW)
rs = ph.season_rows("2026-27")
check("Spiel schon in der Liga-Datei: keine Doppelten, keine Recorder-Zeilen", len([r for r in rs if r["game_id"] == "0022600004"]) == 3 and not [r for r in rs if r["source"] == "recorder"])
f2 = ph.season_path("2026-27")
put("2026-10-22", "0022600010", box("0022600010", "AAA", "BBB", 100, 101, ([pl(1, "Alpha Eins", "PT10M00.00S", 4)], [pl(2, "Beta Zwei", "PT10M00.00S", 6)])))
rs = ph.season_rows("2026-27")
check("zweiter Tag: nur das fehlende Spiel kommt aus dem Recorder, (game_id, person_id) eindeutig", len([r for r in rs if r["source"] == "recorder"]) == 2 and len({(r["game_id"], r["person_id"]) for r in rs}) == len(rs))
check("Recorder-Daten werden nicht in die Liga-Datei geschrieben", all(r["source"] == "league" for r in json.loads(f2.read_text())["rows"]))
(T / "live" / "2026-10-23" / "0022600011").mkdir(parents=True); (T / "live" / "2026-10-23" / "0022600011" / "final_box.json.gz").write_bytes(b"kaputt")
check("kaputter Boxscore im Recorderordner wirft nicht", isinstance(ph.season_rows("2026-27"), list))
check("Recorder-Ordner fehlt -> nur Liga-Datei", (lambda: (os.environ.__setitem__("NBAEDGE_LIVE_DIR", str(T / "gibtsnicht")), len(ph.season_rows("2025-26")))[1])() == 12)
os.environ["NBAEDGE_LIVE_DIR"] = str(T / "live")

# --- Summary nachgerechnet (Spieler 1, Saison 2025-26: 10,20,30,40,50,60; Minuten 30..35)
s = ph.get_player_summary(1, before_date="2025-12-01", season="2025-26")
mean = 35.0; std = math.sqrt(sum((x - mean) ** 2 for x in P1) / 5)
check("Summary: Spiele, Saison-Schnitt Punkte/Minuten", s["games"] == 6 and s["season_avg"]["points"] == 35.0 and abs(s["season_avg"]["minutes"] - 32.5) < 1e-9)
check("Summary: letzte 5 = (20+..+60)/5 = 40, letzte 10 = alle 6 = 35", s["last5"]["points"] == 40.0 and s["last5"]["games"] == 5 and s["last10"]["points"] == 35.0 and s["last10"]["games"] == 6)
check("Summary: Punkte pro Minute = 210 / 195", abs(s["points_per_minute"] - 210 / 195) < 1e-9 and abs(s["minutes_mean"] - 32.5) < 1e-9)
check("Summary: Standardabweichung (Stichprobe)", abs(s["points_std"] - std) < 1e-9, f"{s['points_std']:.3f}")
s2 = ph.get_player_summary(1, before_date="2025-11-04", season="2025-26")
check("Summary mit Stichtag: nur Spiele davor (10,20,30)", s2["games"] == 3 and s2["season_avg"]["points"] == 20.0 and s2["last5"]["points"] == 20.0)
s3 = ph.get_player_summary(999)
check("Summary ohne Spiele: None statt Fehler", s3["games"] == 0 and s3["season_avg"]["points"] is None and s3["points_std"] is None and s3["points_per_minute"] is None)
check("Standardabweichung braucht 2 Spiele", ph.get_player_summary(1, before_date="2025-11-02", season="2025-26")["points_std"] is None)
s4 = ph.get_player_summary(1, before_date="2026-10-22")
check("Stichtag in neuer Saison: Saison 2026-27, letzte 5 reichen in die Vorsaison", s4["season"] == "2026-27" and s4["games"] == 1 and s4["last5"]["games"] == 5, str(s4["games"]))

# --- Kader
(T / "rosters.json").write_text(json.dumps({"version": 1, "format": "nbaedge-rosters", "fetched_at": "2026-10-21T04:56:44+02:00", "source": "x", "season": "2026-27", "abrufe": 1,
    "teams": {"Los Angeles Lakers": [{"person_id": 1, "name": "Alpha Eins", "position": "G", "jersey": "1", "team_id": 1, "team_abbreviation": "LAL"}],
              "Atlanta Hawks": [{"person_id": 2, "name": "Beta Zwei", "position": "F", "jersey": "2", "team_id": 2, "team_abbreviation": "ATL"}]}}))
check("players_for_team: Vollname, Kuerzel, Spitzname", [p["name"] for p in ph.players_for_team("Los Angeles Lakers")] == ["Alpha Eins"] and ph.players_for_team("ATL")[0]["name"] == "Beta Zwei"
      and ph.players_for_team("hawks")[0]["team"] == "Atlanta Hawks")
check("players_for_team: unbekannt/leer -> []", ph.players_for_team("Nirgends") == [] and ph.players_for_team("") == [] and ph.players_for_team("ers") == [])
os.environ["NBAEDGE_ROSTERS"] = str(T / "fehlt.json")
check("players_for_team ohne Kaderdatei -> [] (kein Fehler)", ph.players_for_team("ATL") == [])

# --- Status
stt = ph.player_history_status()
c = stt["seasons"]["2026-27"]
check("Status: Saisonzeile mit Zeitpunkt, Spielen, Spielern", c["fetched_at"] and c["games"] >= 1 and c["players"] >= 3 and stt["seasons"]["2025-26"]["games"] == 6 and stt["seasons"]["2025-26"]["players"] == 2, str(stt["seasons"]))
check("Status: Fehlerfelder vorhanden", {"last_error", "fail_count", "last_attempt", "next_allowed_in_s"} <= set(stt))

# --- ensure_past_seasons
n0 = len(calls)
ph.season_path("2025-26").unlink()
out = ph.ensure_past_seasons(good, now=NOW)
check("fehlende Vorsaison wird einmal geladen, vorhandene nicht", len(out) == 1 and out[0]["ok"] and ph.ensure_past_seasons(good, now=NOW) == [])

check("echte Dateien (data/cache, rosters.json, Tracking) unveraendert", snap() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
