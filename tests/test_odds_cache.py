"""Tests: Odds-API-Zwischenspeicher, Credit-Schutz, Protokoll, Live-Tab, BallDontLie-Cache.
Alles offline (tests/fake_net.py, jede andere URL bricht ab); Caches/Logs liegen in Temp-Verzeichnissen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_odds_cache.py"""
import copy, hashlib, json, os, re, sys, threading, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env, scoreboard_game, SECRET
fake_net.install()
import config.settings as settings
import data.odds_client as oc
import data.fetcher as fetcher
import data.nba_live as nl
from models.elo import MODEL_PATH
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
REAL_FILES = ("odds_cache.json", "odds_calls.log", "upcoming_cache.json", "pregame_lines.json")
real_before = {f: ((ROOT / 'data' / f).stat().st_mtime_ns, (ROOT / 'data' / f).stat().st_size) if (ROOT / 'data' / f).exists() else None for f in REAL_FILES}
n_odds = lambda: len(state["odds_calls"])
def restart():                       # wie App-Neustart: Arbeitsspeicher leer, Dateien bleiben
    oc._mem.update(path=None, mtime=None, obj=None)
    import data.live_market as lm; lm._CACHE.update(fetched_at=0.0, lines={})
    nl._cache.clear()
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def sidebar_text(at):
    return " | ".join([m.value for m in at.sidebar.markdown] + [c.value for c in at.sidebar.caption] + [w.value for w in at.sidebar.warning])
def btn(at, label):
    b = [b for b in at.button if label in b.label]; return b[0] if b else None
def age_cache(tmp, seconds):
    p = Path(os.environ["NBAEDGE_ODDS_CACHE"]); d = json.loads(p.read_text())
    for e in d["entries"].values(): e["fetched_at"] -= seconds
    p.write_text(json.dumps(d))
def projs(at): return [(p["home_team"], p["exp_spread"], p["exp_total"], p["home_score"], p["away_score"]) for p in sorted(at.session_state["projections"], key=lambda x: -abs(x["exp_spread"]))]

# =============================================================== A) Einheiten: odds_client
tmp = fresh_env()
r = oc.get_odds("totals_spreads", caller="test:start")
check("kein Cache: erster Aufruf fragt genau einmal ab, Daten + Credits gespeichert", n_odds() == 1 and r.fetched and r.data and r.remaining == 448, f"{n_odds()} Abruf, {r.remaining} Credits")
r = oc.get_odds("totals_spreads", caller="test:rerun")
check("zweiter Aufruf aus dem Cache (kein Abruf)", n_odds() == 1 and r.from_cache and not r.fetched)
restart(); r = oc.get_odds("totals_spreads", caller="test:neustart")
check("nach Neustart (Arbeitsspeicher leer) weiter aus Datei-Cache", n_odds() == 1 and r.from_cache)
age_cache(tmp, 3600); restart(); r = oc.get_odds("totals_spreads", caller="test:alt")
check("abgelaufener Cache (60 Min.) loest KEINEN Abruf aus, ist als veraltet markiert", n_odds() == 1 and r.stale and 3590 < r.age < 3700 and oc.describe_age(r.age) == "vor 1 Std.", oc.describe_age(r.age))
for _ in range(10): oc.get_odds("totals_spreads", caller="test:loop")
check("10 weitere Aufrufe: 0 zusaetzliche Abrufe", n_odds() == 1)
r = oc.get_odds("totals_spreads", caller="test:knopf", refresh=True)
check("refresh=True (Knopf): genau 1 Abruf, Cache wieder frisch", n_odds() == 2 and r.fetched and not r.stale and r.remaining == 444)
oc.get_odds("h2h", caller="test:h2h")
check("h2h hat einen eigenen Cache-Eintrag (1 Abruf, 2 Credits)", n_odds() == 3 and state["odds_calls"][-1]["markets"] == "h2h" and oc.credits_info()["remaining"] == 442)
r = oc.get_odds("totals_spreads", caller="test:cacheonly", cache_only=True)
check("cache_only: nie ein Abruf", n_odds() == 3 and r.data)

# Protokoll
log = Path(os.environ["NBAEDGE_ODDS_LOG"]).read_text().splitlines()
check("Protokoll: je tatsaechlichem Abruf eine Zeile (Zeit, Aufrufer, Markt, Regionen, Credits)", len(log) == 3 and all(re.search(r"^\d{4}-\d\d-\d\dT.*\| caller=test:\w+ \| kind=\w+ \| markets=\S+ \| regions=us,eu \| status=200 \| remaining=\d+ \| cost=\d", l) for l in log), log[0])
check("Protokoll nennt Kosten 4 bzw. 2 Credits", "cost=4" in log[0] and "cost=2" in log[2], f"{log[0][-40:]} / {log[2][-40:]}")
blob = "".join(p.read_text() for p in Path(tmp).glob("*") if p.is_file())
check("kein API-Key, keine URL und kein apiKey in Cache oder Log", SECRET not in blob and "apiKey" not in blob and "http" not in "".join(log))

# Reserve
tmp = fresh_env(remaining=40)
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {}, "credits": {"remaining": 40, "updated_at": time.time()}, "last_error": {}}))
restart(); r = oc.get_odds("totals_spreads", caller="test:reserve")
check("unter der Reserve (40 < 50): kein automatischer Abruf, blocked='reserve'", n_odds() == 0 and r.blocked == "reserve" and r.low_credits)
r = oc.get_odds("totals_spreads", caller="test:auto", max_age=300)
check("unter der Reserve: auch der Live-Auto-Refresh ist gesperrt", n_odds() == 0 and r.blocked == "reserve")
r = oc.get_odds("totals_spreads", caller="test:manuell", refresh=True)
check("unter der Reserve: manueller Abruf geht (mit low_credits-Warnung)", n_odds() == 1 and r.fetched and r.low_credits and r.remaining == 36)

# Fehler: kein Key in Meldungen, Backoff
tmp = fresh_env(odds_status=401)
r = oc.get_odds("totals_spreads", caller="test:fehler")
check("Fehler 401: Meldung ohne Key/URL, kein Cache", n_odds() == 1 and r.error and SECRET not in r.error and "http" not in r.error and r.data is None, r.error)
for _ in range(10): oc.get_odds("totals_spreads", caller="test:fehler-loop")
check("nach dem Fehler: 5 Min. Backoff, keine Wiederholung bei 10 Aufrufen", n_odds() == 1)
r = oc.get_odds("totals_spreads", caller="test:knopf-fehler", refresh=True)
check("manueller Abruf umgeht den Backoff", n_odds() == 2)
blob = "".join(p.read_text() for p in Path(tmp).glob("*") if p.is_file())
check("Fehlerfall: weder Key noch apiKey in Cache/Log", SECRET not in blob and "apiKey" not in blob and "status=401" in blob)
orig = fake_net.requests.get
def boom(url, **k): raise fake_net.requests.exceptions.ConnectionError(f"Max retries for url: {url}?apiKey={SECRET}")
tmp = fresh_env(); fake_net.requests.get = boom
r = oc.get_odds("totals_spreads", caller="test:netz")
fake_net.requests.get = orig; fake_net.install()
blob = "".join(p.read_text() for p in Path(tmp).glob("*") if p.is_file())
check("Netzwerkfehler mit Key in der Exception: Key erscheint nirgends (Meldung, Cache, Log)", r.error and SECRET not in r.error and SECRET not in blob and "ConnectionError" in blob, r.error)

# Parallel
tmp = fresh_env(); ts = [threading.Thread(target=lambda: oc.get_odds("totals_spreads", caller="test:thread")) for _ in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
check("6 gleichzeitige Sitzungen ohne Cache: nur 1 Abruf", n_odds() == 1)

# Nur odds_client ruft die Odds API auf
hits = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py") if "venv" not in p.parts and "tests" not in p.parts and "analysis" not in p.parts and "the-odds-api.com" in p.read_text()]
check("die Odds API wird nur in data/odds_client.py aufgerufen", hits == ["data/odds_client.py"], str(hits))

# =============================================================== B) BallDontLie: 10 Minuten
tmp = fresh_env(); _orig_sleep = time.sleep; fetcher.time.sleep = lambda *_: None   # nur fuer diesen Abschnitt
g1 = fetcher.fetch_upcoming_games(); g2 = fetcher.fetch_upcoming_games(); g3 = fetcher.fetch_upcoming_games()
check("BallDontLie: 3 Aufrufe -> 1 Abruf (10-Min.-Cache)", state["bdl_calls"] == 1 and len(g1) == len(g2) == len(g3) == 3)
pth = Path(os.environ["NBAEDGE_UPCOMING_CACHE"]); d = json.loads(pth.read_text()); d["fetched_at"] -= 601; pth.write_text(json.dumps(d))
fetcher.fetch_upcoming_games()
check("nach 10 Min. wieder genau 1 neuer Abruf", state["bdl_calls"] == 2)
d = json.loads(pth.read_text()); d["fetched_at"] -= 601; pth.write_text(json.dumps(d)); state["bdl_status"] = 429
g = fetcher.fetch_upcoming_games()
check("Rate-Limit (429) bei abgelaufenem Cache: es wird der alte Cache genutzt, kein Fehler", len(g) == 3)
state["bdl_status"] = 200
time.sleep = _orig_sleep

# =============================================================== C) App (AppTest)
def run_scenarios(flag):
    settings.SHOW_VALUE_BETS = flag
    per = 2 if flag else 1
    tag = f"[SHOW_VALUE_BETS={flag}] "
    tmp = fresh_env(); restart()
    a1 = app().run()
    check(tag + "erster Start ohne Cache: keine Exception, hoechstens 1 Abruf je Markt", not a1.exception and n_odds() == per, f"{n_odds()} Abrufe: {[c['markets'] for c in state['odds_calls']]}")
    check(tag + "BallDontLie: 1 Abruf beim Start", state["bdl_calls"] == 1)
    first = projs(a1)
    check(tag + "Sidebar zeigt 'Odds API: noch X Credits' und das Quoten-Alter", re.search(r"Odds API: noch \d+ Credits", sidebar_text(a1)) and "Quoten von vor" in sidebar_text(a1), sidebar_text(a1)[:140])
    restart(); a2 = app().run()
    check(tag + "zweiter Start mit vorhandenem Cache: 0 zusaetzliche Odds-Abrufe, 0 BallDontLie-Abrufe", n_odds() == per and state["bdl_calls"] == 1)
    check(tag + "Projektionen mit Cache == Projektionen vom frischen Abruf (Knicks, Spurs, Pistons)", projs(a2) == first and len(first) == 3, str(first))
    for _ in range(10): a2.run()
    check(tag + "10 Reruns innerhalb der TTL: 0 zusaetzliche Abrufe", n_odds() == per and not a2.exception)
    c_before = n_odds(); btn(a2, "Refresh Odds").click().run()
    check(tag + "Knopf 'Refresh Odds': genau 1 Abruf je Markt", n_odds() == c_before + per and not a2.exception, f"+{n_odds() - c_before}")
    check(tag + "Projektionen nach dem Knopf unveraendert", projs(a2) == first)
    check(tag + "Credits in der Sidebar aktualisiert", f"noch {state['remaining']} Credits" in sidebar_text(a2), str(state["remaining"]))
    # abgelaufener Cache beim Start
    age_cache(tmp, 45 * 60); restart(); c_before = n_odds(); a3 = app().run()
    txt = sidebar_text(a3)
    check(tag + "abgelaufener Cache (45 Min.) beim Start: 0 Abrufe, Hinweis mit Alter", n_odds() == c_before and "Quoten von vor 45 Min." in txt and "älter als 20 Min." in txt, txt[:160])
    check(tag + "Projektionen mit abgelaufenem Cache unveraendert", projs(a3) == first)
    # Live-Tab ohne laufendes Spiel
    state["scoreboard"] = [scoreboard_game("0022600002", "Philadelphia 76ers", "New York Knicks", 0, "7:00 pm ET")]
    nl._cache.clear(); restart(); c_before = n_odds(); a4 = app().run()
    for _ in range(5): a4.run()
    live_btn = btn(a4, "Live-Linien aktualisieren")
    check(tag + "Live-Tab ohne laufendes Spiel: 0 Abrufe, Knopf gesperrt, Hinweis sichtbar", n_odds() == c_before and live_btn is not None and live_btn.disabled and any("Kein laufendes Spiel" in c.value for c in a4.caption), f"+{n_odds() - c_before}")
    # mit laufendem Spiel
    state["scoreboard"] = [scoreboard_game("0022600001", "Boston Celtics", "Detroit Pistons", 2, "Q2 5:30", "PT05M30.00S", 50, 48)]
    nl._cache.clear(); restart(); c_before = n_odds(); a5 = app().run()
    for _ in range(5): a5.run()
    check(tag + "laufendes Spiel gewaehlt, Auto-Refresh aus: 6 Laeufe, 0 Abrufe", n_odds() == c_before and not a5.exception and btn(a5, "Live-Linien aktualisieren") is not None and not btn(a5, "Live-Linien aktualisieren").disabled)
    check(tag + "Auto-Refresh steht standardmaessig auf AUS", [t for t in a5.toggle if "Auto-Refresh" in t.label][0].value is False)
    btn(a5, "Live-Linien aktualisieren").click().run()
    check(tag + "Knopf 'Live-Linien aktualisieren': genau 1 Abruf (Totals/Spreads, 4 Credits)", n_odds() == c_before + 1 and state["odds_calls"][-1]["markets"] == "totals,spreads", f"+{n_odds() - c_before}")
    # Auto-Refresh an
    c_before = n_odds(); tog = [t for t in a5.toggle if "Auto-Refresh" in t.label][0]; tog.set_value(True).run()
    check(tag + "Auto-Refresh an, Cache frisch: 0 Abrufe, Credit-Hinweis sichtbar", n_odds() == c_before and any("verbraucht Credits" in c.value for c in a5.caption))
    age_cache(tmp, 10 * 60); a5.run()
    check(tag + "Auto-Refresh an, Cache 10 Min. alt: genau 1 Abruf, danach 0", n_odds() == c_before + 1)
    for _ in range(3): a5.run()
    check(tag + "weitere Reruns innerhalb von 5 Min.: 0 Abrufe", n_odds() == c_before + 1)
    # Reserve
    tmp = fresh_env(remaining=40); restart()
    Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {}, "credits": {"remaining": 40, "updated_at": time.time()}, "last_error": {}}))
    a6 = app().run()
    check(tag + "Cache leer, Credits 40 < Reserve 50: kein automatischer Abruf beim Start, Warnung sichtbar", n_odds() == 0 and not a6.exception and "unter der Reserve" in sidebar_text(a6) and "noch 40 Credits" in sidebar_text(a6), sidebar_text(a6)[:150])
    btn(a6, "Refresh Odds").click().run()
    check(tag + "unter der Reserve: Knopf ruft manuell ab (1 Abruf je Markt), Warnung bleibt", n_odds() == per and "unter der Reserve" in sidebar_text(a6))
    state["scoreboard"] = [scoreboard_game("0022600001", "Boston Celtics", "Detroit Pistons", 2, "Q2 5:30")]
    nl._cache.clear(); age_cache(tmp, 10 * 60); restart(); c_before = n_odds(); a7 = app().run()
    [t for t in a7.toggle if "Auto-Refresh" in t.label][0].set_value(True).run()
    check(tag + "unter der Reserve: Live-Auto-Refresh gesperrt (0 Abrufe), Start ohne Abruf", n_odds() == c_before)
    # Fehlerfall: Key erscheint nicht in der Oberflaeche
    tmp = fresh_env(odds_status=401); restart(); state["scoreboard"] = []
    a8 = app().run()
    for _ in range(10): a8.run()
    ui = " ".join(w.value for w in a8.warning) + " " + sidebar_text(a8)
    check(tag + "Odds-Fehler 401 beim Start: 1 Versuch (Backoff bei 10 Reruns), kein Key in der Oberflaeche", n_odds() == per and SECRET not in ui and not a8.exception, ui[:120])
    state["scoreboard"] = []

run_scenarios(False)
run_scenarios(True)
settings.SHOW_VALUE_BETS = False
check("Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
real_after = {f: ((ROOT / 'data' / f).stat().st_mtime_ns, (ROOT / 'data' / f).stat().st_size) if (ROOT / 'data' / f).exists() else None for f in REAL_FILES}
check("Projekt-data/ unberuehrt: odds_cache.json, odds_calls.log, upcoming_cache.json durch die Tests weder angelegt noch veraendert", real_before == real_after)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
