"""
Terminal-Eingabe fuer Pre-Match-Linien und Quoten (Betano-Reihenfolge: IMMER Heim zuerst, dann Gast).

Start:  venv/bin/python eingabe.py

Fragt Linien und Quoten fuer die heutigen, noch nicht begonnenen Spiele nacheinander und EINZELN ab und speichert ueber denselben Weg wie der Tab
"Pre-Match Eingabe" (data/pre_match_store.save_card: Revisionen, updated_at, atomares Schreiben, Tageskopie, Sperre ab Anpfiff).
Keine API-Abrufe: Die Spieleliste kommt aus dem lokalen Zwischenspeicher (data/upcoming_cache.json), die Kader aus data/rosters.json (nur lesen).
Die App darf parallel laufen: vor dem Speichern wird frisch von der Platte gelesen, geschrieben werden nur geaenderte Zeilen.

Tasten:  Enter = ueberspringen / vorhandenen Wert behalten · x = Markt/Linie entfernen · z = ein Schritt zurueck · q = beenden.
Am 'Speichern?'-Prompt: s = zu einem Bereich springen (Sieger, Spread, Total, Team Totals, Spieler); danach direkt zurueck zur Zusammenfassung.
Spread: Linie des genannten Teams mit Betano-Vorzeichen (Wizards -4.5 = Wizards Favorit). Intern wird die Heim-Linie gespeichert (wie im Tab);
eine Gast-Linie wird mit 'g' davor eingegeben ('g +4,5') und umgerechnet.

Technik: Der Ablauf eines Spiels ist eine Funktion (build_plan), die ihre Fragen ueber Session.ask stellt. 'z' verwirft die letzte Antwort und
spielt den Ablauf mit den bisherigen Antworten erneut ab (ohne neu zu fragen); so funktionieren Schleifen und Leitern auch rueckwaerts.
"""
from __future__ import annotations

import copy
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from data import market_lines
from data import pre_match_store as store
from data import pregame_lines
from data import rosters

BOOKMAKER = "Betano"
BERLIN = ZoneInfo("Europe/Berlin")
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MAX_SPREAD_LINES = store.MAX_SPREAD_EXTRA + 1       # Hauptlinie + weitere
TOTAL_LADDER = (-3, -2, -1, 1, 2, 3)               # Schritt 1,0 um die Hauptlinie (7 Linien mit der Hauptlinie)
MIN_ODDS = 1.01
REMOVE = object()                                   # Antwort "x"


class Back(Exception):
    """'z': ein Schritt zurueck."""


class Quit(Exception):
    """'q' (oder Ende der Eingabe): sauber beenden."""


class Console:
    def __init__(self, read=input, write=print):
        self.read, self.write = read, write

    def ask_raw(self, prompt: str) -> str:
        try:
            return self.read(prompt)
        except (EOFError, KeyboardInterrupt):
            self.write("")
            raise Quit() from None


# ------------------------------------------------------------------------------ Formate und Parser
def fnum(v: float) -> str:
    v = float(v)
    return str(int(v)) if v == int(v) else f"{v:g}"


def sgn(v: float) -> str:
    """Betano-Schreibweise einer Spread-Linie: '-4.5', '+4.5', '0'."""
    v = float(v) + 0.0
    return "0" if v == 0 else (f"+{fnum(v)}" if v > 0 else f"-{fnum(abs(v))}")


def odds_text(v: float) -> str:
    return f"{float(v):.2f}"


def parse_odds(text: str) -> float:
    v = store.parse_odds_input(text)
    if v < MIN_ODDS:
        raise store.OddsInputError("Die Quote muss mindestens 1,01 sein.")
    return v


def parse_yes_no(text: str) -> bool:
    t = text.strip().lower()
    if t in ("j", "ja", "y", "yes"):
        return True
    if t in ("n", "nein", "no"):
        return False
    raise store.OddsInputError("Bitte j (ja) oder n (nein) eingeben.")


def make_count_parser(cap: int):
    """Anzahl Spieler eines Teams: 0 bis cap (cap = noch freie Plaetze von store.MAX_PLAYERS je Spiel)."""
    def parse(text: str) -> int:
        t = text.strip()
        if not re.fullmatch(r"\d+", t) or not (0 <= int(t) <= cap):
            raise store.OddsInputError(f"Bitte eine ganze Zahl von 0 bis {cap} eingeben (höchstens {store.MAX_PLAYERS} Spieler je Spiel).")
        return int(t)
    return parse


def nick(name: str) -> str:
    return team_info_nick(name)


def team_info_nick(name: str) -> str:
    try:
        from ui.score_cards import team_info
        return team_info(name)["nick"]
    except Exception:
        return (name or "").split()[-1]


def make_spread_parser(home: str, away: str, taken: set):
    """Linie des genannten Heim-Teams (z. B. '-4,5'); mit 'g' oder dem Namen des Gastteams davor die Linie des Gastteams ('g +4,5').
    Rueckgabe: Heim-Linie (Konvention des Tabs)."""
    away_aliases = sorted({"gast", "g", nick(away).lower(), away.lower()}, key=len, reverse=True)
    home_aliases = sorted({"heim", "h", nick(home).lower(), home.lower()}, key=len, reverse=True)

    def parse(text: str) -> float:
        t, tl, side = text.strip(), text.strip().lower(), "home"
        for alias, s in [(a, "away") for a in away_aliases] + [(a, "home") for a in home_aliases]:
            if tl.startswith(alias) and re.match(r"^[\s+\-−\d.,]", t[len(alias):] or " ") and t[len(alias):].strip():
                t, side = t[len(alias):].strip(), s
                break
        line = store.parse_line_input(t)
        line = (-line + 0.0) if side == "away" else line
        if round(line, 2) in taken:
            raise store.OddsInputError("Diese Spread-Linie ist für dieses Spiel schon erfasst.")
        return line
    return parse


def parse_total(text: str) -> float:
    return store.parse_total_input(text)


# ------------------------------------------------------------------------------ Ablauf mit Wiederholung
SECTIONS = ["winner", "spread", "total", "team_home", "team_away", "players_home", "players_away"]


def section_menu(g: dict) -> list[tuple[str, str]]:
    """Menue fuer 's' am 'Speichern?'-Prompt: [(Schluessel, Beschriftung)] in der Reihenfolge des Ablaufs (Nummer = Position + 1)."""
    H, A = nick(g["home"]), nick(g["away"])
    names = ["Sieger", "Spread", "Total", f"Team Total {H}", f"Team Total {A}", f"Spieler {H}", f"Spieler {A}"]
    return list(zip(SECTIONS, names))


class Session:
    """Stellt die Fragen eines Spiels. Die Antworten werden je Bereich (SECTIONS) gemerkt; bereits beantwortete Fragen werden beim Wiederholen
    daraus bedient. So kann ein einzelner Bereich neu beantwortet werden (Sprung mit 's'), ohne die anderen zu verlieren."""

    def __init__(self, con: Console):
        self.con = con
        self.data: dict[str, list] = {k: [] for k in SECTIONS}
        self.cur = SECTIONS[0]
        self.pos = 0
        self.jump: str | None = None              # Bereich, der gerade per 's' neu beantwortet wird
        self.jump_backup: list | None = None      # seine bisherigen Antworten (fuer 'z' am Bereichsanfang = Sprung abbrechen)

    @property
    def answers(self) -> list:
        return [a for k in SECTIONS for a in self.data[k]]

    def section(self, key: str) -> None:
        self.cur, self.pos = key, 0

    def reset(self) -> None:
        self.section(SECTIONS[0])

    @property
    def live(self) -> bool:
        return self.pos >= len(self.data[self.cur])

    def jump_to(self, key: str) -> None:
        self.jump, self.jump_backup = key, self.data[key]
        self.data[key] = []

    def end_jump(self) -> None:
        self.jump = self.jump_backup = None

    def undo(self) -> str:
        """'z' mitten im Ablauf: letzte Antwort verwerfen. Rueckgabe: 'ok' | 'jump_cancel' (am Anfang des Sprung-Bereichs: alte Antworten zurueck)
        | 'first' (allererste Frage)."""
        lst = self.data[self.cur]
        if self.jump == self.cur and not lst:
            self.data[self.cur] = self.jump_backup or []
            self.end_jump()
            return "jump_cancel"
        if lst:
            lst.pop()
            return "ok"
        for k in reversed(SECTIONS[:SECTIONS.index(self.cur)]):
            if self.data[k]:
                self.data[k].pop()
                return "ok"
        return "first"

    def undo_last(self) -> None:
        """'z' am 'Speichern?'-Prompt: die letzte Antwort im Ablauf (letzter nicht leerer Bereich) verwerfen."""
        for k in reversed(SECTIONS):
            if self.data[k]:
                self.data[k].pop()
                return

    def say(self, text: str = "") -> None:
        if self.live:
            self.con.write(text)

    def ask(self, prompt: str, parse, default=None, default_text: str | None = None, allow_x: bool = False, required: bool = False,
            hint: str | None = None):
        """Rueckgabe: geparster Wert | default (Enter mit Vorgabe) | None (Enter ohne Vorgabe) | REMOVE ('x')."""
        lst = self.data[self.cur]
        if self.pos < len(lst):
            val = lst[self.pos]
            self.pos += 1
            return val
        shown = f" [{default_text}]" if default_text is not None else (f" [{hint}]" if hint else "")
        while True:
            t = self.con.ask_raw(f"{prompt}{shown}: ").strip()
            low = t.lower()
            if low == "q":
                raise Quit()
            if low == "z":
                raise Back()
            if t == "":
                if default is not None:
                    val = default
                elif required:
                    self.con.write("  Bitte einen Wert eingeben.")
                    continue
                else:
                    val = None
            elif low == "x":
                if not allow_x:
                    self.con.write("  Hier gibt es nichts zu entfernen (die Hauptlinie kann nur geändert werden).")
                    continue
                val = REMOVE
            else:
                try:
                    val = parse(t)
                except store.OddsInputError as e:
                    self.con.write(f"  {e}")
                    continue
            lst.append(val)
            self.pos += 1
            return val


# ------------------------------------------------------------------------------ Spiele
def start_label(start_utc: str | None) -> str:
    ts = store.parse_utc(start_utc) if start_utc else None
    if ts is None:
        return "Anpfiff unbekannt"
    dt = datetime.fromtimestamp(ts, BERLIN)
    return f"{WEEKDAYS[dt.weekday()]} {dt:%d.%m.} {dt:%H:%M}"


def list_games(now: float | None = None, games: list | None = None) -> list[dict]:
    """Noch nicht begonnene Spiele aus dem lokalen Zwischenspeicher (kein Abruf), nach Anpfiff sortiert.
    Begonnene, laufende und beendete Spiele werden nicht angeboten."""
    now = now if now is not None else time.time()
    if games is None:
        import json
        from data.fetcher import _upcoming_cache_path
        try:
            games = json.loads(_upcoming_cache_path().read_text()).get("games", [])
        except Exception:
            return []
    out = []
    for g in games:
        try:
            home, away = g["home_team"]["full_name"], g["visitor_team"]["full_name"]
        except (KeyError, TypeError):
            continue
        if str(g.get("status_state") or "").lower() in ("final", "live", "in_progress") or str(g.get("status") or "").lower() == "final":
            continue
        start = store.normalize_start(g.get("datetime"))
        if start is None or not store.is_editable(start, now):
            continue
        out.append({"home": home, "away": away, "date": g.get("date") or "", "start": start})
    return sorted(out, key=lambda x: x["start"])


def cache_reference(g: dict) -> dict:
    """Vorab-Linien aus dem lokalen Speicher (nur zur Plausibilitaetswarnung): {'spread': Heim-Linie, 'total', 'team_total_away'/'_home'}."""
    ref = {}
    try:
        lines, _src, at = pregame_lines.line_for_game_ex([], None, g["home"], g["away"], game_start=pregame_lines.parse_utc(g["start"]))
        for m, c in market_lines.cache_candidates(lines, g["home"], g["away"], at).items():
            ref[m] = -c["line"] + 0.0 if m == "spread" else c["line"]
    except Exception:
        pass
    return ref


def _saved_main(lines: list[dict]) -> dict | None:
    return next((l for l in lines if l.get("id") == "main"), None)


def _warn_dev(plan: dict, market: str, label: str, value: float, ref: dict) -> None:
    if market in ref and abs(value - ref[market]) > market_lines.DEVIATION_LIMITS[market]:
        txt = sgn if market == "spread" else fnum
        plan["warnings"].append(f"{label} {txt(value)} weicht um {fnum(abs(value - ref[market]))} vom Marktwert im Speicher ({txt(ref[market])}) ab "
                                f"(Grenze {fnum(market_lines.DEVIATION_LIMITS[market])}). Wird trotzdem gespeichert.")


def build_plan(s: Session, g: dict, entry: dict | None, roster: dict, ref: dict | None = None) -> dict:
    """Stellt alle Fragen eines Spiels (Heim zuerst) und liefert den Plan:
    {'winner': {home_odds, away_odds}|None, 'spread': [Zeilen], 'total': [...], 'team': {'home': [...], 'away': [...]}, 'players': [Bloecke],
     'remove': [Entfernungen], 'warnings': [...]}; Zeile = {id|None, line, odds..., direction}."""
    ref = ref or {}
    H, A = nick(g["home"]), nick(g["away"])
    plan = {"winner": None, "spread": [], "total": [], "team": {"home": [], "away": []}, "players": [], "remove": [], "replaced": set(), "warnings": []}
    mk = (entry or {}).get("markets", {})

    # ---- 1. Sieger
    s.section("winner")
    s.say("— Sieger —")
    w = mk.get(store.WINNER)
    h = s.ask(f"Quote {H}", parse_odds, default=w["home_odds"] if w else None, default_text=odds_text(w["home_odds"]) if w else None)
    if h is not None:
        a = s.ask(f"Quote {A}", parse_odds, default=w["away_odds"] if w else None, default_text=odds_text(w["away_odds"]) if w else None, required=True)
        plan["winner"] = {"home_odds": h, "away_odds": a}

    # ---- 2. Spread (bis zu 5 Linien)
    s.section("spread")
    s.say("— Spread —")
    lines = store.active_spread_lines(entry)
    main = _saved_main(lines)
    taken: set = set()
    line = s.ask(f"Spread-Linie {H}", make_spread_parser(g["home"], g["away"], taken), default=main["line_home"] if main else None,
                 default_text=sgn(main["line_home"]) if main else None)
    if line is not None:
        taken.add(round(line, 2))
        _warn_dev(plan, "spread", f"Spread {H}", line, ref)

        def spread_odds(sv, ln):
            ho = s.ask(f"Quote {H} {sgn(ln)}", parse_odds, default=sv["home_odds"] if sv else None, default_text=odds_text(sv["home_odds"]) if sv else None, required=True)
            ao = s.ask(f"Quote {A} {sgn(-ln)}", parse_odds, default=sv["away_odds"] if sv else None, default_text=odds_text(sv["away_odds"]) if sv else None, required=True)
            return ho, ao
        ho, ao = spread_odds(main, line)
        plan["spread"].append({"id": "main" if main else "main", "line": line, "home_odds": ho, "away_odds": ao})
        n = 1
        for sv in [l for l in lines if l.get("id") != "main"]:
            n += 1
            taken.discard(round(sv["line_home"], 2))
            ln = s.ask(f"Weitere Spread-Linie {H} ({n} von max. {MAX_SPREAD_LINES})", make_spread_parser(g["home"], g["away"], taken),
                       default=sv["line_home"], default_text=sgn(sv["line_home"]), allow_x=True)
            if ln is REMOVE:
                plan["remove"].append(("spread", sv["id"]))
                n -= 1
                continue
            taken.add(round(ln, 2))
            ho, ao = spread_odds(sv, ln)
            plan["spread"].append({"id": sv["id"], "line": ln, "home_odds": ho, "away_odds": ao})
        while n < MAX_SPREAD_LINES:
            ln = s.ask(f"Weitere Spread-Linie {H} ({n + 1} von max. {MAX_SPREAD_LINES})", make_spread_parser(g["home"], g["away"], taken), hint="Enter = fertig")
            if ln is None:
                break
            n += 1
            taken.add(round(ln, 2))
            ho, ao = spread_odds(None, ln)
            plan["spread"].append({"id": None, "line": ln, "home_odds": ho, "away_odds": ao})

    # ---- 3. Total mit automatischer Leiter
    s.section("total")
    s.say("— Total —")
    lines = store.active_total_lines(entry)
    main = _saved_main(lines)
    t = s.ask("Total-Linie", parse_total, default=main["line"] if main else None, default_text=fnum(main["line"]) if main else None)
    if t is not None:
        _warn_dev(plan, "total", "Total", t, ref)
        ov = s.ask(f"Quote Over {fnum(t)}", parse_odds, default=main["over_odds"] if main else None, default_text=odds_text(main["over_odds"]) if main else None, required=True)
        un = s.ask(f"Quote Under {fnum(t)}", parse_odds, default=main["under_odds"] if main else None, default_text=odds_text(main["under_odds"]) if main else None, required=True)
        plan["total"].append({"id": "main", "line": t, "over_odds": ov, "under_odds": un, "direction": None})
        ladder = [round(t + d, 2) for d in TOTAL_LADDER if t + d >= store.MIN_TOTAL]
        extras = [l for l in lines if l.get("id") != "main"]
        matched = set()
        # Gespeicherte Zusatzlinie auf der neuen Hauptlinie: wird von der Hauptlinie ersetzt (sonst Duplikat)
        for sv in extras:
            if abs(sv["line"] - t) < 1e-9:
                matched.add(sv["id"])
                plan["remove"].append(("total", sv["id"]))
                plan["replaced"].add(("total", sv["id"]))
        for ln in sorted(ladder):
            direction = "lower" if ln < t else "higher"
            sv = next((l for l in extras if abs(l["line"] - ln) < 1e-9), None)      # gespeicherte Zusatzlinie auf dieser Leiter-Linie: wird ueberschrieben
            keep_id = None
            if sv:
                matched.add(sv["id"])
                if sv.get("direction") == direction:
                    keep_id = sv["id"]
                else:                                                               # Richtung hat sich mit der Hauptlinie geaendert: neu anlegen, alte ersetzen
                    plan["remove"].append(("total", sv["id"]))
                    plan["replaced"].add(("total", sv["id"]))
            o = s.ask(f"Quote Over {fnum(ln)}", parse_odds, default=sv["over_odds"] if sv else None, default_text=odds_text(sv["over_odds"]) if sv else None,
                      allow_x=sv is not None)
            if o is None:
                continue
            if o is REMOVE:
                if ("total", sv["id"]) not in plan["remove"]:
                    plan["remove"].append(("total", sv["id"]))
                continue
            u = s.ask(f"Quote Under {fnum(ln)}", parse_odds, default=sv["under_odds"] if sv else None, default_text=odds_text(sv["under_odds"]) if sv else None, required=True)
            plan["total"].append({"id": keep_id, "line": ln, "over_odds": o, "under_odds": u, "direction": direction})
        stale = [l for l in extras if l["id"] not in matched and ("total", l["id"]) not in plan["remove"]]
        if stale:
            names = ", ".join(fnum(l["line"]) for l in stale)
            rm = s.ask(f"Gespeicherte Total-Linien {names} passen nicht zur neuen Leiter. Entfernen? (Enter = entfernen, n = behalten)", parse_yes_no,
                       default=True)
            if rm:
                plan["remove"].extend(("total", l["id"]) for l in stale)

    # ---- 4. Team Totals (Heim, dann Gast), keine automatische Leiter
    for side, team in (("home", g["home"]), ("away", g["away"])):
        N = nick(team)
        s.section(f"team_{side}")
        s.say(f"— Team Total {N} —")
        lines = store.team_total_lines(entry, side)
        main = _saved_main(lines)
        tl = s.ask(f"Team-Total-Linie {N}", store.parse_team_total_input, default=main["line"] if main else None, default_text=fnum(main["line"]) if main else None)
        if tl is None:
            continue
        _warn_dev(plan, f"team_total_{side}", f"Team Total {N}", tl, ref)

        def tt_odds(sv, ln):
            o = s.ask(f"Quote Over {N} {fnum(ln)}", parse_odds, default=sv["over_odds"] if sv else None, default_text=odds_text(sv["over_odds"]) if sv else None, required=True)
            u = s.ask(f"Quote Under {N} {fnum(ln)}", parse_odds, default=sv["under_odds"] if sv else None, default_text=odds_text(sv["under_odds"]) if sv else None, required=True)
            return o, u
        o, u = tt_odds(main, tl)
        rows = plan["team"][side]
        rows.append({"id": "main", "line": tl, "over_odds": o, "under_odds": u, "direction": None})
        used = {tl}

        def make_parse(own: float | None = None):
            def parse(text):
                v = store.parse_team_total_input(text)
                if v in used and v != own:
                    raise store.OddsInputError("Diese Team-Total-Linie ist schon erfasst.")
                d = "higher" if v > tl else "lower"
                same = sum(1 for r in rows if r["direction"] == d and r["line"] != own)
                if v == tl:
                    raise store.OddsInputError("Das ist die Hauptlinie.")
                if same >= store.MAX_TOTAL_PER_DIRECTION:
                    raise store.OddsInputError(f"Höchstens {store.MAX_TOTAL_PER_DIRECTION} {'höhere' if d == 'higher' else 'niedrigere'} Linien je Team.")
                return v
            return parse
        for sv in [l for l in lines if l.get("id") != "main"]:
            ln = s.ask(f"Weitere Team-Total-Linie {N}", make_parse(sv["line"]), default=sv["line"], default_text=fnum(sv["line"]), allow_x=True)
            if ln is REMOVE:
                plan["remove"].append(("team", side, sv["id"]))
                continue
            o, u = tt_odds(sv, ln)
            used.add(ln)
            rows.append({"id": sv["id"], "line": ln, "over_odds": o, "under_odds": u, "direction": "higher" if ln > tl else "lower"})
        while True:
            more = s.ask(f"Weitere Team-Total-Linie {N} vorhanden? (j = ja, Enter = nein)", parse_yes_no)
            if not more:
                break
            ln = s.ask(f"Weitere Team-Total-Linie {N}", make_parse(), required=True)
            o, u = tt_odds(None, ln)
            used.add(ln)
            rows.append({"id": None, "line": ln, "over_odds": o, "under_odds": u, "direction": "higher" if ln > tl else "lower"})

    # ---- 5. Spieler-Meilensteine (nur Over), Heim-Team zuerst
    chosen: set = set()
    for side, team in (("home", g["home"]), ("away", g["away"])):
        N = nick(team)
        s.section(f"players_{side}")
        s.say(f"— Spieler {N} —")
        saved_blocks = [b for b in store.active_player_blocks(entry) if b.get("team") == team]
        if saved_blocks:
            s.say("  Gespeichert: " + "; ".join(f"{b['name']} ({', '.join(str(l['threshold']) + '+' for l in store.player_lines(b))})" for b in saved_blocks))
        if roster["status"] != "ok":
            s.say(f"  Keine Kaderdatei ({roster['message']}): Spieler werden übersprungen.")
            continue
        players = [p for p in roster["teams"].get(team, [])]
        if not players:
            s.say(f"  Kein Kader für {team} in der Kaderdatei: Spieler werden übersprungen.")
            continue
        other = {int(b["person_id"]) for b in store.active_player_blocks(entry) if b.get("team") != team} | {int(c) for c in chosen}
        cnt = s.ask(f"Anzahl {N}-Spieler [Enter = 0]", make_count_parser(max(0, store.MAX_PLAYERS - len(other))))
        for i in range(1, (cnt or 0) + 1):
            def find(text, players=players):
                q = rosters.normalize_name(text).split()
                if not q:
                    raise store.OddsInputError("Name fehlt.")
                hits = [p for p in players if all(tok in rosters.normalize_name(p["name"]) for tok in q)]
                exact = [p for p in hits if rosters.normalize_name(p["name"]) == " ".join(q)]
                hits = exact if len(exact) == 1 else hits
                if not hits:
                    raise store.OddsInputError(f"Kein Spieler „{text.strip()}“ im Kader der {N} gefunden. Bitte noch einmal.")
                return hits
            cands = s.ask(f"{N}-Spieler {i} von {cnt}: Name", find, required=True)
            if len(cands) > 1:
                s.say("  Mehrere Treffer:")
                for k, p in enumerate(cands, 1):
                    s.say(f"   {k}) {p['name']} ({p.get('position') or '–'}, #{p.get('jersey') or '–'})")
                pick = s.ask("Nummer", lambda t, n=len(cands): _pick(t, n), required=True)
                p = cands[pick - 1]
            else:
                p = cands[0]
            if p["person_id"] in chosen:
                s.say(f"  {p['name']} ist schon erfasst, übersprungen.")
                continue
            chosen.add(p["person_id"])
            blk = next((b for b in saved_blocks if int(b["person_id"]) == int(p["person_id"])), None)
            slines = {int(l["threshold"]): l for l in store.player_lines(blk)} if blk else {}
            lo_s = min(slines) if slines else None
            hi_s = max(slines) if slines else None
            start = s.ask(f"Start-Linie {p['name']}", store.parse_threshold_input, default=lo_s, default_text=str(lo_s) if lo_s else None,
                          allow_x=blk is not None, hint="Enter = Spieler überspringen" if not blk else None)
            if start is None:
                continue
            if start is REMOVE:
                plan["remove"].append(("player_block", blk["id"]))
                continue

            def parse_end(text, start=start):
                v = store.parse_threshold_input(text)
                if v < start:
                    raise store.OddsInputError("Die End-Linie darf nicht unter der Start-Linie liegen.")
                if v - start + 1 > store.MAX_MILESTONES:
                    raise store.OddsInputError(f"Höchstens {store.MAX_MILESTONES} Linien je Spieler.")
                return v
            dflt = max(hi_s, start) if hi_s else start
            end = s.ask(f"End-Linie {p['name']}", parse_end, default=dflt, default_text=str(dflt))
            rows = []
            for th in range(start, end + 1):
                sv = slines.get(th)
                q = s.ask(f"Quote {p['name']} {th}+", parse_odds, default=sv["odds"] if sv else None, default_text=odds_text(sv["odds"]) if sv else None,
                          allow_x=sv is not None)
                if q is None:
                    continue
                if q is REMOVE:
                    plan["remove"].append(("player_line", blk["id"], sv["id"]))
                    continue
                rows.append({"id": sv["id"] if sv else None, "threshold": th, "odds": q})
            if rows:
                plan["players"].append({"block_id": blk["id"] if blk else None, "person_id": p["person_id"], "name": p["name"], "team": team,
                                        "team_abbreviation": p.get("team_abbreviation") or "", "rows": rows})
                _warn_monotonic(plan, p["name"], rows)
    return plan


def _warn_monotonic(plan: dict, name: str, rows: list[dict]) -> None:
    """Hinweis, wenn die Quote bei einer hoeheren Schwelle nicht hoeher ist als bei der niedrigeren (ein hoeherer Meilenstein ist schwerer). Wird trotzdem gespeichert."""
    srt = sorted(rows, key=lambda r: r["threshold"])
    bad = [(a, b) for a, b in zip(srt, srt[1:]) if b["odds"] <= a["odds"]]
    if bad:
        txt = "; ".join(f"{b['threshold']}+ @ {odds_text(b['odds'])} nicht höher als {a['threshold']}+ @ {odds_text(a['odds'])}" for a, b in bad[:3])
        plan["warnings"].append(f"{name}: Quoten steigen nicht mit der Schwelle ({txt}{' …' if len(bad) > 3 else ''}; {len(bad)} Stelle(n)). Bitte prüfen. Wird trotzdem gespeichert.")


def _pick(text: str, n: int) -> int:
    t = text.strip()
    if not re.fullmatch(r"\d+", t) or not (1 <= int(t) <= n):
        raise store.OddsInputError(f"Bitte eine Nummer von 1 bis {n} eingeben.")
    return int(t)


# ------------------------------------------------------------------------------ Zusammenfassung und Speichern
def _same(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) < 1e-9


def row_state(kind: str, row: dict, saved_lines: list[dict]) -> str:
    """'neu' | 'geändert' | 'gespeichert' (unveraendert) gegenueber dem Stand beim Start des Spiels."""
    sv = next((l for l in saved_lines if row.get("id") and l.get("id") == row["id"]), None)
    if sv is None:
        return "neu"
    if kind == "spread":
        same = _same(sv.get("line_home"), row["line"]) and _same(sv.get("home_odds"), row["home_odds"]) and _same(sv.get("away_odds"), row["away_odds"])
    elif kind == "milestone":
        same = _same(sv.get("threshold"), row["threshold"]) and _same(sv.get("odds"), row["odds"])
    else:
        same = _same(sv.get("line"), row["line"]) and _same(sv.get("over_odds"), row["over_odds"]) and _same(sv.get("under_odds"), row["under_odds"])
    return "gespeichert" if same else "geändert"


def summary_lines(g: dict, plan: dict, entry: dict | None) -> list[str]:
    H, A = nick(g["home"]), nick(g["away"])
    out = [f"{g['home']} – {g['away']} ({start_label(g['start'])} Uhr)"]
    tag = lambda st: "" if st == "neu" else f"  ({st})"
    w = plan["winner"]
    sw = ((entry or {}).get("markets", {}) or {}).get(store.WINNER)
    out.append("Sieger:  " + (f"{H} {odds_text(w['home_odds'])} | {A} {odds_text(w['away_odds'])}"
                              + ("  (gespeichert)" if sw and _same(sw["home_odds"], w["home_odds"]) and _same(sw["away_odds"], w["away_odds"]) else "") if w else "–"))
    sl = store.active_spread_lines(entry)
    out.append("Spread:  " + ("–" if not plan["spread"] else ""))
    for r in plan["spread"]:
        out.append(f"   {H} {sgn(r['line'])} @ {odds_text(r['home_odds'])} | {A} {sgn(-r['line'])} @ {odds_text(r['away_odds'])}{tag(row_state('spread', r, sl))}")
    tl = store.active_total_lines(entry)
    out.append("Total:   " + ("–" if not plan["total"] else ""))
    for r in sorted(plan["total"], key=lambda x: x["line"]):
        out.append(f"   {fnum(r['line'])}: Over {odds_text(r['over_odds'])} | Under {odds_text(r['under_odds'])}"
                   f"{'  [Hauptlinie]' if r['id'] == 'main' else ''}{tag(row_state('total', r, tl))}")
    for side, team in (("home", g["home"]), ("away", g["away"])):
        rows = plan["team"][side]
        out.append(f"Team Total {nick(team)}: " + ("–" if not rows else ""))
        for r in sorted(rows, key=lambda x: x["line"]):
            out.append(f"   {fnum(r['line'])}: Over {odds_text(r['over_odds'])} | Under {odds_text(r['under_odds'])}"
                       f"{'  [Hauptlinie]' if r['id'] == 'main' else ''}{tag(row_state('team', r, store.team_total_lines(entry, side)))}")
    out.append("Spieler: " + ("–" if not plan["players"] else ""))
    for b in plan["players"]:
        blk = next((x for x in store.active_player_blocks(entry) if x["id"] == b["block_id"]), None)
        sls = store.player_lines(blk) if blk else []
        out.append(f"   {b['name']} ({nick(b['team'])}): " + ", ".join(f"{r['threshold']}+ @ {odds_text(r['odds'])}" +
                                                                     ("" if row_state("milestone", r, sls) == "neu" else "*" if row_state("milestone", r, sls) == "gespeichert" else "'")
                                                                     for r in b["rows"]))
    if any(row_state("milestone", r, store.player_lines(next((x for x in store.active_player_blocks(entry) if x["id"] == b["block_id"]), {}))) == "gespeichert"
           for b in plan["players"] for r in b["rows"]):
        out.append("   (* = schon gespeichert, unverändert)")
    for rm in plan["remove"]:
        out.append("ENTFERNEN: " + describe_removal(rm, entry, g) + ("  (wird durch die neue Zeile ersetzt)" if rm in plan["replaced"] else ""))
    for wmsg in plan["warnings"]:
        out.append("Hinweis: " + wmsg)
    return out


def describe_removal(rm: tuple, entry: dict | None, g: dict) -> str:
    kind = rm[0]
    if kind == "spread":
        l = next((x for x in store.active_spread_lines(entry) if x["id"] == rm[1]), None)
        return f"Spread {nick(g['home'])} {sgn(l['line_home'])}" if l else "Spread-Linie"
    if kind == "total":
        l = next((x for x in store.active_total_lines(entry) if x["id"] == rm[1]), None)
        return f"Total {fnum(l['line'])}" if l else "Total-Linie"
    if kind == "team":
        l = next((x for x in store.team_total_lines(entry, rm[1]) if x["id"] == rm[2]), None)
        return f"Team Total {nick(g[rm[1]])} {fnum(l['line'])}" if l else "Team-Total-Linie"
    b = next((x for x in store.active_player_blocks(entry) if x["id"] == rm[1]), None)
    if kind == "player_block":
        return f"Spieler {b['name']} (alle Linien)" if b else "Spieler"
    l = next((x for x in store.player_lines(b or {}) if x["id"] == rm[2]), None) if b else None
    return f"{b['name']} {l['threshold']}+" if b and l else "Spielerlinie"


def _str(v) -> str:
    return repr(float(v)) if not isinstance(v, str) else v


def _remove_all(g: dict, plan: dict, now: float | None) -> list:
    removed = []
    for rm in plan["remove"]:
        try:
            if rm[0] == "spread":
                store.remove_spread_line(g["date"], g["start"], g["home"], g["away"], rm[1], now=now)
            elif rm[0] == "total":
                store.remove_total_line(g["date"], g["start"], g["home"], g["away"], rm[1], now=now)
            elif rm[0] == "team":
                store.remove_team_total_line(g["date"], g["start"], g["home"], g["away"], rm[1], rm[2], now=now)
            elif rm[0] == "player_block":
                store.remove_player_block(g["date"], g["start"], g["home"], g["away"], rm[1], now=now)
            else:
                store.remove_player_line(g["date"], g["start"], g["home"], g["away"], rm[1], rm[2], now=now)
        except store.OddsInputError:
            continue                                      # schon entfernt (z. B. im Tab): nichts zu tun
        removed.append(rm)
    return removed


def execute_plan(g: dict, plan: dict, entry: dict | None, roster: dict, ref: dict, now: float | None = None) -> dict:
    """Schreibt den Plan. Vor dem Schreiben wird der Eintrag frisch von der Platte gelesen; unveraenderte Zeilen werden nicht erneut
    geschrieben (nur wenn der Store die Hauptlinie als erste Zeile verlangt, mit dem aktuellen Plattenwert). Rueckgabe: das Ergebnis von save_card
    (oder {'status': 'unchanged'}). Wirft CardInputError/OddsInputError/GameStartedError/StoreError."""
    key = store.game_key(g["date"], g["start"], g["home"], g["away"])
    fresh = (store.load().get("entries") or {}).get(key)

    def changed(kind, rows, saved_lines):
        return [r for r in rows if row_state(kind, r, saved_lines) != "gespeichert"]

    def with_main(kind, rows, saved_lines, fresh_lines, to_text):
        """Nur geaenderte Zeilen; die Hauptlinie steht aber immer vorn (Pflicht im Store): unveraendert = aktueller Plattenwert."""
        ch = changed(kind, rows, saved_lines)
        if not ch:
            return None
        if ch[0].get("id") != "main":
            fm = _saved_main(fresh_lines)
            main_row = next((r for r in rows if r.get("id") == "main"), None)
            if fm is not None:
                ch = [{**{"id": "main"}, **fm_values(kind, fm)}] + ch
            elif main_row is not None:
                ch = [main_row] + ch
        return [to_text(r) for r in ch]

    def fm_values(kind, fm):
        if kind == "spread":
            return {"line": fm["line_home"], "home_odds": fm["home_odds"], "away_odds": fm["away_odds"]}
        return {"line": fm["line"], "over_odds": fm["over_odds"], "under_odds": fm["under_odds"], "direction": None}

    spread_rows = with_main("spread", plan["spread"], store.active_spread_lines(entry), store.active_spread_lines(fresh),
                            lambda r: {"id": r["id"], "line": _str(r["line"]), "home_odds": _str(r["home_odds"]), "away_odds": _str(r["away_odds"]), "bookmaker": BOOKMAKER})
    ou = lambda r: {"id": r["id"], "direction": r.get("direction"), "line": _str(r["line"]), "over_odds": _str(r["over_odds"]), "under_odds": _str(r["under_odds"]), "bookmaker": BOOKMAKER}
    total_rows = with_main("total", plan["total"], store.active_total_lines(entry), store.active_total_lines(fresh), ou)
    team_rows = {side: with_main("team", plan["team"][side], store.team_total_lines(entry, side), store.team_total_lines(fresh, side), ou) for side in store.TEAMS}
    blocks = []
    for b in plan["players"]:
        saved_blk = next((x for x in store.active_player_blocks(entry) if x["id"] == b["block_id"]), None)
        ch = changed("milestone", b["rows"], store.player_lines(saved_blk) if saved_blk else [])
        if ch:
            blocks.append({"block_id": b["block_id"], "person_id": b["person_id"], "name": b["name"], "team": b["team"], "team_abbreviation": b["team_abbreviation"],
                           "mode": "milestones", "rows": [{"id": r["id"], "value": str(r["threshold"]), "odds": _str(r["odds"]), "bookmaker": BOOKMAKER} for r in ch]})
    winner = None
    if plan["winner"]:
        sw = ((entry or {}).get("markets", {}) or {}).get(store.WINNER)
        if not (sw and _same(sw["home_odds"], plan["winner"]["home_odds"]) and _same(sw["away_odds"], plan["winner"]["away_odds"])):
            winner = {"home_odds": _str(plan["winner"]["home_odds"]), "away_odds": _str(plan["winner"]["away_odds"]), "bookmaker": BOOKMAKER}
    if winner is None and spread_rows is None and total_rows is None and not blocks and all(v is None for v in team_rows.values()):
        return {"status": "unchanged", "removed": _remove_all(g, plan, now)}
    main_total = next((r["line"] for r in plan["total"] if r["id"] == "main"), None)
    main_spread = next((r["line"] for r in plan["spread"] if r["id"] == "main"), None)
    sugg = tsugg = None
    if "spread" in ref:
        sugg = {"line_home": round(ref["spread"], 2), "line_home_rounded": store.round_half(ref["spread"]), "source": "cache_vorab"}
    if "total" in ref:
        tsugg = {"line": round(ref["total"], 2), "line_rounded": store.round_half(ref["total"]), "source": "cache_vorab"}
    team_sugg = store.derive_team_suggestions(main_total, main_spread) if main_total is not None and main_spread is not None else None
    kw = dict(winner=winner, spread_rows=spread_rows, suggestion=sugg, total_rows=total_rows, total_suggestion=tsugg, team_rows=team_rows,
              team_suggestion=team_sugg, team_names={"away": nick(g["away"]), "home": nick(g["home"])}, player_blocks=blocks or None,
              roster_fetched_at=roster.get("fetched_at"), now=now)
    # Erst pruefen (mit den geplanten Entfernungen als erledigt), dann entfernen, dann speichern: wird das Speichern abgelehnt, bleibt alles wie es war.
    if plan["remove"]:
        store.save_card(g["date"], g["start"], g["home"], g["away"], assume_removed=list(plan["remove"]), dry_run=True, **kw)
    removed = _remove_all(g, plan, now)
    res = store.save_card(g["date"], g["start"], g["home"], g["away"], **kw)
    res["removed"] = removed
    return res


# ------------------------------------------------------------------------------ Hauptablauf
HELP = "Enter = überspringen/behalten · x = entfernen · z = zurück · q = beenden · Spread-Linie des Gastteams: 'g +4,5'"
SAVE_PROMPT = "Speichern? (Enter = ja, n = verwerfen, z = ändern, s = zu einem Bereich springen): "


def section_hint(msg: str, g: dict, plan: dict) -> str:
    """Zu einer Fehlermeldung des Stores: 'tippe s und wähle N für <Bereich>' (leer, wenn der Bereich nicht erkennbar ist)."""
    menu = section_menu(g)
    num = lambda key: SECTIONS.index(key) + 1
    label = lambda key: dict(menu)[key]
    H, A = nick(g["home"]), nick(g["away"])
    keys = None
    if msg.startswith("Sieger"):
        keys = ["winner"]
    elif msg.startswith("Spread"):
        keys = ["spread"]
    elif msg.startswith("Total"):
        keys = ["total"]
    elif msg.startswith("Team Totals"):
        keys = ["team_home"] if f"· {H}" in msg else ["team_away"] if f"· {A}" in msg else ["team_home", "team_away"]
    elif msg.startswith("Spielerpunkte"):
        sides = {("players_home" if b["team"] == g["home"] else "players_away") for b in plan["players"] if b["name"] in msg}
        keys = sorted(sides, key=SECTIONS.index) or ["players_home", "players_away"]
    if not keys:
        return ""
    return "  → Tippe s und wähle " + " oder ".join(str(num(k)) for k in keys) + " für " + " / ".join(label(k) for k in keys) + "."


def jump_menu(con: Console, g: dict) -> str | None:
    """Zeigt das Menue und liefert den gewaehlten Bereichsschluessel (None = abgebrochen)."""
    menu = section_menu(g)
    con.write("Zu welchem Bereich springen?")
    for i, (_k, name) in enumerate(menu, 1):
        con.write(f"  {i}) {name}")
    while True:
        t = con.ask_raw(f"Nummer wählen (1–{len(menu)}, Enter = abbrechen): ").strip().lower()
        if t == "q":
            raise Quit()
        if t == "":
            return None
        if re.fullmatch(r"\d+", t) and 1 <= int(t) <= len(menu):
            return menu[int(t) - 1][0]
        con.write(f"  Bitte eine Nummer von 1 bis {len(menu)} eingeben.")


def run_game(con: Console, g: dict, now_fn=time.time) -> str:
    """Ein Spiel abfragen, bestaetigen, speichern. Rueckgabe: 'saved' | 'discarded' | 'unchanged'. 'q' wirft Quit.
    Am 'Speichern?'-Prompt springt 's' in einen einzelnen Bereich; danach geht es direkt zurueck zur Zusammenfassung."""
    key = store.game_key(g["date"], g["start"], g["home"], g["away"])
    entry = copy.deepcopy((store.load().get("entries") or {}).get(key))
    roster = rosters.load()
    ref = cache_reference(g)
    s = Session(con)
    con.write("")
    con.write(f"=== {g['home']} – {g['away']} · {start_label(g['start'])} Uhr ===")
    con.write(HELP)
    while True:
        try:
            s.reset()
            plan = build_plan(s, g, entry, roster, ref)
        except Back:
            r = s.undo()
            if r == "first":
                con.write("  Das ist schon die erste Frage.")
            elif r == "jump_cancel":
                con.write("  Sprung abgebrochen, die bisherigen Antworten dieses Bereichs bleiben.")
            continue
        s.end_jump()
        con.write("")
        for line in summary_lines(g, plan, entry):
            con.write(line)
        while True:
            t = con.ask_raw(SAVE_PROMPT).strip().lower()
            if t == "q":
                raise Quit()
            if t == "n":
                con.write("Verworfen.")
                return "discarded"
            if t == "z":
                s.undo_last()
                break
            if t == "s":
                sec = jump_menu(con, g)
                if sec is None:
                    continue
                s.jump_to(sec)
                con.write(f"— Sprung: {dict(section_menu(g))[sec]} (z am Anfang = abbrechen) —")
                break
            if t != "":
                continue
            try:
                res = execute_plan(g, plan, entry, roster, ref, now=now_fn())
            except store.CardInputError as e:
                for m in e.errors:
                    con.write(f"  {m}{section_hint(m, g, plan)}")
                continue
            except (store.OddsInputError, store.GameStartedError, store.StoreError) as e:
                con.write(f"  {e}{section_hint(str(e), g, plan)}")
                continue
            if res["status"] == "unchanged" and not res.get("removed"):
                con.write("Nichts geändert.")
                return "unchanged"
            con.write("Gespeichert." if res["status"] != "unchanged" else "Entfernt.")
            return "saved"


def choose(con: Console, games: list[dict]) -> list[dict] | None:
    """Spieleauswahl: Nummer, 'a' = alle der Reihe nach, 'q' = Ende. Rueckgabe None bei 'q'."""
    con.write("")
    con.write("Spiele (noch nicht begonnen, Uhrzeit Berlin):")
    for i, g in enumerate(games, 1):
        con.write(f"  {i}) {start_label(g['start'])}  {nick(g['home'])} – {nick(g['away'])}")
    while True:
        t = con.ask_raw("Nummer wählen (a = alle, q = beenden): ").strip().lower()
        if t == "q":
            return None
        if t == "a":
            return list(games)
        if re.fullmatch(r"\d+", t) and 1 <= int(t) <= len(games):
            return [games[int(t) - 1]]
        con.write(f"  Bitte eine Nummer von 1 bis {len(games)}, a oder q eingeben.")


def main(con: Console | None = None, now_fn=time.time, games: list | None = None) -> int:
    con = con or Console()
    try:
        con.write("NBAEdge · Pre-Match-Eingabe (Betano: Heim zuerst, dann Gast)")
        while True:
            lst = list_games(now_fn(), games)
            if not lst:
                con.write("Keine Spiele zur Eingabe (alle begonnen/beendet oder keine Spieleliste im Zwischenspeicher).")
                return 0
            sel = choose(con, lst)
            if sel is None:
                break
            for g in sel:
                if not store.is_editable(g["start"], now_fn()):
                    con.write(f"{nick(g['home'])} – {nick(g['away'])} hat begonnen, übersprungen.")
                    continue
                run_game(con, g, now_fn)
            if len(sel) > 1:
                break
    except Quit:
        pass
    con.write("Beendet. Bestätigte Spiele sind gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
