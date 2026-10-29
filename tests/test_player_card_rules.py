"""Tests: vier Anzeige-Regeln der Spielerkarten (DESIGN_REGELN.md Regel 94): (1) orange = Modell roh, kein dritter Balken, kein "vorher", kein Kasten "Ausfaelle wirken";
(2) kein Knopf "Prognose mit Ausfaellen neu rechnen", keine neue Ausfall-Variante; (3) Hinweis bei weniger als 10 Spielen; (4) gruenes Zeichen und Mindestquote nur fuer Starter mit
mindestens 10 Spielen ab 80 % Roh-Chance (Rechnung der Mindestquote). Ohne App, ohne Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_player_card_rules.py"""
import os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import config.settings as settings
from engine import player_forecast as pf
from engine import safety_levels as sl
from ui import player_view as pv

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def player(pid, name, base, games, raw, adjusted=None, odds=None):
    """Spieler im Snapshot-Format. raw/adjusted: {Meilenstein: Chance}; odds: {Meilenstein: Quote} (Standard 1,30). games: {Saison: Spiele} oder None (Angabe fehlt)."""
    adjusted = adjusted or raw
    odds = odds or {}
    p = {"person_id": pid, "name": name, "team": "Heim Falken", "team_abbreviation": "HEI", "ok": True, "reason": None, "quality": [], "warnings": [],
         "minutes": {"base": base, "mean": base, "role": pf.role_for_minutes(base)}, "minutes_adjusted": base, "expected_points_raw": 22.0, "expected_points_adjusted": 20.0,
         "p_ge_raw": {str(k): v for k, v in raw.items()}, "p_ge_adjusted": {str(k): v for k, v in adjusted.items()},
         "quotes": [{"milestone": n, "odds": odds.get(n, 1.30), "bookmaker": "Betano", "bookmaker_probability": 1 / odds.get(n, 1.30), "bookmaker_percent": round(100 / odds.get(n, 1.30))} for n in raw]}
    if games is not None:
        p["games_used"] = games
    return p

RAW = {20: 0.85, 24: 0.80, 25: 0.79, 30: 0.30}
ADJ = {20: 0.70, 24: 0.66, 25: 0.65, 30: 0.20}
ENTRY = {"game_key": "k", "players": [
    player(1, "Starter Zwoelf", 33.0, {"2025-26": 12}, RAW, ADJ),
    player(2, "Starter Zehn", 33.0, {"2025-26": 6, "2024-25": 4}, RAW, ADJ),                     # genau 10 Spiele (ueber zwei Saisons gezaehlt)
    player(3, "Starter Neun", 33.0, {"2025-26": 9}, RAW, ADJ),
    player(4, "Starter Ein Spiel", 33.0, {"2025-26": 1}, RAW, ADJ),
    player(5, "Rotation Zwanzig", 24.0, {"2025-26": 20}, RAW, ADJ),
    player(6, "Bank Zwanzig", 15.0, {"2025-26": 20}, RAW, ADJ),
    player(7, "Starter ohne Angabe", 33.0, None, RAW, ADJ),
    player(8, "Starter Grenze", 33.0, {"2025-26": 30}, {20: 0.7996, 24: 0.8004}, odds={20: 1.3, 24: 1.3}),
    player(9, "Starter Zahl", 29.0, {"2025-26": 40}, {20: 0.9, 24: 0.80}, odds={20: 1.2, 24: 1.3}),
]}
raw_model = pv.build_table_model(ENTRY, "raw", "team")                      # so baut der Tab die Karten (Regel 94)
H = pv.render_cards_html(raw_model)
cards = {c.split("pl-c-name'>")[1].split("<")[0].strip(): c for c in re.findall(r"<div class='pl-card'>.*?(?=<div class='pl-card'>|</div><div class='pl-c-legend'>)", H, flags=re.S)}
row = lambda name, n: next(x for x in cards[name].split("<div class='pl-c-row") if f"<b>{n}+" in x)
check("neun Karten", len(cards) == 9)

# ---------------------------------------------------------------- 1) orange = roh, kein dritter Balken, kein "vorher", kein Kasten
r20 = row("Starter Zwoelf", 20)
check("orange Balken und Text = Modell roh (85 %), nicht Teamabgleich (70 %)", "Modell</span> <b>85 %</b>" in r20 and "pl-c-bar pl-c-bar-m'><i style='width:85%'>" in r20 and "70 %" not in r20 and "data-model='85'" in r20, r20[:420])
check("Differenz = Roh minus Betano (85 % - 76,9 % = +8,1 PP), aus ungerundeten Werten", f">{pv.fmt_num((0.85 - 1 / 1.3) * 100, 1, signed=True)}<" in r20 and pv.fmt_num((0.85 - 1 / 1.3) * 100, 1, signed=True) == "+8,1", r20[-200:])
check("kein dritter Balken (Roh/Teamabgleich), kein 'vorher', kein Kasten 'Ausfaelle wirken', kein gelber Kartenrand", not any(w in H for w in ("pl-c-bar-o", "pl-c-wo", "vorher", "Ausfälle wirken", "pl-card-aff", "nicht betroffen", "Teamabgleich")))
css = pv.CARDS_CSS
check("Stylesheet ohne die entfallenen Teile", not any(w in css for w in ("pl-c-bar-o", "pl-c-wo", "pl-c-old", "pl-c-aff", "pl-card-aff")))
check("Betano (blau) und Abstand rechts bleiben", "pl-c-bar pl-c-bar-b" in r20 and "pl-c-d" in r20 and pv.BLUE == "#6f8fd6" and pv.ORANGE == "#ff7a2f")
check("Funktionen fuer Varianten und Vergleich sind weg", not any(hasattr(pv, n) for n in ("attach_variant", "affected", "build_compare_model", "render_compare_html", "OTHER")))
tab_src = (ROOT / "ui" / "player_tab.py").read_text(encoding="utf-8")
check("Tab: Karten werden mit Modus roh gebaut, Umschalter nur in der Tabellenansicht, keine Variante", 'mode = "raw"' in tab_src and "attach_variant" not in tab_src and "latest_variant" not in tab_src and "if table_view:\n                mode = st.radio" in tab_src)

# ---------------------------------------------------------------- 2) kein Knopf, keine neue Ausfall-Variante
abs_src = (ROOT / "ui" / "player_absence.py").read_text(encoding="utf-8")
check("kein Knopf 'Prognose mit Ausfaellen neu rechnen', kein Aufruf von create_variant in ui/", "neu rechnen" not in abs_src and "recompute" not in abs_src and "primary" not in abs_src
      and not any("create_variant" in p.read_text(encoding="utf-8") for p in (ROOT / "ui").glob("*.py")))
check("Kasten fuer Ausfaelle bleibt: Auswahl Fehlt/Fraglich, Speichern, ESPN-Hinweise", all(w in abs_src for w in ('"Fehlt"', '"Fraglich"', '"Auswahl speichern"', "auto_caption_lines", "save_absences")) and callable(pv.absence_box_html))

# ---------------------------------------------------------------- 3) Hinweis bei weniger als 10 Spielen
few = lambda name: "pl-c-few" in cards[name]
check("9 Spiele: Hinweis 'nur 9 Spiele, Chance vermutlich zu hoch' neben dem Namen, Prozentzahlen bleiben sichtbar", few("Starter Neun") and "nur 9 Spiele, Chance vermutlich zu hoch" in cards["Starter Neun"]
      and "Modell</span> <b>85 %</b>" in cards["Starter Neun"] and cards["Starter Neun"].index("pl-c-name") < cards["Starter Neun"].index("pl-c-few") < cards["Starter Neun"].index("pl-c-team"))
check("10 Spiele (aus zwei Saisons) und mehr: kein Hinweis", not few("Starter Zehn") and not few("Starter Zwoelf") and not few("Rotation Zwanzig"))
check("1 Spiel: 'nur 1 Spiel' (Einzahl)", "nur 1 Spiel, Chance vermutlich zu hoch" in cards["Starter Ein Spiel"])
check("Angabe der Spielzahl fehlt: kein Hinweis (nichts geraten)", not few("Starter ohne Angabe"))
check("Hinweis gilt fuer alle Rollen, nicht nur Starter (Bank mit 5 Spielen)", "nur 5 Spiele" in pv.render_cards_html(pv.build_table_model({"players": [player(10, "Bank Fuenf", 15.0, {"2025-26": 5}, {10: 0.5})]}, "raw", "team")))
check("Funktion few_games_text: 9 -> Text, 10 -> None, None -> None", sl.few_games_text(9) == "nur 9 Spiele, Chance vermutlich zu hoch" and sl.few_games_text(10) is None and sl.few_games_text(None) is None)
check("gleiche Spielzahl wie analysis/backtest_thresholds.py (nh >= 10 / nh < 10) und Konstante in config/settings.py", settings.PLAYER_MIN_GAMES == 10 and "(nh >= 10)" in (ROOT / "analysis" / "backtest_thresholds.py").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- 4) gruenes Zeichen + Mindestquote nur fuer Starter mit >= 10 Spielen ab 80 %
tick = lambda name, n: "pl-c-ok" in row(name, n)
check("Starter mit 12 Spielen: 20+ (85 %) und 24+ (80 %) mit Zeichen '20+ ✓', 25+ (79 %) und 30+ (30 %) ohne", tick("Starter Zwoelf", 20) and tick("Starter Zwoelf", 24) and not tick("Starter Zwoelf", 25) and not tick("Starter Zwoelf", 30)
      and "<b>20+ <span class='pl-c-ok'" in r20 and "✓</span></b>" in r20)
check("Mindestquote als kleiner grauer Text unter der Quote: 20+ -> 'Mindestquote 1,22' (1 / (0,85 - 0,03)), 24+ -> 'Mindestquote 1,30'", "<span class='pl-c-odds'>@ 1,30</span><span class='pl-c-minodds'>Mindestquote 1,22</span>" in r20
      and "Mindestquote 1,30" in row("Starter Zwoelf", 24))
check("Zeilen ohne Zeichen zeigen keine Mindestquote", "Mindestquote" not in row("Starter Zwoelf", 25) and "Mindestquote" not in row("Starter Zwoelf", 30) and "pl-c-minodds'" not in row("Starter Zwoelf", 25))
check("genau 10 Spiele: Zeichen", tick("Starter Zehn", 20))
check("9 Spiele: kein Zeichen, keine Mindestquote (auch bei 85 %)", not any(tick("Starter Neun", n) for n in (20, 24, 25, 30)) and "Mindestquote 1" not in cards["Starter Neun"])
check("Rotation und Bank mit 20 Spielen: kein Zeichen (nur Starter)", not any(tick(n, k) for n in ("Rotation Zwanzig", "Bank Zwanzig") for k in (20, 24)))
check("Spielzahl unbekannt: kein Zeichen", not tick("Starter ohne Angabe", 20))
check("Grenze 80 % gilt fuer die UNGERUNDETE Roh-Chance: 79,96 % (angezeigt 80 %) ohne, 80,04 % mit Zeichen", "Modell</span> <b>80 %</b>" in row("Starter Grenze", 20) and not tick("Starter Grenze", 20) and tick("Starter Grenze", 24))
check("Starter wie in der Auswertung: Basis-Minuten ueber 28 (29,0 ja, 28,0 und 24,0 nein)", pf.ROLE_STARTER_MIN == 28.0 and "mu0 > 28" in (ROOT / "analysis" / "backtest_thresholds.py").read_text(encoding="utf-8")
      and tick("Starter Zahl", 24) and sl.is_player_starter(28.1) and not sl.is_player_starter(28.0) and not sl.is_player_starter(24.0) and not sl.is_player_starter(None))
check("Rechnung Mindestquote: 90 % -> 1,15 (1/0,87), 80 % -> 1,30, 85 % -> 1,22, 81,6 % -> 1,27", [sl.odds_text(sl.min_odds(p)) for p in (0.90, 0.80, 0.85, 0.816)] == ["1,15", "1,30", "1,22", "1,27"]
      and "Mindestquote 1,15" in row("Starter Zahl", 20) and "Mindestquote 1,30" in row("Starter Zahl", 24))
check("Abschlag aus config/settings.py (SAFETY_DISCOUNT), nicht fest verdrahtet", settings.SAFETY_DISCOUNT == 0.03 and "0.03" not in (ROOT / "engine" / "safety_levels.py").read_text(encoding="utf-8").replace("SAFETY_DISCOUNT = 0.03", ""))
check("player_safe_odds: Starter/Spiele/Chance einzeln", sl.player_safe_odds(True, 10, 0.80) == 1.30 and sl.player_safe_odds(True, 9, 0.9) is None and sl.player_safe_odds(False, 40, 0.9) is None
      and sl.player_safe_odds(True, 40, 0.7999) is None and sl.player_safe_odds(True, None, 0.9) is None and sl.player_safe_odds(True, 40, None) is None)
check("Konstanten in config/settings.py: Mindest-Chance 0,80, Mindestspiele 10", settings.PLAYER_SAFE_MIN_PROB == 0.80 and settings.PLAYER_MIN_GAMES == 10)
check("Legende erklaert das Zeichen", "✓ = Starter mit mindestens 10 Spielen und Modell roh ab 80 %" in H)
# Farben: Gruen nur fuer das Zeichen (Karten-CSS), Kontrast >= 4,5 : 1; Tabellen-CSS ohne Gruen
def lum(hexc):
    c = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)
P = pv.PALETTE
check("Zeichen gruen (win_ok_text) auf dem Kartenhintergrund, Kontrast >= 4,5 : 1", f".pl-c-ok {{ font-size:15px; font-weight:700; color:{P['win_ok_text']}" in css.replace("{{", "{").replace("}}", "}") or P["win_ok_text"] in css, contrast(P["win_ok_text"], "#1d2338"))
check("Kontrast Zeichen und Hinweis (gelb auf gelb) >= 4,5 : 1", contrast(P["win_ok_text"], "#1d2338") >= 4.5 and contrast(P["chip_yellow_text"], P["chip_yellow_bg"]) >= 4.5, f"{contrast(P['win_ok_text'], '#1d2338'):.1f} / {contrast(P['chip_yellow_text'], P['chip_yellow_bg']):.1f}")
check("Hinweis gelb (chip_yellow), Mindestquote grau (label), Tabellen-CSS ohne Gruen", all(c in css for c in (P["chip_yellow_bg"], P["chip_yellow_text"])) and "color:" + P["label"] in css and P["win_ok_text"] not in pv.PLAYER_CSS)
# Regeln in DESIGN_REGELN.md
rules = (ROOT / "DESIGN_REGELN.md").read_text(encoding="utf-8")
check("DESIGN_REGELN.md: Regel 89 nennt das Spieler-Zeichen, neue Regel 94 fuer die Spielerkarten", re.search(r"^89\..*Spieler-Zeichen", rules, flags=re.M) is not None and re.search(r"^94\. \*\*Spielerkarten", rules, flags=re.M) is not None)
# Tabellenansicht bleibt wie sie war
tab = pv.render_table_html(pv.build_table_model(ENTRY, "team", "team"))
check("Tabellenansicht unveraendert: kein Hinweis, kein Zeichen, keine Mindestquote", not any(w in tab for w in ("pl-c-few", "pl-c-ok", "Mindestquote", "vermutlich zu hoch")))
check("Zahlen unveraendert: Modell/Minuten/Punkte der Tabelle im Modus Teamabgleich weiter aus den angepassten Werten", pv.build_table_model(ENTRY, "team", "team")["players"][0]["rows"][0]["model_pct"] == 70)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
