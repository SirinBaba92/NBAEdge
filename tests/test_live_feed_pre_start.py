"""Tests: Spielstart ueber den Boxscore erkennen (data/live_feed.py), wie der Recorder (record_live._probe_box): Fuehrt das NBA.com-Scoreboard ein Spiel noch als "vor dem Anpfiff" (PRE), obwohl die geplante
Startzeit erreicht ist, holt der Feed den Boxscore (gleiche URL, je Spiel hoechstens alle 30 s, hoechstens 6 Spiele je Aufruf). Meldet er gameStatus 2, gilt das Spiel als laufend (Stand, Uhr, Periode aus dem
Boxscore, Quelle "NBA.com-Boxscore (Ersatz)", Hinweis "Scoreboard hinkt ..."); 404, Fehler oder Status 1 aendern nichts; vor der Startzeit kein zusaetzlicher Abruf; zieht das Scoreboard nach, gilt es wieder.
Ausserdem: Wett-Eingabe-Sperre und der Expander "Wettliste nach Kategorien" (geschlossen). Offline: Attrappen, Temp-Ordner. Aufruf: venv/bin/python tests/test_live_feed_pre_start.py"""
import hashlib, os, sys, warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install(); fresh_env()
os.environ["NBAEDGE_LIVE_DIR"] = str(Path(os.environ["NBAEDGE_TRACKING_DIR"]).parent / "live_history_leer")      # nie das echte NBAEdge_live_history lesen
from data import live_feed as lf
from ui import bet_entry as be

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*.json")) + [ROOT / "data" / "pregame_lines.json", ROOT / "data" / "upcoming_cache.json"]
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.exists()}
real_before = real_files()

DAY = "2026-10-27"
START_DT = datetime(2026, 10, 28, 0, 0, 0, tzinfo=timezone.utc)                  # geplanter Anpfiff 00:00 UTC
START = START_DT.strftime("%Y-%m-%dT%H:%M:%SZ"); T_START = START_DT.timestamp()
class R:
    def __init__(self, status=200, payload=None): self.status_code, self._p, self.text = status, payload, ""
    def json(self): return self._p
def row(gid="G1", status=1, period=0, clock="", text="", hs=0, as_=0, start=START, city=("Philadelphia", "Cleveland")):
    t = lambda c, n, tri, sc: {"teamCity": c, "teamName": n, "teamTricode": tri, "score": sc, "periods": []}
    return {"gameId": gid, "gameStatus": status, "gameStatusText": text or ("7:00 pm ET" if status == 1 else ""), "period": period, "gameClock": clock, "gameEt": f"{DAY}T20:00:00-04:00", "gameTimeUTC": start,
            "homeTeam": t(city[0], "Home" + gid, "HOM", hs), "awayTeam": t(city[1], "Away" + gid, "AWY", as_)}
def boxgame(status=2, period=1, clock="PT08M15.00S", hs=10, as_=7, with_clock=True):
    s = {"fieldGoalsAttempted": 8, "freeThrowsAttempted": 2, "reboundsOffensive": 1, "turnoversTotal": 1}
    g = {"gameStatus": status, "gameStatusText": "", "homeTeam": {"score": hs, "statistics": dict(s), "players": []}, "awayTeam": {"score": as_, "statistics": dict(s), "players": []}}
    if with_clock:
        g.update(period=period, gameClock=clock)
    return g
class Net:
    """Scoreboard mit beliebig vielen Spielen; Boxscore je Spiel (Status/Inhalt einstellbar); zaehlt jeden Abruf mit Zeit."""
    def __init__(self, rows=None, box=None):
        self.rows, self.box, self.box_status, self.log, self.now = rows if rows is not None else [row()], box, 200, [], 0.0
    def get(self, url, headers=None, params=None, timeout=None):
        if "espn.com" in url:
            self.log.append((self.now, "espn", None)); return R(200, {"events": []})
        if "scoreboard" in url:
            self.log.append((self.now, "scoreboard", None)); return R(200, {"scoreboard": {"gameDate": DAY, "games": self.rows}})
        gid = url.rstrip("/").split("boxscore_")[-1].split(".json")[0]
        self.log.append((self.now, "box", gid))
        status = self.box_status(gid) if callable(self.box_status) else self.box_status
        b = self.box(gid) if callable(self.box) else self.box
        return R(status, {"game": b} if status == 200 else {})
    def boxes(self, gid=None): return [x for x in self.log if x[1] == "box" and (gid is None or x[2] == gid)]
def run(net, t0, secs, step=15, feed=None):
    feed = feed or lf.LiveFeed(http_get=net.get, now=lambda: t0)
    s = None
    for k in range(0, secs + 1, step):
        net.now = t0 + k
        s = feed.refresh(t0 + k)
    return feed, s
G = lambda s, gid="G1": next(g for g in s.games if g.game_id == gid)

# --- 1) PRE + Boxscore Status 2 -> laufend, mit Hinweis und echter Differenz
net = Net(box=boxgame(status=2, period=1, clock="PT08M15.00S", hs=10, as_=7))
feed, s = run(net, T_START + 300, 30)                                       # 5 Minuten nach der geplanten Startzeit, Scoreboard sagt noch PRE
g = G(s)
check("PRE + Boxscore gameStatus 2: Spiel laeuft (Status LIVE, 'läuft'), Stand 7:10, Uhr 'Q1 8:15', Quelle 'NBA.com-Boxscore (Ersatz)'",
      g.status == "LIVE" and g.status_text == "läuft" and (g.away_score, g.home_score) == (7, 10) and g.clock_label == "Q1 8:15" and g.source == lf.SOURCE_BOX_SUB, f"{g.status} {g.clock_label} {g.source}")
check("Hinweis 'Scoreboard hinkt ca. 03:45 hinterher' mit der echten Differenz (Boxscore 3:45 gespielt, Scoreboard 0:00); kein 'eingefroren'", "Scoreboard hinkt ca. 03:45 hinterher" in s.status_line and "eingefroren" not in s.status_line and g.frozen_since_s is None, s.status_line)
check("Rohwert des Scoreboards bleibt PRE (feed._raw)", feed._raw["G1"].status == "PRE" and feed._raw["G1"].source == "NBA.com")
check("kein Fehlerhinweis, keine veralteten Daten", s.error is None and not g.data_stale and g.box_error is None)

# --- 2) PRE + 404: nichts aendert sich, kein Fehler, keine gemeinsame Pause
net = Net(box=boxgame()); net.box_status = 404
feed, s = run(net, T_START + 300, 60)
g = G(s)
check("PRE + Boxscore 404: Spiel bleibt PRE ('Vor dem Anpfiff'), kein Fehler, kein Hinweis am Spiel", g.status == "PRE" and g.status_text == "Vor dem Anpfiff" and s.error is None and g.box_error is None and "hinkt" not in s.status_line, f"{g.status} / {s.status_line}")
check("404 loest keine Pause fuer die anderen Abrufe aus (Scoreboard weiter alle 15 s: 5 Abrufe in 60 s)", len([x for x in net.log if x[1] == "scoreboard"]) == 5 and feed._next_allowed == float("-inf"), str(len([x for x in net.log if x[1] == "scoreboard"])))
# --- 2b) PRE + Serverfehler: bleibt PRE, kein Fehlerhinweis am Spiel
net = Net(box=boxgame()); net.box_status = 500
feed, s = run(net, T_START + 300, 30)
g = G(s)
check("PRE + Boxscore-Fehler (500): Spiel bleibt PRE, kein Fehlerhinweis am Spiel", g.status == "PRE" and g.box_error is None and g.source == "NBA.com", f"{g.status}")
# --- 3) PRE + Boxscore Status 1
net = Net(box=boxgame(status=1, with_clock=False))
feed, s = run(net, T_START + 300, 60)
g = G(s)
check("PRE + Boxscore gameStatus 1: Spiel bleibt PRE, Quelle NBA.com, keine Spieler/Besitze uebernommen", g.status == "PRE" and g.source == "NBA.com" and g.possessions is None and g.players == () and "hinkt" not in s.status_line, f"{g.status}")
net = Net(box=boxgame(status=2, period=0, clock="", with_clock=True))
feed, s = run(net, T_START + 300, 30)
check("PRE + Boxscore Status 2 aber Periode 0 (Spielzeit nicht plausibel): bleibt PRE", G(s).status == "PRE")

# --- 4) vor der geplanten Startzeit kein zusaetzlicher Abruf; nach 4 Stunden nicht mehr
net = Net(box=boxgame())
feed, s = run(net, T_START - 600, 540)
check("vor der geplanten Startzeit: kein Boxscore-Abruf (nur das Scoreboard)", not net.boxes() and G(s).status == "PRE", str(len(net.boxes())))
net = Net(box=boxgame())
feed, s = run(net, T_START - 20, 60)
check("ab der geplanten Startzeit: Abruf (Startzeit erreicht)", len(net.boxes()) >= 1 and all(x[0] >= T_START for x in net.boxes()), str([x[0] - T_START for x in net.boxes()]))
net = Net(box=boxgame())
feed, s = run(net, T_START + lf.PRE_PROBE_MAX_SECONDS + 60, 60)
check("verschobenes Spiel (Startzeit mehr als 4 Stunden her): kein Abruf mehr", not net.boxes() and G(s).status == "PRE")
net = Net(rows=[row(start="kaputt")], box=boxgame())
feed, s = run(net, T_START + 300, 60)
check("ohne lesbare Startzeit: kein Abruf, Spiel bleibt PRE", not net.boxes() and G(s).status == "PRE")

# --- 5) Abrufzaehler: je Spiel hoechstens alle 30 s, hoechstens 6 je Aufruf
net = Net(box=boxgame(status=1, with_clock=False))                              # Boxscore sagt Status 1: es wird weiter nachgefragt
feed, s = run(net, T_START + 100, 150)                                          # 11 Aufrufe im 15-s-Takt
times = [x[0] for x in net.boxes("G1")]
check("ein Spiel: Abstand der Boxscore-Abrufe mindestens 30 s (11 Aufrufe in 150 s -> hoechstens 6 Abrufe)", all(b - a >= 30 for a, b in zip(times, times[1:])) and len(times) <= 6 and len(times) >= 4, str([int(x - T_START) for x in times]))
rows8 = [row(gid=f"G{i}") for i in range(1, 9)]
net = Net(rows=rows8, box=boxgame(status=1, with_clock=False))
feed = lf.LiveFeed(http_get=net.get, now=lambda: T_START + 100)
net.now = T_START + 100; feed.refresh(T_START + 100)
n1 = len(net.boxes())
net.now = T_START + 115; feed.refresh(T_START + 115)
n2 = len(net.boxes()) - n1
net.now = T_START + 130; feed.refresh(T_START + 130)
n3 = len(net.boxes()) - n1 - n2
check("8 Spiele, alle PRE nach Startzeit: je Aufruf hoechstens 6 Boxscores (6, dann die uebrigen 2, dann wieder frueheste nach 30 s)", n1 == 6 and n2 == 2 and n3 <= 6 and n1 + n2 + n3 <= 16, f"{n1}, {n2}, {n3}")
per_game = {}
for x in net.boxes(): per_game.setdefault(x[2], []).append(x[0])
check("8 Spiele: je Spiel Abstand mindestens 30 s", all(b - a >= 30 for ts in per_game.values() for a, b in zip(ts, ts[1:])), str({k: [int(x - T_START) for x in v] for k, v in per_game.items()})[:200])
net = Net(rows=[row(gid="LIVE1", status=2, period=2, clock="PT05M00.00S", hs=40, as_=38), row(gid="PRE1")], box=lambda gid: boxgame(status=2, period=2, clock="PT05M00.00S", hs=40, as_=38) if gid == "LIVE1" else boxgame(status=1, with_clock=False))
feed, s = run(net, T_START + 100, 30)
check("laufende Spiele haben Vorrang vor der PRE-Suche (beide werden abgefragt, gleiche URL)", net.boxes("LIVE1") and net.boxes("PRE1"))

# --- 6) Scoreboard holt auf -> es gilt wieder das Scoreboard
net = Net(box=boxgame(status=2, period=1, clock="PT08M15.00S", hs=10, as_=7))
feed = lf.LiveFeed(http_get=net.get, now=lambda: T_START + 300)
for k in (0, 15, 30):
    net.now = T_START + 300 + k; s = feed.refresh(T_START + 300 + k)
check("Vorbedingung: Spiel laeuft ueber den Boxscore", G(s).source == lf.SOURCE_BOX_SUB)
net.rows = [row(status=2, period=1, clock="PT08M15.00S", hs=10, as_=7)]            # Scoreboard hat den gleichen Stand erreicht
net.now = T_START + 345; s = feed.refresh(T_START + 345)
g = G(s)
check("Scoreboard zieht nach (gleicher Stand): Quelle wieder 'NBA.com', Status LIVE, kein Hinweis 'hinkt'", g.source == "NBA.com" and g.status == "LIVE" and "hinkt" not in s.status_line, f"{g.source} / {s.status_line}")
net.rows = [row(status=2, period=1, clock="PT05M00.00S", hs=14, as_=12)]            # Scoreboard ist sogar weiter als der Boxscore
net.now = T_START + 360; s = feed.refresh(T_START + 360)
check("Scoreboard weiter als der Boxscore: Stand 12:14 vom Scoreboard", (G(s).away_score, G(s).home_score) == (12, 14) and G(s).source == "NBA.com")

# --- 7) Einfrier-Erkennung unveraendert: ein PRE-Spiel gilt nie als eingefroren; laufendes eingefrorenes Spiel weiter wie bisher
net = Net(box=boxgame(status=1, with_clock=False))
feed, s = run(net, T_START + 300, 300)                                              # 5 Minuten PRE, Scoreboard unveraendert (laenger als 90 s)
check("PRE ueber 90 s unveraendert: kein 'eingefroren', keine 'Daten veraltet', kein ESPN-Abruf", "eingefroren" not in s.status_line and not G(s).data_stale and not any(x[1] == "espn" for x in net.log), s.status_line)
net = Net(rows=[row(status=2, period=2, clock="PT10M00.00S", hs=20, as_=20)], box=boxgame(status=2, period=2, clock="PT10M00.00S", hs=20, as_=20))
feed, s = run(net, T_START + 4000, 120)
check("laufendes Spiel, Scoreboard UND Boxscore unveraendert (echte Pause): weiter keine Ersatzquelle, kein ESPN-Abruf (bisheriges Verhalten)", G(s).source == "NBA.com" and not any(x[1] == "espn" for x in net.log))

# --- 8) Wett-Eingabe: gesperrt nach erkanntem Start (Sperre: Anpfiff erreicht UND Scoreboard-Status PRE)
net = Net(box=boxgame(status=2, period=1, clock="PT08M15.00S", hs=10, as_=7))
feed, s = run(net, T_START + 300, 30)
g = G(s)
check("Wett-Eingabe: nach erkanntem Start gesperrt (Status LIVE, Anpfiff erreicht)", g.status == "LIVE" and not be.game_editable(g, T_START + 330))
pre_game = G(run(Net(box=boxgame(status=1, with_clock=False)), T_START - 3600, 30)[1])
check("Wett-Eingabe: vor dem Anpfiff weiter moeglich (PRE, Anpfiff noch nicht erreicht)", pre_game.status == "PRE" and be.game_editable(pre_game, T_START - 3500))
check("Wett-Eingabe: PRE nach der geplanten Startzeit (Boxscore meldet noch nichts) bleibt wie bisher gesperrt", not be.game_editable(G(run(Net(box=boxgame(status=1, with_clock=False)), T_START + 300, 30)[1]), T_START + 330))

# --- 9) Expander "Wettliste nach Kategorien": beim Betreten geschlossen (auch mit Wetten)
from streamlit.testing.v1 import AppTest
import page_checks; page_checks.install()
import ui.bet_list as bl
rec = []
orig_exp = bl.st.expander
def spy(label, *a, **k):
    if str(label).startswith("Wettliste nach Kategorien"):
        rec.append(k.get("expanded", False))
    return orig_exp(label, *a, **k)
bl.st.expander = spy
orig_collect = bl.collect_items
bl.collect_items = lambda rows: [{"dummy": 1}, {"dummy": 2}]                  # "es gibt Wetten": frueher expanded=True
os.environ["NBAEDGE_ALL_TABS"] = "1"
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300).run()
bl.st.expander = orig_exp; bl.collect_items = orig_collect
check("Wettliste: Expander 'Wettliste nach Kategorien' wird mit expanded=False erzeugt (auch bei vorhandenen Wetten)", rec and all(x is False for x in rec), str(rec))
check("Wettliste: Quelltext setzt expanded nicht mehr aus der Wettenzahl", "expanded=bool(items)" not in (ROOT / "ui" / "bet_list.py").read_text(encoding="utf-8"))

check("echte Dateien unveraendert (data/tracking, pregame_lines.json, upcoming_cache.json)", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
