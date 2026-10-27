"""Test der Spieler-Karten (ui/player_view.render_cards_html): gleiche Zahlen und Reihenfolge wie die Tabelle, Warnsymbol, Differenz-Farben, Markierung ueber 5 PP, Extremwerte, ohne Quote,
Live-Zusatz. Ohne App, ohne Netz. Aufruf aus dem Projektordner: venv/bin/python tests/test_player_cards.py"""
import os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from ui import player_view as pv

def player(pid, name, abbr, ok=True, warn=None, mins=30.0, pts=18.0, quotes=(), model=None):
    model = model or {}
    return {"person_id": pid, "name": name, "team": "Heim Falken", "team_abbreviation": abbr, "ok": ok, "reason": None if ok else "kein Verlauf", "quality": [], "warnings": [warn] if warn else [],
            "minutes": {"base": mins, "mean": mins, "role": "Stamm"}, "minutes_adjusted": mins, "expected_points_raw": pts, "expected_points_adjusted": pts,
            "p_ge_raw": {str(k): v for k, v in model.items()}, "p_ge_adjusted": {str(k): v for k, v in model.items()},
            "quotes": [{"milestone": n, "odds": o, "bookmaker": "Betano", "bookmaker_probability": bp, "bookmaker_percent": round(bp * 100)} for n, o, bp in quotes]}

ENTRY = {"game_key": "k", "players": [
    player(1, "Plus Plus", "HEI", warn="Rollenwechsel (fraglich)", pts=22.0, quotes=[(15, 1.20, 0.80), (20, 1.85, 0.54), (25, 3.0, 0.32), (30, 5.5, 0.17)], model={15: 0.90, 20: 0.60, 25: 0.30, 30: 0.12}),
    player(2, "Minus Minus", "HEI", pts=12.0, mins=22.0, quotes=[(10, 1.6, 0.62), (15, 2.4, 0.41)], model={10: 0.52, 15: 0.40}),
    player(3, "Extrem Werte", "GAS", pts=3.0, mins=9.0, quotes=[(2, 1.01, 0.99), (10, 80.0, 0.0125)], model={2: 1.0, 10: 0.004}),
    player(4, "Ohne Quote", "GAS", pts=8.0, mins=15.0, quotes=[(5, None, 0.5)], model={5: 0.505}),
    player(5, "Ohne Prognose", "GAS", ok=False, quotes=[(10, 2.0, 0.5)]),
    player(6, "Ohne Meilensteine", "GAS", pts=6.0, mins=11.0, quotes=[], model={}),
]}

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
cards_of = lambda h: re.findall(r"<div class='pl-card(?: pl-card-aff)?'>.*?(?=<div class='pl-card(?: pl-card-aff)?'>|</div><div class='pl-c-legend'>)", h, flags=re.S)
model = pv.build_table_model(ENTRY, "team", "team")
H = pv.render_cards_html(model)
cs = cards_of(H)
by = {c.split("pl-c-name'>")[1].split("<")[0].strip(): c for c in cs}
check("eine Karte je Spieler, Raster, EIN HTML-Block", len(cs) == 6 and "grid-template-columns:repeat(2,minmax(0,1fr))" in pv.CARDS_CSS and "max-width:700px" in pv.CARDS_CSS and "auto-fill" not in pv.CARDS_CSS and H.startswith("<div class='pl-cards'>"))
check("Reihenfolge wie Tabelle (Sortierung Team, Minuten)", [c.split("pl-c-name'>")[1].split("<")[0].strip() for c in cs] == [p["name"] for p in model["players"]])
for sort in ("minutes", "diff"):
    m = pv.build_table_model(ENTRY, "team", sort)
    check(f"Reihenfolge wie Tabelle (Sortierung {sort})", [c.split("pl-c-name'>")[1].split("<")[0].strip() for c in cards_of(pv.render_cards_html(m))] == [p["name"] for p in m["players"]])
check("Warnsymbol nur bei Spielern mit Hinweis", "⚠" in by["Plus Plus"] and "⚠" not in by["Minus Minus"] and "title='Rollenwechsel" in by["Plus Plus"])
check("Metazeile: '22,0 Punkte erwartet · 30,0 Min' (Zahlen fett)", "<b>22,0</b> Punkte erwartet · <b>30,0</b> Min" in by["Plus Plus"], re.search(r"pl-c-meta'>.*?</div>", by["Plus Plus"]).group(0))
check("Team klein rechts, Quote klein unter dem Meilenstein", "pl-c-team'>HEI" in by["Plus Plus"] and "<b>20+</b><span class='pl-c-odds'>@ 1,85</span>" in by["Plus Plus"])
# Zahlen exakt wie die Tabelle
nums_ok = True
for p in model["players"]:
    for r in p["rows"]:
        d = "–" if r["diff"] is None else pv.fmt_num(r["diff"], 1, signed=True)
        nums_ok &= (f"Betano</span> <b>{r['buch_pct']} %</b>" in by[p["name"]] and (f"Modell</span> <b>{r['model_pct']} %</b>" in by[p["name"]] or r["model_pct"] is None) and f">{d}<" in by[p["name"]])
check("Prozentwerte und Differenzen identisch zur Tabelle (Betano, Modell, Differenz je Zeile)", nums_ok)
# Differenzfarben und Markierung
p1 = {r["n"]: r for r in model["players"][[q["name"] for q in model["players"]].index("Plus Plus")]["rows"]}
rowhtml = lambda name, n: next(x for x in by[name].split("<div class='pl-c-row") if f"<b>{n}+</b>" in x)
check("Differenz +6 PP (20+): gruen, Pfeil ◀", "pl-cd-gruen'>+6,0" in rowhtml("Plus Plus", 20) and "◀" in rowhtml("Plus Plus", 20), rowhtml("Plus Plus", 20)[:120])
check("Differenz -10 PP (10+): rot, Pfeil ▼", "pl-cd-rot" in rowhtml("Minus Minus", 10) and "▼" in rowhtml("Minus Minus", 10))
check("Differenz zwischen -3 und +3 (25+: -2): grau, ohne Pfeil", "pl-cd-grau'>−2,0" in rowhtml("Plus Plus", 25) and "pl-c-mark" not in rowhtml("Plus Plus", 25), rowhtml("Plus Plus", 25)[-160:])
check("Schwellen: +3 gruen, -3 rot, 2,9 grau", [pv.diff_class(x) for x in (3.0, -3.0, 2.9, -2.9, None)] == ["pl-cd-gruen", "pl-cd-rot", "pl-cd-grau", "pl-cd-grau", "pl-cd-grau"])
check("5 PP genau: Pfeil/Hintergrund wie bei der Tabelle (mark_for)", pv.mark_for(5.0) == "◀" and pv.mark_for(4.9) == "")
# Balken, Extremwerte
ex = by["Extrem Werte"]
check("Extremwerte: 99 % / 100 % und 1 % / 0 % Balkenbreiten im Bereich 0..100", "width:99%" in ex and "width:100%" in ex and "width:1%" in ex and "width:0%" in ex and "width:-" not in ex and "width:101" not in ex)
check("Balken: oben Betano blau, darunter Modell orange; Text 'Betano 71 % · Modell 72 %'-Form", pv.BLUE == "#6f8fd6" and pv.ORANGE == "#ff7a2f" and ex.index("pl-c-bar-b") < ex.index("pl-c-bar-m") and "Betano</span> <b>99 %</b> · <span class='pl-c-wm'>Modell</span> <b>100 %</b>" in ex)
check("ohne Quote: keine '@'-Zeile, Karte vollstaendig", "pl-c-odds" not in by["Ohne Quote"] and "<b>5+</b>" in by["Ohne Quote"] and "@ None" not in by["Ohne Quote"])
check("ohne Prognose: 'keine Prognose', Modell '–', Differenz '–', kein Modellbalken", "keine Prognose" in by["Ohne Prognose"] and "Modell</span> <b>–</b>" in by["Ohne Prognose"] and "pl-c-bar-m" not in by["Ohne Prognose"] and ">–<" in by["Ohne Prognose"])
check("ohne Meilensteine: Hinweis statt Zeilen", "keine Meilensteine eingelesen" in by["Ohne Meilensteine"] and "pl-c-row" not in by["Ohne Meilensteine"])
check("Legende: Betano blau, Modell orange (ungeprüft), Differenz in PP", "Betano inkl. Marge" in H and "Modell (ungeprüft)" in H and "Prozentpunkten" in H)
def _pe(model_p, book_p):
    return {"game_key": "k", "players": [player(9, "Schwelle", "HEI", pts=20.0, quotes=[(20, 2.0, book_p)], model={20: model_p})]}
hi = lambda mp, bp: "pl-c-hi" in pv.render_cards_html(pv.build_table_model(_pe(mp, bp), "team", "team"))
check("Schwelle 60: bei 60 % und 61 % hinterlegt, bei 59 % nicht (angezeigter Wert zaehlt)", pv.CARD_HIGHLIGHT_MIN_PCT == 60 and hi(0.60, 0.60) and hi(0.61, 0.61) and not hi(0.59, 0.59) and hi(0.595, 0.595) and not hi(0.594, 0.594))
check("Hinterlegung unabhaengig von der Differenz (60 % mit Diff +20 und -20 hinterlegt, 59 % mit Diff +20 nicht)", hi(0.60, 0.40) and hi(0.60, 0.80) and not hi(0.59, 0.39))
check("Differenz allein hinterlegt nie (Plus Plus 25+: 30 % Modell; Minus Minus 15+: 40 %)", "pl-c-hi" not in rowhtml("Minus Minus", 15) and "pl-c-hi" not in rowhtml("Plus Plus", 25) and "pl-c-hi" in rowhtml("Plus Plus", 20) and "pl-c-hi" in rowhtml("Plus Plus", 15))
check("Modus roh nutzt den dort angezeigten Wert", "pl-c-hi" in pv.render_cards_html(pv.build_table_model(_pe(0.7, 0.5), "raw", "team")))
check("Legende: 'Violett hinterlegt = Modell ≥ 60 %'", "Violett hinterlegt = Modell ≥ 60 %" in H and ".pl-c-hi { background:rgba(139,92,246,.16)" in pv.CARDS_CSS.replace("{{", "{"))
check("keine farbige Zeilenhinterlegung mehr, Wortfarben Betano blau / Modell orange, Text 17 px", "pl-c-hot" not in H and "pl-c-hot" not in pv.CARDS_CSS and ".pl-c-wb { color:#6f8fd6" in pv.CARDS_CSS.replace("{{", "{") and "pl-c-wm" in pv.CARDS_CSS and "font-size:17px; line-height" in pv.CARDS_CSS)
check("Stylesheet: Farben nur im Karten-CSS, Tabellen-CSS (Regel 3) unveraendert ohne Gruen/Rot", not any(c in pv.PLAYER_CSS for c in ("#22c55e", "#ef4444", "#86efac", "#fca5a5")))
# Fenster/Wetten wie Tabelle
mw = pv.build_table_model(ENTRY, "team", "team", {1: {"milestone": 30, "odds": 5.5}}, None, None, 3.0)
hw = pv.render_cards_html(mw)
check("Standardfenster: weniger Zeilen wie in der Tabelle, eigene Wette bleibt (🎯 30+)", hw.count("pl-c-row'") < H.count("pl-c-row'") and "<b>30+</b>" in hw and "🎯 30+" in hw)
# raw-Modus
mr = pv.build_table_model(ENTRY, "raw", "team")
check("Modus roh: gleiche Zahlen wie Tabelle", "Plus Plus" in pv.render_cards_html(mr))
# Live-Zusatz
lv = {1: {"points": 21, "minutes": 25.5, "fouls": 2, "status": "spielt", "chances": {25: 0.4, 30: 0.1}, "notes": ["Foulprobleme"], "out": False}}
ml = pv.attach_live(pv.build_table_model(ENTRY, "team", "team"), lv)
hl = pv.render_cards_html(ml)
c1 = cards_of(hl)[[q["name"] for q in ml["players"]].index("Plus Plus")]
check("laufendes Spiel: 'Jetzt', Live-Chance je Zeile, 'erreicht' fuer erreichte Linie", "Jetzt: <b>21</b> Pkt" in c1 and "Live 40 %" in c1 and "erreicht" in c1 and "Foulprobleme" in c1)

# ----------------------------------------------------------------------------- Stufe 2: Karten mit Ausfaellen (Variante)
import copy, inspect
BASE = ENTRY
VAR = copy.deepcopy(ENTRY)
for q in VAR["players"]:
    if q["person_id"] == 1:                                    # betroffen: Minuten 30 -> 35, Punkte 22 -> 24,4; Modell 15+: 90 -> 95, 20+: 60 -> 60, 25+: 30 -> 64, 30+: 12 -> 12
        q["minutes"] = {"base": 35.0, "mean": 35.0, "role": "Stamm"}; q["minutes_adjusted"] = 35.0; q["expected_points_raw"] = q["expected_points_adjusted"] = 24.4
        q["p_ge_raw"] = q["p_ge_adjusted"] = {"15": 0.95, "20": 0.60, "25": 0.64, "30": 0.12}
    if q["person_id"] == 2:                                    # nicht betroffen (Minuten/Punkte gleich), Modell 10+: 52 -> 52, 15+: 40 -> 30
        q["p_ge_raw"] = q["p_ge_adjusted"] = {"10": 0.52, "15": 0.30}
vm = pv.attach_variant(pv.build_table_model(VAR, "team", "team"), BASE, "team")
HV = pv.render_cards_html(vm)
bv = {c.split("pl-c-name'>")[1].split("<")[0].strip(): c for c in cards_of(HV)}
rowv = lambda name, n: next(x for x in bv[name].split("<div class='pl-c-row") if f"<b>{n}+</b>" in x)
check("ohne Ausfaelle: Karten unveraendert (kein Variant-Zusatz, kein Kasten)", "pl-c-aff" not in H.replace("pl-c-aff {", "") and "vorher" not in H and "pl-c-abs'" not in H and "nicht betroffen" not in H)
check("betroffener Spieler: gelber Rand + Box 'Ausfaelle wirken: Minuten 30,0 -> 35,0 · Punkte 22,0 -> 24,4 (+2,4)', alt durchgestrichen",
      "pl-card pl-card-aff" in HV and "<div class='pl-card pl-card-aff'><div class='pl-c-head'><span class='pl-c-name'>Plus Plus" in HV and "Ausfälle wirken: Minuten <s>30,0</s> → <b>35,0</b> · Punkte <s>22,0</s> → <b>24,4</b> (+2,4)" in bv["Plus Plus"] and "pl-c-meta" not in bv["Plus Plus"], bv["Plus Plus"][:260])
check("nicht betroffener Spieler: normale Metazeile mit 'nicht betroffen', kein gelber Rand", "· nicht betroffen" in bv["Minus Minus"] and "pl-card-aff" not in bv["Minus Minus"] and "Ausfälle wirken" not in bv["Minus Minus"])
check("Modell neu in Balken/Text und Differenz (15+: Modell 95 %, Betano 80 % -> +15,0)", "<b>95 %</b>" in rowv("Plus Plus", 15) and "+15,0" in rowv("Plus Plus", 15))
check("'vorher' nur bei Aenderung ab 1 PP: 15+ (90->95) und 25+ (30->64) ja, 20+ (60->60) und 10+ (52->52) nein",
      "vorher 90 %" in rowv("Plus Plus", 15) and "vorher 30 %" in rowv("Plus Plus", 25) and "vorher" not in rowv("Plus Plus", 20) and "vorher" not in rowv("Minus Minus", 10) and "vorher 40 %" in rowv("Minus Minus", 15))
check("Violett nach neuem Wert: 25+ jetzt 64 % hinterlegt (vorher 30 %), 15+ 30 % bei Minus nicht", "pl-c-hi" in rowv("Plus Plus", 25) and "pl-c-hi" not in rowv("Minus Minus", 15))
vs = pv.build_table_model(VAR, "team", "diff")
check("Sortierung 'groesste Differenz' gilt fuer den angezeigten Wert", [c.split("pl-c-name'>")[1].split("<")[0].strip() for c in cards_of(pv.render_cards_html(pv.attach_variant(vs, BASE)))] == [p["name"] for p in vs["players"]])
cur = {"out": {1: {"name": "Plus Plus", "team": "Heim Falken", "source": "espn", "fetched_at": "2026-10-26T04:44:00+01:00"}}, "doubtful": {2: {"name": "Minus Minus", "team": "Heim Falken"}},
       "auto": {"source": "espn", "fetched_at": "2026-10-26T04:44:00+01:00", "unmatched": []}}
box = pv.absence_box_html(cur)
check("Ausfall-Kasten: Fehlt/Fraglich mit Team, Herkunft 'automatisch (ESPN), Stand 04:44' und 'von Hand'", "Ausfälle für dieses Spiel" in box and "Fehlt: Plus Plus (Heim Falken)" in box and "Fraglich: Minus Minus (Heim Falken)" in box and "automatisch (ESPN), Stand 04:44" in box and "von Hand" in box, box[:200])
check("Kasten nur mit Ausfaellen, steht vor den Karten", pv.absence_box_html({"out": {}, "doubtful": {}}) == "" and pv.render_cards_html(vm, cur).startswith("<div class='pl-c-abs'>") and "pl-c-abs'" not in pv.render_cards_html(vm))
check("nur von Hand: Herkunft 'von Hand' ohne ESPN", "von Hand" in pv.absence_box_html({"out": {1: {"name": "A", "team": "T"}}, "doubtful": {}}) and "ESPN" not in pv.absence_box_html({"out": {1: {"name": "A", "team": "T"}}, "doubtful": {}}))
from ui import player_absence as pa
src = Path(ROOT / "ui" / "player_tab.py").read_text(encoding="utf-8")
check("Vergleichstabelle nur in der Tabellenansicht (show_compare, Standard True; Tab reicht table_view durch)", inspect.signature(pa.render_absences).parameters["show_compare"].default is True and "show_compare=table_view" in src)

# ----------------------------------------------------------------------------- dritter Balken: der jeweils andere Modellwert
OT = {"game_key": "k", "players": [
    {**player(21, "Zwei Werte", "HEI", pts=20.0, quotes=[(20, 1.8, 0.55), (25, 3.0, 0.30)], model={}), "p_ge_raw": {"20": 0.56, "25": 0.31}, "p_ge_adjusted": {"20": 0.44, "25": 0.22}},
    {**player(22, "Fehlender Wert", "HEI", pts=18.0, quotes=[(20, 1.8, 0.55), (25, 3.0, 0.30)], model={}), "p_ge_raw": {"20": 0.50}, "p_ge_adjusted": {"20": 0.40, "25": 0.20}},
    {**player(23, "Keine Prognose", "HEI", ok=False, quotes=[(20, 2.0, 0.5)], model={})}]}
ht = pv.render_cards_html(pv.build_table_model(OT, "team", "team"))
hr = pv.render_cards_html(pv.build_table_model(OT, "raw", "team"))
cards_t = {c.split("pl-c-name'>")[1].split("<")[0].strip(): c for c in cards_of(ht)}
cards_r = {c.split("pl-c-name'>")[1].split("<")[0].strip(): c for c in cards_of(hr)}
row_of = lambda cards, name, n: next(x for x in cards[name].split("<div class='pl-c-row") if f"<b>{n}+</b>" in x)
rt, rr = row_of(cards_t, "Zwei Werte", 20), row_of(cards_r, "Zwei Werte", 20)
check("Modus Teamabgleich: Hauptwert 44 %, dritter Balken und Text = Roh 56 % (in der dritten Farbe)", "<b>44 %</b>" in rt and "pl-c-bar pl-c-bar-o'><i style='width:56%'>" in rt and "<span class='pl-c-wo'>Roh <b>56 %</b></span>" in rt, rt[:420])
check("Modus roh: Hauptwert 56 %, dritter Balken und Text = Teamabgleich 44 %", "<b>56 %</b>" in rr and "pl-c-bar pl-c-bar-o'><i style='width:44%'>" in rr and "<span class='pl-c-wo'>Teamabgleich <b>44 %</b></span>" in rr)
check("dritter Balken steht unter Betano und Modell, gleich dick wie die anderen beiden (10 px), Farbe gedaempft", rt.index("pl-c-bar-b") < rt.index("pl-c-bar-m") < rt.index("pl-c-bar-o") and ".pl-c-bar-o i {" in pv.CARDS_CSS.replace("{{", "{") and "height:6px" not in pv.CARDS_CSS and pv.OTHER == "#9fb8ad" and "#9fb8ad" in pv.CARDS_CSS)
check("Differenz, Pfeil und Hervorhebung bleiben beim gewaehlten Modus (Team: 44 % - 55 % = -11 PP mit Pfeil; roh: 56 % >= 60 nicht, 1,0 PP)", "▼" in rt and "pl-cd-rot'>−11,0" in rt and "pl-c-hi" not in rt and "pl-cd-grau'>+1,0" in rr and "▼" not in rr)
rm = row_of(cards_t, "Fehlender Wert", 25)
check("fehlender anderer Wert (roh fehlt bei 25+): kein dritter Balken, kein Text, kein 'None', Zeile vollstaendig", "pl-c-bar-o" not in rm and "pl-c-wo" not in rm and "None" not in ht and "None" not in hr and "<b>25+</b>" in rm and "Modell</span> <b>20 %</b>" in rm, rm[:300])
rn = cards_t["Keine Prognose"]
check("Spieler ohne Prognose: kein dritter Balken, kein Fehler", "pl-c-bar-o" not in rn and "keine Prognose" in rn)
check("Rotation/gleiche Werte: dritter Balken zeigt denselben Wert (nichts Falsches)", "<span class='pl-c-wo'>Roh <b>70 %</b></span>" in pv.render_cards_html(pv.build_table_model(_pe(0.7, 0.5), "team", "team")))
check("Datenattribute der klickbaren Zeilen unveraendert (Modell = angezeigter Wert, Quote, Betano)", "data-model='44'" in rt and "data-model='56'" in rr and "data-buch='55'" in rt and "data-odds='1.8'" in rt)
check("60-%-Linie: Balken in einem Rahmen mit Linie bei CARD_HIGHLIGHT_MIN_PCT, Legendenhinweis, Zeilen unveraendert klickbar", "<div class='pl-c-bars'>" in rt and ".pl-c-bars::after" in pv.CARDS_CSS.replace("{{", "{") and f"left:{pv.CARD_HIGHLIGHT_MIN_PCT}%" in pv.CARDS_CSS and "weiße Linie im Balken = 60 %" in ht and "pointer-events:none" in pv.CARDS_CSS and "data-pid='21'" in rt)
mv = pv.attach_variant(pv.build_table_model(OT, "team", "team"), OT, "team")
check("Variante mit Ausfaellen: dritter Balken und 'vorher' nebeneinander ohne Fehler", "pl-c-bar-o" in pv.render_cards_html(mv))
tab = pv.render_table_html(pv.build_table_model(OT, "team", "team"))
check("Tabellenansicht unveraendert (kein dritter Balken, keine neue Spalte)", "pl-c-bar-o" not in tab and "pl-c-wo" not in tab and "<th>Differenz" in tab)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
