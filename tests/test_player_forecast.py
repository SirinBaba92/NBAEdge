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
check("Schnappschuss-Datei fehlt: context_for_game -> found False", pf.context_for_game("2026-10-22|x|Heim|Gast") == {"found": False, "exp_spread": None, "exp_total": None, "home_score": None, "away_score": None, "home": None, "away": None})
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
check("Schnappschuss: letzte Version, Spread, Total, Teampunkte aus Total und Spread", ctx == {"found": True, "exp_spread": 6.5, "exp_total": 231.0, "home_score": 118.75, "away_score": 112.25, "home": "Heim Team", "away": "Gast Team"}, str(ctx))
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


# --- Teamabgleich (P6c): Rotation 10, Stammspieler behalten Minuten, Bank zuerst gekuerzt
def mk_roster(team, ids_names):
    return {"version": 1, "format": "nbaedge-rosters", "fetched_at": "2026-10-21T04:56:44+02:00", "source": "t", "season": "2026-27", "abrufe": 1,
            "teams": {team: [{"person_id": i, "name": n, "position": "G", "jersey": "1", "team_id": 1, "team_abbreviation": "HEI"} for i, n in ids_names]}}
def hist(pid, n, minutes, points, name):
    return series(pid, "2026-01-01", n, "2025-26", lambda i: minutes, lambda i: points, name=name)
NAMES = ["Eins", "Zwei", "Drei", "Vier", "Fuenf", "Sechs", "Sieben", "Acht", "Neun", "Zehn", "Elf", "Zwoelf"]
SPEC = [(39, 24), (34, 22), (33, 20), (31, 18), (30, 16), (26, 12), (24, 10), (22, 9), (20, 8), (18, 6), (14, 4), (12, 3)]
HEI = [(11 + i, n) for i, n in enumerate(NAMES)]
allhist = []
for (pid, name), (mn, pt) in zip(HEI, SPEC):
    allhist += hist(pid, 30, mn, pt, name)
SMALL = [(31, "K Eins", 34, 20), (32, "K Zwei", 32, 18), (33, "K Drei", 30, 16), (34, "K Vier", 28, 14), (35, "K Fuenf", 26, 12)]
for pid, name, mn, pt in SMALL:
    allhist += hist(pid, 30, mn, pt, name)
rows_t = sorted(allhist, key=lambda x: x["date"])
ph.atomic_write_json(ph.season_path("2025-26"), {"version": 1, "format": "nbaedge-player-games", "season": "2025-26", "fetched_at": "x", "source": "t", "rows": rows_t})
ph.atomic_write_json(ph.season_path("2026-27"), {"version": 1, "format": "nbaedge-player-games", "season": "2026-27", "fetched_at": "x", "source": "t", "rows": []})
pf._league_ppm_cache.clear()
roster = mk_roster("Heim Team", HEI)
roster["teams"]["Klein Team"] = [{"person_id": pid, "name": n, "position": "G", "jersey": "1", "team_id": 2, "team_abbreviation": "KLE"} for pid, n, _, _ in SMALL] + \
    [{"person_id": 99, "name": "K Neu Ohne Verlauf", "position": "G", "jersey": "9", "team_id": 2, "team_abbreviation": "KLE"}]
(T / "rosters.json").write_text(json.dumps(roster))
os.environ["NBAEDGE_ROSTERS"] = str(T / "rosters.json")
key2 = "2026-10-22|2026-10-23T00:00:00Z|Heim Team|Gast Team"
def write_snap(hs, as_, home="Heim Team", away="Gast Team"):
    (T / "tracking" / "projection_snapshots.json").write_text(json.dumps({"version": 1, "format": "x", "updated_at": None, "games": {key2: {"home": home, "away": away,
        "versions": [{"projection": {"exp_spread": hs - as_, "exp_total": hs + as_, "home_score": hs, "away_score": as_}}]}}}))
def ent(pids, team="Heim Team"):
    names = dict(HEI)
    return {key2: {"markets": {"player_points": {"players": [{"id": f"p{i}", "person_id": i, "name": names[i], "team": team, "team_abbreviation": "HEI", "mode": "milestones", "active": True,
            "lines": [{"id": "x", "threshold": 10, "odds": 1.8, "bookmaker": "Betano", "active": True}, {"id": "y", "threshold": 20, "odds": 3.0, "bookmaker": "Betano", "active": True}]} for i in pids]}}}}
write_snap(110.0, 108.0)
tm = pf.team_match("Heim Team", True, pf.context_for_game(key2), "2026-10-22")
info = tm["info"]
check("Teamabgleich: Team erkannt, Rotation = 10 Spieler, Rang 11 und 12 draussen", info["matched"] and info["members"] == 10 and info["out_of_rotation"] == ["Elf", "Zwoelf"] and info["rotation"][:2] == ["Eins", "Zwei"], str(info["rotation"]))
nm = info["minutes_new"]
check("Rotation: Summe der neuen Minuten = 240", abs(sum(nm.values()) - 240.0) < 1e-6 and abs(info["minutes_after"] - 240.0) < 1e-6 and info["minutes_note"] == "", f"{sum(nm.values()):.2f}")
check("Stammspieler behalten ihre erwarteten Minuten (Obergrenze 36)", nm["Eins"] == 36.0 and all(abs(nm[n] - tm["raw"][pid]["minutes"]["mean"]) < 1e-9 for pid, n in HEI[1:5]), str({k: round(v, 1) for k, v in nm.items()}))
check("Bank (Rang 6-10) wird gekuerzt, Faktor zwischen 0,3 und 1,0", all(0.3 - 1e-9 <= nm[n] / tm["raw"][pid]["minutes"]["mean"] <= 1.0 + 1e-9 for pid, n in HEI[5:10]) and nm["Sechs"] < tm["raw"][16]["minutes"]["mean"])
check("Rang 11 und 12 nicht in der Summe (keine neuen Minuten, kein angepasster Wert, Prognose bleibt roh)", "Elf" not in nm and 21 not in tm["adjusted"] and 22 not in tm["adjusted"] and 21 in tm["raw"])
adj_sum = sum(f["expected_points"] for f in tm["adjusted"].values())
check("Summe der angepassten Punkte der Rotation = Teampunkte (110), Toleranz 0,5", abs(adj_sum - 110.0) < 0.5 and 0.6 <= info["factor"] <= 1.4 and not info["strong"], f"{adj_sum:.2f} f={info['factor']:.3f}")
res2 = pf.forecast_game_players(key2, ent([11, 12, 21]))
byn = {x["name"]: x for x in res2["players"]}
f1 = byn["Eins"]["forecast"]
check("Ausgabefelder je Spieler: roh/angepasst, Minuten angepasst", all(k in f1 for k in ("expected_points_raw", "expected_points_adjusted", "p_ge_raw", "p_ge_adjusted", "minutes_adjusted")) and f1["expected_points"] == f1["expected_points_raw"] and f1["p_ge"] == f1["p_ge_raw"] and abs(f1["minutes_adjusted"] - 36.0) < 1e-9)
check("Teamkennzahlen: Spieler-Summe, Teampunkte, Faktor, Minuten vor/nach", {"player_sum", "team_points", "factor", "minutes_before", "minutes_after"} <= set(res2["teams"]["Heim Team"]) and res2["teams"]["Heim Team"]["team_points"] == 110.0)
elf = byn["Elf"]["forecast"]
check("Spieler auf Rang 11: roh, mit Hinweis 'nicht in der Rotation'", elf["ok"] and elf["p_ge_adjusted"] == elf["p_ge_raw"] and elf["expected_points_adjusted"] == elf["expected_points_raw"] and "nicht in der Rotation" in elf["team_note"], elf["team_note"])
fac = res2["teams"]["Heim Team"]["factor_applied"]
check("Faktor wirkt: angepasste Punkte ~ rohe Punkte * Minutenverhaeltnis * f", abs(byn["Zwei"]["forecast"]["expected_points_adjusted"] - byn["Zwei"]["forecast"]["expected_points_raw"] * fac) < 1.0)
# f unter 1 senkt, f ueber 1 hebt die Chancen
write_snap(95.0, 93.0)
low = pf.forecast_game_players(key2, ent([12]))["players"][0]["forecast"]
write_snap(170.0, 168.0)
high = pf.forecast_game_players(key2, ent([12]))["players"][0]["forecast"]
check("f unter 1 senkt, f ueber 1 hebt die Chancen (P(>=20))", low["p_ge_adjusted"][20] < low["p_ge_raw"][20] and high["p_ge_adjusted"][20] > high["p_ge_raw"][20], f"{low['p_ge_adjusted'][20]:.2f}<{low['p_ge_raw'][20]:.2f} / {high['p_ge_adjusted'][20]:.2f}>{high['p_ge_raw'][20]:.2f}")
for label, fcx in (("f<1", low), ("f>1", high)):
    v = [fcx["p_ge_adjusted"][n] for n in range(1, 61)]
    check(f"p_ge_adjusted ({label}) nicht steigend, 0..1, N=1..60", len(v) == 60 and all(0 <= x <= 1 for x in v) and all(a >= b - 1e-12 for a, b in zip(v, v[1:])))
# f-Begrenzung
write_snap(400.0, 398.0)
big = pf.team_match("Heim Team", True, pf.context_for_game(key2), "2026-10-22")["info"]
write_snap(30.0, 28.0)
small = pf.team_match("Heim Team", True, pf.context_for_game(key2), "2026-10-22")["info"]
check("f-Begrenzung oben: 1,4 und Hinweis 'Teamabgleich stark'", big["factor_applied"] == 1.4 and big["strong"] and "Teamabgleich stark" in big["note"] and big["factor"] > 1.4, str(big["factor"]))
check("f-Begrenzung unten: 0,6 und Hinweis", small["factor_applied"] == 0.6 and small["strong"] and "Teamabgleich stark" in small["note"] and small["factor"] < 0.6)
check("normaler Faktor: keine Begrenzung, kein Hinweis", not info["strong"] and info["note"] == "")
# Sonderfaelle der Minutenverteilung
d_ok, n_ok = pf.distribute_minutes([36, 34, 33, 31, 30, 26, 24, 22, 20, 18])
check("distribute_minutes Normalfall: Summe 240, Stammspieler unveraendert", abs(sum(d_ok) - 240) < 1e-9 and d_ok[:5] == [36, 34, 33, 31, 30] and n_ok == "" and all(d_ok[i] < [26, 24, 22, 20, 18][i - 5] for i in range(5, 10)))
d1, n1 = pf.distribute_minutes([36] * 5 + [60] * 5)
check("Sonderfall Bank unter 0,3: alle proportional auf 240, nie ueber 42, Hinweis", abs(sum(d1) - 240) < 1e-9 and max(d1) <= 42 + 1e-9 and "Sonderfall" in n1, n1[:70])
d2, n2 = pf.distribute_minutes([30] * 5 + [10] * 5)
check("Sonderfall Bank ueber 1,0 (Stamm+Bank unter 240): alle proportional auf 240, Hinweis", abs(sum(d2) - 240) < 1e-9 and "Sonderfall" in n2 and abs(d2[0] - 240 / 200 * 30) < 1e-9, n2[:70])
d3, n3 = pf.distribute_minutes([40, 38, 36, 34, 32])
check("Sonderfall ohne Bank: Skalierung mit Obergrenze 42, Hinweis", max(d3) <= 42 + 1e-9 and "Sonderfall" in n3 and "keine Bank" in n3)
d4, _ = pf.distribute_minutes([40, 30, 30, 30, 30, 30, 20, 20, 20, 20])
check("Stammspieler-Obergrenze 36 gilt im Normalfall (40 -> 36)", d4[0] == 36.0 or "Sonderfall" in _)
# Spieler ohne Verlauf in der Rotation (kleine Mannschaft: 5 mit Verlauf + 1 ohne -> 6 Spieler, Sonderfall)
write_snap(100.0, 90.0, home="Klein Team", away="Heim Team")
kt = pf.team_match("Klein Team", True, pf.context_for_game(key2), "2026-10-22")
ki = kt["info"]
check("Spieler ohne Verlauf wird mit Hinweis beruecksichtigt (10 Min., Liga-Schnitt)", ki["no_history"] == ["K Neu Ohne Verlauf"] and ki["members"] == 6 and "Sonderfall" in ki["minutes_note"] and abs(ki["minutes_after"] - 240) < 1e-6)
tot = sum(f["expected_points"] for f in kt["adjusted"].values()) + ki["minutes_new"]["K Neu Ohne Verlauf"] * pf.league_ppm() * ki["factor_applied"]
check("Teamsumme inkl. Spieler ohne Verlauf = Teampunkte (100), Toleranz 0,5", abs(tot - 100.0) < 0.5 or ki["strong"], f"{tot:.2f} f={ki['factor']:.2f}")
# fehlender Schnappschuss
(T / "tracking" / "projection_snapshots.json").unlink()
nos = pf.forecast_game_players(key2, ent([12]))
f_no = nos["players"][0]["forecast"]
check("fehlender Schnappschuss: kein Abgleich, angepasst = roh, Hinweis 'kein Teamabgleich'", f_no["p_ge_adjusted"] == f_no["p_ge_raw"] and f_no["expected_points_adjusted"] == f_no["expected_points_raw"] and "kein Teamabgleich" in f_no["team_note"]
      and not pf.team_match("Heim Team", True, pf.context_for_game(key2), "2026-10-22")["info"]["matched"])
# Staerke
write_snap(95.0, 93.0)
pf.TEAM_MATCH_STRENGTH = 0.0
z = pf.forecast_game_players(key2, ent([12]))["players"][0]["forecast"]
pf.TEAM_MATCH_STRENGTH = 0.5
h = pf.forecast_game_players(key2, ent([12]))
pf.TEAM_MATCH_STRENGTH = 1.0
full = pf.forecast_game_players(key2, ent([12]))
check("TEAM_MATCH_STRENGTH = 0: angepasst = roh (auch Minuten)", z["p_ge_adjusted"] == z["p_ge_raw"] and z["expected_points_adjusted"] == z["expected_points_raw"] and z["minutes_adjusted"] == z["minutes"]["mean"])
check("Staerke 0,5: angewandter Faktor = Wurzel des vollen Faktors", abs(h["teams"]["Heim Team"]["factor_applied"] - full["teams"]["Heim Team"]["factor"] ** 0.5) < 1e-9)
sm = pf.scale_minutes([30.0] * 10)
check("scale_minutes: Summe 240", abs(sum(sm) - 240) < 1e-9 and all(abs(x - 24) < 1e-9 for x in sm))
sm2 = pf.scale_minutes([40.0, 40.0, 10.0, 10.0, 10.0, 10.0, 10.0])
check("scale_minutes: Obergrenze 42 je Spieler, Summe 240 bleibt", max(sm2) <= 42 + 1e-9 and abs(sum(sm2) - 240) < 1e-9, str([round(x, 1) for x in sm2]))

check("echte Dateien (data/cache, Tracking, rosters.json) unveraendert", snap() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
