"""Sperrdatei fuer den Betano-Abruf (flock, Muster wie record_live.InstanceLock): nie zwei Betano-Laeufe gleichzeitig (Automatik und Handabruf).

Die Datei liegt neben data/automation.log (folgt NBAEDGE_AUTOMATION_LOG), nicht in data/tracking.
"""
from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path

from data import automation_log as alog


def betano_lock_path() -> Path:
    return alog.log_path().with_name("betano_auto.lock")


class FileLock:
    """Nicht blockierend (timeout=0) oder mit Wartezeit. acquire() -> True/False; release() ist idempotent. Als Kontext: with FileLock(p) as l: l.held."""

    def __init__(self, path: Path | None = None, timeout: float = 0.0):
        self.path = Path(path) if path else betano_lock_path()
        self.timeout = timeout
        self._fh = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    return False
                time.sleep(0.2)
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh:
            try:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


def is_locked(path: Path) -> bool:
    """True, wenn ein anderer Prozess die Sperrdatei haelt (nur Lesen/Probieren, legt nichts an)."""
    p = Path(path)
    if not p.exists():
        return False
    with open(p, "r") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
    return False
