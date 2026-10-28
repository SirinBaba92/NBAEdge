"""Tests der Spieltag-Logik im Tab Score Projections (ui/score_day.py, app.py): welcher US-Spieltag aktiv ist und dass die Anzeige nur filtert.
Teil 1: reine Funktion active_day (Sommer-/Winterzeit, Mitternacht, Notausstieg 08:00, verschobene Spiele ...). Teil 2: echte app.py im AppTest mit simuliertem Netz
(tests/fake_net.py) und KOPIEN von data/tracking, upcoming_cache.json, pregame_lines.json im Temp-Ordner; die echten Dateien werden nur gelesen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_score_day.py"""
import hashlib, json, os, shutil, sys, tempfile, warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from ui import score_day as sd

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

BER, UTC = ZoneInfo("Europe/Berlin"), timezone.utc
def at(y, m, d, h, mi=0, tz=BER): return datetime(y, m, d, h, mi, tzinfo=tz)
def g(day, status="7:00 PM ET", res=False, feed=None, start=None):
    return {"date": day, "start": start, "status": status, "has_result": res, "feed_status": feed}
D = date.fromisoformat
NOW = at(2026, 10, 28, 20)                                   # Spieltag 28.10. ist noch nicht abgeschlossen (Abschluss waere 29.10. 08:00 Berlin)

# ---- Teil 1: active_day
check("kein Spiel: None", sd.active_day([], NOW) is None)
check("alle Spiele beendet (Final / Ergebnis / Feed FINAL): None", sd.active_day([g("2026-10-28", "Final"), g("2026-10-28", res=True), g("2026-10-28", feed="FINAL")], NOW) is None)
check("nur ein Spiel offen: dieser Spieltag", sd.active_day([g("2026-10-28", "Final"), g("2026-10-28", res=True), g("2026-10-28")], NOW) == D("2026-10-28"))
check("Feed LIVE oder PRE zaehlt nicht als beendet", sd.active_day([g("2026-10-28", feed="LIVE")], NOW) == D("2026-10-28") and sd.active_day([g("2026-10-28", feed="PRE")], NOW) == D("2026-10-28"))
for st_ in ("Postponed", "postponed", "Canceled", "Cancelled", "Abandoned", "Aborted", "Suspended"):
    check(f"Status '{st_}' blockiert den Wechsel nie", sd.active_day([g("2026-10-28", st_)], NOW) is None)
check("verschobenes Spiel blockiert nicht: Rest des Tages bleibt aktiv, sonst naechster Tag",
      sd.active_day([g("2026-10-28", "Postponed"), g("2026-10-28")], NOW) == D("2026-10-28") and sd.active_day([g("2026-10-28", "Postponed"), g("2026-10-29")], NOW) == D("2026-10-29"))
check("mehrere Spieltage: der fruehste mit offenem Spiel gewinnt", sd.active_day([g("2026-10-29"), g("2026-10-28"), g("2026-10-27", "Final")], NOW) == D("2026-10-28"))
check("fruehere Tage fertig, spaeterer offen: der spaetere", sd.active_day([g("2026-10-28", "Final"), g("2026-10-29")], NOW) == D("2026-10-29"))
check("Datum fehlt: Spiel zaehlt ueber den Anpfiff in New York (02:30Z am 29.10. = 28.10. in New York)", sd.active_day([g(None, start="2026-10-29T02:30:00Z")], NOW) == D("2026-10-28"))
check("ohne Datum und Anpfiff: Spiel wird ignoriert", sd.active_day([g(None)], NOW) is None)
check("Zeit als Unix-Zeit und als datetime ohne Zeitzone (= UTC) gleich", sd.active_day([g("2026-10-28")], NOW.timestamp()) == D("2026-10-28") and sd.active_day([g("2026-10-28")], datetime(2026, 10, 28, 18)) == D("2026-10-28"))

# Notausstieg 08:00 deutscher Zeit am Kalendertag nach dem US-Spieltag; Winterzeit (ab 25.10.2026: UTC+1) und Sommerzeit (vor dem 25.10.: UTC+2)
open_ = [g("2026-10-28")]
check("Winterzeit: 07:59 Berlin am Folgetag noch aktiv, 08:00 abgeschlossen", sd.active_day(open_, at(2026, 10, 29, 7, 59)) == D("2026-10-28") and sd.active_day(open_, at(2026, 10, 29, 8, 0)) is None)
check("Winterzeit in UTC angegeben: 06:59Z aktiv, 07:00Z (= 08:00 Berlin) abgeschlossen", sd.active_day(open_, at(2026, 10, 29, 6, 59, UTC)) == D("2026-10-28") and sd.active_day(open_, at(2026, 10, 29, 7, 0, UTC)) is None)
summer = [g("2026-07-15")]
check("Sommerzeit: 07:59 Berlin aktiv, 08:00 abgeschlossen", sd.active_day(summer, at(2026, 7, 16, 7, 59)) == D("2026-07-15") and sd.active_day(summer, at(2026, 7, 16, 8, 0)) is None)
check("Sommerzeit in UTC angegeben: 05:59Z aktiv, 06:00Z (= 08:00 Berlin) abgeschlossen", sd.active_day(summer, at(2026, 7, 16, 5, 59, UTC)) == D("2026-07-15") and sd.active_day(summer, at(2026, 7, 16, 6, 0, UTC)) is None)
check("Umstellungsnacht (Sommer -> Winter, 25.10.): Spieltag 24.10. endet am 25.10. 08:00 Berlin (UTC+1 nach der Umstellung)",
      sd.active_day([g("2026-10-24")], at(2026, 10, 25, 6, 59, UTC)) == D("2026-10-24") and sd.active_day([g("2026-10-24")], at(2026, 10, 25, 7, 0, UTC)) is None)
check("Mitternacht Berlin (00:00 am Folgetag): Spieltag noch aktiv; Mitternacht New York ist kein Wechsel", sd.active_day(open_, at(2026, 10, 29, 0, 0)) == D("2026-10-28") and sd.active_day(open_, at(2026, 10, 29, 5, 0, UTC)) == D("2026-10-28"))
check("Notausstieg: abgeschlossener Tag wird uebersprungen, naechster Tag aktiv", sd.active_day([g("2026-10-28"), g("2026-10-29")], at(2026, 10, 29, 9)) == D("2026-10-29"))
check("Notausstieg: alle Tage abgeschlossen -> None", sd.active_day([g("2026-10-28"), g("2026-10-29")], at(2026, 10, 30, 9)) is None)
check("Eingabe wird nicht veraendert", (lambda gs: (sd.active_day(gs, NOW), gs)[1] == [g("2026-10-28")])([g("2026-10-28")]))

# display_day: bei None der zuletzt gespielte Tag, bis ein neuer Spieltag mit Spielen geladen ist
check("display_day: alles beendet -> zuletzt gespielter Tag der geladenen Spiele", sd.display_day([g("2026-10-27", "Final"), g("2026-10-28", "Final")], NOW) == D("2026-10-28"))
check("display_day: alles beendet, nur Tage beendeter Karten -> neuester Kartentag", sd.display_day([], NOW, [D("2026-10-26"), D("2026-10-27")]) == D("2026-10-27"))
check("display_day: neuer Spieltag mit Spielen geladen -> Wechsel", sd.display_day([g("2026-10-28", "Final"), g("2026-10-29")], NOW) == D("2026-10-29"))
check("display_day: ganz leer -> None", sd.display_day([], NOW) is None and sd.display_day([], NOW, [None]) is None)
check("display_day: Notausstieg unveraendert (offener Tag nach 08:00 abgeschlossen, bleibt aber der zuletzt gespielte, solange nichts Neues geladen ist)",
      sd.active_day(open_, at(2026, 10, 29, 8, 0)) is None and sd.display_day(open_, at(2026, 10, 29, 8, 0)) == D("2026-10-28"))

# ---- Teil 2: echte app.py im AppTest, Kopien im Temp-Ordner
import fake_net
from fake_net import fresh_env
fake_net.install(); tmp = fresh_env()
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
import data.projection_snapshots as ps

def sha(p): return hashlib.sha1(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
def tree(d): return {str(p.relative_to(d)): sha(p) for p in sorted(Path(d).rglob("*")) if p.is_file()}
REAL = {"tracking": tree(ROOT / "data" / "tracking"), "upcoming": sha(ROOT / "data" / "upcoming_cache.json"), "pregame": sha(ROOT / "data" / "pregame_lines.json")}
trk = Path(os.environ["NBAEDGE_TRACKING_DIR"])
shutil.copytree(ROOT / "data" / "tracking", trk, dirs_exist_ok=True)
for src, env in (("upcoming_cache.json", "NBAEDGE_UPCOMING_CACHE"), ("pregame_lines.json", "NBAEDGE_PREGAME_LINES")):
    if (ROOT / "data" / src).exists():
        shutil.copy2(ROOT / "data" / src, os.environ[env])
os.environ["NBAEDGE_ALL_TABS"] = "0"
today = date.today().isoformat()                                # simulierte BallDontLie-Spiele tragen das heutige Datum (fake_net)
snap = trk / "projection_snapshots.json"
old_games = {k: v for k, v in json.loads(snap.read_text())["games"].items() if v.get("result") and v.get("game_date") != today}
h = lambda key: hashlib.md5(key.encode("utf-8")).hexdigest()[:10]

at_ = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300).run()
rank_style = lambda a: " ".join(m.value for m in a.markdown if m.value.startswith("<style>div:has(> .st-key-sc_game_"))
cards = lambda a: [m.value for m in a.markdown if 'class="pc-card' in m.value]
check("App laeuft ohne Fehler", not at_.exception and not problems(at_), " | ".join(problems(at_))[:200])
projs = at_.session_state["projections"]
keys_today = [str((p.get("_line_inputs") or {}).get("entry_key") or p["home_team"]) for p in projs]
style = rank_style(at_)
check("heutige Spiele werden gezeigt", projs and all(h(k) in style for k in keys_today), f"{len(projs)} Spiele")
check("Spiele frueherer Spieltage (Schnappschuss mit Ergebnis, aelter als heute) sind verschwunden", old_games and not any(h(k) in style for k in old_games), f"{len(old_games)} alte Spiele in der Kopie")
check("nur die Karten des aktiven Spieltags: Anzahl = heutige Spiele (+ beendete von heute)", len(cards(at_)) >= len(projs) and len(cards(at_)) == style.count("div:has(> .st-key-sc_game_"), f"{len(cards(at_))} Karten")
check("session_state.projections bleibt ungefiltert (alle Spiele der Abfrage)", len(projs) == len(keys_today) and all(p.get("game_date") for p in projs))

# byteidentisch: nach dem ersten Lauf (der wie bisher Schnappschuesse schreibt) aendert weiteres Rendern nichts mehr an den Kopien
snap_state = lambda: {"tracking": tree(trk), "upcoming": sha(os.environ["NBAEDGE_UPCOMING_CACHE"]), "pregame": sha(os.environ["NBAEDGE_PREGAME_LINES"])}
before = snap_state()
bdl0 = fake_net.state["bdl_calls"]; odds0 = len(fake_net.state["odds_calls"])
at_.run(); at_.run()
after = snap_state()
check("erneutes Rendern: data/tracking (Kopie) byteidentisch", before["tracking"] == after["tracking"])
check("erneutes Rendern: upcoming_cache.json und pregame_lines.json (Kopien) byteidentisch", before["upcoming"] == after["upcoming"] and before["pregame"] == after["pregame"])
check("erneutes Rendern: keine neuen Abrufe (BallDontLie, Odds-API)", fake_net.state["bdl_calls"] == bdl0 and len(fake_net.state["odds_calls"]) == odds0, f"bdl {fake_net.state['bdl_calls'] - bdl0}, odds {len(fake_net.state['odds_calls']) - odds0}")

# Alle heutigen Spiele mit Ergebnis (Kopie im Temp-Ordner), nichts Neues geladen: der letzte Spieltag bleibt sichtbar (kein "Keine Spiele")
def write_snap(data):
    t = trk / "projection_snapshots.json.tmp"; t.write_text(json.dumps(data)); os.replace(t, snap)
data_ = json.loads(snap.read_text())
for k in keys_today:
    if k in data_["games"]:
        data_["games"][k]["result"] = {"home_points": 100, "away_points": 99, "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "test"}
write_snap(data_)
at_.run()
style = rank_style(at_)
check("alle Spiele beendet, nichts Neues geladen: letzter Tag bleibt sichtbar", cards(at_) and all(h(k) in style for k in keys_today) and not any("Keine Spiele" in m.value for m in at_.markdown), f"{len(cards(at_))} Karten")
check("keine Exception dabei", not at_.exception and not problems(at_), " | ".join(problems(at_))[:200])
before2 = snap_state(); at_.run(); at_.run()
check("letzter Tag bleibt sichtbar: weiteres Rendern, Dateien (Kopien) byteidentisch", snap_state() == before2)

# Neuer Spieltag geladen (morgen): Wechsel, nur noch dessen Spiele
tomorrow = (date.today() + timedelta(days=1)).isoformat()
newp = json.loads(json.dumps(projs[0], default=str))
newp.update(game_date=tomorrow, game_status="scheduled", game_start=(datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), home_team="Boston Celtics", away_team="Miami Heat")
newp["_line_inputs"] = dict(newp.get("_line_inputs") or {}, entry_key="NEUER-TAG-TEST|Boston Celtics|Miami Heat")
at_.session_state["projections"] = list(projs) + [newp]
at_.run()
style = rank_style(at_)
check("neuer Spieltag geladen: Wechsel, nur noch die Karte des neuen Tags", h(newp["_line_inputs"]["entry_key"]) in style and not any(h(k) in style for k in keys_today) and style.count("div:has(> .st-key-sc_game_") == 1, f"{len(cards(at_))} Karten")
check("keine Exception beim Wechsel", not at_.exception and not problems(at_), " | ".join(problems(at_))[:200])

# Liste leer, aber beendete Karten vorhanden: zuletzt gespielter Tag aus dem Schnappschuss; ganz leer: "Keine Spiele"
at_.session_state["projections"] = []
at_.run()
check("Liste leer, beendete Karten vorhanden: zuletzt gespielter Tag, kein 'Keine Spiele'", cards(at_) and not any("Keine Spiele" in m.value for m in at_.markdown) and not at_.exception, f"{len(cards(at_))} Karten")
data_ = json.loads(snap.read_text())
data_["games"] = {}                                   # auch keine Schnappschuesse vergangener Tage (sonst zeigt die Datumsauswahl den letzten Tag)
write_snap(data_)
Path(os.environ["NBAEDGE_UPCOMING_CACHE"]).write_text(json.dumps({"games": []}))      # sonst traegt fill_results_from_upcoming_cache die Ergebnisse wieder ein (Temp-Kopie)
at_.run()
check("Liste ganz leer (keine Spiele, keine beendeten Karten): 'Keine Spiele'", any("Keine Spiele" in m.value and "no-bets" in m.value for m in at_.markdown) and not cards(at_) and not at_.exception, f"{len(cards(at_))} Karten")

# Nur lesen: die echten Dateien sind unveraendert
check("echte Dateien unveraendert (data/tracking, upcoming_cache.json, pregame_lines.json)",
      REAL == {"tracking": tree(ROOT / "data" / "tracking"), "upcoming": sha(ROOT / "data" / "upcoming_cache.json"), "pregame": sha(ROOT / "data" / "pregame_lines.json")})
check("in KEINEM AppTest-Lauf dieser Datei: Streamlit-Exception oder der Satz 'was created with a default value ... Session State API'", not page_checks.bad, "; ".join(page_checks.bad[:2]))
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
