"""Tests fuer den Final-Abruf im Live-Feed (data/live_feed.py): nach dem Schlusspfiff wird GENAU EIN weiterer Boxscore geholt (bei Fehler nach der gemeinsamen Wartezeit erneut), erst danach
sind die Spielerpunkte dem Endstand entsprechend (players_complete) und Spieler-Wetten werden gewonnen/verloren/nicht gespielt. Alternativ final_box.json.gz des Recorders (nur lesen).
Offline: Attrappen, nichts ins Projekt geschrieben. Aufruf aus dem Projektordner: venv/bin/python tests/test_live_feed_final.py"""
import gzip, hashlib, json, os, shutil, sys, tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install(); fresh_env()
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ["NBAEDGE_LIVE_DIR"] = str(T / "live")
os.environ["NBAEDGE_FINAL_BOX_DIR"] = str(T / "final_boxes")
from data import day_bets_store as ds
from data import live_feed as lf

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def snap():
    files = list((ROOT / "data" / "tracking").glob("*.json")) + [ROOT / "data" / "pregame_lines.json"]
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.exists()}
real_before = snap()

T0 = datetime(2026, 10, 23, 4, 30, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
DAY, START = "2026-10-22", "2026-10-22T23:00:00Z"

class R:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text
    def json(self): return self._p

def row(status=2, period=4, clock="PT00M30.00S", text="", hs=80, as_=78):
    t = lambda c, n, tri, sc: {"teamCity": c, "teamName": n, "teamTricode": tri, "score": sc, "periods": []}
    return {"gameId": "G1", "gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock, "gameEt": f"{DAY}T19:00:00-04:00", "gameTimeUTC": START,
            "homeTeam": t("Philadelphia", "76ers", "PHI", hs), "awayTeam": t("Cleveland", "Cavaliers", "CLE", as_)}
def pl(pid, name, pts, mins, oncourt="1", played="1", status="ACTIVE"):
    return {"personId": pid, "name": name, "oncourt": oncourt, "played": played, "status": status, "statistics": {"points": pts, "minutes": f"PT{int(mins):02d}M00.00S", "foulsPersonal": 2}}
def boxgame(status=2, period=4, clock="PT00M30.00S", hs=80, as_=78, x=19):
    s = {"fieldGoalsAttempted": 30, "freeThrowsAttempted": 8, "reboundsOffensive": 4, "turnoversTotal": 5}
    return {"gameStatus": status, "period": period, "gameClock": clock,
            "homeTeam": {"score": hs, "statistics": dict(s), "teamTricode": "PHI", "players": [pl(1, "X Spieler", x, 30), pl(2, "Y Spieler", 10, 25), pl(3, "Z Bank", 0, 0, "0", "0", "INACTIVE")]},
            "awayTeam": {"score": as_, "statistics": dict(s), "teamTricode": "CLE", "players": []}}

class Net:
    def __init__(self):
        self.calls, self.row, self.box, self.box_status = [], row(), boxgame(), 200
    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        if "espn.com" in url:
            return R(200, {"events": []})
        if "scoreboard" in url:
            return R(200, {"scoreboard": {"gameDate": DAY, "games": [self.row]}})
        return R(self.box_status, {"game": self.box} if self.box_status == 200 else {}, text="x")
    def boxes(self): return sum(1 for u in self.calls if "boxscore_" in u)
    def reset(self): self.calls.clear()

BETS = {1: {"active": True, "name": "X Spieler", "milestone": 20, "odds": 2.0, "stake": 10.0}, 2: {"active": True, "name": "Y Spieler", "milestone": 25, "odds": 3.0, "stake": 5.0},
        3: {"active": True, "name": "Z Bank", "milestone": 5, "odds": 1.5, "stake": 20.0}}
def statuses(feed, t):
    gm = feed.state(t).games[0]
    return gm, {pid: v.state for pid, v in ds.evaluate_player_bets(BETS, gm).items()}

# --- laufendes Spiel: Boxscore alle 30 s, Spielerliste und players_complete
net = Net(); shutil.rmtree(T / "final_boxes", ignore_errors=True); feed = lf.LiveFeed(http_get=net.get, now=lambda: T0)
feed.refresh(T0)
gm, st = statuses(feed, T0)
check("laufend (80:78, Boxscore 80:78): Spielerliste da, players_complete, X 19 Punkte laeuft, Z (inaktiv) keine Daten-Fehler", len(gm.players) == 3 and gm.players_complete and st[1] == "laeuft" and st[2] == "laeuft", str(st))
check("kein Final-Abruf bei laufendem Spiel (1 Boxscore-Abruf)", net.boxes() == 1)

# --- Schlusspfiff: spaetes Koerbchen (82:78), erster Final-Abruf scheitert
net.row = row(status=3, period=4, clock="", text="Final", hs=82, as_=78)
net.box_status = 500
net.reset(); feed.refresh(T0 + 30)
gm, st = statuses(feed, T0 + 30)
check("Spiel beendet, Final-Abruf scheitert (HTTP 500): Spielerliste ist von vor dem Koerbchen -> players_complete False, Status 'unsicher' (nicht verloren/gewonnen)", gm.status == "FINAL" and not gm.players_complete and st[1] == "unsicher" and st[2] == "unsicher" and st[3] == "unsicher", str(st))
check("genau ein Abrufversuch in diesem Lauf; Wartezeit nach dem Fehler (kein Dauerfeuer)", net.boxes() == 1 and feed._next_allowed > T0 + 30)
net.reset(); [feed.refresh(T0 + 30 + k) for k in (5, 10, 20)]
check("waehrend der Wartezeit kein weiterer Abruf", net.boxes() == 0, str(net.calls))
# --- Wiederholung nach der Wartezeit, jetzt mit Endstand-Boxscore
net.box_status = 200; net.box = boxgame(status=3, clock="PT00M00.00S", hs=82, as_=78, x=21)
due = feed._next_allowed
net.reset(); feed.refresh(due)
gm, st = statuses(feed, due)
check("nach der Wartezeit ein Abruf: Boxscore = Endstand, players_complete True", net.boxes() == 1 and gm.players_complete and (gm.home_score, gm.away_score) == (82, 78))
check("Status erst jetzt entschieden: X (21 >= 20) gewonnen, Y (10 < 25) verloren, Z (0 Min.) nicht gespielt", st == {1: "gewonnen", 2: "verloren", 3: "nicht_gespielt"}, str(st))
prof = {pid: v.profit for pid, v in ds.evaluate_player_bets(BETS, gm).items()}
check("Gewinn/Verlust: +10,00 und -5,00, nicht gespielt ohne Gewinn/Verlust", prof == {1: 10.0, 2: -5.0, 3: None}, str(prof))
net.reset(); [feed.refresh(due + k) for k in (15, 45, 100, 400, 1000)]
check("danach nie wieder ein Boxscore-Abruf fuer dieses Spiel (genau EIN Final-Abruf erfolgreich)", net.boxes() == 0, str(net.calls))

# --- Boxscore hinkt (noch alter Stand): begrenzte Wiederholungen
net = Net(); shutil.rmtree(T / "final_boxes", ignore_errors=True); feed = lf.LiveFeed(http_get=net.get, now=lambda: T0); feed.refresh(T0)
net.row = row(status=3, period=4, clock="", text="Final", hs=82, as_=78)               # Box liefert weiter 80:78
for k in range(1, 40):
    feed.refresh(T0 + 30 * k)
gm, st = statuses(feed, T0 + 30 * 39)
check("Boxscore bleibt beim alten Stand: hoechstens 5 Final-Versuche, Status bleibt 'unsicher' (keine Endlosschleife, nie falsch 'verloren')", net.boxes() <= 1 + lf.FINAL_MAX_TRIES and st[1] == "unsicher" and not gm.players_complete, f"{net.boxes()} {st}")

# --- Recorder-Datei statt Netz
net = Net(); shutil.rmtree(T / "final_boxes", ignore_errors=True); feed = lf.LiveFeed(http_get=net.get, now=lambda: T0); feed.refresh(T0)
gdir = T / "live" / DAY / "G1"; gdir.mkdir(parents=True)
(gdir / "final_box.json.gz").write_bytes(gzip.compress(json.dumps({"game": boxgame(status=3, clock="PT00M00.00S", hs=82, as_=78, x=21)}).encode()))
net.row = row(status=3, period=4, clock="", text="Final", hs=82, as_=78); net.reset()
feed.refresh(T0 + 30)
gm, st = statuses(feed, T0 + 30)
check("final_box.json.gz des Recorders vorhanden und passend: kein Boxscore-Abruf, players_complete, Status entschieden", net.boxes() == 0 and gm.players_complete and st[1] == "gewonnen" and st[2] == "verloren", f"{net.boxes()} {st}")
(gdir / "final_box.json.gz").write_bytes(gzip.compress(json.dumps({"game": boxgame(status=3, clock="PT00M00.00S", hs=80, as_=78, x=19)}).encode()))
net = Net(); shutil.rmtree(T / "final_boxes", ignore_errors=True); feed = lf.LiveFeed(http_get=net.get, now=lambda: T0); feed.refresh(T0)
net.row = row(status=3, period=4, clock="", text="Final", hs=82, as_=78); net.box = boxgame(status=3, clock="PT00M00.00S", hs=82, as_=78, x=21); net.reset()
feed.refresh(T0 + 30)
check("Recorder-Datei passt nicht zum Endstand: wird nicht benutzt, Abruf bei NBA.com", net.boxes() == 1 and statuses(feed, T0 + 30)[1][1] == "gewonnen")
(gdir / "final_box.json.gz").write_bytes(b"kaputt")
net = Net(); shutil.rmtree(T / "final_boxes", ignore_errors=True); feed = lf.LiveFeed(http_get=net.get, now=lambda: T0); feed.refresh(T0)
net.row = row(status=3, period=4, clock="", text="Final", hs=82, as_=78); net.box = boxgame(status=3, clock="PT00M00.00S", hs=82, as_=78, x=21); net.reset()
feed.refresh(T0 + 30)
check("kaputte Recorder-Datei: kein Absturz, Abruf bei NBA.com", net.boxes() == 1 and statuses(feed, T0 + 30)[1][1] == "gewonnen")

# --- App-Start nach Spielende (Spiel war nie live in dieser Sitzung): ein Abruf holt die Spielerliste
net = Net(); net.row = row(status=3, period=4, clock="", text="Final", hs=82, as_=78); net.box = boxgame(status=3, clock="PT00M00.00S", hs=82, as_=78, x=21)
shutil.rmtree(T / "final_boxes", ignore_errors=True); feed = lf.LiveFeed(http_get=net.get, now=lambda: T0); feed.refresh(T0)
gm, st = statuses(feed, T0)
check("Start nach Spielende: ein Final-Abruf im ersten Lauf, Status direkt entschieden", net.boxes() == 1 and st[1] == "gewonnen" and gm.players_complete)

check("echte Dateien unveraendert", snap() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
