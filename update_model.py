"""
Taegliches Fortschreiben der ELO-Ratings, ohne Neutraining.

  cd ~/Desktop/NBAEdge && source venv/bin/activate && python update_model.py

- laedt beendete Spiele (status == "Final", nicht verschoben) seit dem letzten Stand
  (US-Datum, 2 Tage Ueberlappung, Deduplizierung nach Spiel-ID),
- verarbeitet nur neue Spiele mit EloEngine.process_game,
- speichert das Modell atomar und legt eine Datumskopie in data/model_history/ an.
Zweimal hintereinander gestartet aendert sich nichts: ohne neue Spiele wird nichts geschrieben.
Voraussetzung: das Modell wurde mit dem aktuellen train.py trainiert (enthaelt die Spiel-IDs).

  python update_model.py --dry-run     zeigt nur, was passieren wuerde (laedt Spiele, speichert nichts)
"""
import os
import sys

sys.path.insert(0, ".")

from models.elo import EloEngine, MODEL_PATH


def _store_results(games, stats, log, dry_run, results_fn=None) -> None:
    """Endergebnisse beendeter Spiele in vorhandene Schnappschuesse eintragen (data/projection_snapshots.py; nur die schon abgerufenen Spiele, kein weiterer
    Abruf). Ein Fehler hier darf das Modell-Update nie verhindern: er wird gemeldet und im Protokoll als WARN vermerkt."""
    if dry_run:
        return
    try:
        if results_fn is None:
            from data.projection_snapshots import record_results as results_fn
        res = results_fn(games)
        stats["results_written"] = res.get("written", 0)
        if res.get("written"):
            log(f"Ergebnisse in Schnappschuesse eingetragen: {res['written']}")
    except Exception as e:
        stats["results_error"] = f"{type(e).__name__}: {e}"
        log(f"Warnung: Ergebnisse konnten nicht in die Schnappschuss-Datei geschrieben werden ({type(e).__name__}). Das Modell-Update ist davon nicht betroffen.")


def run_update(model_path=None, fetch_fn=None, today=None, dry_run=False, log=print, results_fn=None) -> dict:
    """Kern des Updates (testbar: fetch_fn und model_path sind austauschbar).
    Rueckgabe: Statistik mit 'status' in {'updated', 'unchanged', 'dry_run', 'error'}."""
    path = model_path or MODEL_PATH
    if not EloEngine.exists(path):
        log(f"Kein Modell unter {path}. Bitte zuerst `python train.py` ausfuehren.")
        return {"status": "error", "reason": "no_model"}
    engine = EloEngine.load(path)
    if not engine.processed_ids:
        log("Das gespeicherte Modell enthaelt keine Spiel-IDs (trainiert vor dem Fortschreiben). "
            "Bitte einmal `python train.py` ausfuehren, danach funktioniert update_model.py.")
        return {"status": "error", "reason": "no_ids"}

    if fetch_fn is None:
        from data.game_updates import fetch_final_games
        fetch_fn = fetch_final_games
    if today is None:
        from data.game_updates import us_today
        today = us_today()

    start = engine.next_fetch_start(overlap_days=2)
    before = engine.ratings_as_of()
    log(f"Stand vorher: Ratings bis {before} | Abfrage {start} bis {today} (US-Datum)")
    games = fetch_fn(start, today)
    stats = engine.update_with_games(games)
    stats["start"], stats["end"] = start, today
    log(f"Empfangen: {stats['received']} | nicht beendet/verschoben: {stats['not_final']} | "
        f"bereits verarbeitet: {stats['duplicates']} | neu verarbeitet: {stats['processed']}")

    if stats["processed"] == 0:
        log("Keine neuen Spiele. Modell bleibt unveraendert (nichts gespeichert).")
        _store_results(games, stats, log, dry_run, results_fn)
        stats["status"] = "unchanged"
        return stats
    if dry_run:
        log("--dry-run: nichts gespeichert.")
        stats["status"] = "dry_run"
        return stats

    engine.save(path, dated_copy=True)
    log(f"Stand nachher: Ratings bis {engine.ratings_as_of()}. "
        "Laufende App neu starten (Ctrl+C, dann `streamlit run app.py`), damit sie das Modell neu laedt.")
    _store_results(games, stats, log, dry_run, results_fn)
    stats["status"] = "updated"
    stats["as_of"] = engine.ratings_as_of()
    return stats


def _record(result: str, detail: str, dry_run: bool) -> None:
    """Ergebnis in data/automation.log (auch bei Fehlern und bei 'keine neuen Spiele'); Probelauf wird nicht protokolliert."""
    if not dry_run:
        from data import automation_log
        automation_log.log_event("update_model", result, detail)


def main(argv) -> int:
    dry_run = "--dry-run" in argv
    try:
        if not os.getenv("BALLDONTLIE_API_KEY"):
            from dotenv import load_dotenv
            load_dotenv()
        if not os.getenv("BALLDONTLIE_API_KEY"):
            print("BALLDONTLIE_API_KEY fehlt (.env im Projektordner).")
            _record("ERROR", "BALLDONTLIE_API_KEY fehlt (.env)", dry_run)
            return 2
        res = run_update(dry_run=dry_run)
    except Exception as e:                    # nie ohne Spur abbrechen (der Text wird beim Protokollieren bereinigt)
        print(f"Fehler: {type(e).__name__}")
        _record("ERROR", f"{type(e).__name__}: {e}", dry_run)
        return 1
    status = res["status"]
    warn = f"; Ergebnisse nicht gespeichert: {res['results_error']}" if res.get("results_error") else ""
    note = f", {res['results_written']} Ergebnisse eingetragen" if res.get("results_written") else ""
    flag = "WARN" if warn else "OK"
    if status == "updated":
        _record(flag, f"{res['processed']} neue Spiele, Ratings bis {res.get('as_of')}{note}{warn}", dry_run)
    elif status == "unchanged":
        _record(flag, f"keine neuen Spiele ({res['received']} empfangen, {res['duplicates']} bereits verarbeitet){note}{warn}", dry_run)
    elif status == "error":
        reasons = {"no_model": "kein Modell vorhanden (python train.py)", "no_ids": "Modell ohne Spiel-IDs (python train.py)"}
        _record("ERROR", reasons.get(res.get("reason"), str(res.get("reason"))), dry_run)
    return 0 if status in ("updated", "unchanged", "dry_run") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
