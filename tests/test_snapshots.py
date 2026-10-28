"""Tests fuer Schnappschuesse (data/projection_snapshots.py), Ergebnis-Eintrag (update_model.py), Chips (engine/line_probabilities.row_outcome, ui/score_cards.py)
und die Auswertung (analysis/eval_snapshots.py). Keine echten Abrufe, alles Geschriebene liegt in Temp-Ordnern; das echte Pickle sowie die echten Dateien
pre_match_entries.json / rosters.json werden nur gelesen (SHA vor/nach). Aufruf: venv/bin/python tests/test_snapshots.py"""
import copy, datetime as dt, hashlib, io, json, os, re, sys, tempfile, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests")); sys.path.insert(0, str(ROOT / "analysis"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
import data.nba_live as _nba_live
_nba_live.NBA_CACHE_SECONDS = 10 ** 6
import data.pre_match_store as ps
import data.projection_snapshots as snap
import engine.line_probabilities as lp
import ui.score_cards as sc
import update_model
import eval_snapshots as ev
from models.elo import EloEngine, MODEL_PATH
from engine.projection import compute_projection
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
sha0 = sha(MODEL_PATH)
real = {n: (ROOT / "data" / n).read_bytes() if (ROOT / "data" / n).exists() else None for n in ("tracking/pre_match_entries.json", "rosters.json")}
real_snap = ROOT / "data" / "tracking" / "projection_snapshots.json"; real_snap_existed = real_snap.exists()
H = 3600
K, P = "New York Knicks", "Philadelphia 76ers"
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def make_proj(home=K, away=P, start=None, spread=4.5, total=231.5, tt_home=None, tt_away=None, src="Cache", date="2026-10-21"):
    mk = lambda v, bm="Pinnacle": {"line": v, "source": src if v is not None else None, "bookmaker": bm if v is not None else "", "at": 1_790_000_000.0 if v is not None else None, "at_iso": None,
                                  "cache_line": v, "cache_source": src, "cache_at": 1_790_000_000.0, "warn": False}
    pr = compute_projection({"home_team": home, "away_team": away, "home_elo": 1560, "away_elo": 1500, "expected_total": 226.0, "home_win_prob": 0.62, "away_win_prob": 0.38},
                            market_total=total, market_spread=spread, game_date=date)
    pr.update(game_date=date, game_start=start, market_lines={"spread": mk(spread), "total": mk(total), "team_total_away": mk(tt_away), "team_total_home": mk(tt_home)},
              _line_inputs={"game_start": start, "entry_key": ps.game_key(date, start, home, away)})
    return pr

MODEL = {"file_mtime": "2026-10-21T10:59:00+02:00", "file_size": 1, "sha1": "aaa", "ratings_as_of": "2026-10-20"}
def load_games(): return json.loads(snap.snapshot_path().read_text())["games"]
def reset():
    fresh_env(); snap._cache.update(sig=None, data=None)

# ========================================================= A) Schnappschuss nur vor dem Anpfiff, nur bei geaendertem Inhalt
reset(); now = time.time(); start = iso(now + 6 * H); proj = make_proj(start=start)
st = snap.record_snapshots([proj], {}, model=MODEL, now=now)
key = proj["_line_inputs"]["entry_key"]; g = load_games()
d = json.loads(snap.snapshot_path().read_text())
check("Datei: Versionsfeld 1, Format, Schluessel wie pre_match_store.game_key (Datum|Anpfiff|Heim|Gast)", d["version"] == 1 and d["format"] == "nbaedge-projection-snapshots" and list(g) == [key] and key.count("|") == 3, key)
check("erster Lauf vor dem Anpfiff: 1 neues Spiel, 1 Version, Spieldaten gespeichert", st == {"new_games": 1, "new_versions": 1, "unchanged": 0, "locked": 0} and len(g[key]["versions"]) == 1 and g[key]["home"] == K and g[key]["away"] == P and g[key]["result"] is None, str(st))
v = g[key]["versions"][0]
check("Version: Zeitstempel mit UTC-Versatz, Hash, Modellstand, Projektion (Spread, Total, Team-Scores, Siegwahrscheinlichkeit)",
      re.search(r"[+-]\d\d:\d\d$", v["saved_at"]) and len(v["hash"]) == 16 and v["model"] == MODEL and all(k in v["projection"] for k in ("exp_spread", "exp_total", "home_score", "away_score", "home_win_prob", "away_win_prob")), str(v["projection"]))
check("je Markt (Spread, Total, Team Total Gast/Heim): Hauptlinie mit Quelle, Buchmacher, Zeitpunkt der Linie",
      set(v["markets"]) == {"spread", "total", "team_total_away", "team_total_home"} and v["markets"]["spread"]["line"] == 4.5 and v["markets"]["spread"]["source"] == "Cache" and v["markets"]["spread"]["bookmaker"] == "Pinnacle" and v["markets"]["total"]["line_at"], str(v["markets"]["total"]))
rows = v["tables"]["total"]["rows"]
check("alle angezeigten Zeilen: Linie, P links, P rechts, vorhergesagte Seite, Hauptlinie ja/nein (Staffel 7 Zeilen, eine Hauptlinie)",
      len(rows) == 7 and all(set(r) == {"line", "p_left", "p_right", "predicted", "is_main"} and r["p_left"] + r["p_right"] == 100 for r in rows) and sum(r["is_main"] for r in rows) == 1 and len(v["tables"]["spread"]["rows"]) == 5, str(rows[0]))
check("Streuungs-Konstanten gespeichert (Spread, Total, Team Total)", v["sigmas"] == {"spread": lp.SPREAD_SIGMA, "total": lp.TOTAL_SIGMA, "team_total": lp.TEAM_TOTAL_SIGMA})
check("Anzeigefelder der letzten Version als 'card' (fuer die Karte nach dem Spielende), ohne interne Felder", g[key]["card"]["home_team"] == K and "_line_inputs" not in g[key]["card"] and "market_lines" in g[key]["card"])
b0 = snap.snapshot_path().read_bytes(); m0 = snap.snapshot_path().stat().st_mtime_ns
st = snap.record_snapshots([make_proj(start=start)], {}, model=MODEL, now=now + 60)
check("unveraenderter Inhalt: keine neue Version, Datei unveraendert (nicht neu geschrieben)", st["unchanged"] == 1 and st["new_versions"] == 0 and snap.snapshot_path().read_bytes() == b0 and snap.snapshot_path().stat().st_mtime_ns == m0, str(st))
st = snap.record_snapshots([make_proj(start=start, spread=5.5)], {}, model=MODEL, now=now + 120)
g = load_games()
check("geaenderte Linie: neue Version (2), alte bleibt erhalten", st["new_versions"] == 1 and len(g[key]["versions"]) == 2 and g[key]["versions"][0]["markets"]["spread"]["line"] == 4.5 and g[key]["versions"][1]["markets"]["spread"]["line"] == 5.5)
st = snap.record_snapshots([make_proj(start=start, spread=5.5)], {}, model={**MODEL, "sha1": "bbb", "ratings_as_of": "2026-10-21"}, now=now + 180)
g = load_games()
check("geaendertes Modell (Pickle-Hash/Stand): neue Version (3)", st["new_versions"] == 1 and len(g[key]["versions"]) == 3 and g[key]["versions"][2]["model"]["sha1"] == "bbb")
st = snap.record_snapshots([make_proj(start=start, spread=5.5)], {}, model={**MODEL, "sha1": "bbb", "ratings_as_of": "2026-10-21"}, now=now + 200)
check("danach wieder unveraendert: bleibt bei 3 Versionen", st["new_versions"] == 0 and len(load_games()[key]["versions"]) == 3)
# ab dem Anpfiff gesperrt, letzte Version gilt
late = now + 6 * H + 1
st = snap.record_snapshots([make_proj(start=start, spread=9.5)], {}, model=MODEL, now=late)
g = load_games()
check("ab dem Anpfiff: gesperrt, keine neue Version (auch bei geaenderter Linie)", st["locked"] == 1 and st["new_versions"] == 0 and len(g[key]["versions"]) == 3)
st = snap.record_snapshots([make_proj(start=start, spread=9.5)], {}, model=MODEL, now=now + 6 * H)
check("genau zum Anpfiff (now == Anpfiff): gesperrt", st["locked"] == 1 and len(load_games()[key]["versions"]) == 3)
check("die letzte Version vor dem Anpfiff gilt (final_version)", snap.final_version(g[key]) is g[key]["versions"][-1] and snap.final_version(g[key])["markets"]["spread"]["line"] == 5.5 and snap.final_version({}) is None)
st = snap.record_snapshots([make_proj(home="Miami Heat", away="Chicago Bulls", start=None)], {}, model=MODEL, now=now)
check("unbekannter Anpfiff gilt als begonnen: kein Schnappschuss", st["locked"] == 1 and len(load_games()) == 1)
# Spiel ohne Linien
reset(); now = time.time(); start = iso(now + 4 * H); pn = make_proj(spread=None, total=None, start=start)
pn["market_lines"] = {m: {"line": None, "source": None, "bookmaker": "", "at": None, "at_iso": None, "cache_line": None, "warn": False} for m in ("spread", "total", "team_total_away", "team_total_home")}
pn["market_total"], pn["market_spread"] = None, None
st = snap.record_snapshots([pn], {}, model=MODEL, now=now); g = load_games(); vn = list(g.values())[0]["versions"][0]
check("Spiel ohne Marktlinien wird trotzdem gespeichert: Linien null, Tabellen 'keine Linie', Zeilen leer", st["new_versions"] == 1 and all(m["line"] is None for m in vn["markets"].values()) and all(t["rows"] == [] and t["note"] == "keine Linie" for t in vn["tables"].values()), str(vn["tables"]["total"]))
# Verweis auf die Pre-Match-Eingabe (Zeitstempel, keine Kopie der Quoten)
reset(); now = time.time(); start = iso(now + 5 * H); pe = make_proj(start=start)
ps.save_card("2026-10-21", start, K, P, total_rows=[{"id": "main", "direction": None, "line": 233.5, "over_odds": "1,9", "under_odds": "1,9", "bookmaker": "Betano"}], now=now)
ent = ps.load()["entries"][pe["_line_inputs"]["entry_key"]]
snap.record_snapshots([pe], {pe["_line_inputs"]["entry_key"]: ent}, model=MODEL, now=now)
ref = list(load_games().values())[0]["versions"][0]["pre_match_ref"]
txt = snap.snapshot_path().read_text()
check("Verweis auf die Pre-Match-Eingabe: Schluessel + Zeitstempel je Markt (updated_at), keine Quoten kopiert", ref["entry_key"] == pe["_line_inputs"]["entry_key"] and ref["total"] == ent["markets"]["total"]["updated_at"] and "over_odds" not in txt and "1,9" not in txt and "1.9" not in txt, str(ref))
check("Tabelle nutzt die eigene Eingabe (Total 233,5, genau eine Zeile)", list(load_games().values())[0]["versions"][0]["tables"]["total"]["source"] == "eigene Eingabe")

# ========================================================= B) Atomares Schreiben, Sicherung, Fehlerfaelle
reset(); now = time.time(); start = iso(now + 3 * H)
snap.record_snapshots([make_proj(start=start)], {}, model=MODEL, now=now)
before = snap.snapshot_path().read_bytes()
hist = list((snap.snapshot_path().parent / "history").glob("projection_snapshots_*.json"))
check("Tageskopie in history/ nach dem Speichern, gleicher Inhalt", len(hist) == 1 and hist[0].read_bytes() == before)
real_replace = os.replace
def boom(*a, **k): raise OSError("Platte voll")
os.replace = boom
try:
    try:
        snap.record_snapshots([make_proj(start=start, spread=7.5)], {}, model=MODEL, now=now + 10); raised = None
    except snap.SnapshotError as e:
        raised = str(e)
finally:
    os.replace = real_replace
check("Schreibfehler: SnapshotError, bestehende Datei byte-genau unveraendert, keine .tmp-Reste", raised and snap.snapshot_path().read_bytes() == before and not list(snap.snapshot_path().parent.glob("*.tmp")), str(raised))
snap._cache.update(sig=None, data=None)
st = snap.record_snapshots([make_proj(start=start, spread=7.5)], {}, model=MODEL, now=now + 20)
check("danach funktioniert das Speichern wieder (Version 2)", st["new_versions"] == 1 and len(list(load_games().values())[0]["versions"]) == 2)
# Versionswechsel: byte-genaue Sicherung
reset(); path = snap.snapshot_path(); path.parent.mkdir(parents=True, exist_ok=True)
old_bytes = json.dumps({"version": 0, "format": "x", "games": {}}, indent=3).encode()
path.write_bytes(old_bytes)
now = time.time(); snap.record_snapshots([make_proj(start=iso(now + 3 * H))], {}, model=MODEL, now=now)
bk = list((path.parent / "history").glob("projection_snapshots.v0_vor_Upgrade_*.json"))
check("aeltere Dateiversion: byte-genaue Sicherung in history/, danach Version 1 mit Hinweis", len(bk) == 1 and bk[0].read_bytes() == old_bytes and json.loads(path.read_text())["version"] == 1 and json.loads(path.read_text())["upgraded_from_version"] == 0)
reset(); path = snap.snapshot_path(); path.parent.mkdir(parents=True, exist_ok=True)
newer = json.dumps({"version": 99, "games": {}}).encode(); path.write_bytes(newer)
try:
    snap.record_snapshots([make_proj(start=iso(time.time() + 3 * H))], {}, model=MODEL); raised = False
except snap.SnapshotError:
    raised = True
check("neuere Dateiversion: SnapshotError, Datei unveraendert", raised and path.read_bytes() == newer)
reset(); path = snap.snapshot_path(); path.parent.mkdir(parents=True, exist_ok=True); path.write_text("{kaputt")
snap.record_snapshots([make_proj(start=iso(time.time() + 3 * H))], {}, model=MODEL)
cor = list(path.parent.glob("projection_snapshots.corrupt-*.json"))
check("defekte Datei: als .corrupt-Kopie gesichert, neu begonnen", len(cor) == 1 and cor[0].read_text() == "{kaputt" and len(load_games()) == 1)

# ========================================================= C) Ergebnis eintragen (update_model)
def final_game(gid, date, start, home, away, hs, vs, **kw):
    return {"id": gid, "date": date, "datetime": start.replace("Z", ".000Z"), "status": "Final", "postponed": False, "postseason": False, "season": 2025,
            "home_team": {"full_name": home}, "visitor_team": {"full_name": away}, "home_team_score": hs, "visitor_team_score": vs, **kw}
reset(); now = time.time(); start = iso(now - 2 * H); snap_now = now - 8 * H
pg = make_proj(start=iso(snap_now + 3 * H)); pg["_line_inputs"]["game_start"] = iso(snap_now + 3 * H)
snap.record_snapshots([pg], {}, model=MODEL, now=snap_now)
gstart = iso(snap_now + 3 * H); key = pg["_line_inputs"]["entry_key"]
res = snap.record_results([final_game(5, "2026-10-21", gstart, K, P, 100, 106), final_game(6, "2026-10-21", gstart, "A", "B", 1, 2),
                           {**final_game(7, "2026-10-21", gstart, K, P, 90, 80), "status": "3rd Qtr"}], now=now)
r = load_games()[key]["result"]
check("record_results: Ergebnis (Heim-/Gastpunkte, Zeitpunkt, Quelle) beim passenden Schnappschuss, Spiel ohne Schnappschuss nur gezaehlt, nicht beendetes ignoriert",
      res == {"written": 1, "no_snapshot": 1} and r["home_points"] == 100 and r["away_points"] == 106 and r["recorded_at"] and r["source"] == "update_model", str(res) + str(r))
res = snap.record_results([final_game(5, "2026-10-21", gstart, K, P, 1, 2)], now=now)
check("ein vorhandenes Ergebnis wird nie ueberschrieben", res["written"] == 0 and load_games()[key]["result"]["home_points"] == 100)
st = snap.record_snapshots([make_proj(start=gstart, spread=8.5)], {}, model=MODEL, now=snap_now + 60)
check("mit Ergebnis keine neuen Versionen mehr", len(load_games()[key]["versions"]) == 1)
# update_model: kleines Temp-Modell
def tiny_model(tmp):
    e = EloEngine(); e.process_game({"id": 1, "date": "2026-10-19", "status": "Final", "postponed": False, "postseason": False, "home_team": {"full_name": K}, "visitor_team": {"full_name": P},
                                      "home_team_score": 100, "visitor_team_score": 90}); p = Path(tmp) / "elo_model.pkl"; e.save(p); return p
reset(); now = time.time(); snap_now = now - 8 * H; gstart = iso(snap_now + 3 * H)
pg = make_proj(start=gstart); snap.record_snapshots([pg], {}, model=MODEL, now=snap_now); key = pg["_line_inputs"]["entry_key"]
with tempfile.TemporaryDirectory() as tmp:
    pth = tiny_model(tmp); logs = []
    r1 = update_model.run_update(pth, lambda s, e_: [final_game(2, "2026-10-21", gstart, K, P, 110, 104)], today=dt.date(2026, 10, 21), log=logs.append)
    rr = load_games()[key]["result"]
    check("update_model: beendetes Spiel mit Schnappschuss -> Endergebnis in der Snapshot-Datei (und Modell fortgeschrieben)", r1["status"] == "updated" and r1["results_written"] == 1 and rr["home_points"] == 110 and rr["away_points"] == 104 and rr["source"] == "update_model", str(r1))
    r2 = update_model.run_update(pth, lambda s, e_: [final_game(2, "2026-10-21", gstart, K, P, 110, 104)], today=dt.date(2026, 10, 21), log=logs.append)
    check("zweiter Lauf: keine neuen Spiele, nichts doppelt", r2["status"] == "unchanged" and r2.get("results_written", 0) == 0)
    # Fehlerfall: Schreiben schlaegt fehl -> Modell-Update laeuft trotzdem
    reset(); pg = make_proj(start=gstart); snap.record_snapshots([pg], {}, model=MODEL, now=snap_now)
    pth2 = tiny_model(Path(tmp) / "b" if (Path(tmp) / "b").mkdir() is None else tmp); sha_a = sha(pth2)
    def failing(games): raise snap.SnapshotError("Platte voll")
    logs = []
    r3 = update_model.run_update(pth2, lambda s, e_: [final_game(2, "2026-10-21", gstart, K, P, 110, 104)], today=dt.date(2026, 10, 21), log=logs.append, results_fn=failing)
    check("Fehler beim Ergebnis-Schreiben verhindert den Modell-Update NICHT (Status 'updated', Modell gespeichert, Warnung im Text, results_error gesetzt)",
          r3["status"] == "updated" and r3["processed"] == 1 and sha(pth2) != sha_a and "results_error" in r3 and any("Warnung" in l for l in logs), str(r3))
    check("Fehlerfall: Ergebnis nicht eingetragen, Schnappschuss unveraendert", load_games()[pg["_line_inputs"]["entry_key"]]["result"] is None)
    r4 = update_model.run_update(pth2, lambda s, e_: [final_game(2, "2026-10-21", gstart, K, P, 110, 104)], today=dt.date(2026, 10, 21), log=logs.append, dry_run=True, results_fn=lambda g: 1 / 0)
    check("Probelauf (--dry-run) schreibt keine Ergebnisse", r4["status"] in ("unchanged", "dry_run") and "results_error" not in r4)
# Protokoll: WARN
import data.automation_log as alog
update_model._record("WARN", "1 neue Spiele; Ergebnisse nicht gespeichert: OSError", False)
ev_ = alog.read_events(); stt = alog.sidebar_status()
check("automation.log kennt WARN: Zeile wird gelesen, Sidebar gelb mit Hinweis, WARN zaehlt nicht als 'seit Tagen kein Lauf'", ev_ and ev_[-1]["result"] == "WARN" and stt["warn"] and "Warnung" in stt["hint"] and stt["result"] == "WARN")
# Ergebnis aus dem lokalen upcoming_cache (ohne Abruf)
reset(); now = time.time(); snap_now = now - 8 * H; gstart = iso(snap_now + 3 * H)
pg = make_proj(start=gstart); snap.record_snapshots([pg], {}, model=MODEL, now=snap_now); key = pg["_line_inputs"]["entry_key"]
Path(os.environ["NBAEDGE_UPCOMING_CACHE"]).write_text(json.dumps({"fetched_at": now, "params": {}, "games": [final_game(9, "2026-10-21", gstart, K, P, 99, 98)]}))
calls0 = state["bdl_calls"]
rf = snap.fill_results_from_upcoming_cache(now=now)
check("Ergebnis aus upcoming_cache nachgetragen (Quelle 'upcoming_cache'), ohne BallDontLie-Abruf", rf["written"] == 1 and load_games()[key]["result"]["source"] == "upcoming_cache" and state["bdl_calls"] == calls0)

# ========================================================= D) Chips: row_outcome fuer alle Maerkte
R = lambda line, l, r: {"line": line, "p_left": l, "p_right": r, "predicted": lp.predicted_side(l, r), "is_main": False}
o = lambda kind, row, fav, h, a, key="total": lp.row_outcome(kind, row, fav, h, a, key)
check("Total: Over vorhergesagt (60 %), 231 Punkte bei Linie 230,5 -> eingetreten; 229 -> nicht eingetreten", o("over_under", R(230.5, 60, 40), None, 120, 111) == "hit" and o("over_under", R(230.5, 60, 40), None, 120, 109) == "miss")
check("Total: Under vorhergesagt (35 : 65): 229 Punkte bei 230,5 -> eingetreten; 231 -> nicht eingetreten", o("over_under", R(230.5, 35, 65), None, 120, 109) == "hit" and o("over_under", R(230.5, 35, 65), None, 120, 111) == "miss")
check("Total ganzzahlig, exakter Treffer: Push (Over wie Under)", o("over_under", R(231.0, 60, 40), None, 120, 111) == "push" and o("over_under", R(231.0, 40, 60), None, 120, 111) == "push")
check("50 : 50 (keine vorhergesagte Seite): kein Chip, auch bei exaktem Treffer", o("over_under", R(231.0, 50, 50), None, 120, 111) is None and o("over_under", R(230.5, 50, 50), None, 120, 109) is None)
check("Team Total Heim: Punkte des Heimteams (118 bei 117,5 Over) -> eingetreten; Gast: Punkte des Gastteams (105 bei 108,5, Over vorhergesagt) -> nicht eingetreten",
      o("over_under", R(117.5, 60, 40), None, 118, 100, "team_home") == "hit" and o("over_under", R(108.5, 60, 40), None, 118, 105, "team_away") == "miss" and o("over_under", R(105.0, 40, 60), None, 118, 105, "team_away") == "push")
check("Team Total nutzt NICHT das Gesamt-Total (Heim 118, Gast 100: Linie 150,5 Under -> eingetreten)", o("over_under", R(150.5, 30, 70), None, 118, 100, "team_home") == "hit")
# Spread: Favorit Heim (Knicks -4,5): Heim gewinnt 100:90 -> Margin 10 > 4,5 -> Favorit deckt
sp = lambda x, l, r, fav, h, a: o("spread", R(x, l, r), fav, h, a, "spread")
check("Spread, Heim Favorit -4,5: Heim gewinnt mit 10 -> Favorit deckt; rechts (Heim) vorhergesagt -> eingetreten; links (Gast) vorhergesagt -> nicht eingetreten",
      sp(4.5, 38, 62, "home", 100, 90) == "hit" and sp(4.5, 55, 45, "home", 100, 90) == "miss")
check("Spread, Heim Favorit -4,5: Heim gewinnt nur mit 3 -> Favorit deckt nicht; Heim vorhergesagt -> nicht eingetreten, Gast vorhergesagt -> eingetreten", sp(4.5, 38, 62, "home", 93, 90) == "miss" and sp(4.5, 55, 45, "home", 93, 90) == "hit")
check("Spread, Heim Favorit, Heim VERLIERT: Favorit deckt nicht (Margin negativ)", sp(0.5, 40, 60, "home", 90, 95) == "miss" and sp(0.5, 60, 40, "home", 90, 95) == "hit")
check("Spread, Gast Favorit (Gast −6,5, links): Gast gewinnt 110:100 (Margin 10): Favorit deckt; Gast links vorhergesagt -> eingetreten; Heim vorhergesagt -> nicht eingetreten",
      sp(6.5, 70, 30, "away", 100, 110) == "hit" and sp(6.5, 45, 55, "away", 100, 110) == "miss")
check("Spread, Gast Favorit: Gast verliert 100:105 -> Favorit deckt nicht; Gast vorhergesagt -> nicht eingetreten, Heim vorhergesagt -> eingetreten", sp(2.5, 60, 40, "away", 105, 100) == "miss" and sp(2.5, 40, 60, "away", 105, 100) == "hit")
check("Spread ganzzahlig, exakter Treffer (Margin 5 bei Linie 5,0): Push; Underdog-Linie (X negativ, Favorit +3): Margin -3 -> Push", sp(5.0, 40, 60, "home", 105, 100) == "push" and sp(-3.0, 40, 60, "home", 97, 100) == "push")
check("Spread 'PK' (X = 0): Heim Favorit gewinnt knapp -> deckt; Unentschieden gibt es nicht, Margin 0 ist Push", sp(0.0, 40, 60, "home", 101, 100) == "hit" and sp(0.0, 40, 60, "home", 100, 100) == "push")

# ========================================================= E) Chips im HTML der Karte
pj = make_proj(start=iso(time.time() + 3 * H)); result = {"home_points": 118, "away_points": 100}
vm_fin = sc.build_card_vm(pj, None, None, result); vm_live = sc.build_card_vm(pj)
bodies = [sc.line_block_body_html(b) for b in vm_fin["lines"]]; allh = "".join(bodies)
rows_all = [r for b in vm_fin["lines"] for r in b["rows"]]
n_chips = len(re.findall(r'class="pc-lchip pc-lchip-(hit|miss|push)"', allh))
check("beendetes Spiel mit Ergebnis: Chip in jeder Zeile mit vorhergesagter Seite (Anzahl Chips == Zeilen mit outcome), Texte 'eingetreten' / 'nicht eingetreten'",
      n_chips == sum(1 for r in rows_all if r.get("outcome")) and n_chips >= 19 and "eingetreten<" in allh and "nicht eingetreten<" in allh, f"{n_chips} Chips")
check("Chip 'eingetreten' blau, 'nicht eingetreten' und 'Push' grau (CSS), nie gruen/rot", "pc-lchip-hit" in sc.CARD_CSS and "chip_blue" not in sc.CARD_CSS and sc.PALETTE["chip_blue_bg"] in sc.CARD_CSS and sc.PALETTE["chip_gray_bg"] in sc.CARD_CSS
      and not any(int(v[3:5], 16) > int(v[1:3], 16) + 25 and int(v[3:5], 16) > int(v[5:7], 16) + 25 for k, v in sc.PALETTE.items() if v.startswith("#") and not k.startswith("win_ok_")))      # Gruen nur im Sieger-Zeichen (win_ok_*)
check("laufendes/kommendes Spiel ohne Ergebnis: kein Chip", "pc-lchip" not in "".join(sc.line_block_body_html(b) for b in vm_live["lines"]) and not any(r.get("outcome") for b in vm_live["lines"] for r in b["rows"]))
hit = next(r for b in vm_fin["lines"] if b["key"] == "total" for r in b["rows"] if r["line"] == 230.5)
exp = "hit" if (118 + 100 > 230.5) == (hit["predicted"] == "left") else "miss"
check("Total-Zeile 230,5 mit 218 Gesamtpunkten: Ergebnis passt zur vorhergesagten Seite (Under -> eingetreten)", hit["outcome"] == exp == ("hit" if hit["predicted"] == "right" else "miss"), str(hit))
syn = {"rows": [{**R(220.0, 70, 30), "label": "220,0", "left": "Over 70 %", "right": "30 % Under", "style": "ou", "outcome": "push"}, {**R(221.5, 50, 50), "label": "221,5", "left": "Over 50 %", "right": "50 % Under", "style": "ou", "outcome": None}], "note": None}
hs = sc.line_block_body_html(syn)
check("Push-Chip grau 'Push'; 50 : 50 ohne Chip", 'pc-lchip pc-lchip-push">Push<' in hs and hs.count("pc-lchip ") == 1 and hs.count("pc-lrow-chip") == 1)

# ========================================================= F) Auswertung mit kuenstlichen Daten (bekannte Trefferquoten)
def art(n_hit, n_all, p_pred=65, main=False, market="total"):
    """n_all Spiele; je Spiel eine Zeile mit Over p_pred % (Linie 200,5); Treffer = Over trifft (Gesamtpunkte 210) fuer n_hit Spiele, sonst 190."""
    games = {}
    for i in range(n_all):
        pts = 210 if i < n_hit else 190
        games[f"g{i}"] = {"result": {"home_points": pts // 2, "away_points": pts - pts // 2}, "versions": [{"tables": {market: {"kind": "over_under", "favorite": None, "rows": [{"line": 200.5, "p_left": p_pred, "p_right": 100 - p_pred, "predicted": "left", "is_main": main}]}}}]}
    return {"games": games}
c = ev.collect(art(21, 30)); tab = ev.table(c["rows"]["total"])
check("Auswertung: 30 Zeilen mit 65 % vorhergesagt, 21 Treffer -> Stufe 60-70 %: 30 Zeilen, Trefferquote 70,0 %", tab[1] == ("60-70 %", 30, 0.7, 65.0) and tab[0][1] == 0 and tab[2][1] == 0, str(tab))
sect = lambda t, title: t.split(title)[1].split("\n\n")[0].splitlines()      # Zeilen eines Abschnitts (z. B. 'Total - alle Zeilen')
txt = ev.render(art(21, 30)); line60 = [l for l in sect(txt, "Total - alle Zeilen") if l.strip().startswith("60-70 %")][0]
check("Auswertung: ab 30 Zeilen kein Hinweis; Stufen ohne Daten zeigen 'zu wenig Daten'", "zu wenig Daten" not in line60 and "zu wenig Daten" in [l for l in sect(txt, "Total - alle Zeilen") if l.strip().startswith("50-60 %")][0])
txt = ev.render(art(7, 10)); line60 = [l for l in sect(txt, "Total - alle Zeilen") if l.strip().startswith("60-70 %")][0]
check("Auswertung: 10 Zeilen -> 'zu wenig Daten', Trefferquote 70,0 %", "zu wenig Daten" in line60 and "70.0 %" in line60 and "10" in line60, line60)
mixed = art(30, 30, 85); mixed["games"].update({f"h{i}": v for i, v in art(10, 30, 55, True)["games"].items()})
c = ev.collect(mixed); main_only = ev.table([e for e in c["rows"]["total"] if e[2]])
check("Auswertung: Hauptlinien getrennt (nur die 30 Hauptlinien mit 55 %: 50-60 % mit 10/30 = 33,3 %), 80-90 % nur in 'alle Zeilen'",
      main_only[0][1] == 30 and abs(main_only[0][2] - 10 / 30) < 1e-9 and main_only[3][1] == 0 and ev.table(c["rows"]["total"])[3][1] == 30)
txt = ev.render(mixed)
check("Auswertung: Abschnitte je Markt (Spread, Total, Team Total), je 'alle Zeilen' und 'nur Hauptlinien'", all(s_ in txt for s_ in ("Spread - alle Zeilen", "Total - nur Hauptlinien", "Team Total - alle Zeilen")))
push_data = art(0, 5); push_data["games"]["g0"]["result"] = {"home_points": 100, "away_points": 100.5 - 100.5 + 0}
push_data["games"]["g0"]["versions"][0]["tables"]["total"]["rows"][0]["line"] = 200.0
push_data["games"]["g0"]["result"] = {"home_points": 100, "away_points": 100}
cp = ev.collect(push_data)
check("Auswertung: Push (200 Punkte bei Linie 200,0) zaehlt nicht als Treffer/Fehlschlag, wird separat genannt", cp["push"]["total"] == 1 and len(cp["rows"]["total"]) == 4 and "1 Push" in ev.render(push_data))
c0 = ev.collect({"games": {"x": {"versions": [{"tables": {}}], "result": None}}})
check("ohne Ergebnis/ohne Daten: keine Zeilen, freundliche Meldung", c0["games"] == 0 and "Noch keine" in ev.render({"games": {}}))
with tempfile.TemporaryDirectory() as tmp:
    pth = Path(tmp) / "s.json"; pth.write_text(json.dumps(art(21, 30))); b = pth.read_bytes()
    buf = io.StringIO(); so = sys.stdout; sys.stdout = buf
    try: rc = ev.main([str(pth)])
    finally: sys.stdout = so
    check("Skript main: liest die Datei, druckt die Tabelle, aendert nichts", rc == 0 and "Auswertung der Schnappschuesse" in buf.getvalue() and pth.read_bytes() == b)
    buf = io.StringIO(); sys.stdout = buf
    try: rc = ev.main([str(Path(tmp) / "fehlt.json")])
    finally: sys.stdout = so
    check("Skript main ohne Datei: Hinweis, Rueckgabe 1", rc == 1 and "Keine Schnappschuss-Datei" in buf.getvalue())

# ========================================================= G) echte App (AppTest): Schnappschuss je Rerun, beendetes Spiel mit Chips
reset(); fake_net.install()
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
g = load_games() if snap.snapshot_path().exists() else {}
check("echte App: keine Exception; Schnappschuesse fuer die 3 kommenden Spiele (noch nicht begonnen) in der Temp-Datei", not at.exception and len(g) == 3 and all(len(x["versions"]) == 1 for x in g.values()), f"{len(g)} Spiele")
b1 = snap.snapshot_path().read_bytes()
at.run(); at.run()
check("weitere Reruns: keine neue Version, Datei byte-identisch (kein Wachstum bei jedem Klick)", snap.snapshot_path().read_bytes() == b1)
check("kein Abruf durch die Schnappschuesse (Odds-Aufrufe nur der Start-Abruf)", state["bdl_calls"] >= 0 and len(state["odds_calls"]) <= 1, f"BDL {state['bdl_calls']}, Odds {len(state['odds_calls'])}")
# beendetes Spiel (Schnappschuss + Ergebnis in der Datei) erscheint als Karte mit Chips, laufendes nicht
nowx = time.time(); fs = iso(nowx - 5 * H)
pf = make_proj(home="Miami Heat", away="Chicago Bulls", start=fs)
snap.record_snapshots([pf], {}, model=MODEL, now=nowx - 9 * H) if False else None
pf["_line_inputs"]["game_start"] = fs
d = json.loads(snap.snapshot_path().read_text())
kf = pf["_line_inputs"]["entry_key"]
d["games"][kf] = {"game_date": dt.date.today().isoformat(), "start_utc": fs, "home": "Miami Heat", "away": "Chicago Bulls", "card": snap._jsonable({k: v for k, v in pf.items() if k != "_line_inputs"} | {"game_date": dt.date.today().isoformat()}),
                  "versions": [{"saved_at": "x", "hash": "h", **snap.build_snapshot(pf, None, MODEL)}], "result": {"home_points": 118, "away_points": 100, "recorded_at": ps.iso_now(nowx), "source": "update_model"}}
snap.snapshot_path().write_text(json.dumps(d)); snap._cache.update(sig=None, data=None)
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
sp_idx = [i for i, t in enumerate(at.tabs) if "Score Projections" in t.label][0]
cards = [m.value for m in at.tabs[sp_idx].markdown if 'class="pc-card' in m.value]
blocks = [m.value for m in at.tabs[sp_idx].markdown if 'class="pc-lrow' in m.value or 'class="pc-lnote' in m.value]
chip_blocks = [b for b in blocks if "pc-lchip pc-lchip-" in b]
check("beendetes Spiel (Schnappschuss + Ergebnis): Karte erscheint zusaetzlich (4 Karten), nur dessen Zeilen tragen Chips, die 3 anderen nicht",
      not at.exception and len(cards) == 4 and any("Heat" in c_ for c_ in cards) and len(chip_blocks) == 4 and len(blocks) == 16 and "pc-lchip pc-lchip-" not in "".join(b for b in blocks if b not in chip_blocks), f"{len(cards)} Karten, {len(chip_blocks)} Bloecke mit Chips")
old_rec = d["games"][kf]["result"]["recorded_at"]
d["games"][kf]["result"]["recorded_at"] = ps.iso_now(nowx - 30 * H); snap.snapshot_path().write_text(json.dumps(d)); snap._cache.update(sig=None, data=None)
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
check("beendetes Spiel bleibt am aktiven Spieltag stehen (Spieltag-Logik statt 24-Stunden-Regel)", len([m for m in at.tabs[sp_idx].markdown if 'class="pc-card' in m.value]) == 4)
d["games"][kf]["card"]["game_date"] = "2026-10-21"; d["games"][kf]["game_date"] = "2026-10-21"; snap.snapshot_path().write_text(json.dumps(d)); snap._cache.update(sig=None, data=None)
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
check("beendetes Spiel eines frueheren Spieltags verschwindet aus dem Tab", len([m for m in at.tabs[sp_idx].markdown if 'class="pc-card' in m.value]) == 3)
# Mock/Audit-Modus und Projektion ohne Linien: kein Absturz
st = snap.record_snapshots([{"home_team": K, "away_team": P, "exp_spread": 1, "exp_total": 220, "home_score": 110, "away_score": 109}], {}, model=MODEL)
check("Mock-Projektion ohne market_lines/Anpfiff: kein Schnappschuss, kein Absturz", st["locked"] == 1)

# ========================================================= G2) sigmas_version (23.10.2026): Version 2 = Spread 13,2 / Total 18,6 / Team Total 11,6, Siegchance aus der Spread-Verteilung
reset(); now = time.time(); start = iso(now + 6 * H); proj = make_proj(start=start)
snap.record_snapshots([proj], {}, model=MODEL, now=now)
key = proj["_line_inputs"]["entry_key"]; g = load_games(); v = g[key]["versions"][-1]
check("Schnappschuss neu: sigmas_version \"2\" (im Inhalt und damit im Hash), Auswertungs-Helfer liest sie", v["sigmas_version"] == "2" and snap.sigmas_version_of(v) == "2")
check("fehlendes Feld = Version \"1\" (alte Schnappschuesse), None/leer ebenso", snap.sigmas_version_of({"tables": {}}) == "1" and snap.sigmas_version_of(None) == "1" and snap.sigmas_version_of({"sigmas_version": None}) == "1")
check("Projektion im Schnappschuss: Siegchance aus der Spread-Verteilung, Elo-Logistik als *_elo daneben (0,62 / 0,38 aus der Test-Eingabe)",
      v["projection"]["home_win_prob"] == round(lp.win_prob_home(v["projection"]["exp_spread"]), 4) and v["projection"]["home_win_prob_elo"] == 0.62 and v["projection"]["away_win_prob_elo"] == 0.38)
check("Karte im Schnappschuss traegt Quelle und Sigma (fuer den Hinweis nach dem Spielende)", g[key]["card"]["win_prob_source"] == "normal_spread" and g[key]["card"]["sigma_spread"] == 13.2)
# Beginn: gestartetes Spiel bekommt keine neue Version (auch wenn sich die Sigmas geaendert haben) -> bleibt Version 1
reset(); start_past = iso(now - 3 * H)
old = make_proj(start=iso(now + 6 * H)); snap.record_snapshots([old], {}, model=MODEL, now=now)
k_old = old["_line_inputs"]["entry_key"]
data_old = json.loads(snap.snapshot_path().read_text()); ver = data_old["games"][k_old]["versions"][-1]
for f in ("sigmas_version", "sigmas"):
    ver.pop(f, None)
ver["sigmas"] = {"spread": 10.5, "total": 18.0, "team_total": 12.5}; ver["hash"] = "alt"
snap.snapshot_path().write_text(json.dumps(data_old)); snap._cache.update(sig=None, data=None)
st = snap.record_snapshots([old], {}, model=MODEL, now=now + 7 * H)                  # Anpfiff liegt in der Vergangenheit: gesperrt
gg = load_games()[k_old]
check("begonnenes Spiel mit alter Version (ohne sigmas_version): keine neue Version, bleibt unveraendert Version 1 mit 10,5 / 18,0 / 12,5",
      st["locked"] == 1 and len(gg["versions"]) == 1 and snap.sigmas_version_of(gg["versions"][-1]) == "1" and gg["versions"][-1]["sigmas"] == {"spread": 10.5, "total": 18.0, "team_total": 12.5})
st = snap.record_snapshots([old], {}, model=MODEL, now=now)                           # vor dem Anpfiff: neue Version mit Version 2 (Hash geaendert)
gg = load_games()[k_old]
check("noch nicht begonnenes Spiel mit alter Version: neue Version \"2\" wird angehaengt, die alte bleibt erhalten", len(gg["versions"]) == 2 and snap.sigmas_version_of(gg["versions"][0]) == "1" and snap.sigmas_version_of(gg["versions"][1]) == "2")
# Auswertung getrennt nach sigmas_version
d1, d2 = art(21, 30), art(7, 10)
for gid, game in d2["games"].items():
    game["versions"][0]["sigmas_version"] = "2"
both = {"games": {**{f"a{k}": v_ for k, v_ in d1["games"].items()}, **{f"b{k}": v_ for k, v_ in d2["games"].items()}}}
check("eval_snapshots: collect nach Version (1: 30 Spiele, 2: 10 Spiele, ohne Angabe: 40)", ev.collect(both, "1")["games"] == 30 and ev.collect(both, "2")["games"] == 10 and ev.collect(both)["games"] == 40)
txt = ev.render(both)
check("eval_snapshots: je Version eine eigene Tabelle, nie gemischt (zwei Ueberschriften, keine zusammengefasste Tabelle)", txt.count("Auswertung der Schnappschuesse") == 2 and "Version 1 (Spread 10,5" in txt and "Version 2 (Spread 13,2" in txt and "nicht vergleichbar" not in txt)
check("eval_snapshots --alle: zusaetzlich eine zusammengefasste Tabelle, gekennzeichnet", ev.render(both, mix=True).count("Auswertung der Schnappschuesse") == 3 and "nicht vergleichbar" in ev.render(both, mix=True))
check("eval_snapshots: nur Version 1 vorhanden -> eine Tabelle", ev.render(art(21, 30)).count("Auswertung der Schnappschuesse") == 1)

# ========================================================= H) Rahmen
check("Pickle unveraendert (SHA)", sha(MODEL_PATH) == sha0)
check("echte pre_match_entries.json und rosters.json unveraendert", all(((ROOT / "data" / n).read_bytes() if (ROOT / "data" / n).exists() else None) == v for n, v in real.items()))
check("die echte data/tracking/projection_snapshots.json wurde von den Tests nicht angelegt/veraendert", real_snap.exists() == real_snap_existed)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
