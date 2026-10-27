"""Tests: Team-Modell "team-2" (engine/team_injury.py): Ausfall-Mass, Basis (Vorjahr / laufende Saison), Korrektur von Spread, Punkten und Siegchance, Karte mit Schalter, Expander,
Snapshot-Block. Offline, Temp-Ordner, das Standard-Modell bleibt unveraendert. Aufruf: venv/bin/python tests/test_team_injury.py"""
import copy, hashlib, json, os, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
fake_net.install(); fake_net.fresh_env()
import page_checks; page_checks.install()
from engine import line_probabilities as lp
from engine import team_injury as ti
import data.projection_snapshots as snap
import ui.score_cards as sc
from test_snapshots_helpers import make_proj

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_sha():
    p = ROOT / "data/tracking/projection_snapshots.json"
    return hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else None
sha0 = real_sha()

# ---------------------------------------------------------------- Zeilen: Team NYK (Heim) und PHI (Gast)
_gid = [0]
def mk_rows(abbr, players, n_games, start_day=1, month="2026-11"):
    """players: {pid: (name, minuten, punkte, ausgelassene_spiele_set)}; n_games Teamspiele; Teampunkte = Summe der Spielerpunkte."""
    rows = []
    for g in range(n_games):
        _gid[0] += 1
        for pid, (name, m, pts, skip) in players.items():
            if g in skip:
                continue
            rows.append({"game_id": f"G{_gid[0]}", "date": f"{month}-{start_day + g:02d}", "team": abbr, "person_id": pid, "name": name, "minutes": m, "points": pts})
    return rows
STARS = {i: (f"Star {i}", 40 - i, 30 - 2 * i, set()) for i in range(1, 9)}             # 8 Stammspieler mit absteigenden Minuten
BENCH = {20 + i: (f"Bank {i}", 5.0, 2, set()) for i in range(3)}
TEAM = {**STARS, **BENCH}

# 1) Anteil und Top 8
rows = mk_rows("NYK", TEAM, 12)
top, ng = ti.top_players(rows, "NYK", "2026-12-01")
team_ppg = sum(v[2] for v in TEAM.values())
check("Top 8 nach Minuten, Bank nicht dabei", [t["person_id"] for t in top] == list(range(1, 9)) and ng == 12)
check("Anteil = Punkte pro gespieltem Spiel / Teampunkte pro Teamspiel", abs(top[0]["share"] - STARS[1][2] / team_ppg) < 1e-9, top[0]["share"])
st = {**STARS, 1: ("Star 1", 38.0, 28, set(range(0, 6)))}               # Star 1 verpasst die ersten 6 von 12 Spielen -> Punkte pro GESPIELTEM Spiel
top2, _ = ti.top_players(mk_rows("NYK", st, 12), "NYK", "2026-12-01")
tppg2 = (sum(v[2] for k, v in STARS.items() if k != 1) * 12 + 28 * 6) / 12
check("Anteil bezieht sich auf gespielte Spiele (Punkte pro GESPIELTEM Spiel durch Teampunkte pro Teamspiel)", abs(next(t for t in top2 if t["person_id"] == 1)["share"] - 28 / tppg2) < 1e-9)
rows_cut = ti.top_players(rows, "NYK", "2026-11-06")[1]
check("nur Spiele VOR dem Spieltag zaehlen (before_day)", rows_cut == 5, rows_cut)

# 2) Ausfall-Mass: nur Top 8 und nur die genannten ('fehlt')
m, miss = ti.team_measure(top, {1, 22})
check("Mass = Summe der Anteile der fehlenden Top-8-Spieler; Bankspieler (22) zaehlt nicht", abs(m - round(top[0]["share"], 4)) < 1e-9 and [x["person_id"] for x in miss] == [1])
check("kein Ausfall -> Mass 0", ti.team_measure(top, set())[0] == 0.0)

# 3) Basis: Vorjahr (< 10 Spiele) mit Kader-Bedingung
def prev_season_rows(abbr, players, other=None):
    out = []
    for g in range(30):
        _gid[0] += 1
        for pid, (name, m, pts, skip) in players.items():
            out.append({"game_id": f"P{_gid[0]}", "date": "2026-01-10", "team": abbr, "person_id": pid, "name": name, "minutes": m, "points": pts})
    return out
prev = prev_season_rows("NYK", {**STARS, 99: ("Abgegeben", 45.0, 40, set())}) + prev_season_rows("PHI", {i + 100: (f"P{i}", 40 - i, 30 - 2 * i, set()) for i in range(1, 9)})
cur_short = mk_rows("NYK", {**TEAM, 500: ("Neuzugang", 36.0, 25, set())}, 4) + mk_rows("PHI", {i + 100: (f"P{i}", 40 - i, 30 - 2 * i, set()) for i in range(1, 9)}, 4)
roster_nyk = set(STARS) | set(BENCH) | {500}
roster_phi = {i + 100 for i in range(1, 9)}
t2 = ti.compute("NYK", "PHI", "2026-11-20", {1, 500}, set(), cur_short, prev, roster_nyk, roster_phi)
check("weniger als 10 Teamspiele -> Basis 'Vorjahr'", t2["base"] == "Vorjahr" and t2["games_home"] == 4)
check("Vorjahr: Neuzugang (500, letzte Saison nicht im Team) zaehlt nicht, Alter Star (99, nicht mehr im Kader) verdraengt keinen Kaderspieler",
      [x["person_id"] for x in t2["missing_home"]] == [1] and t2["measure_home"] > 0)
top_prev, _ = ti.top_players(prev, "NYK", None, roster_nyk)
check("Vorjahr: Top 8 nur aus Spielern, die im Kader stehen (99 entfaellt)", 99 not in [t["person_id"] for t in top_prev] and len(top_prev) == 8)

# 4) Wechsel bei 10 Spielen, eine Basis pro Spiel
cur9 = mk_rows("NYK", TEAM, 9) + mk_rows("PHI", {i + 100: (f"P{i}", 40 - i, 30 - 2 * i, set()) for i in range(1, 9)}, 10)
check("Heim 9 / Gast 10 Spiele: beide Teams Vorjahr (nichts gemischt)", ti.compute("NYK", "PHI", "2026-12-01", {1}, {101}, cur9, prev, roster_nyk, roster_phi)["base"] == "Vorjahr")
cur10 = mk_rows("NYK", TEAM, 10) + mk_rows("PHI", {i + 100: (f"P{i}", 40 - i, 30 - 2 * i, set()) for i in range(1, 9)}, 10)
c10 = ti.compute("NYK", "PHI", "2026-12-01", {1}, {101}, cur10, prev, roster_nyk, roster_phi)
check("beide Teams mit 10 Spielen -> laufende Saison", c10["base"] == "laufende Saison" and c10["games_home"] == 10 and c10["games_away"] == 10)
cur_nz = mk_rows("NYK", {**TEAM, 500: ("Neuzugang", 44.0, 35, set())}, 10) + mk_rows("PHI", {i + 100: (f"P{i}", 40 - i, 30 - 2 * i, set()) for i in range(1, 9)}, 10)
c_nz = ti.compute("NYK", "PHI", "2026-12-01", {500}, set(), cur_nz, prev, roster_nyk, roster_phi)
check("laufende Saison: Neuzugang mit vielen Minuten zaehlt (Daten dieser Saison)", c_nz["measure_home"] > 0)

# 5) Korrektur
proj = make_proj(start="2026-12-02T01:00:00Z", spread=4.5, total=231.5, date="2026-12-01")
mh, ma = 0.30, 0.10
info = {"version": "team-2", "base": "Vorjahr", "games_home": 3, "games_away": 3, "measure_home": mh, "measure_away": ma, "missing_home": [], "missing_away": []}
t = ti.apply(proj, info)
delta = 0.5 * -14.4 * (mh - ma)
check("Spread-Korrektur = 0,5 * (-14,4) * (Ausfall Heim - Ausfall Gast), addiert auf den Heim-Spread", abs(t["delta_spread"] - round(delta, 2)) < 1e-9 and abs(t["exp_spread"] - round(proj["exp_spread"] + delta, 1)) < 1e-9, (t["exp_spread"], proj["exp_spread"], delta))
check("Total bleibt gleich (Punkte Heim + Gast)", t["home_score"] + t["away_score"] == proj["home_score"] + proj["away_score"] and t["exp_total"] == proj["exp_total"])
check("Heim verliert, Gast gewinnt Punkte (je etwa die Haelfte der Korrektur)", abs((proj["home_score"] - t["home_score"]) - round(-delta / 2)) <= 1 and t["home_score"] < proj["home_score"] and t["away_score"] > proj["away_score"])
check("Siegchance aus dem korrigierten Spread mit demselben Sigma (win_prob_home)", t["home_win_prob"] == round(lp.win_prob_home(t["exp_spread"]), 4) and abs(t["home_win_prob"] + t["away_win_prob"] - 1) < 1e-9)
check("PP-Verschiebung = neue minus alte Heim-Siegchance in Prozentpunkten (negativ: Heim schwaecher)", t["pp_shift"] < 0 and abs(t["pp_shift"] - (t["home_win_prob"] - proj["home_win_prob"]) * 100) < 0.06, t["pp_shift"])
check("Mass beider Teams 0 -> keine Aenderung und kein Schalter", ti.apply(proj, {**info, "measure_home": 0, "measure_away": 0})["active"] is False and ti.apply(proj, {**info, "measure_home": 0, "measure_away": 0})["exp_spread"] == proj["exp_spread"])
check("gleiches Mass bei beiden Teams: Schalter aktiv (Ausfall vorhanden), Spread unveraendert", ti.apply(proj, {**info, "measure_home": 0.2, "measure_away": 0.2})["active"] and ti.apply(proj, {**info, "measure_home": 0.2, "measure_away": 0.2})["delta_spread"] == 0)
check("Zeichen 'Ausfall: +x PP' nur bei mehr als 2 PP, mit dem Team, das gewinnt", ti.note_text(proj, t, "Knicks", "76ers") == f"Ausfall: +{abs(t['pp_shift']):.0f} PP für 76ers" and ti.note_text(proj, {**t, "pp_shift": 2.0}, "Knicks", "76ers") is None and ti.note_text(proj, {**t, "pp_shift": -2.1}, "K", "P") is not None)
before = copy.deepcopy(proj)
ti.apply(proj, info); check("apply aendert die Projektion nicht (Standard bleibt)", proj == before)

# 6) attach: 'fraglich' zaehlt nicht, Ausfaelle aus der Ausfall-Datei
key = proj["_line_inputs"]["entry_key"]
info_r = {"teams": {proj["home_team"]: [{"person_id": i} for i in roster_nyk], proj["away_team"]: [{"person_id": i} for i in roster_phi]}}
ab_out = {"out": {"1": {"name": "Star 1", "team": proj["home_team"]}}, "doubtful": {"2": {"name": "Star 2", "team": proj["home_team"]}}}
import data.player_history as ph
def season_rows_fn(season): return cur_short
orig_league = ph.league_file
ph.league_file = lambda season: {"rows": prev}
p1 = copy.deepcopy(proj); ti.attach(p1, key, season_rows_fn, info_r, ab_out)
p2 = copy.deepcopy(proj); ti.attach(p2, key, season_rows_fn, info_r, {"out": {}, "doubtful": ab_out["doubtful"]})
p3 = copy.deepcopy(proj); ti.attach(p3, key, season_rows_fn, info_r, {"out": {"22": {"name": "Bank 2", "team": proj["home_team"]}}, "doubtful": {}})
ph.league_file = orig_league
check("attach: Fehlt-Spieler erzeugt Block team2 mit Version, Basis, Mass; Standardwerte unveraendert", p1["team2"]["version"] == "team-2" and p1["team2"]["base"] == "Vorjahr" and p1["team2"]["measure_home"] > 0 and p1["exp_spread"] == proj["exp_spread"])
check("nur 'fraglich' (kein Fehlt): Mass 0, Schalter aus (Spiel ohne Ausfall)", p2["team2"]["measure_home"] == 0 and p2["team2"]["active"] is False)
check("Fehlt-Spieler ausserhalb der Top 8 (Bank): Mass unveraendert 0, kein Schalter", p3["team2"]["active"] is False)

# 7) Karte: ohne Ausfall unveraendert, mit Ausfall Schalter und beide Varianten
def html_of(p): return sc.render_card_html(sc.build_card_vm(p, entry=None))
std_html = html_of(proj)
check("ohne team2-Block: keine Schalter-Teile in der Karte", "pc-sw" not in std_html and "pc-var" not in std_html)
check("Spiel ohne Ausfall (Block, aber nicht aktiv): Karte identisch zu ohne Block", html_of(p2) == std_html)
h1 = html_of(p1)
t2p = p1["team2"]
check("mit Ausfall: Schalter 'Standard | Mit Ausfällen' oben rechts in der Karte", h1.count('<details class="pc-sw"') == 1 and "Mit Ausfällen" in h1 and ">Standard<" in h1 and h1.index("pc-sw") < h1.index("pc-head"))
check("beide Varianten enthalten: Punkteanzeige, Siegchance-Balken, Spread (je 2 mal, Standard und team-2)", h1.count("pc-var-std") == 3 and h1.count("pc-var-t2") == 3, (h1.count("pc-var-std"), h1.count("pc-var-t2")))
sp_std = sc.build_card_vm(proj)["spread"]["model"]; sp_t2 = sc.build_card_vm(p1)["t2"]["vm"]["spread"]["model"]
check("Spread der Variante weicht vom Standard ab und steht im HTML", sp_std != sp_t2 and sp_std in h1 and sp_t2 in h1, (sp_std, sp_t2))
check("Total-Spalte nur einmal (Total bleibt gleich)", h1.count(">TOTAL<") == 1 and h1.count("pc-v-model\">" + sc.build_card_vm(proj)["total"]["model"]) == 1)
pp = abs(t2p["pp_shift"])
check("gelbes Zeichen 'Ausfall: +x PP' unter dem Balken, ausserhalb der Varianten (auch bei Schalter Standard)", (pp > 2) == ("Ausfall: +" in h1) and (("Ausfall: +" not in h1) or (h1.index("Ausfall: +") > h1.rindex("pc-bar") and "pc-var-std" not in h1[h1.index("Ausfall: +") - 200:h1.index("Ausfall: +")])), f"pp {pp}")
check("CSS: Standard sichtbar, team-2 versteckt; offener Schalter dreht das um (auch fuer die Expander ueber den Container)",
      ".pc-var-t2 { display:none; }" in sc.CARD_CSS.replace("{{", "{").replace("}}", "}") or ".pc-var-t2 {" in sc.CARD_CSS and 'pc-sw[open]) .pc-var-std' in sc.CARD_CSS and 'st-key-sc_game_' in sc.CARD_CSS)

# 8) stark verschobene Siegchance zeigt das Zeichen
pbig = copy.deepcopy(proj); pbig["team2"] = ti.apply(proj, {**info, "measure_home": 0.6, "measure_away": 0.0, "missing_home": [{"person_id": 1, "name": "A", "share": 0.6}]})
hb = html_of(pbig)
t2b = pbig["team2"]
check("Standard-Teil enthaelt die heutigen Punkte, team-2-Teil die verschobenen (Heim und Gast), Summe gleich",
      f'>{proj["home_score"]}</span>' in hb.split("pc-var-t2")[0] and f'>{proj["away_score"]}</span>' in hb.split("pc-var-t2")[0]
      and f'>{t2b["home_score"]}</span>' in hb and f'>{t2b["away_score"]}</span>' in hb and t2b["home_score"] != proj["home_score"] and t2b["home_score"] + t2b["away_score"] == proj["home_score"] + proj["away_score"], (proj["home_score"], t2b["home_score"]))
check("grosse Verschiebung (> 2 PP): Zeichen 'Ausfall: +x PP' steht da", "Ausfall: +" in hb and abs(pbig["team2"]["pp_shift"]) > 2, pbig["team2"]["pp_shift"])

# 9) Expander: Spread und Team Totals in beiden Varianten, Total einmal
from streamlit.testing.v1 import AppTest
import pickle
def app_src():
    import os, pickle
    import ui.score_cards as sc2
    vm = pickle.loads(open(os.environ["TI_VM"], "rb").read())
    sc2.render_line_expanders(vm, "abc")
vmx = sc.build_card_vm(pbig, entry=None)
tmp = tempfile.NamedTemporaryFile(delete=False); tmp.write(pickle.dumps(vmx)); tmp.close(); os.environ["TI_VM"] = tmp.name
at = AppTest.from_function(app_src, default_timeout=60).run()
bodies = {e.label: " ".join(m.value for m in e.markdown) for e in at.expander}
check("Expander-Titel unveraendert (SPREAD, TOTAL, TEAM TOTAL x2)", len(at.expander) == 4 and [e.label for e in at.expander][:2] == ["SPREAD", "TOTAL"], list(bodies))
check("SPREAD und beide TEAM TOTALs enthalten beide Varianten, TOTAL nur eine", all("pc-var-std" in v and "pc-var-t2" in v for k, v in bodies.items() if k != "TOTAL") and "pc-var" not in bodies["TOTAL"], {k: v.count("pc-var") for k, v in bodies.items()})
tt_std = vmx["lines"][2]["rows"][0]["label"], vmx["t2"]["vm"]["lines"][2]["rows"][0]["label"]
check("Team-Total-Zeilen der Variante unterscheiden sich (verschobene Punkte)", [r["left"] for r in vmx["lines"][2]["rows"]] != [r["left"] for r in vmx["t2"]["vm"]["lines"][2]["rows"]] or [r["left"] for r in vmx["lines"][3]["rows"]] != [r["left"] for r in vmx["t2"]["vm"]["lines"][3]["rows"]])
check("TOTAL-Zeilen in beiden Varianten gleich", vmx["lines"][1]["rows"] == vmx["t2"]["vm"]["lines"][1]["rows"])
os.unlink(tmp.name)

# 10) Snapshot
model = {"file_mtime": None, "file_size": 0, "sha1": "x", "ratings_as_of": "2026-10-20"}
c_std = snap.build_snapshot(proj, None, model)
c_t2 = snap.build_snapshot(pbig, None, model)
check("Snapshot ohne team2-Block: kein Feld 'team2' (Inhalt/Hash wie bisher)", "team2" not in c_std)
check("Snapshot mit Block: team2 mit Version, Basis, Mass je Team, korrigierten Werten", c_t2["team2"]["version"] == "team-2" and c_t2["team2"]["base"] == "Vorjahr" and c_t2["team2"]["measure_home"] == 0.6 and c_t2["team2"]["measure_away"] == 0.0
      and c_t2["team2"]["home_score"] == pbig["team2"]["home_score"] and c_t2["team2"]["exp_spread"] == pbig["team2"]["exp_spread"] and c_t2["team2"]["home_win_prob"] == pbig["team2"]["home_win_prob"])
check("bestehende Felder unveraendert (heutige Projektion, Linien, Tabellen)", {k: v for k, v in c_t2.items() if k != "team2"} == c_std)
check("echte Snapshot-Datei unveraendert", real_sha() == sha0)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
