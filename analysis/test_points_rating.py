"""Tests fuer models/points_rating.py mit simulierten bzw. gecachten Daten (keine API-Calls,
Schreiben nur in ein temporaeres Verzeichnis). Aufruf: venv/bin/python analysis/test_points_rating.py"""
import copy, datetime, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import load_games
from models.points_rating import PointsRatingModel, season_for_date, VERSION
from models.elo import EloEngine

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

games = load_games()
full = PointsRatingModel(); full.update_with_games(games)
check("Aufbau aus Cache: 14168 Spiele verarbeitet", len(full.processed_ids) == 14168, str(len(full.processed_ids)))
check("Saison im Modell = 2025, letztes Datum 2026-06-13", full.season == 2025 and str(full.last_date) == "2026-06-13")

# --- Saisonuebernahme beim ersten Zugriff in neuer Saison ----------------------
m = copy.deepcopy(full)
before = dict(m.ratings)
p1 = m.predict("New York Knicks", "Philadelphia 76ers", datetime.date(2026, 10, 20))
r40 = m.params["r"]
check("Saisonwechsel beim ersten Zugriff angewendet (Saison 2026)", m.season == 2026 and p1["rating_season"] == 2026)
check("Ratings um Faktor (1-r) verkleinert", abs(m.ratings["New York Knicks"] - before["New York Knicks"] * (1 - r40)) < 1e-9)
p2 = m.predict("New York Knicks", "Philadelphia 76ers", datetime.date(2026, 10, 21))
check("zweiter Zugriff wendet nichts doppelt an", p1["spread"] == p2["spread"])
m2 = copy.deepcopy(full)
pp = m2.predict("New York Knicks", "Philadelphia 76ers", datetime.date(2026, 3, 1))
check("Prognose fuer Datum in alter Saison veraendert nichts", m2.season == 2025 and m2.ratings["New York Knicks"] == full.ratings["New York Knicks"])
check("US-Datum: 30.09. gehoert zur alten, 01.10. zur neuen Saison", season_for_date(datetime.date(2026, 9, 30)) == 2025 and season_for_date(datetime.date(2026, 10, 1)) == 2026)
check("Wahrscheinlichkeiten in [0.03, 0.97]", all(0.03 <= m.predict(a, b, datetime.date(2026, 10, 20))["home_win_prob"] <= 0.97
      for a in list(m.ratings)[:10] for b in list(m.ratings)[:10] if a != b))

# --- Fortschreiben: Dedupe, Final-Filter, Reihenfolge, Gleichheit mit Gesamtlauf ----
cut = [i for i, g in enumerate(games) if g["season"] <= 2024][-1] + 1
part = PointsRatingModel(); part.update_with_games(games[:cut])
new = games[cut:]
bad = [dict(new[0], id=-1, status="3rd Qtr"), dict(new[1], id=-2, postponed=True),
       dict(new[2], id=-3, status="7:00 PM ET", home_team_score=None, visitor_team_score=None)]
batch1 = list(reversed(new[:500])) + bad          # falsche Reihenfolge + unfertige Spiele
batch2 = new[400:]                                 # ueberlappt mit batch1 (Duplikate)
s1 = part.update_with_games(batch1); s2 = part.update_with_games(batch2); s3 = part.update_with_games(batch2)
check("unfertige/verschobene Spiele werden ignoriert", s1["not_final"] == 3 and all(i not in part.processed_ids for i in (-1, -2, -3)), str(s1))
check("Duplikate zwischen Batches erkannt", s2["duplicates"] == 100 and s3["processed"] == 0, f"{s2} / {s3}")
same = all(abs(part.ratings[t] - full.ratings[t]) < 1e-9 for t in full.ratings) and part.season == full.season and part.processed_ids == full.processed_ids
check("inkrementelles Fortschreiben == Gesamtlauf (Ratings, Saison, IDs)", same)
check("naechstes Abfragedatum = letztes Datum - 2 Tage", str(full.next_fetch_start()) == "2026-06-11", str(full.next_fetch_start()))

# --- Speichern/Laden mit Datumskopie, Versionsfeld ---------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "points_rating_test.pkl"
    full.save(path)
    copies = list((Path(tmp) / "model_history").glob("*.pkl"))
    check("Datumskopie angelegt", len(copies) == 1 and "2026-06-13" in copies[0].name, copies[0].name if copies else "")
    back = PointsRatingModel.load(path)
    check("Laden: gleiche Ratings, Version im Pickle", back.version == VERSION and back.ratings["New York Knicks"] == full.ratings["New York Knicks"])
    # falsches/altes Pickle wird abgelehnt (altes Modell wird nur gelesen)
    try:
        PointsRatingModel.load(Path(__file__).resolve().parent.parent / "data" / "elo_model.pkl"); rej = False
    except ValueError:
        rej = True
    check("altes ELO-Pickle wird als falsche Version abgelehnt", rej)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
