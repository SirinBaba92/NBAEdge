"""Tests fuer engine/game_clock.py (Phase und Uhr) und data/nba_headers.py (Chrome-Version aus dem installierten Browser). Offline.
Aufruf aus dem Projektordner: venv/bin/python tests/test_game_clock.py"""
import os, plistlib, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from engine import game_clock as gc
from engine.game_clock import build_game_clock as B, parse_clock
from data import nba_headers as nh

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

# --- parse_clock
check("ISO PT05M23.00S", parse_clock("PT05M23.00S") == 323.0)
check("ISO PT00M00.00S = 0", parse_clock("PT00M00.00S") == 0.0)
check("ISO nur Sekunden PT45.30S", abs(parse_clock("PT45.30S") - 45.3) < 1e-9)
check("mm:ss", parse_clock("5:23") == 323.0)
check("Sekunden als Text", parse_clock("40.8") == 40.8)
check("leer/None/Muell = None", parse_clock("") is None and parse_clock(None) is None and parse_clock("abc") is None and parse_clock("PT") is None)

# --- vor dem Anpfiff: volle Periode, KEINE leere-Uhr-Meldung
c = B(1, "7:00 pm ET", 0, "")
check("PRE: Phase, nicht live, 12:00, kein clock_missing", c.phase == gc.PRE and not c.is_live and c.seconds_left == 720 and not c.clock_missing and c.elapsed_total_s == 0)

# --- Viertel laeuft
c = B(2, "Q1 11:30", 1, "PT11M30.00S")
check("Q1 laeuft", c.phase == gc.Q1 and c.running and c.seconds_left == 690 and c.elapsed_regulation_s == 30 and not c.clock_missing)
c = B(2, "Q3 6:00", 3, "PT06M00.00S")
check("Q3 6:00: gespielt 24+6 Min.", c.phase == gc.Q3 and c.elapsed_regulation_s == 24 * 60 + 360)
c = B(2, "Q4 0:45", 4, "PT00M45.30S")
check("Q4 45,3 s", c.phase == gc.Q4 and abs(c.seconds_left - 45.3) < 1e-9 and c.running)

# --- LEERE UHR bei laufendem Spiel = Periodenende, kein 12:00-Fallback
c = B(2, "Halftime", 2, "")
check("Halbzeit (Text + leere Uhr): HALFTIME, 24 Min. gespielt, 0 s, KEIN clock_missing", c.phase == gc.HALFTIME and c.seconds_left == 0 and c.elapsed_regulation_s == 1440 and not c.clock_missing and not c.running)
c = B(2, "", 2, "")
check("Periode 2, leere Uhr, ohne Text: HALFTIME mit clock_missing", c.phase == gc.HALFTIME and c.seconds_left == 0 and c.clock_missing and c.elapsed_regulation_s == 1440)
c = B(2, "End of 1st", 1, "")
check("Viertelpause nach Q1 (Text erklaert die leere Uhr)", c.phase == gc.BREAK and c.seconds_left == 0 and c.elapsed_regulation_s == 720 and not c.clock_missing)
c = B(2, "", 3, "")
check("Viertelpause nach Q3 ohne Text: BREAK + clock_missing", c.phase == gc.BREAK and c.clock_missing and c.elapsed_regulation_s == 2160)
c = B(2, "", 4, "")
check("Ende Q4 mit leerer Uhr, noch nicht FINAL: REGULAR_END + clock_missing", c.phase == gc.REGULAR_END and c.clock_missing and c.elapsed_regulation_s == 2880 and c.ot_number == 0)
c = B(2, "Q2 0:00", 2, "PT00M00.00S")
check("Q2 mit Uhr 0:00 = HALFTIME ohne clock_missing", c.phase == gc.HALFTIME and not c.clock_missing)
c = B(2, "Q4 0:00", 4, "PT00M00.00S")
check("Q4 0:00 = REGULAR_END", c.phase == gc.REGULAR_END and not c.clock_missing)
check("kein Fall liefert 12:00 bei Pause", all(B(2, t, p, "").seconds_left == 0 for t in ("", "Halftime", "End of 2nd") for p in (1, 2, 3, 4)))

# --- Verlaengerung (5 Minuten)
c = B(2, "OT 3:00", 5, "PT03M00.00S")
check("OT1: Phase, 1. Verlaengerung, 2 Min. gespielt, regulaere Zeit voll", c.phase == gc.OT and c.ot_number == 1 and c.ot_elapsed_s == 120 and c.elapsed_regulation_s == 2880 and c.running)
c = B(2, "2OT 5:00", 6, "PT05M00.00S")
check("OT2 Beginn: 5 Min. aus OT1 schon gespielt", c.ot_number == 2 and c.ot_elapsed_s == 300 and c.elapsed_total_s == 2880 + 300)
c = B(2, "", 5, "")
check("OT mit leerer Uhr: OT, 0 s, clock_missing", c.phase == gc.OT and c.seconds_left == 0 and c.clock_missing and not c.running)

# --- FINAL
c = B(3, "Final", 4, "")
check("FINAL nach 4 Vierteln", c.phase == gc.FINAL and c.is_final and c.ot_number == 0 and c.elapsed_total_s == 2880 and not c.clock_missing)
c = B(3, "Final/OT", 5, "PT00M00.00S")
check("FINAL nach 1 OT: 2880 + 300 s", c.is_final and c.ot_number == 1 and c.elapsed_total_s == 2880 + 300)
c = B(3, "Final/2OT", 6, "")
check("FINAL nach 2 OT", c.ot_number == 2 and c.elapsed_total_s == 2880 + 600)

# --- Zusammenspiel Statuscode / Text / Periode
check("Statuscode fehlt: 'Final' im Text -> FINAL", B(None, "Final", 4, "").is_final)
check("Statuscode fehlt: Periode >= 1 -> live", B(None, "", 2, "PT05M00.00S").is_live)
check("Statuscode fehlt, Periode 0 -> PRE", B(None, "", 0, "").phase == gc.PRE)
check("Status 2 mit Periode 0 (Start) -> PRE", B(2, "", 0, "").phase == gc.PRE)
g = {"gameStatus": 2, "gameStatusText": "Q2 5:30", "period": 2, "gameClock": "PT05M30.00S"}
check("from_scoreboard_game", gc.from_scoreboard_game(g).phase == gc.Q2 and gc.from_scoreboard_game(g).seconds_left == 330)
check("from_simple_game (Text/Periode/Uhr der alten Liste)", gc.from_simple_game({"status": "Halftime", "period": 2, "clock": ""}).phase == gc.HALFTIME)

# --- Chrome-Version aus dem Browser
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    def app(name, short=None, versions=()):
        p = td / f"{name}.app" / "Contents"
        p.mkdir(parents=True)
        info = {"CFBundleShortVersionString": short} if short else {}
        (p / "Info.plist").write_bytes(plistlib.dumps(info))
        for v in versions:
            (p / "Frameworks" / f"{name} Framework.framework" / "Versions" / v).mkdir(parents=True)
        return td / f"{name}.app"
    chrome = app("Chrome", "152.0.7900.10")
    brave = app("Brave", "1.92.144", versions=("151.1.92.144", "Current"))
    check("Chrome-Info.plist: 152", nh.detect_chrome_major([chrome]) == 152)
    check("Brave: Plist ohne Chromium-Hauptversion -> Versions-Ordner 151", nh.detect_chrome_major([brave]) == 151)
    check("hoechste Version aus mehreren Browsern", nh.detect_chrome_major([brave, chrome]) == 152)
    check("kein Browser: Rueckfall", nh.detect_chrome_major([td / "gibt-es-nicht.app"]) == nh.FALLBACK_MAJOR)
    old = app("Alt", "120.0.1")
    check("veralteter Browser: nie unter dem Rueckfall", nh.detect_chrome_major([old]) == nh.FALLBACK_MAJOR)
    bad = app("Kaputt", "abc")
    check("unlesbare Version -> Rueckfall", nh.detect_chrome_major([bad]) == nh.FALLBACK_MAJOR)
h = nh.nba_headers(152)
check("Kopfzeilen: Chrome-UA, Origin, Referer (wie nba_live.py)", "Chrome/152.0.0.0" in h["User-Agent"] and h["Origin"] == "https://www.nba.com" and h["Referer"] == "https://www.nba.com/" and set(h) == {"User-Agent", "Origin", "Referer"})
from data import nba_live as nl
check("gleiche Form wie nba_live.NBA_HEADERS", set(h) == set(nl.NBA_HEADERS) and h["Origin"] == nl.NBA_HEADERS["Origin"] and h["Referer"] == nl.NBA_HEADERS["Referer"])

print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
