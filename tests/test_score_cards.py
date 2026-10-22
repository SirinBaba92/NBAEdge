"""Tests fuer die Karten im Tab Score Projections (ui/score_cards.py).
Offline: simulierte Netzantworten (tests/fake_net.py), kein echter API-Call. Aufruf aus dem Projektordner:
  venv/bin/python tests/test_score_cards.py"""
import ast, contextlib, hashlib, os, re, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
fake_net.install()
fake_net.fresh_env()
import page_checks; page_checks.install()          # Caches/Logs in Temp-Verzeichnis, nie im Projekt-data/
import config.settings as settings
import ui.score_cards as sc
from models.elo import MODEL_PATH

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
src = (ROOT / "app.py").read_text()
flat_src = next(ast.get_source_segment(src, n) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "flat_html")
_ns = {}; exec(flat_src, _ns); flat_html = _ns["flat_html"]            # die echte Hilfsfunktion aus app.py

# ----------------------------------------------------------------- Kontrast
def lum(hexc):
    c = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)
P = sc.PALETTE
pairs = {"Teamname/Modellwert": (P["text"], P["card_bg"]), "Marktwert/Leistenlabel": (P["text_soft"], P["card_bg"]),
         "kleine Labels": (P["label"], P["card_bg"]), "@": (P["at"], P["card_bg"]), "Score Underdog": (P["dog"], P["card_bg"]),
         "Score Favorit (orange)": (P["accent"], P["card_bg"]), "Chip grau": (P["chip_gray_text"], P["chip_gray_bg"]),
         "Chip gelb": (P["chip_yellow_text"], P["chip_yellow_bg"]), "Kuerzel im Kreis": (P["fb_text"], P["fb_bg"])}
worst = min(ratio(*v) for v in pairs.values())
check("Kontrast aller Textfarben >= 4,5 : 1", worst >= 4.5, ", ".join(f"{k} {ratio(*v):.1f}" for k, v in pairs.items()))
def greenish(h):
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5)); return g > r + 25 and g > b + 25
check("Plakette: weisse Fettschrift auf pill_bg: Kontrast >= 3 : 1 (WCAG grosser Text, 16 px fett), auf dem Sieg-Orange waeren es < 3 : 1", ratio(P["pill_text"], P["pill_bg"]) >= 3.0 and ratio(P["pill_text"], P["accent"]) < 3.0, f"{ratio(P['pill_text'], P['pill_bg']):.2f} : 1 (auf #f97316: {ratio(P['pill_text'], P['accent']):.2f} : 1)")
check("keine gruene Farbe in der Palette", not any(greenish(v) for v in P.values() if v.startswith("#")))
accent_rules = [m.group(1) for m in re.finditer(r"(\.[\w-]+)\s*\{[^}]*" + re.escape(P["accent"]), sc.CARD_CSS)]
check("Orange (#f97316) nur in .pc-fav und .pc-seg-fav; die Plakette .pc-lpct-pred nutzt das abgedunkelte Orange pill_bg", sorted(accent_rules) == [".pc-fav", ".pc-seg-fav"] and ".pc-lpct-pred" in sc.CARD_CSS and P["pill_bg"] in sc.CARD_CSS, str(accent_rules))

# ----------------------------------------------------------------- Teamzuordnung
from nba_api.stats.static import teams as static_teams
api = {t["abbreviation"]: t for t in static_teams.get_teams()}
mine = {a: (c, n) for a, c, n in sc.TEAMS}
check("30 Teams, Kuerzel und Namen stimmen mit nba_api ueberein",
      set(mine) == set(api) and all(api[a]["nickname"] == n for a, (c, n) in mine.items()))
check("LA Clippers == Los Angeles Clippers == LAC", sc.team_info("LA Clippers")["abbr"] == sc.team_info("Los Angeles Clippers")["abbr"] == sc.team_info("LAC")["abbr"] == "LAC")
check("LA Lakers/Los Angeles Lakers -> LAL, nicht LAC", sc.team_info("LA Lakers")["abbr"] == sc.team_info("Los Angeles Lakers")["abbr"] == "LAL")
check("Portland Trail Blazers -> POR, Teamname 'Trail Blazers'", sc.team_info("Portland Trail Blazers")["abbr"] == "POR" and sc.team_info("Portland Trail Blazers")["nick"] == "Trail Blazers")
check("alle 30 vollen Namen aus nba_api werden erkannt", all(sc.team_info(t["full_name"])["abbr"] == t["abbreviation"] for t in api.values()))
unk = sc.team_info("Seattle SuperSonics")
check("unbekanntes Team: Kuerzel aus Teamname, known = False", unk["abbr"] == "SUP" and unk["known"] is False and unk["city"] == "Seattle")
logos = sorted(p.stem for p in (ROOT / "data" / "logos").glob("*.svg"))
check("30 lokale Logos vorhanden", logos == sorted(api), f"{len(logos)}")

# ----------------------------------------------------------------- Zahlen wie bisher (Referenz = alte Formeln aus app.py)
def legacy(proj):
    nick = lambda t: t.split()[-1]
    def lab(s):
        if s is None: return None
        s = round(float(s), 1)
        return ("PK", 0.0) if s == 0 else (("home" if s > 0 else "away"), abs(s))
    total_diff = round(proj["exp_total"] - proj["market_total"], 1) if proj.get("market_total") else None
    warn = []
    if proj.get("lineup_warning"): warn.append("LINEUP RISK")
    if total_diff is not None and abs(total_diff) >= 8: warn.append("MARKET DISAGREEMENT")
    return {"away_score": proj["away_score"], "home_score": proj["home_score"], "away_pct": round(proj["away_win_prob"] * 100),
            "home_pct": round(proj["home_win_prob"] * 100), "model_spread": lab(proj["exp_spread"]), "market_spread": lab(proj.get("market_spread")),
            "model_total": float(proj["exp_total"]), "market_total": float(proj["market_total"]) if proj.get("market_total") else None, "warnings": warn}

def num(txt): return float(txt.replace("−", "-").replace(",", "."))
def parse(html, proj):
    hn, an = sc.team_info(proj["home_team"])["nick"], sc.team_info(proj["away_team"])["nick"]
    scores = [int(x) for x in re.findall(r'<span class="pc-score [^"]*">(\d+)</span>', html)]
    lab = re.search(r'<div class="pc-bar-labels"><span>(.*?) (\d+)\xa0%</span><span>(.*?) (\d+)\xa0%</span>', html)
    models = re.findall(r'pc-v-model">(.*?)</span>', html); markets = re.findall(r'pc-v-market">(.*?)</span>', html)
    def spr(t):
        if t == "PK": return ("PK", 0.0)
        if t == "—": return None
        m = re.fullmatch(r"(.*) −([\d,]+)", t)
        return (("home" if m.group(1) == hn else "away" if m.group(1) == an else "?"), num(m.group(2)))
    return {"away_score": scores[0], "home_score": scores[1], "away_pct": int(lab.group(2)), "home_pct": int(lab.group(4)),
            "model_spread": spr(models[0]), "market_spread": spr(markets[0]), "model_total": num(models[1]),
            "market_total": None if markets[1] == "—" else num(markets[1]),
            "warnings": re.findall(r'pc-chip pc-chip-yellow">⚠ ([A-Z ]+)</div>', html)}

base = dict(model_total=223.1, market_diff=8.9, market_weight=0.4, is_playoff=False, home_bias_adjustment=0.0, away_bias_adjustment=0.0, lineup_warning=False)
cases = [
    dict(base, home_team="New York Knicks", away_team="Philadelphia 76ers", home_score=119, away_score=108, home_win_prob=0.88, away_win_prob=0.12, exp_spread=10.4, market_spread=4.5, exp_total=227, market_total=232.0),
    dict(base, home_team="San Antonio Spurs", away_team="Oklahoma City Thunder", home_score=117, away_score=114, home_win_prob=0.67, away_win_prob=0.33, exp_spread=3.1, market_spread=-0.2, exp_total=231, market_total=230.7),
    dict(base, home_team="Detroit Pistons", away_team="Boston Celtics", home_score=113, away_score=111, home_win_prob=0.60, away_win_prob=0.40, exp_spread=1.9, market_spread=-1.5, exp_total=224, market_total=219.8),
    dict(base, home_team="LA Clippers", away_team="Portland Trail Blazers", home_score=120, away_score=101, home_win_prob=0.31, away_win_prob=0.69, exp_spread=-9.0, market_spread=1.0, exp_total=241, market_total=219.8, lineup_warning=True),
    dict(base, home_team="Nowhere Dragons", away_team="Boston Celtics", home_score=111, away_score=111, home_win_prob=0.5, away_win_prob=0.5, exp_spread=0.0, market_spread=None, exp_total=222, market_total=None),
]
all_same, all_flat = True, True
for p in cases:
    html = flat_html(sc.render_card_html(sc.build_card_vm(p)))
    all_same &= parse(html, p) == legacy(p)
    all_flat &= ("\n" not in html) and not re.search(r"<div[^>]*></div>(?!</)", html.replace('class="pc-seg', 'X')) or True
check("Zahlen auf der Karte == bisherige Anzeige (Scores, Prozent, Spread, Total, Warnungen) fuer 5 Faelle", all_same)
html_all = [flat_html(sc.render_card_html(sc.build_card_vm(p))) for p in cases]
check("HTML ohne Zeilenumbruch und ohne Leerzeile/Einrueckung (flat_html)", all("\n" not in h and "  " not in h for h in html_all))
check("keine leeren Platzhalter-Elemente (<div></div>, leere Chips)", not any(re.search(r'<div class="pc-(?:chip|info|city|name|side)[^"]*"></div>', h) for h in html_all))
check("kein 'Edge'/'Value' in den Karten", not any(re.search(r"edge|value", h, re.I) for h in html_all))
check("kein Gruen im Karten-HTML/CSS", not re.search(r"#(?:[0-9a-f]{2}){3}", sc.CARD_CSS + "".join(html_all)) or not any(greenish(c) for c in set(re.findall(r"#(?:[0-9a-f]{6})", (sc.CARD_CSS + "".join(html_all)).lower()))))
check("tabular-nums fuer Karte und Scores", sc.CARD_CSS.count("font-variant-numeric:tabular-nums") >= 3)
check("Score mind. 46 px, waechst mit der Breite (clamp)", "font-size:clamp(46px" in sc.CARD_CSS)
check("Karte nutzt volle Breite bis 1400 px", "width:100%; max-width:1400px" in sc.CARD_CSS)

# Favorit/Orange
def classes(p): return re.findall(r'<span class="pc-score (pc-fav|pc-dog)">', flat_html(sc.render_card_html(sc.build_card_vm(p))))
check("Favorit = hoehere Siegwahrscheinlichkeit: nur dessen Score orange", classes(cases[0]) == ["pc-dog", "pc-fav"] and classes(cases[3]) == ["pc-fav", "pc-dog"])
check("bei 50 : 50 kein Favorit (beide gedaempft)", classes(cases[4]) == ["pc-dog", "pc-dog"])
check("Leiste: Favoriten-Anteil orange, 76ers 12 % links / Knicks 88 % rechts", 'pc-seg pc-seg-other" style="width:12.0%"' in html_all[0] and 'pc-seg pc-seg-fav" style="width:88.0%"' in html_all[0] and "76ers 12\xa0%" in html_all[0] and "Knicks 88\xa0%" in html_all[0])

# Chips: grau/gelb mit Schwellen aus config
S, T = settings.SPREAD_DEVIATION_YELLOW, settings.TOTAL_DEVIATION_YELLOW
def vm_with(spread_dev, total_dev):
    p = dict(cases[0], exp_spread=round(4.5 + spread_dev, 1), market_spread=4.5, exp_total=232.0 + total_dev, market_total=232.0)
    return sc.build_card_vm(p)
check("Spread-Chip: knapp unter Schwelle grau, ab Schwelle gelb", not vm_with(S - 0.1, 0)["spread"]["yellow"] and vm_with(S, 0)["spread"]["yellow"] and vm_with(-S, 0)["spread"]["yellow"])
check("Total-Chip: knapp unter Schwelle grau, ab Schwelle gelb", not vm_with(0, T - 0.1)["total"]["yellow"] and vm_with(0, T)["total"]["yellow"] and vm_with(0, -T)["total"]["yellow"])
check("Schwellen stehen in config/settings.py (5,0 / 8,0)", (S, T) == (5.0, 8.0))
v = sc.build_card_vm(dict(cases[0], exp_spread=10.4, market_spread=4.4))
check("Beispiel: 'Knicks −10,4' gegen 'Knicks −4,4' -> 'Modell sieht Knicks um 6,0 stärker'", v["spread"]["model"] == "Knicks −10,4" and v["spread"]["market"] == "Knicks −4,4" and v["spread"]["dev_text"] == "Modell sieht Knicks um 6,0 stärker")
check("Total-Chip: Richtung ueber/unter", sc.build_card_vm(cases[0])["total"]["dev_text"] == "Modell 5,0 Punkte unter dem Markt" and sc.build_card_vm(cases[2])["total"]["dev_text"] == "Modell 4,2 Punkte über dem Markt")
check("ohne Marktwerte: grauer Chip 'ohne Marktlinie', Marktzeile '—'", sc.build_card_vm(cases[4])["spread"]["dev_text"] == "ohne Marktlinie" and not sc.build_card_vm(cases[4])["total"]["yellow"] and sc.build_card_vm(cases[4])["total"]["market"] == "—")
check("Warnungen LINEUP RISK / MARKET DISAGREEMENT als gelbe Chips (Logik wie bisher)", parse(html_all[3], cases[3])["warnings"] == ["LINEUP RISK", "MARKET DISAGREEMENT"] and parse(html_all[0], cases[0])["warnings"] == [])
check("MODEL DETAILS als aufklappbarer Bereich mit bisherigem Inhalt", all(s in html_all[0] for s in ("<details", "MODEL DETAILS", "raw model total: 223.1", "raw model vs market: 8.9", "market weight: 0.4", "final vs market diff: -5.0", "playoff modifier: OFF", "bias adj: H +0.0 / A +0.0")))
check("kein Eingabefeld auf der Karte", not re.search(r"<input|<select|<textarea", html_all[0]))

# ----------------------------------------------------------------- Logo / Fallback
check("Logo vorhanden: eingebettetes SVG als Bild, kein Kuerzel-Kreis", "data:image/svg+xml;base64," in html_all[0] and "pc-logo-fb" not in html_all[0])
with tempfile.TemporaryDirectory() as tmp:
    for f in ("PHI.svg",): pass
    only_nyk = Path(tmp); (only_nyk / "NYK.svg").write_bytes((ROOT / "data" / "logos" / "NYK.svg").read_bytes())
    h = flat_html(sc.render_card_html(sc.build_card_vm(cases[0]), logo_dir=only_nyk))
    check("fehlende Datei (PHI) -> Kuerzel PHI im Kreis, vorhandenes (NYK) bleibt Logo", ">PHI</div>" in h and h.count("pc-logo-fb") == 1 and h.count("data:image/svg+xml") == 1)
h = flat_html(sc.render_card_html(sc.build_card_vm(cases[4])))
check("absichtlich unbekanntes Team -> Kuerzel DRA im Kreis", ">DRA</div>" in h and "pc-logo-fb" in h)
with tempfile.TemporaryDirectory() as tmp:
    h = flat_html(sc.render_card_html(sc.build_card_vm(cases[0]), logo_dir=tmp))
    check("leerer Logo-Ordner -> beide Teams mit Kuerzel (PHI, NYK)", ">PHI</div>" in h and ">NYK</div>" in h and "data:image" not in h)
check("Logos werden nie live geladen (kein http im Karten-HTML)", not any("http" in h for h in html_all))

# ----------------------------------------------------------------- App-Lauf (Streamlit AppTest), beide Schalterwerte
from streamlit.testing.v1 import AppTest
for flag in (False, True):
    settings.SHOW_VALUE_BETS = flag
    fake_net.fresh_env()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    labels = [t.label for t in at.tabs]
    sp_idx = [i for i, l in enumerate(labels) if "Score Projections" in l][0]
    check(f"SHOW_VALUE_BETS={flag}: keine Exception, Tabs ({len(labels)}) wie zuvor", not at.exception and len(labels) == (9 if flag else 8) and labels[-1].endswith("Pre-Match Eingabe") and labels[-2].endswith("ELO Rankings"), str(labels))
    cards = [m.value for m in at.tabs[sp_idx].markdown if 'class="pc-card' in m.value]
    # Elementbaum: feste Reihenfolge nach Spiel-Schluessel (stabile Expander-Zustaende); sichtbar sortiert CSS (order) nach |Spread|
    projs_dom = sorted(at.session_state["projections"], key=lambda x: str((x.get("_line_inputs") or {}).get("entry_key") or x["home_team"]))
    projs = sorted(at.session_state["projections"], key=lambda x: -abs(x["exp_spread"]))
    _style = " ".join(m.value for m in at.tabs[sp_idx].markdown if "<style>div:has(> .st-key-sc_game_" in m.value)
    import hashlib as _hl
    _h = lambda p_: _hl.md5(str((p_.get("_line_inputs") or {}).get("entry_key") or p_["home_team"]).encode("utf-8")).hexdigest()[:10]
    _visual = [p_ for _, p_ in sorted(((int(re.search(r"has\(> \.st-key-sc_game_" + _h(p_) + r"\)\{order:(\d+)", _style).group(1)), p_) for p_ in projs_dom), key=lambda t: t[0])]
    check(f"SHOW_VALUE_BETS={flag}: sichtbare Reihenfolge (CSS order) = nach |Spread| sortiert", [p_["home_team"] for p_ in _visual] == [p_["home_team"] for p_ in projs])
    projs = projs_dom
    check(f"SHOW_VALUE_BETS={flag}: 3 Karten in unveraenderter Reihenfolge (nach |Spread|)", len(cards) == 3 and [parse(c, p)["home_score"] for c, p in zip(cards, projs)] == [p["home_score"] for p in projs], f"{len(cards)} Karten")
    check(f"SHOW_VALUE_BETS={flag}: Karten-Zahlen == bisherige Anzeige aus den Projektionen", all(parse(c, p) == legacy(p) for c, p in zip(cards, projs)))
    check(f"SHOW_VALUE_BETS={flag}: Karten ohne Zeilenumbruch/Leerzeile", all("\n" not in c for c in cards))
# ----------------------------------------------------------------- Hinweis "Siegchance und Spread aus derselben Verteilung" (sigmas_version 2, 23.10.2026)
from engine.projection import compute_projection
_p2 = compute_projection({"home_team": "New York Knicks", "away_team": "Philadelphia 76ers", "home_elo": 1560, "away_elo": 1500, "expected_total": 226.0, "home_win_prob": 0.62, "away_win_prob": 0.38}, game_date="2026-10-21")
_vm2 = sc.build_card_vm(_p2)
_h2 = flat_html(sc.render_card_html(_vm2))
check("neue Projektion (Siegchance aus der Spread-Verteilung): Hinweis mit Sigma 13,2 im Kartenmodell und im HTML (genau einmal, unter dem Siegbalken)",
      _vm2["win_note"] == "Siegchance und Spread aus derselben Verteilung (Sigma 13,2)" and _h2.count("Siegchance und Spread aus derselben Verteilung (Sigma 13,2)") == 1 and _h2.index("pc-bar-labels") < _h2.index("pc-winnote") < _h2.index("pc-model-wrap"))
check("Siegbalken der Karte = round(Siegchance) aus der Spread-Verteilung (nicht die Elo-Logistik 62 %)", _vm2["home"]["pct"] == round(_p2["home_win_prob"] * 100) != 62 and _vm2["home"]["pct"] + _vm2["away"]["pct"] == 100)
check("alte Projektion/Schnappschuss-Karte ohne win_prob_source: KEIN Hinweis (Siegchance stammte aus der Logistik)", sc.build_card_vm(cases[0])["win_note"] is None and "pc-winnote" not in flat_html(sc.render_card_html(sc.build_card_vm(cases[0]))))
check("Hinweis nennt das Sigma der Projektion (z. B. 10,5 bei einer Version-1-Projektion mit gesetzter Quelle)", sc.build_card_vm({**_p2, "sigma_spread": 10.5})["win_note"] == "Siegchance und Spread aus derselben Verteilung (Sigma 10,5)")

settings.SHOW_VALUE_BETS = False
check("Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
check("in KEINEM AppTest-Lauf dieser Datei: Streamlit-Exception oder der Satz 'was created with a default value ... Session State API'", not page_checks.bad, "; ".join(page_checks.bad[:2]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
