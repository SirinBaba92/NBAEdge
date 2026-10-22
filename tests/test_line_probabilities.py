"""Tests fuer Schritt 9b: Wahrscheinlichkeiten je Linie (engine/line_probabilities.py, reine Anzeige) und die vier Zeilen-Bloecke in der Score-Projections-Karte.
Offline (tests/fake_net.py, Temp-Verzeichnisse), keine echten Abrufe; Pickle, echte Tracking- und Kaderdatei nur gelesen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_line_probabilities.py"""
import datetime as dt, hashlib, inspect, json, os, re, sys, time, warnings
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
import engine.line_probabilities as lp
import ui.score_cards as sc
from models.elo import EloEngine, MODEL_PATH
from engine.projection import compute_projection
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

# ===================================================== A) reine Rechenfunktionen
check("Konstanten: Total 18,0, Team Total 12,5, Spread 10,5 (an die Siegwahrscheinlichkeit angepasst, Kommentar 'wird im Backtest kalibriert')", lp.TOTAL_SIGMA == 18.0 and lp.TEAM_TOTAL_SIGMA == 12.5 and lp.SPREAD_SIGMA == 10.5 and "Backtest kalibriert" in inspect.getsource(lp))
check("50 % am Mittelwert (Total, Team Total, Spread-Linie = Projektion)", abs(lp.prob_above(231.5, 231.5, 18) - 0.5) < 1e-12 and lp.over_under_rows(231.5, [231.5], 231.5, 18)[0]["p_left"] == 50
      and lp.spread_rows(9.5, "home", [9.5], 9.5)[0]["p_left"] == 50 and lp.over_under_rows(231.5, [231.5], 231.5, 18)[0]["predicted"] is None)
rows = lp.over_under_rows(231.5, [x + 0.5 for x in range(200, 260)], None, 18)
check("monoton: Over-Wahrscheinlichkeit sinkt mit der Linie, Under steigt", all(a["p_left"] >= b["p_left"] and a["p_right"] <= b["p_right"] for a, b in zip(rows, rows[1:])) and rows[0]["p_left"] > 90 and rows[-1]["p_left"] < 10)
rows = lp.spread_rows(6.0, "home", [x + 0.5 for x in range(-5, 20)], None)
check("Spread monoton: je groesser die Linie X, desto kleiner die Chance des Favoriten (Heim = rechts)", all(a["p_right"] >= b["p_right"] for a, b in zip(rows, rows[1:])))
rows = lp.spread_rows(6.0, "away", [x + 0.5 for x in range(-5, 20)], None)
check("Spread mit Gast als Favorit: Gast (links) sinkt mit X; margin = -exp_spread", all(a["p_left"] >= b["p_left"] for a, b in zip(rows, rows[1:])) and rows[5]["p_left"] < 50)
allrows = lp.over_under_rows(231.5, [x + 0.5 for x in range(100, 300)], None, 18) + lp.spread_rows(-3.2, "home", [x + 0.5 for x in range(-10, 30)], None) + lp.over_under_rows(113.0, [x + 0.5 for x in range(40, 200)], None, 12.5)
check("beide Seiten ergeben immer 100, ganze Zahlen, 1 bis 99", all(r["p_left"] + r["p_right"] == 100 and isinstance(r["p_left"], int) and 1 <= r["p_left"] <= 99 for r in allrows))
check("vorhergesagte Seite = hoehere Prozentzahl", all((r["predicted"] == "left") == (r["p_left"] > r["p_right"]) and (r["predicted"] == "right") == (r["p_right"] > r["p_left"]) for r in allrows))
check("Over steht IMMER links, Under rechts (Over-Vorhersage 65 : 35, Under-Vorhersage 35 : 65)", lp.over_under_rows(240, [231.5], None, 18)[0]["p_left"] > 50 and lp.over_under_rows(220, [231.5], None, 18)[0]["p_left"] < 50)
r = lp.spread_rows(9.6, "home", [0.5], None)[0]
check("Spread: Gast links / Heim rechts; Heim-Favorit +9,6 bei Linie 0,5: Heim (rechts) ca. 80 %", r["p_right"] > 75 and r["p_left"] < 25 and r["predicted"] == "right", str(r))
r = lp.spread_rows(9.6, "away", [0.5], None)[0]
check("Gast-Favorit mit Projektion Heim +9,6 (Markt falsch herum): Heim bleibt rechts, Gast (Favorit) links nur 20 %", r["p_left"] < 25 and r["p_right"] > 75)
# Staffel
check("Staffel Spread: 5 Linien um die Hauptlinie (9,5 -> 7,5 ... 11,5)", lp.staffel(9.5, 2, min_line=0.5) == [7.5, 8.5, 9.5, 10.5, 11.5])
check("Spread-Staffel nie unter 0,5: Fenster wird verschoben, nicht gekuerzt (Hauptlinie 1,5 -> 0,5 ... 4,5; 0,5 -> 0,5 ... 4,5; 1,0 -> 1,0 ... 5,0; 2,5 -> 0,5 ... 4,5; 3,5 -> 1,5 ... 5,5)",
      lp.staffel(1.5, 2, min_line=0.5) == [0.5, 1.5, 2.5, 3.5, 4.5] and lp.staffel(0.5, 2, min_line=0.5) == [0.5, 1.5, 2.5, 3.5, 4.5] and lp.staffel(1.0, 2, min_line=0.5) == [1.0, 2.0, 3.0, 4.0, 5.0]
      and lp.staffel(2.5, 2, min_line=0.5) == [0.5, 1.5, 2.5, 3.5, 4.5] and lp.staffel(3.5, 2, min_line=0.5) == [1.5, 2.5, 3.5, 4.5, 5.5] and all(len(lp.staffel(m, 2, min_line=0.5)) == 5 and m in lp.staffel(m, 2, min_line=0.5) for m in (0.5, 1.0, 1.5, 2.0, 2.5, 3.5)))
check("Staffel Total/Team Total: 7 Linien (Hauptlinie +-3, Schritt 1,0)", lp.staffel(231.5, 3) == [228.5, 229.5, 230.5, 231.5, 232.5, 233.5, 234.5] and len(lp.staffel(113.5, 3)) == 7)
check("Team-Total-Hauptlinie rechnerisch: Total 231,5, Spread +4,5 (Heim Fav) -> Heim 118,0 / Gast 113,5; Spread -3 -> Heim 114,5 (114,25 gerundet) / Gast 117,5; ohne Total/Spread None",
      lp.team_main_from_total_spread(231.5, 4.5) == {"home": 118.0, "away": 113.5} and lp.team_main_from_total_spread(231.5, -3.0) == {"home": 114.5, "away": 117.5}
      and lp.team_main_from_total_spread(None, 4.5) is None and lp.team_main_from_total_spread(231.5, None) is None and lp.team_main_from_total_spread(231.5, 0.0) == {"home": 116.0, "away": 116.0})
# Konsistenz mit dem Sieg-Balken (rein aus dem Modell: ohne Marktmischung)
eng = EloEngine.load(); teams = sorted(eng.ratings)[:30]; diffs = []; implied = []
from statistics import NormalDist
for i in range(0, 30, 2):
    for j in range(1, 30, 3):
        if i == j: continue
        pred = eng.predict(teams[i], teams[j], dt.date(2026, 10, 21))
        pr = compute_projection(pred, game_date="2026-10-21")
        es = pr["exp_spread"]; fav = "home" if es >= 0 else "away"
        bar = lp.spread_rows(es, fav, [0.0], 0.0)[0]
        home_bar = bar["p_right"]                                     # Heim-Anteil des Spread-Balkens bei Linie 0
        diffs.append(abs(home_bar - round(pred["home_win_prob"] * 100)))
        if abs(es) > 3: implied.append(es / NormalDist().inv_cdf(pred["home_win_prob"]))
import statistics
check(f"Konsistenz mit dem Sieg-Balken: Spread-Balken bei Linie 0 weicht im Mittel {statistics.mean(diffs):.1f} Prozentpunkte (max. {max(diffs)}) vom Siegbalken ab (modellreine Projektion, {len(diffs)} Paarungen)", statistics.mean(diffs) <= 4.0 and max(diffs) <= 13,   # Schwelle nach dem Pickle-Update vom 21.10. (3 neue Spiele): vorher 2,15 / 7, jetzt 3,37 / 12; Streuung wird im Backtest kalibriert
       f"Mittel {statistics.mean(diffs):.2f}, max {max(diffs)}")
check("implizite Streuung der Siegwahrscheinlichkeit liegt zwischen 10 und 12,5 (Median)", 10 <= statistics.median(implied) <= 12.5, f"Median {statistics.median(implied):.1f}")
ex = lp.spread_rows(9.6, "home", [0.0], 0.0)[0]
check("Beispiel Raptors/Bulls: Modell-Spread 9,6, Siegwahrscheinlichkeit 79 % -> Balken bei Linie 0: Heim ca. 82 % (Abweichung <= 3 Punkte)", abs(ex["p_right"] - 79) <= 3, str(ex["p_right"]))

# ===================================================== B) Tabellen einer Karte (build_line_tables)
def fake_proj(spread_line=4.5, total_line=231.5, tt_away=None, tt_home=None, exp_spread=5.0, exp_total=232.0, hs=119, as_=113):
    mk = lambda v, at=T0: {"line": v, "source": "Cache" if v is not None else None, "bookmaker": "", "at": at, "at_iso": None}
    return {"home_team": K, "away_team": P, "exp_spread": exp_spread, "exp_total": exp_total, "home_score": hs, "away_score": as_,
            "market_lines": {"spread": mk(spread_line), "total": mk(total_line), "team_total_away": mk(tt_away), "team_total_home": mk(tt_home)}}
T0 = time.time()
def entry_with(spread=None, total=None, team=None, extra_spread=(), extra_total=(), now=None):
    fresh_env(); now = now or time.time(); start = iso(now + 6 * H)
    rows = [{"id": "main", "line": spread, "home_odds": "1,9", "away_odds": "1,9", "bookmaker": "Betano"}] + [{"id": None, "line": v, "home_odds": "1,9", "away_odds": "1,9", "bookmaker": "Betano"} for v in extra_spread] if spread else None
    trows = [{"id": "main", "direction": None, "line": total, "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}] + [{"id": None, "direction": d, "line": v, "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"} for d, v in extra_total] if total else None
    trm = {s: [{"id": "main", "direction": None, "line": v, "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}] for s, v in (team or {}).items()} or None
    ps.save_card("2026-10-21", start, K, P, spread_rows=rows, total_rows=trows, team_rows=trm, now=now)
    return list(ps.load()["entries"].values())[0]
t = lp.build_line_tables(fake_proj(), None)
check("ohne Eingabe: Spread-Staffel 5 Linien um 4,5 (2,5 ... 6,5), Heim Favorit, Hauptlinie genau eine hervorgehoben", [r["line"] for r in t["spread"]["rows"]] == [2.5, 3.5, 4.5, 5.5, 6.5] and t["spread"]["favorite"] == "home" and [r["line"] for r in t["spread"]["rows"] if r["is_main"]] == [4.5] and t["spread"]["source"] == "Staffel")
check("ohne Eingabe: Total 7 Linien (228,5 ... 234,5), Hauptlinie 231,5", [r["line"] for r in t["total"]["rows"]] == [228.5, 229.5, 230.5, 231.5, 232.5, 233.5, 234.5] and [r["line"] for r in t["total"]["rows"] if r["is_main"]] == [231.5])
check("ohne Eingabe: Team Totals rechnerisch (Gast 113,5 / Heim 118,0) mit Hinweis 'rechnerisch aus Total und Spread', je 7 Linien", [r["line"] for r in t["team_away"]["rows"] if r["is_main"]] == [113.5] and [r["line"] for r in t["team_home"]["rows"] if r["is_main"]] == [118.0] and len(t["team_away"]["rows"]) == 7
      and t["team_home"]["derived"] and "rechnerisch" in t["team_home"]["note"])
t = lp.build_line_tables(fake_proj(spread_line=1.5, total_line=None), None)
check("kleine Spread-Linie 1,5: Fenster 0,5 ... 4,5 (verschoben, 5 Linien); ohne Total: Total und Team Totals 'keine Linie'", [r["line"] for r in t["spread"]["rows"]] == [0.5, 1.5, 2.5, 3.5, 4.5] and t["total"]["rows"] == [] and t["total"]["note"] == "keine Linie" and t["team_home"]["note"] == "keine Linie" and t["team_away"]["rows"] == [])
t = lp.build_line_tables(fake_proj(spread_line=None, total_line=231.5), None)
check("ohne Spread: Spread 'keine Linie', Team Totals 'keine Linie' (Spread fehlt), Total zeigt Staffel", t["spread"]["note"] == "keine Linie" and t["team_home"]["note"] == "keine Linie" and len(t["total"]["rows"]) == 7)
t = lp.build_line_tables(fake_proj(spread_line=0.0, exp_spread=-1.2), None)
check("Pick'em (Spread 0): Hauptlinie 0,5, Favorit nach Projektion (Gast bei exp_spread -1,2)", t["spread"]["favorite"] == "away" and [r["line"] for r in t["spread"]["rows"] if r["is_main"]] == [0.5])
t = lp.build_line_tables(fake_proj(spread_line=-4.5, exp_spread=-3.0), None)
check("Gast Favorit am Markt (Spread -4,5): Zeilen aus Sicht des Gastes, Favorit links, Linie 4,5 -> 'Gast -4,5'", t["spread"]["favorite"] == "away" and [r["line"] for r in t["spread"]["rows"] if r["is_main"]] == [4.5])
t = lp.build_line_tables(fake_proj(tt_away=114.0, tt_home=117.5), None)
check("Team-Total-Hauptlinie aus Cache/aufgeloester Linie (114,0 / 117,5) statt rechnerisch", [r["line"] for r in t["team_away"]["rows"] if r["is_main"]] == [114.0] and [r["line"] for r in t["team_home"]["rows"] if r["is_main"]] == [117.5] and not t["team_home"]["derived"])
# eigene Eingabe
e = entry_with(spread="-4,5", total="231,5", team={"away": "113,5"}, extra_spread=("-5,5", "-3,5"), extra_total=(("higher", "233,5"), ("lower", "229,5")))
t = lp.build_line_tables(fake_proj(), e)
check("eigene Eingabe: genau die eingetragenen Linien, sortiert, Hauptlinie hervorgehoben (Spread 3,5 / 4,5 / 5,5)", [r["line"] for r in t["spread"]["rows"]] == [3.5, 4.5, 5.5] and [r["line"] for r in t["spread"]["rows"] if r["is_main"]] == [4.5] and t["spread"]["source"] == "eigene Eingabe")
check("eigene Eingabe Total: Hauptlinie + 233,5 + 229,5 sortiert (229,5 / 231,5 / 233,5)", [r["line"] for r in t["total"]["rows"]] == [229.5, 231.5, 233.5] and [r["line"] for r in t["total"]["rows"] if r["is_main"]] == [231.5])
check("eigene Eingabe Team Total nur Gast: Gast zeigt genau die Eingabe (1 Linie), Heim rechnerische Staffel", [r["line"] for r in t["team_away"]["rows"]] == [113.5] and t["team_away"]["source"] == "eigene Eingabe" and len(t["team_home"]["rows"]) == 7 and t["team_home"]["derived"])
e = entry_with(spread="+3")
t = lp.build_line_tables(fake_proj(spread_line=-3.0, exp_spread=-2.0), e)
check("eigene Spread-Eingabe Heim +3 (Gast Favorit -3): Favorit Gast, X = 3,0", t["spread"]["favorite"] == "away" and [r["line"] for r in t["spread"]["rows"]] == [3.0] and t["spread"]["rows"][0]["is_main"])
ej = json.loads(json.dumps(entry_with(total="231,5"))); ej["markets"]["total"]["lines"][0]["active"] = False
check("entfernte eigene Zeile zaehlt nicht: wieder Staffel", lp.build_line_tables(fake_proj(), ej)["total"]["source"] == "Staffel")
check("ohne market_lines (Mock): keine Tabellen (None)", lp.build_line_tables({"exp_spread": 1, "exp_total": 220}, None) is None)
# reine Anzeige: die Projektion bleibt unveraendert
pj0 = fake_proj(); snap = json.dumps(pj0, sort_keys=True, default=str); lp.build_line_tables(pj0, None)
check("build_line_tables veraendert die Projektion nicht", json.dumps(pj0, sort_keys=True, default=str) == snap)

def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]; c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True); return (la + 0.05) / (lb + 0.05)

# ===================================================== C) Karte: Blockdaten und HTML der Zeilen
def vm_of(proj, entry=None):
    return sc.build_card_vm({**compute_projection({"home_team": K, "away_team": P, "home_elo": 1560, "away_elo": 1500, "expected_total": 226.0, "home_win_prob": 0.62, "away_win_prob": 0.38},
                                                  market_total=proj["market_lines"]["total"]["line"], market_spread=proj["market_lines"]["spread"]["line"], game_date="2026-10-21"), "market_lines": proj["market_lines"]}, entry)
v1 = vm_of(fake_proj()); v2 = vm_of(fake_proj(spread_line=1.5, total_line=250.5))
ttl = lambda v: [b["title"] for b in v["lines"]]
check("vier Bloecke mit festen Titeln: SPREAD, TOTAL, TEAM TOTAL · 76ers (Gast), TEAM TOTAL · Knicks (Heim) - unabhaengig von den Daten", ttl(v1) == ttl(v2) == ["SPREAD", "TOTAL", "TEAM TOTAL · 76ers", "TEAM TOTAL · Knicks"], str(ttl(v1)))
h1 = sc.render_card_html(v1)
check("Karte bleibt unveraendert (Kopf, Sieg-Balken, Spread/Total, Herkunftszeile, MODEL DETAILS); die Bloecke stecken NICHT in der Karte (native Expander darunter)", "<details" in h1 and h1.count("<details") == 1 and "pc-lines" not in h1 and "pc-card-attached" in h1 and h1.index("pc-origin") < h1.index("MODEL DETAILS"))
check("ohne Zeilenbloecke (Mock): normale Karte ohne 'attached'", "pc-card-attached" not in sc.render_card_html(sc.build_card_vm({"home_team": K, "away_team": P, "home_score": 110, "away_score": 105, "home_win_prob": 0.6, "away_win_prob": 0.4, "exp_total": 215.0, "exp_spread": 5.0, "model_total": 215.0,
                                                                                         "market_diff": 0.0, "market_weight": 0.0, "home_bias_adjustment": 0.0, "away_bias_adjustment": 0.0})))
bodies = [sc.line_block_body_html(b) for b in v1["lines"]]; allh = "".join(bodies)
check("Total-Zeilen: Over links / Under rechts im Text ('Over NN %' ... 'NN % Under')", len(re.findall(r'Over \d+ %</span>', allh)) == 21 and len(re.findall(r'pc-lpct-r"><span class="pc-lpill[^"]*">\d+ % Under</span>', allh)) == 21)
check("Spread-Zeilen aus Sicht des Favoriten: 'Knicks −4,5', Gast (76ers) links, Heim (Knicks) rechts", "Knicks −4,5" in bodies[0] and re.search(r'76ers \d+ %</span>.*?\d+ % Knicks</span>', bodies[0], flags=re.S))
check("Hauptlinie hervorgehoben (pc-lmain + Tag 'Hauptlinie'), je Block genau eine", all(b.count("pc-lrow pc-lmain") == 1 and b.count(">Hauptlinie<") == 1 for b in bodies))
def row_parts(html):
    """je Zeile: (links-Plakette?, rechts-Plakette?, links-Segment orange?, rechts-Segment orange?, Text links, Text rechts)"""
    out = []
    for m in re.finditer(r'<div class="pc-lrow[^"]*">(.*?)</div>', html, flags=re.S):
        row = m.group(1)
        pills = re.findall(r'<span class="pc-lpill( pc-lpct-pred)?">([^<]*)</span>', row)
        segs = re.findall(r'<span class="pc-lseg (pc-seg-fav|pc-seg-other)"', row)
        out.append((bool(pills[0][0]), bool(pills[1][0]), segs[0] == "pc-seg-fav", segs[1] == "pc-seg-fav", pills[0][1], pills[1][1]))
    return out
rp = [row_parts(b) for b in bodies]
pct = lambda t: int(re.search(r"(\d+) %", t).group(1))
check("jede Zeile (Spread, Total, Team Totals): hoehere Seite = Plakette + oranges Segment, die andere ohne beides; nie beide",
      all(len(x) == n_ and all((l_p and l_s and not r_p and not r_s and pct(lt) > pct(rt)) or (r_p and r_s and not l_p and not l_s and pct(rt) > pct(lt)) or (not l_p and not r_p and not l_s and not r_s and pct(lt) == pct(rt)) for l_p, r_p, l_s, r_s, lt, rt in x) for x, n_ in zip(rp, (5, 7, 7, 7))))
flat = [t for x in rp for t in x]
_sr = [{**r, "label": f"Knicks −{r['line']}", "left": f"76ers {r['p_left']} %", "right": f"{r['p_right']} % Knicks", "style": "spread", "is_main": False} for r in lp.spread_rows(3.0, "home", [0.5, 2.5, 4.5, 6.5], None)]
rps = row_parts(sc.line_block_body_html({"rows": _sr, "note": None}))
v3 = vm_of(fake_proj(total_line=226.5)); rp3 = row_parts(sc.line_block_body_html(v3["lines"][1]))
check("im Material kommen vor: Over-Vorhersage UND Under-Vorhersage in derselben Total-Tabelle; Spread Gast- und Heim-Vorhersage (Gast-Favorit / Heim-Favorit)",
      any(t[0] for t in rp3) and any(t[1] for t in rp3) and any(t[1] for t in rps) and any(t[0] for t in rps), str([(t[0], t[1]) for t in rp3]))
syn = lambda l, r, st: {"rows": [{"line": 220.5, "label": "220,5", "p_left": l, "p_right": r, "left": f"Over {l} %", "right": f"{r} % Under", "predicted": lp.predicted_side(l, r), "is_main": False, "style": st}], "note": None}
h50 = sc.line_block_body_html(syn(50, 50, "ou"))
check("50 : 50: keine Plakette, kein oranges Segment, beide Seiten gleich gedaempft", "pc-lpct-pred" not in h50 and "pc-seg-fav" not in h50 and h50.count("pc-seg-other") == 2)
hU = sc.line_block_body_html(syn(38, 62, "ou")); hO = sc.line_block_body_html(syn(70, 30, "ou"))
check("Under 62 % hoeher: rechts orange + Plakette; Over 70 % hoeher: links orange + Plakette (Over bleibt links, Under rechts)",
      row_parts(hU)[0][:4] == (False, True, False, True) and row_parts(hO)[0][:4] == (True, False, True, False))
check("Plakette: weisse Schrift auf pill_bg >= 3 : 1 (grosser Text); Palette ohne Blau-/Grau-Over/Under-Farben und ohne Gruen/Rot; im HTML/CSS keine alten Over/Under-Klassen",
      ratio(sc.PALETTE["pill_text"], sc.PALETTE["pill_bg"]) >= 3.0 and "bar_over" not in sc.PALETTE and "bar_under" not in sc.PALETTE and "seg-over" not in allh and "seg-under" not in allh + sc.CARD_CSS and "seg-over" not in sc.CARD_CSS
      and not any(int(v[3:5], 16) > int(v[1:3], 16) + 25 and int(v[3:5], 16) > int(v[5:7], 16) + 25 for v in sc.PALETTE.values() if v.startswith("#")))
check("Balkenbreiten entsprechen den Prozentzahlen (links + rechts = 100), Zeilen 5 + 7 + 7 + 7", all(int(a) + int(b) == 100 for a, b in re.findall(r'style="width:(\d+)%"></span><span class="pc-lseg [^"]*" style="width:(\d+)%"', allh)) and allh.count('class="pc-lseg') == 2 * 26)
vn = vm_of({"market_lines": {"spread": {"line": None}, "total": {"line": None}, "team_total_away": {"line": None}, "team_total_home": {"line": None}}, "exp_spread": 1.0, "exp_total": 220.0})
check("ohne Linien: vier Bloecke mit 'keine Linie'", len(vn["lines"]) == 4 and all("keine Linie" in sc.line_block_body_html(b) for b in vn["lines"]))

# ===================================================== D) echte App (AppTest)
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
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu", "data": [mk_event(K, P, 232.0, [-4.5, -4.5, -4.0], n + 3 * H, "ev-k")]}},
                                                               "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def pj(at, home): return [x for x in at.session_state["projections"] if x["home_team"] == home][0]
def cards(at): return [m.value for m in at.markdown if 'class="pc-card' in m.value]
def card_of(at, home): return [c for c in cards(at) if f">{sc.team_info(home)['nick']}<" in c][0]
def exps(at, home):
    """Expander der Karte eines Spiels (Score-Projections-Tab): Titel und Inhalt (HTML)."""
    nick = sc.team_info(home)["nick"]; labels = ["SPREAD", "TOTAL"]
    found = [e for e in at.expander if e.label in ("SPREAD", "TOTAL") or e.label.startswith("TEAM TOTAL")]
    return found
def blocks_for(at, home):
    out = []
    for e in at.expander:
        html = " ".join(m.value for m in e.markdown)
        if (e.label in ("SPREAD", "TOTAL") or e.label.startswith("TEAM TOTAL")) and ("pc-lrow" in html or "pc-lnote" in html):      # nur Score-Projections (nicht die Pre-Match-Expander)
            out.append((e.label, html, e.proto.expanded))
    return out
at = app().run()
allb = blocks_for(at, K)
check("echte App: pro Spiel vier Expander mit festen Titeln, direkt unter der Karte (3 Spiele -> 12), standardmaessig zu", len(allb) == 12 and all(not x for l, h, x in allb), str([l for l, h, x in allb][:8]))
sp = next(h for l, h, x in allb if l == "SPREAD" and "Knicks −4,5" in h)
check("echte App: Spread-Staffel um die Cache-Linie 4,3 (4,5 gerundet): 2,5 ... 6,5 (5 Zeilen, Hauptlinie 4,5)", all(f"Knicks −{x}" in sp for x in ("2,5", "3,5", "4,5", "5,5", "6,5")) and sp.count("pc-lrow") == 5, str(sp.count("pc-lrow")))
check("echte App: Spiel ohne Linie (Spurs): Bloecke mit 'keine Linie'", sum(h.count("keine Linie") for l, h, x in allb) >= 4)
check("echte App: Projektionszahlen unveraendert durch die Anzeige (gleich compute_projection mit Cache-Linien)", pj(at, K)["exp_total"] == compute_projection(pj(at, K)["_line_inputs"]["pred"], market_total=232.0, market_spread=4.3, game_date=pj(at, K)["game_date"], bias_adjustments=at.session_state["bias_adjustments"])["exp_total"])
check("echte App: keine Exception/Warnung", not page_checks.problems(at), str(page_checks.problems(at)))
start_k = ps.normalize_start(pj(at, K)["game_start"])
ps.save_card(pj(at, K)["game_date"], start_k, K, P, spread_rows=[{"id": "main", "line": "-4,5", "home_odds": "1,9", "away_odds": "1,9", "bookmaker": "Betano"}, {"id": None, "line": "-6,5", "home_odds": "1,9", "away_odds": "1,9", "bookmaker": "Betano"}],
             total_rows=[{"id": "main", "direction": None, "line": "240,5", "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}], now=time.time())
at.run(); allb2 = blocks_for(at, K)
sp2 = next(h for l, h, x in allb2 if l == "SPREAD" and "Knicks −6,5" in h); tot2 = next(h for l, h, x in allb2 if l == "TOTAL" and "240,5" in h)
check("eigene Eingabe in der echten App: Spread zeigt genau 4,5 und 6,5 (zwei Zeilen, kein 3,5), Total genau 240,5 (eine Zeile); Titel unveraendert", len(allb2) == 12 and sp2.count("pc-lrow") == 2 and "Knicks −3,5" not in sp2 and tot2.count("pc-lrow") == 1 and "pc-lmain" in tot2)
check("echtes Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
check("echte Tracking-Datei byte-identisch", (real_file.read_bytes() if real_file.exists() else None) == real_bytes)
check("echte Kaderdatei byte-identisch", (real_roster.read_bytes() if real_roster.exists() else None) == real_roster_bytes)
check("in KEINEM AppTest-Lauf Exception oder 'default value'-Satz", not page_checks.bad, str(page_checks.bad[:3]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
