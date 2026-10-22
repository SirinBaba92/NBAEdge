"""Tests fuer Schritt 9a: eine Marktlinie je Spiel und Markt (eigene Eingabe gegen Cache, die neuere gewinnt) und die Herkunftszeile in den
Score-Projections-Karten. Offline (tests/fake_net.py, Temp-Verzeichnisse), keine echten Abrufe; echte Tracking-/Kaderdatei und Pickle nur gelesen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_market_lines.py"""
import datetime as dt, hashlib, json, os, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
import data.nba_live as _nba_live
_nba_live.NBA_CACHE_SECONDS = 10 ** 6
import data.market_lines as ml
import data.pre_match_store as ps
import ui.score_cards as sc
from models.elo import MODEL_PATH
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
real_file = ROOT / "data" / "tracking" / "pre_match_entries.json"; real_bytes = real_file.read_bytes() if real_file.exists() else None
real_roster = ROOT / "data" / "rosters.json"; real_roster_bytes = real_roster.read_bytes() if real_roster.exists() else None
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
K, P = "New York Knicks", "Philadelphia 76ers"

def own_entry(at, spread=None, total=None, team=None):
    """Eigene Eingabe in einer Temp-Datei speichern (updated_at = at) und den Eintrag zurueckgeben."""
    fresh_env()
    start = iso(at + 6 * H); rows = [{"id": "main", "line": spread, "home_odds": "1,91", "away_odds": "1,95", "bookmaker": "Betano"}] if spread else None
    trows = [{"id": "main", "direction": None, "line": total, "over_odds": "1,91", "under_odds": "1,89", "bookmaker": "Betano"}] if total else None
    team_rows = {s: [{"id": "main", "direction": None, "line": v, "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}] for s, v in (team or {}).items()} or None
    ps.save_card("2026-10-21", start, K, P, spread_rows=rows, total_rows=trows, team_rows=team_rows, now=at)
    return list(ps.load()["entries"].values())[0]

T = time.time()
def res(entry, cache, cache_at, home=K, away=P):
    return ml.resolve_market_lines(entry, cache, cache_at, "cache_vorab", home, away)

# ===================================================== A) Aufloesung
cache = {"spread": 2.5, "total": 228.5, "team_totals": {}}
e = own_entry(T, total="231,5")
r = res(e, cache, T - 600)["total"]
check("neuere eigene Eingabe gewinnt gegen den Cache (Total 231,5 gegen 228,5)", r["line"] == 231.5 and r["source"] == "eigene Eingabe" and r["bookmaker"] == "Betano" and r["cache_line"] == 228.5 and abs(r["at"] - T) < 2, str(r))
r = res(e, cache, T + 600)["total"]
check("neuerer Cache gewinnt gegen die eigene Eingabe", r["line"] == 228.5 and r["source"] == "Cache" and r["own_line"] == 231.5 and r["bookmaker"] == "")
own_at = ml.own_candidates(e)["total"]["at"]
r = res(e, cache, own_at)["total"]
check("Gleichstand: die eigene Eingabe gewinnt", r["source"] == "eigene Eingabe" and r["line"] == 231.5)
r = res(e, cache, own_at + 0.5)["total"]
check("Cache 0,5 s spaeter: Cache gewinnt (kein Gleichstand mehr)", r["source"] == "Cache")
e2 = json.loads(json.dumps(e)); e2["markets"]["total"]["lines"][0]["active"] = False
r = res(e2, cache, T - 600)["total"]
check("entfernte Eingabe (active: false) zaehlt nicht: es gilt der Cache", r["line"] == 228.5 and r["source"] == "Cache" and r["own_line"] is None)
ex = json.loads(json.dumps(e)); ex["markets"]["total"]["lines"].append({"id": "x1", "role": "extra", "direction": "higher", "active": True, "line": 240.5, "over_odds": 1.9, "under_odds": 1.9, "bookmaker": "B", "updated_at": e["markets"]["total"]["updated_at"], "revisions": []})
check("nur die Hauptlinie zaehlt (weitere Linien nicht)", res(ex, cache, T - 600)["total"]["line"] == 231.5)
rr = res(e, cache, T - 600)
check("nur ein Markt eingetragen (Total): Spread bleibt Cache, Team Totals ohne Linie", rr["spread"]["source"] == "Cache" and rr["spread"]["line"] == 2.5 and rr["team_total_away"]["line"] is None and rr["team_total_home"]["source"] is None)
rr = res(None, cache, T - 600)
check("ohne Eingabe: wie bisher der Cache (Spread 2,5, Total 228,5), Quelle Cache", rr["spread"]["line"] == 2.5 and rr["total"]["line"] == 228.5 and rr["total"]["source"] == "Cache")
rr = res(e, None, None)
check("ohne Cache: die eigene Eingabe (Total), sonst keine Linie", rr["total"]["line"] == 231.5 and rr["total"]["source"] == "eigene Eingabe" and rr["spread"]["line"] is None and rr["spread"]["source"] is None)
rr = res(None, None, None)
check("ohne beides: keine Linie (alle vier Maerkte None)", all(rr[m]["line"] is None and rr[m]["source"] is None for m in ml.MARKETS))
check("projection_inputs: (market_total, market_spread) None ohne Linie", ml.projection_inputs(rr) == (None, None))
# Vorzeichen
e = own_entry(T, spread="-4,5")
r = res(e, {"spread": 1.0}, T - 600)["spread"]
check("Spread-Vorzeichen: Eingabe Heim -4,5 (Heim Favorit) -> market_spread +4,5 (positiv = Heim Favorit); Gast waere +4,5", r["line"] == 4.5 and r["source"] == "eigene Eingabe", str(r["line"]))
e = own_entry(T, spread="+3")
r = res(e, {"spread": 1.0}, T - 600)["spread"]
check("Spread-Vorzeichen: Eingabe Heim +3 (Gast Favorit, Gast -3) -> market_spread -3,0", r["line"] == -3.0, str(r["line"]))
e = own_entry(T, spread="0")
r = res(e, {"spread": 1.0}, T - 600)["spread"]
check("Pick'em: Eingabe 0 -> market_spread 0,0 (nicht -0,0)", r["line"] == 0.0 and str(r["line"]) == "0.0")
e = own_entry(T, spread="-4,5")
cache_pos = {"spread": 4.5}                                      # Cache: Heim -4,5 = +4,5 in der Projekt-Konvention
check("gleiche Linie in beiden Quellen: Abweichung 0, kein Hinweis", res(e, cache_pos, T - 60)["spread"]["deviation"] == 0 and not res(e, cache_pos, T - 60)["spread"]["warn"])
# Team Totals
e = own_entry(T, team={"away": "113,5", "home": "118"})
rr = res(e, {"spread": 4.5, "total": 231.5, "team_totals": {}}, T - 600)
check("Team Total Gast/Heim: eigene Eingabe (113,5 / 118,0), Cache kennt keine Team Totals", rr["team_total_away"]["line"] == 113.5 and rr["team_total_home"]["line"] == 118.0 and rr["team_total_away"]["source"] == "eigene Eingabe" and rr["team_total_away"]["cache_line"] is None)
cache_tt = {"spread": 4.5, "total": 231.5, "team_totals": {"New York Knicks": {"line": 118.5}, "Philadelphia 76ers": {"line": 113.0}}}
rr = res(e, cache_tt, T + 100)
check("Team Totals aus dem Cache (Name -> Gast/Heim richtig zugeordnet): neuerer Cache gewinnt (Gast 113,0 / Heim 118,5)", rr["team_total_away"]["line"] == 113.0 and rr["team_total_home"]["line"] == 118.5 and rr["team_total_away"]["source"] == "Cache")
# gestartetes Spiel: eigene Eingaben sind Vorab-Linien und gelten weiter (Schritt 9b, Teil 1)
e_started = own_entry(T, spread="-4,5", total="231,5")
r1 = res(e_started, cache, T - 600)
check("Eingabe gilt unabhaengig vom Spielzustand (keine pregame-Unterscheidung mehr): gleiche Aufloesung vor und nach Anpfiff", r1["total"]["source"] == "eigene Eingabe" and r1["total"]["line"] == 231.5 and r1["spread"]["line"] == 4.5 and res(e_started, cache, T - 600) == r1)
import inspect
check("resolve_market_lines hat keinen Parameter fuer den Spielzustand", "pregame" not in inspect.signature(ml.resolve_market_lines).parameters)
r2 = res(e_started, {"spread": 2.5, "total": 228.5}, T + 7200)
check("fuer gestartete Spiele zaehlt aus dem Cache nur die gespeicherte Vorab-Linie: ein spaeterer 'gespeichert'-Zeitpunkt vor Anpfiff ist moeglich, eine Live-Linie nie (pregame_lines.py), hier: spaeter Cache gewinnt gegen aeltere Eingabe", r2["total"]["source"] == "Cache")
# Plausibilitaet
e = own_entry(T, spread="-4,5", total="236,5", team={"away": "118,5"})
rr = res(e, {"spread": 0.4, "total": 228.5, "team_totals": {"Philadelphia 76ers": {"line": 113.5}}}, T - 600)
check("Hinweis ab Abweichung > Schwelle (Spread 4,1 > 4,0; Total 8,0 nicht; Team Total 5,0 nicht)", rr["spread"]["warn"] and not rr["total"]["warn"] and not rr["team_total_away"]["warn"] and rr["total"]["deviation"] == 8.0 and rr["team_total_away"]["deviation"] == 5.0, str({m: (rr[m]["deviation"], rr[m]["warn"]) for m in ml.MARKETS}))
rr = res(own_entry(T, total="236,5"), {"total": 228.0}, T - 600)
check("Total 8,5 Abweichung: Hinweis, die eigene Linie wird trotzdem benutzt", rr["total"]["warn"] and rr["total"]["line"] == 236.5 and rr["total"]["source"] == "eigene Eingabe")
check("Schwellen sind Konstanten: Spread 4,0 / Total 8,0 / Team Total 5,0", ml.DEVIATION_LIMITS == {"spread": 4.0, "total": 8.0, "team_total_away": 5.0, "team_total_home": 5.0})
# Datei-Aenderung
fresh_env(); ps.store_path().parent.mkdir(parents=True, exist_ok=True)
a1 = ml.load_entries(); a2 = ml.load_entries()
check("ohne Datei: leere Eintraege, wiederholtes Lesen liefert dasselbe Objekt (nur mtime-Pruefung)", a1 == {} and a1 is a2)
ps.save_card("2026-10-21", iso(T + 6 * H), K, P, total_rows=[{"id": "main", "direction": None, "line": "231,5", "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "B"}], now=T)
b1 = ml.load_entries(); b2 = ml.load_entries()
check("Datei neu geschrieben: Aenderung wird erkannt (neue Eintraege), danach wieder gecacht", len(b1) == 1 and b1 is b2 and b1 is not a1)
sig = ml.entries_signature(); ps.save_card("2026-10-21", iso(T + 6 * H), K, P, total_rows=[{"id": "main", "direction": None, "line": "232,5", "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "B"}], now=T + 5)
check("Datei geaendert (zweites Speichern): Signatur und Inhalt neu", ml.entries_signature() != sig and list(ml.load_entries().values())[0]["markets"]["total"]["lines"][0]["line"] == 232.5)

# ===================================================== B) Oberflaeche (AppTest): Karten, Projektion, Datei-Aenderung
fresh_env(remaining=400)
n = time.time()
def mk_event(home, away, total, home_points, commence, eid):
    bms = []
    for bk, hp in zip(("pinnacle", "draftkings", "fanduel")[:len(home_points)], home_points):
        ms = [{"key": "totals", "last_update": iso(n - 700), "outcomes": [{"name": "Over", "point": total, "price": 1.9}, {"name": "Under", "point": total, "price": 1.9}]},
              {"key": "spreads", "last_update": iso(n - 700), "outcomes": [{"name": home, "point": hp, "price": 1.9}, {"name": away, "point": -hp, "price": 1.9}]}]
        bms.append({"key": bk, "last_update": iso(n - 700), "markets": ms})
    return {"id": eid, "home_team": home, "away_team": away, "commence_time": iso(commence), "bookmakers": bms}
state["commence_offsets"] = {K: 3 * H, "San Antonio Spurs": 3 * H, "Detroit Pistons": -600}
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu",
    "data": [mk_event(K, P, 232.0, [-4.5, -4.5, -4.0], n + 3 * H, "ev-k")]}}, "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
import engine.projection as _proj
_calls = {"n": 0}; _orig_cp = _proj.compute_projection
def _counting(*a, **k):
    _calls["n"] += 1; return _orig_cp(*a, **k)
_proj.compute_projection = _counting
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def net(): return (len(state["odds_calls"]), state["bdl_calls"], state["nba_calls"])
def pj(at, home): return [x for x in at.session_state["projections"] if x["home_team"] == home][0]
def cards(at): return [m.value for m in at.markdown if 'class="pc-card' in m.value]
def card_of(at, home): return [c for c in cards(at) if f">{sc.team_info(home)['nick']}<" in c][0]
def hhmm(ts): return sc._hhmm(ts)

at = app().run(); cp0 = _calls["n"]; net0 = net()
k0 = dict(pj(at, K)); others0 = {x["home_team"]: (x["exp_total"], x["exp_spread"], x["home_score"], x["away_score"]) for x in at.session_state["projections"]}
ml_k = pj(at, K)["market_lines"]
check("Start ohne Eingaben: Marktlinien = Cache (Total 232,0, Spread 4,3), Quelle Cache mit Abrufzeit, market_source wie bisher 'cache_vorab'", pj(at, K)["market_total"] == 232.0 and pj(at, K)["market_spread"] == 4.3 and ml_k["total"]["source"] == "Cache" and pj(at, K)["market_source"] == "cache_vorab" and abs(ml_k["total"]["at"] - (n - 600)) < 2, str(ml_k["total"]))
txt = card_of(at, K)
check(f"Herkunftszeile ohne Eingabe: 'Spread: Cache {hhmm(n - 600)} | Total: Cache {hhmm(n - 600)} | Team Totals: keine Linie'", f"Spread: Cache {hhmm(n - 600)} | Total: Cache {hhmm(n - 600)} | Team Totals: keine Linie" in txt, txt[txt.find("pc-origin"):][:200])
sp_card = card_of(at, "San Antonio Spurs")
check("Spiel ohne Linie (Spurs): 'Alle Linien: keine Linie'", "Alle Linien: keine Linie" in sp_card)
check("Start: keine Exception/Warnung", not page_checks.problems(at), str(page_checks.problems(at)))
# eigene Eingabe speichern (Temp-Tracking-Verzeichnis der Umgebung!)
t_save = time.time(); start_k = ps.normalize_start(pj(at, K)["game_start"])
ps.save_card(pj(at, K)["game_date"], start_k, K, P, total_rows=[{"id": "main", "direction": None, "line": "245,5", "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}],
             team_rows={"away": [{"id": "main", "direction": None, "line": "113,5", "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}], "home": [{"id": "main", "direction": None, "line": "130", "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}]}, now=t_save)
at.run()
check("Datei geaendert -> naechster Rerun nutzt die neue Linie: market_total 245,5 (eigene Eingabe, Betano), Spread bleibt Cache", pj(at, K)["market_total"] == 245.5 and pj(at, K)["market_lines"]["total"]["source"] == "eigene Eingabe" and pj(at, K)["market_lines"]["spread"]["source"] == "Cache" and pj(at, K)["market_spread"] == 4.3)
check("nur das betroffene Spiel wurde neu berechnet (1 compute_projection), andere Spiele unveraendert, KEIN API-Abruf", _calls["n"] == cp0 + 1 and all((x["exp_total"], x["exp_spread"], x["home_score"], x["away_score"]) == others0[x["home_team"]] for x in at.session_state["projections"] if x["home_team"] != K) and net() == net0, f"+{_calls['n'] - cp0} Berechnungen, Abrufe {net0} -> {net()}")
rk = _orig_cp(pj(at, K)["_line_inputs"]["pred"], market_total=245.5, market_spread=4.3, game_date=pj(at, K)["game_date"], bias_adjustments=at.session_state["bias_adjustments"])
check("Projektionszahlen = Rechnung der bestehenden Logik mit der eigenen Linie (Blend unveraendert)", pj(at, K)["exp_total"] == rk["exp_total"] and pj(at, K)["home_score"] == rk["home_score"] and pj(at, K)["market_weight"] == rk["market_weight"] and pj(at, K)["exp_total"] != k0["exp_total"], f"{pj(at, K)['exp_total']} vs {k0['exp_total']}")
txt = card_of(at, K)
check(f"Karte gemischt: 'Spread: Cache ... | Total: Eigene Linie · Betano · {hhmm(t_save)} | Team Totals: Gast Eigene Linie ... / Heim Eigene Linie ...' (Team Totals gleich -> eine Angabe)",
      f"Spread: Cache {hhmm(n - 600)} | Total: Eigene Linie · Betano · {hhmm(t_save)} | Team Totals: Eigene Linie · Betano · {hhmm(t_save)}" in txt, txt[txt.find("pc-origin"):][:200])
check("gelber Hinweis bei starker Abweichung: Total 245,5 vs. 232,0 (> 8,0) und Team Total Heim 130 (Cache ohne Team Totals: kein Hinweis)", "Total: Eigene Linie weicht stark vom Cache ab (245,5 vs. 232,0), bitte prüfen" in txt and "Team Total Knicks: Eigene Linie weicht" not in txt)
check("Pre-Match-Tab: Vorschlag bleibt die Cache-Linie (232,0), nicht die eigene (245,5) - kein Kreislauf", pj(at, K)["cache_market_total"] == 232.0 and [c.value for c in at.caption if "Vorschlag aus Markt (Vorab-Linie): 232,0" in c.value])
# unveraendert -> keine Neuberechnung
cp1 = _calls["n"]; at.run()
check("Rerun ohne Dateiaenderung: keine Neuberechnung", _calls["n"] == cp1)
# Eintrag verschwindet (active: false) -> Cache und Zahlen wie vorher
d = json.loads(ps.store_path().read_text()); ent = list(d["entries"].values())[0]; ent["markets"]["total"]["lines"][0]["active"] = False
for sd in ("away", "home"): ent["markets"]["team_totals"][sd]["lines"][0]["active"] = False
ps.store_path().write_text(json.dumps(d))
at.run()
check("Eingabe entfernt (active: false): zurueck auf den Cache, Projektion wieder wie vor der Eingabe", pj(at, K)["market_total"] == 232.0 and pj(at, K)["exp_total"] == k0["exp_total"] and pj(at, K)["home_score"] == k0["home_score"] and pj(at, K)["market_lines"]["total"]["source"] == "Cache" and net() == net0)
# Spread eigene Eingabe, Vorzeichen in der Projektion
ps.save_card(pj(at, K)["game_date"], start_k, K, P, spread_rows=[{"id": "main", "line": "-6,5", "home_odds": "1,91", "away_odds": "1,95", "bookmaker": "Betano"}], now=time.time())
at.run()
check("Spread eigene Eingabe Heim -6,5 (Heim Favorit) -> market_spread +6,5 in der Projektion; Karte zeigt 'Knicks −6,5' als Marktwert", pj(at, K)["market_spread"] == 6.5 and "Knicks −6,5" in card_of(at, K))
check("Spread: Hinweis bei Abweichung 2,2 (6,5 vs. 4,3) nicht, Quelle 'Eigene Linie · Betano'", "Spread: Eigene Linie · Betano" in card_of(at, K) and "Spread: Eigene Linie weicht" not in card_of(at, K))
# gestartetes Spiel: die eigene Eingabe (vor dem Anpfiff gespeichert) gilt weiter
pist = pj(at, "Detroit Pistons"); st_start = ps.normalize_start(pist["game_start"]); st_ts = ps.parse_utc(st_start)
before = (pist["market_total"], pist["exp_total"]); cp2 = _calls["n"]
ps.save_card(pist["game_date"], st_start, "Detroit Pistons", pist["away_team"], total_rows=[{"id": "main", "direction": None, "line": "250", "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}], now=st_ts - 30)
at.run()
pp = pj(at, "Detroit Pistons")
check("gestartetes Spiel (Pistons, vor Anpfiff eingetragen): die eigene Linie gilt weiter (market_total 250, Quelle 'eigene Eingabe'), genau dieses Spiel neu berechnet, kein Abruf", pp["market_total"] == 250.0 and pp["market_lines"]["total"]["source"] == "eigene Eingabe" and pp["exp_total"] != before[1] and _calls["n"] == cp2 + 1 and net() == net0, f"{before} -> {pp['market_total']}, {pp['exp_total']}")
cp3 = _calls["n"]; exp_after = pp["exp_total"]; at.run()
check("Projektion des gestarteten Spiels aendert sich bei weiteren Reruns nicht (keine Neuberechnung, gleiche Zahlen)", _calls["n"] == cp3 and pj(at, "Detroit Pistons")["exp_total"] == exp_after)
check("Karte des gestarteten Spiels zeigt 'Total: Eigene Linie · Betano'", "Total: Eigene Linie · Betano" in card_of(at, "Detroit Pistons"))
# Reproduzierbarkeit ohne Eingaben
fresh_env(); Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu",
    "data": [mk_event(K, P, 232.0, [-4.5, -4.5, -4.0], n + 3 * H, "ev-k")]}}, "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
at2 = app().run()
check("ohne Eingaben: dieselben Zahlen wie zu Beginn (Projektion unveraendert gegenueber vor der Aenderung)", pj(at2, K)["exp_total"] == k0["exp_total"] and pj(at2, K)["exp_spread"] == k0["exp_spread"] and pj(at2, K)["home_score"] == k0["home_score"] and pj(at2, K)["away_score"] == k0["away_score"])
check("echtes Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
check("echte Tracking-Datei byte-identisch", (real_file.read_bytes() if real_file.exists() else None) == real_bytes)
check("echte Kaderdatei byte-identisch", (real_roster.read_bytes() if real_roster.exists() else None) == real_roster_bytes)
check("in KEINEM AppTest-Lauf Exception oder 'default value'-Satz", not page_checks.bad, str(page_checks.bad[:3]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
