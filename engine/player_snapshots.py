"""
Prognose-Snapshots der Spieler-Punkte-Prognose (gemeinsame Logik fuer analysis/print_player_forecast.py und den Tab "Spieler"). Kein Netz, schreibt nur den Snapshot
(analysis/results/forecast_snapshots/<Tag>.json, Ordner ueber NBAEDGE_SNAPSHOT_DIR). Ein Snapshot je Spiel wird nur EINMAL geschrieben (Ausnahme: new=True mit Sicherung).
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from data import player_history as ph
from data import pre_match_store as store
from engine import player_forecast as pf

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_VERSION = 1


def snapshot_dir() -> Path:
    return Path(os.environ.get("NBAEDGE_SNAPSHOT_DIR") or ROOT / "analysis" / "results" / "forecast_snapshots")


def _atomic_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def build_snapshot_entry(key: str, entries: dict, res: dict, now: datetime) -> dict:
    """Ein Spiel als Snapshot: Zeitpunkt, Anpfiff-Vermerk, Teamfaktoren, je Spieler Prognose (roh + Teamabgleich, p_ge fuer N = 1..60) und die verwendeten Quoten."""
    start = None
    try:
        start = datetime.fromisoformat(key.split("|")[1].replace("Z", "+00:00"))
    except (IndexError, ValueError):
        pass
    after = bool(start and now >= start)
    stamps = {}
    for b in store.active_player_blocks(entries.get(key)):
        for l in store.player_lines(b):
            stamps[(int(b["person_id"]), l.get("threshold"))] = {"updated_at": l.get("updated_at"), "entered_at": l.get("entered_at")}
    players = []
    for p in res["players"]:
        fc = p["forecast"]
        quotes = [{"milestone": r["milestone"], "odds": r["odds"], "bookmaker": r["bookmaker"], "bookmaker_probability": r["probability"], "bookmaker_percent": r["percent"],
                   **stamps.get((int(p["person_id"]), r["milestone"]), {})} for r in p["rows"]]
        row = {"person_id": p["person_id"], "name": p["name"], "team": p["team"], "team_abbreviation": p.get("team_abbreviation"), "ok": fc["ok"], "reason": fc.get("reason"),
               "quality": fc.get("quality"), "warnings": (fc.get("warnings") or []) + p["warnings"] + ([fc["team_note"]] if fc.get("team_note") else []), "quotes": quotes}
        if fc["ok"]:
            row.update(minutes=fc["minutes"], minutes_adjusted=fc["minutes_adjusted"], expected_points_raw=fc["expected_points_raw"], expected_points_adjusted=fc["expected_points_adjusted"],
                       p_ge_raw={str(n): v for n, v in fc["p_ge_raw"].items()}, p_ge_adjusted={str(n): v for n, v in fc["p_ge_adjusted"].items()}, games_used=fc["games_used"])
        players.append(row)
    return {"game_key": key, "created_at": now.astimezone().isoformat(timespec="seconds"), "start_utc": key.split("|")[1] if "|" in key else None, "created_after_start": after,
            "note": "nach Anpfiff erstellt, Daten nur bis Vortag" if after else "vor Anpfiff erstellt", "status": pf.UNVERIFIED, "context": res["context"],
            "teams": res["teams"], "history": data_stand(), "players": players}


def save_snapshot(day: str, key: str, entry: dict, new: bool = False) -> str:
    """Schreibt den Snapshot eines Spiels in <Tag>.json. Existiert er schon: nicht ueberschreiben ('vorhanden'); mit new=True wird die alte Datei mit Zeitstempel gesichert."""
    path = snapshot_dir() / f"{day}.json"
    data = {"version": SNAPSHOT_VERSION, "day": day, "games": {}}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise RuntimeError(f"{path} ist nicht lesbar, nichts überschrieben")
        if key in data["games"]:
            if not new:
                return "vorhanden"
            shutil.copy2(path, path.with_name(f"{day}.json.bak-{datetime.now():%Y%m%d-%H%M%S}"))
    data["games"][key] = entry
    _atomic_json(path, data)
    return "neu geschrieben" if new else "geschrieben"




def data_stand() -> str:
    st = ph.player_history_status()
    parts = [f"{s}: {v['games']} Spiele, {v['players']} Spieler, Stand {(v['fetched_at'] or 'fehlt')[:16].replace('T', ' ')} UTC" for s, v in st["seasons"].items()]
    return "Spielverlauf: " + " | ".join(parts) + (f" | letzter Fehler: {st['last_error']}" if st.get("last_error") else "")



def create_for_game(key: str, entries: dict, new: bool = False, now: datetime | None = None) -> tuple[str, dict]:
    """Prognose rechnen und als Snapshot speichern (einmalig). Rueckgabe (Ergebnis von save_snapshot: 'geschrieben'/'vorhanden'/'neu geschrieben', Snapshot-Eintrag)."""
    now = now or datetime.now(timezone.utc)
    res = pf.forecast_game_players(key, entries)
    entry = build_snapshot_entry(key, entries, res, now)
    return save_snapshot(key.split("|", 1)[0], key, entry, new), entry
