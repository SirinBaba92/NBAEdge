"""
Kaderliste fuer die Spielerauswahl im Tab "Pre-Match Eingabe" (Markt "Spielerpunkte").

Quelle: nba_api PlayerIndex (stats.nba.com), EIN Abruf fuer alle Spieler (Saison aus dem Datum abgeleitet), Timeout 30 s, hoechstens ein Versuch.
Datei: data/rosters.json (einfaches JSON, keine Keys)
  {"version": 1, "format": "nbaedge-rosters", "fetched_at": "<ISO mit Versatz>", "source": "nba_api.PlayerIndex", "season": "2026-27", "abrufe": 1,
   "teams": {"<TEAM_CITY TEAM_NAME>": [{"person_id", "name", "position", "jersey", "team_id", "team_abbreviation"}, ...]}}
Der Abruf laeuft NIE beim Start oder bei einem Rerun der App, nur ueber refresh() (Skript fetch_rosters.py und Knopf "Kader aktualisieren").
Geschrieben wird erst nach vollstaendigem Erfolg (Temp-Datei, fsync, os.replace); bei jedem Fehler bleibt die alte Datei unveraendert.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

VERSION = 1
FORMAT = "nbaedge-rosters"
SOURCE = "nba_api.PlayerIndex"
TIMEOUT_SECONDS = 30
STALE_DAYS = 7
VERY_STALE_DAYS = 14
ROOT = Path(__file__).resolve().parent.parent
_EXTRA_FOLD = str.maketrans({"đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ı": "i"})


class RosterError(Exception):
    """Kader konnte nicht geladen/gespeichert werden; str(e) ist eine kurze deutsche Meldung (alte Datei bleibt unveraendert)."""


def rosters_path() -> Path:
    return Path(os.environ.get("NBAEDGE_ROSTERS") or ROOT / "data" / "rosters.json")


def season_string(today: date | None = None) -> str:
    """NBA-Saison '2026-27' aus dem Datum (ab Oktober die neue Saison), passend zu data.fetcher.current_season."""
    today = today or date.today()
    start = today.year if today.month >= 10 else today.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


# ------------------------------------------------------------------------------ Namen
def strip_accents(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "").translate(_EXTRA_FOLD))
    return "".join(c for c in t if not unicodedata.combining(c))


def normalize_name(text: str) -> str:
    """Vergleichsform: ohne Akzente, klein, ohne Satzzeichen, einfache Leerzeichen ('Nikola Jokić' -> 'nikola jokic', 'Jr.' -> 'jr')."""
    t = strip_accents(text).lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def search_text(name: str) -> str:
    """Zusatz fuer das Label der Auswahlliste: der normalisierte Name, nur wenn er sich vom Namen unterscheidet (Akzente), sonst ''.
    So findet die Suche (Eintippen zum Filtern) 'Jokic' auch 'Nikola Jokić'."""
    plain = strip_accents(name)
    return "" if plain == name else plain


# ------------------------------------------------------------------------------ Datei lesen/schreiben
def build(index: dict, fetched_at: str, season: str) -> dict:
    """Baut die Dateistruktur aus der Rohantwort von PlayerIndex (get_dict()). Wirft RosterError, wenn sie unvollstaendig ist."""
    try:
        rs = index["resultSets"][0]
        headers = rs["headers"]
        rows = [dict(zip(headers, r)) for r in rs["rowSet"]]
    except Exception as e:
        raise RosterError("Die Antwort von stats.nba.com hat ein unerwartetes Format.") from e
    teams: dict[str, list] = {}
    for r in rows:
        if not r.get("TEAM_ID"):
            continue                                    # ohne Team (Free Agents) nicht aufnehmen
        team = f'{r.get("TEAM_CITY") or ""} {r.get("TEAM_NAME") or ""}'.strip()
        name = f'{r.get("PLAYER_FIRST_NAME") or ""} {r.get("PLAYER_LAST_NAME") or ""}'.strip()
        if not team or not name or r.get("PERSON_ID") is None:
            continue
        teams.setdefault(team, []).append({"person_id": int(r["PERSON_ID"]), "name": name, "position": r.get("POSITION") or "",
                                           "jersey": str(r.get("JERSEY_NUMBER") or ""), "team_id": int(r["TEAM_ID"]),
                                           "team_abbreviation": r.get("TEAM_ABBREVIATION") or ""})
    if len(teams) < 30 or sum(len(v) for v in teams.values()) < 300:
        raise RosterError(f"Die Antwort ist unvollständig ({len(teams)} Teams, {sum(len(v) for v in teams.values())} Spieler); die alte Datei bleibt unverändert.")
    for v in teams.values():
        v.sort(key=lambda p: normalize_name(p["name"]))
    return {"version": VERSION, "format": FORMAT, "fetched_at": fetched_at, "source": SOURCE, "season": season, "abrufe": 1,
            "teams": dict(sorted(teams.items()))}


def write(data: dict) -> None:
    path = rosters_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise RosterError("Die Kaderdatei konnte nicht geschrieben werden; die alte Datei bleibt unverändert.") from e


def load(now: float | None = None) -> dict:
    """Liest die Kaderdatei (nie ein Abruf). Rueckgabe: {'status': 'ok'|'missing'|'corrupt', 'teams': {...}, 'fetched_at', 'age_days', 'season', 'message'}.
    Fehlt eine Datei oder ist sie defekt, gibt es keine Exception."""
    now = now if now is not None else time.time()
    path = rosters_path()
    if not path.exists():
        return {"status": "missing", "teams": {}, "fetched_at": None, "age_days": None, "season": None, "message": "Keine Kaderdatei. Bitte 'Kader aktualisieren' drücken."}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        teams = d["teams"]
        if not isinstance(teams, dict) or not teams:
            raise ValueError("teams")
        for plist in teams.values():
            for p in plist:
                int(p["person_id"]); str(p["name"])
        fetched = datetime.fromisoformat(d["fetched_at"]).timestamp()
    except Exception:
        return {"status": "corrupt", "teams": {}, "fetched_at": None, "age_days": None, "season": None,
                "message": "Die Kaderdatei ist nicht lesbar. Bitte 'Kader aktualisieren' drücken (die defekte Datei wird dabei ersetzt)."}
    return {"status": "ok", "teams": teams, "fetched_at": d["fetched_at"], "age_days": max(0.0, (now - fetched) / 86400), "season": d.get("season"), "message": ""}


def age_notice(info: dict) -> tuple[str, str] | None:
    """(Stufe, Text) fuer den Hinweis zum Alter: 'warn' ab 7 Tagen, 'strong' ab 14 Tagen; None bei frischer Datei."""
    age = info.get("age_days")
    if info.get("status") != "ok" or age is None or age < STALE_DAYS:
        return None
    days = int(age)
    if age >= VERY_STALE_DAYS:
        return "strong", f"Die Kaderdatei ist {days} Tage alt (Stand {info['fetched_at'][:10]}). Trades und Neuzugänge fehlen sehr wahrscheinlich: bitte 'Kader aktualisieren' drücken."
    return "warn", f"Die Kaderdatei ist {days} Tage alt (Stand {info['fetched_at'][:10]}). Neuzugänge können fehlen: 'Kader aktualisieren' drücken."


def game_players(info: dict, away: str, home: str) -> tuple[list[dict], list[str]]:
    """Spieler der beiden Teams eines Spiels: erst Gast, dann Heim, je alphabetisch (normalisiert). Rueckgabe (Spieler, fehlende Teams).
    Jeder Spieler bekommt 'team' (Vollname) und 'side' ('away'/'home')."""
    out, missing = [], []
    for side, name in (("away", away), ("home", home)):
        plist = info.get("teams", {}).get(name)
        if not plist:
            missing.append(name)
            continue
        for p in sorted(plist, key=lambda p: normalize_name(p["name"])):
            out.append({**p, "team": name, "side": side})
    return out, missing


def player_label(p: dict) -> str:
    """'Name · Position · #Trikot · Kuerzel' (+ ' · Jokic' bei Akzenten, damit die Suche ohne Akzente findet)."""
    parts = [p["name"], p.get("position") or "–", f'#{p["jersey"]}' if p.get("jersey") else "#–", p.get("team_abbreviation") or ""]
    alias = search_text(p["name"])
    if alias:
        parts.append(alias)
    return " · ".join(x for x in parts if x)


# ------------------------------------------------------------------------------ Abruf
def fetch_playerindex(season: str, timeout: int = TIMEOUT_SECONDS) -> dict:
    """EIN Abruf an stats.nba.com (nba_api PlayerIndex). Kein Wiederholen. Tests ersetzen diese Funktion (kein echtes Netz)."""
    from nba_api.stats.endpoints import PlayerIndex
    return PlayerIndex(season=season, timeout=timeout).get_dict()


def _friendly(e: Exception) -> str:
    n = type(e).__name__.lower()
    msg = str(e).lower()
    if "timeout" in n or "timed out" in msg or "timeout" in msg:
        return f"Zeitüberschreitung ({TIMEOUT_SECONDS} s) bei stats.nba.com. Die alte Kaderdatei bleibt unverändert; bitte später erneut versuchen."
    if "403" in msg or "401" in msg or "forbidden" in msg or "denied" in msg:
        return "stats.nba.com hat den Abruf abgelehnt (Blockade). Die alte Kaderdatei bleibt unverändert."
    if "connection" in n or "connection" in msg or "resolve" in msg or "network" in msg:
        return "Keine Verbindung zu stats.nba.com. Die alte Kaderdatei bleibt unverändert."
    if "json" in n or "decode" in n:
        return "Unerwartete Antwort von stats.nba.com (kein gültiges JSON). Die alte Kaderdatei bleibt unverändert."
    return f"Abruf an stats.nba.com fehlgeschlagen ({type(e).__name__}). Die alte Kaderdatei bleibt unverändert."


def refresh(progress=None, now: float | None = None, fetcher=None) -> dict:
    """Aktualisiert data/rosters.json mit genau EINEM Abruf. progress(fraction, text) ist optional. Rueckgabe: die geschriebene Struktur.
    Wirft RosterError mit deutscher Meldung; die bestehende Datei bleibt dann unveraendert."""
    fetcher = fetcher or fetch_playerindex
    now = now if now is not None else time.time()
    season = season_string(datetime.fromtimestamp(now).date())
    if progress:
        progress(0.1, f"Abruf an stats.nba.com (Saison {season}) …")
    try:
        raw = fetcher(season, TIMEOUT_SECONDS)
    except RosterError:
        raise
    except Exception as e:
        raise RosterError(_friendly(e)) from e
    if progress:
        progress(0.7, "Antwort wird geprüft …")
    data = build(raw, datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"), season)
    write(data)
    if progress:
        progress(1.0, f"Fertig: {sum(len(v) for v in data['teams'].values())} Spieler, {len(data['teams'])} Teams.")
    return data
