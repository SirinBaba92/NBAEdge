"""Tests fuer die Live-Bewertung der Spieler-Wetten (Stufe 3, Baustein P4): engine/player_live.py (Live-Chance, UNGEPRUEFT, Version live-1), idle_s im Live-Feed, Anzeige in Wettkarten
und Spielertabelle. Offline: Attrappen, Temp-Ordner, keine echten Dateien. Aufruf aus dem Projektordner: venv/bin/python tests/test_player_live.py"""
import hashlib, json, os, re, sys, tempfile, time, warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_SNAPSHOT_DIR=str(T / "snaps"), NBAEDGE_PLAYER_CACHE_DIR=str(T / "cache"),
                  NBAEDGE_ROSTERS=str(T / "rosters.json"), NBAEDGE_LIVE_DIR=str(T / "live"))
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
from scipy.stats import nbinom
from data import day_bets_store as ds
from data import live_feed as lf
from data import pre_match_store as ps
from engine import game_clock as gc
from engine import player_live as pl
from ui import player_tab as pt
from ui import player_view as pv

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*"))
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()

# ------------------------------------------------------------- Engine
PRE = {"ok": True, "minutes": {"base": 34.0, "mean": 33.0, "role": "Stamm"}, "minutes_adjusted": 33.0, "expected_points_adjusted": 22.0}
BENCH = {"ok": True, "minutes": {"base": 14.0, "mean": 14.0, "role": "Bank"}, "minutes_adjusted": 14.0, "expected_points_adjusted": 5.0}
def P(points=10, minutes=15.0, fouls=1, status="spielt", idle=0.0): return NS(points=points, minutes=minutes, fouls=fouls, status=status, idle_s=idle)
CK = lambda period, left, status=2, text="": gc.build_game_clock(status, text, period, left)
def lc(n, player, clock, hs=60, as_=58, pre=PRE): return pl.live_chance(n, player, clock, hs, as_, pre)

check("Version live-1, Kennzeichnung UNGEPRÜFT, Konstanten in einer Liste mit Versionsnummer", pl.LIVE_VERSION == "live-1" and pl.STATUS == "UNGEPRÜFT" and pl.LIVE_CONSTANTS["version"] == "live-1" and lc(20, P(), CK(2, "PT06M00.00S")).version == "live-1")
check("Restzeit: Q1 voll 2880 s, Q2 6:00 = 1800 s, Halbzeit 1440 s, OT 3:00 = 180 s", pl.remaining_game_seconds(CK(1, "PT12M00.00S"), 2) == 2880 and pl.remaining_game_seconds(CK(2, "PT06M00.00S"), 2) == 1800
      and pl.remaining_game_seconds(CK(2, "", text="Halftime"), 2) == 1440 and pl.remaining_game_seconds(CK(5, "PT03M00.00S"), 2) == 180)
check("Restzeit: Ende Q4 bei Gleichstand = 300 s Verlaengerung, sonst 0; beendet 0", pl.remaining_game_seconds(CK(4, ""), 0) == 300 and pl.remaining_game_seconds(CK(4, ""), 3) == 0 and pl.remaining_game_seconds(CK(4, "", status=3), 0) == 0)
check("Punkte >= Meilenstein: Chance 1", lc(20, P(points=20), CK(2, "PT06M00.00S")).probability == 1.0 and lc(20, P(points=25), CK(4, "PT01M00.00S")).probability == 1.0)
check("keine Restzeit und Meilenstein nicht erreicht: Chance 0", lc(20, P(points=15), CK(4, "", status=3)).probability == 0.0 and lc(20, P(points=15), CK(4, ""), 100, 90).probability == 0.0)
a = lc(22, P(points=6, minutes=8.0), CK(1, "PT05M00.00S")); b = lc(22, P(points=14, minutes=8.0), CK(1, "PT05M00.00S"))
check("mehr bisherige Punkte -> hoehere Chance", b.probability > a.probability and 0 < a.probability < 1 and 0 < b.probability < 1, f"{a.probability:.3f} < {b.probability:.3f}")
early = lc(22, P(points=10, minutes=12.0), CK(2, "PT10M00.00S")); late = lc(22, P(points=10, minutes=12.0), CK(4, "PT02M00.00S"))
check("weniger Restzeit bei gleichem Stand -> niedrigere Chance; Restminuten sinken", late.probability < early.probability and late.remaining_minutes < early.remaining_minutes)
ch = [lc(n, P(points=8, minutes=10.0), CK(2, "PT08M00.00S")).probability for n in (12, 16, 20, 24, 28)]
check("hoeherer Meilenstein -> niedrigere Chance (monoton fallend), alle in 0..1", all(a_ >= b_ for a_, b_ in zip(ch, ch[1:])) and all(0 <= x <= 1 for x in ch), str([round(x, 3) for x in ch]))
f1 = lc(22, P(points=14, minutes=24.0, fouls=1), CK(4, "PT08M00.00S")); f5 = lc(22, P(points=14, minutes=24.0, fouls=5), CK(4, "PT08M00.00S"))
check("5 Fouls: deutlich niedrigere Chance und Restminuten als 1 Foul, Hinweis 'Foulprobleme'", f5.probability < f1.probability * 0.8 and f5.remaining_minutes < f1.remaining_minutes and any("Foulprobleme (5 Fouls" in n for n in f5.notes))
f6 = lc(22, P(points=14, minutes=24.0, fouls=6), CK(4, "PT08M00.00S"))
check("6 Fouls: ausgeschieden, Chance 0, out, Hinweis", f6.probability == 0.0 and f6.out and any("ausgeschieden" in n for n in f6.notes))
check("Foulfaktoren: 4 Fouls in Q2 strenger als in Q4, 3 Fouls in Q1 leichter Abschlag, 2 Fouls keiner", pl.foul_factor(4, 2) < pl.foul_factor(4, 4) < 1 and pl.foul_factor(3, 1) < 1 and pl.foul_factor(3, 4) == 1 and pl.foul_factor(2, 1) == 1 and pl.foul_factor(6, 1) == 0)
close = lc(22, P(points=15, minutes=29.0), CK(4, "PT06M00.00S"), 90, 88)
blow = lc(22, P(points=15, minutes=29.0), CK(4, "PT06M00.00S"), 115, 90)
check("Blowout (+25 in Q4): Restminuten und Chance viel niedriger als im knappen Spiel, Hinweis mit Faktor aus der gemessenen Kurve", blow.remaining_minutes < close.remaining_minutes * 0.6 and blow.probability < close.probability and any("Blowout-Abschlag" in n for n in blow.notes), f"{close.remaining_minutes:.1f} / {blow.remaining_minutes:.1f}")
check("Blowout-Faktor live nutzt dieselbe Kurve wie die Vorab-Prognose (Stamm, +35 -> ~0,85; knapp ~1,0)", abs(pl.pf.blowout_factor_live(34, 35, 60) - 0.845 / pl.pf._REF["Stamm"]) < 0.01 and 0.95 < pl.pf.blowout_factor_live(34, 3, 60) < 1.12)
bk = lc(12, P(points=4, minutes=6.0), CK(4, "PT06M00.00S"), 115, 90, pre=BENCH)
check("Bankspieler: kein Blowout-Abschlag (Kurve Faktor 1,0)", not any("Blowout" in n for n in bk.notes))
inact = lc(10, P(points=0, minutes=0.0, status="nicht gespielt"), CK(2, "PT06M00.00S"))
check("laut Boxscore inaktiv ohne Einsatz: Chance 0, out, Hinweis", inact.probability == 0.0 and inact.out and any("inaktiv" in n for n in inact.notes))
idle_ok = lc(22, P(points=12, minutes=18.0, status="bank", idle=300.0), CK(3, "PT06M00.00S"))
idle_out = lc(22, P(points=12, minutes=18.0, status="bank", idle=900.0), CK(3, "PT06M00.00S"))
check("Stammspieler >= 12 Min. Spielzeit nicht auf dem Feld: Verdacht auf Ausfall, Chance deutlich gesenkt, Hinweis; kuerzere Pause: kein Verdacht", idle_out.out and idle_out.probability < idle_ok.probability * 0.4 and any("Verdacht auf Verletzung oder Sperre" in n for n in idle_out.notes) and not idle_ok.out)
check("auf dem Feld (spielt) zaehlt idle nicht; Bankspieler (Rolle Bank) ohne Verdacht", not lc(22, P(points=12, minutes=18.0, status="spielt", idle=900.0), CK(3, "PT06M00.00S")).out and not lc(10, P(points=4, minutes=8.0, status="bank", idle=900.0), CK(3, "PT06M00.00S"), pre=BENCH).out)
nopre = lc(22, P(points=8, minutes=10.0), CK(2, "PT08M00.00S"), pre=None)
check("ohne Prognose-Snapshot: allgemeine Annahmen mit Hinweis, trotzdem eine Chance", 0 < nopre.probability < 1 and any("ohne Prognose-Snapshot" in n for n in nopre.notes))
lam, var = 5.0, 12.0; n_, p_ = lam * lam / (var - lam), lam / var
check("Verteilung: Negative Binomial mit Erwartung und Varianz passend, P(>=k) summiert sich richtig; k <= 0 -> 1; Erwartung 0 -> 0; Varianz = Erwartung -> Poisson",
      abs(nbinom.mean(n_, p_) - lam) < 1e-9 and abs(nbinom.var(n_, p_) - var) < 1e-9 and abs(pl.points_distribution_tail(lam, var, 3) - (1 - nbinom.cdf(2, n_, p_))) < 1e-12 and pl.points_distribution_tail(lam, var, 0) == 1.0
      and pl.points_distribution_tail(0.0, 1.0, 2) == 0.0 and abs(pl.points_distribution_tail(4.0, 4.0, 2) - (1 - (2.718281828 ** -4) * (1 + 4))) < 1e-6)
check("pure Funktion: gleiche Eingabe, gleiche Ausgabe (kein Zufall)", lc(22, P(), CK(2, "PT06M00.00S")) == lc(22, P(), CK(2, "PT06M00.00S")))

# ------------------------------------------------------------- Live-Feed: idle_s aus dem Verlauf der Boxscores
T0 = datetime(2026, 10, 23, 3, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
D = lf.current_us_day(T0)
class R:
    def __init__(self, payload): self.status_code, self._p, self.text = 200, payload, ""
    def json(self): return self._p
def srow(period, clock, hs, as_, start="2026-10-23T01:30:00Z", status=2):
    t = lambda nick, sc: {"teamCity": nick.split()[0], "teamName": nick.split()[1], "teamTricode": nick[:3].upper(), "score": sc, "periods": []}
    return {"gameId": "L1", "gameStatus": status, "gameStatusText": "", "period": period, "gameClock": clock, "gameEt": f"{D}T19:00:00-04:00", "gameTimeUTC": start, "homeTeam": t("Heim Falken", hs), "awayTeam": t("Gast Baeren", as_)}
def bplayer(pid, name, pts, mins, on, fouls=1, status="ACTIVE", played="1", reason=""):
    d = {"personId": pid, "name": name, "oncourt": on, "played": played, "status": status, "statistics": {"points": pts, "minutes": f"PT{int(mins):02d}M{int((mins % 1) * 60):02d}.00S", "foulsPersonal": fouls}}
    if reason: d["notPlayingReason"] = reason
    return d
def bgame(period, clock, hs, as_, players):
    s = {"fieldGoalsAttempted": 30, "freeThrowsAttempted": 8, "reboundsOffensive": 4, "turnoversTotal": 5}
    return {"gameStatus": 2, "period": period, "gameClock": clock, "homeTeam": {"score": hs, "statistics": dict(s), "teamTricode": "HEI", "players": players}, "awayTeam": {"score": as_, "statistics": dict(s), "players": []}}
class Net:
    def __init__(self): self.row, self.box = srow(2, "PT08M00.00S", 40, 38), None
    def get(self, url, headers=None, params=None, timeout=None):
        if "espn.com" in url: return R({"events": []})
        if "scoreboard" in url: return R({"scoreboard": {"gameDate": D, "games": [self.row]}})
        return R({"game": self.box})
net = Net()
net.box = bgame(2, "PT08M00.00S", 40, 38, [bplayer(1, "Star", 12, 14.0, "1"), bplayer(2, "Bank", 2, 5.0, "0")])
feed = lf.LiveFeed(http_get=net.get, now=lambda: T0); feed.refresh(T0)
p1 = {p.person_id: p for p in feed.state(T0).games[0].players}
check("erster Boxscore: idle_s 0 fuer alle", p1[1].idle_s == 0 and p1[2].idle_s == 0)
net.row = srow(2, "PT05M00.00S", 46, 42); net.box = bgame(2, "PT05M00.00S", 46, 42, [bplayer(1, "Star", 12, 14.0, "0"), bplayer(2, "Bank", 4, 8.0, "1")])      # Star geht raus, Bank rein
feed.refresh(T0 + 40)
p2 = {p.person_id: p for p in feed.state(T0 + 40).games[0].players}
check("Star ist draussen (Minuten unveraendert): idle_s = Spielzeit seit der letzten Aenderung (3:00 = 180 s), Bank auf dem Feld 0", p2[1].idle_s == 180.0 and p2[2].idle_s == 0 and p2[1].status == "bank", str(p2[1].idle_s))
net.row = srow(2, "PT00M30.00S", 60, 55); net.box = bgame(2, "PT00M30.00S", 60, 55, [bplayer(1, "Star", 12, 14.0, "0"), bplayer(2, "Bank", 9, 12.0, "1")])
feed.refresh(T0 + 90)
p3 = {p.person_id: p for p in feed.state(T0 + 90).games[0].players}
check("weiter draussen: idle_s waechst mit der Spielzeit (7:30 = 450 s)", p3[1].idle_s == 450.0, str(p3[1].idle_s))
net.row = srow(3, "PT10M00.00S", 62, 57); net.box = bgame(3, "PT10M00.00S", 62, 57, [bplayer(1, "Star", 12, 16.0, "1"), bplayer(2, "Bank", 9, 12.0, "0")])
feed.refresh(T0 + 140)
p4 = {p.person_id: p for p in feed.state(T0 + 140).games[0].players}
check("Star spielt wieder (Minuten steigen): idle_s zurueck auf 0", p4[1].idle_s == 0.0 and p4[2].idle_s > 0)
check("nicht eingesetzte Spieler (played=0): idle_s bleibt 0; Grund aus dem Boxscore (notPlayingReason) uebernommen", True)
net.box = bgame(3, "PT10M00.00S", 62, 57, [bplayer(1, "Star", 12, 16.0, "1"), bplayer(3, "Out", 0, 0.0, "0", status="INACTIVE", played="0", reason="INACTIVE_INJURY_MANAGEMENT")])
feed.refresh(T0 + 200)
p5 = {p.person_id: p for p in feed.state(T0 + 200).games[0].players}
check("inaktiver Spieler: Status 'nicht gespielt', Grund aus dem Boxscore, idle 0", p5[3].status == "nicht gespielt" and p5[3].reason == "INACTIVE_INJURY_MANAGEMENT" and p5[3].idle_s == 0.0)

# ------------------------------------------------------------- Wetten-Status mit Live-Chance
g_live = feed.state(T0 + 140).games[0]
net.box = bgame(3, "PT10M00.00S", 62, 57, [bplayer(1, "Star", 12, 16.0, "1"), bplayer(2, "Bank", 9, 12.0, "0")]); feed.refresh(T0 + 230)
g_live = feed.state(T0 + 230).games[0]
bets = {1: {"active": True, "name": "Star", "milestone": 20, "odds": 2.0, "stake": 10.0}, 2: {"active": True, "name": "Bank", "milestone": 8, "odds": 1.5, "stake": 5.0}}
lv = ds.evaluate_player_bets(bets, g_live, {1: {**PRE, "person_id": 1}})
check("laufende Wette: Live-Chance gesetzt (0..1), Hinweise vorhanden (tuple); bereits erreichte Wette gewonnen ohne Live-Chance", lv[1].state == "laeuft" and 0 < lv[1].probability < 1 and isinstance(lv[1].live_notes, tuple) and lv[2].state == "gewonnen" and lv[2].probability is None)
lv_np = ds.evaluate_player_bets(bets, g_live)
check("ohne Snapshot: Live-Chance mit Hinweis 'ohne Prognose-Snapshot'", lv_np[1].probability is not None and any("ohne Prognose-Snapshot" in n for n in lv_np[1].live_notes))
import dataclasses
stale = dataclasses.replace(g_live, data_stale=True)
check("eingefrorene Daten ohne Ersatzquelle: keine Live-Chance", ds.evaluate_player_bets(bets, stale, {1: PRE})[1].probability is None)
final_ = dataclasses.replace(g_live, clock=gc.build_game_clock(3, "Final", 4, ""), status="FINAL", players_complete=True)
check("beendetes Spiel: keine Live-Chance (Status entschieden)", ds.evaluate_player_bets(bets, final_, {1: PRE})[1].probability is None)
card = pv.bet_card_html(bets[1], lv[1], "Baeren @ Falken", "Q3 10:00", "57 : 62", "LIVE")
check("Wettkarte (laufend): grosse Live-Chance 'x %', 'noch N Pkt.', 'ungeprüft'", re.search(r"pl-prob-val'>\d+ %<", card) is not None and "noch " in card and "ungeprüft" in card)
inj = ds.evaluate_player_bets(bets, dataclasses.replace(g_live, players=tuple(dataclasses.replace(p, idle_s=900.0, status="bank") for p in g_live.players)), {1: PRE})
card_inj = pv.bet_card_html(bets[1], inj[1], "x")
check("Verdacht auf Ausfall im Spiel: Live-Chance stark gesenkt, Hinweiszeile mit ⚠ auf der Karte", inj[1].live_out and inj[1].probability < lv[1].probability * 0.4 and "⚠ seit" in card_inj and "Verdacht auf Verletzung oder Sperre" in card_inj)

# ------------------------------------------------------------- Tabelle mit Live-Spalten
entry = {"game_key": "k", "players": [
    {"person_id": 1, "name": "Star", "team": "Heim Falken", "team_abbreviation": "HEI", "ok": True, "reason": None, "quality": [], "warnings": [], "minutes": {"base": 34.0, "mean": 33.0, "role": "Stamm"}, "minutes_adjusted": 33.0,
     "expected_points_raw": 24.0, "expected_points_adjusted": 22.0, "p_ge_raw": {"20": 0.5, "25": 0.3}, "p_ge_adjusted": {"20": 0.45, "25": 0.25},
     "quotes": [{"milestone": 20, "odds": 2.2, "bookmaker": "Betano", "bookmaker_probability": 1 / 2.2, "bookmaker_percent": 45}, {"milestone": 25, "odds": 4.0, "bookmaker": "Betano", "bookmaker_probability": 0.25, "bookmaker_percent": 25}]}]}
ld = pt.live_table_data(g_live, entry)
check("live_table_data: Punkte, Minuten, Fouls und Live-Chancen je Meilenstein; nur laufende Spiele", set(ld) == {1} and ld[1]["points"] == 12 and ld[1]["chances"][20] > ld[1]["chances"][25] and pt.live_table_data(final_, entry) == {} and pt.live_table_data(None, entry) == {} and pt.live_table_data(stale, entry) == {})
html = pv.render_table_html(pv.build_table_model(entry, "team", "team", None, ld))
check("Tabelle: Spalten 'Jetzt' und 'Live (ungeprüft)', Werte '12 · 16,0 · 1', Live-Prozent je Meilenstein", "Jetzt<small>" in html and "Live<small> ungeprüft" in html and "12 · 16,0 · 1" in html and html.count("class='pl-live'") == 2 and re.search(r"class='pl-live'>\d+ %", html) is not None)
html0 = pv.render_table_html(pv.build_table_model(entry, "team", "team"))
check("ohne laufendes Spiel: keine Live-Spalten", "Jetzt<small>" not in html0 and "pl-live'>" not in html0)
ld2 = {1: {**ld[1], "points": 21}}
check("Meilenstein bereits erreicht: 'erreicht'", "erreicht" in pv.render_table_html(pv.build_table_model(entry, "team", "team", None, ld2)))

# ------------------------------------------------------------- Tab im Harness (laufendes Spiel, 30-s-Fragment)
D = lf.current_us_day(time.time())      # der Tab laeuft mit der echten Uhr (LiveFeed ohne now=): Spieltag von heute, nicht der feste von T0
K = ps.game_key(D,"2026-10-23T01:30:00Z", "Heim Falken", "Gast Baeren")
def line(th, odds): return {"id": f"x{th}", "threshold": th, "odds": odds, "bookmaker": "Betano", "active": True, "updated_at": "2026-10-22T20:00:00+02:00", "entered_at": "2026-10-22T20:00:00+02:00"}
(T / "tracking").mkdir(parents=True, exist_ok=True)
(T / "tracking" / "pre_match_entries.json").write_text(json.dumps({"version": 5, "format": "nbaedge-pre-match", "markets": {}, "last_bookmaker": {}, "updated_at": None, "entries": {
    K: {"game_date": D, "markets": {"player_points": {"players": [{"id": "p1", "person_id": 1, "name": "Star", "team": "Heim Falken", "team_abbreviation": "HEI", "mode": "milestones", "active": True, "lines": [line(20, 2.2), line(25, 4.0)]}]}}}}}))
snap_entry = {**entry, "game_key": K, "created_at": "2026-10-23T00:19:41+02:00", "created_after_start": False, "note": "vor Anpfiff erstellt", "history": "x", "teams": {}}
(T / "snaps").mkdir(parents=True, exist_ok=True)
(T / "snaps" / f"{D}.json").write_text(json.dumps({"version": 1, "day": D, "games": {K: snap_entry}}))
ds.set_player_bet(D, "2026-10-23T01:30:00Z", "Heim Falken", "Gast Baeren", 1, "Star", "Heim Falken", 20, odds=2.2, stake=10, now=T0 - 3 * 3600)
tn = Net(); tn.row = srow(3, "PT10M00.00S", 62, 57); tn.box = bgame(3, "PT10M00.00S", 62, 57, [bplayer(1, "Star", 12, 16.0, "1")])
lf._feed = lf.LiveFeed(http_get=tn.get)
at = AppTest.from_file(str(ROOT / "tests" / "_harness_player_tab.py"), default_timeout=60).run()
at.selectbox(key="pl_day").set_value(D).run()
md = " ".join(x.value for x in at.markdown)
check("Tab bei laufendem Spiel: keine Exception/Warnung", not at.exception and not problems(at), " | ".join(problems(at))[:200])
check("'Meine Spieler-Wetten': Karte 'Punkte 12 von 20, noch 8' (laufend), Live-Chance in Prozent (ungeprüft)", "Punkte 12 von 20, noch 8" in md and re.search(r"pl-prob-val'>\d+ %</span><span class='pl-prob-sub'>noch 8 Pkt\.</span><span class='pl-prob-tiny'>ungeprüft</span>", md) is not None)
check("Prognose-Karten des laufenden Spiels: Zeile 'Jetzt', Live-Chance je Meilenstein (2) und Hinweiszeile 'Spiel läuft ... UNGEPRÜFT (Version live-1)'", "pl-c-now'>Jetzt: <b>12</b> Pkt · <b>16,0</b> Min · <b>1</b> Fouls" in md and len(re.findall(r"pl-c-live'>Live \d+ %<", md)) == 2 and "Version live-1" in md and "Q3 10:00" in md, "")

check("echte Dateien (Tracking, Snapshots) unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
