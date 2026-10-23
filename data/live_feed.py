"""
Live-Feed fuer den Spieltag-Tab (Baustein 4): Spieleliste des aktuellen US-Spieltags aus dem NBA.com-Scoreboard, Boxscore nur fuer laufende Spiele, Fehlerzustand mit letztem
guten Stand, ESPN-Fallback nur fuer Stand/Uhr/Status, Verbindung zum Live-Modell und zu den eigenen Wetten. Ohne Streamlit, nur lesend: schreibt nichts ins Projekt.

Aufruf der Oberflaeche (alles wirft nie eine Ausnahme nach oben):
    feed = live_feed.get_feed()                         # ein gemeinsamer Feed je Prozess (alle Sitzungen teilen Zwischenspeicher und Wartezeit)
    state = feed.refresh()                              # holt nur, was faellig ist (Scoreboard hoechstens alle 15 s, Boxscore je laufendem Spiel hoechstens alle 30 s)
    numbers = live_feed.live_numbers_for_state(state)   # {game_id: LiveNumbers}: Chancen je Markt; ohne Schnappschuss ohne Chancen, mit Hinweis
    rows = live_feed.bets_live(state)                   # eigene Wetten des Spieltags mit Live-Status

Spieltag: ab 17:00 Uhr deutscher Zeit gilt das neue US-Spieldatum (wie im Recorder), davor der Vortag (current_us_day).
Zeiten: Scoreboard alle 15 s, Boxscore je Spiel alle 30 s, auch wenn die Oberflaeche oefter fragt. Fehler (403, 429, Zeitueberschreitung, kaputte Antwort): der letzte gute Stand bleibt,
mit Alter in Sekunden und klarer Meldung inkl. Statuscode; neuer Versuch nach 30, 60, 120, 240, hoechstens 300 s (gilt fuer alle NBA.com-Abrufe zusammen); ein Erfolg setzt zurueck.
ESPN (site.api.espn.com) nur als Notfall fuer Stand, Uhr und Status, wenn das NBA.com-Scoreboard ausfaellt: nur fuer Spiele, die eindeutig (beide Mannschaften + Anpfiff) einem schon
bekannten NBA-Spiel zugeordnet werden koennen; ist irgendeine Zuordnung unsicher oder gibt es keinen bekannten Stand, gibt es keinen Fallback. Quelle steht in state.source und game.source.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from data.nba_headers import nba_headers
from data.nba_live import NBA_BOXSCORE_URL, NBA_SCOREBOARD_URL
from engine import game_clock as gc
from engine import live_model as lm

BERLIN = ZoneInfo("Europe/Berlin")
ET = ZoneInfo("America/New_York")
DAY_SWITCH_HOUR = 17                 # ab 17:00 Uhr deutscher Zeit gilt der neue US-Spieltag
SCOREBOARD_SECONDS = 15.0
BOX_SECONDS = 30.0
ESPN_SECONDS = 30.0
BACKOFF_START, BACKOFF_MAX = 30, 300
TIMEOUT_SECONDS = 10
MAX_BOXES_PER_REFRESH = 6
FINAL_MAX_TRIES = 5                  # nach Spielende: so oft hoechstens einen Boxscore holen, der dem Endstand noch nicht entspricht
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
START_TOLERANCE_SECONDS = 3 * 3600   # Anpfiff NBA.com gegen ESPN darf so weit auseinanderliegen
SOURCE_NBA, SOURCE_ESPN = "NBA.com", "ESPN"
SOURCE_BOX_SUB, SOURCE_ESPN_SUB = "NBA.com-Boxscore (Ersatz)", "ESPN (Ersatz)"
FREEZE_SECONDS = 90.0                # laeuft das Spiel laut Scoreboard, aber Uhr UND Stand sind so lange unveraendert: Verdacht auf eingefrorene Daten
BOX_FRESH_SECONDS = 75.0             # ein Boxscore darf hoechstens so alt sein, um das eingefrorene Scoreboard zu ersetzen
LAG_WARN_SECONDS = 120.0            # Rueckstand des Scoreboards (Spielzeit), ab dem die Statuszeile gelb wird
NEWER_SECONDS = 2.0                  # eine Ersatzquelle gilt als neuer, wenn ihre Spielzeit mindestens so viele Sekunden weiter ist (oder mehr Punkte / Spielende)
STALE_NOTE = "Daten veraltet: NBA.com liefert seit über 90 Sekunden denselben Stand und keine Ersatzquelle ist erreichbar. Keine Chancen und kein Wett-Status auf diesen Werten."
NO_ANCHOR_NOTE = "Kein Schnappschuss vor dem Anpfiff für dieses Spiel: keine Chancen (die Hochrechnung braucht die Vorab-Prognose als Anker)."


# ----------------------------------------------------------------------------------------------- Spieltag
def current_us_day(t: float) -> str:
    """Aktueller US-Spieltag (JJJJ-MM-TT) nach dem 17:00-Wechsel in Berliner Zeit: ab 17:00 gilt das Berliner Datum, davor der Vortag (Spiele des US-Tags D laufen bis ca. 6 Uhr am
    Folgetag). Gleiche Regel wie record_live.current_us_day; zoneinfo beruecksichtigt Sommer-/Winterzeit (wirksam ist immer die Berliner Uhrzeit)."""
    b = datetime.fromtimestamp(t, BERLIN)
    return (b.date() if b.hour >= DAY_SWITCH_HOUR else (b - timedelta(days=1)).date()).isoformat()


def game_day_us(row: dict, fallback: str | None = None) -> str:
    """US-Spieldatum eines Scoreboard-Spiels: aus gameEt, sonst aus gameTimeUTC (Ostkueste), sonst fallback."""
    et = str(row.get("gameEt") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", et):
        return et[:10]
    try:
        return datetime.fromisoformat(str(row.get("gameTimeUTC")).replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%d")
    except ValueError:
        return fallback or "unbekannt"


# ----------------------------------------------------------------------------------------------- Datenklassen
@dataclass(frozen=True)
class PlayerLive:
    """Ein Spieler aus dem schon geholten Boxscore (kein zusaetzlicher Abruf). Zuordnung ueber person_id (= personId des Boxscores = NBA-Personennummer)."""
    person_id: int
    name: str
    side: str                          # "home" | "away"
    tricode: str | None
    points: int
    minutes: float                     # gespielte Minuten (Zahl)
    fouls: int
    status: str                        # "spielt" (auf dem Feld) | "bank" (noch nicht oder gerade nicht auf dem Feld) | "nicht gespielt" (laut Boxscore inaktiv)
    played: bool                       # hat bereits Spielzeit


@dataclass(frozen=True)
class GameView:
    game_id: str
    home: str                          # "Philadelphia 76ers"
    away: str
    home_nick: str                     # "76ers"
    away_nick: str
    home_tricode: str | None
    away_tricode: str | None
    day: str                           # US-Spieldatum
    start_utc: str | None
    status: str                        # PRE | LIVE | PAUSE | FINAL
    status_text: str                   # deutsch: "Vor dem Anpfiff", "läuft", "Pause", "Halbzeit", "Ende Q4", "beendet"
    clock: gc.GameClock                # Phase, Periode, Restzeit (leere Uhr = Periodenende, kein 12:00-Fallback)
    clock_label: str                   # "Q3 6:00", "Halbzeit", "Ende Q4", "OT 2:00", "Ende"
    home_score: int
    away_score: int
    home_periods: tuple = ()
    away_periods: tuple = ()
    possessions: lm.Possessions | None = None
    box_age_s: float | None = None
    box_error: str | None = None
    source: str = SOURCE_NBA
    updated_at: float | None = None    # Zeitpunkt der Daten (Epoch)
    players: tuple = ()                # PlayerLive aus dem letzten Boxscore (leer, solange keiner geholt wurde)
    players_complete: bool = False     # Boxscore-Teampunkte == Scoreboard-Stand: die Spielerpunkte sind aktuell (wichtig fuer "verloren" nach Spielende)
    frozen_since_s: float | None = None  # NBA.com-Scoreboard laeuft nicht weiter (Uhr und Stand unveraendert), seit so vielen Sekunden; Stand/Uhr kommen dann von einer Ersatzquelle
    data_stale: bool = False           # Verdacht auf eingefrorene Daten UND keine Ersatzquelle erreichbar: Stand/Uhr nicht verwenden (keine Chancen, kein Wettstatus darauf)

    @property
    def running(self) -> bool:
        return self.status in ("LIVE", "PAUSE")


@dataclass(frozen=True)
class FeedState:
    day: str                                   # aktueller US-Spieltag
    games: tuple                               # Spiele dieses Tages (nach Anpfiff, dann game_id)
    other_day_games: tuple                     # andere Tage auf dem Scoreboard (z. B. Vortag vor dem Umschalten)
    source: str | None                         # "NBA.com" | "ESPN" | None (noch keine Daten)
    fetched_at: float | None                   # Zeitpunkt der letzten frischen Daten (aus irgendeiner Quelle)
    age_s: float | None                        # Alter der Daten in Sekunden
    stale: bool                                # Daten sind nicht mehr frisch: der letzte Abruf (und ein Fallback) ist fehlgeschlagen
    stale_since_s: float | None                # "Daten veraltet seit X Sekunden" (nur wenn stale)
    error: str | None                          # klare Meldung der NBA.com-Stoerung mit Statuscode (auch wenn ESPN einspringt)
    error_status: int | None
    error_ref: str
    retry_in_s: float | None                   # bis zum naechsten Versuch
    backoff_s: int
    scoreboard_day: str | None                 # Spieltag laut NBA.com-Scoreboard
    notice: str | None                         # z. B. Scoreboard zeigt noch den Vortag
    fallback_note: str | None                  # ESPN eingesprungen / warum kein Fallback
    status_line: str                           # fertiger Satz fuer die Oberflaeche
    freeze_note: str | None = None             # Hinweis, wenn NBA.com-Daten eingefroren sind (Statuszeile gelb)


@dataclass(frozen=True)
class LiveNumbers:
    """Live-Zahlen eines Spiels. Ohne Schnappschuss: has_anchor False, projection None, note erklaert es; alle p_*-Methoden liefern dann None."""
    game_id: str
    has_anchor: bool
    note: str | None
    anchor: lm.Anchor | None = None
    projection: lm.LiveProjection | None = None
    snapshot_key: str | None = None

    def p_winner(self, side: str):
        return None if self.projection is None else self.projection.p_winner(side)

    def p_spread(self, side: str, line: float):
        return None if self.projection is None else self.projection.p_spread(side, line)

    def p_over_total(self, line: float):
        return None if self.projection is None else self.projection.p_over_total(line)

    def p_over_team(self, side: str, line: float):
        return None if self.projection is None else self.projection.p_over_team(side, line)


def _box_minutes(value) -> float:
    m = re.fullmatch(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", str(value or "").strip())
    return (int(m.group(1) or 0) + float(m.group(2) or 0) / 60) if m else 0.0


def players_from_box(game: dict) -> tuple:
    """PlayerLive-Liste aus der Boxscore-Antwort (game = response['game']). Unlesbare Spieler werden uebersprungen."""
    out = []
    for side in ("home", "away"):
        team = game.get(f"{side}Team") or {}
        for p in team.get("players") or []:
            try:
                st = p.get("statistics") or {}
                minutes = _box_minutes(st.get("minutes"))
                on = str(p.get("oncourt")) == "1"
                played = str(p.get("played")) == "1" or minutes > 0
                inactive = str(p.get("status") or "ACTIVE").upper() == "INACTIVE"
                status = "spielt" if on else "nicht gespielt" if inactive and not played else "bank"
                out.append(PlayerLive(int(p["personId"]), str(p.get("name") or ""), side, team.get("teamTricode"), int(st.get("points") or 0), minutes,
                                      int(st.get("foulsPersonal") or 0), status, played))
            except (KeyError, TypeError, ValueError):
                continue
    return tuple(out)


# ----------------------------------------------------------------------------------------------- Anzeigehilfen
def status_of(clock: gc.GameClock) -> str:
    if clock.phase == gc.PRE:
        return "PRE"
    if clock.phase == gc.FINAL:
        return "FINAL"
    return "LIVE" if clock.running else "PAUSE"


def _mmss(seconds: float | None) -> str:
    s = max(0, int(round(seconds or 0)))
    return f"{s // 60}:{s % 60:02d}"


def clock_label(clock: gc.GameClock) -> str:
    if clock.phase == gc.PRE:
        return ""
    ot = clock.ot_number
    ot_name = "OT" if ot <= 1 else f"{ot}OT"
    if clock.phase == gc.FINAL:
        return "Ende" if ot == 0 else f"Ende ({ot_name})"
    if clock.phase == gc.HALFTIME:
        return "Halbzeit"
    if clock.phase == gc.BREAK:
        return f"Pause nach Q{clock.period}"
    if clock.phase == gc.REGULAR_END:
        return "Ende Q4"
    if clock.phase == gc.OT:
        return f"{ot_name} {_mmss(clock.seconds_left)}" if clock.running else f"Ende {ot_name}"
    return f"Q{clock.period} {_mmss(clock.seconds_left)}"


_STATUS_TEXT = {"PRE": "Vor dem Anpfiff", "LIVE": "läuft", "FINAL": "beendet"}


def status_text(clock: gc.GameClock) -> str:
    st = status_of(clock)
    if st == "PAUSE":
        return {gc.HALFTIME: "Halbzeit", gc.REGULAR_END: "Ende Q4"}.get(clock.phase, "Pause")
    return _STATUS_TEXT[st]


def same_team(full_name: str, nick: str) -> bool:
    """Vollname (z. B. 'LA Clippers' oder 'Los Angeles Clippers') gehoert zum Spitznamen ('Clippers')."""
    full, nick = str(full_name or "").strip().lower(), str(nick or "").strip().lower()
    return bool(nick) and (full == nick or full.endswith(" " + nick))


# ----------------------------------------------------------------------------------------------- Abruf
class _Backoff:
    def __init__(self):
        self.wait = 0

    def failure(self) -> int:
        self.wait = BACKOFF_START if not self.wait else min(BACKOFF_MAX, self.wait * 2)
        return self.wait

    def success(self) -> None:
        self.wait = 0


class _Res:
    def __init__(self, status=None, data=None, error=None, ref=""):
        self.status, self.data, self.error, self.ref = status, data, error, ref

    @property
    def ok(self) -> bool:
        return self.error is None


def _ref(text) -> str:
    m = re.search(r"Reference(?:&#32;|\s)(?:&#35;|#)([0-9a-fA-F.]+(?:&#46;[0-9a-fA-F]+)*)", str(text or ""))
    return m.group(1).replace("&#46;", ".") if m else ""


def _message(source: str, status, kind: str, ref: str = "") -> str:
    """Klare deutsche Meldung mit Statuscode (kind: http | timeout | net | json | format)."""
    if kind == "timeout":
        return f"{source}: keine Antwort (Zeitüberschreitung)."
    if kind == "net":
        return f"{source}: keine Verbindung."
    if kind == "json":
        return f"{source}: ungültige Antwort (kein JSON, HTTP {status})."
    if kind == "format":
        return f"{source}: ungültige Antwort (unerwartetes Format, HTTP {status})."
    texts = {403: "Zugriff abgelehnt", 429: "zu viele Anfragen", 404: "nicht gefunden"}
    text = texts.get(status, "Abruf fehlgeschlagen")
    return f"{source}: {text} (HTTP {status})" + (f", Referenz {ref}" if ref else "") + "."


# ----------------------------------------------------------------------------------------------- ESPN
def parse_espn(data) -> list[dict]:
    """ESPN-Scoreboard -> [{'id', 'home_nick', 'away_nick', 'home_name', 'away_name', 'start_ts', 'status_code', 'text', 'period', 'clock', 'home_score', 'away_score'}]. Unlesbares wird uebersprungen."""
    out = []
    for ev in (data or {}).get("events") or []:
        try:
            comp = ev["competitions"][0]
            st = ev["status"]
            tp = st["type"]
            teams = {c["homeAway"]: c for c in comp["competitors"]}
            code = {"pre": 1, "in": 2, "post": 3}.get(str(tp.get("state")), None)
            if code is None or "home" not in teams or "away" not in teams:
                continue
            try:
                start = datetime.fromisoformat(str(ev.get("date")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                start = None
            out.append({"id": str(ev.get("id")), "home_nick": teams["home"]["team"].get("name"), "away_nick": teams["away"]["team"].get("name"),
                        "home_name": teams["home"]["team"].get("displayName"), "away_name": teams["away"]["team"].get("displayName"), "start_ts": start,
                        "status_code": code, "text": tp.get("detail") or tp.get("description") or "", "period": int(st.get("period") or 0),
                        "clock": st.get("displayClock"), "home_score": int(teams["home"].get("score") or 0), "away_score": int(teams["away"].get("score") or 0)})
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def match_espn(games: list[GameView], espn: list[dict]) -> tuple[dict, str | None]:
    """Ordnet ESPN-Spiele den bekannten NBA-Spielen zu: {game_id: espn_event}. Zweiter Wert: Grund, wenn die Zuordnung unsicher ist (dann gibt es keinen Fallback).
    Eindeutig = beide Spitznamen gleich und Anpfiff innerhalb von 3 Stunden (falls beide bekannt); jedes ESPN-Spiel hoechstens einem NBA-Spiel."""
    claims: dict[str, list[str]] = {}
    cand: dict[str, list[dict]] = {}
    for g in games:
        try:
            g_start = datetime.fromisoformat(str(g.start_utc).replace("Z", "+00:00")).timestamp() if g.start_utc else None
        except ValueError:
            g_start = None
        found = [e for e in espn if str(e["home_nick"]).lower() == g.home_nick.lower() and str(e["away_nick"]).lower() == g.away_nick.lower()
                 and (g_start is None or e["start_ts"] is None or abs(g_start - e["start_ts"]) <= START_TOLERANCE_SECONDS)]
        cand[g.game_id] = found
        for e in found:
            claims.setdefault(e["id"], []).append(g.game_id)
    if any(len(v) > 1 for v in cand.values()):
        return {}, "Zuordnung unsicher (mehrere ESPN-Spiele passen zu einem NBA-Spiel)"
    if any(len(v) > 1 for v in claims.values()):
        return {}, "Zuordnung unsicher (ein ESPN-Spiel passt zu mehreren NBA-Spielen)"
    matched = {gid: v[0] for gid, v in cand.items() if v}
    return matched, (None if matched else "ESPN lieferte keine zuordenbaren Spiele")


# ----------------------------------------------------------------------------------------------- Feed
class LiveFeed:
    def __init__(self, http_get=None, now=time.time, headers: dict | None = None):
        self._http_get = http_get
        self._now = now
        self._headers = headers if headers is not None else nba_headers()
        self._lock = threading.RLock()
        self._backoff = _Backoff()
        self._games: dict[str, GameView] = {}
        self._box: dict[str, dict] = {}                 # game_id -> {'at', 'poss', 'error', 'attempt', 'players', 'scores'}
        self._scoreboard_day: str | None = None
        self._last_ok: float | None = None              # letztes frisches NBA.com-Scoreboard
        self._fresh_at: float | None = None             # letzte frische Daten aus irgendeiner Quelle
        self._first_fail: float | None = None
        self._last_attempt = float("-inf")
        self._next_allowed = float("-inf")
        self._error: dict | None = None                 # {'message', 'status', 'ref'}
        self._source: str | None = None
        self._espn_at = float("-inf")
        self._fallback_note: str | None = None
        self._sig: dict[str, tuple] = {}                # game_id -> (Signatur aus Status/Periode/Uhr/Stand des Scoreboards, seit wann unveraendert)
        self._raw: dict[str, GameView] = {}             # game_id -> Ansicht genau wie vom Scoreboard geliefert (vor einer Ersatzquelle)
        self._freeze_note: str | None = None
        self._lag_note: str | None = None
        self._lag_warn = False
        self._espn_sub_at = float("-inf")
        self._espn_sub: tuple = ({}, None)              # (zugeordnete ESPN-Spiele, Fehlergrund) vom letzten Ersatz-Abruf

    # -- oeffentlich
    def refresh(self, now: float | None = None, day: str | None = None) -> FeedState:
        """Holt, was faellig ist, und liefert den aktuellen Zustand. Wirft nie eine Ausnahme."""
        with self._lock:
            t = self._now() if now is None else now
            try:
                self._refresh(t)
            except Exception as e:                                     # letzte Sicherung: nie eine Ausnahme nach oben
                self._error = {"message": f"Interner Fehler im Live-Feed ({type(e).__name__}).", "status": None, "ref": ""}
                self._fail(t)
            return self._state(t, day)

    def state(self, now: float | None = None, day: str | None = None) -> FeedState:
        """Aktueller Zustand ohne Abruf."""
        with self._lock:
            return self._state(self._now() if now is None else now, day)

    # -- HTTP
    def _get(self, url: str, source: str, params: dict | None = None) -> _Res:
        try:
            get = self._http_get
            if get is None:
                import requests
                get = requests.get
            kw = {"headers": self._headers if source == SOURCE_NBA else {"User-Agent": "NBAEdge/1.0 (persoenliche Nutzung)"}, "timeout": TIMEOUT_SECONDS}
            if params:
                kw["params"] = params
            r = get(url, **kw)
        except Exception as e:
            name = type(e).__name__
            kind = "timeout" if "timeout" in name.lower() else "net"
            return _Res(None, None, _message(source, None, kind))
        status = getattr(r, "status_code", None)
        if status != 200:
            ref = _ref(getattr(r, "text", ""))
            return _Res(status, None, _message(source, status, "http", ref), ref)
        try:
            return _Res(200, r.json())
        except Exception:
            return _Res(200, None, _message(source, 200, "json"))

    # -- Ablauf
    def _fail(self, t: float) -> None:
        if self._first_fail is None:
            self._first_fail = t
        self._next_allowed = t + self._backoff.failure()

    def _refresh(self, t: float) -> None:
        if t >= self._next_allowed and t - self._last_attempt >= SCOREBOARD_SECONDS:
            self._last_attempt = t
            res = self._get(NBA_SCOREBOARD_URL, SOURCE_NBA)
            board = None
            if res.ok:
                try:
                    board = res.data["scoreboard"]
                    rows = board["games"]
                    if not isinstance(rows, list):
                        raise TypeError
                except (KeyError, TypeError):
                    res = _Res(200, None, _message(SOURCE_NBA, 200, "format"))
            if res.ok:
                self._apply_scoreboard(board, rows, t)
            else:
                self._error = {"message": res.error, "status": res.status, "ref": res.ref}
                self._fail(t)
        if self._error is None:
            self._refresh_boxes(t)
            self._check_frozen(t)
        else:
            self._try_espn(t)

    def _apply_scoreboard(self, board: dict, rows: list, t: float) -> None:
        self._scoreboard_day = str(board.get("gameDate") or "") or None
        games = {}
        for row in rows:
            try:
                g = self._game_from_row(row, t)
            except Exception:
                continue                                              # eine kaputte Zeile darf nicht alle Spiele kosten
            games[g.game_id] = g
            sig = (g.clock.status, g.clock.period, round(g.clock.seconds_left, 1), g.home_score, g.away_score)
            old = self._sig.get(g.game_id)
            # unveraendert zaehlt nur, wenn wir ihn dazwischen auch gesehen haben (nach einer Stoerung/Luecke von > 45 s beginnt die Messung neu)
            self._sig[g.game_id] = (sig, old[1], t) if old and old[0] == sig and t - old[2] <= 45.0 else (sig, t, t)
        self._games = games
        self._raw = dict(games)
        for gid in [k for k in self._sig if k not in games]:
            del self._sig[gid]
        for gid in [k for k in self._box if k not in games]:
            del self._box[gid]
        self._last_ok = self._fresh_at = t
        self._error, self._first_fail, self._source, self._fallback_note = None, None, SOURCE_NBA, None
        self._backoff.success()
        self._next_allowed = float("-inf")

    def _game_from_row(self, row: dict, t: float) -> GameView:
        home, away = row.get("homeTeam") or {}, row.get("awayTeam") or {}
        clock = gc.from_scoreboard_game(row)
        gid = str(row["gameId"])
        box = self._box.get(gid) or {}
        per = lambda team: tuple(int(p.get("score") or 0) for p in sorted(team.get("periods") or [], key=lambda p: int(p.get("period") or 0)))
        return GameView(
            game_id=gid, home=f"{home.get('teamCity', '')} {home.get('teamName', '')}".strip(), away=f"{away.get('teamCity', '')} {away.get('teamName', '')}".strip(),
            home_nick=str(home.get("teamName") or ""), away_nick=str(away.get("teamName") or ""), home_tricode=home.get("teamTricode"), away_tricode=away.get("teamTricode"),
            day=game_day_us(row, self._scoreboard_day), start_utc=row.get("gameTimeUTC"), status=status_of(clock), status_text=status_text(clock), clock=clock, clock_label=clock_label(clock),
            home_score=int(home.get("score") or 0), away_score=int(away.get("score") or 0), home_periods=per(home), away_periods=per(away),
            possessions=box.get("poss"), box_age_s=None, box_error=box.get("error"), source=SOURCE_NBA, updated_at=t,
            players=box.get("players") or (), players_complete=box.get("scores") == (int(home.get("score") or 0), int(away.get("score") or 0)))

    @staticmethod
    def _parse_box(game: dict) -> tuple:
        """(Ballbesitze, Spielerliste, (Heim-, Gast-Punkte), Spielzeit des Boxscores oder None) aus einer Boxscore-Antwort (response['game']). Wirft KeyError/TypeError/ValueError bei Formatfehlern."""
        poss = lm.Possessions(lm.possessions_from_stats(game["homeTeam"]["statistics"]), lm.possessions_from_stats(game["awayTeam"]["statistics"]))
        players = players_from_box(game)                              # Spielerliste aus derselben Antwort, kein zusaetzlicher Abruf
        scores = (int(game["homeTeam"].get("score") or 0), int(game["awayTeam"].get("score") or 0))
        bclock = None
        if game.get("period") is not None:                            # Spielzeit des Boxscores (kann neuer sein als das Scoreboard)
            bclock = gc.build_game_clock(game.get("gameStatus"), game.get("gameStatusText"), game.get("period"), game.get("gameClock"))
            try:
                if bclock.status == 3 and int(game.get("period") or 0) < gc.REG_PERIODS:
                    bclock = None                                         # "beendet" vor dem 4. Viertel ist nicht plausibel: Spielzeit des Boxscores nicht verwenden
            except (TypeError, ValueError):
                bclock = None
        return poss, players, scores, bclock

    def _recorder_final(self, day: str, gid: str) -> dict | None:
        """final_box.json.gz des Recorders (NUR LESEN, kein Netz), falls vorhanden: ~/NBAEdge_live_history (oder NBAEDGE_LIVE_DIR)/<Tag>/<game_id>/. Unlesbar oder fehlend: None."""
        import gzip, json, os
        from pathlib import Path
        root = Path(os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history")
        try:
            return json.loads(gzip.decompress((root / day / gid / "final_box.json.gz").read_bytes()).decode("utf-8")).get("game")
        except Exception:
            return None

    def _refresh_boxes(self, t: float) -> None:
        """Boxscore fuer laufende Spiele (Status 2 laut Scoreboard), je Spiel hoechstens alle 30 s, hoechstens 6 je Aufruf; nach einem Fehler gilt die gemeinsame Wartezeit.
        Final-Abruf: Ist ein Spiel beendet, wird GENAU EIN weiterer Boxscore geholt (danach nie wieder), damit die Spielerpunkte dem Endstand entsprechen (players_complete); vorher wird, falls vorhanden,
        die Datei final_box.json.gz des Recorders gelesen (kein Netz). Bei einem Fehler neuer Versuch nach der gemeinsamen Wartezeit, bis es klappt; stimmt der Boxscore noch nicht mit dem Endstand
        ueberein (Boxscore hinkt), hoechstens FINAL_MAX_TRIES Versuche im Abstand von BOX_SECONDS."""
        def info(gid):
            return self._box.get(gid) or {}
        live_due = [g for g in self._games.values() if g.clock.is_live and t - info(g.game_id).get("attempt", float("-inf")) >= BOX_SECONDS]
        final_due = [g for g in self._games.values() if g.clock.is_final and not info(g.game_id).get("final_done") and info(g.game_id).get("final_tries", 0) < FINAL_MAX_TRIES
                     and t - info(g.game_id).get("attempt", float("-inf")) >= BOX_SECONDS]
        for g in (live_due + final_due)[:MAX_BOXES_PER_REFRESH]:
            entry = self._box.setdefault(g.game_id, {"at": None, "poss": None, "error": None, "attempt": float("-inf"), "players": (), "scores": None, "clock": None, "final_done": False, "final_tries": 0})
            gv = self._games[g.game_id]
            final = gv.clock.is_final
            if final:                                                  # 1. Recorder-Datei (nur lesen), 2. ein Abruf bei NBA.com
                rec = self._recorder_final(gv.day, g.game_id)
                if rec is not None:
                    try:
                        poss, players, scores, bclock = self._parse_box(rec)
                        if scores == (gv.home_score, gv.away_score):
                            entry.update(at=t, poss=poss, error=None, players=players, scores=scores, clock=bclock, final_done=True, attempt=t)
                            self._games[g.game_id] = replace(gv, possessions=poss, box_error=None, players=players, players_complete=True)
                            continue
                    except (KeyError, TypeError, ValueError):
                        pass
            if t < self._next_allowed:
                break
            entry["attempt"] = t
            res = self._get(NBA_BOXSCORE_URL.format(game_id=g.game_id), SOURCE_NBA)
            poss, players, scores, bclock = None, (), None, None
            if res.ok:
                try:
                    poss, players, scores, bclock = self._parse_box(res.data["game"])
                except (KeyError, TypeError, ValueError):
                    res = _Res(200, None, _message(SOURCE_NBA, 200, "format"))
            if res.ok:
                entry.update(at=t, poss=poss, error=None, players=players, scores=scores, clock=bclock)
                self._backoff.success()
                self._next_allowed = float("-inf")
                if final:
                    if scores == (gv.home_score, gv.away_score):
                        entry["final_done"] = True
                    else:
                        entry["final_tries"] = entry.get("final_tries", 0) + 1       # Boxscore hinkt dem Endstand noch hinterher: spaeter noch einmal
            else:
                entry["error"] = res.error                           # letzter guter Boxscore bleibt, Alter waechst
                if res.status != 200:                                # Verbindungs-/HTTP-Fehler (403, 429, Zeitueberschreitung ...): gemeinsame Pause fuer alle NBA.com-Abrufe
                    self._next_allowed = t + self._backoff.failure()   # (ein unlesbarer Boxscore EINES Spiels blockiert dagegen nicht das Scoreboard: neuer Versuch nach 30 s)
            gv = self._games[g.game_id]
            self._games[g.game_id] = replace(gv, possessions=entry["poss"], box_error=entry["error"], players=entry["players"] or (),
                                             players_complete=entry["scores"] == (gv.home_score, gv.away_score))

    def _try_espn(self, t: float) -> None:
        """NBA.com-Scoreboard faellt aus: Stand/Uhr/Status der bekannten Spiele von ESPN, nur bei eindeutiger Zuordnung."""
        if t - self._espn_at < ESPN_SECONDS:
            return
        self._espn_at = t
        known = [g for g in self._games.values()]
        if not known:
            self._fallback_note = "Kein ESPN-Fallback: es gibt noch keinen NBA.com-Stand, dem sich ESPN-Spiele zuordnen ließen."
            return
        days = sorted({g.day for g in known})
        res = self._get(ESPN_URL, SOURCE_ESPN, {"dates": days[-1].replace("-", "")})
        if not res.ok:
            self._fallback_note = f"Kein ESPN-Fallback: {res.error}"
            return
        matched, why = match_espn(known, parse_espn(res.data))
        if why:
            self._fallback_note = f"Kein ESPN-Fallback: {why}."
            return
        for gid, e in matched.items():
            old = self._games[gid]
            clock = gc.build_game_clock(e["status_code"], e["text"], e["period"], e["clock"])
            self._games[gid] = replace(old, clock=clock, status=status_of(clock), status_text=status_text(clock), clock_label=clock_label(clock),
                                       home_score=e["home_score"], away_score=e["away_score"], source=SOURCE_ESPN, updated_at=t,
                                       players_complete=(self._box.get(gid) or {}).get("scores") == (e["home_score"], e["away_score"]))
        self._fresh_at, self._source = t, SOURCE_ESPN
        self._fallback_note = f"Stand, Uhr und Status von ESPN ({len(matched)} von {len(known)} Spielen zugeordnet); Boxscore/Tempo aus dem letzten NBA.com-Stand."

    # -- eingefrorenes Scoreboard
    @staticmethod
    def _newer(clock, scores, raw: GameView) -> bool:
        """Ist der Stand einer Ersatzquelle (ESPN) weiter als das Scoreboard? (Spielzeit, Spielende, Punkte)"""
        if clock.status > raw.clock.status:
            return True                                                  # z. B. ESPN: Spiel beendet, Scoreboard noch "laeuft"
        if clock.status == 2 and raw.clock.status == 2 and clock.elapsed_total_s >= raw.clock.elapsed_total_s + NEWER_SECONDS:
            return True
        return sum(scores) > raw.home_score + raw.away_score and clock.elapsed_total_s >= raw.clock.elapsed_total_s

    @staticmethod
    def _box_newer(clock, scores, raw: GameView) -> bool:
        """Boxscore gegen Scoreboard, IMMER bei laufenden Spielen: neuer, wenn seine Periode spaeter ist, bei gleicher Periode die Restzeit kuerzer, bei gleicher Zeit die Gesamtpunkte hoeher.
        Voraussetzung: die Punkte sind plausibel (kein Team hat weniger Punkte als im Scoreboard). Spielende nur, wenn der Boxscore 'beendet' meldet UND die Punkte plausibel sind
        (Verlaengerung/Viertel 4 oder spaeter, kein Gleichstand, zusammen mindestens 120 Punkte)."""
        if scores[0] < raw.home_score or scores[1] < raw.away_score:
            return False                                                 # Punkte duerfen nie zurueckgehen: nicht vermischen
        if clock.status == 3:
            return clock.period >= gc.REG_PERIODS and scores[0] != scores[1] and sum(scores) >= 120
        if clock.status != 2 or raw.clock.status != 2:
            return False
        if clock.period != raw.clock.period:
            return clock.period > raw.clock.period
        if clock.seconds_left != raw.clock.seconds_left:
            return clock.seconds_left < raw.clock.seconds_left
        return sum(scores) > raw.home_score + raw.away_score

    def _check_frozen(self, t: float) -> None:
        """Quellenwahl fuer laufende Spiele (Stand, Uhr, Periode kommen immer aus EINER Quelle, nie gemischt):
        1. IMMER der Boxscore von NBA.com (alle 30 s ohnehin geholt), wenn er neuer ist als das Scoreboard (_box_newer): das Scoreboard bewegt sich manchmal in kleinen Spruengen und hinkt
           Spielminuten hinterher, ohne je lange still zu stehen. Statuszeile: dezent "Scoreboard hinkt ca. mm:ss hinterher", gelb ab LAG_WARN_SECONDS Rueckstand.
        2. Einfrier-Erkennung (zusaetzlich): laeuft ein Spiel laut Scoreboard (Uhr laeuft), aber Uhr UND Stand sind seit mehr als FREEZE_SECONDS unveraendert und der Boxscore fehlt oder ist nicht
           brauchbar (nicht frisch/Fehler): ESPN als Zweitersatz. Ein frischer Boxscore, der NICHT weiter ist, bedeutet eine echte Unterbrechung (kein Alarm, kein ESPN-Abruf). Pausen (Viertelpause,
           Halbzeit, Verlaengerungspause) loesen nichts aus. Ist keine Ersatzquelle erreichbar: data_stale (keine Chancen/Wettstatus darauf). Die Rohwerte des Scoreboards bleiben unveraendert."""
        mmss = lambda sec: f"{int(sec) // 60:02d}:{int(sec) % 60:02d}"
        sub_notes, lag_info = [], []                                      # sub_notes: (seit, raw, Quelle|None); lag_info: (Rueckstand in Spielsekunden, raw)
        done = set()
        for gid, raw in self._raw.items():
            e = self._box.get(gid) or {}
            bclock = e.get("clock")
            if (raw.clock.is_live and bclock is not None and e.get("at") is not None and t - e["at"] <= BOX_FRESH_SECONDS and e.get("scores") is not None
                    and self._box_newer(bclock, e["scores"], raw)):
                since = t - self._sig[gid][1] if gid in self._sig else 0.0
                frozen = since if since >= FREEZE_SECONDS else None
                self._substitute(gid, raw, bclock, e["scores"], SOURCE_BOX_SUB, frozen, t)
                done.add(gid)
                if frozen is not None:
                    sub_notes.append((since, raw, SOURCE_BOX_SUB))
                lag_info.append((max(0.0, bclock.elapsed_total_s - raw.clock.elapsed_total_s) if bclock.status == 2 else None, raw))
        suspects = {gid: t - self._sig[gid][1] for gid, raw in self._raw.items()
                    if gid not in done and gid in self._sig and raw.clock.is_live and raw.clock.running and t - self._sig[gid][1] >= FREEZE_SECONDS}
        need_espn = []
        for gid, since in suspects.items():
            raw, e = self._raw[gid], self._box.get(gid) or {}
            if e.get("clock") is not None and e.get("at") is not None and t - e["at"] <= BOX_SECONDS + 10 and e.get("scores") is not None:
                continue                                                  # frischer Boxscore ist NICHT weiter: echte Unterbrechung, kein Alarm
            need_espn.append(gid)
        if need_espn:
            if t - self._espn_sub_at >= ESPN_SECONDS:
                self._espn_sub_at = t
                days = sorted({self._raw[g].day for g in need_espn})
                res = self._get(ESPN_URL, SOURCE_ESPN, {"dates": days[-1].replace("-", "")})
                if res.ok:
                    self._espn_sub = match_espn(list(self._raw.values()), parse_espn(res.data))
                else:
                    self._espn_sub = ({}, res.error or "ESPN nicht erreichbar")
            matched, why = self._espn_sub
            for gid in need_espn:
                raw, since, e = self._raw[gid], suspects[gid], matched.get(gid)
                if e is None:                                              # keine Ersatzquelle: Daten nicht verwenden
                    self._games[gid] = replace(self._games[gid], frozen_since_s=since, data_stale=True)
                    sub_notes.append((since, raw, None))
                    continue
                eclock = gc.build_game_clock(e["status_code"], e["text"], e["period"], e["clock"])
                if self._newer(eclock, (e["home_score"], e["away_score"]), raw):
                    self._substitute(gid, raw, eclock, (e["home_score"], e["away_score"]), SOURCE_ESPN_SUB, since, t)
                    sub_notes.append((since, raw, SOURCE_ESPN_SUB))
        if sub_notes:
            since, raw, src = max(sub_notes, key=lambda n: n[0])
            who = f"{raw.away_nick} @ {raw.home_nick}"
            self._freeze_note = (f"NBA.com-Daten eingefroren seit {mmss(since)} ({who}): Stand, Uhr und Periode von {src}" if src
                                 else f"NBA.com-Daten möglicherweise eingefroren seit {mmss(since)} ({who}), keine Ersatzquelle erreichbar: Daten veraltet")
        else:
            self._freeze_note = None
        lags = [(lag, raw) for lag, raw in lag_info if lag is not None]
        if lags and not self._freeze_note:
            lag, raw = max(lags, key=lambda n: n[0])
            self._lag_note = f"Scoreboard hinkt ca. {mmss(lag)} hinterher ({raw.away_nick} @ {raw.home_nick}): Stand und Uhr vom NBA.com-Boxscore"
            self._lag_warn = lag >= LAG_WARN_SECONDS
        else:
            self._lag_note, self._lag_warn = None, False

    def _substitute(self, gid: str, raw: GameView, clock, scores: tuple, source: str, since: float, t: float) -> None:
        """Stand, Uhr, Periode und Status einer Ersatzquelle statt des eingefrorenen Scoreboards uebernehmen (Rohwerte bleiben in self._raw)."""
        box = self._box.get(gid) or {}
        self._games[gid] = replace(self._games[gid], clock=clock, status=status_of(clock), status_text=status_text(clock), clock_label=clock_label(clock), home_score=scores[0], away_score=scores[1],
                                   source=source, updated_at=t, frozen_since_s=since, data_stale=False, players_complete=box.get("scores") == tuple(scores))

    # -- Zustand
    def _state(self, t: float, day: str | None) -> FeedState:
        day = day or current_us_day(t)
        views = []
        for g in self._games.values():
            e = self._box.get(g.game_id) or {}
            views.append(replace(g, box_age_s=None if e.get("at") is None else max(0.0, t - e["at"]), box_error=e.get("error", g.box_error)))
        order = lambda g: (g.start_utc or "", g.game_id)
        games = tuple(sorted((g for g in views if g.day == day), key=order))
        other = tuple(sorted((g for g in views if g.day != day), key=order))
        age = None if self._fresh_at is None else max(0.0, t - self._fresh_at)
        espn_fresh = self._source == SOURCE_ESPN and age is not None and age <= ESPN_SECONDS * 2 + 5     # ESPN liefert noch frischen Stand
        stale = self._error is not None and not espn_fresh                                               # NBA.com gestoert und kein frischer Fallback
        notice = None
        if self._games and not games and self._scoreboard_day and self._scoreboard_day != day:
            notice = f"NBA.com zeigt noch den Spieltag {self._scoreboard_day}; die Spiele des neuen Spieltags {day} sind noch nicht freigeschaltet."
        retry = None if self._error is None else max(0.0, self._next_allowed - t)
        err = self._error
        if err is None:
            line = f"{self._source or SOURCE_NBA} · aktuell (vor {int(age)} s)" if age is not None else "Noch keine Daten abgerufen."
            if self._freeze_note:
                line += f" · ⚠ {self._freeze_note}"
            elif self._lag_note:
                line += f" · {'⚠ ' if self._lag_warn else ''}{self._lag_note}"
        elif self._source == SOURCE_ESPN and not stale:
            line = f"Quelle ESPN (nur Stand, Uhr, Status) · NBA.com gestört: {err['message']} · Stand vor {int(age)} s"
        elif age is None:
            line = f"Noch keine Daten: {err['message']} · nächster Versuch in {int(retry)} s"
        else:
            line = f"Daten veraltet seit {int(age)} Sekunden ({err['message']}) · nächster Versuch in {int(retry)} s"
        return FeedState(day=day, games=games, other_day_games=other, source=self._source, fetched_at=self._fresh_at, age_s=age, stale=stale, stale_since_s=age if stale else None,
                         error=None if err is None else err["message"], error_status=None if err is None else err["status"], error_ref="" if err is None else err["ref"], retry_in_s=retry,
                         backoff_s=self._backoff.wait, scoreboard_day=self._scoreboard_day, notice=notice, fallback_note=self._fallback_note, status_line=line,
                         freeze_note=(self._freeze_note or (self._lag_note if self._lag_warn else None)) if err is None else None)


_feed: LiveFeed | None = None
_feed_lock = threading.Lock()


def get_feed() -> LiveFeed:
    """Gemeinsamer Feed je Prozess: alle Sitzungen teilen Zwischenspeicher und Wartezeit (kein doppelter Abruf bei mehreren Tabs)."""
    global _feed
    with _feed_lock:
        if _feed is None:
            _feed = LiveFeed()
        return _feed


# ----------------------------------------------------------------------------------------------- Verbindung zum Live-Modell
def _load_snapshots() -> dict:
    from data import projection_snapshots as snap
    return snap.load().get("games", {})


def find_snapshot(game: GameView, snapshots: dict | None = None) -> tuple[str, dict] | None:
    """(Schluessel, letzte Version) des Schnappschusses zu diesem Spiel (Spieltag + beide Mannschaften), sonst None. Schnappschuesse entstehen nur VOR dem Anpfiff."""
    snaps = _load_snapshots() if snapshots is None else snapshots
    for key, g in snaps.items():
        if g.get("game_date") == game.day and same_team(g.get("home"), game.home_nick) and same_team(g.get("away"), game.away_nick) and g.get("versions"):
            return key, g["versions"][-1]
    return None


def live_numbers(game: GameView, snapshots: dict | None = None, factors=None) -> LiveNumbers:
    """Live-Zahlen eines Spiels: Anker (Vorab-Werte aus dem Schnappschuss), Uhr, Stand und Ballbesitze gehen an engine/live_model. Ohne Schnappschuss: ohne Chancen, mit Hinweis."""
    if game.data_stale:
        return LiveNumbers(game.game_id, False, STALE_NOTE)
    try:
        found = find_snapshot(game, snapshots)
    except Exception:
        found = None
    if found is None:
        return LiveNumbers(game.game_id, False, NO_ANCHOR_NOTE)
    key, version = found
    try:
        anchor = lm.Anchor.from_snapshot(version)
        proj = lm.project(anchor, game.clock, game.home_score, game.away_score, game.possessions, factors)
    except Exception:
        return LiveNumbers(game.game_id, False, "Schnappschuss unlesbar: keine Chancen.", snapshot_key=key)
    return LiveNumbers(game.game_id, True, None, anchor, proj, key)


def live_numbers_for_state(state: FeedState, snapshots: dict | None = None, factors=None) -> dict:
    """{game_id: LiveNumbers} fuer alle Spiele des aktuellen Spieltags (vor dem Anpfiff: Vorab-Werte, laufend: Live-Werte, beendet: 0/1)."""
    snaps = _load_snapshots() if snapshots is None else snapshots
    return {g.game_id: live_numbers(g, snaps, factors) for g in state.games}


def find_game(state: FeedState, game_date: str, home: str, away: str) -> GameView | None:
    """Spiel zu einem gespeicherten Wettspiel (US-Datum + Vollnamen, Zuordnung ueber die Spitznamen)."""
    for g in state.games + state.other_day_games:
        if g.day == game_date and same_team(home, g.home_nick) and same_team(away, g.away_nick):
            return g
    return None


def bets_live(state: FeedState, snapshots: dict | None = None, day_bets: dict | None = None, player_bets: dict | None = None) -> list[dict]:
    """Eigene Wetten des Spieltags mit Live-Status: [{'key', 'game' (GameView|None), 'numbers' (LiveNumbers|None), 'bets', 'lives' ({markt: BetLive}), 'note',
    'player_bets' ({person_id: Wette}), 'player_lives' ({person_id: BetLivePlayer})}]. Ohne Schnappschuss: Team-Wetten werden angezeigt, aber ohne Status (lives leer, note erklaert es);
    Spieler-Wetten brauchen keinen Schnappschuss (Punkte aus dem Boxscore). Spiel nicht im Scoreboard: game None."""
    from data import day_bets_store as ds
    snaps = _load_snapshots() if snapshots is None else snapshots
    team = ds.get_day_bets(state.day) if day_bets is None else day_bets
    players = ds.get_day_player_bets(state.day) if player_bets is None else player_bets
    rows = []
    keys = sorted(set(team) | set(players), key=lambda k: ((team.get(k) or players.get(k))["game"].get("start_utc") or "", k))
    for key in keys:
        v = team.get(key) or {"game": players[key]["game"], "bets": {}}
        pbets = (players.get(key) or {}).get("player_bets", {})
        g = find_game(state, v["game"]["game_date"], v["game"]["home"], v["game"]["away"])
        if g is None:
            rows.append({"key": key, "game": None, "numbers": None, "bets": v["bets"], "lives": {}, "note": "Spiel (noch) nicht im Scoreboard gefunden.", "player_bets": pbets, "player_lives": {}})
            continue
        nums = live_numbers(g, snaps)
        lives = ds.evaluate_game_bets(v["bets"], nums.anchor, g.clock, g.home_score, g.away_score, g.possessions) if (nums.has_anchor and v["bets"]) else {}
        plives = ds.evaluate_player_bets(pbets, g) if pbets else {}
        rows.append({"key": key, "game": g, "numbers": nums, "bets": v["bets"], "lives": lives, "note": nums.note, "player_bets": pbets, "player_lives": plives})
    return rows
