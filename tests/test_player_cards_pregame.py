"""Test: anklickbare Spielerkarten VOR dem Anpfiff (ui/bet_cards_component.render_bet_cards, Komponente ui/components/bet_cards/index.html). Der Spielstatus ist fest vorgegeben
(Anpfiff in 5 Stunden = noch nicht begonnen; zum Vergleich ein Spiel vor 2 Stunden = begonnen). AppTest zeigt den HTML-Inhalt der Komponente als Argument 'html' (und 'css').
Geprueft werden die Regeln aus DESIGN_REGELN.md Regel 94 auf genau diesem Weg: orange = Modell roh, kein dritter Balken, kein "vorher", kein Kasten "Ausfaelle wirken", Abstand Roh minus Betano,
gelber Hinweis unter 10 Spielen, gruenes Zeichen und Mindestquote nur bei Startern mit mindestens 10 Spielen ab 80 % Roh-Chance. Nur Temp-Ordner, kein Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_player_cards_pregame.py"""
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
from data import absences_store as ab
from data import bet_categories as bc
from data import live_feed as lf
from data import pre_match_store as ps
from engine import player_forecast as pf
from engine import player_snapshots as psn
from ui import bet_cards_component as bcc
from ui import player_tab as pt

class _NoNet:
    class R:
        status_code = 200
        def json(self): return {"scoreboard": {"gameDate": "2026-10-22", "games": []}}
    def get(self, url, **kw): return self.R()
lf._feed = lf.LiveFeed(http_get=_NoNet().get)

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*.json")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*")) + list((ROOT / "data" / "cache").glob("*")) + [ROOT / "data" / "rosters.json"]
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()

# ---------------------------------------------------------------- Spielstatus fest vorgeben
NOW = time.time()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
D = time.strftime("%Y-%m-%d", time.gmtime(NOW))
KEY = ps.game_key(D, iso(NOW + 5 * 3600), "Heim Falken", "Gast Baeren")        # noch nicht begonnen
KEY_STARTED = ps.game_key(D, iso(NOW - 2 * 3600), "Zwei Heim", "Zwei Gast")     # begonnen
check("Spielstatus: Anpfiff in 5 Std. = nicht begonnen und auswaehlbar (Komponente), Anpfiff vor 2 Std. = begonnen, nicht auswaehlbar", not pt.started(KEY) and pt.started(KEY_STARTED) and bcc.is_selectable(KEY, NOW) and not bcc.is_selectable(KEY_STARTED, NOW))

RAW = {20: 0.85, 24: 0.80, 25: 0.79, 30: 0.30}
ADJ = {20: 0.70, 24: 0.66, 25: 0.65, 30: 0.20}
def snap_player(pid, name, base, games, abbr="HEI", team="Heim Falken"):
    quotes = [{"milestone": n, "odds": 1.30, "bookmaker": "Betano", "bookmaker_probability": 1 / 1.30, "bookmaker_percent": 77, "updated_at": "2026-10-22T20:00:00+02:00"} for n in RAW]
    return {"person_id": pid, "name": name, "team": team, "team_abbreviation": abbr, "ok": True, "reason": None, "quality": [], "warnings": [], "quotes": quotes,
            "minutes": {"base": base, "mean": base, "role": pf.role_for_minutes(base)}, "minutes_adjusted": base, "expected_points_raw": 25.0, "expected_points_adjusted": 23.0,   # Standardfenster +-5 um 25 Punkte: 20+ bis 30+ sichtbar
            "p_ge_raw": {str(k): v for k, v in RAW.items()}, "p_ge_adjusted": {str(k): v for k, v in ADJ.items()}, "games_used": {"2025-26": games}}
PLAYERS = [snap_player(1, "Starter Zwoelf", 33.0, 12), snap_player(2, "Starter Neun", 33.0, 9), snap_player(3, "Rotation Zwanzig", 24.0, 20), snap_player(4, "Starter Zehn", 33.0, 10, "GAS", "Gast Baeren")]
(T / "snaps").mkdir(parents=True, exist_ok=True)
entry = {"game_key": KEY, "created_at": "2026-10-29T12:00:00+01:00", "start_utc": KEY.split("|")[1], "created_after_start": False, "note": "vor Anpfiff erstellt", "model_version": pf.PLAYER_MODEL_VERSION,
         "status": pf.UNVERIFIED, "context": {}, "teams": {}, "history": "", "players": PLAYERS}
check("Snapshot (Test) gespeichert", psn.save_snapshot(D, KEY, entry) == "geschrieben")
def line(th, odds): return {"id": f"x{th}", "threshold": th, "odds": odds, "bookmaker": "Betano", "active": True, "updated_at": "2026-10-22T20:00:00+02:00"}
def block(p): return {"id": f"p{p['person_id']}", "person_id": p["person_id"], "name": p["name"], "team": p["team"], "team_abbreviation": p["team_abbreviation"], "mode": "milestones", "active": True, "lines": [line(n, 1.30) for n in RAW]}
(T / "tracking").mkdir(parents=True, exist_ok=True)
(T / "tracking" / "pre_match_entries.json").write_text(json.dumps({"version": 5, "format": "nbaedge-pre-match", "markets": {}, "last_bookmaker": {}, "updated_at": None, "entries": {
    KEY: {"game_date": D, "markets": {"player_points": {"players": [block(p) for p in PLAYERS]}}},
    KEY_STARTED: {"game_date": D, "markets": {"player_points": {"players": [block(PLAYERS[0])]}}}}}))
ab.set_absences(KEY, [{"person_id": 99, "name": "Fehlt Fritz", "team": "Heim Falken"}], [], now=NOW)

# ---------------------------------------------------------------- Tab rendern (AppTest), Komponente abfangen
HARNESS = str(ROOT / "tests" / "_harness_player_tab.py")
at = AppTest.from_file(HARNESS, default_timeout=90).run()
at = at.selectbox(key="pl_day").set_value(D).run()
at = at.selectbox(key=f"pl_game_{D}").set_value(KEY).run()
comps = at.get("component_instance")
check("nicht begonnenes Spiel: anklickbare Karten-Komponente wird gezeichnet (eine), keine Exception", len(comps) == 1 and not at.exception, " | ".join(problems(at))[:200])
args = json.loads(comps[0].proto.json_args)
H, CSS = args["html"], args["css"]
check("Komponente bekommt Spielschluessel, Karten-HTML und Karten-CSS", args["game_key"] == KEY and "pl-cards" in H and "pl-c-few" in CSS and "pl-c-ok" in CSS)
cards = {c.split("pl-c-name'>")[1].split("<")[0].strip(): c for c in re.findall(r"<div class='pl-card'>.*?(?=<div class='pl-card'>|</div><div class='pl-c-legend'>)", H, flags=re.S)}
row = lambda name, n: next(x for x in cards[name].split("<div class='pl-c-row") if f"<b>{n}+" in x)
check("vier Karten, Zeilen anklickbar (data-pid)", len(cards) == 4 and all("data-pid=" in c for c in cards.values()))

# Regel 1: orange = roh, Abstand roh minus Betano, nichts Entfallenes
r20 = row("Starter Zwoelf", 20)
check("orange = Modell roh (85 %), nicht Teamabgleich (70 %); data-model = 85", "Modell</span> <b>85 %</b>" in r20 and "width:85%" in r20 and "70 %" not in r20 and "data-model='85'" in r20, r20[:300])
check("Abstand = Roh minus Betano (+8,1 PP)", ">+8,1<" in r20)
check("kein dritter Balken, kein 'vorher', kein Kasten 'Ausfaelle wirken', kein 'Teamabgleich'-Text in den Karten", not any(w in H for w in ("pl-c-bar-o", "pl-c-wo", "vorher", "Ausfälle wirken", "pl-card-aff", "Teamabgleich")))
mk = " ".join(x.value for x in at.markdown)
check("Ausfall-Kasten ueber den Karten bleibt (Fehlt Fritz), 'Ausfaelle wirken' nirgends, kein Knopf 'neu rechnen'", "Ausfälle für dieses Spiel" in mk and "Fehlt Fritz" in mk and "Ausfälle wirken" not in mk and not [b for b in at.button if "neu rechnen" in b.label])
check("Umschalter 'Modell' in der Kartenansicht nicht vorhanden; Kategorie des Wettscheins vorbelegt mit 'roh'", "pl_mode" not in [r.key for r in at.radio]
      and at.multiselect(key=f"bc_cat_{KEY}_raw").value == [bc.default_player_category("raw")])
# Regel 3: Hinweis unter 10 Spielen
check("9 Spiele: gelber Hinweis 'nur 9 Spiele, Chance vermutlich zu hoch', Prozentzahlen bleiben", "nur 9 Spiele, Chance vermutlich zu hoch" in cards["Starter Neun"] and "Modell</span> <b>85 %</b>" in cards["Starter Neun"])
check("10 und mehr Spiele: kein Hinweis", all("pl-c-few'" not in cards[n] for n in ("Starter Zehn", "Starter Zwoelf", "Rotation Zwanzig")))
# Regel 4: Zeichen und Mindestquote
tick = lambda name, n: "pl-c-ok'" in row(name, n)
check("Starter mit 12 Spielen: '20+ ✓' und 'Mindestquote 1,22' (85 %), 24+ (80 %) mit 'Mindestquote 1,30', 25+ (79 %) und 30+ ohne", tick("Starter Zwoelf", 20) and "Mindestquote 1,22" in r20 and tick("Starter Zwoelf", 24) and "Mindestquote 1,30" in row("Starter Zwoelf", 24)
      and not tick("Starter Zwoelf", 25) and not tick("Starter Zwoelf", 30) and "Mindestquote" not in row("Starter Zwoelf", 25))
check("genau 10 Spiele: Zeichen; 9 Spiele, Rotation: kein Zeichen, keine Mindestquote", tick("Starter Zehn", 20) and not any(tick("Starter Neun", n) for n in RAW) and not any(tick("Rotation Zwanzig", n) for n in RAW) and "Mindestquote" not in cards["Starter Neun"] + cards["Rotation Zwanzig"])
# Komponente: Zeilenraster fuer Checkbox + Mindestquote, kein eigenes Gruen/Rot fuer die neuen Zeichen, nutzt die Anzeige aus player_view
comp = (ROOT / "ui" / "components" / "bet_cards" / "index.html").read_text(encoding="utf-8")
check("Komponente zeichnet nur args.html/args.css (keine eigene Modell-, Hinweis- oder Mindestquoten-Anzeige)", "args.html" in comp and "args.css" in comp and not any(w in comp for w in ("Mindestquote", "vermutlich", "pl-c-few", "pl-c-ok", "pl-c-bar-o")))
check("Komponenten-Raster: Checkbox 28 px, Stufe 84 px, Mitte, Abstand 96 px (die Mindestquote bricht in der Stufenspalte um)", "grid-template-columns:28px 84px 1fr 96px" in comp)

# begonnenes Spiel: einfacher Pfad (kein Komponenten-Aufruf), gleiche Regeln
at2 = at.selectbox(key=f"pl_game_{D}").set_value(KEY_STARTED).run()
check("begonnenes Spiel: keine Komponente, Karten als normales HTML, keine Exception", len(at2.get("component_instance")) == 0 and "pl-cards" in " ".join(x.value for x in at2.markdown) and not at2.exception, " | ".join(problems(at2))[:200])
check("echte Dateien (Tracking, Snapshots, Cache, Kader) unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
