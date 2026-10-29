"""
Play-by-Play-Archiv: laedt das Play-by-Play aller regulaeren Spiele der Saisons 2023-24, 2024-25 und 2025-26 von cdn.nba.com nach.
NEU und getrennt vom Recorder; aendert keine Projektdatei und liest nur die lokalen Spielerdaten (kein Spielplan-Abruf).

Spiel-IDs (nicht geraten): die verschiedenen game_id aus den Spielerdaten in data/cache (NBA.com leaguegamelog, Regular Season, je 1230 Spiele):
    2025-26  data/cache/player_games_2025-26.json          2023-24 / 2024-25  data/cache/backtest_player_games_<Saison>.json
Abruf: wie data/nba_live.py (NBA_PLAYBYPLAY_URL, requests, NBA_HEADERS), aber ohne dessen Cache; ein Abruf alle 2 Sekunden, nie parallel.
Ablage: <Ordner>/<Saison>/<spiel_id>.json.gz (die unveraenderte Antwort, gepackt); vorhandene Dateien werden uebersprungen (Wiederaufnahme nach Abbruch).
Protokoll: <Ordner>/protokoll.txt (Zeit, Spiel, Status), <Ordner>/fehlschlaege.txt (Spiele mit Fehlern), <Ordner>/bericht.txt (Bericht je Saison).

Start (Standard-Ordner /Users/baranalturk/NBAEdge_pbp):
    venv/bin/python analysis/fetch_pbp_archive.py
Test mit wenigen Abrufen:  venv/bin/python analysis/fetch_pbp_archive.py --out /tmp/pbp_test --seasons 2025-26 --limit 3

Fehler: 403/429 = sofort Stopp (Exit-Code 3, kein Wiederholen). Timeout/5xx/Netz: hoechstens 2 Wiederholungen mit 10 s Pause, dann Eintrag in fehlschlaege.txt und weiter.
Andere Antworten (z. B. 404) oder eine ungueltige Datei: kein Wiederholen, Eintrag in fehlschlaege.txt.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT = Path.home() / "NBAEdge_pbp"
SEASONS = ("2023-24", "2024-25", "2025-26")
PAUSE_SECONDS = 2.0
RETRY_PAUSE_SECONDS = 10.0
MAX_RETRIES = 2
TIMEOUT_SECONDS = 10
PROGRESS_EVERY = 50
SOURCES = {"2023-24": "backtest_player_games_2023-24.json", "2024-25": "backtest_player_games_2024-25.json", "2025-26": "player_games_2025-26.json"}


class Blocked(Exception):
    """HTTP 403 oder 429: sofort aufhoeren."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


def cache_dir() -> Path:
    return Path(os.environ.get("NBAEDGE_PLAYER_CACHE_DIR") or ROOT / "data" / "cache")


def game_ids(season: str, cdir: Path | None = None) -> list[str]:
    """Alle verschiedenen Regular-Season-IDs ('002...') einer Saison aus den Spielerdaten, sortiert."""
    path = (cdir or cache_dir()) / SOURCES[season]
    rows = json.loads(path.read_text(encoding="utf-8")).get("rows", [])
    return sorted({str(r["game_id"]) for r in rows if str(r.get("game_id", "")).startswith("002")})


def parse_response(body: bytes, game_id: str) -> int:
    """Prueft die Antwort: gueltiges JSON, Spiel-ID stimmt, Aktionen vorhanden. Gibt die Zahl der Aktionen zurueck, sonst ValueError."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("kein gueltiges JSON")
    game = data.get("game") if isinstance(data, dict) else None
    if not isinstance(game, dict):
        raise ValueError("Feld 'game' fehlt")
    if str(game.get("gameId")) != game_id:
        raise ValueError(f"Spiel-ID stimmt nicht ({game.get('gameId')})")
    actions = game.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("keine Aktionen")
    return len(actions)


def target_path(out: Path, season: str, game_id: str) -> Path:
    return out / season / f"{game_id}.json.gz"


def save_gz(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(gzip.compress(body))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def http_fetch(game_id: str) -> tuple[int | None, bytes]:
    """Ein einzelner Abruf (requests, Kopfzeilen und URL wie data/nba_live.py). (None, b'') bei Netzfehler/Timeout."""
    import requests
    from data.nba_live import NBA_HEADERS, NBA_PLAYBYPLAY_URL
    try:
        r = requests.get(NBA_PLAYBYPLAY_URL.format(game_id=game_id), headers=NBA_HEADERS, timeout=TIMEOUT_SECONDS)
        return r.status_code, r.content
    except requests.exceptions.RequestException:
        return None, b""


class Archive:
    def __init__(self, out: Path, fetch=http_fetch, sleep=time.sleep, now=time.time, write=print):
        self.out, self.fetch, self.sleep, self.now, self.write = Path(out), fetch, sleep, now, write
        self.last_call = None
        self.calls = 0

    def log(self, game_id: str, status: str) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        with open(self.out / "protokoll.txt", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.now()))}\t{game_id}\t{status}\n")

    def _wait(self, seconds: float) -> None:
        if self.last_call is not None:
            rest = seconds - (self.now() - self.last_call)
            if rest > 0:
                self.sleep(rest)

    def get(self, game_id: str) -> tuple[bytes | None, str]:
        """(Antwort, Status). Wirft Blocked bei 403/429. Antwort None bei Fehlschlag; Status beschreibt ihn."""
        status, body = None, b""
        for attempt in range(MAX_RETRIES + 1):
            self._wait(RETRY_PAUSE_SECONDS if attempt else PAUSE_SECONDS)
            status, body = self.fetch(game_id)
            self.last_call = self.now()
            self.calls += 1
            if status in (403, 429):
                raise Blocked(status)
            if status == 200:
                return body, "200"
            if status is not None and 400 <= status < 500:      # z. B. 404: Wiederholen hilft nicht
                return None, f"HTTP {status}"
            self.log(game_id, f"Versuch {attempt + 1}: {'Netz/Timeout' if status is None else f'HTTP {status}'}")
        return None, "Netz/Timeout" if status is None else f"HTTP {status}"

    def run(self, seasons=SEASONS, cdir: Path | None = None, limit: int | None = None) -> dict:
        """Gibt {'stopped': None|'gesperrt'|'limit'|'abbruch', 'report': {Saison: {...}}} zurueck."""
        report, stopped, done = {}, None, 0
        for season in seasons:
            ids = game_ids(season, cdir)
            rep = report[season] = {"expected": len(ids), "saved": 0, "fresh": 0, "failed": [], "bytes": 0}
            for gid in ids:
                path = target_path(self.out, season, gid)
                done += 1
                if path.exists() and path.stat().st_size > 0:
                    rep["saved"] += 1
                else:
                    if limit is not None and self.calls >= limit:
                        stopped = "limit"
                        break
                    try:
                        body, status = self.get(gid)
                    except Blocked as e:
                        self.log(gid, f"GESPERRT HTTP {e.status} - Stopp")
                        stopped = "gesperrt"
                        break
                    except KeyboardInterrupt:
                        self.log(gid, "ABBRUCH durch Benutzer")
                        stopped = "abbruch"
                        break
                    if body is not None:
                        try:
                            n = parse_response(body, gid)
                            save_gz(path, body)
                            rep["saved"] += 1
                            rep["fresh"] += 1
                            self.log(gid, f"gespeichert, {n} Aktionen")
                        except ValueError as e:
                            body, status = None, f"ungueltig: {e}"
                    if body is None:
                        rep["failed"].append((gid, status))
                        self.log(gid, f"FEHLSCHLAG {status}")
                        with open(self.out / "fehlschlaege.txt", "a", encoding="utf-8") as f:
                            f.write(f"{season}\t{gid}\t{status}\n")
                if done % PROGRESS_EVERY == 0:
                    self.write(f"[{time.strftime('%H:%M:%S', time.localtime(self.now()))}] {season}: {done} Spiele bearbeitet, {self.calls} Abrufe")
            rep["bytes"] = sum(p.stat().st_size for p in (self.out / season).glob("*.json.gz")) if (self.out / season).exists() else 0
            if stopped:
                break
        return {"stopped": stopped, "report": report}

    def report_text(self, result: dict) -> str:
        lines = []
        for season, r in result["report"].items():
            lines.append(f"{season}: erwartet {r['expected']}, gespeichert {r['saved']} (neu {r['fresh']}), Fehlschläge {len(r['failed'])}, Größe {r['bytes'] / 1e6:.1f} MB")
        msg = {"gesperrt": "GESTOPPT: NBA.com hat den Zugriff abgelehnt (HTTP 403/429). Bitte später (mind. einige Stunden) erneut starten; vorhandene Dateien werden übersprungen.",
               "limit": "Gestoppt wegen --limit (Test).", "abbruch": "Abbruch durch Benutzer. Neu starten setzt fort.", None: "Lauf vollständig durchgelaufen."}[result["stopped"]]
        lines.append(msg)
        return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seasons", nargs="+", default=list(SEASONS), choices=list(SEASONS))
    ap.add_argument("--limit", type=int, default=None, help="hoechstens so viele Abrufe (Test)")
    args = ap.parse_args(argv)
    arc = Archive(Path(args.out))
    result = arc.run(args.seasons, limit=args.limit)
    text = arc.report_text(result)
    print(text)
    with open(arc.out / "bericht.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return 3 if result["stopped"] == "gesperrt" else 0


if __name__ == "__main__":
    sys.exit(main())
