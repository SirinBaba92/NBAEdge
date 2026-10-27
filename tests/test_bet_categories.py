"""Tests fuer die Wett-Kategorien: data/bet_categories.py (Namen, Voreinstellung), Speichern mit Kategorie (Team- und Spieler-Wetten), Verschieben einzeln und gesammelt, Summen je Kategorie,
Abwaertskompatibilitaet alter Wetten ohne Feld, Wettliste (ui/bet_list.py, AppTest mit Attrappe als Live-Feed). Nur Temp-Ordner, kein Netz, echte Dateien werden nicht veraendert.
Aufruf aus dem Projektordner: venv/bin/python tests/test_bet_categories.py"""
import copy, hashlib, json, os, sys, tempfile, time, warnings
from pathlib import Path
from types import SimpleNamespace
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_SNAPSHOT_DIR=str(T / "snaps"), NBAEDGE_PLAYER_CACHE_DIR=str(T / "cache"),
                  NBAEDGE_ROSTERS=str(T / "rosters.json"), NBAEDGE_LIVE_DIR=str(T / "live"))
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
from data import bet_categories as bc
from data import day_bets_store as ds
from data import live_feed as lf
from data import pre_match_store as ps
from ui import bet_entry as be
from ui import bet_list as bl
from ui import bet_slip as bs
from ui import player_bet_entry as pe

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*"))
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()
TR = T / "tracking"; TR.mkdir(parents=True)

NOW = time.time()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
FUT, PAST = iso(NOW + 5 * 3600), iso(NOW - 2 * 3600)
D = lf.current_us_day(NOW)
K1 = ps.game_key(D, FUT, "Heim Falken", "Gast Baeren")
K2 = ps.game_key(D, PAST, "Zwei Loewen", "Zwei Adler")

# ---------------------------------------------------------------- A) Namen und Voreinstellung
TK = lambda: ds.get_bets(D, FUT, "Heim Falken", "Gast Baeren", include_removed=True)
check("Standardnamen: Bankroll 1/2, Teamabgleich, Roh", bc.names() == {"team_1": "Bankroll 1", "team_2": "Bankroll 2", "player_ta": "Teamabgleich", "player_raw": "Roh"} and not bc.settings_path().exists())
check("Datei liegt im Tracking-Ordner (NBAEDGE_TRACKING_DIR)", bc.settings_path() == TR / "bet_categories.json")
check("Voreinstellung Spieler-Wette: Modus Teamabgleich -> player_ta, roh -> player_raw", bc.default_player_category("team") == "player_ta" and bc.default_player_category("raw") == "player_raw")
check("Voreinstellung Team-Wette: zuerst Bankroll 1", bc.last_team() == ["team_1"])
g = SimpleNamespace(day=D, start_utc=FUT, home="Heim Falken", away="Gast Baeren", home_nick="Falken", away_nick="Baeren", game_id="G1")
r1 = be.save_market_bet(g, "winner", "home", None, "1,85", 10.0, now=NOW, categories=["team_2"])
check("Team-Wette mit Kategorie speichern (Liste)", r1[0] and TK()["winner"]["categories"] == ["team_2"], r1[1])
check("zuletzt benutzte Team-Kategorien werden gemerkt (naechste Voreinstellung)", bc.last_team() == ["team_2"])
bc.set_last_team(["player_ta"])
check("set_last_team ignoriert Spieler-Kategorien", bc.last_team() == ["team_2"])
r2 = be.save_market_bet(g, "total", "over", 231.5, "1,9", None, now=NOW + 1, categories=["player_raw"])
check("Team-Wette mit Spieler-Kategorie wird abgelehnt (nichts gespeichert)", not r2[0] and "total" not in TK(), r2[1])
r2b = be.save_market_bet(g, "total", "over", 231.5, "1,9", None, now=NOW + 1, categories=[])
check("leere Auswahl wird abgelehnt: mindestens eine Kategorie", not r2b[0] and "mindestens eine" in r2b[1] and "total" not in TK(), r2b[1])
r3 = be.save_market_bet(g, "total", "over", 231.5, "1,9", None, now=NOW + 2)
check("ohne Angabe gespeichert -> leere Liste (Ohne Kategorie)", r3[0] and TK()["total"]["categories"] == [])
r4 = be.save_market_bet(g, "winner", "home", None, "1,85", 10.0, now=NOW + 3)
check("Aendern ohne Angabe behaelt die bestehenden Kategorien", TK()["winner"]["categories"] == ["team_2"] and r4[1].startswith("Unverändert"))
r5 = be.save_market_bet(g, "winner", "home", None, "1,85", 10.0, now=NOW + 4, categories=["team_1", "team_2"])
w = TK()["winner"]
check("Mehrfachauswahl: beide Kategorien, Revision mit alter Liste, Einsatz/Quote gleich, weiterhin EINE Wette im Markt", r5[1].startswith("Gespeichert") and w["categories"] == ["team_1", "team_2"]
      and w["revisions"][-1]["categories"] == ["team_2"] and w["stake"] == 10.0 and w["odds"] == 1.85 and len(TK()) == 2)
check("zuletzt benutzt: beide Kategorien", bc.last_team() == ["team_1", "team_2"])
check("einzelne ID als Text wird akzeptiert (zur Liste)", bc.validate("team", "team_1") == ["team_1"] and bc.normalize("player_ta") == ["player_ta"] and bc.normalize(None) == [] and bc.normalize(["team_2", "team_1", "team_1", "x"]) == ["team_1", "team_2"])

# Spieler: Wettschein / Formular / Komponente
opt = lambda n, odds: {"milestone": n, "odds": odds, "bookmaker": "Betano", "bookmaker_percent": 50, "bookmaker_probability": 0.5, "updated_at": "2026-10-26T10:00:00+01:00", "model_raw": None, "model_team": None}
pl = lambda pid, name, opts: {"person_id": pid, "name": name, "team": "Heim Falken", "team_abbreviation": "HEI", "options": opts, "current_bet": None, "forecast_ok": True, "warnings": []}
options = {"players": [pl(1, "Anna Alpha", [opt(15, 1.3), opt(20, 1.85)]), pl(2, "Berta Beta", [opt(10, 1.5)]), pl(3, "Carla Gamma", [opt(20, 2.0)])], "snapshot": True}
PB = lambda: ds.get_player_bets_by_key(K1)
res = bs.save_slip(K1, [{"person_id": 1, "name": "Anna Alpha", "team": "Heim Falken", "milestone": 20, "odds": 1.85, "stake": 10.0}], options, categories=["player_raw"])
check("Wettschein mit Kategorie (Modus roh) speichert player_raw", len(res["saved"]) == 1 and PB()[1]["categories"] == ["player_raw"], str(res["messages"]))
res = bs.save_slip(K1, [{"person_id": 2, "name": "Berta Beta", "team": "Heim Falken", "milestone": 10, "odds": 1.5, "stake": 5.0}], options)
check("Wettschein ohne Angabe: wie bisher (save_fn ohne neues Argument), leere Liste", len(res["saved"]) == 1 and PB()[2]["categories"] == [])
res = bs.save_slip(K1, [{"person_id": 3, "name": "Carla Gamma", "team": "Heim Falken", "milestone": 20, "odds": 2.0, "stake": 5.0, "categories": ["player_ta", "player_raw"]}], options, categories=["player_raw"])
check("Zeile mit eigener Auswahl (beide Spielerkategorien) ueberschreibt die Voreinstellung", PB()[3]["categories"] == ["player_ta", "player_raw"])
seen = []
bs.save_slip(K1, [{"person_id": 3, "name": "Carla Gamma", "team": "x", "milestone": 20, "odds": 2.0, "stake": 5.0}], options, save_fn=lambda *a, **k: (seen.append(k) or (True, "ok")))
check("fremde save_fn ohne Kategorien bekommt kein categories-Argument (Abwaertskompatibilitaet)", seen and "categories" not in seen[0])
done = set()
options2 = {"players": [pl(1, "Anna Alpha", [opt(20, 1.85)]), pl(4, "Dora Delta", [opt(10, 1.4)])], "snapshot": True}
options2["players"][0]["current_bet"] = PB()[1]
act = {"action": "save", "nonce": "n2", "game_key": K1, "items": [{"player": 4, "name": "Dora Delta", "milestone": 10, "quote": 1.4, "stake": 3}]}
pr = bs.process_action(K1, act, options2, done, categories=["player_ta", "player_raw"])
check("Karten-Komponente: Aktion speichert mit den gewaehlten Kategorien (Modus + zusaetzlich die andere)", pr and pr["saved"] == [4] and PB()[4]["categories"] == ["player_ta", "player_raw"], str(pr))
act = {"action": "save", "nonce": "n3", "game_key": K1, "items": [{"player": 4, "name": "Dora Delta", "milestone": 10, "quote": 1.4, "stake": 3}]}
options3 = {"players": [pl(5, "Emil Echo", [opt(10, 1.4)])], "snapshot": True}
act = {"action": "save", "nonce": "n4", "game_key": K1, "items": [{"player": 5, "name": "Emil Echo", "milestone": 10, "quote": 1.4, "stake": 3}]}
pr = bs.process_action(K1, act, options3, done, categories=[])
check("Komponente mit leerer Auswahl: nichts gespeichert, Grund 'mindestens eine'", pr and pr["saved"] == [] and "mindestens eine" in pr["failed"][0]["reason"] and 5 not in PB(), str(pr))
r6 = pe.save_player_bet(K1, options["players"][1], 10, "1,5", 5.0, options, now=NOW + 5, categories=["player_raw"])
check("Formular 'Spieler-Wette eintragen': Kategorien aendern, weiterhin EINE Wette je Spieler", r6[0] and PB()[2]["categories"] == ["player_raw"] and len(PB()) == 4)
r7 = pe.save_player_bet(K1, options["players"][1], 10, "1,5", 5.0, options, now=NOW + 6, categories=["team_1"])
check("Spieler-Wette mit Team-Kategorie abgelehnt", not r7[0] and PB()[2]["categories"] == ["player_raw"], r7[1])
check("Revisionen enthalten die Kategorien", PB()[2]["revisions"][-1]["categories"] == [])

# ---------------------------------------------------------------- B) Umbenennen
snap_ids = lambda: {k: b["categories"] for k, b in ds.get_bets_by_key(K1).items()} | {f"p{k}": b["categories"] for k, b in PB().items()}
before_ids = snap_ids()
names = bc.rename("team_1", "Hauptkonto")
check("Umbenennen: Anzeigename neu, ID gleich, Zuordnung der Wetten unveraendert", names["team_1"] == "Hauptkonto" and bc.label("team_1") == "Hauptkonto" and snap_ids() == before_ids and bc.labels(["team_1", "team_2"]) == "Hauptkonto, Bankroll 2")
saved = json.loads(bc.settings_path().read_text())
check("Einstellungsdatei: nur geaenderte Namen und last_team", saved["names"] == {"team_1": "Hauptkonto"} and saved["last_team"] == ["team_1", "team_2"], str(saved))
for bad, why in (("", "leer"), ("   ", "leer"), ("x" * 31, "zu lang"), ("bankroll 2", "doppelt (ohne Gross/Klein)"), ("Ohne Kategorie", "reserviert")):
    try:
        bc.rename("team_1", bad); okk = False
    except bc.CategoryError:
        okk = True
    check(f"Umbenennen abgelehnt: {why}", okk and bc.names()["team_1"] == "Hauptkonto")
try:
    bc.rename("team_9", "Neu"); okk = False
except bc.CategoryError:
    okk = True
check("unbekannte ID: Fehler (keine neuen Kategorien)", okk and set(bc.names()) == set(bc.ALL_IDS))
sw = bc.rename_many({"team_1": "Bankroll 2", "team_2": "Hauptkonto"})
check("Namen tauschen in einem Schritt moeglich", sw["team_1"] == "Bankroll 2" and sw["team_2"] == "Hauptkonto")
bc.rename_many({"team_1": "Bankroll 1", "team_2": "Bankroll 2"})
check("zurueck auf Standardnamen: Datei enthaelt keine Namen mehr", json.loads(bc.settings_path().read_text())["names"] == {})
bc.settings_path().write_text("{kaputt")
check("kaputte Einstellungsdatei: Standardnamen, kein Absturz", bc.names()["team_1"] == "Bankroll 1" and bc.last_team() == ["team_1"])
bc.settings_path().unlink()

# ---------------------------------------------------------------- C) Abwaertskompatibilitaet, Aendern, Summen
OLD_BET = lambda market, side, line, odds, stake, active=True, **extra: {"market": market, "active": active, "side": side, "line": line, "odds": odds, "stake": stake, "odds_source": "manuell", "line_ref": None,
                                                                         "placed_at": "2026-10-26T10:00:00Z", "updated_at": "2026-10-26T10:00:00Z", "removed_at": None if active else "x", "revisions": [], **extra}
OLD_P = lambda pid, name, ms, odds, stake, **extra: {"market": "player_points", "active": True, "person_id": pid, "name": name, "team": "Zwei Loewen", "milestone": ms, "side": "over", "odds": odds, "stake": stake,
                                                      "odds_source": "manuell", "odds_ref": None, "placed_at": "2026-10-26T10:00:00Z", "updated_at": "2026-10-26T10:00:00Z", "removed_at": None, "revisions": [], **extra}
old = {"version": 2, "format": ds.FORMAT, "updated_at": "x", "games": {
    K1: {"game_date": D, "start_utc": FUT, "home": "Heim Falken", "away": "Gast Baeren", "bets": {"winner": OLD_BET("winner", "home", None, 1.8, 10.0), "total": OLD_BET("total", "over", 231.5, 1.9, 20.0, category="team_1"),
                                                                                              "spread": OLD_BET("spread", "home", -4.5, 1.9, 5.0, active=False)}},
    K2: {"game_date": D, "start_utc": PAST, "home": "Zwei Loewen", "away": "Zwei Adler", "bets": {},
         "player_bets": {"11": OLD_P(11, "Lena Lauf", 12, 1.8, 10.0), "12": OLD_P(12, "Nora Nie", 10, 1.7, 5.0)}}}}
(TR / "day_bets.json").write_text(json.dumps(old))
raw_before = json.loads((TR / "day_bets.json").read_text())
def rows_now():
    return [{"key": K1, "game": None, "bets": ds.get_day_bets(D).get(K1, {"bets": {}})["bets"], "lives": {}, "player_bets": {}, "player_lives": {}},
            {"key": K2, "game": None, "bets": {}, "lives": {}, "player_bets": ds.get_day_player_bets(D).get(K2, {"player_bets": {}})["player_bets"], "player_lives": {}}]
items = bl.collect_items(rows_now())
cats = {(i["kind"], i["id"]): i["categories"] for i in items}
check("alte Wetten: ohne Feld -> leere Liste, frueheres Einzelfeld 'category' -> Liste, entfernte zaehlen nicht", len(items) == 4 and cats[("team", "winner")] == [] and cats[("team", "total")] == ["team_1"]
      and cats[("player", 11)] == [] and all(isinstance(c, list) for c in cats.values()))
check("Lesen aus dem Speicher liefert 'categories' als Liste (kein 'category' mehr in der Kopie)", ds.get_bets_by_key(K1)["total"]["categories"] == ["team_1"] and "category" not in ds.get_bets_by_key(K1)["total"] and ds.get_bets_by_key(K1)["winner"]["categories"] == [])
sm = bl.summary_by_category(items)
check("Summen: Altwetten ohne Feld unter 'Ohne Kategorie', die mit Einzelfeld unter Bankroll 1, 'Alle' = 4", sm["none"]["wetten"] == 3 and sm["team_1"]["wetten"] == 1 and sm["all"]["wetten"] == 4)
check("Tabelle: 'Ohne Kategorie' sichtbar solange es solche Wetten gibt", [r["Kategorie"] for r in bl.summary_rows(sm)] == ["Bankroll 1", "Bankroll 2", "Teamabgleich", "Roh", "Ohne Kategorie", "Alle"])
check("Lesen aendert die Datei nicht (keine Migration)", json.loads((TR / "day_bets.json").read_text()) == raw_before)

strip = lambda b: {k: v for k, v in b.items() if k not in ("category", "categories")}
res = ds.change_categories([{"key": K1, "kind": "team", "id": "winner"}], "add", ["team_2"], now=NOW)
data = json.loads((TR / "day_bets.json").read_text()); wb = data["games"][K1]["bets"]["winner"]
check("hinzufuegen: nur das Feld 'categories' kommt dazu, alles andere identisch (Einsatz, Quote, Status, Zeitstempel, Revisionen)", res["changed"] == 1 and wb["categories"] == ["team_2"] and strip(wb) == raw_before["games"][K1]["bets"]["winner"])
res = ds.change_categories([{"key": K1, "kind": "team", "id": "winner"}], "add", ["team_1"], now=NOW)
data = json.loads((TR / "day_bets.json").read_text())
check("zweite Kategorie hinzufuegen: Wette liegt in beiden, bleibt EINE Wette", data["games"][K1]["bets"]["winner"]["categories"] == ["team_1", "team_2"] and len(data["games"][K1]["bets"]) == 3)
mt = (TR / "day_bets.json").stat().st_mtime_ns
res = ds.change_categories([{"key": K1, "kind": "team", "id": "winner"}], "add", ["team_1"], now=NOW)
check("schon enthalten: 'unchanged', nichts geschrieben", res == {"changed": 0, "unchanged": 1, "skipped": []} and (TR / "day_bets.json").stat().st_mtime_ns == mt)
res = ds.change_categories([{"key": K1, "kind": "team", "id": "winner"}], "remove", ["team_1"], now=NOW)
data = json.loads((TR / "day_bets.json").read_text())
check("entfernen: eine Kategorie weg, die andere bleibt", res["changed"] == 1 and data["games"][K1]["bets"]["winner"]["categories"] == ["team_2"])
res = ds.change_categories([{"key": K1, "kind": "team", "id": "winner"}], "remove", ["team_2"], now=NOW)
data = json.loads((TR / "day_bets.json").read_text())
check("letzte Kategorie entfernen wird verweigert (mindestens eine)", res["changed"] == 0 and len(res["skipped"]) == 1 and "mindestens" in res["skipped"][0][1] and data["games"][K1]["bets"]["winner"]["categories"] == ["team_2"])
res = ds.change_categories([{"key": K1, "kind": "team", "id": "winner"}, {"key": K1, "kind": "team", "id": "total"}], "replace", ["team_1"], now=NOW)
data = json.loads((TR / "day_bets.json").read_text())
check("ersetzen: beide Wetten genau in Bankroll 1; frueheres Einzelfeld 'category' ist durch die Liste ersetzt", data["games"][K1]["bets"]["winner"]["categories"] == ["team_1"] and data["games"][K1]["bets"]["total"]["categories"] == ["team_1"]
      and "category" not in data["games"][K1]["bets"]["total"], str(res))
res = ds.change_categories([{"key": K1, "kind": "player", "id": 11}, {"key": K1, "kind": "team", "id": "spread"}, {"key": K1, "kind": "team", "id": "gibtsnicht"}], "replace", ["team_2"], now=NOW)
check("falsche Wettart, entfernte und unbekannte Wetten werden uebersprungen", res["changed"] == 0 and len(res["skipped"]) == 3)
res = ds.change_categories([{"key": K2, "kind": "player", "id": 11}], "add", ["team_1"], now=NOW)
check("Team-Kategorie fuer Spieler-Wette ist nicht anwendbar (uebersprungen)", res["changed"] == 0 and len(res["skipped"]) == 1)
for bad in (lambda: ds.change_categories([], "add", ["team_9"]), lambda: ds.change_categories([], "kaputt", ["team_1"])):
    try:
        bad(); okk = False
    except ds.BetInputError:
        okk = True
    check("unbekannte Kategorie / Aenderungsart: BetInputError", okk)
# gesammelt (Spiel K2 laeuft schon: Aendern ist nicht an den Anpfiff gebunden)
items2 = bl.collect_items(rows_now())
vis = bl.filter_items(items2, bl.FILTER_NONE)
check("Filter 'Ohne Kategorie': nur die 2 Spieler-Wetten", len(vis) == 2 and all(i["kind"] == "player" for i in vis))
plan = bl.plan_change(items2, "add", ["player_ta"])
check("Vorschau: 'hinzufuegen player_ta' betrifft nur Spieler-Wetten (2), die 2 Team-Wetten sind nicht anwendbar", len(plan["apply"]) == 2 and len(plan["skipped"]) == 2 and plan["same"] == 0)
plan = bl.plan_change(items2, "remove", ["team_1"])
check("Vorschau: 'entfernen team_1' wuerde beide Team-Wetten ohne Kategorie lassen -> uebersprungen, nichts zu tun", len(plan["apply"]) == 0)
ok_, msg = bl.change_items(plan["apply"], "add", ["player_ta"])
ok_, msg = bl.change_items(vis, "add", ["player_ta"])
data = json.loads((TR / "day_bets.json").read_text())
check("gesammelt hinzufuegen: 2 Spieler-Wetten in Teamabgleich, Meldung nennt Anzahl, Rest unveraendert", ok_ and msg.startswith("2 Wette(n) geändert") and all(data["games"][K2]["player_bets"][p]["categories"] == ["player_ta"] for p in ("11", "12"))
      and data["games"][K1]["bets"]["winner"]["categories"] == ["team_1"], msg)
check("Spieler-Wetten: Einsatz/Quote/Meilenstein/Status unveraendert", all(strip(data["games"][K2]["player_bets"][p]) == raw_before["games"][K2]["player_bets"][p] for p in ("11", "12")))
ok_, msg = bl.change_items([i for i in bl.collect_items(rows_now()) if i["id"] == 11], "add", ["player_raw"])
items3 = bl.collect_items(rows_now())
check("Lena liegt in zwei Kategorien, Zahl der Wetten bleibt 4", next(i for i in items3 if i["id"] == 11)["categories"] == ["player_ta", "player_raw"] and len(items3) == 4)
sm = bl.summary_by_category(items3)
check("Eine Wette in zwei Kategorien: beide Kategorie-Summen steigen, 'Alle' zaehlt sie einmal", sm["player_ta"]["wetten"] == 2 and sm["player_raw"]["wetten"] == 1 and sm["all"]["wetten"] == 4
      and sm["player_ta"]["einsatz"] == 15.0 and sm["player_raw"]["einsatz"] == 10.0 and sm["all"]["einsatz"] == 45.0 and sum(sm[c]["wetten"] for c in (*bc.ALL_IDS, "none")) == 5 > sm["all"]["wetten"])
ok_, msg = bl.change_items([], "add", ["team_1"])
check("nichts zu aendern: freundliche Meldung; leere Auswahl: Fehler", ok_ and "Keine Wetten" in msg and not bl.change_items(items3, "add", [])[0])

def BL(market, stake, odds, state, profit, decided, won): return ds.BetLive(market, "home", None, odds, stake, state, "gruen", state, None, decided, won, profit, 0, 0, state != "offen")
its = [{"kind": "team", "key": K1, "id": "winner", "bet": {"stake": 10.0, "side": "home", "odds": 1.8}, "live": BL("winner", 10.0, 1.8, "gewonnen", 8.0, True, True), "categories": ["team_1", "team_2"]},
       {"kind": "team", "key": K1, "id": "total", "bet": {"stake": 20.0}, "live": BL("total", 20.0, 1.9, "verloren", -20.0, True, False), "categories": ["team_1"]},
       {"kind": "team", "key": K1, "id": "spread", "bet": {"stake": 5.0}, "live": BL("spread", 5.0, 1.9, "offen", None, False, None), "categories": ["team_2"]},
       {"kind": "team", "key": K1, "id": "team_total_home", "bet": {"stake": 7.0}, "live": None, "categories": []}]
sm = bl.summary_by_category(its)
check("Summen je Kategorie: Bankroll 1 = 2 Wetten (1 gewonnen, 1 verloren, Einsatz 30, G/V -12)", (sm["team_1"]["wetten"], sm["team_1"]["gewonnen"], sm["team_1"]["verloren"], sm["team_1"]["offen"], sm["team_1"]["einsatz"], sm["team_1"]["gewinn_verlust"]) == (2, 1, 1, 0, 30.0, -12.0), str(sm["team_1"]))
check("Bankroll 2 = 2 Wetten (1 gewonnen, 1 offen, Einsatz 15, G/V +8); Ohne Kategorie = 1 Wette ohne Status, Einsatz 7", (sm["team_2"]["wetten"], sm["team_2"]["gewonnen"], sm["team_2"]["offen"], sm["team_2"]["einsatz"], sm["team_2"]["gewinn_verlust"]) == (2, 1, 1, 15.0, 8.0)
      and (sm["none"]["wetten"], sm["none"]["ohne_status"], sm["none"]["einsatz"]) == (1, 1, 7.0))
check("'Alle': jede Wette einmal (4 Wetten, Einsatz 42, G/V -12), Kategorie-Summen ergeben zusammen mehr (5 > 4)", sm["all"]["wetten"] == 4 and sm["all"]["einsatz"] == 42.0 and sm["all"]["gewinn_verlust"] == -12.0
      and sm["all"]["gewonnen"] == 1 and sm["all"]["verloren"] == 1 and sm["all"]["offen"] == 1 and sum(sm[c]["wetten"] for c in (*bc.ALL_IDS, "none")) == 5)
tab = bl.summary_rows(sm)
check("Tabelle: Spalten und Formatierung", list(tab[0]) == ["Kategorie", "Wetten", "Offen", "Gewonnen", "Verloren", "Nicht gespielt", "Einsatz", "Gewinn/Verlust"] and tab[0]["Gewinn/Verlust"] in ("−12,00", "-12,00"), str(tab[0]))
txt = bl.item_text(its[0])
check("Listentext: Spiel, Markt, Seite, Quote/Einsatz, Status", "Gast Baeren @ Heim Falken" in txt and "Sieger Heim Falken" in txt and "Quote 1,80" in txt and "Einsatz 10,00" in txt and "gewonnen" in txt.lower(), txt)

# ---------------------------------------------------------------- D) Wettliste in der App (AppTest, Attrappe als Live-Feed)
class R:
    def __init__(self, payload): self.status_code, self._p, self.text = 200, payload, ""
    def json(self): return self._p
class Stub:
    def __init__(self): self.rows, self.boxes = [], {}
    def get(self, url, headers=None, params=None, timeout=None):
        if "scoreboard" in url:
            return R({"scoreboard": {"gameDate": D, "games": self.rows}})
        return R({"game": self.boxes.get(url.rsplit("_", 1)[1].split(".")[0], {})})
def srow(gid, home, away, status, period, clock, hs, as_, start):
    t = lambda nick, sc: {"teamCity": nick.split()[0], "teamName": nick.split()[1], "teamTricode": nick[:3].upper(), "score": sc, "periods": []}
    return {"gameId": gid, "gameStatus": status, "gameStatusText": "", "period": period, "gameClock": clock, "gameEt": f"{D}T19:00:00-04:00", "gameTimeUTC": start, "homeTeam": t(home, hs), "awayTeam": t(away, as_)}
stub = Stub()
stub.rows = [srow("A1", "Heim Falken", "Gast Baeren", 1, 0, "", 0, 0, FUT), srow("A2", "Zwei Loewen", "Zwei Adler", 1, 0, "", 0, 0, PAST)]
lf._feed = lf.LiveFeed(http_get=stub.get)
(TR / "day_bets.json").write_text(json.dumps(old))                 # frischer Stand: 3 Wetten ohne Feld, 1 mit frueherem Einzelfeld
if bc.settings_path().exists(): bc.settings_path().unlink()
HARNESS = str(ROOT / "tests" / "_harness_bet_list.py")
at = AppTest.from_file(HARNESS, default_timeout=60).run()
def data_now(): return json.loads((TR / "day_bets.json").read_text())
def mss(at, prefix): return [m for m in at.multiselect if m.key and m.key.startswith(prefix)]
check("Wettliste: keine Exception/Warnung, 4 Wetten, Filter 'Alle' vorgewaehlt", not at.exception and not problems(at) and at.selectbox(key="bl_filter").value == "all" and any("4 Wette(n)" in e.label for e in at.expander), " | ".join(problems(at))[:200])
check("Wettliste: Tabelle mit Zeile 'Ohne Kategorie' und Hinweis 'zaehlen mehrfach'", any("Ohne Kategorie" in str(t.value) for t in at.table) and any("zählen mehrfach" in c.value for c in at.caption))
at.selectbox(key="bl_filter").set_value("none").run()
check("Filter 'Ohne Kategorie' zeigt die 3 Wetten ohne Feld", not at.exception and len(mss(at, "bl_cat_")) == 3, str(len(mss(at, "bl_cat_"))))
tm = [m for m in mss(at, "bl_cat_team_") if m.key.endswith("_winner_none")][0]
check("Team-Wette: Mehrfachauswahl nur mit Team-Kategorien, vorerst leer", tm.options == ["Bankroll 1", "Bankroll 2"] and tm.value == [])
tm.set_value(["team_1", "team_2"]).run()
d = data_now()
check("einzeln aendern (zwei Kategorien): nur 'categories' kommt dazu, Einsatz/Quote unveraendert, weiter 3 Team-Wetten", not at.exception and d["games"][K1]["bets"]["winner"]["categories"] == ["team_1", "team_2"]
      and strip(d["games"][K1]["bets"]["winner"]) == strip(old["games"][K1]["bets"]["winner"]) and len(d["games"][K1]["bets"]) == 3)
check("Erfolgsmeldung nennt die Anzahl", any("1 Wette(n) geändert" in s_.value for s_ in at.success), " | ".join(s_.value for s_ in at.success))
at.selectbox(key="bl_filter").set_value("team_1").run()
check("Filter 'Bankroll 1': Sieger-Wette (beide Kategorien) und Total (frueheres Einzelfeld) = 2 Wetten; Tabelle zaehlt Sieger in beiden Kategorien",
      len(mss(at, "bl_cat_")) == 2 and any("Bankroll 2" in str(t.value) for t in at.table))
at.selectbox(key="bl_filter").set_value("none").run()
pm = mss(at, "bl_cat_player_")
check("Spieler-Wetten: Auswahl nur Spieler-Kategorien", len(pm) == 2 and pm[0].options == ["Teamabgleich", "Roh"], str([m.options for m in pm]))
# gesammelt: Hinzufuegen player_ta fuer die sichtbaren (2 Spieler-Wetten)
at.selectbox(key="bl_bulk_mode").set_value("add")
at.multiselect(key="bl_bulk_cats").set_value(["player_ta"]).run()
at.button(key="bl_bulk_ask").click().run()
warn = " ".join(w.value for w in at.warning)
check("gesammelt: Bestaetigung mit Anzahl (2 Wetten) und Hinweis, noch NICHTS geaendert", "Kategorien hinzufügen: Teamabgleich – 2 Wette(n) werden geändert" in warn and "categories" not in data_now()["games"][K2]["player_bets"]["11"])
at.button(key="bl_no").click().run()
check("Abbrechen: nichts geaendert, Bestaetigung weg", "categories" not in data_now()["games"][K2]["player_bets"]["11"] and not at.warning)
at.selectbox(key="bl_bulk_mode").set_value("add")
at.multiselect(key="bl_bulk_cats").set_value(["player_ta"]).run()
at.button(key="bl_bulk_ask").click().run()
at.button(key="bl_yes").click().run()
d = data_now()
check("Bestaetigen: beide Spieler-Wetten in Teamabgleich, Zahl der Wetten gleich, Meldung", d["games"][K2]["player_bets"]["11"]["categories"] == ["player_ta"] and d["games"][K2]["player_bets"]["12"]["categories"] == ["player_ta"]
      and len(d["games"][K2]["player_bets"]) == 2 and any("2 Wette(n) geändert" in s_.value for s_ in at.success))
at.selectbox(key="bl_filter").set_value("player_ta").run()
pm = mss(at, "bl_cat_player_")
pm[0].set_value([]).run()
check("leere Auswahl einer Wette: Fehlermeldung, nichts geaendert", any("mindestens eine" in e.value for e in at.error) and data_now()["games"][K2]["player_bets"]["11"]["categories"] == ["player_ta"])
at.selectbox(key="bl_bulk_mode").set_value("add")
at.multiselect(key="bl_bulk_cats").set_value(["player_raw"]).run()
at.button(key="bl_bulk_ask").click().run(); at.button(key="bl_yes").click().run()
at.selectbox(key="bl_filter").set_value("all").run()
txt_tab = str([t.value for t in at.table])
d = data_now()
check("zusaetzlich 'Roh' fuer dieselben Wetten: beide Spielerkategorien je 2 Wetten, 'Alle' bleibt bei 4", d["games"][K2]["player_bets"]["11"]["categories"] == ["player_ta", "player_raw"] and "Alle" in txt_tab and not at.exception)
# ersetzen / entfernen gesammelt
at.selectbox(key="bl_filter").set_value("player_raw").run()
at.selectbox(key="bl_bulk_mode").set_value("remove")
at.multiselect(key="bl_bulk_cats").set_value(["player_raw"]).run()
at.button(key="bl_bulk_ask").click().run(); at.button(key="bl_yes").click().run()
d = data_now()
check("gesammelt entfernen: 'Roh' weg, 'Teamabgleich' bleibt", d["games"][K2]["player_bets"]["11"]["categories"] == ["player_ta"])
at.selectbox(key="bl_filter").set_value("player_ta").run()
at.selectbox(key="bl_bulk_mode").set_value("remove")
at.multiselect(key="bl_bulk_cats").set_value(["player_ta"]).run()
at.button(key="bl_bulk_ask").click().run()
warn = " ".join(w.value for w in at.warning)
check("letzte Kategorie gesammelt entfernen: Vorschau zeigt 0 Wetten (mindestens eine bleibt), Knopf gesperrt", "0 Wette(n) werden geändert" in warn and at.button(key="bl_yes").disabled)
at.button(key="bl_no").click().run()
at.selectbox(key="bl_bulk_mode").set_value("replace")
at.multiselect(key="bl_bulk_cats").set_value(["player_raw"]).run()
at.button(key="bl_bulk_ask").click().run(); at.button(key="bl_yes").click().run()
d = data_now()
check("gesammelt ersetzen: beide Spieler-Wetten nur noch in 'Roh'", d["games"][K2]["player_bets"]["11"]["categories"] == ["player_raw"] and d["games"][K2]["player_bets"]["12"]["categories"] == ["player_raw"])
# Umbenennen
at.selectbox(key="bl_filter").set_value("all").run()
at.toggle(key="bl_rename_on").set_value(True).run()
ti = [t for t in at.text_input if t.key and t.key.startswith("bl_name_team_1")][0]
ti.set_value("Hauptkonto")
at.button(key="bl_rename").click().run()
check("Umbenennen in der Oberflaeche: neuer Name in der Tabelle, Wetten behalten ihre IDs", bc.names()["team_1"] == "Hauptkonto" and data_now()["games"][K1]["bets"]["winner"]["categories"] == ["team_1", "team_2"]
      and any("Hauptkonto" in str(t.value) for t in at.table), str(bc.names()))
ti = [t for t in at.text_input if t.key and t.key.startswith("bl_name_team_2")][0]
ti.set_value("hauptkonto")
at.button(key="bl_rename").click().run()
check("doppelter Name wird mit Meldung abgelehnt", bc.names()["team_2"] == "Bankroll 2" and any("verschieden" in e.value for e in at.error), " | ".join(e.value for e in at.error))
(TR / "day_bets.json").write_text("{kaputt")
at2 = AppTest.from_file(HARNESS, default_timeout=60).run()
check("beschaedigte Wett-Datei: Fehlermeldung, kein Absturz, Datei unveraendert", not at2.exception and (TR / "day_bets.json").read_text() == "{kaputt" and any("nicht lesbar" in e.value for e in at2.error))
check("in keinem AppTest-Lauf: Streamlit-Exception/Session-State-Warnung", not [b for b in page_checks.bad if "Exception" in b or "Session" in b], "; ".join(page_checks.bad[:2]))

check("echte Tracking-Dateien und Snapshots unveraendert", real_files() == real_before)
print("\nERGEBNIS:", "ALLES BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
