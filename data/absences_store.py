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
    res = {"out": conv(g.get("out")), "doubtful": conv(g.get("doubtful")), "updated_at": g.get("updated_at")}
    if g.get("auto"):
        res["auto"] = copy.deepcopy(g["auto"])               # {'source', 'fetched_at', 'unmatched'} des letzten automatischen Abrufs
    return res


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
        def mk(players, old):                                    # bleibt ein automatischer Eintrag in derselben Liste, behaelt er seine Kennzeichnung; sonst gilt er als von Hand
            res = {}
            for p in players:
                pid = str(int(p["person_id"]))
                o = old.get(pid) or {}
                res[pid] = {"name": p["name"], "team": p.get("team"), "set_at": o.get("set_at", stamp), **({"source": o["source"], "fetched_at": o.get("fetched_at")} if o.get("source") else {})}
            return res
        game["out"], game["doubtful"] = mk(out, old_out), mk(doubtful, old_dbt)
        removed = {k for m in (old_out, old_dbt) for k, v in m.items() if v.get("source")} - {str(i) for i in ids_out | ids_dbt}
        if removed:                                              # von Hand entfernte automatische Eintraege: der naechste Abruf traegt sie nicht wieder ein
            game["suppressed"] = sorted(set(game.get("suppressed") or []) | removed)
        game["updated_at"] = stamp
        game.setdefault("history", []).append({"at": stamp, "out": sorted(ids_out), "doubtful": sorted(ids_dbt)})
        data["updated_at"] = stamp
        try:
            store._atomic_write(store_path(), data)
        except Exception as e:
            raise AbsencesError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
    return {"status": "saved", "absences": get(game_key)}


def apply_auto(game_key: str, out: list[dict], doubtful: list[dict], unmatched: list[str], now: float | None = None, source: str = "espn") -> dict:
    """Automatische Eintraege (z. B. ESPN) eines Spiels ersetzen: nur Eintraege mit dieser Kennzeichnung werden entfernt/neu gesetzt. Von Hand gesetzte (ohne Kennzeichnung) haben Vorrang
    und bleiben unveraendert; ebenso Spieler, die von Hand aus einer automatischen Liste entfernt wurden ('suppressed'). out/doubtful: [{'person_id', 'name', 'team'}].
    Merkt Abrufzeit und nicht zugeordnete Namen in game['auto']. Ohne Eintraege und ohne Hinweise wird kein neues Spiel angelegt. Rueckgabe {'out': Anzahl, 'doubtful': Anzahl} automatischer Eintraege."""
    now = now if now is not None else time.time()
    stamp = store.iso_now(now)
    with _WriteLock():
        data = _load_for_write()
        day = game_key.split("|", 1)[0]
        game = (data["days"].get(day) or {}).get(game_key)
        if game is None:
            if not (out or doubtful or unmatched):
                return {"out": 0, "doubtful": 0}
            game = data["days"].setdefault(day, {}).setdefault(game_key, {"out": {}, "doubtful": {}, "updated_at": None, "history": []})
        manual = {k for m in (game["out"], game["doubtful"]) for k, v in m.items() if not v.get("source")} | {str(k) for k in game.get("suppressed") or []}
        before = ({k for k, v in game["out"].items() if v.get("source")}, {k for k, v in game["doubtful"].items() if v.get("source")})
        new = []
        for lst in (out, doubtful):
            new.append({str(int(p["person_id"])): {"name": p["name"], "team": p.get("team"), "set_at": stamp, "source": source, "fetched_at": stamp}
                        for p in lst if str(int(p["person_id"])) not in manual})
        both = new[0].keys() & new[1].keys()                     # ESPN nennt einen Spieler nur einmal; im Zweifel gilt "fehlt"
        for m, n in zip((game["out"], game["doubtful"]), new):
            old_auto = {k: v for k, v in m.items() if v.get("source") == source}
            for k in old_auto:
                del m[k]
            for k, v in n.items():
                m[k] = {**v, "set_at": old_auto.get(k, {}).get("set_at", v["set_at"])}
        for k in both:
            game["doubtful"].pop(k, None)
        after = ({k for k, v in game["out"].items() if v.get("source")}, {k for k, v in game["doubtful"].items() if v.get("source")})
        game["auto"] = {"source": source, "fetched_at": stamp, "unmatched": list(unmatched)}
        if before != after:
            game["updated_at"] = data["updated_at"] = stamp
            game.setdefault("history", []).append({"at": stamp, "out": sorted(int(k) for k in game["out"]), "doubtful": sorted(int(k) for k in game["doubtful"]), "source": source})
        try:
            store._atomic_write(store_path(), data)
        except Exception as e:
            raise AbsencesError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
    return {"out": len(after[0]), "doubtful": len(after[1])}
