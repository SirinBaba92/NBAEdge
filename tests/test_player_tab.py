"""Tests fuer den Tab "Spieler" Stufe 1 (Prognose-Ansicht): ui/player_view.py, ui/player_tab.py, engine/player_snapshots.py, Einbindung in app.py.
Nur Temp-Ordner (Tracking, Snapshots, Spielverlauf, Kader), kein Netz, keine echten Dateien. Aufruf aus dem Projektordner: venv/bin/python tests/test_player_tab.py"""
import hashlib, json, os, re, sys, tempfile, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_SNAPSHOT_DIR=str(T / "snaps"), NBAEDGE_PLAYER_CACHE_DIR=str(T / "cache"),
                  NBAEDGE_ROSTERS=str(T / "rosters.json"), NBAEDGE_LIVE_DIR=str(T / "live"))
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
from data import day_bets_store as ds
from data import player_history as ph
from data import pre_match_store as ps
from engine import player_snapshots as psn
from ui import player_tab as pt
from ui import player_view as pv

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def real_files():
    files = list((ROOT / "data" / "tracking").glob("*.json")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*")) + list((ROOT / "data" / "cache").glob("*")) + [ROOT / "data" / "rosters.json"]
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()

NOW = time.time()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
FUT, PAST = iso(NOW + 5 * 3600), iso(NOW - 2 * 3600)
D = time.strftime("%Y-%m-%d", time.gmtime(NOW))
K1 = ps.game_key(D, FUT, "Heim Falken", "Gast Baeren")
K2 = ps.game_key(D, PAST, "Zwei Heim", "Zwei Gast")
K3 = ps.game_key("2026-10-20", FUT, "Alt Heim", "Alt Gast")

def line(th, odds): return {"id": f"x{th}", "threshold": th, "odds": odds, "bookmaker": "Betano", "active": True, "updated_at": "2026-10-22T20:00:00+02:00"}
def block(pid, name, team, abbr, lines): return {"id": f"p{pid}", "person_id": pid, "name": name, "team": team, "team_abbreviation": abbr, "mode": "milestones", "active": True, "lines": lines}
def write_entries(entries):
    (T / "tracking").mkdir(parents=True, exist_ok=True)
    (T / "tracking" / "pre_match_entries.json").write_text(json.dumps({"version": 5, "format": "nbaedge-pre-match", "markets": {}, "last_bookmaker": {}, "updated_at": None, "entries": entries}))
entries = {
    K1: {"game_date": D, "markets": {"player_points": {"players": [
        block(1, "Anton Alt", "Heim Falken", "HEI", [line(15, 1.5), line(20, 2.2), line(25, 4.0)]),
        block(2, "Bruno Bank", "Heim Falken", "HEI", [line(8, 1.6)]),
        block(3, "Carl Gast", "Gast Baeren", "GAS", [line(12, 1.9), line(16, 3.0)]),
        block(4, "Dirk Neu", "Gast Baeren", "GAS", [line(10, 2.0)])]}}},
    K2: {"game_date": D, "markets": {"player_points": {"players": [block(1, "Anton Alt", "Zwei Heim", "ZWH", [line(15, 1.5)])]}}},
    K3: {"game_date": "2026-10-20", "markets": {"player_points": {"players": [block(1, "Anton Alt", "Alt Heim", "ALH", [line(15, 1.5)])]}}},
    "ohne": {"game_date": D, "markets": {}}}
write_entries(entries)

# --- Logik
check("Spiele mit Spielerquoten (ohne Eintrag ohne Spieler), nach Tag und Anpfiff sortiert", pt.games_with_players(entries) == [K3, K2, K1] if K2.split("|")[1] < K1.split("|")[1] else True, str(pt.games_with_players(entries)))
check("Tage mit Quoten", pt.days_with_players(entries) == sorted({D, "2026-10-20"}))
check("Standard-Spieltag: heutiger US-Tag, sonst neuester", pt.default_day(["2026-10-20", "2026-10-21"], time.mktime((2026, 10, 25, 12, 0, 0, 0, 0, 0))) == "2026-10-21" and pt.default_day([]) is None)
check("Spiellabel: Gast @ Heim · Wochentag Uhrzeit (Berlin)", re.fullmatch(r"Gast Baeren @ Heim Falken · (Mo|Di|Mi|Do|Fr|Sa|So) \d\d:\d\d", pt.game_label(K1)) is not None, pt.game_label(K1))
check("begonnen: Zukunft nein, Vergangenheit ja", not pt.started(K1) and pt.started(K2))

# --- Tabellenmodell
def pl(pid, name, team, abbr, ok_, minutes, pts, quotes, raw, adj, quality=None, warnings_=None, reason=None):
    p = {"person_id": pid, "name": name, "team": team, "team_abbreviation": abbr, "ok": ok_, "reason": reason, "quality": quality or [], "warnings": warnings_ or [],
         "quotes": [{"milestone": n, "odds": o, "bookmaker": "Betano", "bookmaker_probability": 1 / o, "bookmaker_percent": round(100 / o), "updated_at": "x"} for n, o in quotes]}
    if ok_:
        p.update(minutes={"mean": minutes[0]}, minutes_adjusted=minutes[1], expected_points_raw=pts[0], expected_points_adjusted=pts[1], p_ge_raw={str(k): v for k, v in raw.items()}, p_ge_adjusted={str(k): v for k, v in adj.items()})
    return p
entry = {"game_key": K1, "created_at": "2026-10-23T00:19:41+02:00", "created_after_start": False, "note": "vor Anpfiff erstellt", "history": "Spielverlauf: x", "teams": {
    "Heim Falken": {"matched": True, "player_sum": 144.1, "team_points": 115.0, "factor": 0.85, "note": ""}, "Gast Baeren": {"matched": False, "note": "kein Teamabgleich"}},
    "players": [
    pl(1, "Anton Alt", "Heim Falken", "HEI", True, (34.0, 30.0), (26.0, 22.0), [(15, 1.5), (20, 2.2), (25, 4.0)], {15: .85, 20: .60, 25: .35}, {15: .85, 20: .50, 25: .15}, ["Rollenwechsel"], ["Minuten der letzten 5 weichen ab"]),
    pl(2, "Bruno Bank", "Heim Falken", "HEI", True, (15.0, 12.0), (6.0, 5.0), [(8, 1.6)], {8: .40}, {8: .66}),
    pl(3, "Carl Gast", "Gast Baeren", "GAS", True, (28.0, 28.0), (14.0, 14.0), [(12, 1.9), (16, 3.0)], {12: .60, 16: .35}, {12: .60, 16: .35}),
    pl(4, "Dirk Neu", "Gast Baeren", "GAS", False, None, None, [(10, 2.0)], {}, {}, ["kein Verlauf"], reason="kein Verlauf (keine Spiele vor dem Stichtag)")]}
m = pv.build_table_model(entry, "team", "team")
names = [p["name"] for p in m["players"]]
check("Sortierung 'Team, dann Minuten': Teams alphabetisch (Baeren: Carl vor Dirk ohne Prognose; Falken: Anton 30 vor Bruno 12)", names == ["Carl Gast", "Dirk Neu", "Anton Alt", "Bruno Bank"], str(names))
P = {p["name"]: p for p in m["players"]}
anton = P["Anton Alt"]
check("Teamabgleich: Minuten und Punkte aus den angepassten Werten", anton["minutes"] == 30.0 and anton["points"] == 22.0)
r20 = next(r for r in anton["rows"] if r["n"] == 20)
check("Zeile: Quote, Buchmacher-Chance (1/2,2 = 45 %), Modell (50 %), Differenz aus ungerundeten Werten", r20["odds"] == 2.2 and r20["buch_pct"] == 45 and r20["model_pct"] == 50 and abs(r20["diff"] - (0.5 - 1 / 2.2) * 100) < 1e-9)
mraw = {p["name"]: p for p in pv.build_table_model(entry, "raw", "team")["players"]}["Anton Alt"]
check("Umschalter roh: Minuten 34, Punkte 26, Modell 60 % bei 20+", mraw["minutes"] == 34.0 and mraw["points"] == 26.0 and next(r for r in mraw["rows"] if r["n"] == 20)["model_pct"] == 60)
marks = {(p["name"], r["n"]): r["mark"] for p in m["players"] for r in p["rows"]}
check("Markierung: ◀ ab +5 PP (Anton 15+: +18), keine bei +4,5 (Anton 20+) und +3,5 (Bruno 8+), ▼ ab -5 PP (Anton 25+: -10), Grenze exakt 5,0", marks[("Anton Alt", 15)] == "◀" and marks[("Anton Alt", 25)] == "▼" and marks[("Anton Alt", 20)] == "" and marks[("Bruno Bank", 8)] == ""
      and pv.mark_for(5.0) == "◀" and pv.mark_for(4.99) == "" and pv.mark_for(-5.0) == "▼" and pv.mark_for(None) == "")
big = {**entry, "players": [pl(9, "Hoch", "Heim Falken", "HEI", True, (30, 30), (20, 20), [(10, 2.0)], {10: .70}, {10: .70})]}
check("Modell 70 % gegen 50 % = +20 PP -> ◀", pv.build_table_model(big)["players"][0]["rows"][0]["mark"] == "◀")
check("Spieler ohne Prognose: keine Minuten/Punkte/Modell, Buchmacher bleibt, Tooltip nennt den Grund", (lambda d: d["minutes"] is None and d["rows"][0]["model_pct"] is None and d["rows"][0]["buch_pct"] == 50 and "Keine Prognose" in d["tooltip"] and "kein Verlauf" in d["tooltip"])(P["Dirk Neu"]))
check("Tooltip: Datenqualitaet und Hinweise; ohne Hinweis leer", "Rollenwechsel" in anton["tooltip"] and "weichen ab" in anton["tooltip"] and P["Carl Gast"]["tooltip"] == "")
by_min = [p["name"] for p in pv.build_table_model(entry, "team", "minutes")["players"]]
check("Sortierung nach Minuten (absteigend, ohne Prognose zuletzt)", by_min == ["Anton Alt", "Carl Gast", "Bruno Bank", "Dirk Neu"], str(by_min))
by_diff = [p["name"] for p in pv.build_table_model(entry, "team", "diff")["players"]]
check("Sortierung nach groesster Differenz (Betrag)", by_diff[0] == "Anton Alt" and by_diff[-1] == "Dirk Neu", str(by_diff))
H = pv.render_table_html(m)
check("HTML: Spaltenkoepfe, UNGEPRUEFT am Modell, Zahlen im deutschen Format (Komma, echtes Minus), Markierungen, Symbol mit Tooltip", "Meilenstein" in H and "ungeprüft" in H and "22,0" in H and "−" in H and "<span class='pl-m'>▼</span>" in H and "class='pl-q' title='" in H and "Rollenwechsel" in H)
check("HTML: Spieler ohne Prognose mit Strich, Meilenstein-Zeilen 15+/20+/25+", H.count("<tbody") == 4 and "15+" in H and "25+" in H and "–" in H)
check("Farben (Regel 3): kein Gruen/Rot im Stylesheet der Tabelle", not any(c in pv.PLAYER_CSS for c in ("#22c55e", "#ef4444", "#86efac", "#fca5a5", "green", "red")))
lines = pv.team_lines(entry)
check("Teamabgleich-Zeilen aus dem Snapshot (Faktor 0,85; anderes Team 'kein Teamabgleich')", lines[0].startswith("Heim Falken: Spieler-Summe 144,1 → Teampunkte 115,0, Faktor 0,85") and lines[1] == "Gast Baeren: kein Teamabgleich")

# --- Tab im Harness (AppTest)
HARNESS = str(ROOT / "tests" / "_harness_player_tab.py")
def run():
    at = AppTest.from_file(HARNESS, default_timeout=60).run()
    return at.selectbox(key="pl_day").set_value(D).run()
at = run()
check("Tab ohne Snapshot: Ueberschrift, UNGEPRUEFT-Hinweis, Spieltag- und Spielauswahl, keine Exception", "## 🏃 Spieler" in " ".join(x.value for x in at.markdown) and any("UNGEPRÜFT" in x.value for x in at.markdown)
      and len(at.selectbox) == 2 and not at.exception, " | ".join(problems(at))[:200])
check("kein Snapshot: Hinweis und Knopf 'Prognose jetzt erstellen'", any("keinen Prognose-Snapshot" in w.value for w in at.info) and [b.label for b in at.button] == ["Prognose jetzt erstellen"])
sel_game = at.selectbox(key=f"pl_game_{D}")
check("Spiele des Tages in der Auswahl (K2 begonnen, K1 offen), Tag-Auswahl mit beiden Tagen", len(sel_game.options) == 2 and any("Zwei Gast @ Zwei Heim" in o for o in sel_game.options) and len(at.selectbox(key="pl_day").options) == 2)

# Cache und Kader fuer das Erstellen: Anton hat Verlauf, die anderen nicht
def grow(pid, name, n=30):
    return [{"game_id": f"g{pid}-{i}", "date": f"2026-0{1 + i // 28}-{1 + i % 28:02d}", "season": "2025-26", "person_id": pid, "name": name, "team": "HEI", "opponent": "X", "home": True, "minutes": 32.0, "points": 20 + i % 5, "fga": 15, "fgm": 8,
             "fta": 4, "ftm": 3, "fg3a": 5, "fg3m": 2, "fouls": 2, "plus_minus": 1, "win": True, "margin": 4, "source": "league"} for i in range(n)]
ph.atomic_write_json(ph.season_path("2025-26"), {"version": 1, "format": "nbaedge-player-games", "season": "2025-26", "fetched_at": "x", "source": "t", "rows": grow(1, "Anton Alt")})
ph.atomic_write_json(ph.season_path("2026-27"), {"version": 1, "format": "nbaedge-player-games", "season": "2026-27", "fetched_at": "x", "source": "t", "rows": []})
at = run()
at.selectbox(key=f"pl_game_{D}").set_value(K1).run()
at.button[0].click().run()
snap_file = T / "snaps" / f"{D}.json"
saved = json.loads(snap_file.read_text()) if snap_file.exists() else {}
check("'Prognose jetzt erstellen': Snapshot geschrieben (K1), danach Tabelle statt Knopf, keine Exception", K1 in saved.get("games", {}) and not [b for b in at.button if b.label == "Prognose jetzt erstellen"] and not at.exception, str(list(saved.get("games", {}))))
H2 = " ".join(x.value for x in at.markdown)
check("Tabelle im Tab: Spieler und Meilensteine, 'vor Anpfiff erstellt'-Hinweis (nicht als Warnung)", "Anton Alt" in H2 and "15+" in H2 and "vor dem Anpfiff erstellt" in H2 and "nach dem Anpfiff erstellt" not in H2)
check("Umschalter Modell (Teamabgleich/roh) und Sortierung vorhanden", at.radio(key="pl_mode").options == ["Teamabgleich", "roh"] and at.radio(key="pl_sort").options == ["Team, dann Minuten", "Minuten", "größte Differenz"])
at.radio(key="pl_mode").set_value("raw").run(); at.radio(key="pl_sort").set_value("diff").run()
check("Umschalten und Sortieren: keine Exception, Tabelle bleibt", not at.exception and "Anton Alt" in " ".join(x.value for x in at.markdown), " | ".join(problems(at))[:200])
check("zweites Erstellen schreibt nicht ueber den vorhandenen Snapshot", psn.create_for_game(K1, entries)[0] == "vorhanden")
# begonnenes Spiel: Snapshot nach Anpfiff
at = run()
at.selectbox(key=f"pl_game_{D}").set_value(K2).run()
check("begonnenes Spiel ohne Snapshot: Hinweis auf eingeschraenkte Aussagekraft", any("bereits begonnen" in w.value for w in at.info))
at.button[0].click().run()
H3 = " ".join(x.value for x in at.markdown)
check("nach Anpfiff erstellt: Warnhinweis 'Daten nur bis Vortag', created_after_start gespeichert", "nach dem Anpfiff erstellt" in H3 and json.loads(snap_file.read_text())["games"][K2]["created_after_start"] is True)
check("Seite ohne Warnung/Exception (Streamlit-Satz zu Standardwerten eingeschlossen)", not at.exception and not [w for w in at.warning if "default value" in w.value] and not page_checks.bad, str(page_checks.bad)[:200])

# --- Einbindung in app.py: Tab steht hinter dem Live Bet Tracker, bestehende Tabs unveraendert
src = (ROOT / "app.py").read_text()
check("app.py: Tab '🏃 Spieler' nach '🎯 Live Bet Tracker', Aufruf render_player_tab()", src.index('"🎯 Live Bet Tracker"') < src.index('"🏃 Spieler"') < src.index('"📰 Lineup News"') and "render_player_tab()" in src)

check("echte Dateien (Tracking, Snapshots, Cache, Kader) unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
