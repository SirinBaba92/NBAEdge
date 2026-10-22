"""
Eine Marktlinie je Spiel und Markt: eigene Eingabe (Pre-Match Eingabe) gegen Cache, die NEUERE gewinnt.

Maerkte: "spread", "total", "team_total_away", "team_total_home".
Kandidaten:
  (a) eigene Eingabe = Hauptlinie (aktive Zeile) aus data/tracking/pre_match_entries.json; Zeitpunkt = updated_at, Buchmacher gespeichert
  (b) Cache = Linie aus dem Odds-Cache bzw. der gespeicherten Vorab-Linie (data/pregame_lines.py); Zeitpunkt = Abrufzeit des Caches
Regeln: spaeterer Zeitpunkt gewinnt, bei Gleichstand die eigene Eingabe; entfernte/fehlende Eingabe -> Cache; ohne beides keine Linie.
Gilt fuer ALLE Spiele, auch laufende und beendete: Eigene Eingaben sind per Definition Vorab-Linien (ab Anpfiff gesperrt) und bleiben nach dem
Anpfiff gueltig, damit sich die Vorab-Projektion nicht aendert. Aus dem Cache zaehlt fuer gestartete Spiele nur die gespeicherte Vorab-Linie
(data/pregame_lines.py), nie eine Live-Linie.

Vorzeichen: "spread" folgt der Projekt-Konvention (positiv = Heimteam ist Favorit). Die Eingabe speichert die Linie aus Heim-Sicht
(line_home, negativ = Heim-Favorit), also spread = -line_home. Die Projektion (engine/projection.py) nutzt nur spread und total;
Team-Total-Linien fliessen NICHT in die Projektion ein (nur Anzeige und spaetere Schritte).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

MARKETS = ("spread", "total", "team_total_away", "team_total_home")
MARKET_NAMES = {"spread": "Spread", "total": "Total", "team_total_away": "Team Total Gast", "team_total_home": "Team Total Heim"}
# Ab dieser Abweichung (eigene Linie gegen Cache) zeigt die Karte einen gelben Hinweis; die eigene Linie wird trotzdem benutzt.
DEVIATION_LIMITS = {"spread": 4.0, "total": 8.0, "team_total_away": 5.0, "team_total_home": 5.0}
SOURCE_OWN = "eigene Eingabe"
SOURCE_CACHE = "Cache"

_entries_cache: dict = {"sig": None, "entries": {}}


def _ts(iso) -> float | None:
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def load_entries() -> dict:
    """Pre-Match-Eintraege (nur lesen). Die Datei wird nur neu gelesen, wenn sich Aenderungszeit/Groesse aendern (wie beim Pickle)."""
    from data import pre_match_store as store
    path = store.store_path()
    try:
        st = path.stat()
        sig = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        sig = (str(path), None, None)
    if _entries_cache["sig"] != sig:
        entries = {}
        if sig[1] is not None:
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                entries = d.get("entries", {}) if isinstance(d, dict) else {}
            except Exception:
                entries = {}
        _entries_cache.update(sig=sig, entries=entries)
    return _entries_cache["entries"]


def entries_signature():
    load_entries()
    return _entries_cache["sig"]


def own_candidates(entry: dict | None) -> dict:
    """Hauptlinien der eigenen Eingabe: {markt: {'line', 'bookmaker', 'at' (Epoch), 'at_iso'}}. Nur aktive Hauptzeilen mit gueltigem Zeitpunkt."""
    out = {}
    if not entry:
        return out
    from data import pre_match_store as store

    def put(market, line, row):
        ts = _ts(row.get("updated_at"))
        if line is None or ts is None:
            return
        out[market] = {"line": line, "bookmaker": row.get("bookmaker") or "", "at": ts, "at_iso": row.get("updated_at")}

    main = next((l for l in store.active_spread_lines(entry) if l.get("id") == "main"), None)
    if main is not None and main.get("line_home") is not None:
        put("spread", round(-float(main["line_home"]), 2) + 0.0, main)          # Heim-Sicht (negativ = Heim-Favorit) -> positiv = Heim-Favorit
    main = next((l for l in store.active_total_lines(entry) if l.get("id") == "main"), None)
    if main is not None:
        put("total", main.get("line"), main)
    for side in store.TEAMS:
        main = next((l for l in store.team_total_lines(entry, side) if l.get("id") == "main"), None)
        if main is not None:
            put(f"team_total_{side}", main.get("line"), main)
    return out


def cache_candidates(lines: dict | None, home: str, away: str, at: float | None) -> dict:
    """Cache-Linien: {markt: {'line', 'at'}}. lines wie parse_totals_spreads (spread positiv = Heim-Favorit). Team Totals nur, wenn der Cache sie kennt."""
    out = {}
    if not lines:
        return out
    if lines.get("spread") is not None:
        out["spread"] = {"line": float(lines["spread"]), "at": at}
    if lines.get("total"):
        out["total"] = {"line": float(lines["total"]), "at": at}
    tt = lines.get("team_totals") or {}
    for side, team in (("home", home), ("away", away)):
        nick = team.split()[-1].lower()
        val = next((v for k, v in tt.items() if nick in str(k).lower()), None)
        if val and val.get("line") is not None:
            out[f"team_total_{side}"] = {"line": float(val["line"]), "at": at}
    return out


def resolve_market_lines(entry: dict | None, cache_lines: dict | None, cache_at: float | None, cache_source: str | None,
                         home: str, away: str) -> dict:
    """Je Markt EINE Linie: {markt: {'line', 'source' ('eigene Eingabe'|'Cache'|None), 'bookmaker', 'at' (Epoch|None), 'at_iso',
    'cache_line', 'cache_at', 'cache_source', 'own_line', 'deviation', 'warn'}}.
    Unabhaengig vom Spielzustand (Eingaben sind Vorab-Linien)."""
    own = own_candidates(entry)
    cache = cache_candidates(cache_lines, home, away, cache_at)
    result = {}
    for m in MARKETS:
        o, c = own.get(m), cache.get(m)
        res = {"line": None, "source": None, "bookmaker": "", "at": None, "at_iso": None,
               "cache_line": c["line"] if c else None, "cache_at": c["at"] if c else None, "cache_source": cache_source if c else None,
               "own_line": o["line"] if o else None, "deviation": None, "warn": False}
        use_own = o is not None and (c is None or c["at"] is None or o["at"] >= c["at"])       # spaeter gewinnt, bei Gleichstand die eigene Eingabe
        if use_own:
            res.update(line=o["line"], source=SOURCE_OWN, bookmaker=o["bookmaker"], at=o["at"], at_iso=o["at_iso"])
            if c is not None:
                res["deviation"] = round(abs(o["line"] - c["line"]), 2)
                res["warn"] = res["deviation"] > DEVIATION_LIMITS[m]
        elif c is not None:
            res.update(line=c["line"], source=SOURCE_CACHE, at=c["at"])
        result[m] = res
    return result


def resolution_key(resolved: dict) -> tuple:
    """Vergleichswert: aendert er sich, muss die Anzeige/Projektion neu aufgebaut werden."""
    return tuple((m, resolved[m]["line"], resolved[m]["source"], resolved[m]["bookmaker"], resolved[m]["at"]) for m in MARKETS)


def projection_inputs(resolved: dict) -> tuple[float | None, float | None]:
    """(market_total, market_spread) fuer compute_projection (Team Totals fliessen nicht ein)."""
    return resolved["total"]["line"], resolved["spread"]["line"]
