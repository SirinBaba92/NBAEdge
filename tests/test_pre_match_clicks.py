"""Klick-Test fuer den Tab Pre-Match Eingabe: nach JEDEM Schritt darf die Seite weder eine Exception noch eine Warnung/Fehlermeldung
enthalten, insbesondere nicht den Streamlit-Satz 'was created with a default value but also had its value set via the Session State API'.
Offline (tests/fake_net.py, Temp-Verzeichnisse), keine echten Calls; die echte Tracking-Datei wird nicht angefasst.
Aufruf aus dem Projektordner: venv/bin/python tests/test_pre_match_clicks.py"""
import datetime as dt, hashlib, json, os, re, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import data.pre_match_store as ps
import data.nba_live as _nba_live
_nba_live.NBA_CACHE_SECONDS = 10 ** 6      # AppTest startet bei jedem Klick das ganze Skript, auch den Live-Tab: dessen 20-s-Zwischenspeicher darf mitten im Test nicht ablaufen
from streamlit.elements.lib import policies
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
real_file = ROOT / "data" / "tracking" / "pre_match_entries.json"
real_sha = hashlib.sha256(real_file.read_bytes()).hexdigest() if real_file.exists() else None
PHRASE = "was created with a default value"
K, P = "New York Knicks", "Philadelphia 76ers"

def problems(at) -> list[str]:
    """Alles, was nach einem Problem aussieht: Exceptions, Warnungen, Fehler und der Streamlit-Satz in irgendeinem Element."""
    out = [f"Exception: {e.value}" for e in at.exception] + [f"Warnung: {w.value}" for w in at.warning] + [f"Fehler: {e.value}" for e in at.error]
    for group in (at.markdown, at.caption, at.info, at.text):
        out += [f"Text: {el.value}" for el in group if PHRASE in str(el.value)]
    return out

def mk_event(home, away, total, home_points, commence, last_update, eid):
    bms = []
    for bk, hp in zip(("pinnacle", "draftkings", "fanduel")[:len(home_points)], home_points):
        ms = [{"key": "totals", "last_update": iso(last_update), "outcomes": [{"name": "Over", "point": total, "price": 1.9}, {"name": "Under", "point": total, "price": 1.9}]},
              {"key": "spreads", "last_update": iso(last_update), "outcomes": [{"name": home, "point": hp, "price": 1.9}, {"name": away, "point": -hp, "price": 1.9}]}]
        bms.append({"key": bk, "last_update": iso(last_update), "markets": ms})
    return {"id": eid, "home_team": home, "away_team": away, "commence_time": iso(commence), "bookmakers": bms}

fresh_env(remaining=400)
state["commence_offsets"] = {K: 3 * H, "San Antonio Spurs": 3 * H, "Detroit Pistons": -600}
n = time.time()
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu", "data": [mk_event(K, P, 232.0, [-4.5, -4.5, -4.0], n + 3 * H, n - 700, "ev-k")]}},
                                                               "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
import engine.projection as _proj
_calls = {"n": 0}; _orig_cp = _proj.compute_projection
def _counting(*a, **k):
    _calls["n"] += 1; return _orig_cp(*a, **k)
_proj.compute_projection = _counting                      # app.py importiert die Funktion bei jedem Lauf neu: Zaehler greift
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def btn(at, key): return [b for b in at.button if b.key == key][0]
def ti(at, key): return at.text_input(key=key)
def step(name, at, action, recompute=0):
    policies._shown_default_value_warning = False          # Streamlit zeigt den Satz sonst nur einmal pro Prozess
    global _total_steps
    _total_steps += 1
    cp_before, net_before = _calls["n"], (len(state["odds_calls"]), state["bdl_calls"], state["nba_calls"])
    action(at)
    p = problems(at)
    check(f"Schritt '{name}': keine Exception, keine Warnung/Fehlermeldung, kein 'default value'-Satz", not p, " | ".join(p)[:200])
    if _calls["n"] - cp_before != recompute or (len(state["odds_calls"]), state["bdl_calls"], state["nba_calls"]) != net_before:
        check(f"   Schritt '{name}': keine neue Projektionsberechnung und keine Abrufe", False, f"compute_projection +{_calls['n'] - cp_before}, odds/bdl/nba {net_before} -> {(len(state['odds_calls']), state['bdl_calls'], state['nba_calls'])}")
    else:
        global _quiet_steps
        _quiet_steps += 1
    return at

_quiet_steps = 0; _total_steps = 0
policies._shown_default_value_warning = False
at = app().run()
p = [x for x in at.session_state["projections"] if x["home_team"] == K][0]
kid = hashlib.md5(ps.game_key(p["game_date"], ps.normalize_start(p["game_start"]), K, P).encode()).hexdigest()[:10]
b0 = f"pm_sp_{kid}_main"
check("Start der Seite: keine Exception, keine Warnung", not problems(at), " | ".join(problems(at))[:200])
cp0, net0 = _calls["n"], (len(state["odds_calls"]), state["bdl_calls"], state["nba_calls"])
check("Start: Projektionen wurden einmal berechnet (3 Spiele)", cp0 == 3, str(cp0))
step("+ bei der Hauptlinie", at, lambda a: btn(a, f"{b0}_plus").click().run())
step("- bei der Hauptlinie", at, lambda a: btn(a, f"{b0}_minus").click().run())
step("- bei der Hauptlinie (zweites Mal)", at, lambda a: btn(a, f"{b0}_minus").click().run())
step("Eingabe im Gast-Feld (+2)", at, lambda a: ti(a, f"{b0}_gline").input("+2").run())
check("   Heim-Feld hat sich umgedreht (-2,0)", ti(at, f"{b0}_line").value == "-2,0", ti(at, f"{b0}_line").value)
step("Eingabe im Heim-Feld (-3)", at, lambda a: ti(a, f"{b0}_line").input("-3").run())
check("   Gast-Feld hat sich umgedreht (+3,0)", ti(at, f"{b0}_gline").value == "+3,0", ti(at, f"{b0}_gline").value)
step("+ Weitere Linie hinzufügen", at, lambda a: btn(a, f"pm_add_{kid}").click().run())
n1 = f"pm_sp_{kid}_n1"
check("   neue Linie automatisch: Heim -4,0 / Gast +4,0", ti(at, f"{n1}_line").value == "-4,0" and ti(at, f"{n1}_gline").value == "+4,0")
step("+ bei der weiteren Linie", at, lambda a: btn(a, f"{n1}_plus").click().run())
step("- bei der weiteren Linie", at, lambda a: btn(a, f"{n1}_minus").click().run())
step("Eingabe im Gast-Feld der weiteren Linie", at, lambda a: ti(a, f"{n1}_gline").input("+6").run())
step("Entfernen (neue, noch nicht gespeicherte Linie)", at, lambda a: btn(a, f"{n1}_rm").click().run())
at = app().run()
step("+ Weitere Linie hinzufügen (erneut)", at, lambda a: btn(a, f"pm_add_{kid}").click().run())
def fill_and_save(a):
    ti(a, f"{b0}_away").input("1,95"); ti(a, f"{b0}_home").input("1,91"); ti(a, f"{b0}_book").input("Pinnacle")
    ti(a, f"{n1}_away").input("2,30"); ti(a, f"{n1}_home").input("1,60"); ti(a, f"{n1}_book").input("Bet365")
    btn(a, f"pm_save_{kid}").click().run()
step("Quoten eintragen und Speichern", at, fill_and_save, recompute=1)         # eigene Spread-Linie gespeichert: GENAU dieses Spiel wird neu berechnet (Schritt 9a), kein Abruf
e = [v for v in ps.load()["entries"].values() if v["home"] == K]
check("   gespeichert: Hauptlinie + weitere Linie in der (Temp-)Datei", e and [l["id"] for l in e[0]["markets"]["spread"]["lines"]] == ["main", "x1"])
at = app().run()
check("Neu laden mit gespeicherten Linien: keine Exception, keine Warnung", not problems(at), " | ".join(problems(at))[:200])
step("+ bei einer gespeicherten weiteren Linie", at, lambda a: btn(a, f"pm_sp_{kid}_x1_plus").click().run())
step("- bei einer gespeicherten weiteren Linie", at, lambda a: btn(a, f"pm_sp_{kid}_x1_minus").click().run())
step("Entfernen (gespeicherte Linie, Revision)", at, lambda a: btn(a, f"pm_sp_{kid}_x1_rm").click().run())
at = app().run()
check("nach dem Entfernen frisch geladen: keine Exception, keine Warnung; Linie als Revision erhalten", not problems(at) and [l["active"] for l in [v for v in ps.load()["entries"].values() if v["home"] == K][0]["markets"]["spread"]["lines"]] == [True, False])
step("Speichern ohne Aenderung", at, lambda a: btn(a, f"pm_save_{kid}").click().run())
# ---- Markt Total: dieselben Pruefungen (keine Warnung/Exception, keine neue Projektionsberechnung, keine Abrufe)
at = app().run()
tb = f"pm_tt_{kid}_main"
step("Total: + bei der Hauptlinie", at, lambda a: btn(a, f"{tb}_plus").click().run())
step("Total: - bei der Hauptlinie", at, lambda a: btn(a, f"{tb}_minus").click().run())
step("Total: Eingabe der Linie (231.5)", at, lambda a: ti(a, f"{tb}_line").input("231.5").run())
step("Total: Eingabe Over-Quote", at, lambda a: ti(a, f"{tb}_over").input("1,95").run())
step("Total: + Hoehere Linie", at, lambda a: btn(a, f"pm_tt_{kid}__addh").click().run())
step("Total: - Niedrigere Linie", at, lambda a: btn(a, f"pm_tt_{kid}__addl").click().run())
hk = [k for k in (t.key or "" for t in at.text_input) if k.startswith(f"pm_tt_{kid}_nh") and k.endswith("_line")][0].rsplit("_line", 1)[0]
lk = [k for k in (t.key or "" for t in at.text_input) if k.startswith(f"pm_tt_{kid}_nl") and k.endswith("_line")][0].rsplit("_line", 1)[0]
check("   Total: neue Linien 1,0 weiter (232,5 / 230,5)", ti(at, f"{hk}_line").value == "232,5" and ti(at, f"{lk}_line").value == "230,5", f"{ti(at, hk + '_line').value} {ti(at, lk + '_line').value}")
step("Total: + bei der hoeheren Linie", at, lambda a: btn(a, f"{hk}_plus").click().run())
step("Total: - bei der niedrigeren Linie", at, lambda a: btn(a, f"{lk}_minus").click().run())
step("Total: Entfernen (neue niedrigere Linie)", at, lambda a: btn(a, f"{lk}_rm").click().run())
def fill_total(a):
    ti(a, f"{tb}_under").input("1,87"); ti(a, f"{tb}_book").input("Pinnacle")
    ti(a, f"{hk}_over").input("2,05"); ti(a, f"{hk}_under").input("1,77"); ti(a, f"{hk}_book").input("Bet365")
    btn(a, f"pm_save_{kid}").click().run()
step("Total: Quoten eintragen und Speichern", at, fill_total, recompute=1)      # eigene Total-Linie: genau dieses Spiel neu (Schritt 9a)
tl = lambda: ps.active_total_lines([v for v in ps.load()["entries"].values() if v["home"] == K][0])
check("   Total gespeichert: Hauptlinie 231,5 + hoehere Linie 233,0 (nach +)", [(l["id"], l["line"]) for l in tl()] == [("main", 231.5), ("x1", 233.0)], str([(l["id"], l["line"]) for l in tl()]))
at = app().run()
check("Total: Neu laden mit gespeicherten Linien ohne Warnung", not problems(at), " | ".join(problems(at))[:200])
step("Total: + bei einer gespeicherten Linie", at, lambda a: btn(a, f"pm_tt_{kid}_x1_plus").click().run())
step("Total: Entfernen (gespeicherte Linie, Revision)", at, lambda a: btn(a, f"pm_tt_{kid}_x1_rm").click().run())
at = app().run()
check("Total: nach dem Entfernen frisch geladen: nur Hauptlinie aktiv, entfernte Linie als Revision erhalten", len(tl()) == 1 and not problems(at))
step("Total: Speichern ohne Aenderung", at, lambda a: btn(a, f"pm_save_{kid}").click().run())
# ---- Markt Team Totals (je Team) und kompakte Zeilen: dieselben Pruefungen
at = app().run()
pa, ph = f"pm_ta_{kid}", f"pm_th_{kid}"
step("Team Totals Gast: + bei der Hauptlinie", at, lambda a: btn(a, f"{pa}_main_plus").click().run())
step("Team Totals Gast: - bei der Hauptlinie", at, lambda a: btn(a, f"{pa}_main_minus").click().run())
step("Team Totals Heim: Eingabe der Linie (118)", at, lambda a: ti(a, f"{ph}_main_line").input("118").run())
step("Team Totals Gast: + Hoehere Linie", at, lambda a: btn(a, f"{pa}__addh").click().run())
step("Team Totals Gast: - Niedrigere Linie", at, lambda a: btn(a, f"{pa}__addl").click().run())
step("Team Totals Heim: + Hoehere Linie", at, lambda a: btn(a, f"{ph}__addh").click().run())
gk = [t.key for t in at.text_input if (t.key or "").startswith(f"{pa}_n") and t.key.endswith("_line")]
check("   Team Totals: neue Zeilen je Team, 1,0 weiter (Heim 119,0)", len(gk) == 2 and ti(at, f"{ph}_nh3_line").value == "119,0" if f"{ph}_nh3_line" in [t.key for t in at.text_input] else len(gk) == 2, str(gk))
gh = gk[0].rsplit("_line", 1)[0]
step("Team Totals: + in einer kompakten Zeile", at, lambda a: btn(a, f"{gh}_plus").click().run())
step("Team Totals: Buchmacher der Hauptlinie aendern (folgt in neue Zeilen)", at, lambda a: ti(a, f"{pa}_main_book").input("Betano").run())
step("Team Totals: Buchmacher einer Zeile von Hand", at, lambda a: ti(a, f"{gh}_book").input("Bet365").run())
step("Team Totals: Entfernen (neue Zeile)", at, lambda a: btn(a, f"{gk[1].rsplit('_line', 1)[0]}_rm").click().run())
step("Spread: + Weitere Linie (kompakte Zeile)", at, lambda a: btn(a, f"pm_add_{kid}").click().run())
sn = [t.key for t in at.text_input if (t.key or "").startswith(f"pm_sp_{kid}_n") and t.key.endswith("_line")][0].rsplit("_line", 1)[0]
step("Spread: + in der kompakten Zeile", at, lambda a: btn(a, f"{sn}_plus").click().run())
step("Spread: Buchmacher in der kompakten Zeile", at, lambda a: ti(a, f"{sn}_book").input("Bet365").run())
def fill_team(a):
    for base, o, u in ((f"{pa}_main", "1,91", "1,89"), (f"{ph}_main", "1,85", "1,95"), (gh, "1,90", "1,90")):
        ti(a, f"{base}_over").input(o); ti(a, f"{base}_under").input(u)
    ti(a, f"{ph}_main_book").input("Pinnacle"); ti(a, f"{sn}_away").input("1,90"); ti(a, f"{sn}_home").input("1,92")
    btn(a, f"pm_save_{kid}").click().run()
step("Team Totals und Spread: Quoten eintragen und Speichern (vier Maerkte)", at, fill_team)
tml = lambda side: ps.team_total_lines([v for v in ps.load()["entries"].values() if v["home"] == K][0], side)
check("   Team Totals gespeichert: Gast Hauptlinie + eine Zeile, Heim Hauptlinie", len(tml("away")) == 2 and len(tml("home")) == 1, str([(l["id"], l["line"]) for l in tml("away")]))
at = app().run()
check("Team Totals: Neu laden ohne Warnung", not problems(at), " | ".join(problems(at))[:200])
xg = [t.key for t in at.text_input if (t.key or "").startswith(f"{pa}_x") and t.key.endswith("_line")][0].rsplit("_line", 1)[0]
step("Team Totals: + bei einer gespeicherten Zeile", at, lambda a: btn(a, f"{xg}_plus").click().run())
step("Team Totals: Entfernen (gespeicherte Linie, Revision)", at, lambda a: btn(a, f"{xg}_rm").click().run())
at = app().run()
check("Team Totals: nach dem Entfernen: Gast nur Hauptlinie aktiv, Revision erhalten", len(tml("away")) == 1 and not problems(at))
step("Vier Maerkte: Speichern ohne Aenderung", at, lambda a: btn(a, f"pm_save_{kid}").click().run())
# ---- Markt Spielerpunkte (Kader aus gefaelschter Datei, kein Netz) und Kader-Knopf
import data.rosters as _ro
from roster_fixture import fake_index
_ro.write(_ro.build(fake_index(), dt.datetime.now().astimezone().isoformat(timespec="seconds"), "2026-27"))
_pids = {p["name"]: p["person_id"] for p in _ro.load()["teams"][P] + _ro.load()["teams"][K]}
at = app().run()
pre = f"pm_pp_{kid}"; pb = f"{pre}_n1"
step("Spielerpunkte: + Spieler hinzufuegen", at, lambda a: btn(a, f"{pre}_addblock").click().run())
step("Spielerpunkte: Spieler waehlen (Jokic)", at, lambda a: a.selectbox(key=f"{pb}_who").select(_pids["Nikola Jokić"]).run())
step("Spielerpunkte: Schwelle eingeben", at, lambda a: ti(a, f"{pb}_n1_line").input("19").run())
step("Spielerpunkte: Quote eingeben", at, lambda a: ti(a, f"{pb}_n1_over").input("2,5").run())
step("Spielerpunkte: + Meilenstein hinzufuegen", at, lambda a: btn(a, f"{pb}_addrow").click().run())
step("Spielerpunkte: + bei der Schwelle", at, lambda a: btn(a, f"{pb}_n2_plus").click().run())
step("Spielerpunkte: - bei der Schwelle", at, lambda a: btn(a, f"{pb}_n2_minus").click().run())
step("Spielerpunkte: Buchmacher der ersten Zeile aendern", at, lambda a: ti(a, f"{pb}_n1_book").input("Pinnacle").run())
check("   zweite Zeile: Schwelle 20, Buchmacher folgt (Pinnacle)", ti(at, f"{pb}_n2_line").value == "20" and ti(at, f"{pb}_n2_book").value == "Pinnacle")
step("Spielerpunkte: Moduswechsel auf Einzellinie (ungespeichert)", at, lambda a: a.radio(key=f"{pb}_mode").set_value("Einzellinie").run())
step("Spielerpunkte: Moduswechsel zurueck auf Meilensteine", at, lambda a: a.radio(key=f"{pb}_mode").set_value("Meilensteine").run())
r1 = at.session_state[f"{pb}__new"][0]
step("Spielerpunkte: Entfernen (neue Zeile)", at, lambda a: btn(a, f"{pb}_{r1}_rm").click().run())
def fill_pp(a):
    r = a.session_state[f"{pb}__new"][0] if a.session_state[f"{pb}__new"] else None
    if r is None:
        btn(a, f"{pb}_addrow").click().run(); r = a.session_state[f"{pb}__new"][0]
    ti(a, f"{pb}_{r}_line").input("19"); ti(a, f"{pb}_{r}_over").input("2,5")
    btn(a, f"pm_save_{kid}").click().run()
step("Spielerpunkte: Quote eintragen und Speichern (fuenf Maerkte)", at, fill_pp)
ppl = lambda: ps.active_player_blocks([v for v in ps.load()["entries"].values() if v["home"] == K][0])
check("   Spielerpunkte gespeichert: Nikola Jokić, Meilenstein 19", [b["name"] for b in ppl()] == ["Nikola Jokić"] and ps.player_lines(ppl()[0])[0]["threshold"] == 19, str(ppl()[:1])[:120])
at = app().run()
check("Spielerpunkte: Neu laden ohne Warnung", not problems(at), " | ".join(problems(at))[:200])
step("Spielerpunkte: + bei einer gespeicherten Zeile", at, lambda a: btn(a, f"{pre}_p1_x1_plus").click().run())
step("Spielerpunkte: Entfernen (gespeicherte Zeile, Revision)", at, lambda a: btn(a, f"{pre}_p1_x1_rm").click().run())
at = app().run()
check("Spielerpunkte: nach dem Entfernen Block inaktiv, Daten als Revision erhalten", ppl() == [] and not problems(at))
step("Fuenf Maerkte: Speichern ohne Aenderung", at, lambda a: btn(a, f"pm_save_{kid}").click().run())
check("in jedem Klick-/Eingabeschritt innerhalb einer Sitzung: keine weitere Projektionsberechnung (compute_projection) und keine Abrufe (Odds/BallDontLie/NBA)", _quiet_steps == _total_steps and _total_steps >= 60, f"{_quiet_steps} von {_total_steps} Schritten ohne neue Berechnung")
check("echte Tracking-Datei unveraendert", (hashlib.sha256(real_file.read_bytes()).hexdigest() if real_file.exists() else None) == real_sha)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
