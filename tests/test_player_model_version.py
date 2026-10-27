"""Tests: Modellversion (PLAYER_MODEL_VERSION) in Prognose-Snapshot und Spieler-Wette, Modell-Chancen (roh/Teamabgleich) und Anzeigemodus bei neuen Wetten, null-Fall,
alte Wetten ohne Felder, Kategorien unbeeintraechtigt. Nur Temp-Ordner, kein Netz, echte Dateien werden nicht veraendert.
Aufruf aus dem Projektordner: venv/bin/python tests/test_player_model_version.py"""
import hashlib, json, os, sys, tempfile, time, warnings
from datetime import datetime, timezone
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_SNAPSHOT_DIR=str(T / "snaps"))
from data import day_bets_store as ds
from data import pre_match_store as ps
from engine import player_forecast as pf
from engine import player_snapshots as psn
from ui import bet_slip as bs
from ui import player_bet_entry as pe

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*"))
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()
(T / "tracking").mkdir(parents=True)

NOW = time.time()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
FUT = iso(NOW + 5 * 3600)
D = "2026-10-22"
K = ps.game_key(D, FUT, "Heim Falken", "Gast Baeren")
GP = dict(game_date=D, start_utc=FUT, home="Heim Falken", away="Gast Baeren")

# ------------------------------------------------------------ Versionsfeld im Snapshot
check("Konstante an zentraler Stelle, Startwert player-1", pf.PLAYER_MODEL_VERSION == "player-1")
res = {"players": [], "context": {}, "teams": {}}
entry = psn.build_snapshot_entry(K, {}, res, datetime.now(timezone.utc))
check("neuer Snapshot-Eintrag enthaelt model_version", entry.get("model_version") == "player-1", entry.get("model_version"))

def write_snapshot(version="player-1"):
    e = {"game_key": K, "created_at": "2026-10-22T10:00:00+02:00", "note": "vor Anpfiff erstellt", "players": [
        {"person_id": 1, "name": "Anna Alpha", "ok": True, "p_ge_raw": {"20": 0.41, "15": 0.7}, "p_ge_adjusted": {"20": 0.47, "15": 0.75}},
        {"person_id": 2, "name": "Berta Beta", "ok": False}]}
    if version: e["model_version"] = version
    p = ds.forecast_snapshot_path(D); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "day": D, "games": {K: e}}))

def opt(m, odds): return {"milestone": m, "odds": odds, "bookmaker": "Betano", "bookmaker_percent": 50, "bookmaker_probability": 0.5, "updated_at": None, "model_raw": None, "model_team": None}
def pl(pid, name, opts): return {"person_id": pid, "name": name, "team": "Heim Falken", "team_abbreviation": "HEI", "options": opts, "current_bet": None, "forecast_ok": True, "warnings": []}
options = {"players": [pl(1, "Anna Alpha", [opt(15, 1.3), opt(20, 1.85)]), pl(2, "Berta Beta", [opt(10, 1.5)]), pl(3, "Carla Gamma", [opt(20, 2.0)])], "snapshot": True}
PB = lambda: ds.get_player_bets_by_key(K)

# ------------------------------------------------------------ neue Wette mit Snapshot
write_snapshot()
r = pe.save_player_bet(K, options["players"][0], 20, "1,85", 10.0, options, now=NOW, categories=["player_ta"], display_mode="raw")
b = PB()[1]
check("neue Wette: Modell-Chance roh / Teamabgleich fuer diese Linie", r[0] and b["model_p_roh"] == 0.41 and b["model_p_team"] == 0.47)
check("neue Wette: Anzeigemodus 'roh' und Modellversion", b["display_mode"] == "roh" and b["model_version"] == "player-1")
check("Kategorien unbeeintraechtigt", b["categories"] == ["player_ta"])
r = pe.save_player_bet(K, options["players"][0], 15, "1,3", 10.0, options, now=NOW + 1, display_mode="team")
b = PB()[1]
check("Aenderung auf andere Linie: Werte der neuen Linie, Modus 'teamabgleich', Kategorien bleiben", b["model_p_roh"] == 0.7 and b["model_p_team"] == 0.75 and b["display_mode"] == "teamabgleich" and b["categories"] == ["player_ta"])
check("Revision bewahrt den alten Stand mit seinen Modellwerten", b["revisions"][-1]["model_p_roh"] == 0.41 and b["revisions"][-1]["display_mode"] == "roh")
# Anzeigemodus ueber den Wettschein (save_slip -> save_fn bekommt nur categories; Modus kommt aus der Sitzung -> hier None)
res = bs.save_slip(K, [{"person_id": 3, "name": "Carla Gamma", "team": "Heim Falken", "milestone": 20, "odds": 2.0, "stake": 5.0}], options, categories=["player_raw"])
b3 = PB()[3]
check("Spieler ohne Snapshot-Eintrag: Chancen null, Wette trotzdem gespeichert", res["saved"] and b3["model_p_roh"] is None and b3["model_p_team"] is None and b3["display_mode"] is None)
b2 = None
pe.save_player_bet(K, options["players"][1], 10, "1,5", 5.0, options, now=NOW + 2, display_mode="team")
b2 = PB()[2]
check("Spieler mit ok=False im Snapshot (keine Chancen): null, nicht blockiert", b2["model_p_roh"] is None and b2["model_p_team"] is None and b2["model_version"] == "player-1")
check("unbekannter Modus -> null", (pe.save_player_bet(K, options["players"][2], 20, "2,0", 6.0, options, now=NOW + 3, display_mode="quatsch")[0]) and PB()[3]["display_mode"] is None)

# ------------------------------------------------------------ Snapshot ohne Versionsfeld (alt) und ohne Snapshot
write_snapshot(version=None)
ds.remove_player_bet(**GP, person_id=1, now=NOW + 4)
pe.save_player_bet(K, options["players"][0], 20, "1,85", 10.0, options, now=NOW + 5, display_mode="team")
check("alter Snapshot ohne Versionsfeld gilt als player-0, Wette erbt das", PB()[1]["model_version"] == "player-0" and PB()[1]["model_p_roh"] == 0.41)
ds.forecast_snapshot_path(D).unlink()
ds.remove_player_bet(**GP, person_id=1, now=NOW + 6)
r = pe.save_player_bet(K, options["players"][0], 20, "1,85", 10.0, options, now=NOW + 7, display_mode="raw")
b = PB()[1]
check("kein Snapshot: Wette wird gespeichert, Chancen null, Modus und aktuelle Version gesetzt", r[0] and b["model_p_roh"] is None and b["model_p_team"] is None and b["display_mode"] == "roh" and b["model_version"] == "player-1")
ds.forecast_snapshot_path(D).write_text("{kaputt")
ds.remove_player_bet(**GP, person_id=1, now=NOW + 8)
r = pe.save_player_bet(K, options["players"][0], 20, "1,85", 10.0, options, now=NOW + 9)
check("defekte Snapshot-Datei blockiert nichts", r[0] and PB()[1]["model_p_roh"] is None)

# ------------------------------------------------------------ alte Wetten ohne Felder
K2 = ps.game_key(D, iso(NOW - 3600), "Zwei Loewen", "Zwei Adler")
data = json.loads(ds.store_path().read_text())
data["games"][K2] = {"game_date": D, "start_utc": iso(NOW - 3600), "home": "Zwei Loewen", "away": "Zwei Adler", "bets": {}, "player_bets": {"11": {
    "market": "player_points", "active": True, "name": "Lena Lauf", "team": "Zwei Loewen", "milestone": 12, "side": "over", "odds": 1.8, "stake": 10.0, "odds_source": "gespeichert",
    "odds_ref": None, "placed_at": "2026-10-22T10:00:00+00:00", "updated_at": "2026-10-22T10:00:00+00:00", "removed_at": None, "revisions": []}}}
ds.store_path().write_text(json.dumps(data))
old = ds.get_player_bets_by_key(K2)
check("alte Wette ohne Felder laedt fehlerfrei", 11 in old and old[11]["milestone"] == 12 and old[11].get("model_p_roh") is None)
check("alte Wette gilt als player-0", ds.bet_model_version(old[11]) == "player-0" and ds.bet_model_version(PB()[1]) == "player-1")
check("alte Wette in Tagesliste und mit 'Ohne Kategorie'", ds.get_day_player_bets(D)[K2]["player_bets"][11]["categories"] == [])
check("echte Dateien unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
