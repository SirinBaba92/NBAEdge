"""Tests: Sicherheitsstufen in den Karten (Tab Score Projections): Mindestquote je Linie, Sieger-Zeichen, Schalter team-2, unveraenderte Anzeige.
Modul engine/safety_levels.py (Hilfsfunktionen), Konstanten in config/settings.py, Darstellung in ui/score_cards.py. Offline, Temp-Ordner.
Aufruf (aus dem Projektordner):  venv/bin/python tests/test_safety_levels.py"""
import copy, importlib.util, math, os, re, subprocess, sys, types, warnings
from pathlib import Path
from statistics import NormalDist
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
fake_net.install(); fake_net.fresh_env()
import page_checks; page_checks.install()
import config.settings as settings
from engine import line_probabilities as lp
from engine import safety_levels as sl
from engine import team_injury as ti
import ui.score_cards as sc
from test_snapshots_helpers import make_proj

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def flat(html): return "".join(line.strip() for line in html.splitlines())
NB = "\xa0"

# ----------------------------------------------------------------- Konstanten
check("Konstanten in config/settings.py: SAFETY_DISCOUNT 0,03 / WINNER_MIN_PROB 0,65 / WINNER_STRONG_PROB 0,70", (settings.SAFETY_DISCOUNT, settings.WINNER_MIN_PROB, settings.WINNER_STRONG_PROB) == (0.03, 0.65, 0.70))
src = (ROOT / "engine" / "safety_levels.py").read_text(encoding="utf-8") + (ROOT / "ui" / "score_cards.py").read_text(encoding="utf-8")
check("nichts fest verdrahtet: weder 0.03 / 0.65 / 0.70 noch '65 %' im Code von safety_levels.py und score_cards.py", not re.search(r"0[.,]03\b|0[.,]65\b|0[.,]70?\b|65\s?%|\b65\b", re.sub(r'""".*?"""|#.*', "", src, flags=re.S)))

# ----------------------------------------------------------------- Mindestquote
check("65 % -> 1,61", sl.odds_text(sl.min_odds(0.65)) == "1,61", sl.min_odds(0.65))
check("59 % -> 1,79", sl.odds_text(sl.min_odds(0.59)) == "1,79", sl.min_odds(0.59))
check("52 % -> 2,04", sl.odds_text(sl.min_odds(0.52)) == "2,04", sl.min_odds(0.52))
check("50 % -> 2,13 (Grenze: genau 50 % wird angezeigt)", sl.odds_text(sl.min_odds(0.50)) == "2,13")
check("unter 50 % keine Anzeige (49,9 %, 30 %, 0 %)", sl.min_odds(0.499) is None and sl.min_odds(0.30) is None and sl.min_odds(0.0) is None and sl.odds_text(None) is None and sl.min_odds(None) is None)
check("Formel 1 / (Chance - Abschlag) auf 2 Stellen, mit Komma, fuer 10 Chancen von 50 bis 95 %", all(sl.odds_text(sl.min_odds(p / 100)) == f"{math.floor(100 / (p / 100 - 0.03) + 0.5) / 100:.2f}".replace(".", ",") for p in range(50, 96, 5)))
old = settings.SAFETY_DISCOUNT
settings.SAFETY_DISCOUNT = 0.05
check("Abschlag kommt aus config/settings.py (0,05 -> 65 % ergibt 1,67)", sl.odds_text(sl.min_odds(0.65)) == "1,67" and "5 Prozentpunkte" in sl.note_text())
settings.SAFETY_DISCOUNT = old
check("Erklaerzeile exakt", sl.note_text() == "Mindestquote = 1 geteilt durch (Chance minus 3 Prozentpunkte). Bietet der Wettschein weniger, lass die Wette aus.", sl.note_text())

# UNGERUNDETE Chance: die Zeile zeigt 65 %, die Chance ist 65,49 % -> 1,60 (aus den gerundeten 65 % waeren es 1,61)
line, sigma = 231.5, lp.TOTAL_SIGMA
mean = line + NormalDist().inv_cdf(0.6549) * sigma
row = lp.over_under_rows(mean, [line], None, sigma)[0]
check("Zeile zeigt gerundet 65 : 35, ungerundet 65,49 %", row["p_left"] == 65 and abs(row["p_left_raw"] - 0.6549) < 1e-9, (row["p_left"], row["p_left_raw"]))
check("Mindestquote aus der UNGERUNDETEN Chance: 1,60 (nicht 1,61 aus dem Prozentwert)", sl.row_min_odds_text(row) == "1,60" and sl.odds_text(sl.min_odds(row["p_left"] / 100)) == "1,61")
under = lp.over_under_rows(line - NormalDist().inv_cdf(0.6549) * sigma, [line], None, sigma)[0]          # Under wahrscheinlicher: rechte Seite orange
check("Under-Seite orange: Chance der rechten Seite = 1 - p_links, ebenfalls 1,60", under["predicted"] == "right" and abs(sl.row_chance(under) - 0.6549) < 1e-9 and sl.row_min_odds_text(under) == "1,60")
sp_even = lp.spread_rows(9.5, "home", [9.5], 9.5)[0]
check("50 : 50 nach Rundung: keine orange Seite, keine Mindestquote", sp_even["predicted"] is None and sl.row_min_odds_text(sp_even) is None)
sp = lp.spread_rows(9.6, "home", [0.5], None)[0]
check("Spread: Heim-Favorit (rechts orange): Chance = 1 - p_links", sp["predicted"] == "right" and abs(sl.row_chance(sp) - (1 - sp["p_left_raw"])) < 1e-12 and abs(sl.row_chance(sp) - NormalDist().cdf((9.6 - 0.5) / lp.SPREAD_SIGMA)) < 1e-12)
check("gespeicherte Schnappschuss-Zeilen ohne ungerundeten Wert: keine Mindestquote", sl.row_min_odds_text({k: v for k, v in sp.items() if k != "p_left_raw"}) is None)

# ----------------------------------------------------------------- Sieger-Zeichen
P0 = make_proj(start="2026-12-02T01:00:00Z", date="2026-12-01")
def with_win(ph, fav_home=True):
    p = copy.deepcopy(P0); p["home_win_prob"], p["away_win_prob"] = (ph, 1 - ph) if fav_home else (1 - ph, ph); return p
def sign_of(ph, fav_home=True): return sc.build_card_vm(with_win(ph, fav_home))["winner"]
s64, s65, s70, s86 = sign_of(0.64), sign_of(0.65), sign_of(0.70), sign_of(0.86)
check("64 %: grau 'Sieger unter 65 %', keine Mindestquote", s64["level"] == "low" and s64["text"] == f"Sieger unter 65{NB}%" and s64["min_odds"] is None)
check("65 %: gruen 'Sieger ab 65 %: erfuellt · Mindestquote 1,61', nicht stark", s65["level"] == "ok" and s65["text"] == f"Sieger ab 65{NB}%: erfüllt · Mindestquote 1,61", s65["text"])
check("70 %: erfuellt und '(stark)', Mindestquote 1,49", s70["level"] == "strong" and s70["text"] == f"Sieger ab 65{NB}%: erfüllt · Mindestquote 1,49 (stark)", s70["text"])
check("86 %: erfuellt und '(stark)', Mindestquote 1,20", s86["level"] == "strong" and s86["text"].endswith("Mindestquote 1,20 (stark)"), s86["text"])
check("Gast als Favorit (65 %): dasselbe Zeichen", sign_of(0.65, False)["text"] == s65["text"] and sign_of(0.64, False)["level"] == "low")
check("ungerundete Siegchance: 64,6 % (zeigt '65 %' im Balken) -> noch unter der Schwelle", sign_of(0.646)["level"] == "low" and sc.build_card_vm(with_win(0.646))["home"]["pct"] == 65)
check("50 : 50 (kein Favorit): grau", sc.build_card_vm(with_win(0.5))["winner"]["level"] == "low")
settings.WINNER_MIN_PROB, settings.WINNER_STRONG_PROB = 0.60, 0.80
check("Schwellen kommen aus config/settings.py (0,60 / 0,80: 64 % erfuellt aber nicht stark, Text 'ab 60 %')", sign_of(0.64)["level"] == "ok" and sign_of(0.64)["text"].startswith(f"Sieger ab 60{NB}%") and sign_of(0.86)["level"] == "strong")
settings.WINNER_MIN_PROB, settings.WINNER_STRONG_PROB = 0.65, 0.70

def html_of(p, **kw): return flat(sc.render_card_html(sc.build_card_vm(p, **kw)))
h86 = html_of(with_win(0.86)); h64 = html_of(with_win(0.64)); h65 = html_of(with_win(0.65))
check("HTML: Zeichen direkt unter dem Siegbalken (nach pc-bar, vor Spread/Total), genau einmal, gruene Klasse ab 65 %", h65.count('class="pc-winner ') == 1 and 'class="pc-winner pc-winner-ok"' in h65 and h65.index('class="pc-bar"') < h65.index("pc-winner") < h65.index("pc-model-wrap"))
check("HTML: unter 65 % graue Klasse", 'class="pc-winner pc-winner-low"' in h64 and "pc-winner-ok" not in h64 and f"Sieger unter 65{NB}%" in h64)
check("HTML: '(stark)' nur ab 70 %", "(stark)" in h86 and "(stark)" not in h65 and "(stark)" not in h64)
check("Spread, Total und Team Total: kein gruenes Zeichen (nur das Sieger-Zeichen traegt die gruene Klasse)", h65.count("pc-winner-ok") == 1 and "pc-winner" not in h65[h65.index("pc-model-wrap"):])

# ----------------------------------------------------------------- Zeilen: Mindestquote-Spalte
PL = copy.deepcopy(P0)
vm = sc.build_card_vm(PL)
check("vier Bloecke mit Zeilen und Spalte 'Mindestquote'", vm["lines"] and len(vm["lines"]) == 4 and all(any(r["min_odds"] for r in b["rows"]) for b in vm["lines"]))
good = True
for b in vm["lines"]:
    for r in b["rows"]:
        expect = sl.odds_text(sl.min_odds(sl.row_chance(r)))
        side_raw = r["p_left_raw"] if r["predicted"] == "left" else (1 - r["p_left_raw"] if r["predicted"] == "right" else None)
        good &= (r["min_odds"] == expect) and ((side_raw is None and r["min_odds"] is None) or (side_raw is not None and side_raw >= 0.5 and r["min_odds"] is not None))
check("jede Zeile: Mindestquote = 1 / (Chance der orangen Seite - 0,03), ungerundet; nur bei orange hinterlegter Seite", good)
bodies = [sc.line_block_body_html(b) for b in vm["lines"]]
check("HTML: Kopfzeile 'Mindestquote' einmal je Block, in jeder Zeile eine Zelle, Zeilen tragen pc-lmincol", all(bd.count('class="pc-lhead"') == 1 and bd.count('class="pc-lmin"') == len(b["rows"]) and bd.count("pc-lmincol") == len(b["rows"]) for bd, b in zip(bodies, vm["lines"])))
txt = re.findall(r'class="pc-lmin">([^<]*)<', bodies[0])
check("angezeigte Werte im Spread-Block mit Komma und 2 Nachkommastellen", all(re.fullmatch(r"\d,\d\d|–", t) for t in txt) and len(txt) == 5, str(txt))
# Zeile mit Linie genau auf dem Modellwert: 50 : 50 -> '–'
tabs = lp.build_line_tables(PL, None)
r50 = lp.spread_rows(PL["exp_spread"], "home", [round(PL["exp_spread"], 2)], None)[0]
check("Zeile mit Linie = Modellwert (50 : 50): Zelle zeigt '–'", r50["predicted"] is None and r50.get("p_left") == 50)

# ----------------------------------------------------------------- Erklaerzeile (Streamlit)
from streamlit.testing.v1 import AppTest
def app_for(vm_, key="k"):
    code = ("import sys; sys.path.insert(0, %r)\nimport ui.score_cards as sc\nfrom test_snapshots_helpers import make_proj\nimport copy\nvm = sc.build_card_vm(make_proj(start='2026-12-02T01:00:00Z', date='2026-12-01'))\nsc.render_line_expanders(vm, 'k')\n" % str(ROOT))
    return code
at = AppTest.from_string(app_for(vm), default_timeout=60); at.run()
md = [m.value for m in at.markdown]
notes = [m for m in md if "pc-minnote" in m]
check("unter den Expandern genau eine Erklaerzeile (nach den vier Expandern)", not at.exception and len(at.expander) == 4 and len(notes) == 1 and sl.note_text() in notes[0], str(at.exception))

# ----------------------------------------------------------------- Schalter team-2
pb = copy.deepcopy(P0)
pb["exp_spread"] = 8.0; pb["home_win_prob"] = round(lp.win_prob_home(8.0), 4); pb["away_win_prob"] = round(1 - pb["home_win_prob"], 4)
info = {"version": "team-2", "base": "Vorjahr", "games_home": 3, "games_away": 3, "measure_home": 0.6, "measure_away": 0.0, "missing_home": [{"person_id": 1, "name": "A", "share": 0.6}], "missing_away": []}
pb["team2"] = ti.apply(pb, info)
vmb = sc.build_card_vm(pb)
hb = flat(sc.render_card_html(vmb))
w_std, w_t2 = vmb["winner"], vmb["t2"]["vm"]["winner"]
check("team-2: Standard 72,8 % -> '(stark)', 'Mit Ausfaellen' 61,0 % -> grau 'unter 65 %' (aus den dort gezeigten Chancen)", w_std["level"] == "strong" and w_t2["level"] == "low" and pb["team2"]["home_win_prob"] < 0.65, (pb["home_win_prob"], pb["team2"]["home_win_prob"]))
signs = re.findall(r'<div class="pc-var pc-var-(std|t2)">(?:(?!<div class="pc-var).)*?<div class="pc-winner pc-winner-\w+"><span>([^<]*)</span></div>', hb)
check("HTML: Standard-Variante traegt das Standard-Zeichen, team-2-Variante das andere; je Variante genau ein Zeichen", signs == [("std", w_std["text"]), ("t2", w_t2["text"])] and hb.count('class="pc-winner ') == 2, str(signs))
check("Sieger-Zeichen ist je Variante aus der ungerundeten Siegchance der Variante berechnet", w_std["min_odds"] == sl.odds_text(sl.min_odds(pb["home_win_prob"])) and w_t2["min_odds"] is None)
# Zeilen: Spread und Team Totals mit zwei Varianten und unterschiedlichen Mindestquoten, Total einmal
lines_std = {b["key"]: b for b in vmb["lines"]}
lines_t2 = {b["key"]: b for b in vmb["t2"]["vm"]["lines"]}
mo = lambda b: [r["min_odds"] for r in b["rows"]]
check("Spread: Mindestquoten unterscheiden sich zwischen Standard und 'Mit Ausfaellen' und stimmen mit den jeweiligen Chancen ueberein", mo(lines_std["spread"]) != mo(lines_t2["spread"]) and all(r["min_odds"] == sl.row_min_odds_text(r) for r in lines_t2["spread"]["rows"]))
check("Team Total Heim/Gast wechseln mit den Punkten der Variante", mo(lines_std["team_home"]) != mo(lines_t2["team_home"]) and mo(lines_std["team_away"]) != mo(lines_t2["team_away"]))
check("Total bleibt gleich (kein Wechsel)", mo(lines_std["total"]) == mo(lines_t2["total"]))
at = AppTest.from_string("import sys; sys.path.insert(0, %r)\nimport ui.score_cards as sc, copy\nfrom test_snapshots_helpers import make_proj\nfrom engine import team_injury as ti, line_probabilities as lp\np = make_proj(start='2026-12-02T01:00:00Z', date='2026-12-01')\np['exp_spread'] = 8.0\np['home_win_prob'] = round(lp.win_prob_home(8.0), 4); p['away_win_prob'] = round(1 - p['home_win_prob'], 4)\np['team2'] = ti.apply(p, %r)\nvm = sc.build_card_vm(p)\nsc.render_line_expanders(vm, 'k')\n" % (str(ROOT), info), default_timeout=60); at.run()
bodies_app = [m.value for m in at.markdown if "pc-lrow" in m.value]
check("Expander-HTML: Spread und Team Totals enthalten beide Varianten (pc-var-std / pc-var-t2) mit Mindestquoten, Total nur einmal", not at.exception and [("pc-var-t2" in b) for b in bodies_app] == [True, False, True, True] and all("pc-lmin" in b for b in bodies_app), str(at.exception))

# ----------------------------------------------------------------- Unveraenderte Anzeige (Vergleich mit dem Stand vor der Aenderung = letzter Commit)
def old_module(path, name):
    srcs = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    m = types.ModuleType(name); m.__file__ = str(ROOT / path); exec(compile(srcs, path, "exec"), m.__dict__); return m
old_sc = old_module("ui/score_cards.py", "old_score_cards")
old_lp = old_module("engine/line_probabilities.py", "old_lp")
def strip_new(html):
    html = re.sub(r'<div class="pc-winner pc-winner-(?:ok|low)"><span>[^<]*</span></div>', "", html)
    html = html.replace('<div class="pc-lhead"><span>Mindestquote</span></div>', "").replace(" pc-lmincol", "")
    return re.sub(r'<span class="pc-lmin">[^<]*</span>', "", html)
cases = [make_proj(), make_proj(spread=-6.5, total=219.5, tt_home=108.5, tt_away=111.0), with_win(0.88), with_win(0.5), with_win(0.30), pb]
same_cards = same_blocks = same_vm = True
for p in cases:
    new_vm, old_vm = sc.build_card_vm(p), old_sc.build_card_vm(p)
    same_cards &= strip_new(flat(sc.render_card_html(new_vm))) == flat(old_sc.render_card_html(old_vm))
    if new_vm["lines"]:
        same_blocks &= [strip_new(flat(sc.line_block_body_html(b))) for b in new_vm["lines"]] == [flat(old_sc.line_block_body_html(b)) for b in old_vm["lines"]]
    strip_rows = lambda v: [[{k: x for k, x in r.items() if k not in ("min_odds", "p_left_raw")} for r in b["rows"]] for b in (v["lines"] or [])]
    same_vm &= all(new_vm[k] == old_vm[k] for k in ("home", "away", "fav", "spread", "total", "warnings", "details", "win_note", "origin", "origin_warnings")) and strip_rows(new_vm) == strip_rows(old_vm)
check("Karten-HTML == bisheriges HTML, wenn man die neuen Elemente (Sieger-Zeichen) entfernt: Scores, Balken, gelbe/graue Chips, Spread-/Total-Spalten (6 Faelle, auch mit team-2)", same_cards)
check("Zeilen-HTML der vier Bloecke == bisheriges HTML ohne Kopfzeile, Klasse und Zelle der Mindestquote (Prozente, Balken, Orange, Hauptlinie unveraendert)", same_blocks)
check("Anzeigewerte (Teams, Siegchance, Spread, Total, Chips, Warnungen, Zeilen-Prozent) == bisherige Werte", same_vm)
chips_new = re.findall(r'class="pc-chip pc-chip-(?:yellow|gray)">[^<]*<', flat(sc.render_card_html(sc.build_card_vm(cases[1]))))
chips_old = re.findall(r'class="pc-chip pc-chip-(?:yellow|gray)">[^<]*<', flat(old_sc.render_card_html(old_sc.build_card_vm(cases[1]))))
check("gelbe/graue Chips identisch", chips_new == chips_old and chips_new)
# Wahrscheinlichkeiten: Engine-Zeilen == Stand vor der Aenderung (ausser dem neuen Zusatzfeld)
same_rows = True
for mean in (200.0, 231.5, 250.2):
    for sig in (lp.TOTAL_SIGMA, lp.TEAM_TOTAL_SIGMA):
        same_rows &= [{k: v for k, v in r.items() if k != "p_left_raw"} for r in lp.over_under_rows(mean, [x + .5 for x in range(190, 260)], 231.5, sig)] == old_lp.over_under_rows(mean, [x + .5 for x in range(190, 260)], 231.5, sig)
for es in (-12.0, -3.2, 0.0, 6.4, 15.1):
    for fav in ("home", "away"):
        same_rows &= [{k: v for k, v in r.items() if k != "p_left_raw"} for r in lp.spread_rows(es, fav, [x + .5 for x in range(-3, 25)], 4.5)] == old_lp.spread_rows(es, fav, [x + .5 for x in range(-3, 25)], 4.5)
check("Engine-Zeilen (Prozent, Seiten, Hauptlinie) == Stand vor der Aenderung; nur das Zusatzfeld p_left_raw ist neu", same_rows)

# Schnappschuss-Karte beendeter Spiele: unveraendert
tabs_snap = {k: {"kind": t["kind"], "source": t.get("source"), "favorite": t.get("favorite"), "derived": bool(t.get("derived", False)), "note": t.get("note"),
                 "rows": [{"line": r["line"], "p_left": r["p_left"], "p_right": r["p_right"], "predicted": r["predicted"], "is_main": bool(r["is_main"])} for r in t["rows"]]} for k, t in lp.build_line_tables(P0, None).items()}
res = {"home_points": 118, "away_points": 109}
vs_new, vs_old = sc.build_card_vm(P0, tables=tabs_snap, result=res), old_sc.build_card_vm(P0, tables=tabs_snap, result=res)
hs_new, hs_old = flat(sc.render_card_html(vs_new)), flat(old_sc.render_card_html(vs_old))
check("Schnappschuss-Karte: HTML identisch zu vorher (kein Sieger-Zeichen)", hs_new == hs_old and "pc-winner" not in hs_new and vs_new["winner"] is None)
check("Schnappschuss-Zeilen: HTML identisch zu vorher, keine Mindestquote-Spalte, Chips eingetreten/nicht eingetreten bleiben", [flat(sc.line_block_body_html(b)) for b in vs_new["lines"]] == [flat(old_sc.line_block_body_html(b)) for b in vs_old["lines"]]
      and all("pc-lmin" not in flat(sc.line_block_body_html(b)) and "pc-lhead" not in flat(sc.line_block_body_html(b)) for b in vs_new["lines"]) and any("pc-lchip" in flat(sc.line_block_body_html(b)) for b in vs_new["lines"]))
at = AppTest.from_string("import sys; sys.path.insert(0, %r)\nimport ui.score_cards as sc\nfrom engine import line_probabilities as lp\nfrom test_snapshots_helpers import make_proj\np = make_proj(start='2026-12-02T01:00:00Z', date='2026-12-01')\nt = lp.build_line_tables(p, None)\nt = {k: {**v, 'rows': [{kk: vv for kk, vv in r.items() if kk != 'p_left_raw'} for r in v['rows']]} for k, v in t.items()}\nvm = sc.build_card_vm(p, tables=t, result={'home_points': 118, 'away_points': 109})\nsc.render_line_expanders(vm, 'k')\n" % str(ROOT), default_timeout=60); at.run()
check("Schnappschuss-Karte: keine Erklaerzeile unter den Expandern", not at.exception and len(at.expander) == 4 and not any("pc-minnote" in m.value for m in at.markdown), str(at.exception))

print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
