"""Tests: Sidebar-Zeile 'Betano-Automatik' (data/automation_log.betano_status + App) und das Plist automation/de.nbaedge.betano-auto.plist.
Offline (tests/fake_net.py), Temp-Ordner fuer Protokoll und Zustandsfile; ~/Library/LaunchAgents und echte Dateien nur gelesen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_auto_sidebar.py"""
import hashlib, json, os, plistlib, subprocess, sys, warnings
from datetime import datetime, timedelta
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install()
import data.automation_log as alog

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
REAL = [ROOT / "data/automation.log", ROOT / "data/betano_auto_state.json", ROOT / "data/tracking/pre_match_entries.json", ROOT / "data/upcoming_cache.json"]
real_before = {str(p): sha(p) for p in REAL}
agents = Path.home() / "Library" / "LaunchAgents"
ls_before = sorted(p.name for p in agents.glob("*")) if agents.exists() else []

NOW = datetime.now().astimezone()
def ev(result, detail, hours_ago, job="betano_auto"):
    return f"{(NOW - timedelta(hours=hours_ago)).isoformat(timespec='seconds')} | job={job} | result={result} | detail={detail}\n"
def setup(lines=None, state=None):
    tmp = fresh_env()
    if lines is not None:
        Path(os.environ["NBAEDGE_AUTOMATION_LOG"]).write_text("".join(lines))
    if state is not None:
        alog.betano_state_path().write_text(json.dumps(state))
    return tmp
def stat(sight=False): return alog.betano_status(NOW, game_in_sight=sight)

# ===== Logik
setup()
b = stat()
check("nie gelaufen: 'nicht aktiv', keine Farbe, keine Warnung", b["level"] == "none" and b["text"] == "Betano-Automatik: nicht aktiv" and b["hint"] == "", str(b))
setup([ev("OK", "Spielplan: Cache; 1 gespeichert, 0 unverändert", 1)])
b = stat(True)
check("ok und letzter Lauf 1 Std. alt bei Spiel in Sicht: gruen, mit Zeit und Ergebnis", b["level"] == "green" and "letzter Lauf" in b["text"] and ", OK" in b["text"] and "Zustand: ok" in b["text"], b["text"])
setup([ev("SKIP", "Spielplan: Cache; kein Spiel in Sicht", 20)])
check("kein Spiel in Sicht, Lauf 20 Std. alt: gruen", stat(False)["level"] == "green")
setup([ev("OK", "x", 5)])
b = stat(True)
check("Spiel in Sicht, letzter Lauf 5 Std. alt (> 3 Std.): gelb mit Hinweis", b["level"] == "yellow" and "3 Std." in b["hint"], str(b))
setup([ev("OK", "x", 2)])
check("Spiel in Sicht, Lauf 2 Std. alt: gruen", stat(True)["level"] == "green")
until = (NOW + timedelta(hours=4)).replace(microsecond=0)
setup([ev("ERROR", "HTTP 429 (Wizards - Bucks), gestoppt, Pause 6 Stunden", 2)], {"state": "pause", "pause_until": until.isoformat(), "last_run": None, "last_error": "HTTP 429"})
b = stat(True)
check("Pause (429): gelb mit Ende der Pause (nicht rot)", b["level"] == "yellow" and f"Pause bis {until.strftime('%d.%m. %H:%M')}" in b["text"], b["text"])
setup([ev("ERROR", "HTTP 429 gestoppt", 8)], {"state": "pause", "pause_until": (NOW - timedelta(hours=2)).isoformat(), "last_run": None, "last_error": "HTTP 429"})
check("abgelaufene Pause wird nicht mehr angezeigt (letzter Lauf ERROR -> rot, bis der naechste Lauf kommt)", stat()["level"] == "red" and "Pause bis" not in stat()["text"])
setup([ev("ERROR", "HTTP 403 (Spielliste), gestoppt, Automatik AUS", 1)], {"state": "aus", "pause_until": None, "last_run": None, "last_error": "HTTP 403"})
b = stat()
check("AUS (403): rot mit Hinweis auf --reset", b["level"] == "red" and "AUS bis Freigabe" in b["text"] and "--reset" in b["hint"], str(b))
setup([ev("ERROR", "abgebrochen nach 3 Fehlern: 0 gespeichert", 1)])
check("ERROR (3 Fehler): rot", stat()["level"] == "red")
setup([ev("SKIP", "Spielplan nicht verfügbar (ConnectionError: kein Netz)", 1)])
b = stat(True)
check("'Spielplan nicht verfügbar': gelb", b["level"] == "yellow" and "Spielplan nicht verfügbar" in b["hint"], str(b))
setup([ev("WARN", "Spielplan: Cache; 1 gespeichert, 1 Fehler", 1)])
check("Warnung (einzelne Spiele): gelb", stat()["level"] == "yellow")
# bestehende Zeile bleibt unabhaengig von betano_auto
setup([ev("OK", "3 Spiele", 5, "fetch_odds_daily"), ev("OK", "5 neue Spiele", 3, "update_model")] + [ev("SKIP", "kein Spiel in Sicht", h) for h in (2, 1)])
s0 = alog.sidebar_status(NOW)
check("bestehende Zeile ('letzter Lauf'): betano_auto-Zeilen aendern sie nicht (letzter Auftrag bleibt update_model, nicht gelb)", s0["job"] == "update_model" and not s0["warn"], str(s0))
setup([ev("OK", "x", 100, "update_model"), ev("OK", "x", 100, "fetch_odds_daily")] + [ev("SKIP", "kein Spiel in Sicht", h) for h in range(1, 40)])
s1 = alog.sidebar_status(NOW)
check("viele betano_auto-Zeilen verdraengen die anderen Auftraege nicht (alte Laeufe bleiben sichtbar -> weiter 'seit ueber 36 Std.')", s1 is not None and s1["warn"] and "update_model" in s1["hint"], str(s1))

# ===== App
from streamlit.testing.v1 import AppTest
def app():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
def side(at):
    return " | ".join([str(x.value) for x in at.sidebar.markdown] + [str(x.value) for x in at.sidebar.caption])
setup([ev("OK", "3 Spiele", 5, "fetch_odds_daily"), ev("OK", "5 neue Spiele", 3, "update_model"), ev("OK", "Spielplan: Cache; kein Spiel", 1)])
at_ = app().run()
t = side(at_)
cap = [str(x.value) for x in at_.sidebar.caption]
mk = [str(x.value) for x in at_.sidebar.markdown]
check("App: bestehende Zeile (Caption) bleibt unveraendert und die Betano-Zeile (gruen) ist zusaetzlich da", any(c.startswith("Automatik: letzter Lauf Ratings") for c in cap)
      and any("Betano-Automatik: letzter Lauf" in m and "4ade80" in m for m in mk), str(cap)[:200])
setup()
t = side(app().run())
check("App: nie gelaufen -> 'Betano-Automatik: nicht aktiv', keine bestehende Zeile, keine Warnung", "Betano-Automatik: nicht aktiv" in t and "Automatik: letzter Lauf" not in t and "facc15" not in t and "f87171" not in t, t[:200])
setup([ev("ERROR", "HTTP 403 gestoppt", 1)], {"state": "aus", "pause_until": None, "last_run": None, "last_error": "HTTP 403"})
t = side(app().run())
check("App: AUS -> rote Zeile mit --reset", "f87171" in t and "AUS bis Freigabe" in t and "--reset" in t, t[:300])

# ===== Plist
plist = ROOT / "automation" / "de.nbaedge.betano-auto.plist"
check("Plist: plutil -lint OK", subprocess.run(["plutil", "-lint", str(plist)], capture_output=True).returncode == 0)
d = plistlib.loads(plist.read_bytes())
check("Plist: Label de.nbaedge.betano-auto", d["Label"] == "de.nbaedge.betano-auto")
check("Plist: StartInterval 3600, kein StartCalendarInterval", d["StartInterval"] == 3600 and "StartCalendarInterval" not in d)
check("Plist: kein RunAtLoad (oder false)", d.get("RunAtLoad", False) is False)
check("Plist: venv/bin/python und betano_auto.py, beide existieren", d["ProgramArguments"][0].endswith("/venv/bin/python") and d["ProgramArguments"][1].endswith("/betano_auto.py")
      and all(Path(x).exists() for x in d["ProgramArguments"]), str(d["ProgramArguments"]))
check("Plist: Arbeitsverzeichnis = Projektordner, existiert", Path(d["WorkingDirectory"]) == ROOT)
check("Plist: Ausgabe/Fehler unter data/ (nicht data/tracking)", all(str(Path(d[k]).parent) == str(ROOT / "data") for k in ("StandardOutPath", "StandardErrorPath")), f"{d['StandardOutPath']}")
check("Plist nicht installiert: ~/Library/LaunchAgents unveraendert, kein betano-Eintrag", sorted(p.name for p in agents.glob("*")) == ls_before and not any("betano" in n for n in ls_before))
check("README: Abschnitt Betano-Automatik mit launchctl bootstrap/bootout und --reset und dem Beobachtungslauf-Hinweis",
      all(x in (ROOT / "automation/README.md").read_text() for x in ("## Betano-Automatik", "launchctl bootstrap", "launchctl bootout", "betano_auto.py --reset", "Erst nach einem Beobachtungslauf")))
real_after = {str(p): sha(p) for p in REAL}
check("echte Dateien unveraendert (automation.log, Zustand, tracking, upcoming_cache)", real_before == real_after, str({k: v for k, v in real_after.items() if real_before[k] != v}))
print("\nALLE TESTS BESTANDEN" if ok else "\nTESTS FEHLGESCHLAGEN")
sys.exit(0 if ok else 1)
