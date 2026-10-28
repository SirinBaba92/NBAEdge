"""Tests fuer die Quellenwahl 'immer die neuere Quelle' im Live-Feed (data/live_feed.py): Das NBA.com-Scoreboard bewegt sich in kleinen Spruengen und hinkt Spielminuten hinterher (Messung
23.10.2026 01:59: Stream Cavaliers 52, 76ers 28, Q2 6:43; App 40:20, Q2 10:37), steht aber nie 90 Sekunden still. Bei laufenden Spielen gilt der Boxscore, wenn seine Periode spaeter ist, bei gleicher
Periode die Restzeit kuerzer, bei gleicher Zeit die Punkte hoeher; Stand und Uhr kommen immer aus EINER Quelle. Offline: Attrappen. Aufruf: venv/bin/python tests/test_live_feed_lag.py"""
import hashlib, os, sys
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

T0 = datetime(2026, 10, 23, 2, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
DAY, START = "2026-10-22", "2026-10-22T23:00:00Z"
class R:
    def __init__(self, status=200, payload=None): self.status_code, self._p, self.text = status, payload, ""
    def json(self): return self._p
def row(status=2, period=2, clock="PT10M37.00S", text="", hs=20, as_=40):
    t = lambda c, n, tri, sc: {"teamCity": c, "teamName": n, "teamTricode": tri, "score": sc, "periods": []}
    return {"gameId": "G1", "gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock, "gameEt": f"{DAY}T19:00:00-04:00", "gameTimeUTC": START,
            "homeTeam": t("Philadelphia", "76ers", "PHI", hs), "awayTeam": t("Cleveland", "Cavaliers", "CLE", as_)}
def boxgame(status=2, period=2, clock="PT06M43.00S", hs=28, as_=52, text="", with_clock=True):
    s = {"fieldGoalsAttempted": 30, "freeThrowsAttempted": 8, "reboundsOffensive": 4, "turnoversTotal": 5}
    g = {"gameStatus": status, "gameStatusText": text, "homeTeam": {"score": hs, "statistics": dict(s), "players": []}, "awayTeam": {"score": as_, "statistics": dict(s), "players": []}}
    if with_clock:
        g.update(period=period, gameClock=clock)
    return g
def espn(period=2, clock="6:43", detail="6:43 - 2nd Quarter", hs=28, as_=52, state_="in"):
    return {"events": [{"id": "401", "date": "2026-10-22T23:00Z", "status": {"clock": 0.0, "displayClock": clock, "period": period, "type": {"state": state_, "detail": detail, "description": detail}},
                        "competitions": [{"competitors": [{"homeAway": "home", "score": str(hs), "team": {"displayName": "Philadelphia 76ers", "name": "76ers"}},
                                                          {"homeAway": "away", "score": str(as_), "team": {"displayName": "Cleveland Cavaliers", "name": "Cavaliers"}}]}]}]}
class Net:
    def __init__(self): self.calls, self.row, self.box, self.box_status, self.espn = [], row(), boxgame(), 200, espn()
    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        if "espn.com" in url: return R(200, self.espn)
        if "scoreboard" in url: return R(200, {"scoreboard": {"gameDate": DAY, "games": [self.row]}})
        return R(self.box_status, {"game": self.box} if self.box_status == 200 else {})
    def espn_calls(self): return sum(1 for u in self.calls if "espn" in u)
def one(net, row_=None, box_=None, secs=30, start=T0):
    """Ein kurzer Lauf (2 Abrufe im 15-s-Takt) mit gegebenem Scoreboard- und Boxscore-Stand."""
    if row_ is not None: net.row = row_
    if box_ is not None: net.box = box_
    feed = lf.LiveFeed(http_get=net.get, now=lambda: start)
    s = None
    for k in range(0, secs + 1, 15): s = feed.refresh(start + k)
    return feed, s
G = lambda s: s.games[0]

# --- 1) Messwert vom 23.10.: Scoreboard Q2 10:37 (40:20), Stream Q2 6:43 (52:28)
net = Net()
feed, s = one(net)
g1 = G(s)
check("Boxscore ist neuer: Stand 52:28, Q2 6:43, Quelle 'NBA.com-Boxscore (Ersatz)' (Label 'Stand von ...')", (g1.away_score, g1.home_score) == (52, 28) and g1.clock_label == "Q2 6:43" and g1.source == lf.SOURCE_BOX_SUB, f"{g1.away_score}:{g1.home_score} {g1.clock_label}")
check("Stand UND Uhr aus derselben Quelle (nie gemischt): Rohwerte bleiben 40:20 / Q2 10:37 gespeichert", (feed._raw["G1"].away_score, feed._raw["G1"].home_score) == (40, 20) and feed._raw["G1"].clock_label == "Q2 10:37" and feed._raw["G1"].source == "NBA.com")
check("Statuszeile: 'Scoreboard hinkt ca. 03:54 hinterher' (10:37 - 6:43), gelb ab 2 Minuten", "Scoreboard hinkt ca. 03:54 hinterher" in s.status_line and "⚠" in s.status_line and 'lv-status-warn' in lc.render_status_html(s), s.status_line)
check("kein ESPN-Abruf, solange der Boxscore da und neuer ist", net.espn_calls() == 0)
check("Chip der Karte nennt die Quelle (source != NBA.com)", g1.source != "NBA.com" and not g1.data_stale)
# Scoreboard bewegt sich in kleinen Spruengen (nie 90 s still), bleibt aber hinter dem Boxscore
feed2 = lf.LiveFeed(http_get=net.get, now=lambda: T0)
for k, (clk, h_, a_) in enumerate([("PT10M37.00S", 20, 40), ("PT10M20.00S", 20, 42), ("PT09M55.00S", 22, 42), ("PT09M10.00S", 22, 45), ("PT08M30.00S", 24, 45), ("PT07M50.00S", 24, 47), ("PT07M15.00S", 26, 47)]):
    net.row = row(clock=clk, hs=h_, as_=a_)
    s = feed2.refresh(T0 + 20 * k)
check("Scoreboard laeuft in kleinen Spruengen (nie 90 s still) und hinkt weiter: trotzdem gilt der Boxscore, Rueckstand sinkt (hier 00:32)", G(s).source == lf.SOURCE_BOX_SUB and (G(s).away_score, G(s).home_score) == (52, 28) and "ca. 00:32" in s.status_line, s.status_line)
check("kleiner Rueckstand (< 2 Min.): dezent, NICHT gelb (kein Warnsymbol, Zustand ok)", "⚠" not in s.status_line and s.freeze_note is None and "lv-status-ok" in lc.render_status_html(s))
net.row = row(clock="PT06M43.00S", hs=28, as_=52)
s = feed2.refresh(T0 + 20 * 8)
check("Scoreboard hat aufgeholt (gleicher Stand): Quelle wieder NBA.com, keine Zeile", G(s).source == "NBA.com" and "hinkt" not in s.status_line and s.freeze_note is None, s.status_line)

# --- 2) Vergleichsregeln einzeln
cases = [
    ("spaetere Periode (Scoreboard Q2 0:30, Boxscore Q3 11:00)", row(period=2, clock="PT00M30.00S", hs=50, as_=55), boxgame(period=3, clock="PT11M00.00S", hs=51, as_=57), True),
    ("fruehere Periode im Boxscore (Q1 gegen Scoreboard Q2): ignoriert", row(period=2, clock="PT10M00.00S", hs=20, as_=30), boxgame(period=1, clock="PT02M00.00S", hs=20, as_=30), False),
    ("gleiche Periode, Restzeit kuerzer (6:43 gegen 10:37)", row(), boxgame(), True),
    ("gleiche Periode, Restzeit LAENGER im Boxscore (Boxscore aelter): ignoriert", row(clock="PT06M00.00S", hs=30, as_=50), boxgame(clock="PT09M00.00S", hs=26, as_=48), False),
    ("gleiche Zeit, mehr Gesamtpunkte im Boxscore", row(clock="PT06M43.00S", hs=26, as_=50), boxgame(clock="PT06M43.00S", hs=28, as_=52), True),
    ("gleiche Zeit, gleiche Punkte: kein Wechsel", row(clock="PT06M43.00S", hs=28, as_=52), boxgame(clock="PT06M43.00S", hs=28, as_=52), False),
    ("gleiche Zeit, WENIGER Punkte im Boxscore: ignoriert", row(clock="PT06M43.00S", hs=30, as_=52), boxgame(clock="PT06M43.00S", hs=28, as_=52), False),
    ("Boxscore neuer in der Zeit, aber ein Team mit weniger Punkten (unplausibel): nicht vermischen", row(clock="PT10M00.00S", hs=30, as_=50), boxgame(clock="PT06M00.00S", hs=29, as_=60), False),
    ("Periodenwechsel: Scoreboard 'Ende Q1' (Pause, 0:00), Boxscore Q2 12:00", row(period=1, clock="", text="End of 1st", hs=30, as_=28), boxgame(period=2, clock="PT12M00.00S", hs=30, as_=28), True),
    ("Verlaengerung: Scoreboard OT 3:00 (5. Periode), Boxscore OT 1:10", row(period=5, clock="PT03M00.00S", hs=110, as_=110), boxgame(period=5, clock="PT01M10.00S", hs=112, as_=110), True),
]
for label, r_, b_, expect in cases:
    n = Net(); f_, s_ = one(n, r_, b_)
    check(f"Vergleich: {label}", (G(s_).source == lf.SOURCE_BOX_SUB) == expect and ((G(s_).away_score, G(s_).home_score) == (b_["awayTeam"]["score"], b_["homeTeam"]["score"]) if expect else (G(s_).away_score, G(s_).home_score) == (r_["awayTeam"]["score"], r_["homeTeam"]["score"])),
          f"{G(s_).source} {G(s_).clock_label}")
n = Net(); f_, s_ = one(n, row(period=2, clock="PT00M30.00S", hs=50, as_=55), boxgame(period=3, clock="PT11M00.00S", hs=51, as_=57))
check("Periodenwechsel-Anzeige: Q3 11:00 und Stand 57:51 aus dem Boxscore", G(s_).clock_label == "Q3 11:00" and (G(s_).away_score, G(s_).home_score) == (57, 51))

# --- 3) Spielende nur mit 'beendet' UND plausiblen Punkten
n = Net(); f_, s_ = one(n, row(period=4, clock="PT00M20.00S", hs=100, as_=96), boxgame(status=3, period=4, clock="PT00M00.00S", hs=102, as_=98, text="Final"))
check("Boxscore 'beendet' (4. Viertel, 102:98 = 200 Punkte, kein Gleichstand): Spiel gilt als beendet", G(s_).status == "FINAL" and (G(s_).home_score, G(s_).away_score) == (102, 98) and G(s_).source == lf.SOURCE_BOX_SUB)
for label, b_ in (("Gleichstand 105:105", boxgame(status=3, period=4, clock="PT00M00.00S", hs=105, as_=105)), ("zu wenige Punkte 50:48", boxgame(status=3, period=4, clock="PT00M00.00S", hs=48, as_=50)),
                  ("erst 3. Viertel", boxgame(status=3, period=3, clock="PT00M00.00S", hs=102, as_=98)), ("Punkte unter dem Scoreboard", boxgame(status=3, period=4, clock="PT00M00.00S", hs=90, as_=90))):
    n = Net(); f_, s_ = one(n, row(period=4, clock="PT00M20.00S", hs=100, as_=96), b_)
    check(f"Spielende NICHT anerkannt: {label}", G(s_).status != "FINAL" and G(s_).source == "NBA.com", f"{G(s_).status} {G(s_).source}")
n = Net(); f_, s_ = one(n, row(period=4, clock="PT00M20.00S", hs=100, as_=96), boxgame(status=2, period=4, clock="PT00M00.00S", hs=102, as_=98))
check("Boxscore noch 'laeuft' bei 0:00: Stand uebernommen, aber nicht als beendet", G(s_).status != "FINAL" and (G(s_).home_score, G(s_).away_score) == (102, 98))

# --- 4) Boxscore fehlt / Fehler / unbrauchbar -> ESPN erst als Zweitersatz (nach 90 s ohne Aenderung)
n = Net(); n.box_status = 500; n.row = row(clock="PT10M37.00S", hs=20, as_=40); n.espn = espn()
f_, s_ = one(n, secs=60)
check("Boxscore-Fehler, Scoreboard 60 s unveraendert: noch kein ESPN-Abruf, Quelle NBA.com", G(s_).source == "NBA.com" and n.espn_calls() == 0)
f_, s_ = one(n, secs=120)
check("Boxscore-Fehler, 120 s unveraendert: ESPN (Ersatz) uebernimmt (Zweitersatz)", G(s_).source == lf.SOURCE_ESPN_SUB and (G(s_).away_score, G(s_).home_score) == (52, 28) and n.espn_calls() >= 1, f"{G(s_).source}")
n = Net(); n.box = boxgame(with_clock=False); n.espn = espn()
f_, s_ = one(n, secs=120)
check("Boxscore ohne Spielzeit (unbrauchbar): ESPN als Zweitersatz", G(s_).source == lf.SOURCE_ESPN_SUB)
n = Net(); n.box = {"gameStatus": 2}                                            # kaputtes Format
f_, s_ = one(n, secs=120)
check("kaputter Boxscore: kein Absturz, ESPN als Zweitersatz", G(s_).source == lf.SOURCE_ESPN_SUB)
n = Net()
f_, s_ = one(n, secs=120)
check("Boxscore da und neuer: ESPN wird NICHT abgefragt (nur Zweitersatz)", n.espn_calls() == 0 and G(s_).source == lf.SOURCE_BOX_SUB)
n = Net(); n.box_status = 500; n.espn_status = None
n.espn = {"events": []}
f_, s_ = one(n, secs=150)
check("weder Boxscore noch ESPN: 'Daten veraltet' (data_stale), keine Chancen", G(s_).data_stale and "Daten veraltet" in s_.status_line)

# --- 5) Pausen ohne Fehlalarm (auch wenn der Boxscore gleich ist oder aelter)
for label, r_, b_ in (("Halbzeit", row(period=2, clock="", text="Halftime", hs=55, as_=50), boxgame(period=2, clock="PT00M00.00S", hs=55, as_=50)),
                      ("Viertelpause", row(period=1, clock="", text="End of 1st", hs=30, as_=28), boxgame(period=1, clock="PT00M00.00S", hs=30, as_=28)),
                      ("Halbzeit, Boxscore etwas aelter (Q2 0:05)", row(period=2, clock="", text="Halftime", hs=55, as_=50), boxgame(period=2, clock="PT00M05.00S", hs=53, as_=50)),
                      ("Ende Q4 / Periodenende", row(period=4, clock="", text="", hs=100, as_=100), boxgame(period=4, clock="PT00M00.00S", hs=100, as_=100)),
                      ("Verlaengerungspause", row(period=5, clock="", text="End of OT", hs=110, as_=110), boxgame(period=5, clock="PT00M00.00S", hs=110, as_=110))):
    n = Net(); f_, s_ = one(n, r_, b_, secs=600)
    check(f"Pause '{label}': 10 Minuten, kein Alarm, keine Zeile, Quelle NBA.com, kein ESPN", G(s_).source == "NBA.com" and s_.freeze_note is None and "hinkt" not in s_.status_line and n.espn_calls() == 0)
n = Net(); f_, s_ = one(n, row(period=2, clock="", text="Halftime", hs=55, as_=50), boxgame(period=3, clock="PT12M00.00S", hs=55, as_=50), secs=30)
check("Halbzeit im Scoreboard, Boxscore schon Q3 12:00 (zweite Haelfte laeuft): neuere Periode gilt", G(s_).source == lf.SOURCE_BOX_SUB and G(s_).clock_label == "Q3 12:00")
n = Net(); n.row = row(status=1, period=0, clock="", hs=0, as_=0); n.box = boxgame(period=1, clock="PT11M00.00S", hs=2, as_=0); n.row["gameTimeUTC"] = "2026-10-23T23:00:00Z"      # Startzeit in der Zukunft: Boxscore wird nicht herangezogen (nach der Startzeit: tests/test_live_feed_pre_start.py)
f_, s_ = one(n)
check("Spiel laut Scoreboard noch nicht begonnen: Boxscore wird gar nicht erst herangezogen", G(s_).status == "PRE" and G(s_).source == "NBA.com")

check("echte Dateien unveraendert", snap() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
