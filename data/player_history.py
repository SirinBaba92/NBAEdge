"""
Lokaler Spielverlauf der Spieler (Spieler-Tab, Baustein P2): Grundlage fuer Minuten-Prognose, Punkte-Verteilung und Backtest.

Quelle: NBA.com leaguegamelog (nba_api), EIN Abruf je Saison liefert alle Spielerzeilen der Liga (Regular Season). Das Teamergebnis steht nicht in der Antwort und wird
aus der Summe der Spielerpunkte je Team und Spiel abgeleitet (Sieg/Niederlage laut Spalte WL, Differenz = eigene minus gegnerische Punkte).
Ergaenzung beim Lesen (nichts wird dafuer geschrieben): Boxscores des Recorders ~/NBAEdge_live_history/<Tag>/<game_id>/final_box.json.gz fuer Spiele, die in der Liga-Datei
noch fehlen (Doppelte ueber game_id + person_id ausgeschlossen).

Dateien (jederzeit neu ladbar, deshalb nicht im Repository), Ordner data/cache oder NBAEDGE_PLAYER_CACHE_DIR:
  player_games_<Saison>.json   {"version": 1, "format": "nbaedge-player-games", "season", "fetched_at", "source", "rows": [Zeile, ...]}
      Zeile: game_id, date (JJJJ-MM-TT), season, person_id, name, team (Kuerzel), opponent (Kuerzel), home (bool), minutes (Zahl), points, fga, fgm, fta, ftm, fg3a, fg3m,
             fouls, plus_minus, win (bool|None), margin (int|None, Punkte-Differenz des Teams), source ("league" | "recorder")
  player_games_status.json     Zeitpunkt des letzten Versuchs, Fehlerzaehler, Fehlermeldung, naechster erlaubter Abruf
Schreiben immer ueber Temp-Datei + os.replace. Ein Fehler (Netz, Sperre, leere oder kleinere Antwort) aendert nie vorhandene Daten und wirft nie eine Ausnahme nach oben.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from data import rosters

VERSION = 1
FORMAT = "nbaedge-player-games"
SOURCE = "nba_api.LeagueGameLog"
ROOT = Path(__file__).resolve().parent.parent
REFRESH_SECONDS = 3600                 # laufende Saison hoechstens einmal pro Stunde
BACKOFF_START, BACKOFF_MAX = 30, 300   # nach Fehlern: 30, 60, 120, 240, 300 ... Sekunden Pause
TIMEOUT_SECONDS = 60
SEASONS_TO_LOAD = ("2025-26", "2026-27")


# ----------------------------------------------------------------------------- Pfade, Hilfen
def cache_dir() -> Path:
    return Path(os.environ.get("NBAEDGE_PLAYER_CACHE_DIR") or ROOT / "data" / "cache")


def season_path(season: str) -> Path:
    return cache_dir() / f"player_games_{season}.json"


def status_path() -> Path:
    return cache_dir() / "player_games_status.json"


def live_root() -> Path:
    return Path(os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history")


def current_season(today: date | None = None) -> str:
    return rosters.season_string(today)


def season_of_date(day: str) -> str:
    return rosters.season_string(date.fromisoformat(day))


def iso_now(now: float | None = None) -> str:
    return datetime.fromtimestamp(now if now is not None else time.time(), timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def minutes_to_float(value) -> float:
    """Minuten als Zahl: 28 | '28' | '28:30' | 'PT28M30.00S' (Boxscore) -> 28.5. Unlesbar oder leer -> 0.0."""
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else 0.0
    text = str(value).strip()
    m = re.fullmatch(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", text)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) + float(m.group(2) or 0) / 60
    if ":" in text:
        a, _, b = text.partition(":")
        try:
            return float(a) + float(b) / 60
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _num(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


# ----------------------------------------------------------------------------- Liga-Antwort -> Zeilen
def parse_league_log(payload: dict, season: str) -> list[dict]:
    """Antwort von leaguegamelog (resultSets[0] mit headers/rowSet) -> Zeilen im Dateiformat. Wirft ValueError bei unbrauchbarer Struktur."""
    try:
        rs = payload["resultSets"][0]
        head = {h: i for i, h in enumerate(rs["headers"])}
        data = rs["rowSet"]
        need = ("GAME_ID", "GAME_DATE", "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "MATCHUP", "MIN", "PTS")
        if any(k not in head for k in need):
            raise KeyError("Spalten")
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError("unbrauchbare Antwort (Spalten fehlen)") from e
    rows, team_pts = [], {}
    for r in data:
        g = lambda k: r[head[k]] if k in head else None
        matchup = str(g("MATCHUP") or "")
        home = " vs. " in matchup
        opp = re.split(r" vs\. | @ ", matchup)[-1].strip() if matchup else ""
        wl = g("WL")
        row = {"game_id": str(g("GAME_ID")), "date": str(g("GAME_DATE"))[:10], "season": season, "person_id": _num(g("PLAYER_ID")), "name": str(g("PLAYER_NAME") or ""),
               "team": str(g("TEAM_ABBREVIATION") or ""), "opponent": opp, "home": home, "minutes": minutes_to_float(g("MIN")), "points": _num(g("PTS")),
               "fga": _num(g("FGA")), "fgm": _num(g("FGM")), "fta": _num(g("FTA")), "ftm": _num(g("FTM")), "fg3a": _num(g("FG3A")), "fg3m": _num(g("FG3M")),
               "fouls": _num(g("PF")), "plus_minus": _num(g("PLUS_MINUS")), "win": (wl == "W") if wl in ("W", "L") else None, "margin": None, "source": "league"}
        rows.append(row)
        team_pts[(row["game_id"], row["team"])] = team_pts.get((row["game_id"], row["team"]), 0) + row["points"]
    for row in rows:
        mine, theirs = team_pts.get((row["game_id"], row["team"])), team_pts.get((row["game_id"], row["opponent"]))
        if mine is not None and theirs is not None:
            row["margin"] = mine - theirs
            if row["win"] is None:
                row["win"] = row["margin"] > 0
    return rows


def default_fetcher(season: str) -> dict:
    """EIN Abruf bei NBA.com (nba_api), keine Wiederholung. Fehler werden als Ausnahme gemeldet; der Aufrufer faengt sie ab."""
    from nba_api.stats.endpoints import leaguegamelog
    ep = leaguegamelog.LeagueGameLog(season=season, player_or_team_abbreviation="P", season_type_all_star="Regular Season", timeout=TIMEOUT_SECONDS)
    return json.loads(ep.nba_response.get_json())


# ----------------------------------------------------------------------------- Lesen der Dateien
_cache: dict = {}          # (Pfad) -> ((mtime_ns, size), Daten)


def _read_cached(path: Path, loader):
    try:
        st = path.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    try:
        data = loader(path)
    except Exception:
        data = None
    _cache[str(path)] = (key, data)
    return data


def _load_season_file(path: Path) -> dict | None:
    d = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or d.get("format") != FORMAT or not isinstance(d.get("rows"), list):
        raise ValueError("Format")
    return d


def league_file(season: str) -> dict | None:
    return _read_cached(season_path(season), _load_season_file)


def _recorder_games(day_dir: Path):
    for gdir in sorted(p for p in day_dir.iterdir() if p.is_dir()):
        f = gdir / "final_box.json.gz"
        if f.is_file():
            yield gdir.name, f


def recorder_rows(day: str, game_id: str, path: Path) -> list[dict]:
    """Spielerzeilen aus einem final_box (Rohformat NBA.com); Spieler ohne Einsatzzeit entfallen (wie in der Liga-Datei)."""
    game = json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8")).get("game") or {}
    home, away = game.get("homeTeam") or {}, game.get("awayTeam") or {}
    if str(game.get("gameStatus")) != "3" and game.get("gameStatus") != 3:
        return []
    hs, as_ = _num(home.get("score")), _num(away.get("score"))
    out = []
    for side, team, other, mine, theirs in (("home", home, away, hs, as_), ("away", away, home, as_, hs)):
        for p in team.get("players") or []:
            s = p.get("statistics") or {}
            minutes = minutes_to_float(s.get("minutes"))
            if minutes <= 0:
                continue
            out.append({"game_id": str(game_id), "date": day, "season": season_of_date(day), "person_id": _num(p.get("personId")), "name": str(p.get("name") or ""),
                        "team": str(team.get("teamTricode") or ""), "opponent": str(other.get("teamTricode") or ""), "home": side == "home", "minutes": minutes,
                        "points": _num(s.get("points")), "fga": _num(s.get("fieldGoalsAttempted")), "fgm": _num(s.get("fieldGoalsMade")), "fta": _num(s.get("freeThrowsAttempted")),
                        "ftm": _num(s.get("freeThrowsMade")), "fg3a": _num(s.get("threePointersAttempted")), "fg3m": _num(s.get("threePointersMade")),
                        "fouls": _num(s.get("foulsPersonal")), "plus_minus": _num(s.get("plusMinusPoints")), "win": mine > theirs, "margin": mine - theirs, "source": "recorder"})
    return out


def _recorder_season_rows(season: str, known_games: set[str], known_keys: set) -> list[dict]:
    root = live_root()
    out = []
    try:
        days = sorted(p for p in root.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
    except OSError:
        return out
    for day_dir in days:
        if season_of_date(day_dir.name) != season:
            continue
        try:
            games = list(_recorder_games(day_dir))
        except OSError:
            continue
        for gid, f in games:
            if gid in known_games:
                continue
            rows = _read_cached(f, lambda p, d=day_dir.name, g=gid: recorder_rows(d, g, p)) or []
            for r in rows:
                key = (r["game_id"], r["person_id"])
                if key not in known_keys:
                    known_keys.add(key)
                    out.append(r)
    return out


def season_rows(season: str, with_recorder: bool = True) -> list[dict]:
    """Alle Zeilen einer Saison: Liga-Datei plus (nur fehlende Spiele) Recorder-Boxscores. Fehlende Datei -> nur Recorder-Zeilen."""
    d = league_file(season)
    rows = list(d["rows"]) if d else []
    if with_recorder:
        known_games = {r["game_id"] for r in rows}
        known_keys = {(r["game_id"], r["person_id"]) for r in rows}
        rows += _recorder_season_rows(season, known_games, known_keys)
    return rows


def _as_day(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


# ----------------------------------------------------------------------------- Zugriff
def get_player_games(person_id: int, season: str | None = None, n: int | None = None, before_date=None) -> list[dict]:
    """Spiele eines Spielers, neueste zuerst. season=None: alle geladenen Saisons. before_date: Spiele AB diesem Tag sind ausgeschlossen (Stichtag fuer den Backtest)."""
    seasons = [season] if season else list(SEASONS_TO_LOAD)
    cutoff = _as_day(before_date)
    out = []
    for s in seasons:
        out += [r for r in season_rows(s) if r["person_id"] == int(person_id) and (cutoff is None or r["date"] < cutoff)]
    out.sort(key=lambda r: (r["date"], r["game_id"]), reverse=True)
    return out[:n] if n else out


def _avg(rows: list[dict], key: str) -> float | None:
    return sum(r[key] for r in rows) / len(rows) if rows else None


def _block(rows: list[dict]) -> dict:
    return {"games": len(rows), "points": _avg(rows, "points"), "minutes": _avg(rows, "minutes"), "fga": _avg(rows, "fga"), "fta": _avg(rows, "fta")}


def get_player_summary(person_id: int, before_date=None, season: str | None = None) -> dict:
    """Schnitte vor dem Stichtag: Saison (Standard: Saison des Stichtags bzw. die laufende), letzte 5 und letzte 10 Spiele (ueber Saisongrenzen), Minuten-Mittel,
    Punkte pro Minute (Summe Punkte / Summe Minuten), Standardabweichung der Punkte (Stichprobe, ab 2 Spielen), Anzahl Spiele."""
    cutoff = _as_day(before_date)
    season = season or (season_of_date(cutoff) if cutoff else current_season())
    allg = get_player_games(person_id, before_date=before_date)
    sg = [r for r in allg if r["season"] == season]
    pts = [r["points"] for r in sg]
    total_min = sum(r["minutes"] for r in sg)
    std = None
    if len(pts) >= 2:
        mean = sum(pts) / len(pts)
        std = math.sqrt(sum((x - mean) ** 2 for x in pts) / (len(pts) - 1))
    return {"person_id": int(person_id), "season": season, "games": len(sg), "games_total": len(allg),
            "season_avg": _block(sg), "last5": _block(allg[:5]), "last10": _block(allg[:10]),
            "minutes_mean": _avg(sg, "minutes"), "points_per_minute": (sum(pts) / total_min) if total_min > 0 else None, "points_std": std}


def players_for_team(team: str) -> list[dict]:
    """Kader aus data/rosters.json (nie ein Abruf). team: Vollname ('Atlanta Hawks'), Kuerzel ('ATL') oder Spitzname ('Hawks'). Unbekannt oder keine Datei -> []."""
    info = rosters.load()
    wanted = str(team or "").strip().lower()
    for name, plist in (info.get("teams") or {}).items():
        abbr = {str(p.get("team_abbreviation") or "").lower() for p in plist}
        if bool(wanted) and (wanted == name.lower() or name.lower().endswith(" " + wanted) or wanted in abbr):
            return [{**p, "team": name} for p in plist]
    return []


# ----------------------------------------------------------------------------- Abruf und Zustand
def _load_state() -> dict:
    try:
        d = json.loads(status_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        atomic_write_json(status_path(), state)
    except Exception:
        pass


def refresh_season(season: str, fetcher=None, now: float | None = None) -> dict:
    """Ein Abruf fuer eine Saison. Schreibt nur bei Erfolg mit mindestens so vielen Zeilen wie bisher; sonst bleibt die Datei unveraendert. Wirft nie.
    Rueckgabe: {'ok', 'season', 'rows', 'message'}."""
    now = now if now is not None else time.time()
    try:
        payload = (fetcher or default_fetcher)(season)
        rows = parse_league_log(payload, season)
        old = league_file(season)
        if not rows:
            return {"ok": False, "season": season, "rows": len(old["rows"]) if old else 0, "message": "leere Antwort, vorhandene Daten bleiben"}
        if old and len(rows) < len(old["rows"]):
            return {"ok": False, "season": season, "rows": len(old["rows"]), "message": f"Antwort kleiner als der Bestand ({len(rows)} < {len(old['rows'])}), vorhandene Daten bleiben"}
        atomic_write_json(season_path(season), {"version": VERSION, "format": FORMAT, "season": season, "fetched_at": iso_now(now), "source": SOURCE, "rows": rows})
        return {"ok": True, "season": season, "rows": len(rows), "message": ""}
    except Exception as e:
        return {"ok": False, "season": season, "rows": 0, "message": f"{type(e).__name__}: {str(e)[:200]}"}


def refresh_current_season(fetcher=None, now: float | None = None, force: bool = False) -> dict:
    """Aktualisiert die laufende Saison: hoechstens einmal pro Stunde (nach Erfolg), nach Fehlern Pause 30 -> 60 -> ... max. 300 s. Wirft nie.
    Rueckgabe: {'status': 'aktualisiert'|'uebersprungen'|'fehler', 'season', 'message', 'wait_s'}."""
    now = now if now is not None else time.time()
    season = current_season(datetime.fromtimestamp(now).date())
    try:
        st = _load_state()
        next_ok = float(st.get("next_allowed_ts") or 0)
        if not force and now < next_ok:
            return {"status": "uebersprungen", "season": season, "message": "noch nicht wieder erlaubt", "wait_s": int(next_ok - now)}
        res = refresh_season(season, fetcher, now)
        st.update({"last_attempt": iso_now(now), "last_attempt_ts": now, "season": season})
        if res["ok"]:
            st.update({"fail_count": 0, "backoff_s": 0, "last_error": None, "last_success": iso_now(now), "next_allowed_ts": now + REFRESH_SECONDS})
            _save_state(st)
            return {"status": "aktualisiert", "season": season, "message": f"{res['rows']} Zeilen", "wait_s": REFRESH_SECONDS}
        wait = BACKOFF_START if not st.get("backoff_s") else min(BACKOFF_MAX, int(st["backoff_s"]) * 2)
        st.update({"fail_count": int(st.get("fail_count") or 0) + 1, "backoff_s": wait, "last_error": res["message"], "next_allowed_ts": now + wait})
        _save_state(st)
        return {"status": "fehler", "season": season, "message": res["message"], "wait_s": wait}
    except Exception as e:
        return {"status": "fehler", "season": season, "message": f"{type(e).__name__}: {str(e)[:200]}", "wait_s": BACKOFF_START}


def ensure_past_seasons(fetcher=None, now: float | None = None) -> list[dict]:
    """Laedt jede Saison aus SEASONS_TO_LOAD VOR der laufenden einmalig, wenn ihre Datei fehlt (ein Abruf je Saison). Wirft nie."""
    out = []
    cur = current_season(datetime.fromtimestamp(now if now is not None else time.time()).date())
    for s in SEASONS_TO_LOAD:
        if s < cur and league_file(s) is None:
            out.append(refresh_season(s, fetcher, now))
    return out


def player_history_status() -> dict:
    """Stand fuer die Oberflaeche: je Saison Zeitpunkt, Zeilen, Spiele, Spieler (Liga-Datei und Recorder getrennt), dazu Fehler und naechster erlaubter Abruf."""
    seasons = {}
    for s in SEASONS_TO_LOAD:
        d = league_file(s)
        league = d["rows"] if d else []
        rec = [r for r in season_rows(s) if r["source"] == "recorder"]
        every = league + rec
        seasons[s] = {"fetched_at": d.get("fetched_at") if d else None, "rows": len(every), "games": len({r["game_id"] for r in every}),
                      "players": len({r["person_id"] for r in every}), "recorder_games": len({r["game_id"] for r in rec})}
    st = _load_state()
    nxt = float(st.get("next_allowed_ts") or 0)
    return {"seasons": seasons, "last_attempt": st.get("last_attempt"), "last_success": st.get("last_success"), "last_error": st.get("last_error"),
            "fail_count": int(st.get("fail_count") or 0), "next_allowed_in_s": max(0, int(nxt - time.time())) if nxt else 0}
