"""Test: Betano-Import ersetzt die gespeicherten Meilensteine eines Spielers komplett (Spieler mit 11 alten und 9 neuen Linien -> 9 Linien, kein Fehler 'hoechstens 10 Meilensteine').
Offline, Temp-Ordner (fake_net.fresh_env), kein Abruf bei Betano; echte Dateien werden nicht beruehrt. Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_replace_lines.py"""
import hashlib, json, os, sys, warnings, copy
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import fresh_env
fake_net.install(); fresh_env()
import data.pre_match_store as ps
import data.rosters as ro
import eingabe as ei
import betano_import as bi

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
sha = lambda p: hashlib.sha1(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
real = {n: sha(ROOT / "data" / n) for n in ("elo_model.pkl", "rosters.json", "tracking/pre_match_entries.json", "tracking/day_bets.json")}
FIX = ROOT / "tests" / "fixtures" / "betano_magic_hawks.har.json"
REAL_ROSTER = (ROOT / "data" / "rosters.json").read_text()
M, HK = "Orlando Magic", "Atlanta Hawks"
START = "2026-10-21T23:00:00Z"
NOW = 1792623600000 / 1000 - 6 * 3600
G = {"home": M, "away": HK, "date": "2026-10-21", "start": START}
KEY = ps.game_key(G["date"], START, M, HK)

def setup():
    tmp = fresh_env()
    ro.rosters_path().write_text(REAL_ROSTER)
    (tmp / "upcoming_cache.json").write_text(json.dumps({"fetched_at": NOW, "params": {}, "games": [{"home_team": {"full_name": M}, "visitor_team": {"full_name": HK}, "date": G["date"], "datetime": START, "status": "scheduled"}]}))
    return tmp
def entry(): return (ps.load().get("entries") or {}).get(KEY)
def run_import(answers):
    out = []
    def real(prompt):
        return answers.pop(0) if answers else "q"
    rc = bi.main(["--datei", str(FIX)], real=real, write=out.append, now_fn=lambda: NOW, after=None)
    return rc, out
def lines_of(name):
    b = next(b for b in ps.active_player_blocks(entry()) if b["name"] == name)
    return sorted(l["threshold"] for l in ps.player_lines(b))

# --- Ausgangslage: normaler Import (Enter = speichern)
setup()
rc, out = run_import([""])
blocks = ps.active_player_blocks(entry())
check("Erster Import speichert Spieler-Linien (Betano liefert je Spieler hoechstens 9)", rc == 0 and blocks and max(len(ps.player_lines(b)) for b in blocks) <= 9, [len(ps.player_lines(b)) for b in blocks][:6])
name = blocks[0]["name"]
new_lines = lines_of(name)
store_path = ps.store_path()

# --- 11 ALTE Linien weit unterhalb der neuen: Betano-Linien liegen alle ausserhalb -> vorher: 20 Linien, Fehler
data = json.loads(store_path.read_text(encoding="utf-8"))
blk = next(b for b in ps.active_player_blocks(data["entries"][KEY]) if b["name"] == name)
tmpl = copy.deepcopy(ps.player_lines(blk)[0])
first = min(new_lines)
fresh_odds = {l["threshold"]: l["odds"] for l in ps.player_lines(blk)}              # Quoten laut Betano (neuester Stand)
old_th = [t for t in range(first - 12, first - 1) if t >= 1][:11]
old_th = old_th if len(old_th) == 11 else list(range(first + 40, first + 51))          # Rueckfall: oberhalb
olds = []
for i, t in enumerate(old_th):
    l = copy.deepcopy(tmpl); l["threshold"] = t; l["id"] = f"alt{i}"; l["odds"] = 1.11 + i * 0.1
    olds.append(l)
for k in ("lines", "milestones", "rows"):
    if k in blk and isinstance(blk[k], list):
        for l in blk[k]:
            l["odds"] = round(l["odds"] * 1.07 + 0.01, 2)                             # gespeicherte Quoten weichen ab -> der Import hat echte Aenderungen zu speichern
        blk[k] = olds + [l for l in blk[k]]
        break
else:
    raise SystemExit("Struktur des Spielerblocks unbekannt: " + str(list(blk)))
ps._atomic_write(store_path, data)
check("Vorbereitung: Spieler hat jetzt 11 alte + 9 neue gespeicherte Linien", len(lines_of(name)) == len(new_lines) + 11 and len(old_th) == 11, (len(lines_of(name)), len(new_lines)))
before_other = {b["name"]: lines_of(b["name"]) for b in ps.active_player_blocks(entry()) if b["name"] != name}

# Gegenprobe: so verhielt sich der Import vorher (Schalter aus) -> alte Linien bleiben neben den neuen, Fehler "hoechstens 10 Meilensteine"
_orig = ei.run_game
ei.run_game = lambda con, g, now_fn=None, replace_player_lines=False: _orig(con, g, now_fn)
rc0, out0 = run_import([""])
ei.run_game = _orig
check("Gegenprobe (Schalter aus = altes Verhalten): Fehler 'hoechstens 10 Meilensteine' tritt auf und nichts wird geaendert", "höchstens 10 Meilensteine" in "\n".join(out0) and len(lines_of(name)) == len(new_lines) + 11, "\n".join(out0)[-200:])
rc, out = run_import([""])
txt = "\n".join(out)
after = lines_of(name)
check("zweiter Import: KEIN Fehler 'hoechstens 10 Meilensteine', gespeichert", rc == 0 and "höchstens" not in txt and "Gespeichert." in txt, txt[-300:])
check("Spieler hat danach nur noch die Linien von Betano (alte 11 verworfen)", after == new_lines and not set(after) & set(old_th), (after, new_lines))
check("andere Spieler unveraendert", all(lines_of(n) == l for n, l in before_other.items()))
check("Linie und Quote sind der neueste Stand von Betano (abweichende gespeicherte Quoten ueberschrieben)", {l["threshold"]: l["odds"] for l in ps.player_lines(next(b for b in ps.active_player_blocks(entry()) if b["name"] == name))} == fresh_odds)

# --- Spieler ohne neue Betano-Daten bleiben unveraendert (Block eines Spielers, den Betano nicht liefert)
data = json.loads(store_path.read_text(encoding="utf-8"))
mk = data["entries"][KEY]["markets"]["player_points"]
blocks_all = mk["blocks"] if isinstance(mk, dict) and "blocks" in mk else None
extra_before = None
if blocks_all is not None:
    ghost = copy.deepcopy(blocks_all[0]); ghost["id"] = "geist"; ghost["person_id"] = 99999999; ghost["name"] = "Nicht Bei Betano"
    for k in ("lines", "milestones", "rows"):
        if k in ghost and isinstance(ghost[k], list):
            for i, l in enumerate(ghost[k]):
                l["id"] = f"g{i}"
    blocks_all.append(ghost)
    ps._atomic_write(store_path, data)
    extra_before = [(l["threshold"], l["odds"]) for l in ps.player_lines(next(b for b in ps.active_player_blocks(entry()) if b["name"] == "Nicht Bei Betano"))]
    rc, out = run_import([""])
    extra_after = [(l["threshold"], l["odds"]) for l in ps.player_lines(next(b for b in ps.active_player_blocks(entry()) if b["name"] == "Nicht Bei Betano"))]
    check("Spieler ohne Betano-Daten: gespeicherte Linien bleiben unveraendert", rc == 0 and extra_before == extra_after, (extra_before[:3], extra_after[:3]))

# --- manuelle Eingabe (eingabe.build_plan ohne den Schalter) verhaelt sich wie vorher
import inspect
check("Schalter replace_player_lines ist standardmaessig AUS (manuelle Eingabe unveraendert), nur der Betano-Import schaltet ihn ein",
      inspect.signature(ei.build_plan).parameters["replace_player_lines"].default is False and inspect.signature(ei.run_game).parameters["replace_player_lines"].default is False
      and "replace_player_lines=True" in Path(ROOT / "betano_import.py").read_text(encoding="utf-8"))
# --- Limit bleibt als Schutz
check("Limit MAX_MILESTONES = 10 bleibt bestehen", ps.MAX_MILESTONES == 10)
check("echte Dateien unveraendert", {n: sha(ROOT / "data" / n) for n in real} == real)
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)
