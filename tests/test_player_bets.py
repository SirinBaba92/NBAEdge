"""Tests fuer Spieler-Wetten (Punkte, mindestens N, Over): Speicher (data/day_bets_store.py), Status (engine/bet_status.py), Live-Feed-Spielerliste (data/live_feed.py).
Nur Temp-Ordner (NBAEDGE_TRACKING_DIR, NBAEDGE_SNAPSHOT_DIR), nie die echten Dateien; kein Netz. Aufruf aus dem Projektordner: venv/bin/python tests/test_player_bets.py"""
import hashlib, json, os, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))

TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ["NBAEDGE_TRACKING_DIR"] = str(T / "tracking")
os.environ["NBAEDGE_SNAPSHOT_DIR"] = str(T / "snaps")
from data import day_bets_store as ds
from data import live_feed as lf
from data import pre_match_store as ps
from engine import bet_status as bs
from engine import game_clock as gc

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e) or True
    except Exception:
        return False
    return False

def snap():
    files = list((ROOT / "data" / "tracking").glob("*")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*"))
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = snap()

NOW = 1_792_800_000.0
H = 3600
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
START, PAST = iso(NOW + 6 * H), iso(NOW - 3 * H)
D, HOME, AWAY = "2026-10-22", "Philadelphia 76ers", "Cleveland Cavaliers"
args = (D, START, HOME, AWAY)
fpath = T / "tracking" / "day_bets.json"

# --- Setzen, Aendern, Entfernen
r = ds.set_player_bet(*args, 1628386, "Jarrett Allen", "Cleveland Cavaliers", 15, odds=2.18, stake=10, odds_source="gespeichert", odds_ref={"bookmaker": "Betano", "updated_at": "x", "milestone": 15}, now=NOW)
d = json.loads(fpath.read_text())
b = d["games"][r["key"]]["player_bets"]["1628386"]
check("Setzen: gespeichert unter player_bets[person_id], Felder, Seite immer over, Dateiversion 2", r["status"] == "saved" and d["version"] == 2 and b["market"] == "player_points" and b["side"] == "over"
      and (b["person_id"], b["name"], b["team"], b["milestone"], b["odds"], b["stake"], b["odds_source"], b["active"]) == (1628386, "Jarrett Allen", "Cleveland Cavaliers", 15, 2.18, 10.0, "gespeichert", True)
      and b["odds_ref"]["bookmaker"] == "Betano" and b["revisions"] == [] and b["removed_at"] is None)
check("gleiche Wette nochmal: unveraendert, keine Revision", ds.set_player_bet(*args, 1628386, "Jarrett Allen", "Cleveland Cavaliers", 15, odds=2.18, stake=10, odds_source="gespeichert", odds_ref={"bookmaker": "Betano", "updated_at": "x", "milestone": 15}, now=NOW + 5)["status"] == "unchanged")
r2 = ds.set_player_bet(*args, 1628386, "Jarrett Allen", "Cleveland Cavaliers", 18, odds=3.45, stake=10, now=NOW + 60)
b2 = r2["bet"]
check("Aendern: Meilenstein 18, alter Stand als Revision 'geaendert', placed_at bleibt", b2["milestone"] == 18 and len(b2["revisions"]) == 1 and b2["revisions"][0]["reason"] == "geaendert" and b2["revisions"][0]["milestone"] == 15
      and b2["placed_at"] == b["placed_at"] and b2["updated_at"] != b["updated_at"])
check("nur EINE aktive Wette je Spieler (ein Eintrag)", len(ds.get_player_bets_by_key(r["key"])) == 1 and ds.get_player_bets_by_key(r["key"])[1628386]["milestone"] == 18)
ds.set_player_bet(*args, 201935, "James Harden", "Cleveland Cavaliers", 17, odds=1.75, now=NOW + 70)
ds.set_player_bet(*args, 1630552, "Jalen Johnson", "Philadelphia 76ers", 20, now=NOW + 80)
check("mehrere Spieler je Spiel, Schluessel person_id", sorted(ds.get_player_bets_by_key(r["key"])) == [201935, 1628386, 1630552])
rem = ds.remove_player_bet(*args, 201935, now=NOW + 90)
rb = rem["bet"]
check("Entfernen loescht nicht: active False, removed_at, Revision 'entfernt'", rem["status"] == "removed" and rb["active"] is False and rb["removed_at"] and rb["revisions"][-1]["reason"] == "entfernt" and rb["revisions"][-1]["milestone"] == 17)
check("entfernte Wette nur mit include_removed sichtbar; nochmal entfernen = none", 201935 not in ds.get_player_bets_by_key(r["key"]) and 201935 in ds.get_player_bets_by_key(r["key"], include_removed=True)
      and ds.remove_player_bet(*args, 201935, now=NOW + 95)["status"] == "none" and ds.remove_player_bet(*args, 999, now=NOW + 95)["status"] == "none")
re_ = ds.set_player_bet(*args, 201935, "James Harden", "Cleveland Cavaliers", 19, now=NOW + 100)
check("nach Entfernen neu setzen: aktiv, Historie bleibt", re_["bet"]["active"] and re_["bet"]["milestone"] == 19 and len(re_["bet"]["revisions"]) == 1)
day = ds.get_day_player_bets(D)
check("Tageszugriff: Spiel mit 3 aktiven Spieler-Wetten", list(day) == [r["key"]] and sorted(day[r["key"]]["player_bets"]) == [201935, 1628386, 1630552])

# --- Sperre ab Anpfiff
check("Sperre: Setzen nach Anpfiff verboten", raises(ps.GameStartedError, ds.set_player_bet, D, PAST, HOME, AWAY, 5, "X", None, 10, now=NOW))
check("Sperre: Entfernen nach Anpfiff verboten", raises(ps.GameStartedError, ds.remove_player_bet, D, PAST, HOME, AWAY, 1628386, now=NOW))
check("Sperre: unbekannter Anpfiff gilt als begonnen", raises(ps.GameStartedError, ds.set_player_bet, D, None, HOME, AWAY, 5, "X", None, 10, now=NOW))
# --- Eingaben
for label, kw in (("Meilenstein 0", dict(milestone=0)), ("Meilenstein 81", dict(milestone=81)), ("Meilenstein 12,5", dict(milestone=12.5)), ("Meilenstein Text", dict(milestone="abc")),
                  ("Meilenstein bool", dict(milestone=True)), ("person_id 0", dict(person_id=0)), ("person_id Text", dict(person_id="x")), ("Name leer", dict(name=" ")),
                  ("Quote 1,0", dict(odds=1.0)), ("Einsatz 0", dict(stake=0))):
    base = dict(person_id=7, name="Test", team="T", milestone=10, odds=None, stake=None); base.update(kw)
    check(f"ungueltige Eingabe abgelehnt: {label}", raises(ds.BetInputError, ds.set_player_bet, *args, base.pop("person_id"), base.pop("name"), base.pop("team"), base.pop("milestone"), now=NOW, **base))
check("Texteingaben werden angenommen (Meilenstein '14', person_id '77', Quote '1,85')", ds.set_player_bet(*args, "77", "Text Spieler", None, "14", odds="1,85", now=NOW)["bet"]["odds"] == 1.85)

# --- vorhandene Team-Wetten unveraendert
ds.set_bet(*args, "total", "over", 231.5, 1.9, 20, now=NOW + 200)
team = ds.get_bets(*args)
check("Team-Wetten unveraendert: get_bets enthaelt nur Team-Maerkte", list(team) == ["total"] and team["total"]["line"] == 231.5 and "player_points" not in team)
check("list_day_bets / get_day_bets ohne Spieler-Wetten", [x["market"] for x in ds.list_day_bets(D)] == ["total"] and list(ds.get_day_bets(D)[r["key"]]["bets"]) == ["total"])
d = json.loads(fpath.read_text())
check("beide Arten im selben Spiel gespeichert", set(d["games"][r["key"]]["bets"]) == {"total"} and len(d["games"][r["key"]]["player_bets"]) >= 3)

# --- alte Dateien lesbar, Version
old = {"version": 1, "format": "nbaedge-day-bets", "updated_at": "x", "games": {"k|1": {"game_date": D, "start_utc": START, "home": "A", "away": "B",
       "bets": {"winner": {"market": "winner", "active": True, "side": "home", "line": None, "odds": 1.5, "stake": 5.0, "odds_source": "manuell", "line_ref": None,
                           "placed_at": "x", "updated_at": "x", "removed_at": None, "revisions": []}}}}}
fpath.write_text(json.dumps(old))
check("alte Datei (Version 1) lesbar", ds.load().get("error") is None and ds.get_bets_by_key("k|1")["winner"]["odds"] == 1.5 and ds.get_player_bets_by_key("k|1") == {})
ds.set_bet(D, START, "A", "B", "total", "over", 220.5, now=NOW)
check("Team-Wette in alter Datei: Version bleibt 1", json.loads(fpath.read_text())["version"] == 1)
ds.set_player_bet(D, START, "A", "B", 5, "Fuenf", "A", 12, now=NOW)
d = json.loads(fpath.read_text())
check("erste Spieler-Wette hebt auf Version 2, alte Wetten bleiben erhalten", d["version"] == 2 and "winner" in d["games"]["k|1"]["bets"] and len(ds.get_day_player_bets(D)) == 1)
fpath.write_text(json.dumps({**old, "version": 3}))
check("Version 3 (zu neu): Fehler statt Ueberschreiben", ds.load().get("error") and raises(ds.DayBetsError, ds.set_player_bet, *args, 5, "X", None, 10, now=NOW))
fpath.write_text("{kaputt")
err = raises(ds.DayBetsError, ds.set_player_bet, *args, 5, "X", None, 10, now=NOW)
check("beschaedigte Datei: Sicherungskopie, Fehler, Datei unveraendert", bool(err) and fpath.read_text() == "{kaputt" and list((T / "tracking").glob("day_bets.corrupt-*.json")))
fpath.write_text(json.dumps({**old, "games": {"k|1": {**old["games"]["k|1"], "player_bets": []}}}))
check("player_bets mit falschem Typ gilt als beschaedigt", ds.load().get("error"))
fpath.unlink()

# --- Status (engine/bet_status.py)
P = lambda pts, mins=20.0, fouls=2, status="spielt": SimpleNamespace(points=pts, minutes=mins, fouls=fouls, status=status)
bet = {"milestone": 15, "odds": 2.0, "stake": 10.0}
st = lambda player, started=True, final=False, complete=True: bs.player_bet_status(bet, player, started, final, complete)
s0 = st(None, started=False)
check("wartet auf Anpfiff", s0.state == "wartet" and s0.label == "Wartet auf Anpfiff" and not s0.decided and s0.needed == 15)
s1 = st(P(9, 18.5, 3))
check("laeuft: aktuelle Punkte, noch noetig, Minuten, Fouls, Spielerstatus", (s1.state, s1.points, s1.needed, s1.minutes, s1.fouls, s1.player_status, s1.decided, s1.probability) == ("laeuft", 9, 6, 18.5, 3, "spielt", False, None))
check("genau N Punkte gewinnt sofort (waehrend des Spiels)", st(P(15)).state == "gewonnen" and st(P(15)).decided and st(P(15)).won is True and st(P(15)).needed == 0)
check("14 von 15: noch nicht gewonnen", st(P(14)).state == "laeuft")
check("mehr als N Punkte gewinnt auch nach Spielende", st(P(22), final=True).state == "gewonnen")
check("verloren: Spiel beendet, Punkte < N, aktueller Boxscore", st(P(12), final=True).state == "verloren" and st(P(12), final=True).won is False and st(P(12), final=True).decided)
check("verloren erst nach Spielende (laufend: nie verloren)", st(P(0, 30)).state == "laeuft")
dnp = st(P(0, 0.0, 0, "bank"), final=True)
check("nicht gespielt: Spiel beendet und 0 Minuten -> eigener Status, nicht entschieden", dnp.state == "nicht_gespielt" and dnp.label == "Nicht gespielt, Einsatz meist zurück, bitte prüfen" and not dnp.decided and dnp.won is None)
check("nicht gespielt: Spieler fehlt im Boxscore des beendeten Spiels", st(None, final=True).state == "nicht_gespielt")
check("Spiel beendet, Boxscore aelter als Endstand: 'unsicher' statt verloren/nicht gespielt", st(P(12), final=True, complete=False).state == "unsicher" and st(P(0, 0.0), final=True, complete=False).state == "unsicher")
check("laufend und Spieler fehlt (noch kein Boxscore): keine Daten", st(None).state == "keine_daten")
check("Gewinn: gewonnen = Einsatz*(Quote-1), verloren = -Einsatz, nicht gespielt/offen = None",
      bs.player_profit(bet, st(P(15))) == 10.0 and bs.player_profit(bet, st(P(3), final=True)) == -10.0 and bs.player_profit(bet, dnp) is None and bs.player_profit(bet, s1) is None
      and bs.player_profit({"milestone": 15}, st(P(15))) is None)

# --- evaluate_player_bets mit GameView-aehnlichem Objekt, Zuordnung ueber person_id
def game(status, complete=True, players=()):
    clock = SimpleNamespace(is_live=status == "LIVE", is_final=status == "FINAL")
    return SimpleNamespace(clock=clock, players=tuple(players), players_complete=complete)
def pl(pid, name, pts, mins, side="home", status="spielt"): return lf.PlayerLive(pid, name, side, "CLE", pts, mins, 1, status, mins > 0)
bets = {1628386: {"active": True, "name": "Jarrett Allen", "milestone": 15, "odds": 2.0, "stake": 10.0}, 201935: {"active": True, "name": "James Harden", "milestone": 20, "odds": 1.8, "stake": 5.0},
        1630552: {"active": True, "name": "Jalen Johnson", "milestone": 10, "odds": 1.5, "stake": 20.0}, 5: {"active": False, "name": "Weg", "milestone": 5, "odds": None, "stake": None}}
fin = ds.evaluate_player_bets(bets, game("FINAL", True, [pl(1628386, "J. Allen (anderer Schreibweise)", 16, 30), pl(201935, "Harden", 12, 33), pl(1630552, "Johnson", 0, 0.0, status="nicht gespielt")]))
check("Zuordnung ueber person_id (Name im Boxscore weicht ab)", fin[1628386].state == "gewonnen" and fin[1628386].points == 16 and fin[1628386].profit == 10.0)
check("Endstand: verloren mit Verlust -5, nicht gespielt ohne Gewinn/Verlust, entfernte Wette 'entfernt'", fin[201935].state == "verloren" and fin[201935].profit == -5.0 and fin[1630552].state == "nicht_gespielt"
      and fin[1630552].profit is None and fin[5].state == "entfernt")
pre = ds.evaluate_player_bets(bets, game("PRE"))
check("vor dem Anpfiff: alle wartend", all(v.state == "wartet" for k, v in pre.items() if k != 5))
liv = ds.evaluate_player_bets(bets, game("LIVE", True, [pl(1628386, "A", 9, 20.5)]))
check("laufend: Spieler im Boxscore laeuft, fehlender 'keine_daten'", liv[1628386].state == "laeuft" and liv[1628386].needed == 6 and liv[1628386].minutes == 20.5 and liv[201935].state == "keine_daten")

# --- Tagesuebersicht
sm = ds.summarize(list(fin.values()))
check("Tagesuebersicht Spieler: 3 Wetten (entfernte zaehlt nicht), 0 offen, 1 gewonnen, 1 verloren, 1 nicht gespielt separat",
      (sm["wetten"], sm["offen"], sm["gewonnen"], sm["verloren"], sm["nicht_gespielt"]) == (3, 0, 1, 1, 1), str(sm))
check("Einsatz 35 (alle), abgerechnet 15, Gewinn/Verlust +5 (10 - 5), nicht gespielt 20 getrennt", (sm["einsatz"], sm["einsatz_abgerechnet"], sm["gewinn_verlust"], sm["einsatz_nicht_gespielt"]) == (35.0, 15.0, 5.0, 20.0), str(sm))
sm_live = ds.summarize(list(liv.values()))
check("laufende Spieler-Wetten zaehlen als offen", sm_live["offen"] == 3 and sm_live["wetten"] == 3)
bl = ds.BetLive("total", "over", 231.5, 1.9, 20.0, "Gewonnen", "gruen", "gewonnen", 1.0, True, True, 18.0, 120, 115, True)
mixed = ds.summarize([bl] + list(fin.values()))
check("Team- und Spieler-Wetten gemischt: Summen addieren sich", (mixed["wetten"], mixed["gewonnen"], mixed["verloren"], mixed["gewinn_verlust"], mixed["nicht_gespielt"]) == (4, 2, 1, 23.0, 1), str(mixed))
check("ohne Spieler-Wetten keine zusaetzlichen Schluessel (alte Form bleibt)", "nicht_gespielt" not in ds.summarize([bl]))

# --- Auswahl-Logik mit und ohne Snapshot
KEY = ps.game_key(D, START, HOME, AWAY)
def line(th, odds, upd="2026-10-22T20:00:00+02:00"): return {"id": f"x{th}", "threshold": th, "odds": odds, "bookmaker": "Betano", "active": True, "updated_at": upd, "entered_at": upd}
blocks = [{"id": "p1", "person_id": 1628386, "name": "Jarrett Allen", "team": "Cleveland Cavaliers", "team_abbreviation": "CLE", "mode": "milestones", "active": True, "lines": [line(10, 1.4), line(15, 2.18)]},
          {"id": "p2", "person_id": 201935, "name": "James Harden", "team": "Cleveland Cavaliers", "team_abbreviation": "CLE", "mode": "milestones", "active": True, "lines": [line(16, 1.6)]}]
entries = {KEY: {"markets": {"player_points": {"players": blocks}}}}
(T / "snaps").mkdir()
no_snap = ds.player_bet_options(KEY, entries=entries, bets={})
check("ohne Snapshot: Spieler und Betano-Meilensteine, Modell-Chancen None, Hinweis", [p["name"] for p in no_snap["players"]] == ["Jarrett Allen", "James Harden"] and no_snap["snapshot"] is False
      and all(o["model_raw"] is None and o["model_team"] is None for p in no_snap["players"] for o in p["options"]) and "kein Prognose-Snapshot" in no_snap["snapshot_note"])
allen = next(p for p in no_snap["players"] if p["person_id"] == 1628386)
check("Option: Meilenstein, Quote, Buchmacher-Chance inkl. Marge (1/Quote), Stand der Quote", allen["options"][1]["milestone"] == 15 and allen["options"][1]["odds"] == 2.18 and allen["options"][1]["bookmaker_percent"] == 46
      and abs(allen["options"][1]["bookmaker_probability"] - 1 / 2.18) < 1e-12 and allen["options"][1]["updated_at"] == "2026-10-22T20:00:00+02:00")
check("nur eingelesene Meilensteine waehlbar", ds.selectable_milestones(no_snap, 1628386) == [10, 15] and ds.selectable_milestones(no_snap, 123) == [] and ds.prefill_player_bet(no_snap, 1628386, 12) is None)
pre = ds.prefill_player_bet(no_snap, 1628386, 15)
check("Quote ist vorbelegt (gespeichert, mit Stand)", pre["odds"] == 2.18 and pre["odds_source"] == "gespeichert" and pre["odds_ref"] == {"bookmaker": "Betano", "updated_at": "2026-10-22T20:00:00+02:00", "milestone": 15})
check("vorbelegte Quote laesst sich direkt speichern", ds.set_player_bet(*args, 1628386, "Jarrett Allen", "Cleveland Cavaliers", 15, now=NOW, **pre)["bet"]["odds_ref"]["milestone"] == 15)
snapshot = {"game_key": KEY, "created_at": "2026-10-23T00:19:41+02:00", "note": "vor Anpfiff erstellt", "players": [
    {"person_id": 1628386, "ok": True, "p_ge_raw": {"10": 0.8, "15": 0.55}, "p_ge_adjusted": {"10": 0.75, "15": 0.5}},
    {"person_id": 201935, "ok": False}]}
(T / "snaps" / f"{D}.json").write_text(json.dumps({"version": 1, "day": D, "games": {KEY: snapshot}}))
with_snap = ds.player_bet_options(KEY, entries=entries)
a2 = next(p for p in with_snap["players"] if p["person_id"] == 1628386)
h2 = next(p for p in with_snap["players"] if p["person_id"] == 201935)
check("mit Snapshot (aus Datei): Modell-Chancen roh und Teamabgleich je Meilenstein", with_snap["snapshot"] and a2["forecast_ok"] and [(o["model_raw"], o["model_team"]) for o in a2["options"]] == [(0.8, 0.75), (0.55, 0.5)]
      and with_snap["snapshot_note"] == "vor Anpfiff erstellt" and with_snap["snapshot_created_at"].startswith("2026-10-23"))
check("Spieler ohne Prognose im Snapshot: Optionen bleiben, Modell None", not h2["forecast_ok"] and h2["options"][0]["model_raw"] is None)
check("aktuelle Wette je Spieler in der Auswahl (aus der Datei)", a2["current_bet"]["milestone"] == 15 and h2["current_bet"] is None)
check("Spiel ohne Spieler-Quoten: leere Liste; defekter Snapshot: ohne Modell", ds.player_bet_options("2026-10-22|x|A|B", entries={})["players"] == []
      and (T / "snaps" / f"{D}.json").write_text("{kaputt") is not None and ds.player_bet_options(KEY, entries=entries)["snapshot"] is False)

# --- Live-Feed: Spielerliste aus dem Boxscore (kein zusaetzlicher Abruf)
box_game = {"homeTeam": {"teamTricode": "PHI", "players": [
    {"personId": 1, "name": "A", "oncourt": "1", "played": "1", "status": "ACTIVE", "statistics": {"points": 12, "minutes": "PT18M30.00S", "foulsPersonal": 2}},
    {"personId": 2, "name": "B", "oncourt": "0", "played": "1", "status": "ACTIVE", "statistics": {"points": 3, "minutes": "PT08M00.00S", "foulsPersonal": 1}},
    {"personId": 3, "name": "C", "oncourt": "0", "played": "0", "status": "ACTIVE", "statistics": {"points": 0, "minutes": "", "foulsPersonal": 0}},
    {"personId": 4, "name": "D", "oncourt": "0", "played": "0", "status": "INACTIVE", "statistics": {}},
    {"name": "ohne Nummer"}]},
    "awayTeam": {"teamTricode": "CLE", "players": [{"personId": 9, "name": "Z", "oncourt": "1", "played": "1", "statistics": {"points": 7, "minutes": "PT05M15.00S", "foulsPersonal": 0}}]}}
pv = {p.person_id: p for p in lf.players_from_box(box_game)}
check("Boxscore -> Spielerliste: Punkte, Minuten als Zahl, Fouls, Seite, Kuerzel", (pv[1].points, pv[1].minutes, pv[1].fouls, pv[1].side, pv[1].tricode) == (12, 18.5, 2, "home", "PHI") and pv[9].side == "away" and abs(pv[9].minutes - 5.25) < 1e-9)
check("Status: spielt / Bank (gespielt) / Bank (noch nicht eingesetzt) / nicht gespielt (inaktiv); Eintrag ohne personId uebersprungen",
      (pv[1].status, pv[2].status, pv[3].status, pv[4].status) == ("spielt", "bank", "bank", "nicht gespielt") and len(pv) == 5 and pv[2].played and not pv[3].played)
check("GameView hat players und players_complete", {"players", "players_complete"} <= set(lf.GameView.__dataclass_fields__) and lf.GameView.__dataclass_fields__["players"].default == ())

check("echte Dateien (Tracking, Prognose-Snapshots) unveraendert", snap() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
