"""Test fuer analysis/fetch_boxscore_archive.py an einem kleinen kuenstlichen Boxscore. Ohne Netz (der Abruf wird durch eine Attrappe ersetzt).
Aufruf: venv/bin/python tests/test_boxscore_archive.py"""
import csv, gzip, json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import fetch_boxscore_archive as fb

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def player(pid, name, status, reason, minutes, pts, played):
    p = {"personId": pid, "name": name, "status": status, "played": played, "statistics": {"minutes": minutes, "points": pts} if minutes is not None else {}}
    if reason:
        p["notPlayingReason"] = reason
    return p
def box(gid="0022300999", wrapped=True):
    g = {"gameId": gid, "gameEt": "2023-12-05T19:30:00-05:00",
         "homeTeam": {"teamTricode": "AAA", "players": [player(1, "Home Star", "ACTIVE", None, "PT34M30.00S", 28, "1"), player(2, "Home Bench", "ACTIVE", None, "PT00M00.00S", 0, "0"),
                                                         player(3, "Home Hurt", "INACTIVE", "INACTIVE_INJURY", None, 0, "0")]},
         "awayTeam": {"teamTricode": "BBB", "players": [player(4, "Away One", "ACTIVE", None, "PT12M", 5, "1"), player(5, "Away Two", "INACTIVE", "INACTIVE_GLEAGUE_TWOWAY", None, 0, "0"),
                                                         player(6, "Away Odd", "SOMETHING", None, None, 0, "0")]}}
    return json.dumps({"meta": {}, "game": g} if wrapped else g).encode()

check("Minuten", fb.minutes_of("PT34M30.00S") == 34.5 and fb.minutes_of("PT12M") == 12.0 and fb.minutes_of("PT00M00.00S") == 0.0 and fb.minutes_of(None) == 0.0 and fb.minutes_of("") == 0.0)
check("Antwort gueltig (mit und ohne 'game'-Huelle), 6 Spieler", fb.parse_response(box(), "0022300999") == 6 and fb.parse_response(box(wrapped=False), "0022300999") == 6)
for name, body, gid in (("falsche Spiel-ID", box(), "0022300000"), ("kein JSON", b"<html>", "0022300999"), ("ohne Spieler", json.dumps({"game": {"gameId": "0022300999", "homeTeam": {"players": []}, "awayTeam": {"players": [1]}}}).encode(), "0022300999")):
    try:
        fb.parse_response(body, gid); check(f"Fehler erkannt: {name}", False)
    except ValueError:
        check(f"Fehler erkannt: {name}", True)
rows = fb.table_rows(box(), "0022300999")
st = {r[3]: r[5] for r in rows}
check("Status: aktiv / INACTIVE_INJURY / INACTIVE_GLEAGUE_TWOWAY / unbekannt unveraendert", st == {1: "aktiv", 2: "aktiv", 3: "INACTIVE_INJURY", 4: "aktiv", 5: "INACTIVE_GLEAGUE_TWOWAY", 6: "SOMETHING"}, st)
check("Kaderspieler ohne Einsatz enthalten (Minuten 0)", [r for r in rows if r[3] == 2][0][6] == 0.0 and [r for r in rows if r[3] == 3][0][6] == 0.0)
check("Datum, Team, Minuten, Punkte", rows[0][:3] == ["0022300999", "2023-12-05", "AAA"] and rows[0][6] == 34.5 and rows[0][7] == 28 and len(rows[0]) == 8)

with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "pbp"; cdir = Path(td) / "cache"; cdir.mkdir()
    ids = ["0022300001", "0022300002", "0022300003"]
    for s, f in fb.game_ids.__globals__["SOURCES"].items():
        (cdir / f).write_text(json.dumps({"rows": [{"game_id": g} for g in ids] if s == "2023-24" else []}), encoding="utf-8")
    calls, clock = [], [1000.0]
    sleeps = []
    def fake_sleep(s): sleeps.append(s); clock[0] += s
    def fetch_ok(gid):
        calls.append(gid); return 200, box(gid)
    arc = fb.Archive(out, fetch=fetch_ok, sleep=fake_sleep, now=lambda: clock[0], write=lambda *_: None)
    res = arc.run(["2023-24"], cdir)
    check("3 Spiele geholt und gespeichert", res["stopped"] is None and res["report"]["2023-24"]["saved"] == 3 and len(calls) == 3)
    check("Ablage <Ordner>/boxscore/<Saison>/<id>.json.gz", fb.target_path(out, "2023-24", "0022300001").exists() and fb.target_path(out, "2023-24", "0022300001").parent.name == "2023-24")
    check("Wartezeit zwischen Abrufen 2 s (hoechstens 0,5 pro Sekunde)", len(sleeps) == 2 and all(abs(x - 2.0) < 1e-9 for x in sleeps), sleeps)
    calls.clear()
    arc2 = fb.Archive(out, fetch=fetch_ok, sleep=fake_sleep, now=lambda: clock[0], write=lambda *_: None)
    res2 = arc2.run(["2023-24"], cdir)
    check("Wiederaufnahme: vorhandene Spiele uebersprungen, kein Abruf", not calls and res2["report"]["2023-24"]["saved"] == 3 and res2["report"]["2023-24"]["fresh"] == 0)
    # Sperre
    out2 = Path(td) / "blocked"
    def fetch_403(gid): calls.append(gid); return 403, b""
    calls.clear()
    arc3 = fb.Archive(out2, fetch=fetch_403, sleep=fake_sleep, now=lambda: clock[0], write=lambda *_: None)
    res3 = arc3.run(["2023-24"], cdir)
    check("403: sofortiger Stopp nach dem ersten Abruf", res3["stopped"] == "gesperrt" and len(calls) == 1)
    out3 = Path(td) / "limit"
    arc4 = fb.Archive(out3, fetch=fetch_ok, sleep=fake_sleep, now=lambda: clock[0], write=lambda *_: None)
    calls.clear()
    res4 = arc4.run(["2023-24"], cdir, limit=2)
    check("--limit begrenzt die Abrufe", res4["stopped"] == "limit" and len(calls) == 2)
    # Tabelle und Bericht, mit Prognosedatei
    (out / "derived").mkdir(parents=True, exist_ok=True)
    with gzip.open(out / "derived" / "forecast_players_2023-24.csv.gz", "wt", newline="") as fh:
        w = csv.writer(fh); w.writerow(["spiel_id", "datum", "team", "spieler_id", "minuten_ist", "punkte_ist", "minuten_erw_roh", "punkte_erw_roh", "minuten_erw_teamabgleich", "punkte_erw_teamabgleich", "tspread", "rotation"])
        w.writerow(["0022300001", "x", "AAA", 1, 34, 28, 30.0, 20, 30, 20, 1, 1])      # in Tabelle, erw. > 20, aktiv
        w.writerow(["0022300001", "x", "AAA", 3, 5, 1, 25.0, 10, 25, 10, 1, 1])        # in Tabelle als INACTIVE_INJURY, erw. > 20 (kuenstlich)
        w.writerow(["0022300001", "x", "AAA", 77, 5, 1, 10.0, 4, 10, 4, 1, 1])         # nicht in Tabelle
    t = fb.build_table(out, "2023-24", cdir)
    check("Tabelle: 3 Spiele x 6 Zeilen, nichts fehlt", len(t["rows"]) == 18 and t["present"] == 3 and t["missing"] == 0)
    with gzip.open(out / "derived" / "inactives_2023-24.csv.gz", "rt", newline="") as fh:
        rd = list(csv.reader(fh))
    check("CSV-Spalten wie verlangt", rd[0] == ["spiel_id", "datum", "team", "spieler_id", "name", "status", "minuten", "punkte"] and len(rd) == 19)
    fc = fb.forecast_check(out, "2023-24", t["rows"])
    check("ID-Kontrolle: 2 von 3 Prognosezeilen gefunden; erw. > 20: 2, davon INACTIVE_INJURY 1", fc["in_downloaded_games"] == 3 and fc["matched"] == 2 and fc["big_rows"] == 2 and fc["big_inactive_injury"] == 1, fc)
    text = fb.run_report(out, ["2023-24"], cdir, Path(td) / "bericht.txt")
    check("Bericht: Zeilen je Status, Anteil Spiele mit INACTIVE_INJURY = 100 %", "INACTIVE_INJURY 3" in text and "3 von 3 = 100.0 %" in text and (Path(td) / "bericht.txt").exists())
print("ALLES OK" if ok else "FEHLER"); sys.exit(0 if ok else 1)
