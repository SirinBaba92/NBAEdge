"""Test: jede neue Version in projection_snapshots.json enthaelt den reinen Modellwert VOR der Marktmischung (model_total, model_spread, Mischgewichte,
Modell-Teampunkte). Offline, Temp-Ordner (fake_net.fresh_env), die echte Datei wird nur per Hash verglichen. Aufruf: venv/bin/python tests/test_snapshots_modellwert.py"""
import datetime as dt, hashlib, json, os, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install(); fresh_env()
import data.pre_match_store as ps
import data.projection_snapshots as snap
from engine.projection import compute_projection

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

real = ROOT / "data" / "tracking" / "projection_snapshots.json"
real_before = hashlib.sha1(real.read_bytes()).hexdigest() if real.exists() else None
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
MODEL = {"file_mtime": "2026-10-21T10:59:00+02:00", "file_size": 1, "sha1": "aaa", "ratings_as_of": "2026-10-20"}
HOME, AWAY = "New York Knicks", "Philadelphia 76ers"

def make_proj(start, spread, total, date="2026-10-21"):
    mk = lambda v: {"line": v, "source": "Cache", "bookmaker": "Pinnacle", "at": 1_790_000_000.0, "at_iso": None, "cache_line": v, "cache_source": "Cache", "cache_at": 1_790_000_000.0, "warn": False}
    pr = compute_projection({"home_team": HOME, "away_team": AWAY, "home_elo": 1560, "away_elo": 1500, "expected_total": 226.0, "home_win_prob": 0.62, "away_win_prob": 0.38},
                            market_total=total, market_spread=spread, game_date=date)
    pr.update(game_date=date, game_start=start, market_lines={"spread": mk(spread), "total": mk(total), "team_total_away": mk(None), "team_total_home": mk(None)},
              _line_inputs={"game_start": start, "entry_key": ps.game_key(date, start, HOME, AWAY)})
    return pr
def games(): return json.loads(snap.snapshot_path().read_text())["games"]

snap._cache.update(sig=None, data=None)
now = time.time(); start = iso(now + 6 * H)
p1 = make_proj(start, spread=-3.5, total=240.5)                # Markt weicht klar vom Modell ab
key = p1["_line_inputs"]["entry_key"]
st = snap.record_snapshots([p1], {}, model=MODEL, now=now)
v = games()[key]["versions"][-1]; pj = v["projection"]
check("erste Version: genau 1 neue Version", st["new_versions"] == 1 and len(games()[key]["versions"]) == 1, str(st))
check("Version enthaelt model_total, model_spread, market_weight, spread_market_weight, model_home_score, model_away_score",
      all(pj.get(k) is not None for k in ("model_total", "model_spread", "market_weight", "spread_market_weight", "model_home_score", "model_away_score")), str(pj))
check("Werte stimmen mit der Projektion ueberein (nichts neu gerechnet, nur uebernommen)", pj["model_total"] == round(p1["model_total"], 4) and pj["model_spread"] == round(p1["model_spread"], 4)
      and pj["market_weight"] == round(p1["market_weight"], 4) and pj["spread_market_weight"] == 0.25 and pj["market_weight"] > 0, str(pj))
check("Modellwert weicht vom gemischten Wert ab (Markt weicht vom Modell ab)", pj["model_total"] != pj["exp_total"] and pj["model_spread"] != pj["exp_spread"] and abs(pj["model_total"] - 240.5) > 1,
      f"{pj['model_total']} vs {pj['exp_total']}; {pj['model_spread']} vs {pj['exp_spread']}")
check("Modell-Teampunkte: Summe = model_total, Differenz = model_spread", abs(pj["model_home_score"] + pj["model_away_score"] - pj["model_total"]) < 1e-3 and abs(pj["model_home_score"] - pj["model_away_score"] - pj["model_spread"]) < 1e-3)
b0 = snap.snapshot_path().read_bytes()
st = snap.record_snapshots([make_proj(start, spread=-3.5, total=240.5)], {}, model=MODEL, now=now + 60)
check("zweiter Abruf ohne Aenderung: keine zusaetzliche Version, Datei unveraendert", st["new_versions"] == 0 and st["unchanged"] == 1 and len(games()[key]["versions"]) == 1 and snap.snapshot_path().read_bytes() == b0, str(st))
st = snap.record_snapshots([make_proj(start, spread=-3.5, total=236.5)], {}, model=MODEL, now=now + 120)
vs = games()[key]["versions"]
check("echte Aenderung (Total-Linie): genau 1 neue Version, alte unveraendert", st["new_versions"] == 1 and len(vs) == 2 and vs[0]["markets"]["total"]["line"] == 240.5 and vs[1]["markets"]["total"]["line"] == 236.5)
check("Modellwert bleibt bei Aenderung der Marktlinie gleich, der gemischte Wert aendert sich", vs[0]["projection"]["model_total"] == vs[1]["projection"]["model_total"] and vs[0]["projection"]["exp_total"] != vs[1]["projection"]["exp_total"])
p_old = make_proj(start, spread=-3.5, total=240.5); [p_old.pop(k) for k in ("model_total", "model_spread")]
check("Projektion ohne Modellwerte (aelter/Mock): Felder fehlen in projection, kein Fehler", "model_total" not in snap.build_snapshot(p_old, None, MODEL)["projection"])
check("echte projection_snapshots.json unveraendert", (hashlib.sha1(real.read_bytes()).hexdigest() if real.exists() else None) == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
