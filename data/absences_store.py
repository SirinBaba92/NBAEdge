"""
Manuelle Ausfall-Auswahl je Spiel und Tag (Spieler-Tab, Stufe 4): "fehlt" und "fraglich" aus dem Kader. Nur Logik, kein Netz.

Datei: data/tracking/absences.json (Ordner ueber NBAEDGE_TRACKING_DIR); sie ist NICHT in .gitignore und damit Teil von "nbabackup" (git add -A).
  {"version": 1, "format": "nbaedge-absences", "updated_at": "...",
   "days": {"<US-Spieltag>": {"<game_key>": {"out": {"<person_id>": {"name", "team", "set_at"}}, "doubtful": {...}, "updated_at",
                                              "history": [{"at", "out": [person_id, ...], "doubtful": [person_id, ...]}]}}}}
- Die Auswahl eines Spiels wird als Ganzes ersetzt (set_absences); ein Spieler kann nicht gleichzeitig "fehlt" und "fraglich" sein ("fehlt" gewinnt NICHT: Fehler).
- Schreiben: Temp-Datei + fsync + os.replace (atomar), Sperre gegen gleichzeitiges Schreiben (Thread + flock auf absences.json.lock). Beschaedigte Datei wird NIE ueberschrieben
  (Sicherungskopie absences.corrupt-<Pruefsumme>.json, Fehler AbsencesError).
Aenderungen sind jederzeit moeglich (auch nach dem Anpfiff): es sind nur Hinweise fuer die Neuberechnung, keine Wetten.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

from data import pre_match_store as store

VERSION = 1
FORMAT = "nbaedge-absences"
_lock = threading.RLock()


class AbsencesError(Exception):
    """Datei nicht lesbar/schreibbar (z. B. beschaedigt); die bestehende Datei bleibt unveraendert."""


def store_path() -> Path:
    return store.tracking_dir() / "absences.json"


def _empty() -> dict:
    return {"version": VERSION, "format": FORMAT, "updated_at": None, "days": {}}


def _parse(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or d.get("format") != FORMAT or not isinstance(d.get("days"), dict):
        raise ValueError("Struktur")
    for games in d["days"].values():
        if not isinstance(games, dict) or any(not isinstance(g, dict) for g in games.values()):
            raise ValueError("Struktur")
    return d


def load() -> dict:
    """Aktueller Stand (leer, wenn die Datei fehlt). Beschaedigt oder zu neu: leere Struktur mit Feld 'error'; die Datei wird nicht veraendert."""
    path = store_path()
    if not path.exists():
        return _empty()
    try:
        d = _parse(path)
    except Exception:
        e = _empty()
        e["error"] = "Die Datei absences.json ist nicht lesbar (beschädigt). Es wird nichts überschrieben."
        return e
    if int(d.get("version", 0) or 0) > VERSION:
        e = _empty()
        e["error"] = "Die Datei absences.json stammt aus einer neueren Programmversion."
        return e
    return d


def load_error() -> str | None:
    return load().get("error")


def get(game_key: str) -> dict:
    """{'out': {person_id (int): {...}}, 'doubtful': {...}, 'updated_at'} eines Spiels (leer, wenn nichts eingetragen ist)."""
    g = (load()["days"].get(game_key.split("|", 1)[0]) or {}).get(game_key) or {}
    conv = lambda m: {int(k): copy.deepcopy(v) for k, v in (m or {}).items()}
    return {"out": conv(g.get("out")), "doubtful": conv(g.get("doubtful")), "updated_at": g.get("updated_at")}


class _WriteLock:
    def __enter__(self):
        _lock.acquire()
        try:
            p = store.tracking_dir() / "absences.json.lock"
            p.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(p, "a+")
            deadline = time.monotonic() + 10.0
            while True:
                try:
                    fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        self._fh.close()
                        raise AbsencesError("Die Ausfall-Datei wird gerade von einem anderen Vorgang geschrieben. Bitte gleich noch einmal versuchen.")
                    time.sleep(0.01)
        except BaseException:
            _lock.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
        finally:
            _lock.release()


def _load_for_write() -> dict:
    path = store_path()
    if not path.exists():
        return _empty()
    try:
        d = _parse(path)
    except Exception:
        try:
            raw = path.read_bytes()
            backup = path.with_name(f"{path.stem}.corrupt-{hashlib.sha1(raw).hexdigest()[:10]}{path.suffix}")
            if not backup.exists():
                shutil.copyfile(path, backup)
        except OSError as e:
            raise AbsencesError("Die Datei absences.json ist beschädigt und konnte nicht gesichert werden; es wurde nichts geändert.") from e
        raise AbsencesError(f"Die Datei absences.json ist beschädigt. Sicherungskopie: {backup.name}. Es wurde nichts geändert; bitte Datei prüfen oder verschieben.")
    if int(d.get("version", 0) or 0) > VERSION:
        raise AbsencesError("Die Datei absences.json stammt aus einer neueren Programmversion; es wurde nichts geändert.")
    return d


def set_absences(game_key: str, out: list[dict], doubtful: list[dict], now: float | None = None) -> dict:
    """Auswahl eines Spiels ersetzen. out/doubtful: [{'person_id', 'name', 'team'}]. Rueckgabe {'status': 'saved'|'unchanged', 'absences': get(...)}.
    Wirft ValueError (Spieler in beiden Listen, ungueltige Nummer) oder AbsencesError (Datei)."""
    now = now if now is not None else time.time()
    ids_out, ids_dbt = {int(p["person_id"]) for p in out}, {int(p["person_id"]) for p in doubtful}
    if any(i <= 0 for i in ids_out | ids_dbt):
        raise ValueError("Ungültige Spieler-Nummer.")
    if ids_out & ids_dbt:
        raise ValueError("Ein Spieler kann nicht gleichzeitig „fehlt“ und „fraglich“ sein.")
    stamp = store.iso_now(now)
    day = game_key.split("|", 1)[0]
    with _WriteLock():
        data = _load_for_write()
        game = data["days"].setdefault(day, {}).setdefault(game_key, {"out": {}, "doubtful": {}, "updated_at": None, "history": []})
        if {int(k) for k in game["out"]} == ids_out and {int(k) for k in game["doubtful"]} == ids_dbt:
            return {"status": "unchanged", "absences": get(game_key)}
        old_out, old_dbt = game.get("out") or {}, game.get("doubtful") or {}
        mk = lambda players, old: {str(int(p["person_id"])): {"name": p["name"], "team": p.get("team"), "set_at": (old.get(str(int(p["person_id"]))) or {}).get("set_at", stamp)} for p in players}
        game["out"], game["doubtful"] = mk(out, old_out), mk(doubtful, old_dbt)
        game["updated_at"] = stamp
        game.setdefault("history", []).append({"at": stamp, "out": sorted(ids_out), "doubtful": sorted(ids_dbt)})
        data["updated_at"] = stamp
        try:
            store._atomic_write(store_path(), data)
        except Exception as e:
            raise AbsencesError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
    return {"status": "saved", "absences": get(game_key)}
