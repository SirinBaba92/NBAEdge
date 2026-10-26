"""
Beim Betano-Import nicht zugeordnete Spielernamen je Spiel (nur Hinweis, keine Rechnung): data/tracking/betano_skipped.json (Ordner ueber NBAEDGE_TRACKING_DIR).
  {"version": 1, "format": "nbaedge-betano-skipped", "days": {"<US-Spieltag>": {"<game_key>": {"home", "away", "names": [...], "at": "<ISO>"}}}}
Ein neuer Lauf ueberschreibt den Eintrag seines Spiels. Geschrieben wird atomar (Temp-Datei + os.replace); eine defekte Datei wird nicht ueberschrieben (record wirft dann, der Aufrufer faengt es ab).
"""
from __future__ import annotations

import json
import time

from data import pre_match_store as store

FORMAT = "nbaedge-betano-skipped"


def path():
    return store.tracking_dir() / "betano_skipped.json"


def _load(strict: bool = False) -> dict:
    p = path()
    if not p.exists():
        return {"version": 1, "format": FORMAT, "days": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("format") != FORMAT or not isinstance(d.get("days"), dict):
            raise ValueError("Struktur")
        return d
    except Exception:
        if strict:
            raise
        return {"version": 1, "format": FORMAT, "days": {}}


def record(game_key: str, home: str, away: str, names: list[str], now: float | None = None) -> None:
    """Uebersprungene Namen eines Spiels merken (auch eine leere Liste: ersetzt einen frueheren Eintrag)."""
    d = _load(strict=True)
    day = game_key.split("|", 1)[0]
    d["days"].setdefault(day, {})[game_key] = {"home": home, "away": away, "names": list(names), "at": store.iso_now(now if now is not None else time.time())}
    store._atomic_write(path(), d)


def get(game_key: str) -> dict | None:
    return (_load()["days"].get(game_key.split("|", 1)[0]) or {}).get(game_key)


def caption(game_key: str) -> str | None:
    """'Nicht zugeordnet bei Betano: A, B (Stand HH:MM)' oder None, wenn es nichts gibt."""
    e = get(game_key)
    if not e or not e.get("names"):
        return None
    stamp = str(e.get("at") or "")[11:16]
    return "Nicht zugeordnet bei Betano: " + ", ".join(e["names"]) + (f" (Stand {stamp})" if stamp else "")
