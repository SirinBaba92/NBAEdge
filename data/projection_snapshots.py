"""
Schnappschuesse der Projektion VOR dem Anpfiff (Grundlage fuer den spaeteren Backtest aller Maerkte).

Datei: data/tracking/projection_snapshots.json  (Ordner ueber NBAEDGE_TRACKING_DIR wie pre_match_entries.json; keine Keys, kein Netz)
  {"version": 1, "format": "nbaedge-projection-snapshots", "updated_at": "...",
   "games": {"<Spieldatum US>|<Anpfiff UTC>|<Heim>|<Gast>": {          # Schluessel = pre_match_store.game_key
       "game_date", "start_utc", "home", "away",
       "versions": [{"saved_at", "hash",
                     "model": {"file_mtime", "file_size", "sha1", "ratings_as_of"},
                     "projection": {"exp_spread", "exp_total", "home_score", "away_score", "home_win_prob", "away_win_prob", "market_total", "market_spread"},
                     "markets": {"spread"|"total"|"team_total_away"|"team_total_home": {"line", "source", "bookmaker", "line_at", "cache_line", "warn"}},
                     "tables": {"spread"|"total"|"team_away"|"team_home": {"kind", "source", "favorite", "derived", "note",
                                  "rows": [{"line", "p_left", "p_right", "predicted", "is_main"}]}},
                     "sigmas": {...}, "pre_match_ref": {"entry_key", "<markt>": "<updated_at der Eingabe>"} | null}],
       "card": {...}       # Anzeigefelder der letzten Version (nur damit ein beendetes Spiel danach noch als Karte erscheint)
       "result": {"home_points", "away_points", "recorded_at", "source"} | null}}}
Eine neue Version entsteht nur, wenn sich der Inhalt (Hash ohne Zeitstempel) gegenueber der letzten Version aendert und das Spiel noch nicht
begonnen hat (unbekannter Anpfiff gilt als begonnen). Ab dem Anpfiff gibt es keine neuen Versionen: die letzte Version ist die gueltige ("final").
Die Spielzahl der Saison je Team ist aus dem Modell nicht ableitbar (die Form-Liste mischt Saisons) und wird deshalb nicht gespeichert.

Schreiben wie pre_match_store: Temp-Datei, fsync, os.replace; Tageskopie in history/; bei Versionsaenderung byte-genaue Sicherung der alten Datei.
"""
from __future__ import annotations

import hashlib
import json
import numbers
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from data import pre_match_store as store

SNAP_VERSION = 1
FORMAT = "nbaedge-projection-snapshots"
FINAL_CARD_HOURS = 24            # beendete Spiele mit Ergebnis erscheinen noch so lange als Karte (aus dem Schnappschuss)
_lock = threading.RLock()
_cache: dict = {"sig": None, "data": None}
_model_cache: dict = {}


class SnapshotError(Exception):
    """Datei nicht lesbar/schreibbar; die bestehende Datei bleibt unveraendert."""


def snapshot_path() -> Path:
    return store.tracking_dir() / "projection_snapshots.json"


def _empty() -> dict:
    return {"version": SNAP_VERSION, "format": FORMAT, "updated_at": None, "games": {}}


def load() -> dict:
    """Liest die Datei (leer, wenn sie fehlt; mtime-Zwischenspeicher, damit Reruns nicht jedes Mal parsen). Defekt: leere Struktur mit 'error'.
    Der Rueckgabewert darf nicht veraendert werden."""
    path = snapshot_path()
    try:
        st = path.stat()
    except OSError:
        return _empty()
    sig = (str(path), st.st_mtime_ns, st.st_size)
    if _cache["sig"] == sig:
        return _cache["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("games"), dict):
            raise ValueError("Struktur")
    except Exception:
        data = _empty()
        data["error"] = "Die Datei projection_snapshots.json ist nicht lesbar."
    _cache["sig"], _cache["data"] = sig, data
    return data


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _daily_copy(now: float | None) -> None:
    try:
        day = datetime.fromtimestamp(now if now is not None else time.time()).astimezone().strftime("%Y-%m-%d")
        dest = store.history_dir() / f"projection_snapshots_{day}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(snapshot_path(), tmp)
        os.replace(tmp, dest)
    except Exception:
        pass            # die Tageskopie darf das Speichern nie scheitern lassen


def _load_for_write() -> dict:
    """Stand fuer eine Aenderung (tiefe Kopie). Defekte Datei: als .corrupt-<Zeit> sichern, neu beginnen. Aeltere Version: byte-genau sichern, dann heben."""
    path = snapshot_path()
    if not path.exists():
        return _empty()
    data = load()
    if data.get("error"):
        backup = path.with_name(f"{path.stem}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}")
        try:
            shutil.copyfile(path, backup)
        except OSError as e:
            raise SnapshotError("Defekte Datei konnte nicht gesichert werden; es wurde nichts geändert.") from e
        d = _empty()
        d["recovered_from_corrupt"] = backup.name
        return d
    data = json.loads(json.dumps(data))
    version = int(data.get("version", 0) or 0)
    if version > SNAP_VERSION:
        raise SnapshotError("Die Datei stammt aus einer neueren Programmversion; es wurde nichts geändert.")
    if version < SNAP_VERSION:
        backup = store.history_dir() / f"{path.stem}.v{version}_vor_Upgrade_{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}"
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, backup)
        except OSError as e:
            raise SnapshotError("Die alte Dateiversion konnte nicht gesichert werden; es wurde nichts geändert.") from e
        data["version"] = SNAP_VERSION
        data["upgraded_from_version"] = version
        data["upgrade_backup"] = backup.name
    return data


def _write(data: dict, now: float | None) -> None:
    data["updated_at"] = store.iso_now(now)
    try:
        _atomic_write(snapshot_path(), data)
    except Exception as e:
        raise SnapshotError(f"Schnappschuss-Datei konnte nicht geschrieben werden ({type(e).__name__}).") from e
    _cache["sig"] = None
    _daily_copy(now)


# ------------------------------------------------------------------------------ Inhalt
def model_info(engine=None, model_path: Path | None = None) -> dict:
    """Modellstand: Aenderungszeit/Groesse/SHA-1 der Pickle-Datei (SHA-1 nur bei geaenderter Datei neu berechnet) und 'Ratings bis'."""
    from models.elo import MODEL_PATH
    path = Path(model_path or MODEL_PATH)
    info = {"file_mtime": None, "file_size": None, "sha1": None, "ratings_as_of": None}
    try:
        st = path.stat()
        info["file_mtime"] = datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds")
        info["file_size"] = st.st_size
        sig = (str(path), st.st_mtime_ns, st.st_size)
        if _model_cache.get("sig") != sig:
            _model_cache.update(sig=sig, sha1=hashlib.sha1(path.read_bytes()).hexdigest())
        info["sha1"] = _model_cache["sha1"]
    except OSError:
        pass
    try:
        if engine is not None:
            as_of = engine.ratings_as_of()
            info["ratings_as_of"] = str(as_of) if as_of is not None else None
    except Exception:
        pass
    return info


def _num(v):
    return None if v is None else round(float(v), 4)


def _iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts)).astimezone().isoformat(timespec="seconds") if ts else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _jsonable(v):
    if isinstance(v, (str, bool)) or v is None:
        return v
    if isinstance(v, numbers.Integral):
        return int(v)
    if isinstance(v, numbers.Real):
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items() if not str(k).startswith("_")}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return None


def build_snapshot(proj: dict, entry: dict | None, model: dict) -> dict | None:
    """Inhalt eines Schnappschusses (ohne Zeitstempel 'saved_at' und 'hash'). None ohne Marktlinien-Struktur (Mock-Projektion)."""
    from engine import line_probabilities as lp
    ml = proj.get("market_lines")
    if ml is None:
        return None
    tables = lp.build_line_tables(proj, entry) or {}
    markets = {}
    for m, res in ml.items():
        markets[m] = {"line": _num(res.get("line")), "source": res.get("source"), "bookmaker": res.get("bookmaker") or None,
                      "line_at": _iso(res.get("at")) if not res.get("at_iso") else res.get("at_iso"),
                      "cache_line": _num(res.get("cache_line")), "warn": bool(res.get("warn"))}
    out_tables = {}
    for k, t in tables.items():
        out_tables[k] = {"kind": t["kind"], "source": t.get("source"), "favorite": t.get("favorite"), "derived": bool(t.get("derived", False)), "note": t.get("note"),
                         "rows": [{"line": r["line"], "p_left": r["p_left"], "p_right": r["p_right"], "predicted": r["predicted"], "is_main": bool(r["is_main"])} for r in t["rows"]]}
    ref = None
    if entry:
        ref = {"entry_key": store.game_key(entry.get("game_date"), entry.get("start_utc"), entry.get("home"), entry.get("away"))}
        for name, mk in (entry.get("markets") or {}).items():
            if isinstance(mk, dict) and mk.get("updated_at"):
                ref[name] = mk["updated_at"]
    return {
        "model": model,
        "projection": {"exp_spread": _num(proj.get("exp_spread")), "exp_total": _num(proj.get("exp_total")), "home_score": _num(proj.get("home_score")),
                       "away_score": _num(proj.get("away_score")), "home_win_prob": _num(proj.get("home_win_prob")), "away_win_prob": _num(proj.get("away_win_prob")),
                       "market_total": _num(proj.get("market_total")), "market_spread": _num(proj.get("market_spread"))},
        "markets": markets, "tables": out_tables,
        "sigmas": {"spread": lp.SPREAD_SIGMA, "total": lp.TOTAL_SIGMA, "team_total": lp.TEAM_TOTAL_SIGMA},
        "pre_match_ref": ref,
    }


def content_hash(content: dict) -> str:
    return hashlib.sha1(json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


def final_version(game: dict) -> dict | None:
    """Die gueltige (letzte) Version vor dem Anpfiff."""
    v = game.get("versions") or []
    return v[-1] if v else None


# ------------------------------------------------------------------------------ Schreiben
def record_snapshots(projections: list[dict], entries: dict | None, engine=None, now: float | None = None, model: dict | None = None) -> dict:
    """Je Projektion eines NOCH NICHT BEGONNENEN Spiels eine neue Version, wenn sich der Inhalt geaendert hat. Eine Datei-Schreibung je Aufruf.
    Rueckgabe {'new_games', 'new_versions', 'unchanged', 'locked'}. Wirft SnapshotError, wenn die Datei nicht geschrieben werden konnte.
    Kein Netz. Aufrufbar aus der App (jeder Rerun) und aus Skripten."""
    now = now if now is not None else time.time()
    stats = {"new_games": 0, "new_versions": 0, "unchanged": 0, "locked": 0}
    todo = []
    entries = entries or {}
    for proj in projections:
        inp = proj.get("_line_inputs") or {}
        start = inp.get("game_start") or proj.get("game_start")
        if not store.is_editable(start, now):
            stats["locked"] += 1
            continue
        key = inp.get("entry_key") or store.game_key(proj.get("game_date"), start, proj["home_team"], proj["away_team"])
        todo.append((key, proj, start))
    if not todo:
        return stats
    model = model if model is not None else model_info(engine)
    current = load().get("games", {})
    pending = []
    for key, proj, start in todo:
        entry = entries.get(key)
        content = build_snapshot(proj, entry, model)
        if content is None:
            continue
        h = content_hash(content)
        last = final_version(current.get(key) or {})
        if last is not None and last.get("hash") == h:
            stats["unchanged"] += 1
            continue
        pending.append((key, proj, start, content, h))
    if not pending:
        return stats
    with _lock:
        data = _load_for_write()
        games = data.setdefault("games", {})
        stamp = store.iso_now(now)
        for key, proj, start, content, h in pending:
            g = games.get(key)
            if g is None:
                g = games[key] = {"game_date": proj.get("game_date"), "start_utc": store.normalize_start(start), "home": proj["home_team"], "away": proj["away_team"],
                                  "versions": [], "card": None, "result": None}
                stats["new_games"] += 1
            if g["versions"] and g["versions"][-1].get("hash") == h:      # zwischenzeitlich schon geschrieben (parallele Sitzung)
                continue
            if g.get("result") is not None or not store.is_editable(g.get("start_utc"), now):
                continue
            g["versions"].append({"saved_at": stamp, "hash": h, **content})
            g["card"] = _jsonable({k: v for k, v in proj.items() if k != "_line_inputs"})
            stats["new_versions"] += 1
        if stats["new_versions"] or stats["new_games"]:
            _write(data, now)
    return stats


def record_results(games: list[dict], now: float | None = None, source: str = "update_model") -> dict:
    """Endergebnisse beendeter Spiele (BallDontLie-Spieldicts, die der Aufrufer ohnehin hat) in vorhandene Schnappschuesse eintragen.
    Nur Spiele mit Schnappschuss und ohne Ergebnis. Rueckgabe {'written': n, 'no_snapshot': n}. Wirft SnapshotError beim Schreibfehler."""
    now = now if now is not None else time.time()
    out = {"written": 0, "no_snapshot": 0}
    current = load().get("games", {})
    found = []
    for g in games:
        if not (g.get("status") == "Final" and not g.get("postponed") and g.get("home_team_score") is not None and g.get("visitor_team_score") is not None):
            continue
        try:
            key = store.game_key(g.get("date"), g.get("datetime"), g["home_team"]["full_name"], g["visitor_team"]["full_name"])
        except (KeyError, TypeError):
            continue
        snap = current.get(key)
        if snap is None:
            out["no_snapshot"] += 1
            continue
        if snap.get("result") is None:
            found.append((key, int(g["home_team_score"]), int(g["visitor_team_score"])))
    if not found:
        return out
    with _lock:
        data = _load_for_write()
        for key, hp, ap in found:
            snap = data.get("games", {}).get(key)
            if snap is not None and snap.get("result") is None:
                snap["result"] = {"home_points": hp, "away_points": ap, "recorded_at": store.iso_now(now), "source": source}
                out["written"] += 1
        if out["written"]:
            _write(data, now)
    return out


def fill_results_from_upcoming_cache(now: float | None = None) -> dict:
    """Ergebnisse aus dem lokalen BallDontLie-Zwischenspeicher (data/upcoming_cache.json) nachtragen. Kein Abruf, nur Datei lesen."""
    try:
        from data.fetcher import _upcoming_cache_path
        games = json.loads(Path(_upcoming_cache_path()).read_text()).get("games", [])
    except Exception:
        return {"written": 0, "no_snapshot": 0}
    if not any(s.get("result") is None for s in load().get("games", {}).values()):
        return {"written": 0, "no_snapshot": 0}
    return record_results(games, now=now, source="upcoming_cache")


def finished_cards(now: float | None = None, hours: float = FINAL_CARD_HOURS, exclude: set | None = None) -> list[dict]:
    """Beendete Spiele mit Ergebnis (in den letzten `hours` Stunden eingetragen) fuer die Anzeige: {'key', 'card', 'tables', 'result'} aus der letzten Version."""
    now = now if now is not None else time.time()
    out = []
    for key, g in load().get("games", {}).items():
        res, ver = g.get("result"), final_version(g)
        if not res or not ver or not g.get("card") or (exclude and key in exclude):
            continue
        ts = store.parse_utc(res.get("recorded_at"))
        if ts is None or now - ts > hours * 3600:
            continue
        out.append({"key": key, "card": g["card"], "tables": ver.get("tables"), "result": res})
    return sorted(out, key=lambda x: x["key"])
