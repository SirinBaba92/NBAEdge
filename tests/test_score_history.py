"""Tests der Datumsauswahl fuer vergangene Tage im Tab Score Projections (ui/score_history.py, app.py, ui/score_cards.py).
Teil 1: reine Funktionen (Liste der Tage, Pfeile, Sortierung, Prognose-Zeile mit/ohne team2, Abgleich mit dem echten Schnappschuss Celtics-Nets, Standard-Prognose 105 : 119).
Teil 2: echte app.py im AppTest mit simuliertem Netz (tests/fake_net.py) und KOPIEN von data/tracking, upcoming_cache.json, pregame_lines.json im Temp-Ordner; die echten Dateien
werden nur gelesen. Aufruf aus dem Projektordner: venv/bin/python tests/test_score_history.py"""
import copy, hashlib, json, os, re, shutil, sys, warnings
from datetime import date
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from ui import score_history as sh

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
D = date.fromisoformat

REAL_SNAP = ROOT / "data" / "tracking" / "projection_snapshots.json"
real_games = json.loads(REAL_SNAP.read_text(encoding="utf-8"))["games"]               # nur lesen
CN_KEY = "2026-10-27|2026-10-27T23:30:00Z|Boston Celtics|Brooklyn Nets"

# ---- Teil 1: reine Funktionen (mit kleinen, selbst gebauten Schnappschuessen)
def mk(day, start, home, away, result=True, t2=None):
    card = {"home_team": home, "away_team": away, "home_score": 110, "away_score": 100, "exp_spread": 10.0, "exp_total": 210, "home_win_prob": 0.8, "away_win_prob": 0.2, "game_date": day, "game_start": start}
    ver = {"tables": {"x": 1}, **({"team2": t2} if t2 else {})}
    return {"game_date": day, "start_utc": start, "card": card, "versions": [ver], "result": {"home_points": 111, "away_points": 99} if result else None}
G = {"a1": mk("2026-10-22", "2026-10-23T01:00:00Z", "A", "B"), "b1": mk("2026-10-21", "2026-10-22T02:00:00Z", "C", "D"), "b2": mk("2026-10-21", "2026-10-22T00:00:00Z", "E", "F"),
     "b3": mk("2026-10-21", "2026-10-22T00:00:00Z", "A", "F", result=False), "c1": mk("2026-10-24", "2026-10-25T00:00:00Z", "G", "H"), "kaputt": {"game_date": "2026-10-23", "card": None, "versions": []}}
days = sh.day_counts(G)
check("Liste der Tage: aufsteigend, mit Spielzahl, ohne Tage ohne Daten (kaputter Eintrag zaehlt nicht)", days == [(D("2026-10-21"), 3, False), (D("2026-10-22"), 1, False), (D("2026-10-24"), 1, False)], str(days))
days2 = sh.day_counts(G, D("2026-10-25"), ["n1", "n2"])
check("aktiver Spieltag kommt dazu (auch ohne Schnappschuss), Spielzahl aus den geladenen Spielen", days2[-1] == (D("2026-10-25"), 2, True) and [d[0] for d in days2] == sorted(d[0] for d in days2))
days3 = sh.day_counts(G, D("2026-10-24"), ["c1", "neu"])
check("aktiver Spieltag mit Schnappschuessen: keine Doppelzaehlung", days3[-1] == (D("2026-10-24"), 2, True), str(days3[-1]))
check("Beschriftung: 'Di 27.10. · 4 Spiele' / '1 Spiel' / 'Mi 28.10. · 12 Spiele · aktueller Spieltag'",
      sh.day_label(D("2026-10-27"), 4, False) == "Di 27.10. · 4 Spiele" and sh.day_label(D("2026-10-27"), 1, False) == "Di 27.10. · 1 Spiel" and sh.day_label(D("2026-10-28"), 12, True) == "Mi 28.10. · 12 Spiele · aktueller Spieltag")
ds = [d[0] for d in days]
check("Pfeile: Mitte hat Vor- und Folgetag, an den Enden None", sh.neighbours(ds, ds[1]) == (ds[0], ds[2]) and sh.neighbours(ds, ds[0])[0] is None and sh.neighbours(ds, ds[-1])[1] is None)
check("Pfeile: unbekannter Tag -> beide None", sh.neighbours(ds, D("2030-01-01")) == (None, None))
items = sh.past_items(G, D("2026-10-21"))
check("Spiele eines Tages nach Anpfiff sortiert (gleicher Anpfiff nach Schluessel), alle Spiele des Tages", [i["key"] for i in items] == ["b2", "b3", "b1"], str([i["key"] for i in items]))
check("Spiel ohne Ergebnis: result None", items[1]["result"] is None and items[0]["result"] is not None)
card, past = sh.card_inputs(items[0])
check("ohne team2: Standard-Prognose (Gast : Heim), kein Hinweis, Ergebnis Gast : Heim", past == {"result": (99, 111), "pred": (100, 110), "t2": False} and card["exp_spread"] == 10.0, str(past))
T2 = {"measure_home": 0.0, "measure_away": 0.0, "exp_spread": 10.0, "home_score": 110, "away_score": 100, "home_win_prob": 0.8, "away_win_prob": 0.2}
check("team2 ohne Ausfall-Mass (0 / 0): Standard-Prognose ohne Hinweis", sh.card_inputs({**items[0], "team2": T2})[1]["t2"] is False)
T2a = {**T2, "measure_home": 2.0, "exp_spread": 7.0, "home_score": 108, "away_score": 102, "home_win_prob": 0.7, "away_win_prob": 0.3}
card2, past2 = sh.card_inputs({**items[0], "team2": T2a})
check("team2 aktiv: Prognose mit Ausfaellen (Gast : Heim), Hinweis, Spread/Siegchance aus team2, Total unveraendert", past2["pred"] == (102, 108) and past2["t2"] and card2["exp_spread"] == 7.0 and card2["home_win_prob"] == 0.7 and card2["exp_total"] == 210, str(past2))
check("Eingabe wird nicht veraendert", items[0]["card"]["exp_spread"] == 10.0 and "team2" not in items[0]["card"])
# echter Schnappschuss Celtics-Nets (Standard-Prognose Gast 105 : Heim 119, Ergebnis 124 : 125)
cn = sh.past_items(real_games, D("2026-10-27"))
cn = [i for i in cn if i["key"] == CN_KEY]
check("echter Schnappschuss Celtics-Nets gefunden", len(cn) == 1)
if cn:
    cn_card, cn_past = sh.card_inputs(cn[0])
    check("Celtics-Nets: Standard-Prognose 105 : 119, Ergebnis 124 : 125, kein Ausfall-Hinweis (team2 mit Mass 0)", cn_past == {"result": (124, 125), "pred": (105, 119), "t2": False}, str(cn_past))
    t2_copy = copy.deepcopy(cn[0]); t2_copy["team2"] = {**t2_copy["team2"], "measure_home": 1.0, "exp_spread": 10.0, "home_score": 117, "away_score": 107}
    check("Celtics-Nets mit (kuenstlichem) Ausfall-Mass: Prognose mit Ausfaellen 107 : 117 und Hinweis", sh.card_inputs(t2_copy)[1] == {"result": (124, 125), "pred": (107, 117), "t2": True})
old_days = [d for d, _, _ in sh.day_counts(real_games)]
check("echte Datei: Tage ab 21.10., aufsteigend, jeder Tag mit mindestens einem Spiel", old_days and old_days[0] == D("2026-10-21") and old_days == sorted(old_days))

# ---- Teil 1b: past-Modus im Speicher (Anordnung, Farben, Quoten, aktive Karte unveraendert); nichts wird geschrieben
import fake_net
fake_net.install(); fake_net.fresh_env()
from engine import betano_quotes as bq
from engine import line_probabilities as lp
import ui.score_cards as sc
from test_snapshots_helpers import make_proj
flat = lambda html: "".join(line.strip() for line in html.splitlines())
def ln(i, role, active=True, bm="Betano", **kw): return {"id": i, "role": role, "active": active, "bookmaker": bm, **kw}
def entry_bos(home_is_bos=True, bm="Betano"):
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
def past_vm(proj, entry, pred="auto", t2=False, result=(100, 90)):
    tables = lp.build_line_tables(proj, entry)                       # wie gespeichert: Standard-Zeilen
    pr = (proj["away_score"], proj["home_score"]) if pred == "auto" else pred
    return sc.build_card_vm(proj, entry=entry, tables=tables, result={"home_points": result[1], "away_points": result[0]} if result else None, past={"result": result, "pred": pr, "t2": t2})
BOS, BKN = "Boston Celtics", "Brooklyn Nets"
rows_of = lambda vm, key: next(b for b in vm["lines"] if b["key"] == key)["rows"]
qs = lambda vm, key: [r["quote"] for r in rows_of(vm, key)]
pv = past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos())
html = sc.render_card_html(pv); cells = lambda h: re.findall(r'<span class="(pc-[a-z]+)(?: (pc-fav|pc-dog))?">(?:<span[^>]*>)?([^<]*)', re.search(r'<div class="pc-mid pc-mid-past">(.*?)</div>\s*<div class="pc-team">', h, re.S).group(1))
check("Anordnung: Ergebnis (Gast | @ | Heim) und darunter Prognose (Gast | 'Modell-Prognose' | Heim) in derselben Spalten-Reihenfolge", [c[2] for c in cells(html)] == ["100", "@", "90", "105", "Modell-Prognose", "119"] and 'class="pc-mid pc-mid-past"' in html)
check("Zahlen der Prognose halb so gross wie das Ergebnis, Text 15 px", "pc-pscore {" in sc.CARD_CSS and "clamp(23px,2.2vw,33px)" in sc.CARD_CSS and "clamp(46px,4.4vw,66px)" in sc.CARD_CSS and ".pc-pmid {" in sc.CARD_CSS and "font-size:15px" in sc.CARD_CSS.split(".pc-pmid {")[1].split("}")[0])
check("Farben: Team mit mehr prognostizierten Punkten orange, anderes gedaempft", [(c[0], c[1]) for c in cells(html)][3:] == [("pc-pscore", "pc-dog"), ("pc-pmid", ""), ("pc-pscore", "pc-fav")])
h3 = sc.render_card_html(past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos(), pred=(112, 112)))
check("Farben: gleiche Prognose-Punkte -> beide gedaempft", [c[1] for c in cells(h3)][3:] == ["pc-dog", "", "pc-dog"])
h4 = sc.render_card_html(past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos(), pred=(130, 99)))
check("Farben: Gast hat mehr Prognose-Punkte -> Gast orange, Heim gedaempft", [c[1] for c in cells(h4)][3:] == ["pc-fav", "", "pc-dog"])
h5 = sc.render_card_html(past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos(), pred=None))
check("keine Prognose: die Prognose-Zeile entfaellt (nur das Ergebnis, kein 'Modell-Prognose')", "Modell-Prognose" not in h5 and "pc-pscore" not in h5 and [c[2] for c in cells(h5)] == ["100", "@", "90"])
h6 = sc.render_card_html(past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos(), t2=True))
check("Hinweis 'Prognose mit Ausfällen' klein unter dem Text in der Mitte (nur bei team2 aktiv)", 'class="pc-pmid">Modell-Prognose<span class="pc-predt2">Prognose mit Ausfällen</span>' in h6 and "Prognose mit Ausfällen" not in html)
h7 = sc.render_card_html(past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos(), result=None))
check("ohne Ergebnis: Striche, 'kein Ergebnis gespeichert', Prognose-Zeile bleibt", "kein Ergebnis gespeichert" in h7 and [c[2] for c in cells(h7)] == ["–", "@", "–", "105", "Modell-Prognose", "119"])

# Quoten der vergangenen Karte (nur lesend, Betano-Eintrag): Zuordnung wie auf der Karte des aktiven Spieltags
check("Sieger-Quoten unter dem Siegbalken: links Gast 8,50, rechts Heim 1,07 ('Quote 8,50', Komma, 2 Stellen)", pv["moneyline"] == {"away": "8,50", "home": "1,07"} and '<div class="pc-bar-odds"><span>Quote 8,50</span><span>Quote 1,07</span></div>' in flat(html))
check("Spread (Heim = Boston, Modell 13,0): orange Heim rechts -> Quote 1,91; Total 224 > 222,5: Over 1,91; Team Totals Celtics 119 > 117,5: Over 1,85, Nets 105 > 104,5: Over 1,80",
      qs(pv, "spread") == ["1,91"] and qs(pv, "total") == ["1,91"] and qs(pv, "team_home") == ["1,85"] and qs(pv, "team_away") == ["1,80"], f"{qs(pv, 'spread')} {qs(pv, 'total')} {qs(pv, 'team_home')} {qs(pv, 'team_away')}")
u = past_vm(proj_for(BOS, BKN, 11.0, 221.0, 116, 103, 0.80), entry_bos())
check("Spread Modell 11,0: orange Gast links -> Quote der Nets 1,90; Total 221: Under 1,90; Team Totals Under: Celtics 1,85, Nets 1,91", qs(u, "spread") == ["1,90"] and qs(u, "total") == ["1,90"] and qs(u, "team_home") == ["1,85"] and qs(u, "team_away") == ["1,91"], f"{qs(u, 'spread')} {qs(u, 'total')} {qs(u, 'team_home')} {qs(u, 'team_away')}")
r = past_vm(proj_for(BKN, BOS, -13.0, 224.0, 105, 119, 0.16), entry_bos(home_is_bos=False))
check("vertauschte Rollen (Boston Gast): Zeile 'Celtics −12,5', Favorit Gast links -> Celtics-Quote 1,91; Sieger links 1,07 (Gast), rechts 8,50 (Heim)", rows_of(r, "spread")[0]["label"] == "Celtics −12,5" and qs(r, "spread") == ["1,91"] and r["moneyline"] == {"away": "1,07", "home": "8,50"})
live = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=entry_bos())
check("Quoten der vergangenen Karte == Quoten der Karte des aktiven Spieltags bei gleichen Zeilen (engine/betano_quotes wiederverwendet)", all(qs(pv, k) == [x["quote"] for x in rows_of(live, k)] for k in ("spread", "total", "team_home", "team_away")) and pv["moneyline"] == live["moneyline"])
tb = lp.build_line_tables(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos()); tb["total"]["rows"][0] = {**tb["total"]["rows"][0], "predicted": None}
v50 = sc.build_card_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry=entry_bos(), tables=tb, result={"home_points": 90, "away_points": 100}, past={"result": (100, 90), "pred": (105, 119), "t2": False})
check("genau 50 % (keine orange Seite): Zelle leer", qs(v50, "total") == [None])
nq = past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), {"markets": {"winner_incl_ot": {"home_odds": 1.07, "away_odds": 8.5, "bookmaker": "Betano"}}})
check("fehlende Quote: Platz bleibt leer (Spread/Total/Team Totals), Sieger-Quote bleibt", all(q is None for k in ("spread", "total", "team_home", "team_away") for q in qs(nq, k)) and nq["moneyline"] == {"away": "8,50", "home": "1,07"} and "pc-lqcol" not in " ".join(sc.line_block_body_html(b) for b in nq["lines"]))
pin = past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), entry_bos(bm="Pinnacle"))
check("Anbieter nur Betano: Eintrag eines anderen Anbieters -> keine Quote, keine Sieger-Quoten, keine Spalte", pin["moneyline"] is None and all(q is None for k in ("spread", "total", "team_home", "team_away") for q in qs(pin, k)) and "pc-bar-odds" not in sc.render_card_html(pin))
body = " ".join(sc.line_block_body_html(b) for b in pv["lines"])
check("Spalte 'Quote' in den Expandern; nie Mindestquote, Sieger-Zeichen oder Erklaerzeile; Chips bleiben", "pc-lhq" in body and "Mindestquote" not in body and "pc-lmin" not in body and pv["winner"] is None and pv["minodds_note"] is False and "pc-lchip pc-lchip-" in body)
no_entry = past_vm(proj_for(BOS, BKN, 13.0, 224.0, 119, 105, 0.84), None)
check("ohne gespeicherten Eintrag: wie bisher (keine Quoten, keine Spalte, keine Sieger-Quoten)", no_entry["moneyline"] is None and "pc-lqcol" not in " ".join(sc.line_block_body_html(b) for b in no_entry["lines"]))

# Zeilenlayout vergangener Karten: Chip steht in derselben Zeile (demselben Zeilen-Element) wie Linie und Quote
import html as _html
def row_divs(body): return re.findall(r'<div class="(pc-lrow[^"]*)">(.*?)</div>(?=<div class="pc-lrow|<div class="pc-lnote|$)', body, re.S)
cn_item = [i for i in sh.past_items(real_games, D("2026-10-27")) if i["key"] == CN_KEY][0]                    # echter Schnappschuss Celtics-Nets mit mehreren Linien je Block
cn_entry = json.loads((ROOT / "data" / "tracking" / "pre_match_entries.json").read_text()); cn_entry = (cn_entry.get("entries", cn_entry)).get(CN_KEY)
tb50 = copy.deepcopy(cn_item["tables"]); tb50["spread"]["rows"][-1]["predicted"] = None                       # letzte Spread-Zeile genau 50 %: kein Chip, keine Quote
cn_card, cn_past = sh.card_inputs(cn_item)
v_mix = sc.build_card_vm(cn_card, entry=cn_entry, tables=tb50, result=cn_item["result"], past=cn_past)
for blk in v_mix["lines"]:
    body = sc.line_block_body_html(blk); rows = re.findall(r'<div class="(pc-lrow [^"]*)">', body)
    chips_in_rows = [(c, r) for c, r in re.findall(r'<div class="(pc-lrow [^"]*)">((?:(?!<div class="pc-lrow ).)*)', body, re.S)]
    check(f"{blk['title']}: jede Zeile ist EIN Element mit Linie, Quote, Balken und (falls vorhanden) Chip; alle Zeilen tragen pc-lrow-chip + pc-lqcol (auch die ohne Chip, gleiche Spalten und Hoehe)",
          len(rows) == len(blk["rows"]) and all("pc-lrow-chip" in c and "pc-lqcol" in c for c in rows) and all(("pc-lline" in r and "pc-lq" in r and "pc-lbar" in r) for _, r in chips_in_rows)
          and all(("pc-lchip" in r) == bool(row["outcome"]) for (_, r), row in zip(chips_in_rows, blk["rows"])), f"{len(rows)} Zeilen")
    check(f"{blk['title']}: Kopfzeile traegt dieselben Gitterklassen (pc-lqcol pc-lrow-chip), 'Quote' ueber der Quote-Spalte", 'class="pc-lhead pc-lhgrid pc-lqcol pc-lrow-chip"' in body and body.count('class="pc-lhq">Quote<') == 1)
bd = sc.line_block_body_html(next(b for b in v_mix["lines"] if b["key"] == "spread"))
check("Spread mit 50-%-Zeile ohne Chip: die Zeile hat keinen Chip, aber dieselben Klassen wie die anderen Zeilen", bd.count("pc-lchip pc-lchip-") == len(next(b for b in v_mix["lines"] if b["key"] == "spread")["rows"]) - 1)
css = sc.CARD_CSS
check("CSS: sechs Spalten (Linie, Quote, links, Balken, rechts, Chip) fuer pc-lqcol + pc-lrow-chip; schmal: Chip in der ersten Zeile neben Linie und Quote, gleiche Zeilenhoehe",
      re.search(r"\.pc-lqcol\.pc-lrow-chip \{ grid-template-columns:([^;]+);", css) and len(re.search(r"\.pc-lqcol\.pc-lrow-chip \{ grid-template-columns:([^;]+);", css).group(1).replace("minmax(110px,170px)", "A").replace("minmax(90px,1fr)", "B").split()) == 6
      and 'grid-template-areas:"line quote chip" "pl bar pr"' in css and "grid-template-rows:minmax(29px,auto) auto" in css and "max-width:1400px" in css)
check("aktiver Spieltag (Quote, ohne Chip): Zeilen tragen weiter KEIN pc-lrow-chip", all("pc-lrow-chip" not in b for b in (sc.line_block_body_html(x) for x in live["lines"])) and "pc-lhead pc-lhgrid pc-lqcol" in sc.line_block_body_html(live["lines"][0]))

# Karte des aktiven Spieltags unveraendert: HTML-Vergleich mit dem Stand vor dieser Aenderung (Fixture, vorher erzeugt)
gold = json.loads((ROOT / "tests" / "fixtures" / "score_active_card_golden.json").read_text(encoding="utf-8"))
for name, key in (("plain", "card"), ("t2", "card_t2")):
    vm_ = sc.build_card_vm(gold["inputs"][key], entry=gold["inputs"]["entry"])
    check(f"aktiver Spieltag ({name}): Karten-HTML, Zeilen, Sieger-Quoten und Sieger-Zeichen identisch zum Stand vorher", sc.render_card_html(vm_) == gold["golden"][name]["html"]
          and json.loads(json.dumps([b["rows"] for b in vm_["lines"]], default=str)) == json.loads(json.dumps(gold["golden"][name]["lines"], default=str)) and vm_["moneyline"] == gold["golden"][name]["moneyline"]
          and json.loads(json.dumps(vm_["winner"])) == gold["golden"][name]["winner"] and "pc-mid-past" not in sc.render_card_html(vm_) and "pc-pscore" not in sc.render_card_html(vm_))

# ---- Teil 2: echte app.py im AppTest, Kopien im Temp-Ordner
from fake_net import fresh_env, state
tmp = fresh_env()
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
import data.fetcher as fetcher
import data.odds_client as oc
import data.projection_snapshots as ps

sha = lambda p: hashlib.sha1(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
def tree(d): return {str(p.relative_to(d)): sha(p) for p in sorted(Path(d).rglob("*")) if p.is_file()}
REAL = {"tracking": tree(ROOT / "data" / "tracking"), "upcoming": sha(ROOT / "data" / "upcoming_cache.json"), "pregame": sha(ROOT / "data" / "pregame_lines.json")}
trk = Path(os.environ["NBAEDGE_TRACKING_DIR"])
shutil.copytree(ROOT / "data" / "tracking", trk, dirs_exist_ok=True)
for src, env in (("upcoming_cache.json", "NBAEDGE_UPCOMING_CACHE"), ("pregame_lines.json", "NBAEDGE_PREGAME_LINES")):
    if (ROOT / "data" / src).exists():
        shutil.copy2(ROOT / "data" / src, os.environ[env])
os.environ["NBAEDGE_ALL_TABS"] = "0"
snap = trk / "projection_snapshots.json"
today = date.today().isoformat()
def write_snap(data):
    t = trk / "projection_snapshots.json.tmp"; t.write_text(json.dumps(data)); os.replace(t, snap)

CALLS = {"snap": 0, "fetch": 0, "odds": 0}
orig_rs = ps.record_snapshots
def counting_rs(*a, **k):
    CALLS["snap"] += 1
    return orig_rs(*a, **k)
ps.record_snapshots = counting_rs

at_ = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300).run()
cards = lambda a: [m.value for m in a.markdown if 'class="pc-card' in m.value]
text = lambda a: " ".join(str(m.value) for m in list(a.markdown) + list(a.caption))
sel = lambda a: a.selectbox(key="score_day_sel")
check("App laeuft ohne Fehler", not at_.exception and not problems(at_), " | ".join(problems(at_))[:200])
check("neue Sitzung startet auf dem aktiven Spieltag (heute), Chip 'Aktueller Spieltag'", sel(at_).value == today and "Aktueller Spieltag" in text(at_) and "Vergangener Tag" not in text(at_), str(sel(at_).value))
opt_labels = list(sel(at_).options)                                  # in AppTest: die angezeigten Beschriftungen
iso_of = lambda lab: "2026-" + re.search(r"(\d\d)\.(\d\d)\.", lab).group(2) + "-" + re.search(r"(\d\d)\.(\d\d)\.", lab).group(1)
opts = [iso_of(l) for l in opt_labels]
check("Auswahlliste: aufsteigend, ab 21.10., aktiver Spieltag am Ende (mit Zusatz), ohne doppelte Tage", opts == sorted(opts) and opts[0] == "2026-10-21" and opts[-1] == today and len(set(opts)) == len(opts)
      and opt_labels[-1].endswith("· aktueller Spieltag") and sum("aktueller Spieltag" in l for l in opt_labels) == 1, str(opt_labels))
check("Beschriftung 'Di 27.10. · 4 Spiele' (Spielzahl aus dem Schnappschuss)", "Di 27.10. · 4 Spiele" in opt_labels, str(opt_labels))
prev_b, next_b, today_b = at_.button(key="score_day_prev"), at_.button(key="score_day_next"), at_.button(key="score_day_today")
check("auf dem aktiven Spieltag (letzter Eintrag): Folgetag und Heute deaktiviert, Vortag aktiv", next_b.disabled and today_b.disabled and not prev_b.disabled)
active_cards = len(cards(at_))
active_style = " ".join(m.value for m in at_.markdown if m.value.startswith("<style>div:has(> .st-key-sc_game_"))

# Ab hier: Abruffunktionen auf Fehler, Netz-Zaehler merken
def boom(*a, **k): raise AssertionError("Abruf beim Ansehen vergangener Tage")
def odds_boom(*a, **k):
    if k.get("cache_only"):                                       # die Seitenleiste liest den Odds-Zwischenspeicher bei jedem Rerun (nur Datei, kein Abruf)
        return oc_orig(*a, **k)
    raise AssertionError("Odds-API-Abruf beim Ansehen vergangener Tage")
fetcher_orig, oc_orig = fetcher.fetch_upcoming_games, oc.get_odds
fetcher.fetch_upcoming_games = boom; oc.get_odds = odds_boom
net0 = (state["bdl_calls"], len(state["odds_calls"]), state["nba_calls"], state["espn_calls"])
before = {"tracking": tree(trk), "upcoming": sha(os.environ["NBAEDGE_UPCOMING_CACHE"]), "pregame": sha(os.environ["NBAEDGE_PREGAME_LINES"])}
CALLS["snap"] = 0
at_.run(); base_snap_calls = CALLS["snap"]                            # ein Rerun auf dem aktiven Spieltag: so oft ruft die Seite record_snapshots ohnehin auf (Seitenkopf, unveraendert)

# Vortag klicken -> Sprung auf den Tag davor
at_.button(key="score_day_prev").click().run()
check("Vortag: Sprung auf den vorigen Tag der Liste", sel(at_).value == opts[-2] and not at_.exception, str(sel(at_).value))
# Auswahlliste: 27.10.
CALLS["snap"] = 0
sel(at_).select("2026-10-27").run()
past_snap_calls = CALLS["snap"]
check("Auswahl springt auf den gewaehlten Tag, Chip 'Vergangener Tag · nur ansehen', Satz unter der Leiste", sel(at_).value == "2026-10-27" and "Vergangener Tag · nur ansehen" in text(at_)
      and "Gespeicherte Vorab-Prognose mit Ergebnis, so wie sie vor Anpfiff war. Es wird nichts gespeichert und nichts abgerufen." in text(at_) and "Aktueller Spieltag" not in text(at_))
pc = cards(at_)
real27 = [i for i in sh.past_items(real_games, D("2026-10-27"))]
check("vergangener Tag: alle Spiele des Tages als Karten", len(pc) == len(real27) and len(pc) > 0, f"{len(pc)} Karten, erwartet {len(real27)}")
teams_order = [re.findall(r'class="pc-name">([^<]+)<', c) for c in pc]
exp_order = [[i["card"]["away_team"].split()[-1], i["card"]["home_team"].split()[-1]] for i in real27]
check("Karten nach Anpfiff sortiert (wie past_items)", len(teams_order) == len(exp_order) and all(t[0].endswith(e[0]) and t[1].endswith(e[1]) for t, e in zip(teams_order, exp_order)), f"{teams_order} / {exp_order}")
cn_html = [c for c in pc if "Celtics" in c and "Nets" in c]
mid_of = lambda c: re.search(r'<div class="pc-mid pc-mid-past">(.*?)</div>\s*<div class="pc-team">', c, re.S).group(1)
cells_of = lambda c: re.findall(r'<span class="(pc-[a-z]+)(?: (pc-fav|pc-dog))?">(?:<span[^>]*>)?([^<]*)', mid_of(c))
check("Celtics-Nets: Ergebnis 124 | @ | 125, darunter 105 | Modell-Prognose | 119 (Gast links, Heim rechts), ohne Ausfall-Hinweis",
      len(cn_html) == 1 and [c[2] for c in cells_of(cn_html[0])] == ["124", "@", "125", "105", "Modell-Prognose", "119"] and "Prognose mit Ausfällen" not in cn_html[0], str(cells_of(cn_html[0]))[:200])
check("Celtics-Nets: Farben wie beim Ergebnis (Heim 125 und Prognose 119 orange, Gast gedaempft)", [(c[0], c[1]) for c in cells_of(cn_html[0])] == [("pc-score", "pc-dog"), ("pc-at", ""), ("pc-score", "pc-fav"), ("pc-pscore", "pc-dog"), ("pc-pmid", ""), ("pc-pscore", "pc-fav")])
joined = " ".join(pc)
check("Karten ohne Mindestquoten, Sieger-Zeichen und Schalter team-2", "Mindestquote" not in joined and "pc-winner" not in joined and "pc-sw" not in joined)
real_entries = json.loads((trk / "pre_match_entries.json").read_text()); real_entries = real_entries.get("entries", real_entries)
wq = (real_entries.get(CN_KEY) or {}).get("markets", {}).get("winner_incl_ot") or {}
check("Celtics-Nets: Betano-Sieger-Quoten unter dem Siegbalken (links Gast, rechts Heim) aus dem gespeicherten Eintrag", bool(wq) and re.search(r'class="pc-bar-odds"><span>Quote ' + f"{wq['away_odds']:.2f}".replace(".", ",") + r'</span><span>Quote ' + f"{wq['home_odds']:.2f}".replace(".", ",") + "</span>", cn_html[0]) is not None, str(wq))
blocks = [m.value for m in at_.markdown if 'class="pc-lrow' in m.value]
check("Zeilen tragen die gespeicherten Chips (eingetreten / nicht eingetreten)", any("pc-lchip pc-lchip-" in b for b in blocks), f"{len(blocks)} Bloecke")
check("Karten des aktiven Spieltags sind nicht dabei", not active_style or not any(h in " ".join(m.value for m in at_.markdown if m.value.startswith("<style>div:has(> .st-key-sc_game_")) for h in re.findall(r"sc_game_([0-9a-f]{10})", active_style)))
check("kein Fehler beim Ansehen", not at_.exception and not problems(at_), " | ".join(problems(at_))[:200])

# Pfeile an den Enden: erster Tag
sel(at_).select(opts[0]).run()
check("Pfeile: am ersten Tag ist Vortag deaktiviert, Folgetag aktiv", at_.button(key="score_day_prev").disabled and not at_.button(key="score_day_next").disabled)
at_.button(key="score_day_next").click().run()
check("Folgetag: Sprung auf den naechsten Tag der Liste", sel(at_).value == opts[1])
at_.button(key="score_day_today").click().run()
check("Heute: springt auf den aktiven Spieltag, Karten wie vorher", sel(at_).value == today and len(cards(at_)) == active_cards and "Aktueller Spieltag" in text(at_), f"{len(cards(at_))} vs {active_cards}")
check("aktiver Spieltag unveraendert (gleiche Kartenreihenfolge)", " ".join(m.value for m in at_.markdown if m.value.startswith("<style>div:has(> .st-key-sc_game_")) == active_style)

# nichts abgerufen, nichts geschrieben
net1 = (state["bdl_calls"], len(state["odds_calls"]), state["nba_calls"], state["espn_calls"])
after = {"tracking": tree(trk), "upcoming": sha(os.environ["NBAEDGE_UPCOMING_CACHE"]), "pregame": sha(os.environ["NBAEDGE_PREGAME_LINES"])}
check("Ansehen vergangener Tage ruft fetch_upcoming_games und Odds-API nie auf (beide auf Fehler gesetzt, kein Fehler aufgetreten)", not at_.exception)
check("kein Netzabruf (BallDontLie, Odds-API, NBA.com, ESPN) beim Blaettern", net0 == net1, f"{net0} -> {net1}")
check("record_snapshots: auf einem vergangenen Tag nicht haeufiger als auf dem aktiven Spieltag (Aufruf kommt nur vom Seitenkopf)", past_snap_calls <= max(base_snap_calls, 1), f"{past_snap_calls} <= {base_snap_calls}")
check("data/tracking, upcoming_cache.json, pregame_lines.json (Kopien) vor und nach dem Ansehen byteidentisch", before == after)
fetcher.fetch_upcoming_games, oc.get_odds = fetcher_orig, oc_orig

# Spiel ohne Ergebnis und team2 mit Ausfall: Kopie im Temp-Ordner veraendern
data_ = json.loads(snap.read_text())
g27 = [(k, g) for k, g in data_["games"].items() if g["game_date"] == "2026-10-27"]
k_none = [k for k, g in g27 if k != CN_KEY][0]
data_["games"][k_none]["result"] = None
cn_ver = data_["games"][CN_KEY]["versions"][-1]
cn_ver["team2"].update(measure_home=1.0, exp_spread=10.0, home_score=117, away_score=107)
write_snap(data_)
sel(at_).select("2026-10-27").run()
pc = cards(at_)
nores = [c for c in pc if "kein Ergebnis gespeichert" in c]
check("Spiel ohne Ergebnis: 'kein Ergebnis gespeichert' (nur dieses)", len(nores) == 1, f"{len(nores)}")
cn_html = [c for c in pc if "Celtics" in c and "Nets" in c][0]
check("team2 mit Ausfall-Mass: 107 | Modell-Prognose | 117, Hinweis 'Prognose mit Ausfällen' klein in der Mitte, ohne Schalter",
      [c[2] for c in cells_of(cn_html)][3:] == ["107", "Modell-Prognose", "117"] and re.search(r'class="pc-pmid">Modell-Prognose<span class="pc-predt2">Prognose mit Ausfällen</span>', cn_html) and "pc-sw" not in cn_html)
items_now = sh.past_items(json.loads(snap.read_text())["games"], D("2026-10-27"))
n_t2 = sum(sh.t2_active(i.get("team2")) for i in items_now)
check("Expander tragen 'Linien: Standard-Modell' genau bei den Spielen mit Ausfall-Prognose (4 Bloecke je Spiel)", n_t2 >= 1 and sum("Linien: Standard-Modell" in m.value for m in at_.markdown) == 4 * n_t2, f"{n_t2} Spiele mit Ausfall-Prognose")
check("Hinweis 'Prognose mit Ausfällen' genau bei diesen Karten; ohne team2 / Mass 0: kein Hinweis", sum("Prognose mit Ausfällen" in c for c in pc) == n_t2, f"{n_t2}")

# Neuladen = neue Sitzung: startet wieder auf dem aktiven Spieltag
at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300).run()
check("Neuladen (neue Sitzung) startet auf dem aktiven Spieltag", at2.selectbox(key="score_day_sel").value == today and "Aktueller Spieltag" in text(at2) and not at2.exception)
check("echte Dateien unveraendert (data/tracking, upcoming_cache.json, pregame_lines.json)",
      REAL == {"tracking": tree(ROOT / "data" / "tracking"), "upcoming": sha(ROOT / "data" / "upcoming_cache.json"), "pregame": sha(ROOT / "data" / "pregame_lines.json")})
check("in KEINEM AppTest-Lauf dieser Datei: Streamlit-Exception oder der Satz 'was created with a default value ... Session State API'", not page_checks.bad, "; ".join(page_checks.bad[:2]))
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
