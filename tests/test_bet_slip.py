"""Tests fuer den Wettschein im Tab Prognose (ui/bet_slip.py): Schein aufbauen, Summen, Duplikate, gesperrte Meilensteine, Speichern ueber die bestehende Funktion, Fehlerfaelle.
Nur Temp-Ordner (NBAEDGE_TRACKING_DIR), kein Netz, echte Dateien werden nicht veraendert. Aufruf aus dem Projektordner: venv/bin/python tests/test_bet_slip.py"""
import hashlib, os, sys, tempfile, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ["NBAEDGE_TRACKING_DIR"] = str(T / "tracking")
from config import settings
from data import day_bets_store as ds
from ui import bet_slip as bs
from ui import player_bet_entry as pe

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*"))
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()

KEY = "2099-01-01|2099-01-02T01:00:00Z|Heim Falken|Gast Baeren"
PAST = "2020-01-01|2020-01-02T01:00:00Z|Heim Falken|Gast Baeren"
opt = lambda n, odds, bp, mt=None, mr=None: {"milestone": n, "odds": odds, "bookmaker": "Betano", "bookmaker_percent": bp, "bookmaker_probability": bp / 100, "updated_at": "2026-10-26T10:00:00+01:00", "model_raw": mr, "model_team": mt}
pl = lambda pid, name, opts, cur=None: {"person_id": pid, "name": name, "team": "Heim Falken", "team_abbreviation": "HEI", "options": opts, "current_bet": cur, "forecast_ok": True, "warnings": []}
A = pl(1, "Anna Alpha", [opt(15, 1.30, 75, 0.78, 0.70), opt(20, 1.85, 54, 0.72, 0.60), opt(25, 3.0, 32, 0.30, 0.28)])
B = pl(2, "Berta Beta", [opt(10, 1.50, 64, 0.66), opt(15, 2.20, 44, 0.40)])
C = pl(3, "Carla Gamma", [opt(20, 2.00, 49, None), opt(25, 3.50, 27, None)])
D = pl(4, "Dora Delta", [opt(10, 1.40, 70, 0.75), opt(15, 2.40, 40, 0.42)], cur={"active": True, "milestone": 10, "odds": 1.4, "stake": 5.0})
options = {"players": [A, B, C, D], "snapshot": True}

# --- Anzeige-Text
_prev = settings.SHOW_TEAM_ADJUSTED
settings.SHOW_TEAM_ADJUSTED = False                     # Standard in config/settings.py; hier explizit gesetzt (unabhaengig vom Standardwert), am Ende zurueck
try:
    check("Meilenstein-Text (Schalter False, Standard): Teamabgleich ausgeblendet, '20+ · Quote 1,85 · Betano 54 % · Modell 60 %' (roh), auch im Modus team; ohne Snapshot ohne Modell",
          bs.option_label(A["options"][1]) == "20+ · Quote 1,85 · Betano 54 % · Modell 60 %" and bs.option_label(A["options"][1], "raw").endswith("Modell 60 %") and "Modell" not in bs.option_label(C["options"][0]))
    settings.SHOW_TEAM_ADJUSTED = True
    check("Meilenstein-Text (Schalter True): '20+ · Quote 1,85 · Betano 54 % · Modell 72 %' (Teamabgleich), roh = 60 %, ohne Snapshot ohne Modell", bs.option_label(A["options"][1]) == "20+ · Quote 1,85 · Betano 54 % · Modell 72 %"
          and bs.option_label(A["options"][1], "raw").endswith("Modell 60 %") and "Modell" not in bs.option_label(C["options"][0]))
finally:
    settings.SHOW_TEAM_ADJUSTED = _prev
check("Schalter nach der Pruefung wieder auf dem Wert von vorher", settings.SHOW_TEAM_ADJUSTED is _prev)
# --- Schein bauen
slip, msgs = [], []
for p, n in ((A, 20), (B, 10), (C, 25)):
    slip, m = bs.add_lines(slip, p, [n], 10.0); msgs += m
check("Schein mit 3 Wetten (Spieler, Meilenstein, Quote vom Hinzufuegen, Standard-Einsatz 10)", [(l["person_id"], l["milestone"], l["odds"], l["stake"]) for l in slip] == [(1, 20, 1.85, 10.0), (2, 10, 1.5, 10.0), (3, 25, 3.5, 10.0)] and not msgs)
t = bs.totals(slip)
check("Summen: Gesamteinsatz 30,00, Ø Quote (1,85+1,50+3,50)/3 = 2,28", t == {"n": 3, "stake": 30.0, "avg_odds": 2.28}, t)
check("leerer Schein: 0 Wetten, keine Ø Quote", bs.totals([]) == {"n": 0, "stake": 0.0, "avg_odds": None})
slip2 = [dict(l) for l in slip]; slip2[0]["stake"] = 12.5
check("Einsatz aenderbar: Summe folgt", bs.totals(slip2)["stake"] == 32.5)
# --- Duplikate / gesperrt
s2, m2 = bs.add_lines(slip, A, [15], 10.0)
check("Duplikat: derselbe Spieler (anderer Meilenstein) wird abgelehnt, Schein unveraendert", len(s2) == 3 and not any(l["milestone"] == 15 for l in s2) and any("Spieler ist schon im Schein" in x for x in m2), m2)
s3, m3 = bs.add_lines(slip, A, [20], 10.0)
check("Duplikat: identischer Meilenstein 'schon im Schein'", len(s3) == 3 and any("schon im Schein" in x for x in m3), m3)
s4, m4 = bs.add_lines([], A, [15, 20], 10.0)
check("zwei Meilensteine desselben Spielers auf einmal: abgelehnt mit Hinweis (je Spieler nur eine Wette)", s4 == [] and any("nur eine Wette" in x for x in m4), m4)
bl = bs.blocked_milestones(D, [])
check("schon gesetzte Wette: Meilenstein '✓ schon gesetzt', andere Meilensteine des Spielers gesperrt", bl[10] == "✓ schon gesetzt" and "schon eine Wette auf 10+" in bl[15], bl)
s5, m5 = bs.add_lines([], D, [10], 10.0)
check("gesperrter Meilenstein wird nicht hinzugefuegt", s5 == [] and m5)
check("Zeile entfernen", [l["person_id"] for l in bs.remove_line(slip, 2)] == [1, 3])
# --- Speichern
res = bs.save_slip(KEY, slip, options)
saved = ds.get_player_bets_by_key(KEY)
check("Speichern: 3 Eintraege in der Wettliste mit Meilenstein, Quote, Einsatz, Quelle 'gespeichert'", len(saved) == 3 and saved[1]["milestone"] == 20 and saved[1]["odds"] == 1.85 and saved[3]["milestone"] == 25 and saved[2]["stake"] == 10.0
      and all(b["odds_source"] == "gespeichert" and b["placed_at"] for b in saved.values()), {k: (b["milestone"], b["odds"], b["stake"]) for k, b in saved.items()})
check("Meldung '3 Wetten gespeichert', Schein leer", res["messages"] == ["3 Wetten gespeichert"] and res["remaining"] == [] and len(res["saved"]) == 3, res["messages"])
# --- Fehlerfall
KEY2 = "2099-01-01|2099-01-02T03:00:00Z|Heim Falken|Gast Baeren"
bad = [{**slip[0]}, {**slip[1], "stake": 0.0}, {**slip[2], "milestone": 99}]
r2 = bs.save_slip(KEY2, bad, options)
sv2 = ds.get_player_bets_by_key(KEY2)
check("Fehlerfall: gueltige Wette gespeichert, ungueltige (Einsatz 0, Meilenstein nicht in Liste) nicht", set(sv2) == {1} and len(r2["failed"]) == 2 and [l["person_id"] for l in r2["remaining"]] == [2, 3], r2["messages"])
check("Meldung nennt die nicht gespeicherten Wetten; gespeicherte stehen nicht mehr im Schein", any("Berta Beta 10+" in m and "Einsatz" in m for m in r2["messages"]) and any("Carla Gamma 99+" in m for m in r2["messages"]) and r2["messages"][0] == "1 Wette gespeichert")
def flaky(key, player, ms, odds, stake, options, now=None):
    if player["person_id"] == 2:
        raise RuntimeError("Platte voll")
    return pe.save_player_bet(key, player, ms, odds, stake, options, now=now)
KEY3 = "2099-01-01|2099-01-02T05:00:00Z|Heim Falken|Gast Baeren"
r3 = bs.save_slip(KEY3, slip, options, save_fn=flaky)
check("Ausnahme in einer Zeile: andere werden gespeichert, Zeile bleibt im Schein, kein Absturz", set(ds.get_player_bets_by_key(KEY3)) == {1, 3} and [l["person_id"] for l in r3["remaining"]] == [2] and "Unerwarteter Fehler" in r3["messages"][-1], r3["messages"])
r4 = bs.save_slip(PAST, slip, options)
check("Spiel hat begonnen: nichts gespeichert, alle bleiben im Schein mit Sperr-Meldung", not ds.get_player_bets_by_key(PAST) and len(r4["remaining"]) == 3 and all("gesperrt" in m for m in r4["messages"]), r4["messages"][:1])
r5 = bs.save_slip(KEY, slip, options)
check("erneutes Speichern identischer Wetten: 'unveraendert' zaehlt als gespeichert, keine Doppelung", len(ds.get_player_bets_by_key(KEY)) == 3 and r5["remaining"] == [])
check("Bedingung wie das bestehende Formular (ds.is_bet_editable)", ds.is_bet_editable(KEY.split("|")[1]) and not ds.is_bet_editable(PAST.split("|")[1]))
check("echte Wettliste und Tracking-Dateien unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
