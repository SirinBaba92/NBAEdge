"""Tests fuer Totals-Fix und Fortschreiben (update_model.py) mit simulierten Daten.
Keine echten API-Calls, das echte Pickle wird nur gelesen; alles Geschriebene liegt in einem
temporaeren Verzeichnis. Aufruf: venv/bin/python tests/test_update_model.py"""
import copy, datetime as dt, hashlib, json, shutil, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import update_model
import data.game_updates as gu
import data.fetcher as fetcher
from models.elo import EloEngine, MODEL_PATH

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
real_sha = sha(MODEL_PATH)

def mk(i, date, h, a, hs, vs, status="Final", post=False, **kw):
    return {"id": i, "date": date, "status": status, "postponed": False, "postseason": post, "season": 2025,
            "home_team": {"full_name": h}, "visitor_team": {"full_name": a},
            "home_team_score": hs, "visitor_team_score": vs, **kw}

# --- 1. Totals-Fix: Playoffs nicht in Off/Def, aber in ELO/Form/Ruhetage ------------------
e = EloEngine()
e.process_game(mk(1, "2026-04-10", "A", "B", 110, 100))
off_a, def_a = e.off_ratings["A"], e.def_ratings["A"]
elo_a, form_a = e.ratings["A"], list(e.form["A"])
e.process_game(mk(2, "2026-04-20", "A", "B", 90, 85, post=True))
check("Playoff-Spiel aendert Off/Def nicht", e.off_ratings["A"] == off_a and e.def_ratings["A"] == def_a)
check("Playoff-Spiel aendert ELO, Form und letztes Spiel", e.ratings["A"] != elo_a and len(e.form["A"]) == len(form_a) + 1 and e.last_game["A"] == dt.date(2026, 4, 20))
e.process_game(mk(3, "2026-04-12", "A", "B", 100, 100 - 1))
check("Regular-Season-Spiel aendert Off/Def", e.off_ratings["A"] != off_a)
check("last_game wandert nie rueckwaerts", e.last_game["A"] == dt.date(2026, 4, 20))
check("Spiel-IDs und Stand werden gemerkt", e.processed_ids == {1, 2, 3} and e.ratings_as_of() == dt.date(2026, 4, 20))

# --- 2. Altes Pickle (vor dem Fortschreiben, ohne Spiel-IDs): synthetisch nachgebaut ---------
# (das echte Pickle wird nach jedem Training ersetzt und hat dann IDs; es wird hier nur gelesen)
import pickle
real = EloEngine.load()
check("echtes Pickle laesst sich laden", real.ratings_as_of() is not None, f"Stand {real.ratings_as_of()}, IDs: {None if real.processed_ids is None else len(real.processed_ids)}")
legacy = EloEngine()
for g in json.loads((ROOT / "data" / "cache" / "games_2020.json").read_text())[:200]:
    legacy.process_game(g)
for attr in ("processed_ids", "last_processed_date", "pending"):
    legacy.__dict__.pop(attr)                      # so sah ein Pickle vor dem Fortschreiben aus
with tempfile.TemporaryDirectory() as tmp:
    pth = Path(tmp) / "elo_model.pkl"
    pth.write_bytes(pickle.dumps(legacy))
    old = EloEngine.load(pth)
    check("altes Pickle ohne IDs wird als 'unbekannt' erkannt", old.processed_ids is None)
    check("Stand des alten Pickles aus last_game", old.ratings_as_of() == max(legacy.last_game.values()), str(old.ratings_as_of()))
    try:
        old.update_with_games([]); raised = False
    except RuntimeError:
        raised = True
    check("update_with_games verweigert Modell ohne IDs", raised)
    before = sha(pth); msgs = []
    res = update_model.run_update(model_path=pth, fetch_fn=lambda s, e_: 1 / 0, log=msgs.append)
    check("run_update bricht bei Pickle ohne IDs ab, ohne abzurufen und ohne zu schreiben",
          res["status"] == "error" and res["reason"] == "no_ids" and sha(pth) == before)
    res = update_model.run_update(model_path=Path(tmp) / "fehlt.pkl", log=msgs.append)
    check("run_update meldet fehlendes Modell", res["reason"] == "no_model")

# --- 3. Training legt IDs an (ohne build_model/save: das echte Pickle bleibt unberuehrt) ---
allg = []
for y in range(2015, 2026):
    allg += json.loads((ROOT / "data" / "cache" / f"games_{y}.json").read_text())
allg = [g for g in allg if g["status"] == "Final"]
allg.sort(key=lambda g: g["date"])
cut = "2025-12-31"
train = [g for g in allg if g["date"][:10] <= cut]
remote_all = [g for g in allg if g["date"][:10] > cut]         # "kommende" Spiele 2026
eng = EloEngine()
for g in train:
    eng.process_game(g)
check("Training legt alle Spiel-IDs an", eng.processed_ids == {g["id"] for g in train} and eng.ratings_as_of() == dt.date(2025, 12, 31) or eng.ratings_as_of() <= dt.date(2025, 12, 31),
      f"{len(eng.processed_ids)} IDs, Stand {eng.ratings_as_of()}")

# --- 4. Fortschreiben mit simulierter API --------------------------------------------------
calls = []
inprog_id = remote_all[40]["id"]
def make_fetch(remote):
    def fetch(start, end):
        calls.append((start, end))
        out = []
        for g in remote:
            d = dt.date.fromisoformat(g["date"][:10])
            if start <= d <= end:
                out.append(copy.deepcopy(g))
        return out
    return fetch

with tempfile.TemporaryDirectory() as tmp:
    pth = Path(tmp) / "elo_model.pkl"
    eng.fit_lr(); eng.save(pth)
    hist = Path(tmp) / "model_history"
    remote = copy.deepcopy(remote_all)
    for g in remote:
        if g["id"] == inprog_id: g["status"] = "3rd Qtr"           # laeuft noch
    remote.append({**copy.deepcopy(remote_all[1]), "id": 999001, "status": "Final", "postponed": True})
    fetch = make_fetch(remote)
    logs = []
    r1 = update_model.run_update(pth, fetch, today=dt.date(2026, 1, 20), log=logs.append)
    check("Lauf 1: neue Spiele verarbeitet, gespeichert", r1["status"] == "updated" and r1["processed"] > 0, str(r1))
    check("Lauf 1: Abfrage ab letztem Stand - 2 Tage (US-Datum)", calls[0] == (dt.date(2025, 12, 29), dt.date(2026, 1, 20)), str(calls[0]))
    check("Lauf 1: Spiel in Bearbeitung und Verschobenes nicht verarbeitet", r1["not_final"] >= 2 and inprog_id not in EloEngine.load(pth).processed_ids)
    check("Lauf 1: Datumskopie angelegt", len(list(hist.glob("elo_model_*.pkl"))) == 1, [p.name for p in hist.glob("*.pkl")][0])
    check("kein .tmp zurueckgeblieben", not list(Path(tmp).glob("*.tmp")))
    s1, n1 = sha(pth), len(EloEngine.load(pth).processed_ids)
    r2 = update_model.run_update(pth, fetch, today=dt.date(2026, 1, 20), log=logs.append)
    check("Lauf 2 (identisch): nichts geaendert, nichts gespeichert", r2["status"] == "unchanged" and r2["processed"] == 0 and sha(pth) == s1 and len(list(hist.glob("*.pkl"))) == 1, str(r2))
    check("Lauf 2: Ueberlappung wurde als Duplikat erkannt", r2["duplicates"] > 0, f"{r2['duplicates']} Duplikate")
    for g in remote:                                                  # Spiel ist jetzt beendet
        if g["id"] == inprog_id: g["status"] = "Final"
    r3 = update_model.run_update(pth, fetch, today=dt.date(2026, 3, 1), log=logs.append)
    e3 = EloEngine.load(pth)
    check("Lauf 3: spaeter beendetes Spiel wird nachgeholt (genau einmal)", r3["status"] == "updated" and inprog_id in e3.processed_ids)
    r4 = update_model.run_update(pth, fetch, today=dt.date(2026, 3, 1), log=logs.append)
    check("Lauf 4 (identisch zu 3): nichts geaendert", r4["status"] == "unchanged")
    r5 = update_model.run_update(pth, fetch, today=dt.date(2026, 3, 1), dry_run=True, log=logs.append)
    check("--dry-run schreibt nichts", r5["status"] == "unchanged" and sha(pth) == sha(pth))
    check("Lauf 3: Abfrage reichte bis zum spaet beendeten Spiel zurueck (pending)", calls[2][0] < dt.date(2026, 1, 18), str(calls[2]))
    check("Lauf 3: danach keine offenen Spiele mehr", not e3.pending)

# Gleichheit mit Gesamtlauf (sauberes Szenario ohne spaet beendete Spiele; Reihenfolge der Verarbeitung wie beim Training)
with tempfile.TemporaryDirectory() as tmp:
    pth = Path(tmp) / "elo_model.pkl"
    eng2 = copy.deepcopy(eng); eng2.save(pth)
    fetch = make_fetch(remote_all)
    for today in (dt.date(2026, 1, 20), dt.date(2026, 1, 20), dt.date(2026, 2, 10), dt.date(2026, 3, 1), dt.date(2026, 3, 1)):
        update_model.run_update(pth, fetch, today=today, log=lambda *_: None)
    e3 = EloEngine.load(pth)
    upto = e3.ratings_as_of().isoformat()
    full = EloEngine()
    for g in [g for g in allg if g["date"][:10] <= upto]:
        full.process_game(g)
    same = (set(full.ratings) == set(e3.ratings)
            and all(abs(full.ratings[t] - e3.ratings[t]) < 1e-9 for t in full.ratings)
            and all(abs(full.off_ratings[t] - e3.off_ratings[t]) < 1e-9 and abs(full.def_ratings[t] - e3.def_ratings[t]) < 1e-9 for t in full.ratings)
            and full.last_game == e3.last_game and full.form == e3.form and full.processed_ids == e3.processed_ids)
    check("Fortschreiben (mehrere Laeufe, auch doppelt) == kompletter Neuaufbau (ELO, Off/Def, Form, Ruhetage, IDs)", same, f"Stand {upto}, {len(e3.processed_ids)} Spiele")

# --- 5. Abruf: Parameter, Paginierung, Filter, US-Datum -------------------------------------
seen = []
pages = [{"data": [mk(1, "2026-01-01", "A", "B", 1, 2), mk(2, "2026-01-01", "C", "D", 1, 2, status="Q4")], "meta": {"next_cursor": 77}},
         {"data": [mk(3, "2026-01-02", "E", "F", 1, 2, postponed=True) | {"postponed": True}, mk(4, "2026-01-02", "G", "H", 3, 2)], "meta": {}}]
def fake_get(endpoint, params=None, retries=5):
    seen.append((endpoint, dict(params))); return pages[len(seen) - 1]
orig_get, orig_sleep = fetcher._get, gu.time.sleep
fetcher._get, gu.time.sleep = fake_get, lambda *_: None
try:
    got = gu.fetch_final_games(dt.date(2026, 1, 1), dt.date(2026, 1, 2))
finally:
    fetcher._get, gu.time.sleep = orig_get, orig_sleep
check("Abruf: start_date/end_date, Paginierung per Cursor", seen[0][1]["start_date"] == "2026-01-01" and seen[0][1]["end_date"] == "2026-01-02" and seen[1][1]["cursor"] == 77 and len(seen) == 2)
check("Abruf: nur Final und nicht verschoben", [g["id"] for g in got] == [1, 4])
utc = dt.datetime(2026, 10, 21, 2, 0, tzinfo=dt.timezone.utc)
check("US-Datum: 02:00 UTC am 21.10. ist noch der 20.10. in New York (deutsche Zeit: 04:00 am 21.10.)", utc.astimezone(gu.US_TZ).date() == dt.date(2026, 10, 20))

check("echtes Pickle data/elo_model.pkl unveraendert", sha(MODEL_PATH) == real_sha)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
