"""Tests: Der Live-Feed holt je 30-s-Takt hoechstens EINMAL, auch wenn mehrere Takt-Fragmente (Spieltag-Kopf, Spieltag-Karten, Meine Spieler-Wetten, Spielertabelle) im selben Moment laufen
(ui/live_tab.pick_state). Scoreboard hoechstens alle 15 s, Boxscore je laufendem Spiel hoechstens alle 30 s, ESPN-Ersatz hoechstens alle 30 s, ein Final-Abruf je Spiel. Offline: Attrappen.
Aufruf: venv/bin/python tests/test_feed_cycle.py"""
import os, sys, warnings
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install(); fresh_env()
from data import live_feed as lf
from ui import live_tab as lt

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

T0 = datetime(2026, 10, 23, 2, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
DAY = "2026-10-22"
class R:
    def __init__(self, payload): self.status_code, self._p, self.text = 200, payload, ""
    def json(self): return self._p
def row(gid, status, period, clock, hs, as_, start="2026-10-22T23:00:00Z"):
    t = lambda nick, sc: {"teamCity": nick.split()[0], "teamName": nick.split()[1], "teamTricode": nick[:3].upper(), "score": sc, "periods": []}
    return {"gameId": gid, "gameStatus": status, "gameStatusText": "", "period": period, "gameClock": clock, "gameEt": f"{DAY}T19:00:00-04:00", "gameTimeUTC": start, "homeTeam": t(f"Heim{gid} Falken", hs), "awayTeam": t(f"Gast{gid} Baeren", as_)}
def box(period, clock, hs, as_):
    s = {"fieldGoalsAttempted": 30, "freeThrowsAttempted": 8, "reboundsOffensive": 4, "turnoversTotal": 5}
    return {"gameStatus": 2, "period": period, "gameClock": clock, "homeTeam": {"score": hs, "statistics": dict(s), "players": []}, "awayTeam": {"score": as_, "statistics": dict(s), "players": []}}
class Net:
    def __init__(self): self.calls, self.n = [], 0
    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append("espn" if "espn" in url else "board" if "scoreboard" in url else "box")
        if "espn" in url: return R({"events": []})
        self.n += 1
        if "scoreboard" in url: return R({"scoreboard": {"gameDate": DAY, "games": [row("A", 2, 2, f"PT{max(0, 10 - self.n // 4):02d}M00.00S", 40, 38), row("B", 2, 1, "PT05M00.00S", 20, 18), row("C", 1, 0, "", 0, 0, "2026-10-23T23:00:00Z")]}})
        gid = url.rsplit("_", 1)[1].split(".")[0]
        return R({"game": box(2, "PT09M00.00S", 40, 38) if gid == "A" else box(1, "PT05M00.00S", 20, 18)})
    def count(self, k): return self.calls.count(k)

def fragments(feed, t):
    """vier Takt-Fragmente im selben Moment (Spieltag-Kopf, Spieltag-Karten, Meine Spieler-Wetten, Spielertabelle): jedes ruft pick_state wie in der Oberflaeche."""
    return [lt.pick_state(feed, False, True, True, t) for _ in range(4)]

net = Net(); feed = lf.LiveFeed(http_get=net.get, now=lambda: T0)
st1 = lt.pick_state(feed, False, True, False, T0)                      # erstes Laden der Seite
check("erstes Laden: 1 Scoreboard-Abruf und je ein Boxscore der zwei laufenden Spiele (das Vorab-Spiel bekommt keinen)", (net.count("board"), net.count("box"), net.count("espn")) == (1, 2, 0), str(net.calls))
net.calls.clear(); fragments(feed, T0 + 1)
check("vier Fragmente 1 s spaeter: kein weiterer Abruf", net.calls == [], str(net.calls))
net.calls.clear(); fragments(feed, T0 + 16)
check("nach 16 s: hoechstens EIN Scoreboard-Abruf fuer alle vier Fragmente, Boxscores noch nicht faellig (< 30 s)", net.count("board") == 1 and net.count("box") == 0, str(net.calls))
net.calls.clear(); fragments(feed, T0 + 31)
check("nach 31 s: 1 Scoreboard-Abruf + 1 Boxscore je laufendem Spiel (2), nicht vier mal", net.count("board") == 1 and net.count("box") == 2, str(net.calls))
net.calls.clear()
for k in range(5): fragments(feed, T0 + 32 + k)
check("weitere Fragment-Laeufe innerhalb derselben 15 s: keine Abrufe", net.calls == [], str(net.calls))
ticks = [T0 + 30 * k for k in range(2, 12)]
net.calls.clear()
for t in ticks: fragments(feed, t)
per_min = len(net.calls) / (len(ticks) * 30 / 60)
check("10 Takte (5 Minuten) mit je vier Fragmenten: pro Minute hoechstens 2 Scoreboard- und 4 Boxscore-Abrufe (zwei laufende Spiele), nie mehr", net.count("board") <= len(ticks) and net.count("box") <= len(ticks) * 2 and net.count("espn") == 0, f"{net.count('board')} {net.count('box')} -> {per_min:.1f} Abrufe/Min.")
net.calls.clear()
for k in range(20): feed.state(T0 + 400 + k)
check("feed.state() (Anzeige ohne Takt) ruft nie ab", net.calls == [])
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
