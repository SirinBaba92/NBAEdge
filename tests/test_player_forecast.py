"""Tests fuer engine/player_forecast.py (Spieler-Punkte-Prognose, UNGEPRUEFT). Nur kuenstliche Daten in Temp-Ordnern, kein Netz, keine echten Dateien veraendert.
Aufruf aus dem Projektordner: venv/bin/python tests/test_player_forecast.py"""
import hashlib, json, os, sys, tempfile
from datetime import date, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))

TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ["NBAEDGE_PLAYER_CACHE_DIR"] = str(T / "cache")
os.environ["NBAEDGE_LIVE_DIR"] = str(T / "live")
os.environ["NBAEDGE_TRACKING_DIR"] = str(T / "tracking")
from data import player_history as ph
from engine import player_forecast as pf

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def snap():
    files = list((ROOT / "data" / "cache").glob("*")) + list((ROOT / "data" / "tracking").glob("*.json")) + [ROOT / "data" / "rosters.json", ROOT / "data" / "pregame_lines.json"]
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = snap()

def g(pid, day, season, minutes, points, team="AAA", name="Test Spieler", gid=None):
    return {"game_id": gid or f"{pid}-{day}", "date": day, "season": season, "person_id": pid, "name": name, "team": team, "opponent": "BBB", "home": True, "minutes": float(minutes),
            "points": int(points), "fga": 10, "fgm": 4, "fta": 2, "ftm": 1, "fg3a": 3, "fg3m": 1, "fouls": 2, "plus_minus": 0, "win": True, "margin": 5, "source": "league"}

def series(pid, start, n, season, minutes_fn, points_fn, **kw):
    d0 = date.fromisoformat(start)
    return [g(pid, (d0 + timedelta(days=2 * i)).isoformat(), season, minutes_fn(i), points_fn(i), **kw) for i in range(n)]

# Spieler 1: Stammspieler, konstant 34 Min., Punkte schwanken 16..28 (Mittel 22)
P1 = lambda i: [16, 22, 28, 20, 24, 18, 26, 22][i % 8]
M1 = lambda i: 34
games25 = series(1, "2025-11-01", 40, "2025-26", M1, P1)
games26 = series(1, "2026-10-17", 3, "2026-27", M1, lambda i: 22)
allg = sorted(games25 + games26, key=lambda x: x["date"], reverse=True)

# --- before_date
fc = pf.forecast_player(1, "2026-10-23", home=True, exp_spread=0.0, games=allg)
check("alle Spiele vor dem Stichtag zaehlen (43)", fc["ok"] and sum(fc["games_used"].values()) == 43, str(fc["games_used"]))
fc_b = pf.forecast_player(1, "2026-10-23", games=allg + [g(1, "2026-10-23", "2026-27", 40, 80), g(1, "2026-10-25", "2026-27", 40, 80)])
check("Spiele AM Stichtag und danach werden ignoriert", fc_b["games_used"] == fc["games_used"] and abs(fc_b["expected_points"] - fc["expected_points"] - 0.0) < 1.5)
fc_c = pf.forecast_player(1, "2026-10-17", games=allg)
check("Stichtag 17.10.: das Spiel vom 17.10. zaehlt nicht (nur Vorsaison)", fc_c["games_used"] == {"2025-26": 40} and "nur Vorsaison" in fc_c["quality"], str(fc_c["games_used"]))
# ueber den Spielverlauf (data/player_history) mit Temp-Cache
ph.atomic_write_json(ph.season_path("2025-26"), {"version": 1, "format": "nbaedge-player-games", "season": "2025-26", "fetched_at": "x", "source": "t", "rows": games25})
ph.atomic_write_json(ph.season_path("2026-27"), {"version": 1, "format": "nbaedge-player-games", "season": "2026-27", "fetched_at": "x", "source": "t", "rows": games26})
fc_h = pf.forecast_player(1, "2026-10-22", home=True, exp_spread=0.0)
check("ueber player_history: Stichtag 22.10. -> 43 Spiele, Stichtag 17.10. -> 40", fc_h["games_used"] == {"2025-26": 40, "2026-27": 3} and pf.forecast_player(1, "2026-10-17")["games_used"] == {"2025-26": 40})

# --- Gewichte
w = pf.game_weights(allg, "2026-27")
check("Gewichte: Summe 1, alle positiv", abs(sum(w) - 1) < 1e-9 and all(x > 0 for x in w))
cur_idx = [i for i, x in enumerate(allg) if x["season"] == "2026-27"]
check("Gewichte fallen innerhalb der Saison (neuere staerker)", all(w[cur_idx[i]] > w[cur_idx[i + 1]] for i in range(len(cur_idx) - 1)))
prev_idx = [i for i, x in enumerate(allg) if x["season"] == "2025-26"]
check("Halbwertszeit: 8 Spiele aelter = halbes Gewicht", abs(w[prev_idx[8]] / w[prev_idx[0]] - 0.5) < 1e-9)
check("Schrumpfung: 3 Spiele in der neuen Saison -> Anteil 3/(3+8)", abs(sum(w[i] for i in cur_idx) - 3 / 11) < 1e-9, str(sum(w[i] for i in cur_idx)))
w0 = pf.game_weights(games25[::-1], "2026-27")
check("keine Spiele in der neuen Saison: Vorsaison traegt alles", abs(sum(w0) - 1) < 1e-9)
w8 = pf.game_weights(series(1, "2026-10-01", 8, "2026-27", M1, P1)[::-1] + games25[::-1], "2026-27")
check("8 Spiele in der neuen Saison: je 50 %", abs(sum(w8[:8]) - 0.5) < 1e-9)
check("nur neue Saison: Anteil 1", abs(sum(pf.game_weights(games26[::-1], "2026-27")) - 1) < 1e-9 and pf.game_weights([], "2026-27") == [])

# --- Schrumpfung wirkt auf die Minuten
prev = series(2, "2025-11-01", 40, "2025-26", lambda i: 30, lambda i: 15)
new2 = series(2, "2026-10-20", 2, "2026-27", lambda i: 20, lambda i: 10)
new30 = series(2, "2026-09-01", 30, "2026-27", lambda i: 20, lambda i: 10)
m_few = pf.forecast_player(2, "2026-12-30", games=sorted(prev + new2, key=lambda x: x["date"], reverse=True))["minutes"]["base"]
m_many = pf.forecast_player(2, "2026-12-30", games=sorted(prev + new30, key=lambda x: x["date"], reverse=True))["minutes"]["base"]
check("wenige neue Spiele: Minuten naeher an der Vorsaison (30) als bei vielen", m_few > m_many and m_few > 26 and m_many < 25, f"{m_few:.1f} vs {m_many:.1f}")

# --- Verteilung
p = fc["p_ge"]
vals = [p[n] for n in range(1, 61)]
check("p_ge fuer N = 1..60, Werte in 0..1", sorted(p) == list(range(1, 61)) and all(0.0 <= v <= 1.0 for v in vals))
check("p_ge nicht steigend in N", all(a >= b - 1e-12 for a, b in zip(vals, vals[1:])))
check("p_ge sinnvoll: P(>=1) ~ 1, P(>=60) ~ 0, Median nahe den erwarteten Punkten", p[1] > 0.99 and p[60] < 0.01 and abs(next(n for n in range(1, 61) if p[n] < 0.5) - fc["expected_points"]) < 3)
check("erwartete Punkte nahe Historie (22) bei Spread 0", abs(fc["expected_points"] - 22) < 2.0, f"{fc['expected_points']:.1f}")
check("Minuten: Mittel, Streuung, Spanne vorhanden", 30 < fc["minutes"]["mean"] < 38 and fc["minutes"]["sd"] >= pf.MINUTES_SD_FLOOR and fc["minutes"]["low"] < fc["minutes"]["mean"] < fc["minutes"]["high"])
check("Status UNGEPRUEFT als Konstante und im Ergebnis", fc["status"] == pf.UNVERIFIED == "UNGEPRÜFT" and "UNGEPRÜFT" in pf.UNVERIFIED_TEXT)

# --- Blowout
f0, f15 = pf.blowout_factor(34, 0.0), pf.blowout_factor(34, 15.0)
check("Blowout-Faktor Stammspieler: Spread 0 > Spread 15", f0 > f15 and f0 > 1.0 and f15 < 1.0, f"{f0:.3f} / {f15:.3f}")
check("Blowout-Faktor symmetrisch (+15 = -15)", abs(pf.blowout_factor(34, 15) - pf.blowout_factor(34, -15)) < 1e-9)
check("Rotation schwaecher als Stamm, Bank = 1,0", 1.0 > pf.blowout_factor(24, 15) > f15 and pf.blowout_factor(15, 15) == 1.0 and pf.blowout_factor(24, 0) < f0)
check("Referenz: typischer Abstand ergibt Faktor ~1", all(abs(v - 1.0) < 0.01 for v in pf._REF.values()), str(pf._REF))
fa = pf.forecast_player(1, "2026-10-23", home=True, exp_spread=0.0, games=allg)
fb = pf.forecast_player(1, "2026-10-23", home=True, exp_spread=15.0, games=allg)
fc_away = pf.forecast_player(1, "2026-10-23", home=False, exp_spread=15.0, games=allg)
check("Minuten bei Spread 15 kleiner als bei Spread 0", fb["minutes"]["mean"] < fa["minutes"]["mean"] and fb["expected_points"] < fa["expected_points"], f"{fa['minutes']['mean']:.2f} / {fb['minutes']['mean']:.2f}")
check("Gast bei Heim-Spread 15 = gleicher Abstand (Betrag), gleiche Minuten", abs(fc_away["minutes"]["mean"] - fb["minutes"]["mean"]) < 1e-9)
check("Blowout-Faktor im Ergebnis dokumentiert", abs(fb["minutes"]["blowout_factor"] - f15) < 1e-9 and fb["minutes"]["role"] == "Stamm")

# --- fehlender Schnappschuss / kein Verlauf / Qualitaet
fn = pf.forecast_player(1, "2026-10-23", home=True, exp_spread=None, games=allg)
check("fehlender Schnappschuss: Prognose mit Spread 0 und Warnung", fn["ok"] and any("Schnappschuss" in x for x in fn["warnings"]) and abs(fn["minutes"]["mean"] - fa["minutes"]["mean"]) < 1e-9)
check("Schnappschuss-Datei fehlt: context_for_game -> found False", pf.context_for_game("2026-10-22|x|Heim|Gast") == {"found": False, "exp_spread": None, "exp_total": None, "home": None, "away": None})
none = pf.forecast_player(999, "2026-10-23")
check("Spieler ohne Verlauf: keine Prognose, Grund genannt", none["ok"] is False and "kein Verlauf" in none["reason"] and none["quality"] == ["kein Verlauf"] and "p_ge" not in none and none["status"] == pf.UNVERIFIED)
check("nur Kurzeinsaetze (< 8 Min.): keine Prognose, Grund", pf.forecast_player(3, "2026-10-23", games=series(3, "2026-10-01", 5, "2026-27", lambda i: 3, lambda i: 2))["ok"] is False)
few = pf.forecast_player(4, "2026-10-23", games=series(4, "2026-10-01", 4, "2026-27", lambda i: 20, lambda i: 10)[::-1])
check("wenige Spiele erkannt", "wenige Spiele" in few["quality"] and few["ok"])
rolle = series(5, "2026-01-01", 30, "2025-26", lambda i: 32, lambda i: 18) + series(5, "2026-03-15", 5, "2025-26", lambda i: 18, lambda i: 8)
rolle.sort(key=lambda x: x["date"], reverse=True)
fr = pf.forecast_player(5, "2026-10-23", games=rolle)
check("Rollenwechsel erkannt (letzte 5 Spiele 18 statt ~30 Min.)", "Rollenwechsel" in fr["quality"] and any("letzten 5" in x for x in fr["warnings"]), str(fr["quality"]))
check("Spieler mit steigender Rolle bekommt hoehere Minuten als Vorsaison-Schnitt allein, aber unter dem alten Wert (Mischung)", 18 < fr["minutes"]["base"] < 32)

# --- Kontext und Spiel (Schnappschuss + Quoten im Temp-Ordner)
key = "2026-10-22|2026-10-23T00:00:00Z|Heim Team|Gast Team"
(T / "tracking").mkdir(parents=True, exist_ok=True)
(T / "tracking" / "projection_snapshots.json").write_text(json.dumps({"version": 1, "format": "x", "updated_at": None, "games": {key: {"home": "Heim Team", "away": "Gast Team",
    "versions": [{"projection": {"exp_spread": 4.0, "exp_total": 229.5}}, {"projection": {"exp_spread": 6.5, "exp_total": 231.0}}]}}}))
ctx = pf.context_for_game(key)
check("Schnappschuss: letzte Version, Spread und Total", ctx == {"found": True, "exp_spread": 6.5, "exp_total": 231.0, "home": "Heim Team", "away": "Gast Team"}, str(ctx))
entries = {key: {"markets": {"player_points": {"players": [
    {"id": "p1", "person_id": 1, "name": "Test Spieler", "team": "Heim Team", "team_abbreviation": "HEI", "mode": "milestones", "active": True,
     "lines": [{"id": "x", "threshold": 20, "odds": 1.8, "bookmaker": "Betano", "active": True}, {"id": "y", "threshold": 25, "odds": 3.0, "bookmaker": "Betano", "active": True}]},
    {"id": "p2", "person_id": 999, "name": "Unbekannt", "team": "Gast Team", "team_abbreviation": "GAS", "mode": "milestones", "active": True,
     "lines": [{"id": "x", "threshold": 10, "odds": 1.5, "bookmaker": "Betano", "active": True}]}]}}}}
res = pf.forecast_game_players(key, entries)
byname = {x["name"]: x for x in res["players"]}
check("Spiel: beide Spieler, Heim aus dem Schnappschuss, Prognose bzw. Grund", res["context"]["found"] and byname["Test Spieler"]["forecast"]["ok"] and not byname["Unbekannt"]["forecast"]["ok"] and byname["Test Spieler"]["forecast"]["context"]["home"] is True)
check("Spiel: Spread 6,5 aus dem Schnappschuss wirkt (Minuten unter Spread 0)", byname["Test Spieler"]["forecast"]["minutes"]["mean"] < pf.forecast_player(1, "2026-10-22", home=True, exp_spread=0.0)["minutes"]["mean"])
check("Spiel: Quotenzeilen bleiben erhalten", [r["milestone"] for r in byname["Test Spieler"]["rows"]] == [20, 25])
empty = pf.forecast_game_players("2026-10-22|x|A|B", {})
check("Spiel ohne Spieler: leere Liste", empty["players"] == [] and empty["context"]["found"] is False)

check("echte Dateien (data/cache, Tracking, rosters.json) unveraendert", snap() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
