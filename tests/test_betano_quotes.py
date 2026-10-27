"""Tests: Betano-Quoten in den Karten (Score Projections): Moneyline unter dem Siegbalken, Spalte "Quote" in den Zeilen von Spread, Total und Team Total (engine/betano_quotes.py, ui/score_cards.py).
Alles mit Eintraegen im Speicher (nur lesend, nichts wird geschrieben); Temp-Ordner fuer die Tracking-Dateien. Aufruf (aus dem Projektordner):  venv/bin/python tests/test_betano_quotes.py"""
import copy, os, re, subprocess, sys, types, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
fake_net.install(); fake_net.fresh_env()
import page_checks; page_checks.install()
from engine import betano_quotes as bq
from engine import line_probabilities as lp
from engine import team_injury as ti
import ui.score_cards as sc
from test_snapshots_helpers import make_proj

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def flat(html): return "".join(line.strip() for line in html.splitlines())

# ----------------------------------------------------------------- Format
check("Format: Komma, 2 Nachkommastellen ('5,50', '1,91', '2,00')", bq.odds_text(5.5) == "5,50" and bq.odds_text(1.91) == "1,91" and bq.odds_text(2) == "2,00" and bq.odds_text("1.9") == "1,90")
check("fehlende/unbrauchbare Quote -> None (None, '', 'x', 0, 1,0)", all(bq.odds_text(v) is None for v in (None, "", "x", 0, 1.0, float("nan"))))
check("nur Betano (gross/klein egal), nie ein anderer Anbieter", bq.is_betano("Betano") and bq.is_betano(" betano ") and not bq.is_betano("Pinnacle") and not bq.is_betano("") and not bq.is_betano(None))

# ----------------------------------------------------------------- Eintrag wie im Pre-Match-Speicher (Boston gegen Brooklyn, Zahlen aus der Aufgabe)
def ln(i, role, active=True, bm="Betano", **kw): return {"id": i, "role": role, "active": active, "bookmaker": bm, **kw}
def entry_bos(home_is_bos=True, bm="Betano"):
    """Spread: Celtics -12,5 @ 1,91 / Nets +12,5 @ 1,90; Total 222,5 Over 1,91 / Under 1,90; TT Celtics 117,5: 1,85 / 1,85; TT Nets 104,5: Over 1,80 / Under 1,91; Sieger Celtics 1,07 / Nets 8,50.
    Gespeichert wird aus Heim-Sicht: ist Boston das Heimteam, ist line_home = -12,5 (home_odds = Celtics); ist Boston Gast, ist line_home = +12,5 (home_odds = Nets)."""
    if home_is_bos:
        sp = ln("main", "main", line_home=-12.5, line_away=12.5, home_odds=1.91, away_odds=1.90, bm=bm)
        win = {"home_odds": 1.07, "away_odds": 8.5, "bookmaker": bm}
        tt = {"home": {"lines": [ln("main", "main", line=117.5, over_odds=1.85, under_odds=1.85, bm=bm)]}, "away": {"lines": [ln("main", "main", line=104.5, over_odds=1.80, under_odds=1.91, bm=bm)]}}
    else:
        sp = ln("main", "main", line_home=12.5, line_away=-12.5, home_odds=1.90, away_odds=1.91, bm=bm)
        win = {"home_odds": 8.5, "away_odds": 1.07, "bookmaker": bm}
        tt = {"home": {"lines": [ln("main", "main", line=104.5, over_odds=1.80, under_odds=1.91, bm=bm)]}, "away": {"lines": [ln("main", "main", line=117.5, over_odds=1.85, under_odds=1.85, bm=bm)]}}
    return {"markets": {"winner_incl_ot": win, "spread": {"lines": [sp]}, "total": {"lines": [ln("main", "main", line=222.5, over_odds=1.91, under_odds=1.90, direction=None, bm=bm)]}, "team_totals": tt}}

def proj_for(home, away, spread, total, hs, as_, p_home):
    p = make_proj(home=home, away=away, start="2026-12-02T01:00:00Z", date="2026-12-01")
    p.update(exp_spread=spread, exp_total=total, home_score=hs, away_score=as_, home_win_prob=p_home, away_win_prob=round(1 - p_home, 4))
    return p
BOS, BKN = "Boston Celtics", "Brooklyn Nets"
def rows_of(vm, key): return next(b for b in vm["lines"] if b["key"] == key)["rows"]
def q(vm, key): return [r["quote"] for r in rows_of(vm, key)]
def pred(vm, key): return [r["predicted"] for r in rows_of(vm, key)]

# 1) Heim = Boston: Spread
vm = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=entry_bos())
check("Spread: Celtics (Heim) -12,5 favorisiert (13,0 > 12,5): orange = Heim rechts -> Quote der Celtics 1,91, Zeile 'Celtics −12,5'", rows_of(vm, "spread")[0]["label"] == "Celtics −12,5" and pred(vm, "spread") == ["right"] and q(vm, "spread") == ["1,91"], str(q(vm, "spread")))
vm = sc.build_card_vm(proj_for(BOS, BKN, 11.0, 224.0, 119, 105, 0.80), entry=entry_bos())
check("Spread: Modell 11,0 < 12,5: orange = Gast links = Nets +12,5 -> Quote der Nets 1,90 (gleiche Zeile 'Celtics −12,5')", rows_of(vm, "spread")[0]["label"] == "Celtics −12,5" and pred(vm, "spread") == ["left"] and q(vm, "spread") == ["1,90"], str(q(vm, "spread")))
# 2) Vertauschte Rollen: Brooklyn Heim, Boston Gast (Celtics -12,5 auswaerts: line_home = +12,5)
vm = sc.build_card_vm(proj_for(BKN, BOS, -13.0, 224.0, 105, 119, 0.16), entry=entry_bos(home_is_bos=False))
check("vertauschte Rollen (Boston Gast): Zeile 'Celtics −12,5', Favorit Gast links orange -> Quote der Celtics 1,91 (away_odds)", rows_of(vm, "spread")[0]["label"] == "Celtics −12,5" and pred(vm, "spread") == ["left"] and q(vm, "spread") == ["1,91"], str(q(vm, "spread")))
vm = sc.build_card_vm(proj_for(BKN, BOS, -11.0, 224.0, 105, 119, 0.20), entry=entry_bos(home_is_bos=False))
check("vertauschte Rollen, Modell nur -11,0: orange = Heim Nets +12,5 rechts -> Quote der Nets 1,90 (home_odds)", pred(vm, "spread") == ["right"] and q(vm, "spread") == ["1,90"], str(q(vm, "spread")))
# 3) Total
for tot, side, expect in ((224.0, "left", "1,91"), (221.0, "right", "1,90")):
    v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, tot, 119, 105, 0.84), entry=entry_bos())
    check(f"Total 222,5, Modell {tot}: orange {'Over' if side == 'left' else 'Under'} -> Quote {expect}", pred(v, "total") == [side] and q(v, "total") == [expect], str(q(v, "total")))
# 4) Team Totals (Celtics = Heim = team_home; Nets = Gast = team_away)
for hs, as_, ch, cn in ((119, 106, "1,85", "1,80"), (116, 103, "1,85", "1,91")):
    v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 222.0, hs, as_, 0.84), entry=entry_bos())
    check(f"Team Total Celtics 117,5 (Modell {hs}) -> {ch}; Nets 104,5 (Modell {as_}) -> {cn}", q(v, "team_home") == [ch] and q(v, "team_away") == [cn] and pred(v, "team_home") == ["left" if hs > 117.5 else "right"] and pred(v, "team_away") == ["left" if as_ > 104.5 else "right"], f"{q(v, 'team_home')} {q(v, 'team_away')}")
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 222.0, 119, 103, 0.84), entry=entry_bos())
check("Team Total: Over Celtics 1,85, Under Nets 1,91 (Heim und Gast nicht vertauscht: Nets hat 1,80 / 1,91, Celtics 1,85 / 1,85)", q(v, "team_home") == ["1,85"] and q(v, "team_away") == ["1,91"])
v = sc.build_card_vm(proj_for(BKN, BOS, -13.0, 222.0, 103, 119, 0.16), entry=entry_bos(home_is_bos=False))
check("vertauschte Rollen: Team Total Heim = Nets (104,5), Gast = Celtics (117,5): Nets Under 1,91, Celtics Over 1,85", q(v, "team_home") == ["1,91"] and q(v, "team_away") == ["1,85"], f"{q(v, 'team_home')} {q(v, 'team_away')}")
# 5) Moneyline
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=entry_bos())
check("Moneyline: Gast Nets 8,50 links, Heim Celtics 1,07 rechts", v["moneyline"] == {"away": "8,50", "home": "1,07"})
h = flat(sc.render_card_html(v))
m = re.search(r'<div class="pc-bar" .*?</div></div><div class="pc-bar-odds"><span>(.*?)</span><span>(.*?)</span></div>', h)
check("HTML: direkt unter dem Siegbalken, links 'Quote 8,50' (Gast), rechts 'Quote 1,07' (Heim), vor dem Sieger-Zeichen", m is not None and m.groups() == ("Quote 8,50", "Quote 1,07") and h.index("pc-bar-odds") < h.index("pc-winner"), str(m and m.groups()))
v = sc.build_card_vm(proj_for(BKN, BOS, -13.0, 224.0, 105, 119, 0.16), entry=entry_bos(home_is_bos=False))
check("vertauschte Rollen: Gast = Celtics 1,07 links, Heim = Nets 8,50 rechts", v["moneyline"] == {"away": "1,07", "home": "8,50"} and re.search(r'pc-bar-odds"><span>Quote 1,07</span><span>Quote 8,50</span>', flat(sc.render_card_html(v))))
# 6) nur Betano, nie andere Anbieter / Odds-API
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=entry_bos(bm="Pinnacle"))
check("Eintrag eines anderen Anbieters (Pinnacle): keine Moneyline, keine Zeilen-Quoten, kein Quoten-Element im HTML", v["moneyline"] is None and all(r["quote"] is None for b in v["lines"] for r in b["rows"]) and "pc-bar-odds" not in flat(sc.render_card_html(v)) and 'class="pc-lq"' not in "".join(sc.line_block_body_html(b) for b in v["lines"]))
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=None)
check("ohne gespeicherten Eintrag (Odds-API-Linien in market_lines vorhanden): Platz bleibt leer, keine Spalte 'Quote'", v["moneyline"] is None and "pc-bar-odds" not in flat(sc.render_card_html(v)) and all(r["quote"] is None for b in v["lines"] for r in b["rows"]) and "pc-lhq" not in "".join(sc.line_block_body_html(b) for b in v["lines"]))
# gemischt: Sieger-Quote Betano, Spread-Zeile eines anderen Anbieters
e = entry_bos(); e["markets"]["spread"]["lines"][0]["bookmaker"] = "Pinnacle"
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=e)
check("gemischt: Sieger Betano gezeigt, Spread-Linie eines anderen Anbieters nicht", v["moneyline"] is not None and q(v, "spread") == [None] and q(v, "total") == ["1,91"])

# 7) genau 50 %: keine favorisierte Seite -> leer
v = sc.build_card_vm(proj_for(BOS, BKN, 12.5, 222.5, 119, 103, 0.84), entry=entry_bos())
check("genau 50 % (Spread-Linie = Modellwert 12,5, Total 222,5): keine orange Seite, keine Quote", pred(v, "spread") == [None] and q(v, "spread") == [None] and pred(v, "total") == [None] and q(v, "total") == [None] and rows_of(v, "spread")[0]["p_left"] == 50)
check("50 %: Zelle bleibt leer (kein Strich), Spalte erscheint nicht, wenn keine Zeile des Blocks eine Quote hat", 'class="pc-lq"' not in sc.line_block_body_html(next(b for b in v["lines"] if b["key"] == "spread")) and 'pc-lhq' not in sc.line_block_body_html(next(b for b in v["lines"] if b["key"] == "total")))
# 8) fehlende Quote
e = entry_bos(); e["markets"]["total"]["lines"].append(ln("x1", "extra", line=223.5, over_odds=None, under_odds=None, direction="higher"))
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=e)
body = sc.line_block_body_html(next(b for b in v["lines"] if b["key"] == "total"))
check("Total mit zwei Linien, fuer 223,5 keine Quote gespeichert: Zeile 222,5 mit 1,91, Zeile 223,5 leer (leere Zelle), Kopfzeile 'Quote' bleibt", q(v, "total") == ["1,91", None] and body.count('class="pc-lq"') == 2 and re.findall(r'class="pc-lq">([^<]*)<', body) == ["1,91", ""] and "pc-lhq" in body, str(q(v, "total")))
e = entry_bos(); del e["markets"]["total"]; del e["markets"]["winner_incl_ot"]
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=e)
check("Betano hat noch keine Sieger-/Total-Quote gespeichert: Platz unter dem Balken leer, Total ohne Spalte 'Quote', Spread mit Quote", v["moneyline"] is None and "pc-bar-odds" not in flat(sc.render_card_html(v)) and all(x is None for x in q(v, "total")) and q(v, "spread") == ["1,91"] and "pc-lhq" not in sc.line_block_body_html(next(b_ for b_ in v["lines"] if b_["key"] == "total")))
e = entry_bos(); e["markets"]["winner_incl_ot"]["home_odds"] = None
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=e)
check("nur die Gast-Quote vorhanden: links 'Quote 8,50', rechts leer", re.search(r'pc-bar-odds"><span>Quote 8,50</span><span></span>', flat(sc.render_card_html(v))) is not None)
e = entry_bos(); e["markets"]["spread"]["lines"][0]["active"] = False
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=e)
check("entfernte (inaktive) Linie: keine Quote", all(r["quote"] is None for r in rows_of(v, "spread")))

# 9) Spalten-Reihenfolge im HTML: Linie | Quote | Prozent links | Balken | Prozent rechts | Mindestquote
v = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=entry_bos())
b = sc.line_block_body_html(next(b for b in v["lines"] if b["key"] == "spread"))
row = b[b.index('<div class="pc-lrow'):]
check("Zeile: Quote zwischen Linie und linkem Prozentwert, Mindestquote ganz rechts", row.index("pc-lline") < row.index('class="pc-lq"') < row.index("pc-lpct-l") < row.index("pc-lbar") < row.index("pc-lpct-r") < row.index('class="pc-lmin"'))
row_cls = re.match(r'<div class="(pc-lrow[^"]*)"', row).group(1)
check("Kopfzeile: 'Quote' ueber der Quote-Spalte, 'Mindestquote' ueber der rechten Spalte, gleiche Gitter-Klassen (pc-lqcol pc-lmincol) wie die Zeilen", '<span class="pc-lhq">Quote</span>' in b and '<span class="pc-lhm">Mindestquote</span>' in b and 'class="pc-lhead pc-lhgrid pc-lqcol pc-lmincol"' in b and row_cls.endswith("pc-lmincol pc-lqcol"), row_cls)
from engine import safety_levels as sl
check("Mindestquote bleibt unveraendert (aus der ungerundeten Chance, unabhaengig von der Betano-Quote): Spread 51,5 % -> 2,06", rows_of(v, "spread")[0]["min_odds"] == sl.row_min_odds_text(rows_of(v, "spread")[0]) == "2,06", rows_of(v, "spread")[0]["min_odds"])

# 10) Schalter team-2: favorisierte Seite wechselt -> Quote wechselt (beide Varianten im HTML)
pe = proj_for(BOS, BKN, 13.0, 222.0, 119, 103, 0.84)
e2 = entry_bos(); e2["markets"]["team_totals"]["home"]["lines"][0]["under_odds"] = 1.88
info = {"version": "team-2", "base": "Vorjahr", "games_home": 3, "games_away": 3, "measure_home": 0.8, "measure_away": 0.0, "missing_home": [{"person_id": 1, "name": "A", "share": 0.8}], "missing_away": []}
pe["team2"] = ti.apply(pe, info)
vs = sc.build_card_vm(pe, entry=e2)
t2 = vs["t2"]["vm"]
lines_std = {b["key"]: b for b in vs["lines"]}; lines_t2 = {b["key"]: b for b in t2["lines"]}
qq = lambda lines, key: [r["quote"] for r in lines[key]["rows"]]
pp = lambda lines, key: [r["predicted"] for r in lines[key]["rows"]]
check("team-2: Spread Standard Heim (Celtics 1,91), 'Mit Ausfaellen' Gast (Nets 1,90): Quote wechselt mit der orangen Seite", pp(lines_std, "spread") == ["right"] and qq(lines_std, "spread") == ["1,91"] and pp(lines_t2, "spread") == ["left"] and qq(lines_t2, "spread") == ["1,90"], f"{pp(lines_t2, 'spread')} {qq(lines_t2, 'spread')}")
check("team-2: Team Total Celtics Standard Over (1,85) -> Mit Ausfaellen Under (1,88); Nets Standard Under (1,91) -> Over (1,80)", qq(lines_std, "team_home") == ["1,85"] and qq(lines_t2, "team_home") == ["1,88"] and qq(lines_std, "team_away") == ["1,91"] and qq(lines_t2, "team_away") == ["1,80"], f"{qq(lines_t2, 'team_home')} {qq(lines_t2, 'team_away')}")
check("team-2: Total unveraendert in beiden Varianten", qq(lines_std, "total") == qq(lines_t2, "total"))
check("team-2: Moneyline-Quoten (Buchmacher-Zahlen) in beiden Varianten gleich", t2["moneyline"] == vs["moneyline"] == {"away": "8,50", "home": "1,07"} and flat(sc.render_card_html(vs)).count("pc-bar-odds") == 2)
from streamlit.testing.v1 import AppTest
tests_data = types.ModuleType("tests_data")
sys.modules["tests_data"] = tests_data
tests_data.vm = vs
at = AppTest.from_string("import sys\nsys.path.insert(0, %r)\nsys.path.insert(0, %r)\nimport tests_data, ui.score_cards as sc\nsc.render_line_expanders(tests_data.vm, 'k')\n" % (str(ROOT), str(ROOT / "tests")), default_timeout=60)
at.run()
bodies = [m.value for m in at.markdown if "pc-lrow" in m.value]
spread_body = bodies[0] if bodies else ""
std_part, _, t2_part = spread_body.partition('<div class="pc-var pc-var-t2">')
get_q = lambda html: re.findall(r'class="pc-lq">([^<]*)<', html)
check("Expander-HTML (Streamlit): Spread enthaelt beide Varianten mit eigener Quote (Standard 1,91 | Mit Ausfaellen 1,90), Total nur einmal", not at.exception and get_q(std_part) == ["1,91"] and get_q(t2_part) == ["1,90"] and "pc-var-t2" not in bodies[1], str(at.exception))

# 11) unveraendert: Vergleich mit dem Stand VOR dieser Aenderung (Backup-Commit 84b683c)
BASE = "84b683c"
def old_module(path, name):
    srcs = subprocess.run(["git", "show", f"{BASE}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    mod = types.ModuleType(name); mod.__file__ = str(ROOT / path); exec(compile(srcs, path, "exec"), mod.__dict__); return mod
old_sc = old_module("ui/score_cards.py", "old_sc_before_quotes")
def strip_new(html):
    html = re.sub(r'<div class="pc-bar-odds">.*?</div>', "", html)
    html = re.sub(r'<div class="pc-lhead pc-lhgrid pc-lqcol( pc-lmincol)?">.*?</div>', lambda m_: '<div class="pc-lhead"><span>Mindestquote</span></div>' if m_.group(1) else "", html)
    html = html.replace(" pc-lqcol", "")
    return re.sub(r'<span class="pc-lq">[^<]*</span>', "", html)
cases = [(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos()), (proj_for(BKN, BOS, -11.0, 221.0, 105, 119, 0.20), entry_bos(False)), (pe, e2), (proj_for(BOS, BKN, 12.5, 222.5, 119, 103, 0.84), entry_bos())]
same_c = same_b = same_v = True
for p_, e_ in cases:
    nv, ov = sc.build_card_vm(p_, entry=e_), old_sc.build_card_vm(p_, entry=e_)
    same_c &= strip_new(flat(sc.render_card_html(nv))) == flat(old_sc.render_card_html(ov))
    same_b &= [strip_new(flat(sc.line_block_body_html(b_))) for b_ in nv["lines"]] == [flat(old_sc.line_block_body_html(b_)) for b_ in ov["lines"]]
    drop = lambda v_: [[{k: x for k, x in r.items() if k != "quote"} for r in b_["rows"]] for b_ in v_["lines"]]
    same_v &= all(nv[k] == ov[k] for k in ("home", "away", "fav", "spread", "total", "warnings", "details", "win_note", "origin", "winner", "minodds_note")) and drop(nv) == drop(ov)
check("Karten-HTML == Stand vorher, wenn man die neuen Quoten-Elemente entfernt (Scores, Balken, Chips, Spread/Total, Sieger-Zeichen; 4 Faelle, auch mit team-2)", same_c)
check("Zeilen-HTML (Prozente, Balken, Orange, Hauptlinie, Mindestquote) == Stand vorher ohne die Quoten-Spalte", same_b)
check("Anzeigewerte (Siegchance, Spread, Total, Chips, Sieger-Zeichen, Mindestquoten, Zeilen-Prozent) == Stand vorher", same_v)
chips = lambda html: re.findall(r'class="pc-chip pc-chip-(?:yellow|gray)">[^<]*<', html)
check("gelbe/graue Chips identisch", all(chips(flat(sc.render_card_html(sc.build_card_vm(p_, entry=e_)))) == chips(flat(old_sc.render_card_html(old_sc.build_card_vm(p_, entry=e_)))) for p_, e_ in cases))
# Schnappschuss-Karte beendeter Spiele: keine Quoten, identisch
p0 = proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84)
tabs = {k: {"kind": t["kind"], "source": t.get("source"), "favorite": t.get("favorite"), "derived": bool(t.get("derived", False)), "note": t.get("note"),
            "rows": [{"line": r["line"], "p_left": r["p_left"], "p_right": r["p_right"], "predicted": r["predicted"], "is_main": bool(r["is_main"])} for r in t["rows"]]} for k, t in lp.build_line_tables(p0, entry_bos()).items()}
res = {"home_points": 118, "away_points": 109}
vsn, vso = sc.build_card_vm(p0, entry=entry_bos(), tables=tabs, result=res), old_sc.build_card_vm(p0, entry=entry_bos(), tables=tabs, result=res)
check("Schnappschuss-Karte beendeter Spiele (auch wenn ein Eintrag uebergeben wird): keine Quoten, HTML identisch zu vorher", vsn["moneyline"] is None and all(r["quote"] is None for b_ in vsn["lines"] for r in b_["rows"]) and flat(sc.render_card_html(vsn)) == flat(old_sc.render_card_html(vso))
      and [flat(sc.line_block_body_html(b_)) for b_ in vsn["lines"]] == [flat(old_sc.line_block_body_html(b_)) for b_ in vso["lines"]])
# Wahrscheinlichkeiten unveraendert (Engine nicht angefasst): Zeilen gleich dem Stand vorher
old_lp = old_module("engine/line_probabilities.py", "old_lp_before_quotes")
check("Wahrscheinlichkeiten unveraendert: Engine-Zeilen == Stand vorher (Prozent, Seiten, Rohwert)", lp.build_line_tables(p0, entry_bos()) == old_lp.build_line_tables(p0, entry_bos()))
# nichts geschrieben: Temp-Tracking-Ordner bleibt leer
tdir = Path(os.environ.get("NBAEDGE_TRACKING_DIR", ""))
check("Tests schreiben nichts: der (Temp-)Tracking-Ordner ist leer und liegt nicht unter data/tracking", not (tdir / "pre_match_entries.json").exists() and str(tdir) != str(ROOT / "data" / "tracking") and not list(tdir.glob("*.json")) if tdir.is_dir() else True, str(tdir))
src_q = (ROOT / "engine" / "betano_quotes.py").read_text(encoding="utf-8")
check("betano_quotes.py liest nur (kein open/write/replace/save/dump im Code)", not re.search(r"\bopen\(|write|os\.replace|save_|\.dump\(|\.save\(", re.sub(r'""".*?"""|#.*', "", src_q, flags=re.S)))

print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
