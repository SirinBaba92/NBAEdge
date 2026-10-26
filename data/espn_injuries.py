"""
Injury Report von ESPN automatisch in die Ausfall-Felder eintragen (data/absences_store.py, Datei data/tracking/absences.json).

Quelle: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries (oeffentlich, kein Schluessel). Abruf wie bei der ESPN-Ersatzquelle des Live-Feeds
(requests, User-Agent "NBAEdge/1.0 (persoenliche Nutzung)", Zeitlimit data.live_feed.TIMEOUT_SECONDS), genau EIN Abruf je Lauf, kein Wiederholen.
- Zuordnung nur zu Spielern der Spiele, die noch nicht begonnen haben (Kader aus data/rosters.json): erst exakter Name, dann normalisiert (ohne Akzente/Punkte, ohne Jr./Sr./II/III/IV).
  Nur eindeutige Treffer; alles andere steht in der Liste "nicht zugeordnet" und wird NICHT geraten.
- "Out" (auch "Out For Season") = fehlt; "Questionable", "Doubtful", "Day-To-Day", "Probable" = fraglich (nur Hinweis). Andere Status werden ignoriert.
- Eintrag mit Kennzeichnung source="espn" und Abrufzeit; von Hand gesetzte Eintraege haben Vorrang und werden nie ueberschrieben (data/absences_store.apply_auto).
Einzeln starten: venv/bin/python -m data.espn_injuries
"""
from __future__ import annotations

import re
import sys
import time

from data import absences_store as ab
from data import pre_match_store as store
from data import rosters
from data.rosters import SUFFIXES, match_player, short_key      # gemeinsamer Namensabgleich (data/rosters.py), hier weiter unter diesen Namen erreichbar

ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
USER_AGENT = "NBAEdge/1.0 (persoenliche Nutzung)"
OUT_STATUS = {"out", "out for season"}
DOUBTFUL_STATUS = {"questionable", "doubtful", "day to day", "probable"}
TEAM_ALIASES = {"los angeles clippers": "la clippers"}
UNREACHABLE = "ESPN-Verletzungen: nicht erreichbar"


def fetch() -> dict:
    """Ein Abruf bei ESPN. Wirft bei jedem Fehler (Netz, HTTP, JSON)."""
    import requests
    from data.live_feed import TIMEOUT_SECONDS
    r = requests.get(ESPN_INJURIES_URL, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not isinstance(data.get("injuries"), list):
        raise ValueError("Format")
    return data


def team_key(name: str) -> str:
    n = rosters.normalize_name(name)
    return TEAM_ALIASES.get(n, n)


def classify(status: str) -> str | None:
    """'out' | 'doubtful' | None (unbekannter Status wird ignoriert)."""
    s = re.sub(r"[^a-z]+", " ", str(status or "").lower()).strip()
    return "out" if s in OUT_STATUS else "doubtful" if s in DOUBTFUL_STATUS else None


def parse(data: dict) -> list[dict]:
    """[{'name', 'team', 'kind' ('out'|'doubtful'), 'status'}] aus der ESPN-Antwort (Eintraege mit unbekanntem Status entfallen)."""
    out = []
    for t in data.get("injuries") or []:
        for i in t.get("injuries") or []:
            kind = classify(i.get("status"))
            name = (i.get("athlete") or {}).get("displayName")
            if kind and name:
                out.append({"name": name, "team": t.get("displayName") or "", "kind": kind, "status": i.get("status")})
    return out


def upcoming_games(now: float) -> list[dict]:
    """Noch nicht begonnene Spiele mit Spielerquoten/Eintrag: [{'key', 'home', 'away'}]."""
    games = []
    for key, e in (store.load().get("entries") or {}).items():
        parts = key.split("|")
        if len(parts) >= 4 and store.is_editable(parts[1], now):
            games.append({"key": key, "home": parts[2], "away": parts[3]})
    return games


def assign(injuries: list[dict], games: list[dict], info: dict) -> tuple[dict, list[str]]:
    """({game_key: {'out': [Spieler], 'doubtful': [Spieler], 'unmatched': [Namen]}}, nicht zugeordnet gesamt). Nur Teams der uebergebenen Spiele zaehlen."""
    res, unmatched_all = {}, []
    for g in games:
        roster, _ = rosters.game_players(info, g["away"], g["home"])
        teams = {team_key(g["home"]), team_key(g["away"])}
        r = {"out": [], "doubtful": [], "unmatched": []}
        for inj in injuries:
            if team_key(inj["team"]) not in teams:
                continue
            side = [p for p in roster if team_key(p["team"]) == team_key(inj["team"])]
            p = match_player(inj["name"], side)
            if p is None:
                r["unmatched"].append(f'{inj["name"]} ({inj["team"]}, {inj["status"]})')
                continue
            r[inj["kind"]].append({"person_id": int(p["person_id"]), "name": p["name"], "team": p["team"]})
        res[g["key"]] = r
        unmatched_all += r["unmatched"]
    return res, unmatched_all


def run(now: float | None = None, fetch_fn=fetch, info: dict | None = None, games: list[dict] | None = None) -> dict:
    """Ein Lauf: abrufen, zuordnen, eintragen. Wirft nie. Rueckgabe {'ok', 'error', 'games', 'out', 'doubtful', 'unmatched': [...], 'line'}."""
    now = now if now is not None else time.time()
    try:
        data = fetch_fn()
        injuries = parse(data)
    except Exception:
        return {"ok": False, "error": UNREACHABLE, "line": UNREACHABLE, "games": 0, "out": 0, "doubtful": 0, "unmatched": []}
    try:
        info = info if info is not None else rosters.load()
        games = games if games is not None else upcoming_games(now)
        assigned, unmatched = assign(injuries, games, info)
        n_out = n_dbt = 0
        for key, r in assigned.items():
            res = ab.apply_auto(key, r["out"], r["doubtful"], r["unmatched"], now=now)
            n_out += res["out"]; n_dbt += res["doubtful"]
    except Exception as e:
        msg = f"ESPN-Verletzungen: nicht eingetragen ({type(e).__name__}: {str(e)[:120]})"
        return {"ok": False, "error": msg, "line": msg, "games": 0, "out": 0, "doubtful": 0, "unmatched": []}
    line = f"ESPN-Verletzungen: {n_out} fehlt, {n_dbt} fraglich in {len(games)} Spiel(en) eingetragen" + (f"; nicht zugeordnet: {len(unmatched)}" if unmatched else "") + "."
    return {"ok": True, "error": None, "line": line, "games": len(games), "out": n_out, "doubtful": n_dbt, "unmatched": unmatched}


def main(write=print) -> int:
    res = run()
    write(res["line"])
    for u in res["unmatched"]:
        write(f"  nicht zugeordnet: {u}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
