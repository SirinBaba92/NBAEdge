"""Test: erzielte Punkte und Spielminuten auf den Spielerkarten BEENDETER Spiele (ui/player_view.attach_final, ui/player_tab.final_table_data). Ohne App, ohne Netz.
Aufruf aus dem Projektordner: venv/bin/python tests/test_player_card_final.py"""
import os, sys
from pathlib import Path
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from ui import player_tab as pt
from ui import player_view as pv

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def snap_player(pid, name):
    return {"person_id": pid, "name": name, "team": "Heim Falken", "team_abbreviation": "HEI", "ok": True, "reason": None, "quality": [], "warnings": [], "minutes": {"base": 30.0, "mean": 30.0, "role": "Stamm"},
            "minutes_adjusted": 30.0, "expected_points_raw": 21.3, "expected_points_adjusted": 20.0, "p_ge_raw": {"20": 0.6}, "p_ge_adjusted": {"20": 0.5}, "games_used": {"2025-26": 20},
            "quotes": [{"milestone": 20, "odds": 1.8, "bookmaker": "Betano", "bookmaker_probability": 1 / 1.8, "bookmaker_percent": 56}]}
ENTRY = {"players": [snap_player(1, "Spielt Sven"), snap_player(2, "Fehlt Fritz"), snap_player(3, "Inaktiv Ida"), snap_player(4, "Null Nils")]}
pl = lambda pid, pts, mins, played, reason="": NS(person_id=pid, points=pts, minutes=mins, played=played, reason=reason)
game = lambda final=True, complete=True, players=None: NS(clock=NS(is_final=final), players=players if players is not None else (pl(1, 18, 31.2, True), pl(3, 0, 0.0, False, "Knee Soreness"), pl(4, 0, 0.0, False)), players_complete=complete)

fin = pt.final_table_data(game(), ENTRY)
check("beendetes Spiel: Punkte und Minuten aus dem Boxscore, nicht gespielt mit Grund, fehlender Spieler = nicht gespielt", fin[1] == {"points": 18, "minutes": 31.2, "played": True, "reason": ""} and fin[3] == {"points": 0, "minutes": 0.0, "played": False, "reason": "Knee Soreness"}
      and fin[2]["played"] is False and fin[4]["played"] is False)
check("nicht beendet, Boxscore nicht komplett (Punkte passen nicht zum Endstand), kein Spiel oder keine Spielerliste: nichts", pt.final_table_data(game(final=False), ENTRY) == {} and pt.final_table_data(game(complete=False), ENTRY) == {}
      and pt.final_table_data(None, ENTRY) == {} and pt.final_table_data(game(players=()), ENTRY) == {})
model = pv.attach_final(pv.build_table_model(ENTRY, "raw", "team"), fin)
H = pv.render_cards_html(model)
cards = {c.split("pl-c-name'>")[1].split("<")[0].strip(): c for c in __import__("re").findall(r"<div class='pl-card'>.*?(?=<div class='pl-card'>|</div><div class='pl-c-legend'>)", H, flags=__import__("re").S)}
check("Karte: 'Erzielt 18 Pkt · 31,2 Min' hinter 'Punkte erwartet · Min'", "<b>21,3</b> Punkte erwartet · <b>30,0</b> Min · <span class='pl-c-final'>Erzielt <b>18</b> Pkt · <b>31,2</b> Min</span>" in cards["Spielt Sven"], cards["Spielt Sven"][:400])
check("nicht gespielt: 'Nicht gespielt (Knee Soreness)' bzw. ohne Grund", "Nicht gespielt (Knee Soreness)" in cards["Inaktiv Ida"] and "Nicht gespielt</span>" in cards["Fehlt Fritz"] and "Nicht gespielt</span>" in cards["Null Nils"])
check("Prognose und Prozentzahlen bleiben unveraendert (Modell roh 60 %)", "Modell</span> <b>60 %</b>" in cards["Spielt Sven"])
m2 = pv.attach_final(pv.build_table_model(ENTRY, "raw", "team"), {})
H2 = pv.render_cards_html(m2)
check("ohne beendetes Spiel: keine Zusatzanzeige", "pl-c-final'>" not in H2 and "Erzielt" not in H2)
check("Stil grau (chip_gray), kein Gruen/Rot", ".pl-c-final {" in pv.CARDS_CSS.replace("{{", "{") and pv.PALETTE["chip_gray_bg"] in pv.CARDS_CSS)

# Ergebnis-Zeichen in hervorgehobenen Zeilen (Modell ab 60 %)
def two_rows(model_by_n):
    p = snap_player(1, "Spielt Sven"); p["p_ge_raw"] = {str(n): v for n, v in model_by_n.items()}
    p["quotes"] = [{"milestone": n, "odds": 1.8, "bookmaker": "Betano", "bookmaker_probability": 1 / 1.8, "bookmaker_percent": 56} for n in model_by_n]
    return {"players": [p]}
E2 = two_rows({15: 0.80, 18: 0.65, 20: 0.60, 25: 0.30})
def html_for(points, played=True):
    m = pv.attach_final(pv.build_table_model(E2, "raw", "team"), {1: {"points": points, "minutes": 30.0, "played": played, "reason": ""}})
    return pv.render_cards_html(m)
rowh = lambda h, n: next(x for x in h.split("<div class='pl-c-row") if f"<b>{n}+" in x)
h18 = html_for(18)
check("18 Punkte: hervorgehoben 15+ und 18+ gruenes Haekchen, 20+ (60 %, hervorgehoben) rotes X", "pl-c-res-ok'" in rowh(h18, 15) and "✓" in rowh(h18, 15) and "pl-c-res-ok'" in rowh(h18, 18) and "pl-c-res-no'" in rowh(h18, 20) and "✗" in rowh(h18, 20))
check("nicht hervorgehobene Zeile (25+, 30 %): kein Zeichen, auch nicht bei verfehlt", "pl-c-res" not in rowh(h18, 25) and "pl-c-hi" not in rowh(h18, 25))
check("genau erreicht (20 Punkte bei 20+): Haekchen", "pl-c-res-ok'" in rowh(html_for(20), 20))
check("nicht gespielt: keine Zeichen; ohne beendetes Spiel: keine Zeichen", "pl-c-res" not in html_for(0, played=False).replace(".pl-c-res", "") and "class='pl-c-res" not in pv.render_cards_html(pv.attach_final(pv.build_table_model(E2, "raw", "team"), {})))
check("Farben: gruen/rot aus dem Statusstil der Karten, Zeichen mit Hinweistext (title)", "pl-c-res-ok" in pv.CARDS_CSS and "pl-c-res-no" in pv.CARDS_CSS and "title='20+ verfehlt: 18 Punkte'" in rowh(h18, 20))

# ---- aeltere Spieltage: Aufzeichnung des Recorders (nur lesen) statt Live-Feed
import gzip, json, tempfile
with tempfile.TemporaryDirectory() as td:
    root = Path(td); os.environ["NBAEDGE_LIVE_DIR"] = str(root)
    KEY = "2026-10-27|2026-10-27T23:30:00Z|Heim Falken|Gast Baeren"
    gdir = root / "2026-10-27" / "0022600128"; gdir.mkdir(parents=True)
    (gdir / "context.json").write_text(json.dumps({"game_key": KEY, "game_id": "0022600128"}))
    def box(status):
        pj = lambda pid, pts, mins, played: {"personId": pid, "name": f"P{pid}", "played": played, "oncourt": "0", "status": "ACTIVE", "statistics": {"points": pts, "minutes": mins, "foulsPersonal": 1}}
        return {"game": {"gameId": "0022600128", "gameStatus": status, "homeTeam": {"teamTricode": "HEI", "players": [pj(1, 18, "PT31M12.00S", "1"), pj(3, 0, "PT00M00.00S", "0")]}, "awayTeam": {"teamTricode": "GAS", "players": []}}}
    (gdir / "final_box.json.gz").write_bytes(gzip.compress(json.dumps(box(3)).encode())); (gdir / "result.json").write_text("{}")
    rf = pt.recorder_final_data(KEY, ENTRY)
    check("Aufzeichnung (Recorder-Ordner, final_box): Punkte 18 und 31,2 Minuten, Spieler 3 ohne Einsatz = nicht gespielt, Spieler ohne Eintrag = nicht gespielt", rf[1]["points"] == 18 and abs(rf[1]["minutes"] - 31.2) < 1e-9 and rf[1]["played"] and rf[3]["played"] is False and rf[2]["played"] is False, str(rf))
    check("final_for_game: Spiel nicht im Live-Feed (None) -> Aufzeichnung; Live-Feed hat Vorrang", pt.final_for_game(None, ENTRY, KEY)[1]["points"] == 18 and pt.final_for_game(game(), ENTRY, KEY)[1]["minutes"] == 31.2)
    check("kein Recorder-Ordner fuer das Spiel: nichts", pt.recorder_final_data("2026-10-27|x|Andere|Spiel", ENTRY) == {} and pt.recorder_final_data("2026-10-20|x|A|B", ENTRY) == {})
    (gdir / "final_box.json.gz").write_bytes(gzip.compress(json.dumps(box(2)).encode()))                   # Recorder: Boxscore zeigt beim Abruf oft noch Status 2 ("Ende"), result.json fehlt noch nicht
    check("Status 2 im Boxscore zaehlt nicht, solange result.json (Aufzeichnung abgeschlossen) da ist", pt.recorder_final_data(KEY, ENTRY)[1]["points"] == 18)
    (gdir / "result.json").rename(gdir / "result.json.weg")
    check("ohne result.json (Aufzeichnung noch nicht abgeschlossen): nichts", pt.recorder_final_data(KEY, ENTRY) == {})
    (gdir / "result.json.weg").rename(gdir / "result.json")
    (gdir / "final_box.json.gz").write_bytes(b"kaputt")
    check("unlesbare final_box: nichts, keine Ausnahme", pt.recorder_final_data(KEY, ENTRY) == {})
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
