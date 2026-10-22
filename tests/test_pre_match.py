"""Tests fuer den Tab 'Pre-Match Eingabe' und data/pre_match_store.py.
Offline (tests/fake_net.py, Temp-Verzeichnisse), keine echten Calls, Pickle nur gelesen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_pre_match.py"""
import datetime as dt, hashlib, json, os, re, sys, threading, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
import data.pre_match_store as ps
import ui.pre_match_tab as pmt
from models.elo import MODEL_PATH
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
real_dir = ROOT / "data" / "tracking"
real_before = sorted((p.name, p.stat().st_mtime_ns) for p in real_dir.rglob("*")) if real_dir.exists() else None
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
fsha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
K, P = "New York Knicks", "Philadelphia 76ers"
def save(start, now, h="1,55", a="2,50", b="Pinnacle", home=K, away=P, date="2026-10-20"):
    return ps.save_market(date, start, home, away, "winner_incl_ot", h, a, b, now=now)

# ======================================================== A) Eingabepruefung
good = {"1,85": 1.85, "1.85": 1.85, " 2 ": 2.0, "1,01": 1.01, "10,5": 10.5, "1000": 1000.0, "2,50": 2.5}
check("gueltige Quoten (Komma/Punkt/Leerzeichen)", all(ps.parse_odds_input(k) == v for k, v in good.items()))
bad = ["", "  ", None, "abc", "1,00", "1.0", "0,9", "0", "-2,5", "1,2,3", "1.2.3", "1,5.5", "nan", "inf", "1e3", "1001", "2,5x", "--1"]
errs = {}
for t in bad:
    try: ps.parse_odds_input(t); errs[t] = None
    except ps.OddsInputError as e: errs[t] = str(e)
check("ungueltige Eingaben werden alle abgelehnt (leer, Text, <=1,00, negativ, mehrere Trenner, nan/inf, >1000)", all(v for v in errs.values()), str({k: v for k, v in errs.items() if not v}))
check("Meldungen sind kurz und deutsch", errs["abc"].startswith("Bitte eine Zahl") and errs["1,00"] == "Die Quote muss größer als 1,00 sein." and errs[""] == "Quote fehlt.")
check("Buchmacher: Steuerzeichen/Leerraum bereinigt, auf 60 Zeichen begrenzt", ps.clean_bookmaker("  Pin\n nacle\t ") == "Pin nacle" and len(ps.clean_bookmaker("x" * 100)) == 60)

# ======================================================== B) Speichern, Neu-Laden, Aendern
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
r = save(start, now)
data = json.loads(ps.store_path().read_text())          # ohne die App lesbar: nur json
key = f"2026-10-20|{start}|{K}|{P}"
m = data["entries"][key]["markets"]["winner_incl_ot"]
check("Datei: Kopf mit Version 5/Format, Schluessel Spieldatum|Anpfiff|Heim|Gast", data["version"] == 5 and data["format"] == "nbaedge-pre-match-entries" and key in data["entries"] and r["key"] == key and r["status"] == "saved")
check("Eintrag: Quoten, Buchmacher, Zeitstempel eingetragen am (mit UTC-Versatz) vor dem Anpfiff", m["home_odds"] == 1.55 and m["away_odds"] == 2.5 and m["bookmaker"] == "Pinnacle" and re.search(r"[+-]\d\d:\d\d$", m["entered_at"]) and dt.datetime.fromisoformat(m["entered_at"]).timestamp() < ps.parse_utc(start))
check("Datei enthaelt keine Keys/Zugangsdaten und ist reines JSON (Zahlen als Zahlen)", "apikey" not in ps.store_path().read_text().lower() and isinstance(m["home_odds"], float))
day = dt.datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d")
hist = ps.history_dir() / f"pre_match_entries_{day}.json"
check("Tageskopie unter data/tracking/history/ mit gleichem Inhalt", hist.exists() and fsha(hist) == fsha(ps.store_path()), hist.name)
check("kein .tmp zurueckgeblieben", not list(ps.tracking_dir().rglob("*.tmp")))
check("Neu-Laden: load()/get_entry liefern die gespeicherten Werte", ps.get_entry(key)["markets"]["winner_incl_ot"]["home_odds"] == 1.55 and ps.last_bookmaker() == "Pinnacle")
r2 = save(start, now + 5)
check("gleiche Werte nochmal speichern: 'unchanged', keine neue Revision", r2["status"] == "unchanged" and len(ps.get_entry(key)["markets"]["winner_incl_ot"]["revisions"]) == 1)
r3 = save(start, now + 60, h="1.60", b="Bet365")
m = ps.get_entry(key)["markets"]["winner_incl_ot"]
check("Aendern vor dem Anpfiff: neue Werte, entered_at bleibt, updated_at neu, 2 Revisionen (alte Quote bleibt nachvollziehbar)", r3["status"] == "saved" and m["home_odds"] == 1.6 and m["entered_at"] != m["updated_at"] and [x["home_odds"] for x in m["revisions"]] == [1.55, 1.6] and [x["bookmaker"] for x in m["revisions"]] == ["Pinnacle", "Bet365"])
check("Buchmacher merkt sich den zuletzt benutzten Namen", ps.last_bookmaker() == "Bet365")
r4 = save(iso(now + 5 * H), now + 70, home="San Antonio Spurs", away="Oklahoma City Thunder")
check("zweites Spiel: eigener Schluessel, erstes unveraendert", len(ps.load()["entries"]) == 2 and ps.get_entry(key)["markets"]["winner_incl_ot"]["home_odds"] == 1.6)

# ======================================================== C) Sperre nach dem Anpfiff
before = fsha(ps.store_path())
for label, t in (("ab dem Anpfiff", now + 3 * H), ("nach dem Anpfiff", now + 3 * H + 1)):
    try: save(start, t, h="9,9"); raised = False
    except ps.GameStartedError: raised = True
    check(f"Speichern {label}: GameStartedError, Datei unveraendert", raised and fsha(ps.store_path()) == before)
try: ps.save_market("2026-10-20", None, K, P, "winner_incl_ot", "1,5", "2,5", "", now=now); raised = False
except ps.GameStartedError: raised = True
check("unbekannter Anpfiff: gesperrt", raised and fsha(ps.store_path()) == before)
try: save(start, now, h="abc"); raised = False
except ps.OddsInputError: raised = True
check("ungueltige Quote wird VOR jeder Dateiaenderung abgelehnt", raised and fsha(ps.store_path()) == before)

# ======================================================== D) Datei bleibt bei Fehler heil
import os as _os
real_replace = _os.replace
def boom(*a, **k): raise OSError("Platte voll")
_os.replace = boom
try: save(start, now + 80, h="1,70"); raised = None
except ps.StoreError as e: raised = str(e)
finally: _os.replace = real_replace
check("Fehler beim Ersetzen: StoreError mit kurzer Meldung, Originaldatei Byte fuer Byte unveraendert, kein .tmp", raised and "nicht verändert" in raised and fsha(ps.store_path()) == before and not list(ps.tracking_dir().rglob("*.tmp")), str(raised))
real_dumps = json.dumps
def bad_dumps(*a, **k): raise TypeError("nicht serialisierbar")
ps.json.dumps = bad_dumps
try: save(start, now + 90, h="1,71"); raised = None
except ps.StoreError as e: raised = str(e)
finally: ps.json.dumps = real_dumps
check("Fehler beim Serialisieren: Originaldatei unveraendert", raised and fsha(ps.store_path()) == before)
# kaputte Datei
ps.store_path().write_text('{"version": 1, "entries": [kaputt')
check("defekte Datei: load() meldet Fehler, aendert nichts", ps.load().get("error") and ps.store_path().read_text().startswith('{"version": 1, "entries": [kaputt'))
r = save(start, now + 100)
backups = list(ps.tracking_dir().glob("pre_match_entries.corrupt-*.json"))
check("Speichern bei defekter Datei: defekte Datei wird gesichert (.corrupt-...), neue saubere Datei", r["status"] == "saved" and len(backups) == 1 and backups[0].read_text().startswith('{"version": 1') and len(ps.load()["entries"]) == 1 and not ps.load().get("error"))
# neuere Version
d = ps.load(); d["version"] = 99; ps.store_path().write_text(json.dumps(d)); b = fsha(ps.store_path())
try: save(start, now + 110, h="1,9"); raised = False
except ps.StoreError: raised = True
check("Datei aus neuerer Programmversion: nichts wird veraendert", raised and fsha(ps.store_path()) == b)
# parallel
tmp = fresh_env(); errors = []
def worker(i):
    try: ps.save_market("2026-10-20", iso(now + 3 * H + i * 60), f"Heim{i} Team", f"Gast{i} Team", "winner_incl_ot", "1,5", "2,5", "X", now=now)
    except Exception as e: errors.append(repr(e))
ts = [threading.Thread(target=worker, args=(i,)) for i in range(12)]; [t.start() for t in ts]; [t.join() for t in ts]
check("12 gleichzeitige Speichervorgaenge: alle Eintraege vorhanden, Datei gueltig", not errors and len(ps.load()["entries"]) == 12, str(errors[:1]))

# ======================================================== E) App (AppTest)
def games_setup(offsets):
    tmp = fresh_env(); state["commence_offsets"] = dict(offsets); return tmp
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def kid(home, away, at):
    p = [x for x in at.session_state["projections"] if x["home_team"] == home][0]
    return pmt.hashlib.md5(ps.game_key(p["game_date"], ps.normalize_start(p["game_start"]), home, away).encode()).hexdigest()[:10], p
def submit(at, k):
    return [b for b in at.button if b.key == f"pm_save_{k}"][0]          # EIN Speichern-Knopf pro Karte
def pm_html(at): return " ".join(m.value for m in at.tabs[-1].markdown)
PAIRS = {"New York Knicks": "Philadelphia 76ers", "San Antonio Spurs": "Oklahoma City Thunder", "Detroit Pistons": "Boston Celtics"}
tmp = games_setup({"New York Knicks": 3 * H, "San Antonio Spurs": 3 * H, "Detroit Pistons": -600})
at = app().run()
labels = [t.label for t in at.tabs]
check("Tab 'Pre-Match Eingabe' steht am Ende, die anderen Tabs unveraendert in der Reihenfolge", not at.exception and labels[-1].endswith("Pre-Match Eingabe") and labels[:-1] == ["📊 Score Projections", "🔴 Live (alt)", "🏀 Spieltag", "🎯 Live Bet Tracker", "📰 Lineup News", "📅 History", "📈 ELO Rankings"], str(labels))
html = pm_html(at)
check("Karten fuer dieselben 3 Spiele wie Score Projections (Teams, Reihenfolge nach Anpfiff)", html.count("AWAY") == 3 and all(n in html for n in ("Knicks", "Spurs", "Pistons", "76ers", "Thunder", "Celtics")) and len(at.session_state["projections"]) == 3)
check("Karte nutzt Kartenkopf und Logos aus score_cards (pc-head, eingebettete SVG-Logos), Anpfiff in Berliner Zeit", html.count('class="pc-head"') == 3 and "data:image/svg+xml" in html and re.search(r"(Mo|Di|Mi|Do|Fr|Sa|So) \d\d\.\d\d\. · \d\d:\d\d Uhr", html))
k_knicks, p_knicks = kid("New York Knicks", "Philadelphia 76ers", at)
k_spurs, _ = kid("San Antonio Spurs", "Oklahoma City Thunder", at)
k_pist, _ = kid("Detroit Pistons", "Boston Celtics", at)
widgets = {x.key for x in at.text_input if x.key}
check("Eingabefelder nur bei Spielen vor dem Anpfiff (Knicks, Spurs); Pistons (laeuft) ohne Felder", {f"pm_home_{k_knicks}", f"pm_away_{k_knicks}", f"pm_book_{k_knicks}", f"pm_home_{k_spurs}"} <= widgets and not any(k_pist in w for w in widgets), str(sorted(widgets)))
check("Status-Chips in der Mitte unveraendert: 2 x Vorab (grau), laeuft (gelb)", html.count(">Vorab<") == 2 and 'pc-chip pc-chip-yellow">läuft<' in html and 'pc-chip pc-chip-gray">Vorab<' in html)
c0 = (len(state["odds_calls"]), state["bdl_calls"], state["nba_calls"])
at.run(); at.run()
check("Tab oeffnen/Reruns: keine zusaetzlichen Odds-, BallDontLie- oder NBA-Abrufe, keine Credits", (len(state["odds_calls"]), state["bdl_calls"], state["nba_calls"]) == c0, str(c0))
check("ohne Eingabe wird nichts gespeichert (keine Datei)", not ps.store_path().exists())

# Speichern ueber die Oberflaeche
at.text_input(key=f"pm_home_{k_knicks}").input("1,55"); at.text_input(key=f"pm_away_{k_knicks}").input("2.50"); at.text_input(key=f"pm_book_{k_knicks}").input("Pinnacle")
submit(at, k_knicks).click().run()
e = ps.load()["entries"]
check("Speichern-Knopf: Eintrag in data/tracking/pre_match_entries.json (Quoten, Buchmacher, Zeitstempel)", not at.exception and len(e) == 1 and list(e.values())[0]["markets"]["winner_incl_ot"]["away_odds"] == 2.5 and list(e.values())[0]["home"] == "New York Knicks")
check("Schluessel enthaelt Spieldatum (US), Anpfiff (UTC), Heim und Gast", list(e)[0] == ps.game_key(p_knicks["game_date"], ps.normalize_start(p_knicks["game_start"]), "New York Knicks", "Philadelphia 76ers"), list(e)[0])
html = pm_html(at)
check("Karte zeigt danach oben rechts den blaugrauen Chip 'gespeichert HH:MM' (nicht gruen)", len(re.findall(r'<div class="pm-corner"><div class="pc-chip pc-chip-blue">gespeichert \d\d:\d\d</div></div>', html)) == 1 and "Zuletzt gespeichert" not in " ".join(c.value for c in at.caption))
# neue Sitzung: Werte erscheinen wieder
at2 = app().run()
check("Neu oeffnen (neue Sitzung): gespeicherte Werte stehen wieder in den Feldern", at2.text_input(key=f"pm_home_{k_knicks}").value == "1,55" and at2.text_input(key=f"pm_away_{k_knicks}").value == "2,50" and at2.text_input(key=f"pm_book_{k_knicks}").value == "Pinnacle")
check("Buchmacher-Feld merkt sich den zuletzt benutzten Namen bei einem neuen Spiel", at2.text_input(key=f"pm_book_{k_spurs}").value == "Pinnacle" and at2.text_input(key=f"pm_home_{k_spurs}").value == "")
# aendern
at2.text_input(key=f"pm_home_{k_knicks}").input("1,60"); submit(at2, k_knicks).click().run()
m = list(ps.load()["entries"].values())[0]["markets"]["winner_incl_ot"]
check("Aendern ueber die Oberflaeche: neue Quote, 2 Revisionen, entered_at unveraendert", m["home_odds"] == 1.6 and len(m["revisions"]) == 2 and m["entered_at"] == m["revisions"][0]["saved_at"])
# Eingabepruefung in der App
before = fsha(ps.store_path())
for h_in, a_in, expect in (("abc", "2,5", "Bitte eine Zahl"), ("1,00", "2,5", "größer als 1,00"), ("0,9", "2,5", "größer als 1,00"), ("1,5", "", "Quote fehlt"), ("1,5", "2,5,5", "Dezimaltrenner")):
    a = app().run()
    a.text_input(key=f"pm_home_{k_spurs}").input(h_in); a.text_input(key=f"pm_away_{k_spurs}").input(a_in)
    submit(a, k_spurs).click().run()
    check(f"ungueltige Eingabe ({h_in!r} / {a_in!r}): gelbe Warnung '{expect}', Datei unveraendert", any(expect in w.value for w in a.warning) and fsha(ps.store_path()) == before and not a.exception, "; ".join(w.value for w in a.warning)[:80])

# laufendes Spiel: nur Anzeige
pist = ps.load  # Eintrag fuer Pistons nachtraeglich 'vor dem Anpfiff' anlegen
_, pp = kid("Detroit Pistons", "Boston Celtics", at)
ps.save_market(pp["game_date"], pp["game_start"], "Detroit Pistons", "Boston Celtics", "winner_incl_ot", "1,48", "2,70", "Bet365", now=ps.parse_utc(pp["game_start"]) - 1000)
a = app().run(); h = pm_html(a)
check("laufendes Spiel mit gespeicherter Quote: Werte nur angezeigt (1,48 / 2,70 / Bet365), keine Eingabefelder, Hinweis 'gesperrt'", "1,48" in h and "2,70" in h and "Bet365" in h and "Das Spiel läuft: Eingaben sind gesperrt." in h and not any(k_pist in (x.key or '') for x in a.text_input))
b = fsha(ps.store_path())
try: ps.save_market(pp["game_date"], pp["game_start"], "Detroit Pistons", "Boston Celtics", "winner_incl_ot", "3,3", "3,3", "X", now=time.time()); raised = False
except ps.GameStartedError: raised = True
check("laufendes Spiel: auch direkt im Speicher nicht aenderbar (Datei unveraendert)", raised and fsha(ps.store_path()) == b)
# Rennen: Spiel beginnt zwischen Anzeige und Klick
calls = {"n": 0}; real_now = pmt._now; t_start = ps.parse_utc(p_knicks["game_start"])
def racing_now():
    calls["n"] += 1
    return t_start - 100 if calls["n"] == 1 else t_start + 5
a = app().run(); b = fsha(ps.store_path())
a.text_input(key=f"pm_home_{k_knicks}").input("1,99")
pmt._now = racing_now
submit(a, k_knicks).click().run()
pmt._now = real_now
check("Spiel beginnt zwischen Anzeige und Klick: Speichern wird abgelehnt (Warnung), Datei unveraendert", any("bereits begonnen" in w.value for w in a.warning) and fsha(ps.store_path()) == b, "; ".join(w.value for w in a.warning)[:80])
# Spiel ohne Anpfiff (z. B. Offline/Mock): gesperrt
check("Zustaende: ohne Anpfiff 'unbekannt' (gesperrt), laeuft nach Anpfiff, beendet bei Final oder nach 4 Std.", pmt.game_state(None, None, 1e9) == "unbekannt" and pmt.game_state(iso(1000), None, 900) == "vorab" and pmt.game_state(iso(1000), None, 1100) == "läuft" and pmt.game_state(iso(1000), "Final", 1100) == "beendet" and pmt.game_state(iso(1000), "Q4", 1000 + 5 * H) == "beendet")
check("Anpfiff in Berliner Zeit (UTC+2 im Oktober, UTC+1 im Winter)", pmt.berlin_kickoff("2026-10-20T23:00:00Z") == "Mi 21.10. · 01:00 Uhr" and pmt.berlin_kickoff("2026-12-25T18:00:00Z") == "Fr 25.12. · 19:00 Uhr")
check("Quote-Anzeige mit Dezimalkomma (1,55 / 2,50 / 1,005)", pmt.fmt_odds(1.55) == "1,55" and pmt.fmt_odds(2.5) == "2,50" and pmt.fmt_odds(1.005) == "1,005")
check("Design: kein Gruen in CSS/Chips des Tabs (Palette ohne gruene Farbe)", not any(re.search(r"#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})", c) and (int(c[3:5], 16) > int(c[1:3], 16) + 25 and int(c[3:5], 16) > int(c[5:7], 16) + 25) for c in set(re.findall(r"#[0-9a-f]{6}", pmt.PRE_MATCH_CSS.lower()))))

# ======================================================== F) Rahmen
check("Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
real_after = sorted((p.name, p.stat().st_mtime_ns) for p in real_dir.rglob("*")) if real_dir.exists() else None
check("Projekt-data/tracking/ durch die Tests weder angelegt noch veraendert", real_before == real_after)
check("in KEINEM AppTest-Lauf dieser Datei: Streamlit-Exception oder der Satz 'was created with a default value ... Session State API'", not page_checks.bad, "; ".join(page_checks.bad[:2]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
