"""Test der Speicher-Aktion der Karten-Komponente (ui/bet_slip.process_action, ui/bet_cards_component): nonce nur einmal, Duplikate, gesperrte Meilensteine, ein Spieler = eine Wette, Teilfehler,
fremdes Spiel, Komponenten-Datei. Nur Temp-Ordner, kein Netz, echte Dateien bleiben unveraendert. Aufruf aus dem Projektordner: venv/bin/python tests/test_bet_cards_action.py"""
import hashlib, json, os, re, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ["NBAEDGE_TRACKING_DIR"] = str(T / "tracking")
from data import day_bets_store as ds
from ui import bet_slip as bs
from ui import player_bet_entry as pe
from ui import player_view as pv

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in (ROOT / "data" / "tracking").glob("*") if p.is_file()}
real_before = real_files()

KEY = "2099-01-01|2099-01-02T01:00:00Z|Heim Falken|Gast Baeren"
opt = lambda n, odds, bp: {"milestone": n, "odds": odds, "bookmaker": "Betano", "bookmaker_percent": bp, "bookmaker_probability": bp / 100, "updated_at": "2026-10-26T10:00:00+01:00", "model_raw": None, "model_team": None}
pl = lambda pid, name, opts, cur=None: {"person_id": pid, "name": name, "team": "Heim Falken", "team_abbreviation": "HEI", "options": opts, "current_bet": cur, "forecast_ok": True, "warnings": []}
options = {"players": [pl(1, "Anna Alpha", [opt(15, 1.30, 75), opt(20, 1.85, 54)]), pl(2, "Berta Beta", [opt(10, 1.50, 64), opt(15, 2.20, 44)]),
                       pl(3, "Carla Gamma", [opt(20, 2.00, 49), opt(25, 3.50, 27)]), pl(4, "Dora Delta", [opt(10, 1.40, 70), opt(15, 2.40, 40)], cur={"active": True, "milestone": 10})], "snapshot": True}
it = lambda pid, n, q, stake=10: {"player": pid, "name": f"P{pid}", "milestone": n, "quote": q, "stake": stake}
act = lambda nonce, items, key=KEY: {"action": "save", "nonce": nonce, "game_key": key, "items": items}

done = set()
a = act("n1", [it(1, 20, 1.85), it(2, 10, 1.5, "12,5"), it(3, 25, 3.5)])
r = bs.process_action(KEY, a, options, done)
saved = ds.get_player_bets_by_key(KEY)
check("Aktion speichert 3 Wetten (Quote vom Klick, Einsatz inkl. Komma '12,5')", r["count"] == 3 and r["saved"] == [1, 2, 3] and not r["failed"] and saved[2]["stake"] == 12.5 and saved[1]["odds"] == 1.85 and saved[3]["milestone"] == 25, r)
check("nonce wird NIE ein zweites Mal ausgefuehrt (Streamlit liefert den Wert bei jedem Rerun erneut)", bs.process_action(KEY, a, options, done) is None and len(ds.get_player_bets_by_key(KEY)) == 3 and "n1" in done)
rev = {p: len(b.get("revisions", [])) for p, b in ds.get_player_bets_by_key(KEY).items()}
for _ in range(3):
    bs.process_action(KEY, a, options, done)
check("auch nach mehreren Reruns keine neue Revision in der Wettliste", {p: len(b.get("revisions", [])) for p, b in ds.get_player_bets_by_key(KEY).items()} == rev)
# neue Aktion: Teilfehler
KEY2 = "2099-01-01|2099-01-02T03:00:00Z|Heim Falken|Gast Baeren"
bad = act("n2", [it(1, 15, 1.30), it(1, 20, 1.85), it(2, 99, 1.0), it(4, 15, 2.4), it(3, 20, 2.0, 0), it(5, 10, 1.5)], KEY2)
r2 = bs.process_action(KEY2, bad, options, set())
reasons = {(f["player"], f["milestone"]): f["reason"] for f in r2["failed"]}
check("Teilfehler: gueltige Zeile gespeichert (Anna 15+), alle ungueltigen mit Grund gemeldet", r2["saved"] == [1] and set(ds.get_player_bets_by_key(KEY2)) == {1} and len(r2["failed"]) == 5, reasons)
check("ein Spieler = eine Wette (zweiter Eintrag von Anna abgelehnt)", "nur eine Wette" in reasons[(1, 20)])
check("Meilenstein nicht in der Betano-Liste / unbekannter Spieler abgelehnt", "nicht in der eingelesenen Betano-Liste" in reasons[(2, 99)] and (5, 10) in reasons)
check("gespeicherte Wette des Spielers sperrt (Dora hat schon 10+)", "schon eine gespeicherte Wette auf 10+" in reasons[(4, 15)])
check("Einsatz 0 abgelehnt", "Einsatz" in reasons[(3, 20)])
check("gesperrte Meilensteine fuer die Komponente: {'4': 10}", bs.locked_for_component(options) == {"4": 10})
# fremdes Spiel / ungueltige Aktionen
done3 = set()
check("Aktion eines anderen Spiels: nichts gespeichert, nonce verbraucht", bs.process_action(KEY2, act("n3", [it(2, 10, 1.5)], KEY), options, done3) is None and set(ds.get_player_bets_by_key(KEY2)) == {1} and "n3" in done3)
check("ungueltige Aktionen (None, anderer Typ, ohne nonce) werden ignoriert", all(bs.process_action(KEY, x, options, set()) is None for x in (None, "x", {"action": "x", "nonce": "a"}, {"action": "save", "items": []}, {"action": "save", "nonce": ""})))
# begonnenes Spiel
PAST = "2020-01-01|2020-01-02T01:00:00Z|Heim Falken|Gast Baeren"
r4 = bs.process_action(PAST, act("n4", [it(1, 20, 1.85)], PAST), options, set())
check("begonnenes Spiel: nichts gespeichert, Zeile mit Sperr-Grund gemeldet", r4["count"] == 0 and not ds.get_player_bets_by_key(PAST) and "gesperrt" in r4["failed"][0]["reason"], r4["failed"])
# Zeilen-Daten in den Karten
sample = {"game_key": "k", "players": [{"person_id": 7, "name": "O'Neil \"Z\"", "team": "T", "team_abbreviation": "HEI", "ok": True, "reason": None, "quality": [], "warnings": [], "minutes": {"base": 30.0, "mean": 30.0, "role": "Stamm"}, "minutes_adjusted": 30.0,
          "expected_points_raw": 20.0, "expected_points_adjusted": 20.0, "p_ge_raw": {"20": 0.7}, "p_ge_adjusted": {"20": 0.7},
          "quotes": [{"milestone": 20, "odds": 1.85, "bookmaker": "Betano", "bookmaker_probability": 0.54, "bookmaker_percent": 54}]}]}
H = pv.render_cards_html(pv.build_table_model(sample, "team", "team"))
check("Karten-Zeilen tragen data-Attribute (ID, Name maskiert, Meilenstein, Quote, Betano-%, Modell-%)", "data-pid='7'" in H and "data-name='O&#x27;Neil &quot;Z&quot;'" in H and "data-n='20'" in H and "data-odds='1.85'" in H and "data-buch='54'" in H and "data-model='70'" in H, re.search(r"<div class='pl-c-row[^>]*>", H).group(0))
# Komponente: Datei vorhanden, ohne Netz/externe Skripte, Protokoll-Nachrichten
html = (ROOT / "ui" / "components" / "bet_cards" / "index.html").read_text(encoding="utf-8")
check("Komponente: Protokoll (componentReady, render, setFrameHeight, setComponentValue), sessionStorage mit try/catch", all(x in html for x in ("streamlit:componentReady", "streamlit:render", "streamlit:setFrameHeight", "streamlit:setComponentValue", "sessionStorage")) and "try {" in html)
check("Komponente: keine externen Skripte, kein fetch/XMLHttpRequest/WebSocket/http-Adressen", not re.search(r"<script[^>]+src=|fetch\(|XMLHttpRequest|WebSocket|https?://", html))
check("Komponente: Wettschein steht im Dokument VOR den Karten, keine feste Hoehe (kein innerHeight, kein overflow-y:auto/scroll), Hoehe per ResizeObserver aus dem Inhalt",
      html.index('id="bar"') < html.index('id="cards"') and "innerHeight" not in html and not re.search(r"overflow-y\s*:\s*(auto|scroll)", html) and "ResizeObserver" in html and "getBoundingClientRect().height" in html and "position:fixed" not in html.replace(" ", ""))
from ui import bet_cards_component as bc
check("Wrapper: declare_component mit Pfad auf den Komponenten-Ordner", bc._PATH.is_dir() and (bc._PATH / "index.html").exists())
check("echte Wettliste und Tracking-Dateien unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
