"""Tests fuer data/day_bets_store.py (Baustein 3, Wett-Speicher): Setzen/Aendern/Entfernen, Revisionen, eine Wette je Markt, Sperre ab Anpfiff, .5-Linien,
beschaedigte Datei, gleichzeitige Schreibzugriffe, Auswahl-Logik und Anbindung an das Live-Modell. Nur Temp-Ordner (NBAEDGE_TRACKING_DIR), nie das echte day_bets.json; kein Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_day_bets_store.py"""
import hashlib, json, os, subprocess, sys, tempfile, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))

REAL_DIR = ROOT / "data" / "tracking"
real_file = REAL_DIR / "day_bets.json"
real_before = real_file.read_bytes() if real_file.exists() else None
real_lock = REAL_DIR / "day_bets.json.lock"; real_lock_before = real_lock.exists()      # die echte App legt sie im Betrieb selbst an
TMP = tempfile.TemporaryDirectory()
os.environ["NBAEDGE_TRACKING_DIR"] = TMP.name
from data import day_bets_store as ds
from data import pre_match_store as ps
from engine import bet_status as bs
from engine import game_clock as gc
from engine import live_model as lm

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
    except Exception as e:
        return False
    return False

NOW = 1_792_800_000.0                                               # fester Zeitpunkt
H = 3600
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
START = iso(NOW + 6 * H)
D, HOME, AWAY = "2026-10-22", "Philadelphia 76ers", "Cleveland Cavaliers"
G = (D, START, HOME, AWAY)
path = ds.store_path()
def reset():
    for p in list(Path(TMP.name).rglob("*")):
        if p.is_file():
            p.unlink()
def raw(): return json.loads(path.read_text())
sha = lambda p: hashlib.sha1(Path(p).read_bytes()).hexdigest()

# ----------------------------------------------------------------- Format, Pfad, Setzen
check("Speicherort liegt im Temp-Ordner (NBAEDGE_TRACKING_DIR), Dateiname day_bets.json", path == Path(TMP.name) / "day_bets.json" and ds.store_path().name == "day_bets.json")
check("leer: keine Wetten, kein Fehler, Datei wird beim Lesen nicht angelegt", ds.get_bets(*G) == {} and ds.get_day_bets(D) == {} and ds.load_error() is None and not path.exists())
r = ds.set_bet(*G, "winner", side="home", odds="1,85", stake="20", now=NOW)
d = raw(); key = ps.game_key(D, START, HOME, AWAY)
check("Format nbaedge-day-bets Version 1, Schluessel wie pre_match_store.game_key", d["format"] == "nbaedge-day-bets" and d["version"] == 1 and list(d["games"]) == [key] and r["key"] == key and key.count("|") == 3, key)
b = d["games"][key]["bets"]["winner"]
check("Wette: alle Felder (active, side, line, odds, stake, odds_source, line_ref, categories, placed_at, updated_at, removed_at, revisions)",
      set(b) == {"market", "active", "side", "line", "odds", "stake", "odds_source", "line_ref", "categories", "placed_at", "updated_at", "removed_at", "revisions"} and b["categories"] == [] and b["active"] is True and b["side"] == "home"
      and b["line"] is None and b["odds"] == 1.85 and b["stake"] == 20.0 and b["odds_source"] == "manuell" and b["removed_at"] is None and b["revisions"] == [] and b["placed_at"] == b["updated_at"])
check("Spielkopf gespeichert (Datum, Anpfiff UTC, Heim, Gast)", {k: d["games"][key][k] for k in ("game_date", "start_utc", "home", "away")} == {"game_date": D, "start_utc": START, "home": HOME, "away": AWAY})
check("Zeitstempel mit UTC-Versatz (wie pre_match_store)", b["placed_at"].endswith(("+00:00", "Z")) or b["placed_at"][-6] in "+-", b["placed_at"])
check("atomar: kein Temp-Rest im Ordner; Tageskopie in history/", not [p for p in Path(TMP.name).rglob("*.tmp")] and any(Path(TMP.name, "history").glob("day_bets_*.json")))
check("Rueckgabe: status saved, bet", r["status"] == "saved" and r["bet"]["side"] == "home")

# ----------------------------------------------------------------- alle Maerkte, eine Wette je Markt
ds.set_bet(*G, "spread", side="home", line=-4.5, now=NOW)
ds.set_bet(*G, "total", line="231,5", odds=1.9, now=NOW)
ds.set_bet(*G, "team_total_home", line=118.5, stake=10, now=NOW)
ds.set_bet(*G, "team_total_away", side="over", line=113.5, now=NOW)
bets = ds.get_bets(*G)
check("fuenf Maerkte gleichzeitig moeglich (Total und Team Totals Heim/Gast nebeneinander)", set(bets) == set(ds.MARKETS) and bets["total"]["line"] == 231.5 and bets["team_total_home"]["line"] == 118.5 and bets["team_total_away"]["line"] == 113.5)
check("Total/Team Total ohne Seitenangabe = Over (Standard), Spread mit Linie aus Sicht der gewaehlten Mannschaft", bets["total"]["side"] == "over" and bets["spread"]["side"] == "home" and bets["spread"]["line"] == -4.5)
check("Quote und Einsatz sind optional: Wette ohne beides zaehlt (Spread ohne Quote/Einsatz)", bets["spread"]["odds"] is None and bets["spread"]["stake"] is None and bets["spread"]["odds_source"] is None and bets["spread"]["active"])
n_before = len(raw()["games"][key]["bets"])
ds.set_bet(*G, "total", line=232.5, odds=1.95, now=NOW + 10)
d = raw(); tb = d["games"][key]["bets"]["total"]
check("zweite Wette im selben Markt ersetzt die erste (hoechstens eine je Markt), Anzahl bleibt 5", len(d["games"][key]["bets"]) == n_before == 5 and tb["line"] == 232.5 and tb["odds"] == 1.95)
check("Revision: alter Stand (Linie 231,5, Quote 1,9) bleibt erhalten", len(tb["revisions"]) == 1 and tb["revisions"][0]["line"] == 231.5 and tb["revisions"][0]["odds"] == 1.9 and tb["revisions"][0]["reason"] == "geaendert" and "replaced_at" in tb["revisions"][0])
check("placed_at bleibt (dieselbe Wette), updated_at neuer", tb["placed_at"] == bets["total"]["placed_at"] and tb["updated_at"] != tb["placed_at"])
ds.set_bet(*G, "total", line=232.5, odds=1.95, stake=15, now=NOW + 20)
ds.set_bet(*G, "total", line=232.5, odds=2.05, stake=15, now=NOW + 30)
tb = ds.get_bets(*G)["total"]
check("mehrere Aenderungen: Revisionen in zeitlicher Reihenfolge, nichts geht verloren", [x["line"] for x in tb["revisions"]] == [231.5, 232.5, 232.5] and [x["stake"] for x in tb["revisions"]] == [None, None, 15.0] and tb["odds"] == 2.05 and tb["stake"] == 15.0)
b0 = path.read_bytes()
r = ds.set_bet(*G, "total", line=232.5, odds=2.05, stake=15, now=NOW + 99)
check("identische Eingabe: status unchanged, Datei bytegleich, keine neue Revision", r["status"] == "unchanged" and path.read_bytes() == b0)
other = ds.set_bet("2026-10-22", iso(NOW + 8 * H), "Oklahoma City Thunder", "Denver Nuggets", "winner", side="away", now=NOW)
check("anderes Spiel: eigener Eintrag, die ersten Wetten bleiben", len(raw()["games"]) == 2 and ds.get_bets(*G)["winner"]["side"] == "home" and other["bet"]["side"] == "away")

# ----------------------------------------------------------------- Entfernen
r = ds.remove_bet(*G, "spread", now=NOW + 40)
sp = ds.get_bets(*G, include_removed=True)["spread"]
check("Entfernen: active false, removed_at gesetzt, Wette bleibt in der Datei", r["status"] == "removed" and sp["active"] is False and sp["removed_at"] and "spread" in raw()["games"][key]["bets"])
check("Entfernen: letzter aktiver Stand steht in revisions (reason entfernt)", len(sp["revisions"]) == 1 and sp["revisions"][0]["reason"] == "entfernt" and sp["revisions"][0]["active"] is True and sp["revisions"][0]["line"] == -4.5)
check("Standardlesen blendet entfernte aus, include_removed zeigt sie", "spread" not in ds.get_bets(*G) and "spread" in ds.get_bets(*G, include_removed=True) and len(ds.get_bets(*G)) == 4)
b0 = path.read_bytes()
check("erneutes Entfernen ohne aktive Wette: status none, nichts geschrieben; unbekannte Wette ebenso", ds.remove_bet(*G, "spread", now=NOW + 50)["status"] == "none" and ds.remove_bet(*G, "winner", now=NOW + 60)["status"] == "removed"
      and ds.remove_bet(D, iso(NOW + 12 * H), "A", "B", "winner", now=NOW)["status"] == "none")
ds.set_bet(*G, "spread", side="away", line=4.5, odds=1.8, now=NOW + 70)
sp = ds.get_bets(*G)["spread"]
check("nach Entfernen neu gesetzt: aktiv, neue placed_at, Geschichte (Entfernung) bleibt", sp["active"] and sp["removed_at"] is None and sp["side"] == "away" and sp["line"] == 4.5 and sp["placed_at"] != ds.get_bets(*G, include_removed=True)["total"]["placed_at"]
      and len(sp["revisions"]) == 1 and sp["revisions"][0]["reason"] == "entfernt")

# ----------------------------------------------------------------- Sperre ab Anpfiff
reset()
b0 = None
ds.set_bet(*G, "winner", side="home", now=NOW)
b0 = path.read_bytes()
msg = raises(ds.GameStartedError, ds.set_bet, *G, "winner", side="away", now=NOW + 6 * H)
check("genau zum Anpfiff gesperrt (Setzen/Aendern), klare Meldung", isinstance(msg, str) and "begonnen" in msg and path.read_bytes() == b0, str(msg))
check("nach dem Anpfiff gesperrt (Entfernen)", isinstance(raises(ds.GameStartedError, ds.remove_bet, *G, "winner", now=NOW + 7 * H), str) and path.read_bytes() == b0)
check("eine Sekunde vor dem Anpfiff noch moeglich", ds.set_bet(*G, "winner", side="away", now=NOW + 6 * H - 1)["status"] == "saved" and ds.get_bets(*G)["winner"]["side"] == "away")
check("Lesen bleibt nach dem Anpfiff moeglich", ds.get_bets(*G)["winner"]["side"] == "away" and ds.is_bet_editable(START, NOW) and not ds.is_bet_editable(START, NOW + 6 * H) and not ds.is_bet_editable(START, NOW + 6 * H + 1))
check("unbekannter Anpfiff gilt als begonnen (None, leer, Muell)", all(isinstance(raises(ds.GameStartedError, ds.set_bet, D, s, HOME, AWAY, "winner", side="home", now=NOW), str) for s in (None, "", "kein Datum"))
      and not ds.is_bet_editable(None, NOW) and ds.get_bets(D, None, HOME, AWAY) == {})
check("Spiel in der Vergangenheit: neues Spiel kann nicht mehr angelegt werden (nichts geschrieben)", isinstance(raises(ds.GameStartedError, ds.set_bet, D, iso(NOW - H), "X", "Y", "winner", side="home", now=NOW), str) and len(raw()["games"]) == 1)

# ----------------------------------------------------------------- .5-Linien und Eingaben
reset()
bad_lines = [231.0, 231, 232.0, "231", "231,0", 0, 0.0, "abc", "", None, float("nan"), True]
check("ganzzahlige und ungueltige Linien werden abgelehnt (Total)", all(isinstance(raises(ds.BetInputError, ds.set_bet, *G, "total", line=x, now=NOW), str) for x in bad_lines) and not path.exists())
check("Meldung nennt .5-Linien", "nur .5-Linien" in raises(ds.BetInputError, ds.set_bet, *G, "total", line=231.0, now=NOW))
check(".5-Linien werden akzeptiert (Zahl, Text mit Komma/Punkt)", all(ds.set_bet(*G, "total", line=x, now=NOW + i)["bet"]["line"] == 231.5 for i, x in enumerate((231.5, "231,5", "231.5", " 231,5 "))))
check("Spread: ganzzahlig/0 abgelehnt, negative und positive .5 ok, Gast +4,5", all(isinstance(raises(ds.BetInputError, ds.set_bet, *G, "spread", side="home", line=x, now=NOW), str) for x in (-4.0, 0.0, 4)) and ds.set_bet(*G, "spread", side="home", line=-4.5, now=NOW)["bet"]["line"] == -4.5
      and ds.set_bet(*G, "spread", side="away", line="+4,5", now=NOW + 1)["bet"]["line"] == 4.5 and ds.set_bet(*G, "spread", side="home", line="−4,5", now=NOW + 2)["bet"]["line"] == -4.5)
check("Bereiche: Total 100 bis 400, Team Total 40 bis 200, Spread bis 60", all(isinstance(raises(ds.BetInputError, ds.set_bet, *G, m, line=x, now=NOW), str) for m, x in (("total", 99.5), ("total", 400.5), ("team_total_home", 39.5), ("team_total_away", 200.5), ("spread", 60.5)))
      and ds.set_bet(*G, "total", line=100.5, now=NOW)["status"] == "saved" and ds.set_bet(*G, "spread", side="home", line=-59.5, now=NOW)["status"] == "saved")
check("Seiten: Sieger/Spread nur home/away, Total/Team Total over ODER under (home/away dort abgelehnt), Sieger ohne Linie, Sieger/Spread ohne Seite abgelehnt", isinstance(raises(ds.BetInputError, ds.set_bet, *G, "winner", side="over", now=NOW), str)
      and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "winner", side=None, now=NOW), str) and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "spread", side=None, line=-4.5, now=NOW), str)
      and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "total", side="home", line=231.5, now=NOW), str) and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "team_total_home", side="away", line=118.5, now=NOW), str)
      and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "spread", side="over", line=-4.5, now=NOW), str) and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "winner", side="home", line=1.5, now=NOW), str)
      and ds.set_bet(*G, "winner", side="home", line="", now=NOW)["bet"]["line"] is None)
check("Under und Over bei Total und Team Total waehlbar (je Markt weiter nur eine Wette: Under ersetzt Over mit Revision)", ds.set_bet(*G, "total", side="over", line=231.5, now=NOW + 40)["bet"]["side"] == "over"
      and ds.set_bet(*G, "total", side="under", line=231.5, now=NOW + 41)["bet"]["side"] == "under" and ds.get_bets(*G)["total"]["revisions"][-1]["side"] == "over"
      and ds.set_bet(*G, "team_total_home", side="under", line=118.5, now=NOW + 42)["bet"]["side"] == "under" and ds.set_bet(*G, "team_total_away", side="over", line=113.5, now=NOW + 43)["bet"]["side"] == "over")
check("Sieger und Spread weiter fuer home UND away waehlbar", ds.set_bet(*G, "winner", side="away", now=NOW + 44)["bet"]["side"] == "away" and ds.set_bet(*G, "spread", side="away", line=4.5, now=NOW + 45)["bet"]["side"] == "away"
      and ds.SIDES == {"winner": ("home", "away"), "spread": ("home", "away"), "total": ("over", "under"), "team_total_home": ("over", "under"), "team_total_away": ("over", "under")})
check("unbekannter Markt abgelehnt", isinstance(raises(ds.BetInputError, ds.set_bet, *G, "player_points", side="home", now=NOW), str) and isinstance(raises(ds.BetInputError, ds.remove_bet, *G, "xyz", now=NOW), str))
check("Quote: 1,85 / 1.85 / 2 ok; <= 1, 1000+, Text abgelehnt; leer = keine Quote", [ds.set_bet(*G, "winner", side="home", odds=o, now=NOW + i)["bet"]["odds"] for i, o in enumerate(("1,85", "1.85", 2))] == [1.85, 1.85, 2.0]
      and all(isinstance(raises(ds.BetInputError, ds.set_bet, *G, "winner", side="home", odds=o, now=NOW), str) for o in (1.0, 0.5, "1000,5", "abc", "1,2,3"))
      and ds.set_bet(*G, "winner", side="home", odds="", now=NOW + 9)["bet"]["odds"] is None)
check("Einsatz: 20 / 12,50 / '12.5' ok (2 Stellen); 0, negativ, Text, riesig abgelehnt; leer = kein Einsatz", [ds.parse_stake_input(x) for x in ("20", "12,50", "12.5", 7, 0.125, " 3 ")] == [20.0, 12.5, 12.5, 7.0, 0.12, 3.0]
      and all(isinstance(raises(ds.BetInputError, ds.parse_stake_input, x), str) for x in (0, -5, "abc", "1,2,3", 10 ** 7, True)) and ds.parse_stake_input("") is None and ds.parse_stake_input(None) is None)
check("Quelle der Quote: 'gespeichert' ok, anderes abgelehnt, ohne Quote keine Quelle, Quote ohne Quelle = manuell", ds.set_bet(*G, "total", line=231.5, odds=1.9, odds_source="gespeichert", now=NOW + 20)["bet"]["odds_source"] == "gespeichert"
      and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "total", line=231.5, odds=1.9, odds_source="telefon", now=NOW), str) and ds.set_bet(*G, "total", line=231.5, odds_source="gespeichert", now=NOW + 21)["bet"]["odds_source"] is None
      and ds.set_bet(*G, "total", line=231.5, odds=1.9, now=NOW + 22)["bet"]["odds_source"] == "manuell")
ref = ds.make_line_ref(231.5, 232.5, source="Cache", at="2026-10-22T10:00:00+02:00", bookmaker="Betano")
check("line_ref: Hauptlinie zum Zeitpunkt der Wette, gewaehlte Linie, is_main", ref == {"main_line": 231.5, "chosen_line": 232.5, "is_main": False, "source": "Cache", "bookmaker": "Betano", "at": "2026-10-22T10:00:00+02:00"} and ds.make_line_ref(231.5, 231.5)["is_main"] is True and ds.make_line_ref(None, 231.5)["is_main"] is False)
ds.set_bet(*G, "total", line=232.5, line_ref=ref, now=NOW + 30)
check("line_ref wird gespeichert (Kopie); ungueltig (kein Dict, nicht speicherbar) abgelehnt", ds.get_bets(*G)["total"]["line_ref"] == ref and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "total", line=232.5, line_ref="x", now=NOW), str)
      and isinstance(raises(ds.BetInputError, ds.set_bet, *G, "total", line=232.5, line_ref={"x": object()}, now=NOW), str))
b0 = path.read_bytes()
raises(ds.BetInputError, ds.set_bet, *G, "total", line=231.0, now=NOW)
check("ungueltige Eingabe schreibt nichts", path.read_bytes() == b0)
check("Spieldaten pruefen: leeres Heim, falsches Datum abgelehnt", isinstance(raises(ds.BetInputError, ds.set_bet, D, START, "", AWAY, "winner", side="home", now=NOW), str) and isinstance(raises(ds.BetInputError, ds.set_bet, "22.10.2026", START, HOME, AWAY, "winner", side="home", now=NOW), str))

# ----------------------------------------------------------------- beschaedigte Datei
reset()
ds.set_bet(*G, "winner", side="home", now=NOW)
good = path.read_bytes()
path.write_text('{"format": "nbaedge-day-bets", "games": {"x": ')            # abgeschnitten
bad = path.read_bytes()
check("beschaedigt: Lesen liefert leer + Fehlermeldung, Datei unveraendert", ds.get_bets(*G) == {} and ds.get_day_bets(D) == {} and "beschädigt" in ds.load_error() and path.read_bytes() == bad)
msg = raises(ds.DayBetsError, ds.set_bet, *G, "total", line=231.5, now=NOW)
backups = sorted(Path(TMP.name).glob("day_bets.corrupt-*.json"))
check("beschaedigt: Setzen wirft DayBetsError mit Hinweis auf die Sicherungskopie, Originaldatei NICHT ueberschrieben", isinstance(msg, str) and "Sicherungskopie" in msg and path.read_bytes() == bad and len(backups) == 1 and backups[0].name in msg, str(msg))
check("Sicherungskopie ist bytegleich zur beschaedigten Datei", backups[0].read_bytes() == bad)
raises(ds.DayBetsError, ds.remove_bet, *G, "winner", now=NOW)
check("weitere Versuche: keine zweite Sicherung mit demselben Inhalt, Datei weiter unveraendert", len(list(Path(TMP.name).glob("day_bets.corrupt-*.json"))) == 1 and path.read_bytes() == bad)
for content in ('[]', '{"format": "anderes", "games": {}}', '{"format": "nbaedge-day-bets", "games": []}', '{"format": "nbaedge-day-bets", "games": {"k": {"bets": 5}}}', "", "kein json"):
    path.write_text(content)
    c = path.read_bytes()
    check(f"Struktur ungueltig ({content[:34]!r}): Fehler beim Schreiben, nichts ueberschrieben", isinstance(raises(ds.DayBetsError, ds.set_bet, *G, "total", line=231.5, now=NOW), str) and path.read_bytes() == c and ds.load_error())
path.write_text(json.dumps({"format": "nbaedge-day-bets", "version": 99, "games": {}}))
check("Datei aus neuerer Programmversion: Fehler, nicht ueberschrieben", isinstance(raises(ds.DayBetsError, ds.set_bet, *G, "total", line=231.5, now=NOW), str) and json.loads(path.read_text())["version"] == 99 and "neueren" in ds.load_error())
path.write_bytes(good)
check("Datei wieder in Ordnung: alles geht wieder, alter Inhalt noch da", ds.get_bets(*G)["winner"]["side"] == "home" and ds.set_bet(*G, "total", line=231.5, now=NOW)["status"] == "saved" and set(ds.get_bets(*G)) == {"winner", "total"})
b0 = path.read_bytes(); real_replace = os.replace
def boom(*a, **k): raise OSError("Platte voll")
ps.os.replace = boom
try:
    m = raises(ds.DayBetsError, ds.set_bet, *G, "spread", side="home", line=-4.5, now=NOW + 5)
finally:
    ps.os.replace = real_replace
check("Schreibfehler: Meldung, Datei bytegleich, kein Temp-Rest", isinstance(m, str) and "nicht verändert" in m and path.read_bytes() == b0 and not list(Path(TMP.name).glob("*.tmp")), str(m))

# ----------------------------------------------------------------- gleichzeitige Schreibzugriffe
reset()
games = [("2026-10-22", iso(NOW + (6 + i) * H), f"Heim{i}", f"Gast{i}") for i in range(16)]
errors = []
def worker(g, i):
    try:
        ds.set_bet(*g, "total", line=220.5 + i, stake=i + 1, now=NOW + i)
    except Exception as e:
        errors.append(repr(e))
ths = [threading.Thread(target=worker, args=(g, i)) for i, g in enumerate(games)]
[t.start() for t in ths]; [t.join() for t in ths]
d = raw()
check("16 Threads, 16 Spiele: keine Fehler, alle 16 Wetten vorhanden und richtig zugeordnet, Datei gueltig", not errors and len(d["games"]) == 16 and all(d["games"][ps.game_key(g[0], g[1], g[2], g[3])]["bets"]["total"]["line"] == 220.5 + i for i, g in enumerate(games)), errors[:1])
errors.clear()
reset()
def worker2(i):
    try:
        ds.set_bet(*G, "total", line=230.5, stake=i + 1, now=NOW + i)
    except Exception as e:
        errors.append(repr(e))
ths = [threading.Thread(target=worker2, args=(i,)) for i in range(10)]
[t.start() for t in ths]; [t.join() for t in ths]
tb = raw()["games"][key]["bets"]["total"]
check("10 Threads aendern DIESELBE Wette: genau eine Wette, 9 Revisionen (jeder Zwischenstand gesichert), kein Verlust", not errors and len(raw()["games"][key]["bets"]) == 1 and len(tb["revisions"]) == 9 and sorted([r_["stake"] for r_ in tb["revisions"]] + [tb["stake"]]) == [float(i + 1) for i in range(10)], errors[:1])
reset()
code = ("import sys; sys.path.insert(0, %r)\nfrom data import day_bets_store as ds\n"
        "ds.set_bet(%r, %r, %r, %r, sys.argv[1], side=sys.argv[2], line=(None if sys.argv[1]=='winner' else float(sys.argv[3])), stake=float(sys.argv[4]), now=%r)\n") % (str(ROOT), D, START, HOME, AWAY, NOW)
jobs = [("winner", "home", "0", "5"), ("spread", "home", "-4.5", "6"), ("total", "over", "231.5", "7"), ("team_total_home", "over", "118.5", "8"), ("team_total_away", "over", "113.5", "9")] * 2
env = {**os.environ, "NBAEDGE_TRACKING_DIR": TMP.name}
procs = [subprocess.Popen([sys.executable, "-c", code, *j], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for j in jobs]
outs = [p.communicate(timeout=120) for p in procs]
d = raw()
check("10 Prozesse gleichzeitig (je zwei je Markt, gleiche Werte): alle Aufrufe ohne Fehler, Datei gueltig, 5 Maerkte genau einmal", all(p.returncode == 0 for p in procs) and set(d["games"][key]["bets"]) == set(ds.MARKETS) and len(d["games"]) == 1, [o[1].decode()[-200:] for o in outs if o[1]][:1])
check("Prozesse: doppelte identische Wetten erzeugen keine Revisionen", all(b["revisions"] == [] for b in d["games"][key]["bets"].values()) and [d["games"][key]["bets"][m]["stake"] for m in ds.MARKETS] == [5.0, 6.0, 7.0, 8.0, 9.0])
check("nach den Prozessen: kein Temp-Rest, Sperrdatei nur als .lock", not list(Path(TMP.name).glob("*.tmp")) and (Path(TMP.name) / "day_bets.json.lock").exists())

# ----------------------------------------------------------------- Tagesabfrage
reset()
ds.set_bet("2026-10-22", iso(NOW + 8 * H), "B_Heim", "B_Gast", "winner", side="home", now=NOW)
ds.set_bet("2026-10-22", iso(NOW + 6 * H), "A_Heim", "A_Gast", "total", line=210.5, now=NOW)
ds.set_bet("2026-10-22", iso(NOW + 6 * H), "A_Heim", "A_Gast", "winner", side="away", now=NOW)
ds.set_bet("2026-10-23", iso(NOW + 30 * H), "C_Heim", "C_Gast", "winner", side="home", now=NOW)
ds.remove_bet("2026-10-22", iso(NOW + 8 * H), "B_Heim", "B_Gast", "winner", now=NOW)
day = ds.get_day_bets("2026-10-22")
check("Spieltag lesen: nur Spiele dieses US-Datums mit aktiven Wetten (B hat nur eine entfernte Wette)", set(v["game"]["home"] for v in day.values()) == {"A_Heim"} and ds.get_day_bets("2026-10-23").keys() != day.keys() and len(ds.get_day_bets("2026-10-21")) == 0)
check("Spieltag lesen mit entfernten Wetten", {v["game"]["home"] for v in ds.get_day_bets("2026-10-22", include_removed=True).values()} == {"A_Heim", "B_Heim"})
flat = ds.list_day_bets("2026-10-22")
check("flache Liste: nach Anpfiff und Markt-Reihenfolge (winner vor total)", [(r_["game"]["home"], r_["market"]) for r_ in flat] == [("A_Heim", "winner"), ("A_Heim", "total")] and flat[0]["bet"]["side"] == "away")
check("Spiel ueber Datum/Anpfiff/Heim/Gast und ueber Schluessel gleich lesbar", ds.get_bets("2026-10-22", iso(NOW + 6 * H), "A_Heim", "A_Gast") == ds.get_bets_by_key(ps.game_key("2026-10-22", iso(NOW + 6 * H), "A_Heim", "A_Gast")))

# ----------------------------------------------------------------- Auswahl-Logik
check("naechste .5-Linie: 231,0 -> 231,5; 231,2 -> 231,5; 231,8 -> 231,5; -4,2 -> -4,5; -4,5 -> -4,5; 118,0 -> 118,5", [ds.nearest_half_line(x) for x in (231.0, 231.2, 231.8, -4.2, -4.5, 118.0)] == [231.5, 231.5, 231.5, -4.5, -4.5, 118.5])
lt = ds.line_choices("total", 231.5)
check("Total: Hauptlinie +- 5 in Schritten von 1 (11 Linien, alle .5, aufsteigend, enthaelt die Hauptlinie)", lt == [226.5 + i for i in range(11)] and all(abs(x * 2 - round(x * 2)) < 1e-9 and round(x * 2) % 2 == 1 for x in lt) and 231.5 in lt)
check("Standard je Markt = Hauptlinie (auf .5 gebracht); Sieger/ohne Hauptlinie: keine", ds.default_line("total", 231.5) == 231.5 and ds.default_line("total", 231.0) == 231.5 and ds.default_line("winner", 231.5) is None and ds.default_line("total", None) is None)
sh, sa = ds.line_choices("spread", -4.5, "home"), ds.line_choices("spread", -4.5, "away")
check("Spread Heim: -9,5 bis 0,5; Gast: -0,5 bis 9,5 (Gegenlinien, aufsteigend); Standard Heim -4,5 / Gast +4,5", sh == [-9.5 + i for i in range(11)] and sa == [-0.5 + i for i in range(11)] and ds.default_line("spread", -4.5, "home") == -4.5 and ds.default_line("spread", -4.5, "away") == 4.5)
check("Spread: Heim -4,5 bei Gast: Linie -x Heim <-> +x Gast stimmt fuer jede Auswahl", all(-x in sa for x in sh))
check("Bereichsgrenzen werden respektiert (Team Total nahe 40, Total nahe 400)", min(ds.line_choices("team_total_home", 42.5)) >= 40.0 and min(ds.line_choices("team_total_home", 42.5)) == 40.5 and max(ds.line_choices("total", 398.5)) <= 400.0)
check("ohne Hauptlinie / Sieger / unbekannter Markt: leere Liste", ds.line_choices("total", None) == [] and ds.line_choices("winner", 1.5) == [] and ds.line_choices("xyz", 1.5) == [])
check("weniger Schritte", ds.line_choices("total", 231.5, steps=2) == [229.5, 230.5, 231.5, 232.5, 233.5])
sel = ds.selectable_lines({"spread_home": -4.5, "total": 231.5, "team_total_home": 118.5, "team_total_away": None})
check("selectable_lines: alle Maerkte, jeweils Vorauswahl = Hauptlinie und 11 Linien; fehlende Hauptlinie leer", set(sel) == {"winner", "spread", "total", "team_total_home", "team_total_away"} and sel["total"]["default"] == 231.5 and len(sel["total"]["lines"]) == 11
      and sel["spread"]["home"]["default"] == -4.5 and sel["spread"]["away"]["default"] == 4.5 and sel["team_total_home"]["default"] == 118.5 and sel["team_total_away"] == {"default": None, "lines": []} and sel["winner"] == {"default": None, "lines": []})
check("jede auswaehlbare Linie wird vom Speicher akzeptiert (Total, Spread Heim/Gast, Team Total)", all(ds._validate("total", None, x, None, None, None, None)["line"] == x for x in sel["total"]["lines"])
      and all(ds._validate("spread", "home", x, None, None, None, None)["line"] == x for x in sel["spread"]["home"]["lines"]) and all(ds._validate("spread", "away", x, None, None, None, None)["line"] == x for x in sel["spread"]["away"]["lines"])
      and all(ds._validate("team_total_home", None, x, None, None, None, None)["line"] == x for x in sel["team_total_home"]["lines"]))
res = {"spread": {"line": 4.5}, "total": {"line": 231.5}, "team_total_home": {"line": None}, "team_total_away": {"line": None}}
ml = ds.main_lines_from_resolved(res)
check("Hauptlinien aus market_lines: Spread positiv (Heim-Favorit) -> Heim-Sicht -4,5; Team Totals rechnerisch aus Total/Spread (118,0 / 113,5)", ml["spread_home"] == -4.5 and ml["total"] == 231.5 and ml["team_total_home"] == 118.0 and ml["team_total_away"] == 113.5, str(ml))
ml2 = ds.main_lines_from_resolved({"spread": {"line": -3.5}, "total": {"line": None}, "team_total_home": {"line": 114.5}, "team_total_away": {"line": 117.5}})
check("Hauptlinien: Auswaerts-Favorit (-3,5) -> Heim +3,5; vorhandene Team-Total-Linien bleiben; ohne Total keine Ableitung noetig", ml2["spread_home"] == 3.5 and ml2["team_total_home"] == 114.5 and ml2["team_total_away"] == 117.5 and ds.main_lines_from_resolved(None)["total"] is None)
entry = {"markets": {ps.WINNER: {"home_odds": 1.55, "away_odds": 2.5, "bookmaker": "Betano", "updated_at": "t1"},
                      ps.SPREAD: {"lines": [{"id": "main", "active": True, "line_home": -4.5, "line_away": 4.5, "home_odds": 1.91, "away_odds": 1.89, "bookmaker": "Betano", "updated_at": "t2"},
                                            {"id": "x1", "active": False, "line_home": -5.5, "line_away": 5.5, "home_odds": 2.1, "away_odds": 1.7}]},
                      ps.TOTAL: {"lines": [{"id": "main", "active": True, "line": 231.5, "over_odds": 1.9, "under_odds": 1.92, "bookmaker": "Betano", "updated_at": "t3"}]},
                      ps.TEAM_TOTALS: {"home": {"lines": [{"id": "main", "active": True, "line": 118.5, "over_odds": 1.85, "under_odds": 1.95, "bookmaker": "Betano", "updated_at": "t4"}]}, "away": {"lines": []}}}}
check("Quote aus dem Speicher: Sieger Heim/Gast", ds.stored_odds(entry, "winner", "home")["odds"] == 1.55 and ds.stored_odds(entry, "winner", "away")["odds"] == 2.5 and ds.stored_odds(entry, "winner", "home")["bookmaker"] == "Betano")
check("Quote aus dem Speicher: Spread je Seite und Linie (entfernte Linie nicht)", ds.stored_odds(entry, "spread", "home", -4.5)["odds"] == 1.91 and ds.stored_odds(entry, "spread", "away", 4.5)["odds"] == 1.89 and ds.stored_odds(entry, "spread", "home", -5.5) is None and ds.stored_odds(entry, "spread", "home", -3.5) is None)
check("Quote aus dem Speicher: Under-Quote bei Total und Team Total (Seite under)", ds.stored_odds(entry, "total", "under", 231.5)["odds"] == 1.92 and ds.stored_odds(entry, "team_total_home", "under", 118.5)["odds"] == 1.95
      and ds.stored_odds(entry, "total", "over", 231.5)["odds"] == 1.9)
check("Quote aus dem Speicher: Total und Team Total (Over), unbekannte Linie/Markt/Eintrag: None", ds.stored_odds(entry, "total", "over", 231.5)["odds"] == 1.9 and ds.stored_odds(entry, "total", "over", 232.5) is None and ds.stored_odds(entry, "team_total_home", "over", 118.5)["odds"] == 1.85
      and ds.stored_odds(entry, "team_total_away", "over", 113.5) is None and ds.stored_odds(None, "winner", "home") is None and ds.stored_odds(entry, "xyz", "home", 1.5) is None)

# ----------------------------------------------------------------- Anbindung an das Live-Modell
anchor = lm.Anchor(230.0, 8.1, 119.0, 111.0, round(0.7303, 4), sigmas_version="2")
Q3 = gc.build_game_clock(2, "", 3, "PT06M00.00S"); PRE = gc.build_game_clock(1, "", 0, ""); FIN = gc.build_game_clock(3, "Final", 4, "")
mk = lambda market, **kw: {"market": market, "active": True, "side": kw.pop("side", None), "line": kw.pop("line", None), "odds": kw.pop("odds", None), "stake": kw.pop("stake", None), **kw}
bets = {"winner": mk("winner", side="home", odds=1.5, stake=20), "total": mk("total", side="over", line=144.5, odds=1.9, stake=10), "spread": mk("spread", side="home", line=-4.5),
        "team_total_home": mk("team_total_home", side="over", line=120.5, odds=1.85, stake=5), "team_total_away": mk("team_total_away", side="over", line=59.5)}
live = ds.evaluate_game_bets(bets, anchor, Q3, 85, 60)
check("Live: Total Over 144,5 bei 145 Punkten sofort gewonnen (Spiel laeuft noch), Gewinn = Einsatz * (Quote - 1)", live["total"].state == "gewonnen" and live["total"].won and live["total"].probability == 1.0 and live["total"].profit == 9.0 and not live["total"].final)
check("Live: Team Total Gast Over 59,5 bei 60 Punkten gewonnen (ohne Quote/Einsatz: kein Gewinn, Wette zaehlt)", live["team_total_away"].state == "gewonnen" and live["team_total_away"].profit is None)
check("Live: Sieger und Spread offen mit Chance und Stand (85:60)", live["winner"].state == "offen" and live["spread"].state == "offen" and 0 < live["winner"].probability < 1 and (live["winner"].home_pts, live["winner"].away_pts) == (85, 60) and live["winner"].profit is None
      and live["team_total_home"].state == "offen" and live["winner"].label in ("Auf Kurs", "Offen", "In Gefahr", "Kaum noch möglich"))
check("Live: Sieger Heim bei 25 Punkten Vorsprung in Q3 'Auf Kurs' (gruen)", live["winner"].label == "Auf Kurs" and live["winner"].color == "gruen")
pre = ds.evaluate_game_bets(bets, anchor, PRE, 0, 0)
check("vor dem Anpfiff: Status 'Wartet auf Anpfiff' (grau) mit der Vorab-Chance; Sieger = 73,0 % laut Anker", all(v.state == "wartet" and v.label == "Wartet auf Anpfiff" and v.color == "grau" for v in pre.values()) and abs(pre["winner"].probability - 0.7303) < 5e-5)
fin = ds.evaluate_game_bets(bets, anchor, FIN, 100, 112)
check("Spielende 100:112: Sieger Heim verloren (-Einsatz), Total 144,5 gewonnen (Gewinn), Spread verloren, Team Total Heim 120,5 verloren, Gast gewonnen", fin["winner"].state == "verloren" and fin["winner"].profit == -20.0
      and fin["total"].state == "gewonnen" and fin["spread"].state == "verloren" and fin["team_total_home"].state == "verloren" and fin["team_total_home"].profit == -5.0 and fin["team_total_away"].state == "gewonnen" and fin["winner"].final)
ub = {"total": mk("total", side="under", line=144.5, odds=2.0, stake=10), "team_total_home": mk("team_total_home", side="under", line=120.5, odds=1.9, stake=10)}
lu = ds.evaluate_game_bets(ub, anchor, Q3, 85, 60)
check("Live Under: Total Under 144,5 bei 145 Punkten sofort VERLOREN (Stand hat die Linie erreicht), Team Total Heim Under 120,5 offen", lu["total"].state == "verloren" and lu["total"].decided and lu["total"].probability == 0.0
      and lu["total"].profit == -10.0 and lu["team_total_home"].state == "offen" and 0 < lu["team_total_home"].probability < 1)
check("Live Under: Chance = 1 - Over-Chance", abs(lu["team_total_home"].probability + ds.evaluate_game_bets({"team_total_home": mk("team_total_home", side="over", line=120.5)}, anchor, Q3, 85, 60)["team_total_home"].probability - 1) < 1e-12)
fu = ds.evaluate_game_bets(ub, anchor, FIN, 70, 60)
check("Spielende 70:60: Total Under 144,5 gewonnen (130 Punkte), Team Total Heim Under 120,5 gewonnen; bei 100:112 verloren/gewonnen", fu["total"].state == "gewonnen" and fu["total"].profit == 10.0 and fu["team_total_home"].state == "gewonnen"
      and ds.evaluate_game_bets(ub, anchor, FIN, 100, 112)["total"].state == "verloren" and ds.evaluate_game_bets(ub, anchor, FIN, 100, 112)["team_total_home"].state == "gewonnen")
rem = ds.bet_live_status({**bets["winner"], "active": False}, lm.project(anchor, Q3, 85, 60))
check("entfernte Wette: Status 'Entfernt', zaehlt nicht", rem.state == "entfernt" and rem.label == "Entfernt" and rem.probability is None and ds.summarize([rem])["wetten"] == 0)
smry = ds.summarize(list(fin.values()))
check("Tagesuebersicht (nach Spielende): 5 Wetten, 0 offen, 2 gewonnen, 3 verloren, Einsatz 35, Gewinn/Verlust nur abgerechnet mit Quote+Einsatz (9,0 - 20,0 - 5,0 = -16,0), 1 ohne Quote/Einsatz",
      smry == {"wetten": 5, "offen": 0, "gewonnen": 2, "verloren": 3, "einsatz": 35.0, "einsatz_abgerechnet": 35.0, "gewinn_verlust": -16.0, "ohne_quote_oder_einsatz": 2}, str(smry))
smry2 = ds.summarize(list(live.values()))
check("Tagesuebersicht (laufend): 3 offen, 2 gewonnen, 0 verloren, nur das abgerechnete Total im Gewinn (+9,0)", (smry2["offen"], smry2["gewonnen"], smry2["verloren"], smry2["gewinn_verlust"]) == (3, 2, 0, 9.0), str(smry2))
check("gespeicherte Wetten passen zur Statuslogik (set_bet -> get_bets -> evaluate_game_bets)", (lambda: (ds.set_bet(*G, "total", line=144.5, odds=1.9, stake=10, now=NOW), ds.evaluate_game_bets(ds.get_bets(*G), anchor, Q3, 85, 60)["total"].state)[1] == "gewonnen")())

# ----------------------------------------------------------------- Rahmen
check("das echte data/tracking/day_bets.json wurde nicht angelegt/veraendert", (real_file.read_bytes() if real_file.exists() else None) == real_before)
check("Temp-Ordner wurde benutzt (Datei liegt dort), im echten Ordner keine Sperrdatei neu angelegt oder entfernt", path.parent == Path(TMP.name) and real_lock.exists() == real_lock_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
