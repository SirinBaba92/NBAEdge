"""Tests fuer Prognose-Snapshots (analysis/print_player_forecast.py) und Auswertung (analysis/eval_player_forecasts.py). Nur kuenstliche Daten in Temp-Ordnern, kein Netz,
keine echten Dateien veraendert. Aufruf aus dem Projektordner: venv/bin/python tests/test_eval_player_forecasts.py"""
import gzip, hashlib, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))

TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ["NBAEDGE_SNAPSHOT_DIR"] = str(T / "snaps")
os.environ["NBAEDGE_LIVE_DIR"] = str(T / "live")
os.environ["NBAEDGE_PLAYER_CACHE_DIR"] = str(T / "cache")
os.environ["NBAEDGE_TRACKING_DIR"] = str(T / "tracking")
from analysis import print_player_forecast as pp
from analysis import eval_player_forecasts as ev

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def snap():
    files = list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*")) + list((ROOT / "data" / "cache").glob("*")) + list((ROOT / "data" / "tracking").glob("*.json"))
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = snap()

# --- Snapshot: nicht ueberschreiben, --neu mit Sicherung
KEY = "2026-10-22|2026-10-23T00:00:00Z|Heim Falken|Gast Baeren"
KEY2 = "2026-10-22|2026-10-23T02:00:00Z|Zwei Heim|Zwei Gast"
res_empty = {"context": {"found": False}, "teams": {}, "players": []}
e1 = pp.build_snapshot_entry(KEY, {}, res_empty, datetime(2026, 10, 22, 22, 0, tzinfo=timezone.utc))
check("Snapshot vor Anpfiff: Vermerk 'vor Anpfiff erstellt', created_after_start False", e1["created_after_start"] is False and e1["note"] == "vor Anpfiff erstellt" and e1["status"] == "UNGEPRÜFT")
e_late = pp.build_snapshot_entry(KEY, {}, res_empty, datetime(2026, 10, 23, 0, 30, tzinfo=timezone.utc))
check("Snapshot nach Anpfiff: Vermerk 'nach Anpfiff erstellt, Daten nur bis Vortag'", e_late["created_after_start"] is True and e_late["note"] == "nach Anpfiff erstellt, Daten nur bis Vortag")
check("erstes Schreiben", pp.save_snapshot("2026-10-22", KEY, e1) == "geschrieben")
path = T / "snaps" / "2026-10-22.json"
before = path.read_bytes()
check("zweites Schreiben: vorhanden, Datei bytegleich (nicht ueberschrieben)", pp.save_snapshot("2026-10-22", KEY, e_late) == "vorhanden" and path.read_bytes() == before)
check("anderes Spiel am selben Tag wird ergaenzt, erstes bleibt", pp.save_snapshot("2026-10-22", KEY2, e1 | {"game_key": KEY2}) == "geschrieben" and set(json.loads(path.read_text())["games"]) == {KEY, KEY2})
old = path.read_bytes()
check("--neu: ersetzt das eine Spiel", pp.save_snapshot("2026-10-22", KEY, e_late, new=True) == "neu geschrieben" and json.loads(path.read_text())["games"][KEY]["created_after_start"] is True)
baks = list((T / "snaps").glob("2026-10-22.json.bak-*"))
check("--neu: Sicherung mit Zeitstempel enthaelt den alten Stand", len(baks) == 1 and baks[0].read_bytes() == old and json.loads(path.read_text())["games"][KEY2]["game_key"] == KEY2)
(T / "snaps" / "2026-10-25.json").write_text("{kaputt")
try:
    pp.save_snapshot("2026-10-25", KEY, e1); check("defekte Snapshot-Datei: nicht ueberschrieben", False)
except RuntimeError:
    check("defekte Snapshot-Datei: Fehler statt Ueberschreiben", (T / "snaps" / "2026-10-25.json").read_text() == "{kaputt")
(T / "snaps" / "2026-10-25.json").unlink()
for f in baks: f.unlink()
path.unlink()

# --- Auswertung: kuenstliche Snapshots und Ergebnisse
def player(pid, name, team, abbr, quotes, ok_=True):
    p = {"person_id": pid, "name": name, "team": team, "team_abbreviation": abbr, "ok": ok_, "reason": None, "quality": [], "warnings": [], "quotes": [
        {"milestone": n, "odds": o, "bookmaker": "Betano", "bookmaker_probability": b, "bookmaker_percent": round(b * 100)} for n, o, b, _, _ in quotes]}
    if ok_:
        p.update(minutes={"mean": 30.0}, minutes_adjusted=30.0, expected_points_raw=18.0, expected_points_adjusted=19.0,
                 p_ge_raw={str(n): r for n, _, _, r, _ in quotes}, p_ge_adjusted={str(n): t for n, _, _, _, t in quotes}, games_used={"2025-26": 40})
    return p
#                          N  Quote  Buch  roh  Team
P_A = player(1, "Anton A", "Heim Falken", "HEI", [(20, 1.9, .5, .6, .56), (21, 2.4, .4, .45, .33)])
P_B = player(2, "Bruno B", "Heim Falken", "HEI", [(10, 1.5, .7, .8, .8)])       # 0 Minuten -> nicht gespielt
P_C = player(3, "Carl C", "Heim Falken", "HEI", [(10, 1.5, .7, .8, .8)])        # fehlt im Boxscore -> nicht gespielt
P_D = player(4, "Dirk D", "Gast Baeren", "GAS", [(10, 1.7, .6, .3, .2)])
P_E = player(5, "Egon E", "Gast Baeren", "GAS", [(10, 1.7, .6, .3, .2)], ok_=False)
def entry(key, players): return {"game_key": key, "created_at": "x", "created_after_start": False, "note": "vor Anpfiff erstellt", "players": players, "teams": {}, "context": {}}
def put_snap(day, key, players):
    f = T / "snaps" / f"{day}.json"
    d = json.loads(f.read_text()) if f.exists() else {"version": 1, "day": day, "games": {}}
    d["games"][key] = entry(key, players); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d))
def put_box(day, gid, home_nick, away_nick, home_players, away_players):
    def side(nick, ps): return {"teamName": nick, "teamCity": "X", "players": [{"personId": pid, "statistics": {"minutes": mn, "points": pts}} for pid, mn, pts in ps]}
    d = T / "live" / day / gid; d.mkdir(parents=True, exist_ok=True)
    (d / "final_box.json.gz").write_bytes(gzip.compress(json.dumps({"game": {"homeTeam": side(home_nick, home_players), "awayTeam": side(away_nick, away_players)}}).encode()))

put_snap("2026-10-22", KEY, [P_A, P_B, P_C, P_D, P_E])
put_box("2026-10-22", "G1", "Falken", "Baeren", [(1, "PT30M00.00S", 20), (2, "PT00M00.00S", 0)], [(4, "PT20M00.00S", 5), (5, "PT15M00.00S", 12)])
days = ev.load_snapshots(T / "snaps")
c = ev.collect(days)
check("ein Tag: 1 Spiel, 2 gewertete Spieler mit Prognose (A, D), 3 Zeilen", c["games"] == 1 and len(c["players"]) == 2 and len(c["rows"]) == 3, f"{c['games']} {len(c['players'])} {len(c['rows'])}")
check("nicht gespielt getrennt gezaehlt (B mit 0 Minuten, C fehlt im Boxscore), E ohne Prognose getrennt", sorted(x.split(" (")[0] for x in c["not_played"]) == ["Bruno B", "Carl C"] and c["no_forecast"] == ["Egon E"])
byn = {(r["name"], r["n"]): r for r in c["rows"]}
check("Trefferlogik bei genau N Punkten (20 Punkte: 20+ Treffer, 21+ kein Treffer)", byn[("Anton A", 20)]["hit"] is True and byn[("Anton A", 21)]["hit"] is False and byn[("Dirk D", 10)]["hit"] is False)
b, r_, t = ev.brier(c["rows"], "bookmaker"), ev.brier(c["rows"], "raw"), ev.brier(c["rows"], "team")
exp_b = ((.5 - 1) ** 2 + (.4 - 0) ** 2 + (.6 - 0) ** 2) / 3
exp_r = ((.6 - 1) ** 2 + (.45 - 0) ** 2 + (.3 - 0) ** 2) / 3
exp_t = ((.56 - 1) ** 2 + (.33 - 0) ** 2 + (.2 - 0) ** 2) / 3
check("Brier nachgerechnet (Buchmacher, roh, Team)", abs(b - exp_b) < 1e-12 and abs(r_ - exp_r) < 1e-12 and abs(t - exp_t) < 1e-12, f"{b:.5f} {r_:.5f} {t:.5f}")
check("Verzerrung = mittlere (Chance - Treffer)", abs(ev.bias(c["rows"], "bookmaker") - ((.5 - 1) + .4 + .6) / 3) < 1e-12)
bins = ev.bins5(c["rows"], "bookmaker")
check("5 Stufen: Zeilen verteilt (0,4 -> Stufe 2, 0,5 -> Stufe 2, 0,6 -> Stufe 3)", [n for n, _, _ in bins] == [2, 1] and abs(bins[0][1] - 0.45) < 1e-12 and abs(bins[0][2] - 0.5) < 1e-12, str(bins))
up = [r for r in c["rows"] if r["team_p"] * 100 - r["bookmaker"] * 100 >= ev.MARK_PP]
down = [r for r in c["rows"] if r["team_p"] * 100 - r["bookmaker"] * 100 <= -ev.MARK_PP]
nu, hu, ou, pu = ev.units(up); nd, hd, od, pd_ = ev.units(down)
check("Markierung ◀ (Modell >= 5 PP hoeher): 1 Zeile, Treffer, Einheiten +0,9", (nu, hu, round(ou, 2), round(pu, 6)) == (1, 1.0, 1.9, 0.9), str((nu, hu, ou, pu)))
check("Markierung ▼ (Modell >= 5 PP niedriger): 2 Zeilen, kein Treffer, Einheiten -2", (nd, hd, round(od, 2), round(pd_, 6)) == (2, 0.0, 2.05, -2.0), str((nd, hd, od, pd_)))
text = "\n".join(ev.render_block("Test", c))
check("Ausgabe: Zaehlung, Brier, markierte Zeilen, Abweichungen", "nicht gespielt 2" in text and "Brier" in text and "◀" in text and "▼" in text and "Punkte erwartet" in text)
check("Spiel ohne Ergebnisse wird uebersprungen und genannt", "keine Ergebnisse" in "\n".join(ev.render_block("x", ev.collect({"2026-10-24": {"games": {KEY: entry(KEY, [P_A])}}}))))

# --- mehrere Tage + Liga-Datei als Ersatz
put_snap("2026-10-23", "2026-10-23|2026-10-24T00:00:00Z|Heim Falken|Gast Baeren", [P_A, P_D])
put_box("2026-10-23", "G2", "Falken", "Baeren", [(1, "PT25M00.00S", 30)], [(4, "PT20M00.00S", 12)])
days = ev.load_snapshots(T / "snaps")
c2 = ev.collect(days)
check("zwei Tage: Gesamtblock = 2 Spiele, 6 Zeilen", c2["games"] == 2 and len(c2["rows"]) == 6 and sorted(days) == ["2026-10-22", "2026-10-23"], f"{c2['games']} {len(c2['rows'])}")
check("Tag-Filter beim Laden", list(ev.load_snapshots(T / "snaps", "2026-10-23")) == ["2026-10-23"])
put_snap("2026-10-24", "2026-10-24|2026-10-25T00:00:00Z|Heim Falken|Gast Baeren", [P_A, P_D])
from data import player_history as ph
def lrow(pid, team, mn, pts): return {"game_id": "G3", "date": "2026-10-24", "season": "2026-27", "person_id": pid, "name": "x", "team": team, "opponent": "Y", "home": True, "minutes": mn, "points": pts,
                                      "fga": 1, "fgm": 1, "fta": 0, "ftm": 0, "fg3a": 0, "fg3m": 0, "fouls": 0, "plus_minus": 0, "win": True, "margin": 1, "source": "league"}
ph.atomic_write_json(ph.season_path("2026-27"), {"version": 1, "format": "nbaedge-player-games", "season": "2026-27", "fetched_at": "x", "source": "t", "rows": [lrow(1, "HEI", 30.0, 25), lrow(4, "GAS", 28.0, 15)]})
res, src = ev.game_results("2026-10-24", ev.load_snapshots(T / "snaps", "2026-10-24")["2026-10-24"]["games"]["2026-10-24|2026-10-25T00:00:00Z|Heim Falken|Gast Baeren"])
check("ohne Recorder-Boxscore: Ergebnisse aus der Liga-Datei", src == "Liga-Datei" and res[1]["points"] == 25 and res[4]["points"] == 15)
c3 = ev.collect(ev.load_snapshots(T / "snaps"))
check("drei Tage gesamt: 3 Spiele, 9 Zeilen", c3["games"] == 3 and len(c3["rows"]) == 9)
check("main: Tag und Gesamtblock, Exit 0, Datei geschrieben", ev.main(["2026-10-22", "--dir", str(T / "snaps")]) == 0 and ev.main(["--dir", str(T / "snaps")]) == 0 and ev.main(["2099-01-01", "--dir", str(T / "snaps")]) == 2)
for n in ("2026-10-22", "alle"):
    f = ROOT / "analysis" / "results" / f"eval_player_forecasts_{n}.txt"
    if f.exists(): f.unlink()                                           # vom Test erzeugte (ignorierte) Ausgaben wieder entfernen

check("echte Dateien (Snapshots, Cache, Tracking) unveraendert", snap() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
