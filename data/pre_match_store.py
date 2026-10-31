"""
Pre-Match-Eingaben: eigene Quoten pro Spiel, erfasst VOR dem Anpfiff (Tracking und spaeterer Backtest).

Datei: data/tracking/pre_match_entries.json  (einfaches JSON, ohne die App lesbar, keine Keys)
  {
    "version": 2,
    "format": "nbaedge-pre-match-entries",
    "markets": {"winner_incl_ot": "..."},
    "last_bookmaker": {"winner_incl_ot": "Pinnacle"},
    "updated_at": "2026-10-21T00:41:03+02:00",
    "entries": {
      "<Spieldatum US>|<Anpfiff UTC>|<Heim>|<Gast>": {
        "game_date": "2026-10-20", "start_utc": "2026-10-20T23:00:00Z", "home": "...", "away": "...",
        "markets": {"winner_incl_ot": {
            "home_odds": 1.55, "away_odds": 2.5, "bookmaker": "Pinnacle",
            "entered_at": "<erste Erfassung>", "updated_at": "<letzte Aenderung>",
            "revisions": [{"home_odds": ..., "away_odds": ..., "bookmaker": ..., "saved_at": ...}, ...]}}}
    }
  }
Version 2 fuegt den Markt "spread" hinzu:
  "spread": {"entered_at", "updated_at", "lines": [
      {"id": "main"|"x1"|..., "role": "main"|"extra", "active": true|false, "line_home": -4.5, "line_away": 4.5,
       "home_odds": 1.91, "away_odds": 1.91, "bookmaker": "...", "entered_at", "updated_at", ["removed_at"],
       "market_suggestion": {"line_home": -4.33, "line_home_rounded": -4.5, "source": "cache_vorab"} | null,   # ungerundet und auf 0,5 gerundet
       "revisions": [{"action": "saved"|"removed", ... , "saved_at", "market_suggestion"}]}]}
  Die Hauptlinie steht immer an erster Stelle; entfernte Linien bleiben mit active=false und Revision erhalten.
Version 3 fuegt den Markt "total" (Ueber/Unter der Gesamtpunkte) hinzu:
  "total": {"entered_at", "updated_at", "lines": [
      {"id": "main"|"x1"|..., "role": "main"|"extra", "direction": null (Hauptlinie) | "higher" | "lower", "active": true|false,
       "line": 231.5, "over_odds": 1.91, "under_odds": 1.91, "bookmaker": "...", "entered_at", "updated_at", ["removed_at"],
       "market_suggestion": {"line": 231.4, "line_rounded": 231.5, "source": "cache_vorab"} | null,
       "revisions": [{"action": "saved"|"removed", ..., "saved_at", "market_suggestion"}]}]}
  Hauptlinie plus bis zu 3 hoehere und 3 niedrigere weitere Linien (je 1,0 Punkt weiter); jede Linie hoechstens einmal je Spiel.
Version 4 fuegt den Markt "team_totals" hinzu (je Team getrennt, Linien wie beim Total, Plausibilitaet 40 bis 200):
  "team_totals": {"entered_at", "updated_at", "away": {"team": "...", "lines": [...]}, "home": {"team": "...", "lines": [...]}}
  market_suggestion einer Team-Total-Hauptlinie ist rechnerisch (source "derived"): Heim = (Total - Linie_Heim) / 2, Gast = (Total + Linie_Heim) / 2.
Version 5 fuegt den Markt "player_points" hinzu (Spielerbloecke):
  "player_points": {"entered_at", "updated_at", "players": [
      {"id": "p1", "person_id": 1630173, "name": "...", "team": "<Vollname>", "team_abbreviation": "SAC", "mode": "milestones"|"line", "active": true|false,
       "roster_fetched_at": "<Kaderstand, mit dem gewaehlt wurde>", "entered_at", "updated_at", ["removed_at"],
       "lines": [{"id": "x1", "threshold": 19 (nur Meilenstein: mindestens so viele Punkte, nur "odds") | "line": 24.5 (nur Einzellinie: "over_odds", "under_odds"),
                  "odds", "bookmaker", "active", "entered_at", "updated_at", ["removed_at"], "revisions": [...]}]}]}
  Der Modus und der Spieler eines gespeicherten Blocks aendern sich nicht (Wechsel nur durch Entfernen und neuen Block); Entfernen ist immer eine Revision.
Version 1 bis 4 bleiben lesbar; beim ersten Schreiben wird die alte Datei byte-genau als history/pre_match_entries.v<alt>_vor_Upgrade_*.json gesichert.
Quelle einer Revision: optionales Feld "source". Fehlt es (alle Handeingaben, auch alle aelteren Revisionen), gilt "hand"; die Automatik (save_auto)
schreibt "source": "auto". Eine auto-Revision beruehrt nie einen Markt/eine Linie/einen Spielerblock, der eine Hand-Revision hat (Vorrang der Hand).
Sperre: flock auf pre_match_entries.json.lock um jedes Lesen-Aendern-Schreiben (wirkt auch zwischen Prozessen).
Alle Zeitstempel tragen den UTC-Versatz. Gespeichert wird nur, solange das Spiel noch nicht begonnen hat (hier
geprueft, nicht nur in der Oberflaeche), damit "entered_at" belegt, dass die Quote vor dem Anpfiff erfasst wurde.

Schreiben: Temp-Datei im selben Ordner, fsync, dann os.replace (atomar). Bei jedem Fehler bleibt die bestehende Datei
unveraendert. Nach jedem erfolgreichen Speichern entsteht eine Tageskopie in data/tracking/history/.
"""
from __future__ import annotations

import copy
import fcntl
import json
import math
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

STORE_VERSION = 5          # 2: Markt "spread"; 3: Markt "total"; 4: Markt "team_totals"; 5: Markt "player_points" (aeltere Versionen bleiben lesbar; beim ersten Schreiben wird die Datei gesichert und gehoben)
FORMAT = "nbaedge-pre-match-entries"
MARKETS = {"winner_incl_ot": "Sieger inkl. OT (Dezimalquoten Heim/Gast)",
           "spread": "Spread (Linie aus Heim-Sicht, Dezimalquoten Gast/Heim, Hauptlinie + weitere Linien)",
           "team_totals": "Team Totals (Ueber/Unter der Punkte je Team, Hauptlinie + hoehere/niedrigere Linien je Team)",
           "player_points": "Spielerpunkte (Meilensteine +N mit einer Quote oder Einzellinie mit Over/Under, je Spieler)",
           "total": "Total (Ueber/Unter der Gesamtpunkte, Dezimalquoten Over/Under, Hauptlinie + hoehere/niedrigere Linien)"}
WINNER = "winner_incl_ot"
SPREAD = "spread"
TOTAL = "total"
TEAM_TOTALS = "team_totals"
MIN_TEAM_TOTAL, MAX_TEAM_TOTAL = 40.0, 200.0
TEAMS = ("away", "home")          # Gast zuerst, dann Heim
PLAYER_POINTS = "player_points"
MAX_PLAYERS = 20                  # Spielerbloecke je Spiel (bis Schritt 10: 10)
MAX_MILESTONES = 10               # Meilensteine je Spieler
MAX_PLAYER_LINES = 5              # Einzellinien je Spieler
MIN_THRESHOLD, MAX_THRESHOLD = 1, 80
MIN_PLAYER_LINE, MAX_PLAYER_LINE = 3.0, 80.0
MODES = ("milestones", "line")
MIN_TOTAL, MAX_TOTAL = 100.0, 400.0
MAX_TOTAL_PER_DIRECTION = 3
MAX_SPREAD_EXTRA = 4              # weitere Spread-Linien (plus Hauptlinie = 5 Linien, wie die Leiter in Score Projections)
MAX_LINE = 60.0
MAX_BOOKMAKER_LEN = 60
ROOT = Path(__file__).resolve().parent.parent
LOCK_TIMEOUT_SECONDS = 10.0
SOURCE_HAND, SOURCE_AUTO = "hand", "auto"


class OddsInputError(ValueError):
    """Ungueltige Eingabe (kurze deutsche Meldung)."""


class GameStartedError(Exception):
    """Das Spiel hat bereits begonnen (oder der Anpfiff ist unbekannt): keine Aenderung mehr."""


class StoreError(Exception):
    """Datei konnte nicht gelesen/geschrieben werden; die bestehende Datei bleibt unveraendert."""


class _StoreLock:
    """Thread-Sperre (wiedereintrittsfaehig) plus flock auf pre_match_entries.json.lock (wirkt auch zwischen Prozessen, Muster wie day_bets_store).
    Der flock wird nur beim aeussersten Betreten genommen; wartet hoechstens LOCK_TIMEOUT_SECONDS, dann StoreError (nichts geaendert)."""

    def __init__(self):
        self._rlock = threading.RLock()
        self._depth = 0
        self._fh = None

    def __enter__(self):
        self._rlock.acquire()
        try:
            if self._depth == 0:
                lock_path = store_path().with_name(store_path().name + ".lock")
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                fh = open(lock_path, "a+")
                deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
                while True:
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            fh.close()
                            raise StoreError("Die Eingabe-Datei wird gerade von einem anderen Vorgang geschrieben. Bitte gleich noch einmal versuchen.") from None
                        time.sleep(0.01)
                self._fh = fh
            self._depth += 1
        except BaseException:
            self._rlock.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            self._depth -= 1
            if self._depth == 0:
                try:
                    fcntl.flock(self._fh, fcntl.LOCK_UN)
                finally:
                    self._fh.close()
                    self._fh = None
        finally:
            self._rlock.release()


_lock = _StoreLock()


def tracking_dir() -> Path:
    return Path(os.environ.get("NBAEDGE_TRACKING_DIR") or ROOT / "data" / "tracking")


def store_path() -> Path:
    return tracking_dir() / "pre_match_entries.json"


def history_dir() -> Path:
    return tracking_dir() / "history"


# ------------------------------------------------------------------------------ Eingaben
def parse_odds_input(text) -> float:
    """Dezimalquote aus Text: Komma oder Punkt, Zahl > 1,00 (hoechstens 1000)."""
    if text is None or not str(text).strip():
        raise OddsInputError("Quote fehlt.")
    t = str(text).strip().replace(" ", "").replace(" ", "")
    if t.count(",") + t.count(".") > 1:
        raise OddsInputError("Bitte nur einen Dezimaltrenner verwenden (z. B. 1,85).")
    t = t.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        raise OddsInputError("Bitte eine Zahl eingeben (z. B. 1,85).")
    value = float(t)
    if not math.isfinite(value) or value <= 1.0:
        raise OddsInputError("Die Quote muss größer als 1,00 sein.")
    if value > 1000:
        raise OddsInputError("Die Quote ist unrealistisch hoch (über 1000).")
    return value


def clean_bookmaker(text) -> str:
    t = re.sub(r"[\x00-\x1f\x7f]", " ", str(text or ""))
    return " ".join(t.split())[:MAX_BOOKMAKER_LEN]


def parse_line_input(text) -> float:
    """Spread-Linie aus Heim-Sicht: Komma oder Punkt, Vorzeichen (+, -, −), nur ganze und halbe Linien (z. B. -1 / -1,5 / 0 / +2)."""
    if text is None or not str(text).strip():
        raise OddsInputError("Linie fehlt.")
    t = str(text).strip().replace(" ", "").replace("\u00a0", "").replace("\u2212", "-")
    if t.count(",") + t.count(".") > 1:
        raise OddsInputError("Bitte nur einen Dezimaltrenner verwenden (z. B. -4,5).")
    t = t.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", t):
        raise OddsInputError("Bitte eine Linie eingeben (z. B. -4,5 oder +3,25).")
    value = float(t)
    if abs(value) > MAX_LINE:
        raise OddsInputError(f"Die Linie ist unrealistisch (mehr als {int(MAX_LINE)} Punkte).")
    if abs(value * 2 - round(value * 2)) > 1e-9:
        raise OddsInputError("Nur ganze und halbe Linien erlaubt (z. B. -1, -1,5, 0, +2).")
    return value + 0.0                                   # kein -0.0


def parse_total_input(text) -> float:
    """Total-Linie (Gesamtpunkte): Komma oder Punkt, nur ganze und halbe Linien (231 / 231,5), zwischen 100 und 400."""
    return _parse_ou_line(text, MIN_TOTAL, MAX_TOTAL, "231,5")


def parse_team_total_input(text) -> float:
    """Team-Total-Linie (Punkte eines Teams): wie parse_total_input, aber zwischen 40 und 200."""
    return _parse_ou_line(text, MIN_TEAM_TOTAL, MAX_TEAM_TOTAL, "113,5")


def _parse_ou_line(text, lo: float, hi: float, example: str) -> float:
    if text is None or not str(text).strip():
        raise OddsInputError("Linie fehlt.")
    t = str(text).strip().replace(" ", "").replace("\u00a0", "")
    if t.count(",") + t.count(".") > 1:
        raise OddsInputError(f"Bitte nur einen Dezimaltrenner verwenden (z. B. {example}).")
    t = t.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        raise OddsInputError(f"Bitte eine Linie eingeben (z. B. {example}).")
    value = float(t)
    if abs(value * 2 - round(value * 2)) > 1e-9:
        raise OddsInputError(f"Nur ganze und halbe Linien erlaubt (z. B. {example.split(',')[0]} oder {example}).")
    if not (lo <= value <= hi):
        raise OddsInputError(f"Die Linie ist unrealistisch (erwartet {int(lo)} bis {int(hi)} Punkte).")
    return value


def parse_threshold_input(text) -> int:
    """Meilenstein-Schwelle (Punkte, mindestens so viele): ganze Zahl von 1 bis 80 ('19' oder '+19')."""
    if text is None or not str(text).strip():
        raise OddsInputError("Schwelle fehlt.")
    t = str(text).strip().replace(" ", "").lstrip("+")
    if not re.fullmatch(r"\d+", t):
        raise OddsInputError("Die Schwelle muss eine ganze Zahl sein (z. B. 19).")
    v = int(t)
    if not (MIN_THRESHOLD <= v <= MAX_THRESHOLD):
        raise OddsInputError(f"Die Schwelle ist unrealistisch (erwartet {MIN_THRESHOLD} bis {MAX_THRESHOLD}).")
    return v


def parse_player_line_input(text) -> float:
    """Spielerpunkte-Linie: ganze und halbe Linien von 3 bis 80 (z. B. 24,5)."""
    return _parse_ou_line(text, MIN_PLAYER_LINE, MAX_PLAYER_LINE, "24,5")


def round_half(value: float) -> float:
    """Auf 0,5 runden (Haelften weg von null): -4,3 -> -4,5; -4,25 -> -4,5; 3,1 -> 3,0."""
    return math.copysign(math.floor(abs(value) * 2 + 0.5) / 2, value) + 0.0


def next_line(line_home: float) -> float:
    """Naechste weitere Linie: 1,0 Punkt weiter Richtung Favorit. Heim-Favorit (Linie < 0): Heim -1; Gast-Favorit (Linie > 0):
    Gast -1, also Heim +1; Pick'em (0): Favorit ist die Heim-Seite (Heim -1)."""
    return line_home - 1.0 if line_home <= 0 else line_home + 1.0


def parse_utc(text) -> float | None:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def normalize_start(start) -> str | None:
    """Anpfiff als 'YYYY-MM-DDTHH:MM:SSZ' (UTC); None, wenn unbekannt/ungueltig."""
    ts = parse_utc(start) if start else None
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def game_key(game_date: str, start_utc: str, home: str, away: str) -> str:
    """Schluessel: Spieldatum (US) + Anpfiffzeit (UTC) + Heim + Gast."""
    return f"{game_date}|{normalize_start(start_utc)}|{home}|{away}"


def is_editable(start_utc, now: float | None = None) -> bool:
    """Nur vor dem Anpfiff. Unbekannter Anpfiff gilt als gesperrt."""
    ts = parse_utc(start_utc) if start_utc else None
    return ts is not None and (now if now is not None else time.time()) < ts


def iso_now(now: float | None = None) -> str:
    dt = datetime.fromtimestamp(now if now is not None else time.time()).astimezone()
    return dt.isoformat(timespec="seconds")


# ------------------------------------------------------------------------------ Datei
def _empty() -> dict:
    return {"version": STORE_VERSION, "format": FORMAT, "markets": dict(MARKETS), "last_bookmaker": {},
            "updated_at": None, "entries": {}}


def load() -> dict:
    """Liest die Datei (leer, wenn sie fehlt). Defekte Datei: leere Struktur mit 'error'-Hinweis (nichts wird veraendert)."""
    path = store_path()
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
            raise ValueError("Struktur")
    except Exception:
        d = _empty()
        d["error"] = "Die Datei pre_match_entries.json ist nicht lesbar."
        return d
    data.setdefault("last_bookmaker", {})
    return data


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _daily_copy(now: float | None) -> None:
    try:
        day = datetime.fromtimestamp(now if now is not None else time.time()).astimezone().strftime("%Y-%m-%d")
        dest = history_dir() / f"pre_match_entries_{day}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(store_path(), tmp)
        os.replace(tmp, dest)
    except Exception:
        pass            # die Tageskopie darf das Speichern nie scheitern lassen


def _load_for_write() -> dict:
    """Aktueller Stand fuer eine Aenderung. Defekte Datei wird als .corrupt-<Zeit> gesichert, dann neu begonnen.
    Aeltere Version (z. B. 1): vorher als Kopie sichern (history/), dann auf STORE_VERSION heben (Inhalt bleibt)."""
    path = store_path()
    if not path.exists():
        return _empty()
    data = load()
    if data.get("error"):
        backup = path.with_name(f"{path.stem}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}")
        try:
            shutil.copyfile(path, backup)
        except OSError as e:
            raise StoreError("Defekte Datei konnte nicht gesichert werden; es wurde nichts geändert.") from e
        d = _empty()
        d["recovered_from_corrupt"] = backup.name
        return d
    version = int(data.get("version", 0) or 0)
    if version > STORE_VERSION:
        raise StoreError("Die Datei stammt aus einer neueren Programmversion; es wurde nichts geändert.")
    if version < STORE_VERSION:
        backup = history_dir() / f"{path.stem}.v{version}_vor_Upgrade_{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}"
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, backup)
        except OSError as e:
            raise StoreError("Die alte Dateiversion konnte nicht gesichert werden; es wurde nichts geändert.") from e
        data["version"] = STORE_VERSION
        data["markets"] = {**data.get("markets", {}), **MARKETS}
        data["upgraded_from_version"] = version
        data["upgrade_backup"] = backup.name
    return data


def get_entry(key: str) -> dict | None:
    return load()["entries"].get(key)


def last_bookmaker(market: str = "winner_incl_ot") -> str:
    return load().get("last_bookmaker", {}).get(market, "")


# ------------------------------------------------------------------------------ Speichern
def save_market(game_date: str, start_utc: str, home: str, away: str, market: str,
                home_odds_text, away_odds_text, bookmaker: str = "", now: float | None = None) -> dict:
    """Speichert die Quoten eines Marktes. Gibt {'status': 'saved'|'unchanged', 'key', 'entry'} zurueck.
    Wirft OddsInputError (Eingabe), GameStartedError (Spiel begonnen) oder StoreError (Datei)."""
    if market != WINNER:
        raise OddsInputError("Unbekannter Markt (Spread: save_spread).")
    home_odds = parse_odds_input(home_odds_text)          # erst pruefen, dann irgendetwas anfassen
    away_odds = parse_odds_input(away_odds_text)
    bookmaker = clean_bookmaker(bookmaker)
    start_norm = normalize_start(start_utc)
    now = now if now is not None else time.time()
    if start_norm is None:
        raise GameStartedError("Anpfiff unbekannt: keine Eingabe möglich.")
    if not is_editable(start_norm, now):
        raise GameStartedError("Das Spiel hat bereits begonnen: keine Änderung mehr möglich.")
    key = game_key(game_date, start_norm, home, away)
    with _lock:
        data = _load_for_write()
        entry = data["entries"].setdefault(key, {"game_date": game_date, "start_utc": start_norm, "home": home, "away": away, "markets": {}})
        stamp = iso_now(now)
        m = entry["markets"].get(market)
        if m and (m["home_odds"], m["away_odds"], m.get("bookmaker", "")) == (home_odds, away_odds, bookmaker):
            if bookmaker and data.get("last_bookmaker", {}).get(market) != bookmaker:
                data.setdefault("last_bookmaker", {})[market] = bookmaker
                data["updated_at"] = stamp
                try:
                    _atomic_write(store_path(), data)
                except Exception as e:
                    raise StoreError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
            return {"status": "unchanged", "key": key, "entry": copy.deepcopy(entry)}
        rev = {"home_odds": home_odds, "away_odds": away_odds, "bookmaker": bookmaker, "saved_at": stamp}
        if m is None:
            m = {"entered_at": stamp, "revisions": []}
            entry["markets"][market] = m
        m.update(home_odds=home_odds, away_odds=away_odds, bookmaker=bookmaker, updated_at=stamp)
        m["revisions"].append(rev)
        if bookmaker:
            data.setdefault("last_bookmaker", {})[market] = bookmaker
        data["updated_at"] = stamp
        data["version"] = STORE_VERSION
        data["markets"] = {**data.get("markets", {}), **MARKETS}
        try:
            _atomic_write(store_path(), data)
        except Exception as e:
            raise StoreError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
        _daily_copy(now)
        return {"status": "saved", "key": key, "entry": copy.deepcopy(entry), "recovered": data.get("recovered_from_corrupt")}


# ------------------------------------------------------------------------------ Spread
def active_spread_lines(entry: dict | None) -> list[dict]:
    """Aktive Spread-Linien eines Eintrags (Hauptlinie zuerst, dann weitere in der Reihenfolge des Anlegens)."""
    lines = ((entry or {}).get("markets", {}).get(SPREAD) or {}).get("lines", [])
    return [l for l in lines if l.get("active", True)]


def active_total_lines(entry: dict | None) -> list[dict]:
    """Aktive Total-Linien eines Eintrags (Hauptlinie zuerst, dann weitere in der Reihenfolge des Anlegens)."""
    lines = ((entry or {}).get("markets", {}).get(TOTAL) or {}).get("lines", [])
    return [l for l in lines if l.get("active", True)]


def team_total_lines(entry: dict | None, side: str, active_only: bool = True) -> list[dict]:
    """Team-Total-Linien eines Teams ('away'/'home'); standardmaessig nur aktive (Hauptlinie zuerst)."""
    lines = ((((entry or {}).get("markets", {}).get(TEAM_TOTALS) or {}).get(side)) or {}).get("lines", [])
    return [l for l in lines if l.get("active", True)] if active_only else list(lines)


def derive_team_suggestions(total: float | None, line_home: float | None) -> dict | None:
    """Rechnerischer Vorschlag der Team-Total-Hauptlinien aus Vorab-Total und Spread-Linie (aus Heim-Sicht):
    Heim = (Total - Linie_Heim) / 2, Gast = (Total + Linie_Heim) / 2, je auf 0,5 gerundet. Fehlt eines von beiden: None.
    Rueckgabe {'away': {'line', 'line_rounded', 'source': 'derived'}, 'home': {...}}."""
    if total is None or line_home is None:
        return None
    raw = {"home": round((float(total) - float(line_home)) / 2, 2), "away": round((float(total) + float(line_home)) / 2, 2)}
    return {side: {"line": v, "line_rounded": round_half(v), "source": "derived"} for side, v in raw.items()}


def active_player_blocks(entry: dict | None) -> list[dict]:
    """Aktive Spielerblocks (Spielerpunkte) eines Eintrags in der Reihenfolge des Anlegens."""
    return [b for b in ((entry or {}).get("markets", {}).get(PLAYER_POINTS) or {}).get("players", []) if b.get("active", True)]


def player_lines(block: dict) -> list[dict]:
    return [l for l in block.get("lines", []) if l.get("active", True)]


def saved_summary(entry: dict | None) -> tuple[bool, str | None]:
    """(irgendein Markt gespeichert?, Zeitstempel der letzten Speicherung irgendeines Marktes)."""
    if not entry:
        return False, None
    stamps, saved = [], False
    w = entry.get("markets", {}).get(WINNER)
    if w:
        saved = True
        stamps.append(w.get("updated_at"))
    sp = entry.get("markets", {}).get(SPREAD)
    if sp:
        if any(l.get("active", True) for l in sp.get("lines", [])):
            saved = True
        for l in sp.get("lines", []):
            stamps.append(l.get("updated_at"))
            stamps.append(l.get("removed_at"))
    tt = entry.get("markets", {}).get(TOTAL)
    if tt:
        if any(l.get("active", True) for l in tt.get("lines", [])):
            saved = True
        for l in tt.get("lines", []):
            stamps.append(l.get("updated_at"))
            stamps.append(l.get("removed_at"))
    pp = entry.get("markets", {}).get(PLAYER_POINTS)
    if pp:
        for b in pp.get("players", []):
            if b.get("active", True) and any(l.get("active", True) for l in b.get("lines", [])):
                saved = True
            stamps.append(b.get("updated_at"))
            stamps.append(b.get("removed_at"))
            for l in b.get("lines", []):
                stamps.append(l.get("updated_at"))
                stamps.append(l.get("removed_at"))
    tm = entry.get("markets", {}).get(TEAM_TOTALS)
    if tm:
        for side in TEAMS:
            ls = (tm.get(side) or {}).get("lines", [])
            if any(l.get("active", True) for l in ls):
                saved = True
            for l in ls:
                stamps.append(l.get("updated_at"))
                stamps.append(l.get("removed_at"))
    stamps = [x for x in stamps if x]
    last = max(stamps, key=lambda x: datetime.fromisoformat(x).timestamp()) if stamps else None
    return saved, last


def _spread_market(entry: dict) -> dict:
    return entry["markets"].setdefault(SPREAD, {"entered_at": None, "updated_at": None, "lines": []})


def _line_values(line_home: float, home_odds: float, away_odds: float, bookmaker: str) -> dict:
    return {"line_home": line_home, "line_away": (-line_home) + 0.0, "home_odds": home_odds, "away_odds": away_odds, "bookmaker": bookmaker}


def _prepare_game(game_date, start_utc, now):
    start_norm = normalize_start(start_utc)
    if start_norm is None:
        raise GameStartedError("Anpfiff unbekannt: keine Eingabe möglich.")
    if not is_editable(start_norm, now):
        raise GameStartedError("Das Spiel hat bereits begonnen: keine Änderung mehr möglich.")
    return start_norm


def _apply_spread(market: dict, parsed: list, suggestion: dict | None, stamp: str) -> tuple[int, list]:
    """Wendet geprueft geparste Spread-Zeilen auf den Markt an (nur im Speicher). Unveraenderte Zeilen erzeugen keine Revision."""
    changed, results = 0, []
    for rid, line_home, home_odds, away_odds, bookmaker in parsed:
        values = _line_values(line_home, home_odds, away_odds, bookmaker)
        existing = None
        if rid is not None:
            existing = next((l for l in market["lines"] if l["id"] == rid and l.get("active", True)), None)
            if existing is None and rid != "main":
                raise OddsInputError("Diese weitere Linie existiert nicht mehr.")
        sugg = copy.deepcopy(suggestion) if (rid == "main" and suggestion) else None
        if existing is not None:
            cur = {k: existing.get(k) for k in values}
            if cur == values:
                results.append((existing["id"], "unchanged"))
                continue
            existing.update(values)
            existing["updated_at"] = stamp
            if rid == "main":
                existing["market_suggestion"] = sugg
            existing["revisions"].append({"action": "saved", **values, "saved_at": stamp, "market_suggestion": sugg})
            results.append((existing["id"], "saved"))
        else:
            if rid == "main":
                new_id, role = "main", "main"
                market["lines"].insert(0, None)       # Platzhalter, Hauptlinie immer oben
            else:
                n = 1 + max([int(l["id"][1:]) for l in market["lines"] if l and l["id"].startswith("x") and l["id"][1:].isdigit()] or [0])
                new_id, role = f"x{n}", "extra"
            new = {"id": new_id, "role": role, "active": True, **values, "entered_at": stamp, "updated_at": stamp,
                   "market_suggestion": sugg, "revisions": [{"action": "saved", **values, "saved_at": stamp, "market_suggestion": sugg}]}
            if rid == "main":
                market["lines"][0] = new
            else:
                market["lines"].append(new)
            results.append((new_id, "saved"))
        changed += 1
    return changed, results


def _apply_winner(entry: dict, home_odds: float, away_odds: float, bookmaker: str, stamp: str) -> bool:
    """Wendet die Sieger-Quoten an (nur im Speicher). False, wenn unveraendert (keine neue Revision)."""
    m = entry["markets"].get(WINNER)
    if m and (m["home_odds"], m["away_odds"], m.get("bookmaker", "")) == (home_odds, away_odds, bookmaker):
        return False
    if m is None:
        m = {"entered_at": stamp, "revisions": []}
        entry["markets"][WINNER] = m
    m.update(home_odds=home_odds, away_odds=away_odds, bookmaker=bookmaker, updated_at=stamp)
    m["revisions"].append({"home_odds": home_odds, "away_odds": away_odds, "bookmaker": bookmaker, "saved_at": stamp})
    return True


def save_spread(game_date: str, start_utc: str, home: str, away: str, rows: list[dict],
                suggestion: dict | None = None, now: float | None = None) -> dict:
    """Speichert die Spread-Linien eines Spiels.

    rows: Liste von {'id': 'main' | <vorhandene Linien-ID> | None (neue weitere Linie), 'line', 'home_odds', 'away_odds',
          'bookmaker'} (Texte wie eingegeben); die Hauptlinie ('main') steht zuerst und ist Pflicht. Leere neue Zeilen
          (id None) werden uebersprungen. suggestion: Marktvorschlag zum Zeitpunkt des Speicherns (nur fuer die Hauptlinie
          festgehalten), z. B. {'line_home': -4.33, 'line_home_rounded': -4.5, 'source': 'cache_vorab'} oder None.
    Wirft OddsInputError, GameStartedError oder StoreError; vor jeder Dateiaenderung wird alles geprueft."""
    now = now if now is not None else time.time()
    parsed = []
    for i, row in enumerate(rows):
        rid = row.get("id")
        label = "Hauptlinie" if rid == "main" else f"Weitere Linie {i}"
        texts = [row.get("line"), row.get("home_odds"), row.get("away_odds")]
        if rid is None and not any(str(t or "").strip() for t in texts):
            continue
        try:
            parsed.append((rid, parse_line_input(row.get("line")), parse_odds_input(row.get("home_odds")),
                           parse_odds_input(row.get("away_odds")), clean_bookmaker(row.get("bookmaker"))))
        except OddsInputError as e:
            raise OddsInputError(f"{label}: {e}") from None
    if not parsed or parsed[0][0] != "main":
        raise OddsInputError("Hauptlinie fehlt.")
    start_norm = _prepare_game(game_date, start_utc, now)
    key = game_key(game_date, start_norm, home, away)
    with _lock:
        data = _load_for_write()
        entry = data["entries"].setdefault(key, {"game_date": game_date, "start_utc": start_norm, "home": home, "away": away, "markets": {}})
        market = _spread_market(entry)
        stamp = iso_now(now)
        changed, results = _apply_spread(market, parsed, suggestion, stamp)
        if changed == 0:
            return {"status": "unchanged", "key": key, "entry": copy.deepcopy(entry), "lines": results}
        market["entered_at"] = market.get("entered_at") or stamp
        market["updated_at"] = stamp
        book = next((p[4] for p in parsed if p[4]), "")
        if book:
            data.setdefault("last_bookmaker", {})[SPREAD] = book
        data["updated_at"] = stamp
        data["markets"] = {**data.get("markets", {}), **MARKETS}
        try:
            _atomic_write(store_path(), data)
        except Exception as e:
            raise StoreError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
        _daily_copy(now)
        return {"status": "saved", "key": key, "entry": copy.deepcopy(entry), "lines": results, "recovered": data.get("recovered_from_corrupt")}


def remove_spread_line(game_date: str, start_utc: str, home: str, away: str, line_id: str, now: float | None = None) -> dict:
    """Entfernt eine WEITERE Spread-Linie: sie wird als inaktiv markiert und die Entfernung als Revision festgehalten
    (nichts wird geloescht). Die Hauptlinie kann nur geaendert, nicht entfernt werden."""
    now = now if now is not None else time.time()
    if line_id == "main":
        raise OddsInputError("Die Hauptlinie kann nicht entfernt werden.")
    start_norm = _prepare_game(game_date, start_utc, now)
    key = game_key(game_date, start_norm, home, away)
    with _lock:
        data = _load_for_write()
        entry = data["entries"].get(key)
        line = next((l for l in ((entry or {}).get("markets", {}).get(SPREAD) or {}).get("lines", []) if l["id"] == line_id and l.get("active", True)), None)
        if line is None:
            raise OddsInputError("Diese Linie existiert nicht (mehr).")
        stamp = iso_now(now)
        line["active"] = False
        line["removed_at"] = stamp
        line["updated_at"] = stamp
        line["revisions"].append({"action": "removed", **{k: line.get(k) for k in ("line_home", "line_away", "home_odds", "away_odds", "bookmaker")},
                                  "saved_at": stamp, "market_suggestion": None})
        entry["markets"][SPREAD]["updated_at"] = stamp
        data["updated_at"] = stamp
        data["markets"] = {**data.get("markets", {}), **MARKETS}
        try:
            _atomic_write(store_path(), data)
        except Exception as e:
            raise StoreError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
        _daily_copy(now)
        return {"status": "removed", "key": key, "entry": copy.deepcopy(entry)}


# ------------------------------------------------------------------------------ Total
def _total_market(entry: dict) -> dict:
    return entry["markets"].setdefault(TOTAL, {"entered_at": None, "updated_at": None, "lines": []})


def _total_values(line: float, over_odds: float, under_odds: float, bookmaker: str) -> dict:
    return {"line": line, "over_odds": over_odds, "under_odds": under_odds, "bookmaker": bookmaker}


def _apply_total(market: dict, parsed: list, suggestion: dict | None, stamp: str) -> tuple[int, list]:
    """Wendet geprueft geparste Total-Zeilen an (nur im Speicher). parsed: (id|None, line, over, under, bookmaker, direction).
    Unveraenderte Zeilen erzeugen keine Revision."""
    changed, results = 0, []
    for rid, line, over, under, bookmaker, direction in parsed:
        values = _total_values(line, over, under, bookmaker)
        existing = None
        if rid is not None:
            existing = next((l for l in market["lines"] if l and l["id"] == rid and l.get("active", True)), None)
            if existing is None and rid != "main":
                raise OddsInputError("Diese weitere Linie existiert nicht mehr.")
        sugg = copy.deepcopy(suggestion) if (rid == "main" and suggestion) else None
        if existing is not None:
            if {k: existing.get(k) for k in values} == values:
                results.append((existing["id"], "unchanged"))
                continue
            existing.update(values)
            existing["updated_at"] = stamp
            if rid == "main":
                existing["market_suggestion"] = sugg
            existing["revisions"].append({"action": "saved", **values, "saved_at": stamp, "market_suggestion": sugg})
            results.append((existing["id"], "saved"))
        else:
            if rid == "main":
                new_id, role, direction = "main", "main", None
                market["lines"].insert(0, None)       # Platzhalter, Hauptlinie immer oben
            else:
                n = 1 + max([int(l["id"][1:]) for l in market["lines"] if l and l["id"].startswith("x") and l["id"][1:].isdigit()] or [0])
                new_id, role = f"x{n}", "extra"
            new = {"id": new_id, "role": role, "direction": direction, "active": True, **values, "entered_at": stamp, "updated_at": stamp,
                   "market_suggestion": sugg, "revisions": [{"action": "saved", **values, "saved_at": stamp, "market_suggestion": sugg}]}
            if rid == "main":
                market["lines"][0] = new
            else:
                market["lines"].append(new)
            results.append((new_id, "saved"))
        changed += 1
    return changed, results


def _remove_ou_line(game_date, start_utc, home, away, line_id, now, locate) -> dict:
    """Entfernt eine WEITERE Over/Under-Linie (inaktiv + Revision 'removed'; nichts wird geloescht). locate(entry) -> (Markt-Dict mit 'lines',
    Dict mit 'updated_at'). Die Hauptlinie kann nicht entfernt werden."""
    now = now if now is not None else time.time()
    if line_id == "main":
        raise OddsInputError("Die Hauptlinie kann nicht entfernt werden.")
    start_norm = _prepare_game(game_date, start_utc, now)
    key = game_key(game_date, start_norm, home, away)
    with _lock:
        data = _load_for_write()
        entry = data["entries"].get(key)
        sub, top = locate(entry) if entry else ({"lines": []}, {})
        line = next((l for l in sub.get("lines", []) if l["id"] == line_id and l.get("active", True)), None)
        if line is None:
            raise OddsInputError("Diese Linie existiert nicht (mehr).")
        stamp = iso_now(now)
        line["active"] = False
        line["removed_at"] = stamp
        line["updated_at"] = stamp
        line["revisions"].append({"action": "removed", **{k: line.get(k) for k in ("line", "over_odds", "under_odds", "bookmaker")},
                                  "saved_at": stamp, "market_suggestion": None})
        top["updated_at"] = stamp
        data["updated_at"] = stamp
        data["version"] = STORE_VERSION
        data["markets"] = {**data.get("markets", {}), **MARKETS}
        try:
            _atomic_write(store_path(), data)
        except Exception as e:
            raise StoreError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
        _daily_copy(now)
        return {"status": "removed", "key": key, "entry": copy.deepcopy(entry)}


def remove_total_line(game_date: str, start_utc: str, home: str, away: str, line_id: str, now: float | None = None) -> dict:
    """Entfernt eine WEITERE Total-Linie (inaktiv + Revision 'removed')."""
    def locate(entry):
        m = (entry.get("markets") or {}).get(TOTAL) or {"lines": []}
        return m, m
    return _remove_ou_line(game_date, start_utc, home, away, line_id, now, locate)


def remove_team_total_line(game_date: str, start_utc: str, home: str, away: str, side: str, line_id: str, now: float | None = None) -> dict:
    """Entfernt eine WEITERE Team-Total-Linie eines Teams ('away'/'home') (inaktiv + Revision 'removed')."""
    if side not in TEAMS:
        raise OddsInputError("Unbekanntes Team.")
    def locate(entry):
        m = (entry.get("markets") or {}).get(TEAM_TOTALS) or {}
        return m.get(side) or {"lines": []}, m
    return _remove_ou_line(game_date, start_utc, home, away, line_id, now, locate)


def _team_market(entry: dict, home: str, away: str) -> dict:
    m = entry["markets"].setdefault(TEAM_TOTALS, {"entered_at": None, "updated_at": None})
    m.setdefault("away", {"team": away, "lines": []})
    m.setdefault("home", {"team": home, "lines": []})
    return m


def _validate_total(rows: list[dict] | None, saved_lines: list[dict], parse=None, name: str = "Total", main_label: str | None = None):
    """None = Markt nicht ausgefuellt. Eine Zeile gilt als ausgefuellt, wenn mindestens eine Quote steht oder sie schon gespeichert ist.
    Prueft Format, Plausibilitaet, doppelte Linien (je Spiel nur einmal) und das Maximum je Richtung. Mehrere Fehler werden gesammelt.
    Auch fuer Team Totals (parse=parse_team_total_input, name='Team Totals · <Team>', je Team getrennt)."""
    if not rows:
        return None
    parse = parse or parse_total_input
    main_label = main_label or f"{name} · Hauptlinie"
    saved_ids = {l["id"] for l in saved_lines}
    parsed, errors, extras = [], [], 0
    for row in rows:
        rid = row.get("id")
        if rid != "main":
            extras += 1
        label = main_label if rid == "main" else f"{name} · Weitere Linie {extras}"
        odds_filled = any(str(row.get(k) or "").strip() for k in ("over_odds", "under_odds"))
        if not odds_filled and rid not in saved_ids:
            continue
        direction = row.get("direction") if rid != "main" else None
        if rid is not None and rid != "main":
            direction = next((l.get("direction") for l in saved_lines if l["id"] == rid), direction)
        try:
            if rid != "main" and direction not in ("higher", "lower"):
                raise OddsInputError("Richtung der Linie fehlt (höher oder niedriger).")
            for key, nm in (("over_odds", "Quote Over"), ("under_odds", "Quote Under")):
                if not str(row.get(key) or "").strip():
                    raise OddsInputError(f"{nm} fehlt.")
            parsed.append((rid, parse(row.get("line")), parse_odds_input(row.get("over_odds")),
                           parse_odds_input(row.get("under_odds")), clean_bookmaker(row.get("bookmaker")), direction))
        except OddsInputError as e:
            errors.append(f"{label}: {e}")
    if errors:
        raise CardInputError(errors)
    if not parsed:
        return None
    if parsed[0][0] != "main":
        raise OddsInputError(f"{main_label}: Linie und Quoten fehlen.")
    edited = {p[0] for p in parsed if p[0] is not None}
    final = [(l["id"], l["line"], l.get("direction")) for l in saved_lines if l["id"] not in edited] + [(p[0], p[1], p[5]) for p in parsed]
    seen = {}
    for rid, line, _d in final:
        seen[line] = seen.get(line, 0) + 1
    dup = sorted(v for v, n in seen.items() if n > 1)
    if dup:
        raise CardInputError([f"{name}: Die Linie {str(v).rstrip('0').rstrip('.').replace('.', ',')} kommt mehrfach vor "
                              f"(jede Linie nur einmal pro Spiel und Markt)." for v in dup])
    for d, word in (("higher", "höhere"), ("lower", "niedrigere")):
        if sum(1 for _r, _l, dd in final if dd == d) > MAX_TOTAL_PER_DIRECTION:
            raise CardInputError([f"{name}: höchstens {MAX_TOTAL_PER_DIRECTION} {word} Linien."])
    return parsed


# ------------------------------------------------------------------------------ Spielerpunkte
def _fmt_value(mode: str, v) -> str:
    return f"+{int(v)}" if mode == "milestones" else str(v).rstrip("0").rstrip(".").replace(".", ",") if float(v) != int(v) else f"{int(v)},0"


def _row_values_pp(mode: str, parsed: tuple) -> dict:
    """parsed = (id, value, odds..., bookmaker) -> Werte-Dict einer Zeile (je nach Modus)."""
    if mode == "milestones":
        return {"threshold": parsed[1], "odds": parsed[2], "bookmaker": parsed[3]}
    return {"line": parsed[1], "over_odds": parsed[2], "under_odds": parsed[3], "bookmaker": parsed[4]}


def _validate_players(blocks: list[dict] | None, saved_blocks: list[dict]):
    """None = Markt nicht ausgefuellt. Ein Block gilt als ausgefuellt, wenn mindestens eine Quote steht (oder er gespeichert ist); dann muss ein Spieler
    gewaehlt sein und jede ausgefuellte/gespeicherte Zeile vollstaendig und gueltig. Doppelte Schwellen/Linien je Spieler, derselbe Spieler in
    zwei Bloecken und die Maxima werden abgelehnt. Fehler werden gesammelt und nennen Markt und Spieler."""
    if not blocks:
        return None
    by_id = {b["id"]: b for b in saved_blocks}
    errors, out, seen_pid = [], [], {}
    for n, blk in enumerate(blocks, start=1):
        bid = blk.get("block_id")
        saved = by_id.get(bid) if bid else None
        mode = blk.get("mode") or "milestones"
        name = (blk.get("name") or "").strip() or f"Spieler {n}"
        label = f"Spielerpunkte · {name}"
        rows = blk.get("rows") or []
        odds_keys = ("odds",) if mode == "milestones" else ("over_odds", "under_odds")
        filled = any(str(r.get(k) or "").strip() for r in rows for k in odds_keys)
        if not filled and saved is None:
            continue
        if mode not in MODES:
            errors.append(f"{label}: Unbekannter Modus.")
            continue
        pid = blk.get("person_id")
        if pid in (None, ""):
            errors.append(f"Spielerpunkte · Block {n}: Bitte einen Spieler wählen.")
            continue
        if saved is not None and (int(saved["person_id"]) != int(pid) or saved.get("mode") != mode):
            errors.append(f"{label}: Spieler und Modus eines gespeicherten Blocks können nicht geändert werden (Block entfernen und neu anlegen).")
            continue
        saved_rows = {l["id"]: l for l in player_lines(saved)} if saved else {}
        parsed, row_errors = [], []
        for r in rows:
            rid = r.get("id")
            touched = any(str(r.get(k) or "").strip() for k in odds_keys) or rid in saved_rows
            if not touched:
                continue
            try:
                if mode == "milestones":
                    v = parse_threshold_input(r.get("value"))
                    if not str(r.get("odds") or "").strip():
                        raise OddsInputError(f"Quote bei +{v} fehlt.")
                    parsed.append((rid, v, parse_odds_input(r.get("odds")), clean_bookmaker(r.get("bookmaker"))))
                else:
                    v = parse_player_line_input(r.get("value"))
                    lab = _fmt_value(mode, v)
                    for key, nm in (("over_odds", "Over"), ("under_odds", "Under")):
                        if not str(r.get(key) or "").strip():
                            raise OddsInputError(f"Quote {nm} bei {lab} fehlt.")
                    parsed.append((rid, v, parse_odds_input(r.get("over_odds")), parse_odds_input(r.get("under_odds")), clean_bookmaker(r.get("bookmaker"))))
            except OddsInputError as e:
                row_errors.append(f"{label}: {e}")
        errors.extend(row_errors)
        if row_errors:
            continue
        if not parsed:
            continue
        edited = {x[0] for x in parsed if x[0] is not None}
        final_vals = [l["threshold" if mode == "milestones" else "line"] for i2, l in saved_rows.items() if i2 not in edited] + [x[1] for x in parsed]
        dups = sorted({v for v in final_vals if final_vals.count(v) > 1})
        if dups:
            errors.extend(f"{label}: {'Schwelle' if mode == 'milestones' else 'Linie'} {_fmt_value(mode, v)} kommt mehrfach vor (nur einmal je Spieler)." for v in dups)
            continue
        cap = MAX_MILESTONES if mode == "milestones" else MAX_PLAYER_LINES
        if len(final_vals) > cap:
            errors.append(f"{label}: höchstens {cap} {'Meilensteine' if mode == 'milestones' else 'Linien'}.")
            continue
        if pid in seen_pid:
            errors.append(f"Spielerpunkte: {name} ist doppelt gewählt (ein Block je Spieler und Spiel).")
            continue
        seen_pid[pid] = name
        out.append({"block_id": bid, "person_id": int(pid), "name": name, "team": blk.get("team") or "", "team_abbreviation": blk.get("team_abbreviation") or "",
                    "mode": mode, "rows": parsed})
    if errors:
        raise CardInputError(errors)
    if not out:
        return None
    others = {b["person_id"] for b in saved_blocks if b["id"] not in {o["block_id"] for o in out if o["block_id"]}}
    clash = [o["name"] for o in out if o["person_id"] in others]
    if clash:
        raise CardInputError([f"Spielerpunkte: {c} ist doppelt gewählt (ein Block je Spieler und Spiel)." for c in clash])
    if len(out) + len(others) > MAX_PLAYERS:
        raise CardInputError([f"Spielerpunkte: höchstens {MAX_PLAYERS} Spieler je Spiel."])
    return out


def _apply_players(market: dict, parsed_blocks: list, stamp: str, roster_fetched_at: str | None) -> int:
    """Wendet geprueft geparste Spielerbloecke an (nur im Speicher). Unveraenderte Zeilen erzeugen keine Revision. Rueckgabe: Zahl der Aenderungen."""
    changed = 0
    for pb in parsed_blocks:
        mode = pb["mode"]
        block = next((b for b in market["players"] if b["id"] == pb["block_id"] and b.get("active", True)), None) if pb["block_id"] else None
        if pb["block_id"] and block is None:
            raise OddsInputError("Dieser Spielerblock existiert nicht mehr.")
        if block is None:
            n = 1 + max([int(b["id"][1:]) for b in market["players"] if b["id"][1:].isdigit()] or [0])
            block = {"id": f"p{n}", "person_id": pb["person_id"], "name": pb["name"], "team": pb["team"], "team_abbreviation": pb["team_abbreviation"], "mode": mode,
                     "active": True, "roster_fetched_at": roster_fetched_at, "entered_at": stamp, "updated_at": stamp, "lines": []}
            market["players"].append(block)
        block_changed = False
        for parsed in pb["rows"]:
            rid = parsed[0]
            values = _row_values_pp(mode, parsed)
            existing = next((l for l in block["lines"] if l["id"] == rid and l.get("active", True)), None) if rid else None
            if rid and existing is None:
                raise OddsInputError("Diese Zeile existiert nicht mehr.")
            if existing is not None:
                if {k: existing.get(k) for k in values} == values:
                    continue
                existing.update(values)
                existing["updated_at"] = stamp
                existing["revisions"].append({"action": "saved", **values, "saved_at": stamp})
            else:
                n = 1 + max([int(l["id"][1:]) for l in block["lines"] if l["id"][1:].isdigit()] or [0])
                block["lines"].append({"id": f"x{n}", "active": True, **values, "entered_at": stamp, "updated_at": stamp,
                                       "revisions": [{"action": "saved", **values, "saved_at": stamp}]})
            block_changed = True
        if block_changed:
            block["updated_at"] = stamp
            changed += 1
    return changed


def _player_market(entry: dict) -> dict:
    return entry["markets"].setdefault(PLAYER_POINTS, {"entered_at": None, "updated_at": None, "players": []})


def _remove_player_part(game_date, start_utc, home, away, block_id, line_id, now) -> dict:
    """Entfernt eine Zeile (line_id) oder den ganzen Spielerblock (line_id None): inaktiv + Revision 'removed', nichts wird geloescht."""
    now = now if now is not None else time.time()
    start_norm = _prepare_game(game_date, start_utc, now)
    key = game_key(game_date, start_norm, home, away)
    with _lock:
        data = _load_for_write()
        entry = data["entries"].get(key)
        market = ((entry or {}).get("markets") or {}).get(PLAYER_POINTS) or {"players": []}
        block = next((b for b in market["players"] if b["id"] == block_id and b.get("active", True)), None)
        if block is None:
            raise OddsInputError("Dieser Spieler existiert nicht (mehr).")
        if line_id is None:
            targets = [l for l in block["lines"] if l.get("active", True)]
        else:
            targets = [l for l in block["lines"] if l["id"] == line_id and l.get("active", True)]
            if not targets:
                raise OddsInputError("Diese Zeile existiert nicht (mehr).")
        stamp = iso_now(now)
        keys = ("threshold", "odds", "bookmaker") if block["mode"] == "milestones" else ("line", "over_odds", "under_odds", "bookmaker")
        for l in targets:
            l["active"] = False
            l["removed_at"] = stamp
            l["updated_at"] = stamp
            l["revisions"].append({"action": "removed", **{k: l.get(k) for k in keys}, "saved_at": stamp})
        if line_id is None or not any(l.get("active", True) for l in block["lines"]):
            block["active"] = False
            block["removed_at"] = stamp
        block["updated_at"] = stamp
        market["updated_at"] = stamp
        data["updated_at"] = stamp
        data["version"] = STORE_VERSION
        data["markets"] = {**data.get("markets", {}), **MARKETS}
        try:
            _atomic_write(store_path(), data)
        except Exception as e:
            raise StoreError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
        _daily_copy(now)
        return {"status": "removed", "key": key, "entry": copy.deepcopy(entry)}


def remove_player_line(game_date: str, start_utc: str, home: str, away: str, block_id: str, line_id: str, now: float | None = None) -> dict:
    """Entfernt eine gespeicherte Zeile (Meilenstein oder Linie) eines Spielers (inaktiv + Revision). Ist es die letzte, wird der Block inaktiv."""
    return _remove_player_part(game_date, start_utc, home, away, block_id, line_id, now)


def remove_player_block(game_date: str, start_utc: str, home: str, away: str, block_id: str, now: float | None = None) -> dict:
    """Entfernt den ganzen gespeicherten Spielerblock (alle Zeilen inaktiv + Revision, Block inaktiv)."""
    return _remove_player_part(game_date, start_utc, home, away, block_id, None, now)


# ------------------------------------------------------------------------------ Eine Karte, ein Speichern
class CardInputError(OddsInputError):
    """Eine oder mehrere ausgefuellte Maerkte sind unvollstaendig/ungueltig; .errors enthaelt je eine Meldung mit Marktnamen."""
    def __init__(self, errors: list[str]):
        super().__init__(" ".join(errors))
        self.errors = list(errors)


def _validate_winner(winner: dict | None, has_saved: bool):
    """None = Markt nicht ausgefuellt (ueberspringen). Gespeicherte Maerkte werden immer geprueft (kein stilles Leeren)."""
    if winner is None:
        return None
    filled = any(str(winner.get(k) or "").strip() for k in ("home_odds", "away_odds"))
    if not filled and not has_saved:
        return None
    try:
        return (parse_odds_input(winner.get("home_odds")), parse_odds_input(winner.get("away_odds")), clean_bookmaker(winner.get("bookmaker")))
    except OddsInputError as e:
        raise OddsInputError(f"Sieger inkl. OT: {e}") from None


def _validate_spread(rows: list[dict] | None, saved_ids: set):
    """None = Markt nicht ausgefuellt. Eine Zeile gilt als ausgefuellt, wenn mindestens eine Quote steht oder sie schon gespeichert ist
    (nur eine vorbefuellte Linie ohne Quoten zaehlt nicht). Mehrere Fehler werden gesammelt."""
    if not rows:
        return None
    parsed, errors, extras = [], [], 0
    for row in rows:
        rid = row.get("id")
        if rid != "main":
            extras += 1
        label = "Spread · Hauptlinie" if rid == "main" else f"Spread · Weitere Linie {extras}"
        odds_filled = any(str(row.get(k) or "").strip() for k in ("home_odds", "away_odds"))
        if not odds_filled and rid not in saved_ids:
            continue
        try:
            parsed.append((rid, parse_line_input(row.get("line")), parse_odds_input(row.get("home_odds")),
                           parse_odds_input(row.get("away_odds")), clean_bookmaker(row.get("bookmaker"))))
        except OddsInputError as e:
            errors.append(f"{label}: {e}")
    if errors:
        raise CardInputError(errors)
    if not parsed:
        return None
    if parsed[0][0] != "main":
        raise OddsInputError("Spread · Hauptlinie: Linie und Quoten fehlen.")
    return parsed


def _entry_without(cur: dict | None, removals: list[tuple]) -> dict | None:
    """Kopie des Eintrags, in der die genannten Linien/Bloecke als entfernt gelten (nur fuer die Pruefung, nichts wird geschrieben).
    Eintraege: ('spread', id) | ('total', id) | ('team', side, id) | ('player_block', id) | ('player_line', block_id, line_id)."""
    if not cur or not removals:
        return cur
    e = copy.deepcopy(cur)
    mk = e.get("markets") or {}

    def off(lines, lid):
        for l in lines or []:
            if l.get("id") == lid:
                l["active"] = False
    for rm in removals:
        if rm[0] == "spread":
            off((mk.get(SPREAD) or {}).get("lines"), rm[1])
        elif rm[0] == "total":
            off((mk.get(TOTAL) or {}).get("lines"), rm[1])
        elif rm[0] == "team":
            off((((mk.get(TEAM_TOTALS) or {}).get(rm[1])) or {}).get("lines"), rm[2])
        else:
            for b in (mk.get(PLAYER_POINTS) or {}).get("players", []):
                if b.get("id") != rm[1]:
                    continue
                if rm[0] == "player_block":
                    b["active"] = False
                else:
                    off(b.get("lines"), rm[2])
                    if not any(l.get("active", True) for l in b.get("lines", [])):
                        b["active"] = False
    return e


def save_card(game_date: str, start_utc: str, home: str, away: str, winner: dict | None = None, spread_rows: list[dict] | None = None,
              suggestion: dict | None = None, total_rows: list[dict] | None = None, total_suggestion: dict | None = None,
              team_rows: dict | None = None, team_suggestion: dict | None = None, team_names: dict | None = None,
              player_blocks: list[dict] | None = None, roster_fetched_at: str | None = None, now: float | None = None,
              assume_removed: list[tuple] | None = None, dry_run: bool = False, source: str = SOURCE_HAND) -> dict:
    """Speichert alle ausgefuellten Maerkte eines Spiels in EINEM Schreibvorgang (alles oder nichts).

    winner:      {'home_odds', 'away_odds', 'bookmaker'} (Texte wie eingegeben) oder None
    spread_rows: wie bei save_spread; Zeilen ohne Quoten werden uebersprungen, ein Markt ohne ausgefuellte Zeile ebenfalls
    total_rows:  {'id': 'main' | vorhandene ID | None (neu), 'direction': 'higher'|'lower' (nur neue), 'line', 'over_odds', 'under_odds',
                  'bookmaker'}; total_suggestion: {'line', 'line_rounded', 'source'} oder None
    team_rows:   {'away': [Zeilen wie total_rows], 'home': [...]}; team_suggestion: {'away': {...}, 'home': {...}} (source 'derived') oder None;
                 team_names: {'away': 'Thunder', 'home': 'Spurs'} nur fuer die Meldungen
    player_blocks: Spielerpunkte, je Block {'block_id': 'p1'|None, 'person_id', 'name', 'team', 'team_abbreviation', 'mode': 'milestones'|'line',
                 'rows': [{'id': None|'x1', 'value': Schwelle/Linie, 'odds' (Meilenstein) | 'over_odds', 'under_odds', 'bookmaker'}]};
                 roster_fetched_at: Stand der Kaderdatei, mit der gewaehlt wurde
    assume_removed: Linien/Bloecke, die beim Pruefen als entfernt gelten (Formate siehe _entry_without); dry_run=True: nur pruefen, nie schreiben
                 (Rueckgabe {'status': 'checked'}). So kann man erst pruefen und danach erst entfernen.
    source:      'hand' (Standard, Revisionen bleiben ohne Feld "source") | 'auto' (neue Revisionen tragen "source": "auto"); Aufrufer der Automatik: save_auto
    Unvollstaendig/ungueltig -> CardInputError (mit Marktnamen), es wird nichts geschrieben.
    Rueckgabe: {'status': 'saved'|'unchanged', 'markets': {'winner_incl_ot'|'spread'|'total'|'team_totals'|'player_points': 'saved'|'unchanged'|'skipped'}, ...}"""
    now = now if now is not None else time.time()
    start_norm = _prepare_game(game_date, start_utc, now)                 # Sperre zuerst
    key = game_key(game_date, start_norm, home, away)
    cur = _entry_without((load().get("entries") or {}).get(key), assume_removed or [])
    saved_ids = {l["id"] for l in active_spread_lines(cur)}
    errors, w_vals, s_parsed = [], None, None
    try:
        w_vals = _validate_winner(winner, bool((cur or {}).get("markets", {}).get(WINNER)))
    except OddsInputError as e:
        errors.append(str(e))
    try:
        s_parsed = _validate_spread(spread_rows, saved_ids)
    except CardInputError as e:
        errors.extend(e.errors)
    except OddsInputError as e:
        errors.append(str(e))
    t_parsed = None
    try:
        t_parsed = _validate_total(total_rows, active_total_lines(cur))
    except CardInputError as e:
        errors.extend(e.errors)
    except OddsInputError as e:
        errors.append(str(e))
    tm_parsed = {}
    for side in TEAMS:
        nm = (team_names or {}).get(side) or (away if side == "away" else home)
        try:
            tm_parsed[side] = _validate_total((team_rows or {}).get(side), team_total_lines(cur, side), parse=parse_team_total_input,
                                              name=f"Team Totals · {nm}", main_label=f"Team Totals · {nm}")
        except CardInputError as e:
            errors.extend(e.errors)
        except OddsInputError as e:
            errors.append(str(e))
    pp_parsed = None
    try:
        pp_parsed = _validate_players(player_blocks, active_player_blocks(cur))
    except CardInputError as e:
        errors.extend(e.errors)
    except OddsInputError as e:
        errors.append(str(e))
    if errors:
        raise CardInputError(errors)
    if w_vals is None and s_parsed is None and t_parsed is None and pp_parsed is None and all(v is None for v in tm_parsed.values()):
        raise OddsInputError("Nichts eingetragen.")
    if dry_run:
        return {"status": "checked", "key": key}
    with _lock:
        data = _load_for_write()
        entry = data["entries"].setdefault(key, {"game_date": game_date, "start_utc": start_norm, "home": home, "away": away, "markets": {}})
        stamp = iso_now(now)
        result = {"winner_incl_ot": "skipped", "spread": "skipped", "total": "skipped", "team_totals": "skipped", "player_points": "skipped"}
        changed = False
        before = {id(r) for r in _all_revisions(entry)} if source == SOURCE_AUTO else None
        if w_vals is not None:
            c = _apply_winner(entry, *w_vals, stamp)
            result[WINNER] = "saved" if c else "unchanged"
            changed |= c
            if w_vals[2]:
                data.setdefault("last_bookmaker", {})[WINNER] = w_vals[2]
        if s_parsed is not None:
            market = _spread_market(entry)
            n, _ = _apply_spread(market, s_parsed, suggestion, stamp)
            result[SPREAD] = "saved" if n else "unchanged"
            if n:
                market["entered_at"] = market.get("entered_at") or stamp
                market["updated_at"] = stamp
                changed = True
            book = next((p[4] for p in s_parsed if p[4]), "")
            if book:
                data.setdefault("last_bookmaker", {})[SPREAD] = book
        if t_parsed is not None:
            market = _total_market(entry)
            n, _ = _apply_total(market, t_parsed, total_suggestion, stamp)
            result[TOTAL] = "saved" if n else "unchanged"
            if n:
                market["entered_at"] = market.get("entered_at") or stamp
                market["updated_at"] = stamp
                changed = True
            book = next((p[4] for p in t_parsed if p[4]), "")
            if book:
                data.setdefault("last_bookmaker", {})[TOTAL] = book
        if any(v is not None for v in tm_parsed.values()):
            market = _team_market(entry, home, away)
            n_all = 0
            for side, parsed in tm_parsed.items():
                if parsed is None:
                    continue
                n, _ = _apply_total(market[side], parsed, (team_suggestion or {}).get(side), stamp)
                n_all += n
                book = next((p[4] for p in parsed if p[4]), "")
                if book:
                    data.setdefault("last_bookmaker", {})[f"{TEAM_TOTALS}_{side}"] = book
            result[TEAM_TOTALS] = "saved" if n_all else "unchanged"
            if n_all:
                market["entered_at"] = market.get("entered_at") or stamp
                market["updated_at"] = stamp
                changed = True
        if pp_parsed is not None:
            market = _player_market(entry)
            n = _apply_players(market, pp_parsed, stamp, roster_fetched_at)
            result[PLAYER_POINTS] = "saved" if n else "unchanged"
            if n:
                market["entered_at"] = market.get("entered_at") or stamp
                market["updated_at"] = stamp
                changed = True
            book = next((r[-1] for pb in pp_parsed for r in pb["rows"] if r[-1]), "")
            if book:
                data.setdefault("last_bookmaker", {})[PLAYER_POINTS] = book
        if not changed:
            return {"status": "unchanged", "key": key, "markets": result, "entry": copy.deepcopy(entry)}
        if before is not None:
            for r in _all_revisions(entry):
                if id(r) not in before:
                    r["source"] = SOURCE_AUTO
        data["updated_at"] = stamp
        data["version"] = STORE_VERSION
        data["markets"] = {**data.get("markets", {}), **MARKETS}
        try:
            _atomic_write(store_path(), data)
        except Exception as e:
            raise StoreError("Speichern fehlgeschlagen; die bestehende Datei wurde nicht verändert.") from e
        _daily_copy(now)
        return {"status": "saved", "key": key, "markets": result, "entry": copy.deepcopy(entry), "recovered": data.get("recovered_from_corrupt")}


# ------------------------------------------------------------------------------ Automatik (noch nirgends eingebunden)
SKIP_HAND_PRIORITY = "übersprungen: Handeingabe hat Vorrang"


def _all_revisions(node) -> list[dict]:
    """Alle Revisions-Eintraege (Dicts in Listen namens 'revisions') beliebig tief im Eintrag."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "revisions" and isinstance(v, list):
                out.extend(r for r in v if isinstance(r, dict))
            else:
                out.extend(_all_revisions(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_all_revisions(v))
    return out


def revision_source(rev: dict) -> str:
    """'auto' nur bei ausdruecklichem Feld; Revisionen ohne Feld (alle bisherigen) gelten als Handeingabe."""
    return SOURCE_AUTO if (rev or {}).get("source") == SOURCE_AUTO else SOURCE_HAND


def has_hand_revision(unit: dict | None) -> bool:
    """Hat dieser Markt/diese Linie/dieser Block (auch entfernt) mindestens eine Handeingabe in seinen Revisionen?"""
    return any(revision_source(r) == SOURCE_HAND for r in _all_revisions(unit or {}))


def _lines_of(market: dict | None) -> list[dict]:
    return list((market or {}).get("lines") or [])


def _filter_rows(rows, lines: list[dict], value_key: str, parse) -> tuple[list | None, int]:
    """Entfernt Zeilen, die eine Linie mit Handeingabe treffen (ueber die ID oder den gleichen Linienwert). Rueckgabe (Zeilen oder None, Zahl uebersprungen)."""
    if not rows:
        return rows, 0
    hand_ids = {l["id"] for l in lines if has_hand_revision(l)}
    hand_vals = {l.get(value_key) for l in lines if has_hand_revision(l)}
    keep, skipped = [], 0
    for row in rows:
        try:
            val = parse(row.get("line"))
        except OddsInputError:
            val = None
        if row.get("id") in hand_ids or (val is not None and val in hand_vals):
            skipped += 1
        else:
            keep.append(row)
    if any(l["id"] == "main" for l in lines if has_hand_revision(l)) and keep:
        return None, skipped + len(keep)         # Hand-Hauptlinie: die ganze Leiter des Marktes bleibt Hand (Zeilen ohne Hauptlinie waeren auch nicht speicherbar)
    return (keep or None), skipped


def save_auto(game_date: str, start_utc: str, home: str, away: str, winner: dict | None = None, spread_rows: list[dict] | None = None,
              suggestion: dict | None = None, total_rows: list[dict] | None = None, total_suggestion: dict | None = None,
              team_rows: dict | None = None, team_suggestion: dict | None = None, team_names: dict | None = None,
              player_blocks: list[dict] | None = None, roster_fetched_at: str | None = None, now: float | None = None) -> dict:
    """Speicherpfad der Automatik (noch nirgends aufgerufen). Gleiche Eingaben wie save_card, neue Revisionen tragen "source": "auto".
    Vorrang der Hand: Teile (Sieger-Markt, Spread-/Total-/Team-Total-Linie, Spielerblock) mit mindestens einer Handeingabe-Revision werden NICHT angefasst
    (auch nicht entfernt); sie werden uebersprungen. Alles unter derselben Sperre wie das Speichern. Entfernen gibt es fuer die Automatik nicht.
    Rueckgabe wie save_card plus 'skipped_hand': Zahl uebersprungener Teile; Status 'skipped' (Grund SKIP_HAND_PRIORITY), wenn nichts uebrig bleibt."""
    now = now if now is not None else time.time()
    start_norm = _prepare_game(game_date, start_utc, now)
    key = game_key(game_date, start_norm, home, away)
    with _lock:
        entry = (load().get("entries") or {}).get(key) or {}
        mk = entry.get("markets") or {}
        skipped = 0
        if winner is not None and has_hand_revision(mk.get(WINNER)):
            winner, skipped = None, skipped + 1
        spread_rows, n = _filter_rows(spread_rows, _lines_of(mk.get(SPREAD)), "line_home", parse_line_input)
        skipped += n
        total_rows, n = _filter_rows(total_rows, _lines_of(mk.get(TOTAL)), "line", parse_total_input)
        skipped += n
        if team_rows:
            new_team = {}
            for side in TEAMS:
                new_team[side], n = _filter_rows((team_rows or {}).get(side), _lines_of((mk.get(TEAM_TOTALS) or {}).get(side)), "line", parse_team_total_input)
                skipped += n
            team_rows = new_team if any(new_team.values()) else None
        if player_blocks:
            hand_pids = {b.get("person_id") for b in (mk.get(PLAYER_POINTS) or {}).get("players", []) if has_hand_revision(b)}
            keep = [b for b in player_blocks if not (b.get("person_id") in hand_pids and b.get("person_id") not in (None, ""))]
            skipped += len(player_blocks) - len(keep)
            player_blocks = keep or None
        if all(x is None for x in (winner, spread_rows, total_rows, team_rows, player_blocks)):
            if skipped:
                return {"status": "skipped", "reason": SKIP_HAND_PRIORITY, "key": key, "skipped_hand": skipped}
            raise OddsInputError("Nichts eingetragen.")
        res = save_card(game_date, start_norm, home, away, winner=winner, spread_rows=spread_rows, suggestion=suggestion, total_rows=total_rows,
                        total_suggestion=total_suggestion, team_rows=team_rows, team_suggestion=team_suggestion, team_names=team_names,
                        player_blocks=player_blocks, roster_fetched_at=roster_fetched_at, now=now, source=SOURCE_AUTO)
        res["skipped_hand"] = skipped
        return res
