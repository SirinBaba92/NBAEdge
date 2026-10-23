"""Tests fuer data/live_feed.py (Baustein 4, Live-Feed): Spieltag-Umstellung, Spieleliste, Zwischenspeicher-Zeiten, Fehlerzustand mit letztem guten Stand und Pausenverdopplung,
ESPN-Fallback, Verbindung zum Live-Modell und zu den Wetten, gemeinsame Header mit dem alten Tab. Offline: Abrufe sind Attrappen (eigene Net-Klasse bzw. tests/fake_net.py), kein echter
Abruf, nichts wird ins Projekt geschrieben. Aufruf aus dem Projektordner: venv/bin/python tests/test_live_feed.py"""
import hashlib, os, sys, threading, time
from datetime import datetime
from statistics import NormalDist
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import requests
import fake_net
from fake_net import state as FN, fresh_env
fake_net.install(); fresh_env()
from data import day_bets_store as ds
from data import live_feed as lf
from data import nba_live as nl
from data.nba_headers import nba_headers
from engine import game_clock as gc
from engine import live_model as lm
import record_live as rl

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

BER = ZoneInfo("Europe/Berlin")
def berlin(y, m, d, hh, mm=0, ss=0): return datetime(y, m, d, hh, mm, ss, tzinfo=BER).timestamp()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
T0 = berlin(2026, 10, 23, 1, 0)                                      # Berlin 01:00 -> US-Spieltag 2026-10-22
DAY = "2026-10-22"
START_NIGHT = "2026-10-22T23:00:00Z"
def real_snapshot():
    """Hash aller echten Dateien, die der Test nie beschreiben darf (data/tracking/*.json inkl. day_bets.json, pregame_lines.json); fehlende Datei = fehlt im Ergebnis."""
    files = list((ROOT / "data" / "tracking").glob("*.json")) + [ROOT / "data" / "pregame_lines.json"]
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.exists()}
real_tracking = real_snapshot()                       # direkt vor dem Testlauf

# ----------------------------------------------------------------- Attrappe fuer den Abruf
class R:
    def __init__(self, status=200, payload=None, text="", bad_json=False):
        self.status_code, self._p, self.text, self._bad = status, payload, text, bad_json
    def json(self):
        if self._bad: raise ValueError("kein JSON")
        return self._p

class Net:
    def __init__(self):
        self.calls, self.rows, self.board_day, self.boxes = [], [], DAY, {}
        self.status, self.box_status, self.exc, self.espn, self.espn_status = 200, 200, None, {"events": []}, 200
        self.board_payload = None
    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, headers, params, timeout))
        if "espn.com" in url:
            return R(self.espn_status, self.espn)
        if self.exc is not None:
            raise self.exc
        if "scoreboard" in url:
            if self.status != 200:
                return R(self.status, {}, text="<HTML>Access Denied Reference&#32;&#35;18&#46;6e2a3517&#46;1792</HTML>")
            return R(200, self.board_payload if self.board_payload is not None else {"scoreboard": {"gameDate": self.board_day, "games": self.rows}})
        gid = url.rsplit("_", 1)[1].split(".")[0]
        if self.box_status != 200:
            return R(self.box_status, {})
        return R(200, {"game": self.boxes.get(gid, box())})
    def kinds(self): return [("espn" if "espn" in c[0] else "board" if "scoreboard" in c[0] else "box") for c in self.calls]
    def count(self, kind): return self.kinds().count(kind)
    def reset(self): self.calls.clear()

def team(city, name, tri, score, periods=()):
    return {"teamCity": city, "teamName": name, "teamTricode": tri, "score": score, "periods": [{"period": i + 1, "score": s} for i, s in enumerate(periods)]}

def row(gid, status=2, period=3, clock="PT06M00.00S", text="", hs=85, as_=60, home=("Philadelphia", "76ers", "PHI"), away=("Cleveland", "Cavaliers", "CLE"), start=START_NIGHT, day=DAY, periods=((), ())):
    return {"gameId": gid, "gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock, "gameEt": f"{day}T19:00:00-04:00", "gameTimeUTC": start,
            "homeTeam": team(*home, hs, periods[0]), "awayTeam": team(*away, as_, periods[1])}

def box(fga=60, fta=20, oreb=8, tov=10):
    s = {"fieldGoalsAttempted": fga, "freeThrowsAttempted": fta, "reboundsOffensive": oreb, "turnoversTotal": tov}
    return {"homeTeam": {"statistics": dict(s)}, "awayTeam": {"statistics": dict(s)}}

def feed_with(net, now=T0):
    return lf.LiveFeed(http_get=net.get, now=lambda: now)

# ----------------------------------------------------------------- Spieltag: Umstellung um 17:00 deutscher Zeit
check("16:59:59 Berlin = Vortag, 17:00:00 = heute", lf.current_us_day(berlin(2026, 10, 23, 16, 59, 59)) == "2026-10-22" and lf.current_us_day(berlin(2026, 10, 23, 17, 0, 0)) == "2026-10-23")
check("nachts 01:00 und mittags 12:00 Berlin: noch der Spieltag vom Vortag", lf.current_us_day(berlin(2026, 10, 23, 1)) == "2026-10-22" and lf.current_us_day(berlin(2026, 10, 23, 12)) == "2026-10-22")
check("Sommerzeit (Juli): Umstellung bei 17:00 Berliner Uhrzeit (UTC 15:00)", lf.current_us_day(berlin(2026, 7, 15, 16, 59, 59)) == "2026-07-14" and lf.current_us_day(berlin(2026, 7, 15, 17)) == "2026-07-15")
check("Winterzeit (Dezember): Umstellung bei 17:00 Berliner Uhrzeit (UTC 16:00)", lf.current_us_day(berlin(2026, 12, 15, 16, 59, 59)) == "2026-12-14" and lf.current_us_day(berlin(2026, 12, 15, 17)) == "2026-12-15")
check("Tag der Zeitumstellung (25.10.2026, Berlin Winterzeit ab 03:00): 16:59 / 17:00", lf.current_us_day(berlin(2026, 10, 25, 16, 59, 59)) == "2026-10-24" and lf.current_us_day(berlin(2026, 10, 25, 17)) == "2026-10-25")
check("Frühjahr (29.03.2026, Sommerzeit ab 02:00): 16:59 / 17:00", lf.current_us_day(berlin(2026, 3, 29, 16, 59, 59)) == "2026-03-28" and lf.current_us_day(berlin(2026, 3, 29, 17)) == "2026-03-29")
check("Utc-Zeitpunkt: 15:00:00Z im Sommer = 17:00 Berlin = neuer Tag, 15:00:00Z im Winter = 16:00 Berlin = Vortag",
      lf.current_us_day(datetime(2026, 7, 15, 15, 0, tzinfo=ZoneInfo("UTC")).timestamp()) == "2026-07-15" and lf.current_us_day(datetime(2026, 12, 15, 15, 0, tzinfo=ZoneInfo("UTC")).timestamp()) == "2026-12-14")
check("gleiche Regel wie der Recorder (record_live.current_us_day) ueber 4000 Zeitpunkte quer durch das Jahr, auch Umstellungstage", all(lf.current_us_day(t) == rl.current_us_day(t) for t in range(1_774_000_000, 1_774_000_000 + 4000 * 2400, 2400)))
check("US-Spieldatum eines Spiels: aus gameEt, sonst aus UTC (02:00Z = Vortag 22:00 ET), sonst Rueckfall", lf.game_day_us({"gameEt": "2026-10-22T19:00:00-04:00"}) == "2026-10-22" and lf.game_day_us({"gameTimeUTC": "2026-10-23T02:00:00Z"}) == "2026-10-22" and lf.game_day_us({}, "2026-10-21") == "2026-10-21")

# ----------------------------------------------------------------- Spieleliste (auch vor dem Anpfiff), Phasen ohne Uhr, Verlaengerung
net = Net()
net.rows = [row("G1", status=1, period=0, clock="", text="7:00 pm ET", hs=0, as_=0, start="2026-10-22T23:00:00Z"),
            row("G2", status=2, period=3, clock="PT06M00.00S", hs=85, as_=60, home=("Oklahoma City", "Thunder", "OKC"), away=("Denver", "Nuggets", "DEN"), start="2026-10-23T01:30:00Z"),
            row("G3", status=2, period=2, clock="", text="Halftime", hs=58, as_=55, home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"), start="2026-10-23T00:00:00Z"),
            row("G4", status=2, period=4, clock="", text="", hs=100, as_=100, home=("Detroit", "Pistons", "DET"), away=("Chicago", "Bulls", "CHI"), start="2026-10-22T23:30:00Z"),
            row("G5", status=2, period=5, clock="PT02M00.00S", hs=110, as_=110, home=("Utah", "Jazz", "UTA"), away=("Phoenix", "Suns", "PHX"), start="2026-10-23T02:00:00Z"),
            row("G6", status=3, period=4, clock="", text="Final", hs=120, as_=101, home=("Houston", "Rockets", "HOU"), away=("Dallas", "Mavericks", "DAL"), start="2026-10-22T22:00:00Z"),
            row("G7", status=2, period=1, clock="", text="End of 1st", hs=30, as_=28, home=("Miami", "Heat", "MIA"), away=("Orlando", "Magic", "ORL"), start="2026-10-22T22:30:00Z"),
            row("G8", status=2, period=6, clock="PT04M10.00S", hs=130, as_=128, home=("Atlanta", "Hawks", "ATL"), away=("Brooklyn", "Nets", "BKN"), start="2026-10-23T03:00:00Z"),
            row("G9", status=3, period=6, clock="", text="Final/2OT", hs=135, as_=131, home=("Toronto", "Raptors", "TOR"), away=("Indiana", "Pacers", "IND"), start="2026-10-22T21:00:00Z"),
            row("OLD", status=3, period=4, clock="", text="Final", hs=99, as_=98, home=("Memphis", "Grizzlies", "MEM"), away=("Sacramento", "Kings", "SAC"), start="2026-10-22T02:00:00Z", day="2026-10-21")]
net.boxes = {"G2": box(60, 20, 8, 10), "G3": box(50, 10, 5, 8)}
feed = feed_with(net)
st = feed.refresh(T0)
G = {g.game_id: g for g in st.games}
check("Spieltag 22.10.: 9 Spiele des Tages, Spiel vom Vortag getrennt in other_day_games", st.day == DAY and len(st.games) == 9 and [g.game_id for g in st.other_day_games] == ["OLD"] and "OLD" not in G)
check("Spiele nach Anpfiff sortiert (UTC-Zeit, dann game_id)", [g.start_utc for g in st.games] == sorted(g.start_utc for g in st.games))
check("noch nicht begonnenes Spiel steht in der Liste: PRE, 0:0, Anpfiff UTC, keine Uhr", G["G1"].status == "PRE" and G["G1"].status_text == "Vor dem Anpfiff" and G["G1"].clock.phase == gc.PRE and G["G1"].start_utc == "2026-10-22T23:00:00Z" and (G["G1"].home_score, G["G1"].away_score) == (0, 0) and G["G1"].clock_label == "")
check("Spielstand und Namen: Heim/Gast, Vollname + Spitzname + Kuerzel", G["G2"].home == "Oklahoma City Thunder" and G["G2"].away == "Denver Nuggets" and G["G2"].home_nick == "Thunder" and G["G2"].home_tricode == "OKC" and (G["G2"].home_score, G["G2"].away_score) == (85, 60))
check("laufendes Viertel: LIVE, Q3 6:00, laeuft", G["G2"].status == "LIVE" and G["G2"].status_text == "läuft" and G["G2"].clock_label == "Q3 6:00" and G["G2"].clock.seconds_left == 360 and G["G2"].running)
check("Halbzeit (leere Uhr, Statustext Halftime): PAUSE, 'Halbzeit', 0 s statt 12:00, kein clock_missing", G["G3"].status == "PAUSE" and G["G3"].status_text == "Halbzeit" and G["G3"].clock_label == "Halbzeit" and G["G3"].clock.seconds_left == 0 and not G["G3"].clock.clock_missing and G["G3"].clock.phase == gc.HALFTIME)
check("Periodenende Q4 mit leerer Uhr ohne Text: PAUSE, 'Ende Q4', 0 s, clock_missing gemeldet (kein 12:00-Fallback)", G["G4"].status == "PAUSE" and G["G4"].clock.phase == gc.REGULAR_END and G["G4"].clock.seconds_left == 0 and G["G4"].clock.clock_missing and G["G4"].clock_label == "Ende Q4" and G["G4"].status_text == "Ende Q4")
check("Viertelpause 'End of 1st' mit leerer Uhr: PAUSE, 'Pause nach Q1', 0 s", G["G7"].status == "PAUSE" and G["G7"].clock.phase == gc.BREAK and G["G7"].clock_label == "Pause nach Q1" and G["G7"].clock.seconds_left == 0)
check("Verlaengerung laeuft: LIVE, 'OT 2:00', 1. OT; 2. Verlaengerung '2OT 4:10'", G["G5"].status == "LIVE" and G["G5"].clock_label == "OT 2:00" and G["G5"].clock.ot_number == 1 and G["G8"].clock_label == "2OT 4:10" and G["G8"].clock.ot_number == 2)
check("beendet: FINAL, 'Ende', nach Verlaengerung 'Ende (2OT)'", G["G6"].status == "FINAL" and G["G6"].status_text == "beendet" and G["G6"].clock_label == "Ende" and G["G9"].clock_label == "Ende (2OT)" and G["G9"].clock.ot_number == 2 and G["G9"].clock.elapsed_total_s == 2880 + 600)
check("keine einzige Pause mit 12:00 (seconds_left der Pausen = 0)", all(G[i].clock.seconds_left == 0 for i in ("G3", "G4", "G7")))
check("Zustand nach erstem Abruf: Quelle NBA.com, nicht veraltet, kein Fehler, Alter 0", st.source == "NBA.com" and not st.stale and st.error is None and st.age_s == 0 and st.stale_since_s is None and st.error_status is None and st.scoreboard_day == DAY and st.status_line.startswith("NBA.com"))

# ----------------------------------------------------------------- Boxscore nur fuer laufende Spiele; Besitze
live_ids = sorted(g.game_id for g in st.games if g.clock.is_live)
fetched = sorted(c[0].rsplit("_", 1)[1].split(".")[0] for c in net.calls if "boxscore" in c[0])
check("Boxscore nur fuer Spiele mit Status 'laeuft' laut Scoreboard (auch Halbzeit/Periodenende, nicht PRE/beendet/Vortag)", fetched == live_ids == ["G2", "G3", "G4", "G5", "G7", "G8"] and net.count("board") == 1, str(fetched))
check("Besitze aus dem Boxscore (FGA + 0,44 FTA - OREB + TOV je Team), Alter und kein Fehler", abs(G["G2"].possessions.home - (60 + 0.44 * 20 - 8 + 10)) < 1e-9 and G["G2"].box_age_s == 0 and G["G2"].box_error is None and G["G1"].possessions is None and G["G6"].possessions is None)

# ----------------------------------------------------------------- Zwischenspeicher: Scoreboard 15 s, Boxscore 30 s
net = Net(); net.rows = [row("A1"), row("A2", status=1, period=0, clock="", hs=0, as_=0), row("A3", home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"))]
feed = feed_with(net)
feed.refresh(T0)
check("erster Abruf: 1 Scoreboard + 2 Boxscores (A1, A3)", net.kinds() == ["board", "box", "box"], str(net.kinds()))
net.reset(); [feed.refresh(T0 + s) for s in (1, 5, 10, 14.9)]
check("Oberflaeche fragt oefter (1 s, 5 s, 10 s, 14,9 s): kein neuer Abruf", net.calls == [])
net.reset(); feed.refresh(T0 + 15)
check("nach 15 s: Scoreboard neu, Boxscores noch nicht (30 s)", net.kinds() == ["board"], str(net.kinds()))
net.reset(); feed.refresh(T0 + 29.9)
check("nach 29,9 s: nichts", net.calls == [])
net.reset(); feed.refresh(T0 + 30)
check("nach 30 s: Scoreboard und beide Boxscores", net.kinds() == ["board", "box", "box"], str(net.kinds()))
net = Net(); net.rows = [row("A1"), row("A2", status=1, period=0, clock="", hs=0, as_=0), row("A3", home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"))]
feed = feed_with(net)
for s in range(0, 61):
    feed.refresh(T0 + s)
check("jede Sekunde 61 Sekunden lang gefragt: Scoreboard 5 x (0, 15, 30, 45, 60 s), Boxscore je Spiel 3 x (0, 30, 60 s)", net.count("board") == 5 and net.count("box") == 6, f"{net.count('board')} / {net.count('box')}")
check("Alter der Daten wird mitgefuehrt (Box 30 s alt ohne neuen Abruf)", feed.state(T0 + 75).games[0].box_age_s == 15 and feed.state(T0 + 75).age_s == 15)

# ----------------------------------------------------------------- Fehler: 403 mit letztem guten Stand und Pausenverdopplung
net = Net(); net.rows = [row("B1", status=2), row("B2", status=1, period=0, clock="", hs=0, as_=0, home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"))]
feed = feed_with(net)
good = feed.refresh(T0)
net.status = 403
net.reset()
s1 = feed.refresh(T0 + 15)
check("403: letzter guter Stand bleibt (gleiche Spiele, gleicher Stand), Fehlermeldung mit Statuscode und Referenz", [(g.game_id, g.home_score) for g in s1.games] == [(g.game_id, g.home_score) for g in good.games] and "HTTP 403" in s1.error and "Zugriff abgelehnt" in s1.error
      and s1.error_status == 403 and s1.error_ref == "18.6e2a3517.1792", str(s1.error))
check("403: Zustand veraltet mit Alter in Sekunden ('Daten veraltet seit 15 Sekunden') und naechstem Versuch", s1.stale and s1.age_s == 15 and s1.stale_since_s == 15 and "Daten veraltet seit 15 Sekunden" in s1.status_line and "nächster Versuch in 30 s" in s1.status_line and s1.retry_in_s == 30 and s1.backoff_s == 30, s1.status_line)
net.reset(); [feed.refresh(T0 + 15 + s) for s in (1, 10, 20, 29)]
check("waehrend der Pause keine NBA.com-Abrufe (Oberflaeche fragt weiter), Alter waechst", net.count("board") == 0 and net.count("box") == 0 and feed.state(T0 + 40).stale_since_s == 40 and feed.state(T0 + 40).retry_in_s == 5)
waits, t = [], T0 + 15
for i in range(7):
    due = t + feed._backoff.wait                      # naechster erlaubter Versuch
    net.reset(); feed.refresh(due - 0.5)
    early = net.count("board")
    net.reset(); s = feed.refresh(due)
    waits.append((early, net.count("board"), s.backoff_s))
    t = due
check("Pausenverdopplung 30 -> 60 -> 120 -> 240 -> 300 -> 300 -> 300 s, vor Ablauf nie ein Abruf, danach genau einer", [w[2] for w in waits] == [60, 120, 240, 300, 300, 300, 300] and all(w[0] == 0 and w[1] == 1 for w in waits), str(waits))
check("Spiele und Stand bleiben die ganze Zeit erhalten", [g.game_id for g in feed.state(t).games] == ["B1", "B2"] and feed.state(t).games[0].home_score == 85)
net.status = 200; net.reset()
due = feed._next_allowed
feed.refresh(due)
rec = feed.state(due)
check("Erfolg: Fehler weg, Wartezeit zurueckgesetzt, Quelle NBA.com", rec.error is None and not rec.stale and rec.backoff_s == 0 and rec.source == "NBA.com" and rec.fallback_note is None and rec.retry_in_s is None)

net.status = 429; feed2 = feed_with(net); feed2.refresh(T0)
check("erster Abruf scheitert mit 429: Meldung 'zu viele Anfragen (HTTP 429)', keine Spiele, 'Noch keine Daten', kein Absturz", feed2.state(T0).error.startswith("NBA.com: zu viele Anfragen (HTTP 429)") and feed2.state(T0).games == () and feed2.state(T0).age_s is None
      and feed2.state(T0).status_line.startswith("Noch keine Daten") and feed2.state(T0).stale)
net.status = 200
for name, exc, msg in (("Timeout", requests.exceptions.Timeout("t"), "keine Antwort (Zeitüberschreitung)"), ("Verbindungsfehler", requests.exceptions.ConnectionError("dns"), "keine Verbindung"), ("unbekannte Ausnahme", RuntimeError("boom"), "keine Verbindung")):
    n2 = Net(); n2.rows = [row("C1")]; f2 = feed_with(n2); f2.refresh(T0)
    n2.exc = exc; s = f2.refresh(T0 + 15)
    check(f"{name}: letzter guter Stand bleibt, Meldung '{msg}', Statuscode leer, Pause 30 s", s.error is not None and msg in s.error and s.error_status is None and len(s.games) == 1 and s.stale and s.backoff_s == 30, str(s.error))
n3 = Net(); n3.rows = [row("D1")]; f3 = feed_with(n3); f3.refresh(T0)
class BadJson(R):
    def json(self): raise ValueError("kein JSON")
n3.get_orig = n3.get
n3.get = lambda url, headers=None, params=None, timeout=None: BadJson(200, None, text="<html>") if "scoreboard" in url else n3.get_orig(url, headers, params, timeout)
f3._http_get = n3.get
s = f3.refresh(T0 + 15)
check("200 mit kaputtem JSON: Meldung 'ungueltige Antwort (kein JSON, HTTP 200)', letzter guter Stand bleibt", "kein JSON" in s.error and "HTTP 200" in s.error and len(s.games) == 1 and s.error_status == 200 and s.stale)
for name, payload in (("unerwartetes Format", {"foo": 1}), ("games keine Liste", {"scoreboard": {"games": "x"}}), ("Liste statt Objekt", [1, 2]), ("leeres Objekt", {})):
    n4 = Net(); n4.rows = [row("E1")]; f4 = feed_with(n4); f4.refresh(T0)
    n4.board_payload = payload; s = f4.refresh(T0 + 15)
    check(f"Antwort mit {name}: Meldung 'unerwartetes Format', alter Stand bleibt, keine Ausnahme", s.error is not None and ("unerwartetes Format" in s.error or "kein JSON" in s.error) and len(s.games) == 1, str(s.error))
class Weird: pass
n5 = Net(); n5.rows = [row("F1")]; f5 = feed_with(n5); f5.refresh(T0)
f5._http_get = lambda *a, **k: Weird()
s = f5.refresh(T0 + 15)
check("Antwortobjekt ohne Statuscode/JSON: keine Ausnahme, Fehlerzustand mit letztem Stand", s.error is not None and len(s.games) == 1 and s.stale)
n6 = Net(); n6.rows = [row("H1"), {"homeTeam": {}, "awayTeam": {}}, row("H2", home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"))]
check("kaputte Zeile (ohne gameId) wird uebersprungen, die uebrigen Spiele bleiben", [g.game_id for g in feed_with(n6).refresh(T0).games] == ["H1", "H2"])

# ----------------------------------------------------------------- Boxscore-Fehler: letzter guter Boxscore bleibt, Scoreboard nicht betroffen
net = Net(); net.rows = [row("K1")]; net.boxes = {"K1": box(60, 20, 8, 10)}
feed = feed_with(net); feed.refresh(T0)
net.box_status = 403; net.reset()
s = feed.refresh(T0 + 30)
g = s.games[0]
check("Boxscore 403 nach 30 s: Besitze vom letzten guten Boxscore bleiben, Fehlermeldung am Spiel, Box-Alter 30 s, Scoreboard-Zustand ohne Fehler", g.possessions is not None and abs(g.possessions.home - 70.8) < 1e-9 and "HTTP 403" in g.box_error and g.box_age_s == 30 and s.error is None and not s.stale)
net.reset(); feed.refresh(T0 + 45); feed.refresh(T0 + 59)
check("nach Boxscore-Fehler gilt die gemeinsame Pause (30 s): bis dahin auch kein Scoreboard-Abruf", net.calls == [])
net.box_status = 200; net.reset(); feed.refresh(T0 + 60)
check("danach wieder Abrufe; Boxscore-Erfolg loescht den Box-Fehler", net.count("board") == 1 and net.count("box") == 1 and feed.state(T0 + 60).games[0].box_error is None and feed.state(T0 + 60).games[0].box_age_s == 0)

# Boxscore mit unerwartetem Format (gueltiges JSON, aber ohne Teamwerte): nur dieses Spiel meldet den Fehler, KEINE gemeinsame Pause, Scoreboard laeuft weiter
net = Net(); net.rows = [row("K2"), row("K3", home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"))]; net.boxes = {"K2": {"homeTeam": {}, "awayTeam": {}}, "K3": box()}
feed = feed_with(net); s = feed.refresh(T0)
check("Boxscore mit unerwartetem Format (K2): Fehlermeldung am Spiel, Besitze leer; anderes Spiel (K3) mit Besitzen; Scoreboard-Zustand ohne Fehler", {g.game_id: (g.possessions is not None, g.box_error is not None) for g in s.games} == {"K2": (False, True), "K3": (True, False)} and s.error is None and not s.stale and s.backoff_s == 0)
net.reset(); feed.refresh(T0 + 15)
check("danach keine gemeinsame Pause: Scoreboard nach 15 s wieder dran", net.count("board") == 1)

# ----------------------------------------------------------------- Spieltag noch Vortag auf dem Scoreboard (zwischen 17:00 und der Freischaltung)
net = Net(); net.rows = [row("L1", status=3, period=4, clock="", text="Final", day="2026-10-21", start="2026-10-22T02:00:00Z")]; net.board_day = "2026-10-21"
feed = feed_with(net, berlin(2026, 10, 22, 17, 30)); s = feed.refresh(berlin(2026, 10, 22, 17, 30))
check("17:30 Berlin: neuer Spieltag 22.10., Scoreboard zeigt noch den 21.10.: keine Spiele des Tages, Hinweistext, Vortag-Spiele getrennt", s.day == "2026-10-22" and s.games == () and len(s.other_day_games) == 1 and "zeigt noch den Spieltag 2026-10-21" in s.notice and s.scoreboard_day == "2026-10-21")
net.rows = [row("L2", status=1, period=0, clock="", hs=0, as_=0, day="2026-10-22")]; net.board_day = "2026-10-22"
s = feed.refresh(berlin(2026, 10, 22, 18, 1))
check("Scoreboard springt auf den 22.10.: Spiele erscheinen, kein Hinweis mehr", [g.game_id for g in s.games] == ["L2"] and s.notice is None and s.other_day_games == ())
check("explizit gewaehlter Spieltag (day=...) ueberschreibt die Uhr", feed.state(berlin(2026, 10, 22, 18, 1), day="2026-10-21").day == "2026-10-21" and feed.state(berlin(2026, 10, 22, 18, 1), day="2026-10-21").games == ())

# ----------------------------------------------------------------- ESPN-Fallback
def espn_event(eid, home, away, state_, period, clock, detail, hs, as_, date="2026-10-22T23:00Z", hnick=None, anick=None):
    return {"id": eid, "date": date, "status": {"clock": 0.0, "displayClock": clock, "period": period, "type": {"state": state_, "detail": detail, "description": detail}},
            "competitions": [{"competitors": [{"homeAway": "home", "score": str(hs), "team": {"displayName": home, "name": hnick or home.split()[-1]}},
                                              {"homeAway": "away", "score": str(as_), "team": {"displayName": away, "name": anick or away.split()[-1]}}]}]}
def base_net():
    n = Net(); n.rows = [row("M1", status=2, period=3, clock="PT06M00.00S", hs=85, as_=60), row("M2", status=1, period=0, clock="", hs=0, as_=0, home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"), start="2026-10-23T00:00:00Z")]
    return n
net = base_net(); feed = feed_with(net); feed.refresh(T0)
net.status = 403
net.espn = {"events": [espn_event("401", "Philadelphia 76ers", "Cleveland Cavaliers", "in", 4, "3:00", "3:00 - 4th Quarter", 90, 70),
                       espn_event("402", "Boston Celtics", "Miami Heat", "pre", 0, "0.0", "Thu, October 22nd at 8:00 PM EDT", 0, 0, date="2026-10-23T00:00Z")]}
net.reset(); s = feed.refresh(T0 + 15)
G = {g.game_id: g for g in s.games}
check("NBA.com 403 -> ESPN springt ein: Stand, Uhr, Status von ESPN, Quelle 'ESPN' am Zustand und am Spiel", s.source == "ESPN" and G["M1"].source == "ESPN" and (G["M1"].home_score, G["M1"].away_score) == (90, 70) and G["M1"].clock.phase == gc.Q4 and G["M1"].clock.seconds_left == 180 and G["M1"].clock_label == "Q4 3:00"
      and G["M2"].status == "PRE" and net.count("espn") == 1, str(s.fallback_note))
check("ESPN-Zustand: NBA.com-Fehler bleibt sichtbar (mit Statuscode), Daten gelten als frisch (nicht veraltet), klare Zeile 'Quelle ESPN', Hinweis nennt 2 von 2 Spielen", s.error_status == 403 and "HTTP 403" in s.error and not s.stale and s.stale_since_s is None and s.status_line.startswith("Quelle ESPN") and "2 von 2" in s.fallback_note)
check("ESPN-Abruf nur mit Datum des Spieltags und ohne NBA-Header (kein Origin)", net.calls[-1][2] == {"dates": "20261022"} and "Origin" not in (net.calls[-1][1] or {}) and "espn.com" in net.calls[-1][0])
net.reset(); [feed.refresh(T0 + 15 + s_) for s_ in (1, 10, 20, 29)]
check("ESPN hoechstens alle 30 s (Oberflaeche fragt weiter)", net.count("espn") == 0)
net.reset(); feed.refresh(T0 + 45)
check("nach 30 s wieder ESPN-Abruf (und NBA.com-Versuch nach der 30-s-Pause)", net.count("espn") == 1 and net.count("board") == 1, str(net.kinds()))
net.status = 200; net.reset(); due = feed._next_allowed
feed.refresh(due)
s = feed.state(due)
check("NBA.com wieder da: Quelle NBA.com, Spiele wieder von NBA.com, kein Fehler, Fallback-Hinweis weg", s.source == "NBA.com" and all(g.source == "NBA.com" for g in s.games) and s.error is None and s.fallback_note is None and s.games[0].home_score == 85)
net = base_net(); feed = feed_with(net); feed.refresh(T0); net.status = 403
net.espn = {"events": [espn_event("401", "Philadelphia 76ers", "Cleveland Cavaliers", "in", 4, "3:00", "x", 90, 70), espn_event("499", "Philadelphia 76ers", "Cleveland Cavaliers", "pre", 0, "0.0", "y", 0, 0, date="2026-10-23T01:00Z")]}
s = feed.refresh(T0 + 15)
check("Zuordnung unsicher (zwei ESPN-Spiele passen zu einem NBA-Spiel): KEIN Fallback, Quelle bleibt NBA.com, Stand unveraendert, 'Zuordnung unsicher' im Hinweis, Daten veraltet", s.source == "NBA.com" and s.games[0].source == "NBA.com" and s.games[0].home_score == 85 and "Zuordnung unsicher" in s.fallback_note and s.stale)
net = base_net(); feed = feed_with(net); feed.refresh(T0); net.status = 403
net.espn = {"events": [espn_event("401", "Los Angeles Lakers", "Golden State Warriors", "in", 4, "3:00", "x", 90, 70)]}
s = feed.refresh(T0 + 15)
check("ESPN kennt keines der Spiele: kein Fallback, Hinweis 'keine zuordenbaren Spiele'", s.source == "NBA.com" and "keine zuordenbaren" in s.fallback_note and s.stale and s.games[0].home_score == 85)
net = base_net(); feed = feed_with(net); feed.refresh(T0); net.status = 403
net.espn = {"events": [espn_event("401", "Philadelphia 76ers", "Cleveland Cavaliers", "in", 4, "3:00", "x", 90, 70, date="2026-10-22T15:00Z"), espn_event("402", "Boston Celtics", "Miami Heat", "pre", 0, "0.0", "y", 0, 0, date="2026-10-23T00:00Z")]}
s = feed.refresh(T0 + 15)
check("Anpfiff weicht mehr als 3 Stunden ab: Spiel wird nicht zugeordnet (M1 bleibt NBA.com-Stand), M2 wird zugeordnet (kein unsicherer Fall)", {g.game_id: g.source for g in s.games} == {"M1": "NBA.com", "M2": "ESPN"} and s.games[0].home_score == 85 and "1 von 2" in s.fallback_note)
net = base_net(); feed = feed_with(net); feed.refresh(T0); net.status = 403; net.espn_status = 500
s = feed.refresh(T0 + 15)
check("ESPN selbst faellt aus (HTTP 500): kein Fallback, Meldung im Hinweis, Daten veraltet, keine Ausnahme", s.source == "NBA.com" and "HTTP 500" in s.fallback_note and s.stale and s.games[0].home_score == 85)
net = Net(); net.rows = [row("N1")]; net.status = 403
feed = feed_with(net); s = feed.refresh(T0)
check("NBA.com scheitert schon beim allerersten Abruf: ESPN wird NICHT gefragt (kein bekannter Stand zum Zuordnen), Hinweis erklaert es", net.count("espn") == 0 and s.games == () and "keinen NBA.com-Stand" in s.fallback_note)
net = base_net(); feed = feed_with(net); feed.refresh(T0); net.status = 403
net.espn = {"events": [espn_event("401", "Philadelphia 76ers", "Cleveland Cavaliers", "in", 2, "0.0", "Halftime", 60, 50), espn_event("402", "Boston Celtics", "Miami Heat", "in", 1, "0.0", "End of 1st Quarter", 30, 28)]}
s = feed.refresh(T0 + 15)
G = {g.game_id: g for g in s.games}
check("ESPN: Halbzeit ('Halftime', Uhr 0.0) und Viertelende ('End of 1st Quarter') ohne 12:00", G["M1"].clock.phase == gc.HALFTIME and G["M1"].clock_label == "Halbzeit" and G["M1"].status == "PAUSE" and G["M2"].clock.phase == gc.BREAK and G["M2"].clock_label == "Pause nach Q1" and G["M2"].clock.seconds_left == 0)
net = base_net(); feed = feed_with(net); feed.refresh(T0); net.status = 403
net.espn = {"events": [espn_event("401", "Philadelphia 76ers", "Cleveland Cavaliers", "post", 4, "0.0", "Final", 110, 100), espn_event("402", "Boston Celtics", "Miami Heat", "in", 5, "2:00", "2:00 - 1st OT", 120, 120)]}
G = {g.game_id: g for g in feed.refresh(T0 + 15).games}
check("ESPN: Spielende (post) und Verlaengerung (Periode 5, 2:00)", G["M1"].status == "FINAL" and G["M1"].clock_label == "Ende" and G["M2"].clock_label == "OT 2:00" and G["M2"].clock.ot_number == 1)
net = base_net(); feed = feed_with(net); feed.refresh(T0); poss0 = feed.state(T0).games[0].possessions; net.status = 403
net.espn = {"events": [espn_event("401", "Philadelphia 76ers", "Cleveland Cavaliers", "in", 4, "3:00", "x", 90, 70)]}
g1 = feed.refresh(T0 + 15).games[0]
check("ESPN-Stand: Besitze bleiben die letzten aus NBA.com (nicht geloescht, Box-Alter waechst)", g1.possessions == poss0 and g1.box_age_s == 15 and g1.source == "ESPN")

# ----------------------------------------------------------------- Verbindung zum Live-Modell: Anker aus dem Schnappschuss, Uhr, Stand, Besitze
def snap_version(total=230.0, spread=8.1, home=119.0, away=111.0, p=0.7303, version="2"):
    return {"projection": {"exp_total": total, "exp_spread": spread, "home_score": home, "away_score": away, "home_win_prob": p}, "sigmas": {"spread": 13.2, "total": 18.6, "team_total": 11.6}, "sigmas_version": version}
snaps = {"2026-10-22|2026-10-22T23:00:00Z|Philadelphia 76ers|Cleveland Cavaliers": {"game_date": DAY, "home": "Philadelphia 76ers", "away": "Cleveland Cavaliers", "versions": [{"hash": "alt"}, snap_version()]},
         "2026-10-22|2026-10-23T00:00:00Z|Boston Celtics|Miami Heat": {"game_date": DAY, "home": "Boston Celtics", "away": "Miami Heat", "versions": [snap_version(225.0, 3.0, 114.0, 111.0, round(NormalDist().cdf(3.0 / 13.2), 4))]}}
net = base_net(); net.boxes = {"M1": box(60, 20, 8, 10)}
feed = feed_with(net); st = feed.refresh(T0)
nums = lf.live_numbers_for_state(st, snaps)
check("Live-Zahlen je Spiel des Tages; laufendes Spiel mit Anker, Uhr (Q3 6:00), Stand 85:60 und Besitzen", set(nums) == {"M1", "M2"} and nums["M1"].has_anchor and nums["M1"].projection.phase == gc.Q3 and (nums["M1"].projection.home_pts, nums["M1"].projection.away_pts) == (85, 60) and nums["M1"].projection.pace_weight > 0
      and nums["M1"].snapshot_key.endswith("Philadelphia 76ers|Cleveland Cavaliers") and nums["M1"].note is None)
check("Live-Zahlen: Sieger Heim bei 85:60 in Q3 deutlich ueber der Vorab-Chance, Total Over/Team Total/Spread liefern Zahlen", nums["M1"].p_winner("home") > 0.9 and abs(nums["M1"].p_winner("home") + nums["M1"].p_winner("away") - 1) < 1e-12 and 0 < nums["M1"].p_over_total(240.5) < 1 and 0 < nums["M1"].p_spread("home", -4.5) < 1 and nums["M1"].p_over_team("home", 130.5) is not None)
check("Spiel vor dem Anpfiff: Zahlen = Vorab-Werte exakt (Sieger = Phi(Spread/Sigma), Total = Vorab-Funktion)", abs(nums["M2"].p_winner("home") - NormalDist().cdf(3.0 / 13.2)) < 5e-5 and abs(nums["M2"].p_over_total(225.5) - (1 - NormalDist().cdf((225.5 - 225.0) / 18.6))) < 1e-12 and abs(nums["M2"].p_over_team("home", 114.5) - (1 - NormalDist().cdf(0.5 / 11.6))) < 1e-12)
check("ohne Besitze (Spiel ohne Boxscore): Tempo-Gewicht 0, Zahlen trotzdem da", nums["M2"].projection.pace_weight == 0.0 and nums["M2"].projection.pace_mult == 1.0)
check("Ergebnis nur lesend: gleiche Eingabe -> gleiche Zahlen (kein Zustand)", lf.live_numbers(st.games[0], snaps).p_winner("home") == nums[st.games[0].game_id].p_winner("home"))
no_snap = {"x": {"game_date": DAY, "home": "Philadelphia 76ers", "away": "Cleveland Cavaliers", "versions": [snap_version()]}}
nn = lf.live_numbers_for_state(st, no_snap)
check("ohne Schnappschuss fuer ein Spiel (M2): Spiel bleibt in der Liste, aber ohne Chancen und mit Hinweis; andere Spiele unberuehrt", nn["M2"].has_anchor is False and nn["M2"].projection is None and nn["M2"].note == lf.NO_ANCHOR_NOTE and nn["M2"].p_winner("home") is None
      and nn["M2"].p_over_total(225.5) is None and nn["M2"].p_spread("home", -3.5) is None and nn["M2"].p_over_team("home", 110.5) is None and nn["M1"].has_anchor and [g.game_id for g in st.games] == ["M1", "M2"])
check("Schnappschuss-Datei fehlt oder ist leer (Standard-Lader): keine Chancen statt Absturz", all(not v.has_anchor for v in lf.live_numbers_for_state(st).values()))
check("Schnappschuss mit anderem Spieltag passt nicht (Zuordnung ueber Datum UND Mannschaften)", not lf.live_numbers(st.games[0], {"k": {**no_snap["x"], "game_date": "2026-10-21"}}).has_anchor)
check("Spitzname-Zuordnung auch bei anderen Vollnamen (LA/Los Angeles Clippers)", lf.same_team("LA Clippers", "Clippers") and lf.same_team("Los Angeles Clippers", "Clippers") and lf.same_team("Portland Trail Blazers", "Trail Blazers") and not lf.same_team("Boston Celtics", "Clippers") and not lf.same_team("", "x"))
fin_feed = Net(); fin_feed.rows = [row("O1", status=3, period=4, clock="", text="Final", hs=120, as_=101)]
nf = lf.live_numbers_for_state(feed_with(fin_feed).refresh(T0), snaps)["O1"]
check("beendetes Spiel: Chancen exakt 0 oder 1", nf.has_anchor and nf.p_winner("home") == 1.0 and nf.p_over_total(220.5) == 1.0 and nf.p_over_total(221.5) == 0.0 and nf.projection.final)

# ----------------------------------------------------------------- Wetten mit Live-Status
fresh_env()
real_now = time.time()
start_bet = iso(real_now + 6 * 3600)
bet_day = lf.game_day_us({"gameTimeUTC": start_bet})
net = Net(); net.board_day = bet_day
net.rows = [row("P1", status=2, period=3, clock="PT06M00.00S", hs=85, as_=60, start=start_bet, day=bet_day), row("P2", status=1, period=0, clock="", hs=0, as_=0, home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"), start=start_bet, day=bet_day)]
net.boxes = {"P1": box()}
ds.set_bet(bet_day, start_bet, "Philadelphia 76ers", "Cleveland Cavaliers", "winner", side="home", odds=1.5, stake=20)
ds.set_bet(bet_day, start_bet, "Philadelphia 76ers", "Cleveland Cavaliers", "total", side="under", line=144.5, odds=2.0, stake=10)
ds.set_bet(bet_day, start_bet, "Philadelphia 76ers", "Cleveland Cavaliers", "team_total_home", side="over", line=84.5)
ds.set_bet(bet_day, start_bet, "Boston Celtics", "Miami Heat", "spread", side="away", line=3.5)
ds.set_bet(bet_day, start_bet, "Dallas Mavericks", "Utah Jazz", "winner", side="home")
feed = feed_with(net, real_now); st = feed.refresh(real_now, day=bet_day)
snaps_b = {"a": {"game_date": bet_day, "home": "Philadelphia 76ers", "away": "Cleveland Cavaliers", "versions": [snap_version()]}}
rows_b = {r["key"].split("|")[2]: r for r in lf.bets_live(st, snaps_b)}
check("Wetten des Spieltags mit Live-Status: Spiel P1 mit Snapshot: Total Under 144,5 bei 145 Punkten verloren, Team Total Heim Over 84,5 bei 85 gewonnen, Sieger offen/auf Kurs", set(rows_b["Philadelphia 76ers"]["lives"]) == {"winner", "total", "team_total_home"}
      and rows_b["Philadelphia 76ers"]["lives"]["total"].state == "verloren" and rows_b["Philadelphia 76ers"]["lives"]["team_total_home"].state == "gewonnen" and rows_b["Philadelphia 76ers"]["lives"]["winner"].state == "offen" and rows_b["Philadelphia 76ers"]["game"].game_id == "P1")
check("Spiel ohne Schnappschuss: Wette sichtbar, aber ohne Status, mit Hinweis", rows_b["Boston Celtics"]["lives"] == {} and rows_b["Boston Celtics"]["note"] == lf.NO_ANCHOR_NOTE and rows_b["Boston Celtics"]["bets"]["spread"]["side"] == "away" and rows_b["Boston Celtics"]["game"].game_id == "P2")
check("Wette auf ein Spiel, das nicht im Scoreboard steht: game None mit Hinweis, kein Absturz", rows_b["Dallas Mavericks"]["game"] is None and rows_b["Dallas Mavericks"]["numbers"] is None and "nicht im Scoreboard" in rows_b["Dallas Mavericks"]["note"])
check("Wetten-Liste ohne Wetten: leer", lf.bets_live(st, snaps_b, day_bets={}) == [])

# ----------------------------------------------------------------- Header, gemeinsamer Feed, Standardabruf ueber fake_net, nur lesend
net = Net(); net.rows = [row("Q1")]; feed = lf.LiveFeed(http_get=net.get, now=lambda: T0); feed.refresh(T0)
h = net.calls[0][1]
check("NBA.com-Abrufe nutzen data/nba_headers.py: Chrome-UA (aktuelle Version aus dem installierten Browser), Origin, Referer; Timeout 10 s", h == nba_headers() and set(h) == {"User-Agent", "Origin", "Referer"} and "Chrome/" in h["User-Agent"] and net.calls[0][3] == 10)
check("alter Tab (data/nba_live.py) nutzt dieselben Header und dieselbe Chrome-Version (nicht mehr fest 147)", nl.NBA_HEADERS == nba_headers(nl.NBA_CHROME_MAJOR) and nl.NBA_HEADERS["User-Agent"] == h["User-Agent"] and nl.NBA_CHROME_MAJOR >= 150)
FN["scoreboard"] = [row("R1", status=2, period=2, clock="PT03M00.00S"), row("R2", status=3, period=4, clock="", text="Final", home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"))]
FN["board_date"] = DAY; FN["boxes"] = {"R1": box()}
before = FN["nba_calls"]
f_default = lf.LiveFeed(now=lambda: T0)
sd = f_default.refresh(T0)
check("fake_net: 2 Spiele, Boxscore des laufenden Spiels (R1) und der eine Final-Abruf des beendeten (R2), 3 Abrufe bei cdn.nba.com", [g.game_id for g in sd.games] == ["R1", "R2"] and FN["nba_calls"] - before == 3 and sd.source == "NBA.com" and sd.games[0].possessions is not None and not sd.stale, str(FN["nba_urls"][-3:]))
FN["nba_status"] = 403
sd = f_default.refresh(T0 + 15)
check("fake_net: 403 -> Fehlerzustand mit letztem Stand", sd.error_status == 403 and len(sd.games) == 2 and sd.stale and FN["espn_calls"] >= 1)
FN["nba_status"] = 200
check("get_feed(): ein gemeinsamer Feed je Prozess", lf.get_feed() is lf.get_feed() and isinstance(lf.get_feed(), lf.LiveFeed))
net = Net(); net.rows = [row("S1"), row("S2", home=("Boston", "Celtics", "BOS"), away=("Miami", "Heat", "MIA"))]
shared = feed_with(net); errs = []
def hit():
    try:
        for _ in range(20): shared.refresh(T0)
    except Exception as e:
        errs.append(repr(e))
ths = [threading.Thread(target=hit) for _ in range(8)]; [t.start() for t in ths]; [t.join() for t in ths]
check("8 Threads (mehrere Browser-Sitzungen) fragen gleichzeitig: genau 1 Scoreboard + 2 Boxscores, keine Ausnahme", not errs and net.count("board") == 1 and net.count("box") == 2, f"{net.kinds()} {errs}")
check("nur lesend: der Test hat keine echte Datei veraendert oder neu angelegt (Tracking-Dateien inkl. day_bets.json, pregame_lines.json: Hash vorher = nachher)", real_snapshot() == real_tracking)

print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
