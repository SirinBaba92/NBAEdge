"""
Wett-Speicher fuer den Spieltag-Tab (Baustein 3): eigene Vorab-Wetten je Spiel und Markt. Nur Logik, keine Oberflaeche, kein Netz.

Datei: data/tracking/day_bets.json  (Ordner ueber NBAEDGE_TRACKING_DIR wie pre_match_entries.json)
  {"version": 1, "format": "nbaedge-day-bets", "updated_at": "...",
   "games": {"<US-Spieldatum>|<Anpfiff UTC>|<Heim>|<Gast>": {        # Schluessel = pre_match_store.game_key
       "game_date", "start_utc", "home", "away",
       "bets": {"winner"|"spread"|"total"|"team_total_home"|"team_total_away": {
           "market", "active": true|false, "side": "home"|"away"|"over", "line": 231.5 | null, "odds": 1.91 | null, "stake": 20.0 | null,
           "odds_source": "gespeichert"|"manuell"|null, "line_ref": {"main_line", "chosen_line", "is_main", "source", "bookmaker", "at"} | null,
           "placed_at", "updated_at", "removed_at": null | "...",
           "revisions": [{"reason": "geaendert"|"entfernt", "replaced_at", "active", "side", "line", "odds", "stake", "odds_source", "line_ref",
                          "placed_at", "updated_at", "removed_at"}]}}}}}

Regeln
- Hoechstens EINE Wette je Markt und Spiel; eine neue Wette im selben Markt ersetzt die alte (der alte Stand bleibt in revisions).
- Entfernen loescht nichts: active = false, removed_at gesetzt, der letzte aktive Stand steht in revisions (reason "entfernt").
- Sperre ab Anpfiff (start_utc, hier geprueft und nicht nur in der Oberflaeche): Setzen, Aendern und Entfernen wirft GameStartedError; unbekannter Anpfiff gilt als begonnen.
- Seiten: Sieger und Spread "home"/"away" (bei Spread ist line die Linie aus Sicht der gewaehlten Mannschaft, z. B. Heim -4,5 oder Gast +4,5); Total und Team Total sind immer "over".
- Linien: nur .5-Linien (Betano kennt keine ganzzahligen Linien). Quote und Einsatz sind optional; die Wette zaehlt auch ohne.
- Schreiben: Temp-Datei + fsync + os.replace (atomar), Sperre gegen gleichzeitiges Schreiben (Thread-Sperre + flock auf day_bets.json.lock, wirkt auch zwischen Prozessen),
  Tageskopie in history/. Ist die Datei beschaedigt, wird sie NIE ueberschrieben: Sicherungskopie day_bets.corrupt-<Pruefsumme>.json, Fehler DayBetsError, nichts geaendert.
- Auswahl-Logik (reine Funktionen): nearest_half_line, line_choices, selectable_lines, main_lines_from_resolved, stored_odds, make_line_ref.
- Verbindung zum Live-Modell: evaluate_game_bets / bet_live_status (engine/live_model + engine/bet_status), summarize fuer die Tagesuebersicht.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from data import pre_match_store as store
from data.pre_match_store import GameStartedError, OddsInputError, game_key, iso_now, normalize_start

STORE_VERSION = 1
FORMAT = "nbaedge-day-bets"
MARKETS = ("winner", "spread", "total", "team_total_home", "team_total_away")
MARKET_NAMES = {"winner": "Sieger", "spread": "Spread", "total": "Total", "team_total_home": "Team Total Heim", "team_total_away": "Team Total Gast"}
SIDES = {"winner": ("home", "away"), "spread": ("home", "away"), "total": ("over",), "team_total_home": ("over",), "team_total_away": ("over",)}
LINE_BOUNDS = {"spread": (0.5, 60.0), "total": (100.0, 400.0), "team_total_home": (40.0, 200.0), "team_total_away": (40.0, 200.0)}   # Betrag der Linie (Spread) bzw. Wertebereich
SOURCES = ("gespeichert", "manuell")
MAX_STAKE = 100_000.0
LOCK_TIMEOUT_SECONDS = 10.0
LINE_STEPS = 5                     # auswaehlbar: Hauptlinie +- 5 in Schritten von 1
_lock = threading.RLock()


class DayBetsError(Exception):
    """Datei konnte nicht gelesen/geschrieben werden (z. B. beschaedigt); die bestehende Datei bleibt unveraendert. str(e) ist eine kurze deutsche Meldung."""


class BetInputError(ValueError):
    """Ungueltige Eingabe (kurze deutsche Meldung)."""


# ------------------------------------------------------------------------------ Pfade und Datei
def store_path() -> Path:
    return store.tracking_dir() / "day_bets.json"


def _lock_path() -> Path:
    return store.tracking_dir() / "day_bets.json.lock"


def _history_dir() -> Path:
    return store.tracking_dir() / "history"


def _empty() -> dict:
    return {"version": STORE_VERSION, "format": FORMAT, "updated_at": None, "games": {}}


def _parse(path: Path) -> dict:
    """Liest und prueft die Datei. Wirft ValueError bei unlesbarem Inhalt oder falscher Struktur."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("games"), dict):
        raise ValueError("Struktur")
    for g in data["games"].values():
        if not isinstance(g, dict) or not isinstance(g.get("bets"), dict):
            raise ValueError("Struktur")
    return data


def load() -> dict:
    """Aktueller Stand (leer, wenn die Datei fehlt). Beschaedigt oder zu neu: leere Struktur mit Feld 'error'; die Datei wird nicht veraendert."""
    path = store_path()
    if not path.exists():
        return _empty()
    try:
        data = _parse(path)
    except Exception:
        d = _empty()
        d["error"] = "Die Datei day_bets.json ist nicht lesbar (beschädigt). Es wird nichts überschrieben."
        return d
    if int(data.get("version", 0) or 0) > STORE_VERSION:
        d = _empty()
        d["error"] = "Die Datei day_bets.json stammt aus einer neueren Programmversion."
        return d
    return data


def load_error() -> str | None:
    """Meldung, wenn die Datei nicht gelesen werden kann (fuer die Oberflaeche), sonst None."""
    return load().get("error")


def _load_for_write() -> dict:
    """Stand fuer eine Aenderung. Beschaedigte Datei: Sicherungskopie (einmal je Inhalt) und DayBetsError; die Originaldatei bleibt unangetastet."""
    path = store_path()
    if not path.exists():
        return _empty()
    try:
        data = _parse(path)
    except Exception:
        try:
            raw = path.read_bytes()
        except OSError as e:
            raise DayBetsError("Die Datei day_bets.json ist nicht lesbar; es wurde nichts geändert.") from e
        backup = path.with_name(f"{path.stem}.corrupt-{hashlib.sha1(raw).hexdigest()[:10]}{path.suffix}")
        if not backup.exists():
            try:
                shutil.copyfile(path, backup)
            except OSError as e:
                raise DayBetsError("Die Datei day_bets.json ist beschädigt und konnte nicht gesichert werden; es wurde nichts geändert.") from e
        raise DayBetsError(f"Die Datei day_bets.json ist beschädigt. Sicherungskopie: {backup.name}. Es wurde nichts geändert; bitte Datei prüfen oder verschieben.")
    if int(data.get("version", 0) or 0) > STORE_VERSION:
        raise DayBetsError("Die Datei day_bets.json stammt aus einer neueren Programmversion; es wurde nichts geändert.")
    data["version"] = STORE_VERSION
    return data


class _WriteLock:
    """Thread-Sperre plus flock auf day_bets.json.lock (auch zwischen Prozessen). Wartet hoechstens LOCK_TIMEOUT_SECONDS."""

    def __enter__(self):
        _lock.acquire()
        try:
            _lock_path().parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(_lock_path(), "a+")
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        self._fh.close()
                        raise DayBetsError("Die Wett-Datei wird gerade von einem anderen Vorgang geschrieben. Bitte gleich noch einmal versuchen.")
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


def _write(data: dict, stamp: str, now: float) -> None:
    data["updated_at"] = stamp
    try:
        store._atomic_write(store_path(), data)
    except Exception as e:
        raise DayBetsError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
    try:                                                     # Tageskopie darf das Speichern nie scheitern lassen
        day = datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d")
        dest = _history_dir() / f"day_bets_{day}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(store_path(), tmp)
        os.replace(tmp, dest)
    except Exception:
        pass


# ------------------------------------------------------------------------------ Eingaben pruefen
def parse_line_input(value) -> float:
    """Linie aus Zahl oder Text (Komma oder Punkt). Nur .5-Linien (Betano kennt keine ganzzahligen)."""
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        raise BetInputError("Die Linie fehlt.")
    if isinstance(value, str):
        t = value.strip().replace(" ", "").replace("−", "-").replace(",", ".")
        if not re.fullmatch(r"[+-]?\d+(\.\d+)?", t):
            raise BetInputError("Bitte eine Zahl als Linie eingeben (z. B. 231,5).")
        value = float(t)
    value = float(value)
    if not math.isfinite(value) or abs(round(value * 2) - value * 2) > 1e-9 or round(value * 2) % 2 == 0:
        raise BetInputError("Es sind nur .5-Linien möglich (z. B. 231,5 oder −4,5).")
    return round(value, 1) + 0.0


def parse_odds_optional(value) -> float | None:
    """Quote optional: leer/None -> None; sonst Dezimalquote > 1,00 (wie die Pre-Match-Eingabe)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return store.parse_odds_input(value)
    except OddsInputError as e:
        raise BetInputError(str(e)) from None


def parse_stake_input(value) -> float | None:
    """Einsatz optional: leer/None -> None; sonst Zahl > 0 (Komma oder Punkt), hoechstens 100 000, auf 2 Stellen gerundet."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise BetInputError("Bitte den Einsatz als Zahl eingeben (z. B. 20 oder 12,50).")
    if isinstance(value, str):
        t = value.strip().replace(" ", "")
        if t.count(",") + t.count(".") > 1 or not re.fullmatch(r"\d+([.,]\d+)?", t):
            raise BetInputError("Bitte den Einsatz als Zahl eingeben (z. B. 20 oder 12,50).")
        value = float(t.replace(",", "."))
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise BetInputError("Der Einsatz muss größer als 0 sein.")
    if value > MAX_STAKE:
        raise BetInputError("Der Einsatz ist unrealistisch hoch.")
    return round(value, 2)


def make_line_ref(main_line: float | None, chosen_line: float | None, source: str | None = None, at: str | None = None, bookmaker: str | None = None) -> dict:
    """Welche Linie war zum Zeitpunkt der Wette die Hauptlinie? (Fuer spaetere Auswertung: Haupt- gegen Leiterlinie.)"""
    is_main = main_line is not None and chosen_line is not None and abs(float(main_line) - float(chosen_line)) < 1e-9
    return {"main_line": None if main_line is None else float(main_line), "chosen_line": None if chosen_line is None else float(chosen_line),
            "is_main": bool(is_main), "source": source, "bookmaker": bookmaker, "at": at}


def _clean_line_ref(ref) -> dict | None:
    if ref is None:
        return None
    if not isinstance(ref, dict):
        raise BetInputError("line_ref muss ein Wörterbuch sein.")
    try:
        json.dumps(ref)
    except TypeError:
        raise BetInputError("line_ref ist nicht speicherbar.") from None
    return copy.deepcopy(ref)


def _validate(market: str, side, line, odds, stake, odds_source, line_ref) -> dict:
    if market not in MARKETS:
        raise BetInputError(f"Unbekannter Markt: {market}.")
    allowed = SIDES[market]
    if side is None and len(allowed) == 1:
        side = allowed[0]
    if side not in allowed:
        raise BetInputError(f"{MARKET_NAMES[market]}: Seite muss {' oder '.join(allowed)} sein" + (" (nur Over ist vorgesehen)." if allowed == ("over",) else "."))
    if market == "winner":
        if line not in (None, ""):
            raise BetInputError("Beim Sieger gibt es keine Linie.")
        line = None
    else:
        line = parse_line_input(line)
        lo, hi = LINE_BOUNDS[market]
        if not (lo <= abs(line) <= hi if market == "spread" else lo <= line <= hi):
            raise BetInputError(f"{MARKET_NAMES[market]}: Linie außerhalb des plausiblen Bereichs ({'±' if market == 'spread' else ''}{lo:g} bis {hi:g}).")
    odds, stake = parse_odds_optional(odds), parse_stake_input(stake)
    if odds_source is not None and odds_source not in SOURCES:
        raise BetInputError(f"Quelle der Quote muss {' oder '.join(SOURCES)} sein.")
    if odds is None:
        odds_source = None
    elif odds_source is None:
        odds_source = "manuell"
    return {"side": side, "line": line, "odds": odds, "stake": stake, "odds_source": odds_source, "line_ref": _clean_line_ref(line_ref)}


def _check_editable(start_utc, now: float) -> str:
    """Normalisierter Anpfiff; wirft GameStartedError ab dem Anpfiff (oder bei unbekanntem Anpfiff)."""
    start_norm = normalize_start(start_utc)
    if start_norm is None:
        raise GameStartedError("Anpfiff unbekannt: keine Änderung möglich.")
    if not store.is_editable(start_norm, now):
        raise GameStartedError("Das Spiel hat bereits begonnen: keine Änderung mehr möglich.")
    return start_norm


def is_bet_editable(start_utc, now: float | None = None) -> bool:
    """True, solange das Spiel noch nicht begonnen hat (unbekannter Anpfiff: False)."""
    return store.is_editable(normalize_start(start_utc) if start_utc else None, now)


_CORE = ("side", "line", "odds", "stake", "odds_source")
_STATE = ("active", "side", "line", "odds", "stake", "odds_source", "line_ref", "placed_at", "updated_at", "removed_at")


def _revision(bet: dict, reason: str, stamp: str) -> dict:
    return {"reason": reason, "replaced_at": stamp, **{k: copy.deepcopy(bet.get(k)) for k in _STATE}}


# ------------------------------------------------------------------------------ Setzen, Aendern, Entfernen
def set_bet(game_date: str, start_utc: str, home: str, away: str, market: str, side: str | None = None, line=None, odds=None, stake=None,
            odds_source: str | None = None, line_ref: dict | None = None, now: float | None = None) -> dict:
    """Wette setzen oder aendern (ersetzt die bestehende des Marktes, der alte Stand bleibt in revisions). Rueckgabe {'status': 'saved'|'unchanged', 'key', 'bet'}.
    Wirft BetInputError (Eingabe), GameStartedError (ab Anpfiff) oder DayBetsError (Datei). Es wird erst geprueft, dann geschrieben."""
    now = now if now is not None else time.time()
    new = _validate(market, side, line, odds, stake, odds_source, line_ref)
    start_norm = _check_editable(start_utc, now)
    if not (str(home).strip() and str(away).strip() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(game_date))):
        raise BetInputError("Spieldatum (JJJJ-MM-TT), Heim und Gast müssen angegeben sein.")
    key = game_key(game_date, start_norm, home, away)
    with _WriteLock():
        data = _load_for_write()
        game = data["games"].setdefault(key, {"game_date": game_date, "start_utc": start_norm, "home": home, "away": away, "bets": {}})
        old = game["bets"].get(market)
        if old and old.get("active") and all(old.get(k) == new[k] for k in _CORE):
            return {"status": "unchanged", "key": key, "bet": copy.deepcopy(old)}
        stamp = iso_now(now)
        revisions = list(old["revisions"]) if old else []
        placed_at = stamp
        if old and old.get("active"):
            revisions.append(_revision(old, "geaendert", stamp))
            placed_at = old["placed_at"]                       # dieselbe Wette, nur geaendert
        game["bets"][market] = {"market": market, "active": True, **new, "placed_at": placed_at, "updated_at": stamp, "removed_at": None, "revisions": revisions}
        _write(data, stamp, now)
        return {"status": "saved", "key": key, "bet": copy.deepcopy(game["bets"][market])}


def remove_bet(game_date: str, start_utc: str, home: str, away: str, market: str, now: float | None = None) -> dict:
    """Wette entfernen (nicht loeschen): active false, removed_at gesetzt, letzter aktiver Stand in revisions. Rueckgabe {'status': 'removed'|'none', 'key', 'bet'}.
    Ohne aktive Wette in diesem Markt: 'none' (kein Fehler, nichts geschrieben). Wirft GameStartedError ab Anpfiff."""
    now = now if now is not None else time.time()
    if market not in MARKETS:
        raise BetInputError(f"Unbekannter Markt: {market}.")
    start_norm = _check_editable(start_utc, now)
    key = game_key(game_date, start_norm, home, away)
    with _WriteLock():
        data = _load_for_write()
        bet = (data["games"].get(key) or {}).get("bets", {}).get(market)
        if not bet or not bet.get("active"):
            return {"status": "none", "key": key, "bet": copy.deepcopy(bet) if bet else None}
        stamp = iso_now(now)
        bet["revisions"].append(_revision(bet, "entfernt", stamp))
        bet.update(active=False, removed_at=stamp, updated_at=stamp)
        _write(data, stamp, now)
        return {"status": "removed", "key": key, "bet": copy.deepcopy(bet)}


# ------------------------------------------------------------------------------ Lesen
def _bets_of(game: dict | None, include_removed: bool) -> dict:
    return {m: copy.deepcopy(b) for m, b in ((game or {}).get("bets") or {}).items() if include_removed or b.get("active")}


def get_bets_by_key(key: str, include_removed: bool = False) -> dict:
    """{markt: wette} eines Spiels (Schluessel wie game_key); standardmaessig nur aktive Wetten."""
    return _bets_of(load()["games"].get(key), include_removed)


def get_bets(game_date: str, start_utc: str, home: str, away: str, include_removed: bool = False) -> dict:
    """{markt: wette} eines Spiels. Unbekannter Anpfiff oder unbekanntes Spiel: {}."""
    start_norm = normalize_start(start_utc) if start_utc else None
    if start_norm is None:
        return {}
    return get_bets_by_key(game_key(game_date, start_norm, home, away), include_removed)


def get_day_bets(day: str, include_removed: bool = False) -> dict:
    """Alle Wetten eines US-Spieltags: {game_key: {'game': {game_date, start_utc, home, away}, 'bets': {markt: wette}}}; Spiele ohne (aktive) Wetten fehlen."""
    out = {}
    for key, g in load()["games"].items():
        if g.get("game_date") != day:
            continue
        bets = _bets_of(g, include_removed)
        if bets:
            out[key] = {"game": {k: g.get(k) for k in ("game_date", "start_utc", "home", "away")}, "bets": bets}
    return out


def list_day_bets(day: str, include_removed: bool = False) -> list[dict]:
    """Flache Liste fuer die Tagesuebersicht: [{'key', 'game', 'market', 'bet'}], nach Anpfiff, Markt-Reihenfolge."""
    rows = []
    for key, v in sorted(get_day_bets(day, include_removed).items(), key=lambda kv: (kv[1]["game"].get("start_utc") or "", kv[0])):
        for m in MARKETS:
            if m in v["bets"]:
                rows.append({"key": key, "game": v["game"], "market": m, "bet": v["bets"][m]})
    return rows


# ------------------------------------------------------------------------------ Auswahl-Logik (rein)
def nearest_half_line(value: float) -> float:
    """Naechste .5-Linie (ganzzahlige Werte -> naechstes .5 nach oben: 231,0 -> 231,5; -4,2 -> -4,5; 231,8 -> 231,5)."""
    return math.floor(float(value)) + 0.5


def _in_bounds(market: str, line: float) -> bool:
    lo, hi = LINE_BOUNDS[market]
    return lo <= abs(line) <= hi if market == "spread" else lo <= line <= hi


def line_choices(market: str, main_line: float | None, side: str | None = None, steps: int = LINE_STEPS) -> list[float]:
    """Auswaehlbare Linien eines Marktes: Hauptlinie +- steps in Schritten von 1, alle .5, aufsteigend, nur im plausiblen Bereich.
    Spread: main_line ist die Linie aus HEIM-Sicht (z. B. -4,5); side 'away' liefert die Linien aus Gast-Sicht (+4,5 ...). Sieger/ohne Hauptlinie: []."""
    if market not in MARKETS or market == "winner" or main_line is None:
        return []
    base = nearest_half_line(main_line)
    lines = [round(base + k, 1) + 0.0 for k in range(-steps, steps + 1)]
    if market == "spread" and side == "away":
        lines = sorted((-x + 0.0 for x in lines))
    return [x for x in lines if _in_bounds(market, x)]


def default_line(market: str, main_line: float | None, side: str | None = None) -> float | None:
    """Vorauswahl: die Hauptlinie (auf .5 gebracht); fuer Spread/Gast die negierte Heim-Linie. Sieger oder ohne Hauptlinie: None."""
    if market == "winner" or market not in MARKETS or main_line is None:
        return None
    base = nearest_half_line(main_line)
    return (-base + 0.0) if (market == "spread" and side == "away") else base


def selectable_lines(main_lines: dict, steps: int = LINE_STEPS) -> dict:
    """Alle Maerkte auf einmal. main_lines: {'spread_home': Linie aus Heim-Sicht, 'total', 'team_total_home', 'team_total_away'} (None = keine Hauptlinie).
    Rueckgabe {'winner': {'default': None, 'lines': []}, 'spread': {'home': {...}, 'away': {...}}, 'total': {'default', 'lines'}, ...}."""
    out = {"winner": {"default": None, "lines": []}}
    sp = main_lines.get("spread_home")
    out["spread"] = {s: {"default": default_line("spread", sp, s), "lines": line_choices("spread", sp, s, steps)} for s in ("home", "away")}
    for m in ("total", "team_total_home", "team_total_away"):
        out[m] = {"default": default_line(m, main_lines.get(m)), "lines": line_choices(m, main_lines.get(m), None, steps)}
    return out


def main_lines_from_resolved(resolved: dict | None) -> dict:
    """Hauptlinien aus data.market_lines.resolve_market_lines (Spread dort: positiv = Heim-Favorit -> hier aus Heim-Sicht negiert). Fehlen die Team-Total-Linien,
    werden sie rechnerisch aus Total und Spread abgeleitet (wie in Score Projections)."""
    from engine.line_probabilities import team_main_from_total_spread
    r = resolved or {}
    line = lambda m: ((r.get(m) or {}).get("line"))
    sp, total = line("spread"), line("total")
    out = {"spread_home": None if sp is None else round(-float(sp), 2) + 0.0, "total": total,
           "team_total_home": line("team_total_home"), "team_total_away": line("team_total_away")}
    if out["team_total_home"] is None or out["team_total_away"] is None:
        derived = team_main_from_total_spread(total, sp)
        if derived:
            out["team_total_home"] = out["team_total_home"] if out["team_total_home"] is not None else derived["home"]
            out["team_total_away"] = out["team_total_away"] if out["team_total_away"] is not None else derived["away"]
    return out


def stored_odds(entry: dict | None, market: str, side: str, line: float | None = None) -> dict | None:
    """Quote aus der gespeicherten Vorab-Eingabe (pre_match_entries, z. B. vom Betano-Import) fuer die gewaehlte Wette:
    {'odds', 'bookmaker', 'updated_at'} oder None. Sieger: Heim/Gast-Quote; Spread: Linie der gewaehlten Mannschaft; Total/Team Total: Over-Quote der Linie."""
    if not entry:
        return None
    close = lambda a, b: a is not None and b is not None and abs(float(a) - float(b)) < 1e-9
    row = None
    if market == "winner":
        m = (entry.get("markets") or {}).get(store.WINNER)
        if m and m.get(f"{side}_odds"):
            return {"odds": m[f"{side}_odds"], "bookmaker": m.get("bookmaker", ""), "updated_at": m.get("updated_at")}
        return None
    if market == "spread":
        row = next((l for l in store.active_spread_lines(entry) if close(l.get(f"line_{side}"), line)), None)
        key = f"{side}_odds"
    elif market == "total":
        row = next((l for l in store.active_total_lines(entry) if close(l.get("line"), line)), None)
        key = "over_odds"
    elif market in ("team_total_home", "team_total_away"):
        row = next((l for l in store.team_total_lines(entry, market.rsplit("_", 1)[1]) if close(l.get("line"), line)), None)
        key = "over_odds"
    else:
        return None
    if row and row.get(key):
        return {"odds": row[key], "bookmaker": row.get("bookmaker", ""), "updated_at": row.get("updated_at")}
    return None


# ------------------------------------------------------------------------------ Verbindung zum Live-Modell
@dataclass(frozen=True)
class BetLive:
    market: str
    side: str | None
    line: float | None
    odds: float | None
    stake: float | None
    label: str                 # Status laut engine/bet_status: Gewonnen / Verloren / Auf Kurs / Offen / In Gefahr / Kaum noch möglich / Wartet auf Anpfiff / Entfernt
    color: str                 # gruen / gelb / orange / rot / grau
    state: str                 # gewonnen | verloren | offen | wartet | entfernt
    probability: float | None  # Chance, dass die Wette durchgeht
    decided: bool
    won: bool | None
    profit: float | None       # nur abgerechnet UND mit Quote und Einsatz, sonst None
    home_pts: int
    away_pts: int
    final: bool


def bet_live_status(bet: dict, proj, started: bool = True) -> BetLive:
    """Aktueller Status EINER gespeicherten Wette aus einer fertigen Hochrechnung (engine.live_model.LiveProjection)."""
    from engine import bet_status as bs
    if not bet.get("active", True):
        return BetLive(bet["market"], bet.get("side"), bet.get("line"), bet.get("odds"), bet.get("stake"), "Entfernt", bs.COLORS[bs.WAITING], "entfernt", None, False, None, None,
                       proj.home_pts, proj.away_pts, proj.final)
    st = bs.evaluate_bet(bet, proj, started=started)
    profit = bs.profit(bet, st) if (st.decided and bet.get("odds") is not None and bet.get("stake") is not None) else None
    state = ("gewonnen" if st.won else "verloren") if st.decided else ("offen" if started else "wartet")
    return BetLive(bet["market"], bet.get("side"), bet.get("line"), bet.get("odds"), bet.get("stake"), st.label, st.color, state, st.probability, st.decided, st.won, profit,
                   proj.home_pts, proj.away_pts, proj.final)


def evaluate_game_bets(bets: dict, anchor, clock, home_pts: int, away_pts: int, poss=None, factors=None) -> dict:
    """Status aller Wetten eines Spiels ({markt: BetLive}); die Hochrechnung wird einmal berechnet.
    anchor: engine.live_model.Anchor (Schnappschuss beim Anpfiff), clock: engine.game_clock.GameClock, Stand und optional Ballbesitze (Possessions)."""
    from engine import live_model as lm
    proj = lm.project(anchor, clock, home_pts, away_pts, poss, factors)
    started = bool(clock.is_live or clock.is_final)
    return {m: bet_live_status(b, proj, started) for m, b in bets.items()}


def summarize(lives: list[BetLive]) -> dict:
    """Tagesuebersicht: offene, gewonnene, verlorene Wetten, gesetzter Einsatz, Gewinn/Verlust nur der abgerechneten Wetten (mit Quote und Einsatz).
    Entfernte Wetten zaehlen nicht. 'ohne_quote_oder_einsatz' nennt abgerechnete Wetten, die nicht in den Gewinn eingehen."""
    act = [b for b in lives if b.state != "entfernt"]
    settled = [b for b in act if b.decided]
    return {"wetten": len(act), "offen": sum(1 for b in act if not b.decided), "gewonnen": sum(1 for b in act if b.decided and b.won), "verloren": sum(1 for b in act if b.decided and not b.won),
            "einsatz": round(sum(b.stake or 0.0 for b in act), 2), "einsatz_abgerechnet": round(sum(b.stake or 0.0 for b in settled), 2),
            "gewinn_verlust": round(sum(b.profit for b in settled if b.profit is not None), 2),
            "ohne_quote_oder_einsatz": sum(1 for b in settled if b.profit is None)}
