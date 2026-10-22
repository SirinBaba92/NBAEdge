"""Tests fuer die Einfrier-Erkennung im Live-Feed (data/live_feed.py): das NBA.com-Scoreboard laeuft nicht weiter (Vorfall 23.10.2026 01:20 Uhr: Q1 7:45, 9:7 stundenlang unveraendert),
Boxscore und ESPN sind weiter. Offline: Abrufe sind Attrappen, nichts wird ins Projekt geschrieben. Aufruf aus dem Projektordner: venv/bin/python tests/test_live_feed_freeze.py"""
import hashlib, os, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install(); fresh_env()
from data import live_feed as lf
from ui import live_card as lc

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def snap():
    files = list((ROOT / "data" / "tracking").glob("*.json")) + [ROOT / "data" / "pregame_lines.json"]
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.exists()}
real_before = snap()

T0 = datetime(2026, 10, 23, 1, 20, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
DAY, START = "2026-10-22", "2026-10-22T23:00:00Z"

class R:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text
    def json(self): return self._p

def row(status=2, period=1, clock="PT07M45.00S", text="", hs=7, as_=9):
    t = lambda c, n, tri, sc: {"teamCity": c, "teamName": n, "teamTricode": tri, "score": sc, "periods": []}
    return {"gameId": "G1", "gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock, "gameEt": f"{DAY}T19:00:00-04:00", "gameTimeUTC": START,
            "homeTeam": t("Philadelphia", "76ers", "PHI", hs), "awayTeam": t("Cleveland", "Cavaliers", "CLE", as_)}

def boxgame(status=2, period=1, clock="PT03M38.00S", hs=13, as_=23, text=""):
    s = {"fieldGoalsAttempted": 30, "freeThrowsAttempted": 8, "reboundsOffensive": 4, "turnoversTotal": 5}
    return {"gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock,
            "homeTeam": {"score": hs, "statistics": dict(s), "players": []}, "awayTeam": {"score": as_, "statistics": dict(s), "players": []}}

def espn(state_="in", period=1, clock="3:38", detail="3:38 - 1st Quarter", hs=13, as_=23):
    return {"events": [{"id": "401", "date": "2026-10-22T23:00Z", "status": {"clock": 0.0, "displayClock": clock, "period": period, "type": {"state": state_, "detail": detail, "description": detail}},
                        "competitions": [{"competitors": [{"homeAway": "home", "score": str(hs), "team": {"displayName": "Philadelphia 76ers", "name": "76ers"}},
                                                          {"homeAway": "away", "score": str(as_), "team": {"displayName": "Cleveland Cavaliers", "name": "Cavaliers"}}]}]}]}

class Net:
    def __init__(self):
        self.calls, self.row, self.box, self.espn, self.espn_status, self.box_status = [], row(), boxgame(), espn(), 200, 200
    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        if "espn.com" in url:
            return R(self.espn_status, self.espn)
        if "scoreboard" in url:
            return R(200, {"scoreboard": {"gameDate": DAY, "games": [self.row]}})
        return R(self.box_status, {"game": self.box} if self.box_status == 200 else {})
    def count(self, kind): return sum(1 for u in self.calls if (("espn" in u) if kind == "espn" else ("scoreboard" in u) if kind == "board" else ("boxscore" in u or "box" in u.rsplit("/", 1)[-1])))
    def reset(self): self.calls.clear()

def run(net, seconds, step=15, start=T0, feed=None):
    """Feed im 15-Sekunden-Takt (wie die Oberflaeche) von start bis start+seconds; Rueckgabe (Feed, letzter Zustand)."""
    feed = feed or lf.LiveFeed(http_get=net.get, now=lambda: start)
    s = None
    for k in range(0, seconds + 1, step):
        s = feed.refresh(start + k)
    return feed, s
g = lambda s: s.games[0]

# --- A) Scoreboard eingefroren, Boxscore weiter
net = Net()
feed, s = run(net, 60)
check("bis 60 s: noch kein Alarm (Quelle NBA.com, Rohwerte 9:7 Q1 7:45, keine Notiz)", g(s).source == "NBA.com" and (g(s).away_score, g(s).home_score) == (9, 7) and s.freeze_note is None and g(s).frozen_since_s is None, s.status_line)
feed, s = run(net, 120, start=T0 + 75, feed=feed)
G = g(s)
check("nach > 90 s: Stand, Uhr, Periode vom Boxscore (Q1 3:38, 23:13), Quelle 'NBA.com-Boxscore (Ersatz)'", G.source == lf.SOURCE_BOX_SUB and (G.away_score, G.home_score) == (23, 13) and G.clock.seconds_left == 218 and G.clock.period == 1 and G.clock_label == "Q1 3:38", f"{G.source} {G.clock_label}")
check("Statuszeile gelb: 'NBA.com-Daten eingefroren seit mm:ss' mit Spiel und Ersatzquelle; Zustand traegt freeze_note", s.freeze_note and "NBA.com-Daten eingefroren seit " in s.status_line and "Cavaliers @ 76ers" in s.status_line and "NBA.com-Boxscore (Ersatz)" in s.status_line, s.status_line)
check("Statuszeile wird als Warnung (gelb) gerendert, mit Zeitformat mm:ss", 'lv-status-warn' in lc.render_status_html(s) and __import__("re").search(r"eingefroren seit \d\d:\d\d ", s.status_line) is not None)
check("Chip an der Karte nennt die Ersatzquelle ('Stand von NBA.com-Boxscore (Ersatz)'), frozen_since_s gesetzt", G.frozen_since_s is not None and G.frozen_since_s >= 90 and not G.data_stale)
check("kein ESPN-Abruf noetig, solange der Boxscore weiter ist", net.count("espn") == 0, str(net.calls[-3:]))
check("Rohwerte des Scoreboards bleiben unveraendert gespeichert (9:7)", (feed._raw["G1"].away_score, feed._raw["G1"].home_score) == (9, 7) and feed._raw["G1"].source == "NBA.com")
# Weiterlaufen des Boxscores: Ersatzstand folgt
net.box = boxgame(clock="PT02M10.00S", hs=15, as_=26)
feed, s = run(net, 60, start=T0 + 200, feed=feed)
check("Boxscore laeuft weiter: Ersatzstand folgt (Q1 2:10, 26:15)", g(s).clock_label == "Q1 2:10" and (g(s).away_score, g(s).home_score) == (26, 15) and g(s).source == lf.SOURCE_BOX_SUB)

# --- Rueckwechsel auf NBA.com, sobald das Scoreboard wieder laeuft
net.row = row(clock="PT02M05.00S", hs=15, as_=26)
net.box = boxgame(clock="PT02M05.00S", hs=15, as_=26)
feed, s = run(net, 30, start=T0 + 270, feed=feed)
check("Scoreboard laeuft wieder: Quelle wieder NBA.com, keine Notiz, normale Statuszeile", g(s).source == "NBA.com" and s.freeze_note is None and g(s).frozen_since_s is None and "eingefroren" not in s.status_line and (g(s).away_score, g(s).home_score) == (26, 15), s.status_line)

# --- B) Boxscore nicht verwendbar -> ESPN (Ersatz)
net = Net(); net.box_status = 500; net.espn = espn(clock="3:38", hs=13, as_=23)
feed, s = run(net, 120)
G = g(s)
check("ohne Boxscore: ESPN springt ein, Quelle 'ESPN (Ersatz)', Stand 23:13, Q1 3:38", G.source == lf.SOURCE_ESPN_SUB and (G.away_score, G.home_score) == (23, 13) and G.clock_label == "Q1 3:38" and "ESPN (Ersatz)" in s.status_line, f"{G.source} {G.clock_label}")
check("ESPN erst nach der Einfrierschwelle und hoechstens alle 30 s abgefragt", 1 <= net.count("espn") <= 120 // 30 + 1, str(net.count("espn")))
net.espn = espn(clock="2:00", detail="2:00 - 1st Quarter", hs=16, as_=26)
feed, s = run(net, 45, start=T0 + 135, feed=feed)
check("ESPN laeuft weiter: Ersatzstand folgt (Q1 2:00)", g(s).clock_label == "Q1 2:00" and g(s).source == lf.SOURCE_ESPN_SUB)
net.row = row(clock="PT01M50.00S", hs=17, as_=26); net.espn = espn(clock="1:50", detail="1:50 - 1st Quarter", hs=17, as_=26)
feed, s = run(net, 30, start=T0 + 200, feed=feed)
check("Rueckwechsel von ESPN auf NBA.com, sobald das Scoreboard wieder laeuft", g(s).source == "NBA.com" and s.freeze_note is None)

# --- C) Boxscore meldet Spielende, Scoreboard haengt auf 'laeuft'
net = Net(); net.box = boxgame(status=3, period=4, clock="PT00M00.00S", hs=110, as_=104, text="Final")
feed, s = run(net, 120)
check("Boxscore sagt 'beendet', Scoreboard haengt: Spiel gilt als beendet (FINAL, Endstand 104:110)", g(s).status == "FINAL" and (g(s).away_score, g(s).home_score) == (104, 110) and g(s).source == lf.SOURCE_BOX_SUB, g(s).clock_label)

# --- D) Pausen loesen keinen Fehlalarm aus (auch nach vielen Minuten ohne Aenderung)
for label, r_ in (("Halbzeit", row(period=2, clock="", text="Halftime", hs=55, as_=50)), ("Viertelpause", row(period=1, clock="", text="End of 1st", hs=30, as_=28)),
                  ("Ende Q4 (Periodenende)", row(period=4, clock="", text="", hs=100, as_=100)), ("Verlaengerungspause", row(period=5, clock="", text="End of OT", hs=110, as_=110))):
    n = Net(); n.row = r_; n.box = boxgame(period=r_["period"], clock="PT05M00.00S", hs=70, as_=60)    # selbst ein 'neuerer' Boxscore loest hier nichts aus
    f_, s_ = run(n, 600)
    check(f"Pause '{label}': 10 Minuten unveraendert, kein Alarm, Quelle NBA.com", s_.freeze_note is None and g(s_).source == "NBA.com" and g(s_).frozen_since_s is None and n.count("espn") == 0)
n = Net(); n.row = row(status=1, period=0, clock="", hs=0, as_=0)
f_, s_ = run(n, 600)
check("vor dem Anpfiff (PRE) und beendet (FINAL): kein Alarm", s_.freeze_note is None and g(s_).source == "NBA.com")
n = Net(); n.row = row(status=3, period=4, clock="", text="Final", hs=100, as_=90)
f_, s_ = run(n, 600)
check("beendetes Spiel unveraendert: kein Alarm", s_.freeze_note is None and g(s_).source == "NBA.com")

# --- E) echte Spielunterbrechung (Uhr steht, Boxscore zeigt dasselbe): kein Alarm, kein ESPN-Abruf
n = Net(); n.box = boxgame(clock="PT07M45.00S", hs=7, as_=9)
f_, s_ = run(n, 240)
check("Unterbrechung 4 Minuten: Boxscore gleich wie Scoreboard -> kein Alarm, Quelle NBA.com, kein ESPN-Abruf", s_.freeze_note is None and g(s_).source == "NBA.com" and n.count("espn") == 0 and not g(s_).data_stale, s_.status_line)

# --- F) keine Ersatzquelle erreichbar: Verdacht, Daten veraltet, keine Chancen
n = Net(); n.box_status = 500; n.espn_status = 500
f_, s_ = run(n, 150)
G = g(s_)
check("kein Boxscore, kein ESPN: data_stale, Statuszeile 'möglicherweise eingefroren ... Daten veraltet'", G.data_stale and G.frozen_since_s >= 90 and "möglicherweise eingefroren" in s_.status_line and "Daten veraltet" in s_.status_line and lf.SOURCE_ESPN_SUB not in s_.status_line, s_.status_line)
nums = lf.live_numbers(G, {})
check("Live-Chancen nie auf veraltete Werte: has_anchor False, Hinweis 'Daten veraltet'", not nums.has_anchor and nums.projection is None and "Daten veraltet" in nums.note)
n = Net(); n.box_status = 500; n.espn = {"events": []}
f_, s_ = run(n, 150)
check("ESPN kennt das Spiel nicht: ebenfalls data_stale", g(s_).data_stale)

# --- G) Wetten-Status stuetzt sich nicht auf eingefrorene Werte
from data import day_bets_store as ds
state_games = {"G1": g(s_)}
class St: day = DAY; games = (g(s_),); other_day_games = ()
rows_ = lf.bets_live(St, {}, {"k": {"game": {"game_date": DAY, "start_utc": START, "home": "Philadelphia 76ers", "away": "Cleveland Cavaliers"}, "bets": {"winner": {"market": "winner", "active": True, "side": "home", "line": None, "odds": 1.5, "stake": 10.0, "odds_source": None, "line_ref": None, "placed_at": "x", "updated_at": "x", "removed_at": None, "revisions": []}}}}, {})
check("Wette im eingefrorenen Spiel ohne Ersatzquelle: kein Status (lives leer), Hinweis 'Daten veraltet'", rows_[0]["lives"] == {} and "Daten veraltet" in (rows_[0]["note"] or ""))

check("echte Dateien unveraendert", snap() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
