"""Tests fuer die Navigation 'nur der aktive Bereich rechnet' (app.py, LAZY_TABS): jeder Bereich laeuft allein ohne Fehler, die anderen Bereiche rechnen nicht mit (keine Takt-Fragmente
unsichtbarer Tabs), Wechsel, Standardbereich, Rueckschalter NBAEDGE_ALL_TABS=1. Offline (tests/fake_net.py), keine echten Dateien. Aufruf: venv/bin/python tests/test_lazy_tabs.py"""
import hashlib, os, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
import ui.live_tab as lt
import ui.player_tab as pt
import ui.pre_match_tab as pm

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*.json")) + [ROOT / "data" / "pregame_lines.json", ROOT / "data" / "live_bets.json"]
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.exists()}
real_before = real_files()

CALLS = {"spieltag": 0, "spieler": 0, "prematch": 0, "live_head": 0, "live_cards": 0, "my_bets": 0}
def count(mod, name, key):
    orig = getattr(mod, name)
    def w(*a, **k):
        CALLS[key] += 1
        return orig(*a, **k)
    setattr(mod, name, w)
count(lt, "render_spieltag_tab", "spieltag"); count(pt, "render_player_tab", "spieler"); count(pm, "render_pre_match_tab", "prematch")
count(lt, "_live_head", "live_head"); count(lt, "_live_cards", "live_cards"); count(pt, "_my_bets", "my_bets")

def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
HEAD = {"📊 Score Projections": "## 📊 Score Projections", "🔴 Live (alt)": "## 🔴 Live Projection Engine", "🏀 Spieltag": "## 🏀 Spieltag", "🎯 Live Bet Tracker": "## 🎯 Live Bet Tracker",
        "🏃 Spieler": "## 🏃 Spieler", "📰 Lineup News": "## 📰 Lineup / Injury News", "📅 History": "## 📅 History / Accuracy / Self-Correction", "📈 ELO Rankings": "## 📈 Team ELO Rankings",
        "✍️ Pre-Match Eingabe": "## ✍️ Pre-Match Eingabe"}

os.environ["NBAEDGE_ALL_TABS"] = "0"
for k in CALLS: CALLS[k] = 0
at = app().run()
check("lazy: Navigation als Auswahlelement, keine st.tabs", len(at.tabs) == 0 and at.radio(key="main_tab") is not None and not at.exception, " | ".join(problems(at))[:200])
labels = list(at.radio(key="main_tab").options)
check("Bereiche in der gewohnten Reihenfolge, Score Projections zuerst (Standard)", labels[:3] == ["📊 Score Projections", "🔴 Live (alt)", "🏀 Spieltag"] and labels[-1] == "✍️ Pre-Match Eingabe" and "🏃 Spieler" in labels, str(labels))
md = lambda a: [m.value for m in a.markdown]
heads = lambda a: [h for h in HEAD.values() if h in md(a)]
check("Standardbereich: nur die Ueberschrift von Score Projections, kein anderer Bereich gerechnet", heads(at) == [HEAD["📊 Score Projections"]] and CALLS == {k: 0 for k in CALLS}, str(CALLS))
for label in labels:
    if label not in HEAD: continue
    for k in CALLS: CALLS[k] = 0
    a = app().run()
    a = a.radio(key="main_tab").set_value(label).run()
    probs = [p for p in problems(a) if "Live-Modus" not in p]
    check(f"Bereich '{label}' allein: keine Exception, nur seine Ueberschrift", not a.exception and heads(a) == [HEAD[label]], f"{heads(a)} {' | '.join(probs)[:150]}")
    want = {"spieltag": label == "🏀 Spieltag", "spieler": label == "🏃 Spieler", "prematch": label == "✍️ Pre-Match Eingabe"}
    got = {"spieltag": CALLS["spieltag"] > 0, "spieler": CALLS["spieler"] > 0, "prematch": CALLS["prematch"] > 0}
    check(f"  '{label}': rechnet nur sich selbst (Spieltag/Spieler/Pre-Match-Funktionen und Takt-Fragmente nur im eigenen Bereich)", got == want and (CALLS["live_head"] > 0) == (label == "🏀 Spieltag") and (CALLS["my_bets"] > 0) == (label == "🏃 Spieler"), f"{CALLS}")
# Wechsel in einer Sitzung
a = app().run()
for k in CALLS: CALLS[k] = 0
a.radio(key="main_tab").set_value("🏃 Spieler").run()
c1 = dict(CALLS)
a.radio(key="main_tab").set_value("✍️ Pre-Match Eingabe").run()
check("Wechsel Spieler -> Pre-Match in einer Sitzung: der verlassene Bereich rechnet nicht mehr (keine Takt-Fragmente der Spieler-Seite)", c1["spieler"] == 1 and CALLS["spieler"] == 1 and CALLS["prematch"] == 1 and CALLS["my_bets"] == c1["my_bets"], f"{c1} -> {CALLS}")
a.radio(key="main_tab").set_value("🎯 Live Bet Tracker").run()
check("alter Live Bet Tracker ohne den Bereich 'Live (alt)': kein Fehler, Hinweis auf den letzten Besuch von 'Live (alt)'", not a.exception and any("letzten Besuch" in c.value for c in a.caption))

# Rueckschalter: alle Tabs wie frueher
os.environ["NBAEDGE_ALL_TABS"] = "1"
for k in CALLS: CALLS[k] = 0
b = app().run()
check("NBAEDGE_ALL_TABS=1: wieder st.tabs mit allen neun Bereichen, alle rechnen", len(b.tabs) == 9 and CALLS["spieltag"] == 1 and CALLS["spieler"] == 1 and CALLS["prematch"] == 1 and not b.exception, f"{len(b.tabs)} {CALLS}")

check("echte Dateien unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
