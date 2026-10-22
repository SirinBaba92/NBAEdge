"""Tests fuer engine/player_odds.py (Buchmacher-Chance aus Betano-Meilensteinen). Offline; die echte pre_match_entries.json wird nur gelesen (Kopie im Temp-Ordner).
Aufruf aus dem Projektordner: venv/bin/python tests/test_player_odds.py"""
import hashlib, json, os, shutil, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from engine import player_odds as po

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

REAL = ROOT / "data" / "tracking" / "pre_match_entries.json"
real_hash = hashlib.sha1(REAL.read_bytes()).hexdigest() if REAL.exists() else None

def line(th, odds, active=True, book="Betano"): return {"id": f"x{th}", "threshold": th, "odds": odds, "bookmaker": book, "active": active}
def block(name, team, lines, active=True, mode="milestones"):
    return {"id": name, "person_id": abs(hash(name)) % 10**6, "name": name, "team": team, "team_abbreviation": team[:3].upper(), "mode": mode, "active": active, "lines": lines}
def entries(blocks): return {"G": {"markets": {"player_points": {"players": blocks}}}}

# Umrechnung
check("2,00 = 50 %", po.implied_probability(2.0) == 0.5 and po.milestone_rows(block("A", "X", [line(10, 2.0)]))[0]["percent"] == 50)
check("1,80 = 56 %", po.milestone_rows(block("A", "X", [line(10, 1.8)]))[0]["percent"] == 56)
check("1/Quote ohne festen Abschlag", abs(po.implied_probability(4.0) - 0.25) < 1e-12 and abs(po.implied_probability(1.01) - 1 / 1.01) < 1e-12)
check("ungueltige Quoten -> None", all(po.implied_probability(v) is None for v in (None, 0, 1, 1.0, 0.5, -2, "abc", "", float("nan"), float("inf"), True, [], {})))
check("Quote als Text mit Zahl wird akzeptiert", po.implied_probability("2.5") == 0.4)
check("Label", po.MARGIN_LABEL == "Buchmacher-Chance (inkl. Marge)")

# Zeilen
b = block("Spieler", "Atlanta Hawks", [line(15, 3.0), line(10, 1.5), line(12, 1.9, active=False), line(13, 2.0, book="Test")])
rows = po.milestone_rows(b)
check("Reihenfolge aufsteigend, inaktive Linie weg", [r["milestone"] for r in rows] == [10, 13, 15], str([r["milestone"] for r in rows]))
check("Zeile: Meilenstein = Over N-0,5, Quote, Buchmacher, Prozent", rows[1] == {"milestone": 13, "over_line": 12.5, "odds": 2.0, "bookmaker": "Test", "probability": 0.5, "percent": 50}, str(rows[1]))
check("Mehrfachmeilensteine: eine Zeile je aktive Linie", len(rows) == 3)
check("Linie ohne gueltige Quote wird uebersprungen", len(po.milestone_rows(block("A", "X", [line(10, None), line(11, 1.0), line(12, 2.0)]))) == 1)
check("Block ohne Linien / None -> leer", po.milestone_rows(block("A", "X", [])) == [] and po.milestone_rows(None) == [])
check("Einzellinie (kein threshold) wird nicht als Meilenstein gelesen", po.milestone_rows(block("A", "X", [{"line": 24.5, "over_odds": 1.9, "active": True}], mode="line")) == [])

# Plausibilitaet
check("saubere Reihe: keine Warnung", po.monotonic_warnings(rows) == [])
bad = po.milestone_rows(block("Falsch", "X", [line(10, 2.0), line(12, 1.8), line(14, 3.0)]))
w = po.monotonic_warnings(bad, "Falsch")
check("Verstoss (12+ wahrscheinlicher als 10+) erkannt, genau einer", len(w) == 1 and "12+" in w[0] and "10+" in w[0] and w[0].startswith("Falsch"), str(w))
check("gleiche Chance bei hoeherem Meilenstein ist Verstoss", len(po.monotonic_warnings(po.milestone_rows(block("G", "X", [line(10, 2.0), line(11, 2.0)])))) == 1)
check("Quoten werden nicht korrigiert", [r["odds"] for r in bad] == [2.0, 1.8, 3.0])

# Spiel
E1 = entries([block("Zeta", "Boston Celtics", [line(20, 3.0)]), block("Alpha", "Atlanta Hawks", [line(18, 2.0), line(22, 4.0)]),
              block("Beta", "Atlanta Hawks", [line(10, 1.3), line(15, 2.0)]), block("Weg", "Atlanta Hawks", [line(5, 1.2)], active=False),
              block("Leer", "Atlanta Hawks", [line(5, 1.2, active=False)])])
g = po.game_player_odds(E1, "G")
check("Spieler nach Team, dann niedrigstem Meilenstein sortiert; inaktive und leere Spieler fehlen", [p["name"] for p in g] == ["Beta", "Alpha", "Zeta"], str([p["name"] for p in g]))
check("Spieler-Felder", set(g[0]) == {"name", "team", "team_abbreviation", "person_id", "rows", "warnings"})
check("Spiel ohne Spieler / unbekanntes Spiel / None -> leere Liste", po.game_player_odds({"G": {"markets": {}}}, "G") == [] and po.game_player_odds(E1, "X") == [] and po.game_player_odds(None, "G") == [])
check("Warnliste je Spiel", po.game_warnings(po.game_player_odds(entries([block("S", "X", [line(10, 2.0), line(11, 1.5)])]), "G")) != [])

# Lesetest auf Kopie der echten Datei
if REAL.exists():
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "pre_match_entries.json"; shutil.copy(REAL, copy)
        data = json.loads(copy.read_text(encoding="utf-8"))
        ents = data["entries"]
        res = {k: po.game_player_odds(ents, k) for k in ents}
        games = sum(1 for v in res.values() if v)
        players = sum(len(v) for v in res.values())
        lines = sum(len(p["rows"]) for v in res.values() for p in v)
        check("Struktur: jede Zeile hat Meilenstein, Quote > 1, Prozent 1..99", all(1 < r["odds"] and 1 <= r["percent"] <= 99 and isinstance(r["milestone"], int) for v in res.values() for p in v for r in p["rows"]))
        check("Struktur: Zeilen aufsteigend je Spieler", all([r["milestone"] for r in p["rows"]] == sorted(r["milestone"] for r in p["rows"]) for v in res.values() for p in v))
        print(f"INFO echte Datei (Kopie): {games} Spiele, {players} Spieler, {lines} aktive Linien, {sum(len(p['warnings']) for v in res.values() for p in v)} Warnungen")
        # Soll-Zahlen nur pruefen, wenn die Datei so noch vorliegt (Marker: genau diese Zahlen im Bestand beim Schreiben des Tests)
        if lines == 1519 or players == 180:
            check("Bestand 13 Spiele / 180 Spieler / 1.519 aktive Linien", (games, players, lines) == (13, 180, 1519), str((games, players, lines)))
check("echte Datei nicht veraendert", (hashlib.sha1(REAL.read_bytes()).hexdigest() if REAL.exists() else None) == real_hash)

print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
