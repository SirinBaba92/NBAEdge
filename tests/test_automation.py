"""Tests fuer die Automatisierung (nichts wird aktiviert): fetch_odds_daily.py, update_model.py-Protokoll,
automation.log, plist-/Shell-Dateien, Modell-Neuladen und Sidebar-Zeile in der App.
Offline: simulierte Antworten (tests/fake_net.py), Temp-Verzeichnisse, kein launchctl, keine echten Calls.
Aufruf aus dem Projektordner: venv/bin/python tests/test_automation.py"""
import copy, hashlib, json, os, plistlib, re, subprocess, sys, time, warnings
from datetime import datetime, timedelta
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env, SECRET
fake_net.install()
import data.automation_log as alog
import data.odds_client as oc
import fetch_odds_daily as fod
import update_model
import models.elo as elo_mod
from models.elo import EloEngine, MODEL_PATH
from config.settings import ODDS_MIN_CREDITS_RESERVE

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
real_data = {p.name: p.stat().st_mtime_ns for p in (ROOT / "data").glob("*") if p.is_file()}
agents0 = {p.name: p.read_bytes() for p in (Path.home() / "Library" / "LaunchAgents").glob("de.nbaedge*")}   # Zeitplan kann vom Nutzer eingeschaltet sein: Test darf daran nichts aendern
n_odds = lambda: len(state["odds_calls"])
def files_text(tmp): return "".join(p.read_text() for p in Path(tmp).glob("*") if p.is_file() and p.suffix in (".log", ".json"))
def alines(): return Path(os.environ["NBAEDGE_AUTOMATION_LOG"]).read_text().splitlines()
def olines(): return Path(os.environ["NBAEDGE_ODDS_LOG"]).read_text().splitlines() if Path(os.environ["NBAEDGE_ODDS_LOG"]).exists() else []
def restart(): oc._mem.update(path=None, mtime=None, obj=None)
def age_cache(seconds):
    p = Path(os.environ["NBAEDGE_ODDS_CACHE"]); d = json.loads(p.read_text())
    for e in d["entries"].values(): e["fetched_at"] -= seconds
    p.write_text(json.dumps(d)); restart()
sleeps = []
quiet = lambda *_: None

# ============================================================ A) automation_log
tmp = fresh_env()
os.environ["ODDS_API_KEY"] = SECRET
alog.log_event("fetch_odds_daily", "ERROR", f"Fehler bei https://api.the-odds-api.com/v4/sports?apiKey={SECRET}&x=1 und {SECRET} | mit Pipe\nzweite Zeile")
line = alines()[0]
check("log_event: eine Zeile, Format Zeit | job | result | detail", len(alines()) == 1 and re.match(r"^\d{4}-\d\d-\d\dT[\d:+]+ \| job=fetch_odds_daily \| result=ERROR \| detail=", line), line[:90])
check("log_event: keine URL, kein apiKey, kein Key-Wert", SECRET not in line and "http" not in line and "apiKey=" not in line.replace("apiKey=<verborgen>", ""), line[-90:])
for i in range(30): alog.log_event("update_model", "OK", "x" * 190)
p = Path(os.environ["NBAEDGE_AUTOMATION_LOG"]); alog.MAX_BYTES = 3000; alog.KEEP_LINES = 5
alog.log_event("update_model", "OK", "letzte Zeile")
check("Kuerzen: ueber dem Limit nur die letzten Zeilen, neueste bleibt erhalten", p.stat().st_size < 3000 + 300 and alines()[-1].endswith("letzte Zeile") and len(alines()) == 5, f"{p.stat().st_size} Bytes, {len(alines())} Zeilen")
alog.MAX_BYTES, alog.KEEP_LINES = 1_000_000, 500
real_worst = 500 * (30 + 30 + 200 + 40)
check("Original: 1 MB Limit, 500 Zeilen behalten (hoechstens ca. 150 KB)", alog.MAX_BYTES == 1_000_000 and alog.KEEP_LINES == 500 and real_worst < 200_000, str(real_worst))

# ============================================================ B) fetch_odds_daily
def scenario(remaining=452, odds_status=200):
    tmp = fresh_env(remaining=remaining, odds_status=odds_status); sleeps.clear(); return tmp

# Reserve unterschritten
tmp = scenario(remaining=40)
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {}, "credits": {"remaining": 40, "updated_at": time.time()}, "last_error": {}})); restart()
r = fod.run(sleep=sleeps.append, log=quiet)
check("Reserve unterschritten (40 < 50): kein Abruf", n_odds() == 0 and r["result"] == "SKIP")
check("Reserve: automation.log SKIP mit Grund, odds_calls.log mit Eintrag", f"result=SKIP | detail=Credits 40 unter Reserve {ODDS_MIN_CREDITS_RESERVE}" in alines()[-1] and "caller=scheduled" in olines()[-1] and "status=uebersprungen" in olines()[-1] and "Reserve" in olines()[-1], olines()[-1][-70:])
check("Reserve: kein Cache angelegt, kein Key irgendwo", not any(e for e in json.loads(Path(os.environ["NBAEDGE_ODDS_CACHE"]).read_text())["entries"]) and SECRET not in files_text(tmp))

# frischer Cache (10 Min.) und Grenze 60 Min.
tmp = scenario(); oc.get_odds("totals_spreads", caller="manuell", refresh=True); base = n_odds(); age_cache(10 * 60)
r = fod.run(sleep=sleeps.append, log=quiet)
check("frischer Cache (10 Min.): kein Abruf, SKIP im Protokoll", n_odds() == base and r["result"] == "SKIP" and "Cache jünger als 60 Min." in alines()[-1] and "status=uebersprungen" in olines()[-1], alines()[-1][-80:])
age_cache(49 * 60)   # insgesamt 59 Min.
r = fod.run(sleep=sleeps.append, log=quiet)
check("59 Min. alter Cache: weiterhin uebersprungen", n_odds() == base and r["result"] == "SKIP")
age_cache(2 * 60)    # insgesamt 61 Min.
r = fod.run(sleep=sleeps.append, log=quiet)
check("61 Min. alter Cache: genau 1 Abruf, caller=scheduled, Cache wieder frisch", n_odds() == base + 1 and r["result"] == "OK" and "caller=scheduled |" in olines()[-1] and oc.get_odds("totals_spreads", caller="t", cache_only=True).age < 5)

# Erfolg ohne Cache
tmp = scenario(); r = fod.run(sleep=sleeps.append, log=quiet)
check("Erfolg: genau 1 Abruf (Totals/Spreads, 4 Credits), Cache gefuellt", n_odds() == 1 and state["odds_calls"][0]["markets"] == "totals,spreads" and r["result"] == "OK" and r["remaining"] == 448 and not sleeps)
check("Erfolg: odds_calls.log (Aufrufer scheduled, Markt, Regionen, Credits) und automation.log OK", "caller=scheduled | kind=totals_spreads | markets=totals,spreads | regions=us,eu | status=200 | remaining=448 | cost=4" in olines()[-1] and "result=OK | detail=3 Spiele, noch 448 Credits" in alines()[-1], alines()[-1][-60:])
check("Erfolg: kein Key in Cache, odds_calls.log, automation.log", SECRET not in files_text(tmp) and "apiKey" not in files_text(tmp))

# Fehler dann Erfolg
tmp = scenario(); state["odds_status_seq"][:] = [401, 200]
r = fod.run(sleep=sleeps.append, log=quiet)
check("Fehler, dann Erfolg: genau 2 Abrufe, 5 Min. (300 s) Pause dazwischen", n_odds() == 2 and sleeps == [300] and r["result"] == "OK" and r["attempts"] == 2, f"{n_odds()} Abrufe, Pausen {sleeps}")
check("Wiederholung im Protokoll vermerkt", "(nach Wiederholung)" in alines()[-1] and "status=401" in olines()[0] and "status=200" in olines()[1])
# zweimal Fehler
tmp = scenario(odds_status=401)
r = fod.run(sleep=sleeps.append, log=quiet)
check("zweimal Fehler: genau 2 Abrufe (nicht mehr), dann aufgegeben, Ergebnis ERROR", n_odds() == 2 and sleeps == [300] and r["result"] == "ERROR", f"{n_odds()} Abrufe")
check("aufgegeben: automation.log ERROR mit kurzer Meldung, kein Key/URL", "result=ERROR | detail=aufgegeben nach 2 Versuchen: Odds API: Key ungueltig" in alines()[-1] and SECRET not in files_text(tmp) and "http" not in alines()[-1])
# unerwartete Ausnahme
tmp = scenario(); orig = oc.get_odds
def kaputt(*a, **k): raise RuntimeError(f"Max retries exceeded with url: https://api.the-odds-api.com/v4/x?apiKey={SECRET}")
fod.oc.get_odds = kaputt
rc = fod.main(); fod.oc.get_odds = orig
check("unerwartete Ausnahme: Exit-Code 1, ERROR im Protokoll, ohne URL und Key", rc == 1 and "result=ERROR | detail=RuntimeError:" in alines()[-1] and SECRET not in files_text(tmp) and "http" not in alines()[-1], alines()[-1][-80:])
rc_ok = (lambda: (scenario(), fod.main())[1])()
check("main(): Exit-Code 0 bei Erfolg", rc_ok == 0)

# ============================================================ C) update_model.py: Protokoll in main()
tmp = fresh_env(); real_loader = None
import dotenv; dotenv.load_dotenv = lambda *a, **k: False
orig_run = update_model.run_update
def case(fn, key="x" * 12):
    os.environ["BALLDONTLIE_API_KEY"] = key; update_model.run_update = fn
    try: return update_model.main([])
    finally: update_model.run_update = orig_run
rc = case(lambda **k: {"status": "updated", "processed": 7, "as_of": datetime(2026, 10, 20).date(), "received": 9, "duplicates": 2})
check("update_model: neue Spiele -> OK mit Anzahl und Stand im Protokoll", rc == 0 and "job=update_model | result=OK | detail=7 neue Spiele, Ratings bis 2026-10-20" in alines()[-1], alines()[-1][-70:])
rc = case(lambda **k: {"status": "unchanged", "processed": 0, "received": 12, "duplicates": 12, "not_final": 0})
check("update_model: 'keine neuen Spiele' wird protokolliert (OK)", rc == 0 and "result=OK | detail=keine neuen Spiele" in alines()[-1])
rc = case(lambda **k: {"status": "error", "reason": "no_ids"})
check("update_model: Fehlerstatus -> ERROR im Protokoll, Exit-Code 1", rc == 1 and "result=ERROR | detail=Modell ohne Spiel-IDs" in alines()[-1])
def boom(**k): raise RuntimeError(f"HTTPSConnectionPool: Max retries exceeded with url: https://api.balldontlie.io/v1/games?x=1 key={'k' * 12}")
n = len(alines()); rc = case(boom, key="k" * 12)
check("update_model: unerwartete Ausnahme -> Exit 1, ERROR im Protokoll ohne URL/Key", rc == 1 and len(alines()) == n + 1 and "result=ERROR | detail=RuntimeError:" in alines()[-1] and "http" not in alines()[-1] and "k" * 12 not in alines()[-1], alines()[-1][-90:])
os.environ.pop("BALLDONTLIE_API_KEY", None); update_model.run_update = orig_run
n = len(alines()); rc = update_model.main([])
check("update_model: fehlender API-Key -> Exit 2 und ERROR im Protokoll", rc == 2 and "result=ERROR | detail=BALLDONTLIE_API_KEY fehlt" in alines()[-1] and len(alines()) == n + 1)
os.environ["BALLDONTLIE_API_KEY"] = "x" * 12; n = len(alines()); update_model.run_update = lambda **k: {"status": "dry_run", "processed": 3}
rc = update_model.main(["--dry-run"]); update_model.run_update = orig_run
check("update_model --dry-run: nichts protokolliert", rc == 0 and len(alines()) == n)
os.environ.pop("BALLDONTLIE_API_KEY", None)

# ============================================================ D) plist- und Shell-Dateien
lint = subprocess.run(["plutil", "-lint"] + [str(p) for p in sorted((ROOT / "automation").glob("*.plist"))], capture_output=True, text=True)
check("plutil -lint fuer alle plist-Dateien (update-model, fetch-odds, betano-auto)", lint.returncode == 0 and lint.stdout.count(": OK") == 3, lint.stdout.strip().replace("\n", " | "))
exp = {"de.nbaedge.update-model": ("update_model.py", 8, "automation_update_model"), "de.nbaedge.fetch-odds": ("fetch_odds_daily.py", 22, "automation_fetch_odds")}
for label, (script, hour, out) in exp.items():
    d = plistlib.loads((ROOT / "automation" / f"{label}.plist").read_bytes())
    pa = d["ProgramArguments"]
    check(f"{label}: Label, absolutes venv-Python, Skript, WorkingDirectory = Projektordner",
          d["Label"] == label and pa[0] == str(ROOT / "venv" / "bin" / "python") and Path(pa[0]).exists() and pa[1] == str(ROOT / script) and Path(pa[1]).exists() and d["WorkingDirectory"] == str(ROOT))
    check(f"{label}: StartCalendarInterval {hour:02d}:00, kein RunAtLoad", d["StartCalendarInterval"] == {"Hour": hour, "Minute": 0} and not d.get("RunAtLoad", False))
    check(f"{label}: stdout/stderr in Dateien unter data/", d["StandardOutPath"] == str(ROOT / "data" / f"{out}.out.log") and d["StandardErrorPath"] == str(ROOT / "data" / f"{out}.err.log"))
for sh in ("install_schedule.sh", "uninstall_schedule.sh"):
    f = ROOT / "automation" / sh; code = [l for l in f.read_text().splitlines() if not l.strip().startswith("#")]
    check(f"{sh}: Syntax OK (bash -n), ausfuehrbar, ohne sudo/pmset", subprocess.run(["bash", "-n", str(f)]).returncode == 0 and os.access(f, os.X_OK) and not re.search(r"\b(sudo|pmset)\b", "\n".join(code)))
inst = (ROOT / "automation" / "install_schedule.sh").read_text()
check("install: Benutzerkonto (~/Library/LaunchAgents), launchctl bootstrap gui/<UID>, Anzeige der geladenen Auftraege", "$HOME/Library/LaunchAgents" in inst and 'DOMAIN="gui/$(id -u)"' in inst and 'launchctl bootstrap "$DOMAIN"' in inst and "launchctl list | grep nbaedge" in inst)
uninst = (ROOT / "automation" / "uninstall_schedule.sh").read_text()
check("uninstall: launchctl bootout gui/<UID>, Datei entfernen, Anzeige", 'launchctl bootout "$DOMAIN/$label"' in uninst and "rm -f" in uninst and "launchctl list | grep nbaedge" in uninst)

# ============================================================ E) App: Modell-Neuladen, Sidebar-Zeile (AppTest)
from streamlit.testing.v1 import AppTest
import tempfile, shutil, pickle
tmp = fresh_env(); work = Path(tempfile.mkdtemp(prefix="nbaedge_model_")); model = work / "elo_model.pkl"
shutil.copy2(MODEL_PATH, model); elo_mod.MODEL_PATH = model
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def side(at): return " | ".join([m.value for m in at.sidebar.markdown] + [c.value for c in at.sidebar.caption])
at = app().run()
eng0 = at.session_state["engine"]; k0 = eng0.ratings["New York Knicks"]; asof0 = eng0.ratings_as_of()
check("App startet mit der Modelldatei im Temp-Ordner (nicht mit dem echten Pickle)", not at.exception and k0 == EloEngine.load(MODEL_PATH).ratings["New York Knicks"], str(asof0))
calls0, bdl0 = n_odds(), state["bdl_calls"]
for _ in range(10): at.run()
check("10 Reruns ohne Dateiaenderung: Modell bleibt dasselbe Objekt, keine neuen Abrufe", at.session_state["engine"] is eng0 and n_odds() == calls0 and not at.exception)
proj0 = {p["home_team"]: p["exp_spread"] for p in at.session_state["projections"]}
new = pickle.loads(model.read_bytes()); new.ratings["New York Knicks"] += 150.0; new.last_processed_date = datetime(2026, 10, 20).date()
tmpf = work / "elo_model.pkl.tmp"; tmpf.write_bytes(pickle.dumps(new)); time.sleep(0.05); os.replace(tmpf, model)     # wie update_model.save (atomar)
at.run()
eng1 = at.session_state["engine"]
check("Modelldatei ersetzt: die laufende Sitzung laedt das neue Modell von selbst (session_state UND cache_resource)", not at.exception and eng1 is not eng0 and eng1.ratings["New York Knicks"] == k0 + 150.0, f"{k0:.0f} -> {eng1.ratings['New York Knicks']:.0f}")
check("Sidebar zeigt weiter 'Ratings bis' und jetzt das neue Datum (20.10.2026)", "Ratings bis: 20.10.2026" in side(at), side(at)[:0] or "")
proj1 = {p["home_team"]: p["exp_spread"] for p in at.session_state["projections"]}
check("Projektionen wurden mit den neuen Ratings neu berechnet (Knicks-Spread groesser)", proj1["New York Knicks"] > proj0["New York Knicks"], f"{proj0['New York Knicks']} -> {proj1['New York Knicks']}")
check("Neuladen verbraucht keine Odds-Credits (Cache) und keinen zusaetzlichen BallDontLie-Abruf innerhalb der TTL", n_odds() == calls0 and state["bdl_calls"] == bdl0, f"Odds {n_odds() - calls0}, BDL {state['bdl_calls'] - bdl0}")
at2 = app().run()
check("neue Sitzung nach der Aenderung: laedt direkt das neue Modell", at2.session_state["engine"].ratings["New York Knicks"] == k0 + 150.0)
for _ in range(3): at.run()
check("weitere Reruns: kein erneutes Laden (Objekt bleibt)", at.session_state["engine"] is eng1)
elo_mod.MODEL_PATH = MODEL_PATH

# Sidebar-Zeile Automatik
def with_log(lines):
    Path(os.environ["NBAEDGE_AUTOMATION_LOG"]).write_text("".join(lines))
def entry(job, result, detail, hours_ago):
    return f"{(datetime.now().astimezone() - timedelta(hours=hours_ago)).isoformat(timespec='seconds')} | job={job} | result={result} | detail={detail}\n"
elo_mod.MODEL_PATH = MODEL_PATH
Path(os.environ["NBAEDGE_AUTOMATION_LOG"]).unlink(missing_ok=True)
a0 = app().run(); check("ohne automation.log: keine Zeile \"Automatik: letzter Lauf\" (die Betano-Zeile zeigt dezent \"nicht aktiv\")", "Automatik: letzter Lauf" not in side(a0) and "Betano-Automatik: nicht aktiv" in side(a0))
with_log([entry("fetch_odds_daily", "OK", "3 Spiele, noch 444 Credits", 5), entry("update_model", "OK", "5 neue Spiele, Ratings bis 2026-10-20", 3)])
a1 = app().run(); t = side(a1)
check("OK-Lauf: 'Automatik: letzter Lauf Ratings dd.mm. HH:MM, OK', nicht gelb", "Automatik: letzter Lauf Ratings" in t and ", OK" in t and "facc15" not in t.split("Automatik")[1][:60], t.split("Automatik")[1][:90])
with_log([entry("fetch_odds_daily", "OK", "3 Spiele", 30), entry("update_model", "ERROR", "RuntimeError: Verbindung", 1)])
t = side(app().run())
check("Fehler im letzten Lauf: gelb mit Hinweis", "Automatik: letzter Lauf Ratings" in t and "Fehler" in t and "facc15" in t and "Letzter Lauf mit Fehler" in t, t.split("Automatik")[1][:140])
with_log([entry("update_model", "OK", "keine neuen Spiele", 40), entry("fetch_odds_daily", "OK", "3 Spiele", 2)])
t = side(app().run())
check("letzter erfolgreicher update_model-Lauf > 36 Std.: gelb mit Hinweis", "facc15" in t and "seit über 36 Std." in t and "update_model" in t, t.split("Automatik")[1][:160])
with_log([entry("update_model", "OK", "x", 35), entry("fetch_odds_daily", "SKIP", "Cache jünger als 60 Min.", 2)])
t = side(app().run())
check("35 Std. und SKIP (frischer Cache) zaehlen als in Ordnung (nicht gelb)", "Automatik: letzter Lauf Quoten" in t and "übersprungen" in t and "facc15" not in t.split("Automatik")[1][:80])

# ============================================================ F) Rahmen
check("Pickle und Projekt-data/ unberuehrt (keine neuen/geaenderten Dateien, auch automation.log unveraendert)", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0 and {p.name for p in (ROOT / "data").glob("*") if p.is_file()} == set(real_data)
      and all(p.stat().st_mtime_ns == real_data[p.name] for p in (ROOT / "data").glob("*") if p.is_file() and p.name in real_data))
check("kein launchctl/Installation durch den Test: ~/Library/LaunchAgents unveraendert (Stand vor dem Test)", {p.name: p.read_bytes() for p in (Path.home() / "Library" / "LaunchAgents").glob("de.nbaedge*")} == agents0)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
