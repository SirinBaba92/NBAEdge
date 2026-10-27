"""Tests: History-Tab (data/history_view.py, ui/history_tab.py). Vorab-Stand, Push, Abweichung, Ergebnis-Rueckgriff auf den Recorder, Anzeige. Nur Temp-Ordner, kein Netz, echte Dateien unveraendert.
Aufruf: venv/bin/python tests/test_history_view.py"""
import hashlib, json, os, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from data import history_view as hv
from ui import history_tab as ht

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real():
    p = ROOT / "data/tracking/projection_snapshots.json"
    return hashlib.sha1(p.read_bytes()).hexdigest()
before = real()

def ver(saved, hs=118, as_=110, exp_total=228.0, exp_spread=8.0, mt=220.0, ms=5.0, wp=0.7):
    return {"saved_at": saved, "projection": {"home_score": hs, "away_score": as_, "exp_total": exp_total, "exp_spread": exp_spread, "market_total": mt, "market_spread": ms, "home_win_prob": wp}}
def game(versions, result=None, start="2026-10-26T23:00:00Z", home="Heim A", away="Gast B"):
    return {"game_date": "2026-10-26", "start_utc": start, "home": home, "away": away, "versions": versions, "result": result}
R = lambda h, a: {"home_points": h, "away_points": a, "recorded_at": "x", "source": "t"}
EV = lambda g, root=None: hv.evaluate("k", g, root)

# Stand vor Anpfiff
g = game([ver("2026-10-26T20:00:00+00:00", exp_total=226.0), ver("2026-10-26T22:59:00Z", exp_total=228.0), ver("2026-10-26T23:00:01Z", exp_total=300.0), ver("2026-10-27T01:00:00+00:00", exp_total=400.0)], R(120, 100))
e = EV(g)
check("letzter Stand VOR Anpfiff zaehlt, spaetere Versionen werden ignoriert", e["pred_total"] == 228.0 and e["forecast_saved_at"] == "2026-10-26T22:59:00Z", e["pred_total"])
check("genau zum Anpfiff gespeichert gilt noch als vorher", hv.pre_game_version(game([ver("2026-10-26T23:00:00Z", exp_total=1.0)]))["projection"]["exp_total"] == 1.0)
check("nur Versionen nach Anpfiff -> keine Vorab-Prognose, Spiel erscheint nicht", EV(game([ver("2026-10-26T23:30:00Z")], R(1, 2))) is None)
check("ohne Ergebnis -> nicht beendet", EV(game([ver("2026-10-26T20:00:00Z")], None)) is None)
check("ohne Anpfiffzeit -> keine Vorab-Prognose", EV(game([ver("2026-10-26T20:00:00Z")], R(1, 2), start=None)) is None)

# Abweichung (Ist - Prognose)
e = EV(game([ver("2026-10-26T20:00:00Z", hs=118, as_=110, exp_total=228.0, exp_spread=8.0)], R(120, 100)))
check("Abweichung Heim/Gast/Total/Spread = Ist - Prognose", (e["dev_home"], e["dev_away"], e["dev_total"], e["dev_spread"]) == (2, -10, -8.0, 12.0) and e["act_total"] == 220 and e["act_spread"] == 20, e)

# Push Total (ganzzahlig 220.0)
e = EV(game([ver("2026-10-26T20:00:00Z", exp_total=228.0, mt=220.0)], R(120, 100)))
check("Total 220 bei Ergebnis 220 = Push (eigenes Ergebnis)", e["total_outcome"] == "push" and e["total_result"] == "Push" and e["total_tip"] == "Über")
e = EV(game([ver("2026-10-26T20:00:00Z", exp_total=228.0, mt=219.5)], R(120, 100)))
check("Total 219,5 bei Ergebnis 220 = Treffer fuer Ueber", e["total_outcome"] == "treffer")
e = EV(game([ver("2026-10-26T20:00:00Z", exp_total=228.0, mt=221.5)], R(120, 100)))
check("Total 221,5, Tipp Ueber, Ergebnis 220 = Fehlschlag", e["total_outcome"] == "fehlschlag" and e["total_result"] == "Unter")
# Push Spread (Heim-Vorsprung 20 gegen Linie 20.0)
e = EV(game([ver("2026-10-26T20:00:00Z", exp_spread=8.0, ms=20.0)], R(120, 100)))
check("Spread-Linie 20 bei Vorsprung 20 = Push", e["spread_outcome"] == "push" and e["spread_result"] == "Push")
e = EV(game([ver("2026-10-26T20:00:00Z", exp_spread=8.0, ms=5.0)], R(120, 100)))
check("Spread: Modell sieht mehr als Linie 5, Heim gewinnt mit 20 -> Treffer", e["spread_outcome"] == "treffer" and e["spread_tip"] == "Heim")
e = EV(game([ver("2026-10-26T20:00:00Z", exp_spread=-2.0, ms=-3.5)], R(100, 101)))
check("Spread: Gast (Linie -3,5), Ergebnis -1 -> Heim deckt, Tipp Heim (-2 > -3,5) = Treffer", e["spread_result"] == "Heim" and e["spread_outcome"] == "treffer")
e = EV(game([ver("2026-10-26T20:00:00Z", exp_total=220.0, mt=220.0)], R(120, 100)))
check("Prognose genau auf der Linie, Ergebnis ebenfalls: Push; sonst kein Tipp", e["total_outcome"] == "push")
e = EV(game([ver("2026-10-26T20:00:00Z", exp_total=220.0, mt=220.0)], R(121, 100)))
check("Prognose genau auf der Linie -> kein Tipp", e["total_outcome"] == "kein_tipp" and e["total_tip"] is None)
e = EV(game([ver("2026-10-26T20:00:00Z", mt=None, ms=None)], R(120, 100)))
check("ohne Linie: nicht bewertet, aber Abweichung vorhanden", e["total_outcome"] is None and e["spread_outcome"] is None and e["dev_total"] is not None)
s = hv.summarize([EV(game([ver("2026-10-26T20:00:00Z", exp_total=228.0, mt=220.0)], R(120, 100))), EV(game([ver("2026-10-26T20:00:00Z", exp_total=228.0, mt=219.5)], R(120, 100))), EV(game([ver("2026-10-26T20:00:00Z", mt=None)], R(120, 100)))])
check("Zaehlung: Push getrennt von Treffer/Fehlschlag", s["total"] == {"treffer": 1, "fehlschlag": 0, "push": 1, "kein_tipp": 0, "ohne_linie": 1} and s["games"] == 3, s["total"])
check("Sieger: Heim favorisiert und gewinnt = Treffer", EV(game([ver("2026-10-26T20:00:00Z", wp=0.7)], R(120, 100)))["winner"] == "treffer" and EV(game([ver("2026-10-26T20:00:00Z", wp=0.7)], R(100, 120)))["winner"] == "fehlschlag")

# Rueckgriff Recorder
with tempfile.TemporaryDirectory() as td:
    d = Path(td) / "2026-10-26" / "0022600001"; d.mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({"home": {"team": "Heim A", "final": 110}, "away": {"team": "Gast B", "final": 102}}))
    e = EV(game([ver("2026-10-26T20:00:00Z")], None), Path(td))
    check("Ergebnis fehlt im Snapshot -> aus dem Recorder", e and e["act_home"] == 110 and e["act_away"] == 102 and e["result_source"] == "recorder")
    check("anderes Spiel im Recorder-Ordner -> kein Ergebnis", EV(game([ver("2026-10-26T20:00:00Z")], None, home="Heim X"), Path(td)) is None)
    e2 = EV(game([ver("2026-10-26T20:00:00Z")], R(1, 2)), Path(td))
    check("Snapshot-Ergebnis hat Vorrang", e2["act_home"] == 1 and e2["result_source"] == "snapshot")

# Anzeige
rows = ht.table_rows([EV(game([ver("2026-10-26T20:00:00Z", exp_total=228.0, mt=220.0)], R(120, 100)))])
check("Anzeige: Push steht als Push da", "Push" in rows[0]["Total"] and "➖" in rows[0]["Total"] and rows[0]["Total-Linie"] == "220,0", rows[0]["Total"])
check("Anzeige: Abweichung mit Vorzeichen", rows[0]["Abw. Total"] == "-8,0")

# Echte Daten 26.10. (nur lesen)
real_rows = [r for r in hv.finished_games() if r["day"] == "2026-10-26"]
check("26.10.: 9 beendete Spiele (Ergebnis aus Snapshot oder, wo dort noch nicht eingetragen, aus dem Recorder)", len(real_rows) == 9 and sum(r["result_source"] == "recorder" for r in real_rows) <= 4, len(real_rows))
check("26.10.: alle Vorab-Staende vor dem Anpfiff", all(hv.pre_game_version({"start_utc": r["start_utc"], "versions": [{"saved_at": r["forecast_saved_at"]}]}) for r in real_rows))
cle = next(r for r in real_rows if "Cleveland" in r["home"])
check("26.10. Cleveland-Minnesota: Ergebnis 127:125 Heim, Prognose 117:117", (cle["act_home"], cle["act_away"], cle["pred_home"], cle["pred_away"]) == (127, 125, 117, 117))
check("echte Snapshot-Datei unveraendert", real() == before)

# AppTest
from streamlit.testing.v1 import AppTest
def _app():
    from ui.history_tab import render_history_tab
    render_history_tab()
at = AppTest.from_function(_app, default_timeout=60).run()
check("Tab rendert ohne Ausnahme, mit Tabelle", not at.exception and len(at.dataframe) == 1 and at.selectbox[0].options[0] == "Alle", [str(e.value) for e in at.exception])
at.selectbox[0].select("2026-10-26").run()
check("Spieltag 26.10. waehlbar: 9 Spiele", not at.exception and len(at.dataframe[0].value) == 9 and at.metric[0].value == "9")
check("echte Snapshot-Datei weiter unveraendert", real() == before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
