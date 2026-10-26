"""
Betano-Quoten automatisch in die Pre-Match-Eingabe uebernehmen (ersetzt das Eintippen in eingabe.py).

Start (holt die Quoten direkt bei Betano: 1 Abruf der Spielliste + 1 Abruf je Spiel, 3 s Pause dazwischen; nur mit Erlaubnis von Betano):
    venv/bin/python betano_import.py              # alle Spiele der Liste von eingabe.py der Reihe nach
    venv/bin/python betano_import.py 2            # nur Spiel Nr. 2 der Liste
Zum Testen/Nachspielen OHNE Abruf, aus einem im Browser gespeicherten Mitschnitt:
    venv/bin/python betano_import.py --datei www.betano.de.json [Spielnummer]

Das Skript liest die Quoten, beantwortet damit genau die Fragen von eingabe.py (gleiche Regeln, Grenzen, Pruefungen, Revisionen, Sperre ab Anpfiff)
und zeigt die Zusammenfassung. Gespeichert wird NUR, wenn du bei "Speichern?" selbst Enter drueckst (n = verwerfen, s = Bereich nachbessern, z = zurueck).

Was uebernommen wird (Haupt-/Zusatzlinien nach Betano):
- Sieger: beide Quoten.
- Spread: Hauptlinie und 2 niedrigere + 2 hoehere Linien (Schritt 1,0).
- Total: Hauptlinie und 3 niedrigere + 3 hoehere Linien (Schritt 1,0) -- die Leiter von eingabe.py.
- Team Totals je Team: Hauptlinie und weitere Linien von Betano (hoechstens 3 hoehere und 3 niedrigere).
- Spieler (Punkte): alle Spieler aus Betano, die in der Kaderdatei des Teams stehen; alle Meilensteine (hoechstens 10 je Spieler, die niedrigsten).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import eingabe as ei
from data import pre_match_store as store
from data import rosters

MAX_SPREAD_STEPS = 2          # Linien unter/ueber der Hauptlinie
BASE_URL = "https://www.betano.de"
LIST_PATH = "/api/sport/basketball/usa/nba/441g/?req=la,s,stnf,c,mb"
EVENT_REQ = "?req=la,s,stnf,c,mb&bt=6"          # bt=6 = Tab "Alle" (mit den Team-Total-Leitern)
PAUSE_SECONDS = 3.0


class ImportAbort(Exception):
    pass


# Betano-Name -> Name wie in der Spieleliste (nur Abweichungen)
NAME_ALIASES = {"Los Angeles Clippers": "LA Clippers"}


def canon(name: str) -> str:
    return NAME_ALIASES.get(name, name)


def name_variants(name: str) -> set:
    """Alle Schreibweisen eines Teams (Spieleliste und Betano)."""
    return {name} | {k for k, v in NAME_ALIASES.items() if v == name}


# ------------------------------------------------------------------------------ Lesen (Mitschnitt oder Einzel-JSON)
def load_payloads(path: str | Path) -> list[dict]:
    """Alle 'data'-Bloecke mit Spiel-Quoten (data.event) bzw. Spieleliste (data.blocks) aus einem HAR-Mitschnitt oder einer JSON-Datei."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    texts = []
    if isinstance(raw, dict) and "log" in raw:
        for e in raw["log"].get("entries", []):
            c = (e.get("response") or {}).get("content") or {}
            if "json" in str(c.get("mimeType", "")) and c.get("text"):
                texts.append(c["text"])
    else:
        texts.append(json.dumps(raw))
    out = []
    for t in texts:
        try:
            d = json.loads(t).get("data")
        except (ValueError, AttributeError):
            continue
        if isinstance(d, dict) and ("event" in d or "blocks" in d):
            out.append(d)
    return out


def list_events(payloads: list[dict]) -> list[dict]:
    """Spiele aus Spieleliste und Einzelantworten: [{'id', 'name', 'url', 'start_ms', 'teams': (a, b)}]."""
    seen, out = set(), []
    evs = []
    for d in payloads:
        for b in d.get("blocks") or []:
            evs.extend(b.get("events") or [])
        if "event" in d:
            evs.append(d["event"])
    for e in evs:
        if e.get("id") in seen:
            continue
        seen.add(e.get("id"))
        out.append({"id": e.get("id"), "name": e.get("name"), "url": e.get("url"), "start_ms": e.get("startTime"),
                    "teams": tuple(canon(p["name"]) for p in e.get("participants", [])[:2])})
    return out


def parse_initial_state(html: str) -> dict | None:
    """Die in eine Spielseite (HTML) eingebettete Datenstruktur: window["initial_state"]={"data":{...}} -> data-Block (oder None)."""
    key = 'window["initial_state"]='
    i = html.find(key)
    if i < 0:
        return None
    try:
        st, _ = json.JSONDecoder().raw_decode(html[i + len(key):])
        return st.get("data")
    except ValueError:
        return None


def detail_for(payloads: list[dict], event_id: str) -> dict | None:
    return next((d for d in payloads if "event" in d and str(d["event"].get("id")) == str(event_id)), None)


# ------------------------------------------------------------------------------ Parsen eines Spiels
def _num(x):
    return float(x) if x is not None else None


def _table_rows(market: dict) -> list[dict]:
    return (market.get("tableLayout") or {}).get("rows") or []


def _sels(row: dict) -> list[dict]:
    return [s for g in row.get("groupSelections", []) for s in g.get("selections", [])]


def _ou_pair(sels: list[dict]):
    over = next((s for s in sels if s["name"].startswith("Über")), None)
    under = next((s for s in sels if s["name"].startswith("Unter")), None)
    if over and under:
        return float(over["handicap"]), float(over["price"]), float(under["price"])
    return None


def parse_event(data: dict, home: str, away: str) -> dict:
    """Quoten eines Spiels aus der Detailantwort. home/away = Vollnamen wie in der Spieleliste (bestimmt die Seiten)."""
    ev = data["event"]
    mk = ev.get("markets") or []
    res = {"winner": None, "spread": {"main": None, "lines": {}}, "total": {"main": None, "lines": {}},
           "team": {"home": {"main": None, "lines": {}}, "away": {"main": None, "lines": {}}}, "players": {}}

    def team_of(selection_name: str):
        n = selection_name.strip()
        if any(n.startswith(v) for v in name_variants(home)):
            return "home"
        return "away" if any(n.startswith(v) for v in name_variants(away)) else None

    # Hauptlinien und Sieger aus dem Kopfblock (sixPack)
    for col in (ev.get("sixPackLayout") or {}).get("columns", []):
        sels = col.get("selections", [])
        if col.get("type") == "H2H1" and len(sels) == 2:
            by = {team_of(s["name"]): float(s["price"]) for s in sels}
            if "home" in by and "away" in by:
                res["winner"] = (by["home"], by["away"])
        elif col.get("type") == "FHOT" and len(sels) == 2:
            h = next((s for s in sels if team_of(s["name"]) == "home"), None)
            if h:
                res["spread"]["main"] = float(h["handicap"])
        elif col.get("type") == "FTPO" and sels:
            res["total"]["main"] = float(sels[0]["handicap"])
    for m in mk:
        t = m.get("type")
        if t == "H2HT" and res["winner"] is None:
            by = {team_of(s["name"]): float(s["price"]) for s in m.get("selections", [])}
            if "home" in by and "away" in by:
                res["winner"] = (by["home"], by["away"])
        elif t == "FHOT":
            for row in _table_rows(m):
                sels = _sels(row)
                h = next((s for s in sels if team_of(s["name"]) == "home"), None)
                a = next((s for s in sels if team_of(s["name"]) == "away"), None)
                if h and a:
                    res["spread"]["lines"][float(h["handicap"])] = (float(h["price"]), float(a["price"]))
        elif t == "FTPO":
            for row in _table_rows(m):
                p = _ou_pair(_sels(row))
                if p:
                    res["total"]["lines"][p[0]] = (p[1], p[2])
        elif t in ("OUHO", "OUAO"):
            side = "home" if t == "OUHO" else "away"
            if m.get("selections") and len(m["selections"]) == 2:           # die einzeilige Wette = Hauptlinie
                p = _ou_pair(m["selections"])
                if p:
                    res["team"][side]["lines"][p[0]] = (p[1], p[2])
                    res["team"][side]["main"] = p[0]
            else:                                                           # die Leiter (viele Linien)
                sels = m.get("selections") or [s for r in _table_rows(m) for s in _sels(r)]
                by = {}
                for s_ in sels:
                    by.setdefault(float(s_["handicap"]), []).append(s_)
                for hc, ss in by.items():
                    p = _ou_pair(ss)
                    if p:
                        res["team"][side]["lines"].setdefault(p[0], (p[1], p[2]))
        elif t == "PLNP":
            for row in _table_rows(m):
                th = {}
                for s in _sels(row):
                    mm = re.fullmatch(r"(\d+)\+", s["name"].strip())
                    if mm:
                        th[int(mm.group(1))] = float(s["price"])
                if th and row.get("title"):
                    res["players"].setdefault(row["title"], {}).update(th)
    if res["total"]["main"] is None and res["total"]["lines"]:             # ohne Kopfblock: Linie mit den ausgeglichensten Quoten
        tl = res["total"]["lines"]
        res["total"]["main"] = min(tl, key=lambda x: (abs(tl[x][0] - tl[x][1]), x))
    if res["spread"]["main"] is None and res["spread"]["lines"]:
        sl = res["spread"]["lines"]
        res["spread"]["main"] = min(sl, key=lambda x: (abs(sl[x][0] - sl[x][1]), x))
    for side in ("home", "away"):                      # ohne einzeilige Hauptwette: die Linie mit den ausgeglichensten Quoten
        ls = res["team"][side]["lines"]
        if ls and res["team"][side]["main"] is None:
            res["team"][side]["main"] = min(ls, key=lambda x: (abs(ls[x][0] - ls[x][1]), x))
    return res


def team_split(players: dict, roster_players: dict, g: dict) -> tuple[dict, list[str]]:
    """Ordnet die Betano-Spieler den Kaderlisten zu: {'home': [(Vollname, {schwelle: quote})], 'away': [...]}, dazu die nicht zuzuordnenden Namen."""
    both = [{**p, "side": side} for side in ("home", "away") for p in roster_players.get(g[side], [])]
    out, miss = {"home": [], "away": []}, []
    for name, th in players.items():
        hit = rosters.match_player(name, both)           # tolerant (ohne Akzente/Punkte, ohne Jr./II/III), nur eindeutige Treffer; Mehrdeutiges wird nicht geraten
        if hit:
            out[hit["side"]].append((hit["name"], th))
        else:
            miss.append(name)
    return out, miss


# ------------------------------------------------------------------------------ Antworten auf die Fragen von eingabe.py
class AutoAnswers:
    """read(prompt) fuer ei.Console: beantwortet jede Frage von eingabe.build_plan aus den Betano-Daten; bei 'Speichern?' uebernimmt die Tastatur."""

    def __init__(self, g: dict, data: dict, roster: dict, real=input, write=print):
        self.g, self.d, self.real, self.write = g, data, real, write
        self.H, self.A = ei.nick(g["home"]), ei.nick(g["away"])
        self.handover = False
        self.used_spread: set = set()
        self.used_team = {"home": set(), "away": set()}
        self.split, self.unmatched = team_split(data["players"], roster.get("teams", {}) if roster.get("status") == "ok" else {}, g)
        self.last, self.repeat = None, 0
        self.notes: list[str] = []
        sp = data["spread"]
        self.spread_want = [] if sp["main"] is None else sorted(
            l for l in (sp["main"] + k for k in range(-MAX_SPREAD_STEPS, MAX_SPREAD_STEPS + 1) if k) if l in sp["lines"])
        self.team_want = {side: self._team_extras(side) for side in ("home", "away")}
        self.player_pick = {side: [] for side in ("home", "away")}
        self.cur_player: dict = {}
        self.N = f"({re.escape(self.H)}|{re.escape(self.A)})"

    def _team_extras(self, side: str) -> list[float]:
        t = self.d["team"][side]
        if t["main"] is None:
            return []
        lo = sorted((l for l in t["lines"] if l < t["main"]), reverse=True)[:store.MAX_TOTAL_PER_DIRECTION]
        hi = sorted(l for l in t["lines"] if l > t["main"])[:store.MAX_TOTAL_PER_DIRECTION]
        return sorted(lo + hi)

    # ---- Hilfen
    @staticmethod
    def _base(prompt: str) -> tuple[str, str | None]:
        m = re.search(r"\s*\[([^\]]*)\]\s*:?\s*$", prompt)
        base = prompt[:m.start()] if m else prompt.rstrip().rstrip(":")
        dflt = m.group(1) if m else None
        return base.strip(), (None if dflt is not None and dflt.startswith("Enter") else dflt)      # "[Enter = fertig]" ist ein Hinweis, keine Vorgabe

    @staticmethod
    def _f(text: str) -> float:
        return float(text.replace(",", ".").replace("−", "-"))

    def _odds(self, v) -> str:
        return ei.odds_text(v)

    def _side_of_team(self, nick: str) -> str:
        return "home" if nick == self.H else "away"

    # ---- Hauptfunktion
    def __call__(self, prompt: str) -> str:
        if self.handover:
            return self.real(prompt)
        if prompt.startswith("Speichern?"):
            self.handover = True
            self.write("")
            self.write("── Betano-Daten eingespielt. Ab hier entscheidest DU: Enter = speichern, n = verwerfen, s = Bereich nachbessern, z = zurück, q = beenden. ──")
            return self.real(prompt)
        base, dflt = self._base(prompt)
        if (base, dflt) == self.last:
            self.repeat += 1
            if self.repeat > 3 or not base.startswith("Anzahl"):
                raise ImportAbort(f"Die Eingabe wurde abgelehnt, ich komme bei dieser Frage nicht weiter: {prompt.strip()!r}")
        else:
            self.last, self.repeat = (base, dflt), 0
        return self._answer(base, dflt)

    def _answer(self, base: str, dflt: str | None) -> str:
        d, H, A = self.d, self.H, self.A
        # Sieger
        if base == f"Quote {H}":
            return self._odds(d["winner"][0]) if d["winner"] else ""
        if base == f"Quote {A}":
            return self._odds(d["winner"][1]) if d["winner"] else ""
        # Spread
        if base == f"Spread-Linie {H}":
            return ei.sgn(d["spread"]["main"]) if d["spread"]["main"] is not None else ""
        m = re.fullmatch(rf"Quote ({re.escape(H)}|{re.escape(A)}) ([+-]?[\d.]+)", base)
        if m and d["spread"]["lines"]:
            ln = self._f(m.group(2)) * (1 if m.group(1) == H else -1)
            pair = d["spread"]["lines"].get(ln)
            if pair:
                return self._odds(pair[0] if m.group(1) == H else pair[1])
            raise ImportAbort(f"Spread-Linie {ei.sgn(ln)} fehlt in den Betano-Daten.")
        if base.startswith(f"Weitere Spread-Linie {H}"):
            main = d["spread"]["main"]
            if dflt is not None:
                cur = self._f(dflt)
                if cur in self.spread_want and cur not in self.used_spread and cur != main:
                    self.used_spread.add(cur)
                    return ei.sgn(cur)
                return "x"
            nxt = next((l for l in self.spread_want if l not in self.used_spread and l != main), None)
            if nxt is None:
                return ""
            self.used_spread.add(nxt)
            return ei.sgn(nxt)
        # Total
        if base == "Total-Linie":
            return ei.fnum(d["total"]["main"]) if d["total"]["main"] is not None else ""
        m = re.fullmatch(r"Quote (Over|Under) ([\d.]+)", base)
        if m:
            ln = self._f(m.group(2))
            pair = d["total"]["lines"].get(ln)
            if pair:
                return self._odds(pair[0] if m.group(1) == "Over" else pair[1])
            if m.group(1) == "Over":
                return "x" if dflt is not None else ""
            raise ImportAbort(f"Total-Linie {ei.fnum(ln)} (Under) fehlt in den Betano-Daten.")
        if base.startswith("Gespeicherte Total-Linien"):
            return ""
        # Team Totals
        m = re.fullmatch(rf"Team-Total-Linie {self.N}", base)
        if m:
            t = d["team"][self._side_of_team(m.group(1))]
            return ei.fnum(t["main"]) if t["main"] is not None else ""
        m = re.fullmatch(rf"Quote (Over|Under) {self.N} ([\d.]+)", base)
        if m:
            side = self._side_of_team(m.group(2))
            pair = d["team"][side]["lines"].get(self._f(m.group(3)))
            if not pair:
                raise ImportAbort(f"Team-Total-Linie {m.group(3)} ({m.group(2)}) fehlt in den Betano-Daten.")
            return self._odds(pair[0] if m.group(1) == "Over" else pair[1])
        m = re.fullmatch(rf"Weitere Team-Total-Linie {self.N} vorhanden\?.*", base)
        if m:
            side = self._side_of_team(m.group(1))
            return "j" if any(l not in self.used_team[side] for l in self.team_want[side]) else ""
        m = re.fullmatch(rf"Weitere Team-Total-Linie {self.N}", base)
        if m:
            side = self._side_of_team(m.group(1))
            if dflt is not None:
                cur = self._f(dflt)
                if cur in self.team_want[side] and cur not in self.used_team[side]:
                    self.used_team[side].add(cur)
                    return ei.fnum(cur)
                return "x"
            nxt = next((l for l in self.team_want[side] if l not in self.used_team[side]), None)
            if nxt is None:
                raise ImportAbort("Keine weitere Team-Total-Linie mehr vorhanden.")
            self.used_team[side].add(nxt)
            return ei.fnum(nxt)
        # Spieler
        m = re.fullmatch(rf"Anzahl {self.N}-Spieler", base)
        if m:
            side = self._side_of_team(m.group(1))
            self.player_pick[side] = list(self.split[side])
            n = max(0, len(self.player_pick[side]) - self.repeat)           # Wiederholung = Zahl war zu hoch (freie Plaetze): eins weniger
            self.player_pick[side] = self.player_pick[side][:n]
            return str(n)
        m = re.fullmatch(rf"{self.N}-Spieler (\d+) von \d+: Name", base)
        if m:
            side = self._side_of_team(m.group(1))
            name, th = self.player_pick[side][int(m.group(2)) - 1]
            self.cur_player = {"name": name, "th": th}
            return name
        if base == "Nummer":
            return "1"
        m = re.fullmatch(r"Start-Linie (.+)", base)
        if m and self.cur_player.get("name") == m.group(1):
            return str(min(self.cur_player["th"]))
        m = re.fullmatch(r"End-Linie (.+)", base)
        if m and self.cur_player.get("name") == m.group(1):
            th = sorted(self.cur_player["th"])
            lo = th[0]
            return str(min(th[-1], lo + store.MAX_MILESTONES - 1))
        m = re.fullmatch(r"Quote (.+) (\d+)\+", base)
        if m and self.cur_player.get("name") == m.group(1):
            q = self.cur_player["th"].get(int(m.group(2)))
            return self._odds(q) if q else ("x" if dflt is not None else "")
        raise ImportAbort(f"Unbekannte Frage, nichts gespeichert: {base!r}")


# ------------------------------------------------------------------------------ Ablauf
def match_event(g: dict, events: list[dict]) -> dict | None:
    for e in events:
        if set(e["teams"]) == {g["home"], g["away"]}:
            ts = store.parse_utc(g["start"]) if g.get("start") else None
            if ts is None or not e["start_ms"] or abs(e["start_ms"] / 1000 - ts) < 18 * 3600:
                return e
    return None


def run_one(con_write, g: dict, data: dict, real=input, now_fn=time.time) -> str | None:
    roster = rosters.load()
    parsed = parse_event(data, g["home"], g["away"])
    auto = AutoAnswers(g, parsed, roster, real=real, write=con_write)
    skip = ("—", "=== ", "Enter = überspringen")

    def write(line=""):
        if str(line).startswith(skip) or str(line).startswith("  Gespeichert:"):
            return
        con_write(line)
    con = ei.Console(read=auto, write=write)
    con_write("")
    con_write(f"Betano: {g['home']} – {g['away']} ({ei.start_label(g['start'])} Uhr): "
              f"{len(parsed['spread']['lines'])} Spread-, {len(parsed['total']['lines'])} Total-Linien, Team Totals "
              f"{len(parsed['team']['home']['lines'])}/{len(parsed['team']['away']['lines'])}, {len(parsed['players'])} Spieler in den Daten.")
    try:
        res = ei.run_game(con, g, now_fn)
    except ImportAbort as e:
        con_write(f"\nABBRUCH: {e}")
        return None
    if auto.unmatched:
        con_write("Hinweis: nicht im Kader gefunden, übersprungen: " + ", ".join(auto.unmatched))
    if parsed["players"]:                                  # nur Laeufe mit Spieler-Linien: uebersprungene Namen pro Spiel merken (Anzeige im Tab Spieler)
        try:
            from data import betano_skipped
            betano_skipped.record(store.game_key(g["date"], g["start"], g["home"], g["away"]), g["home"], g["away"], auto.unmatched, now_fn())
        except Exception:
            pass
    return res


def fetch_json(path: str) -> dict:
    """Ein Abruf bei Betano (ohne --datei)."""
    import urllib.request
    req = urllib.request.Request(BASE_URL + path, headers={"Accept": "application/json", "User-Agent": "NBAEdge/1.0 (persoenliche Nutzung)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv=None, real=input, write=print, now_fn=time.time, after=None, before=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    src = None
    if "--datei" in args:
        i = args.index("--datei")
        if i + 1 >= len(args):
            write("--datei braucht einen Dateinamen.")
            return 2
        src = args[i + 1]
        del args[i:i + 2]
    live = src is None
    if any(a.startswith("-") for a in args):
        write(__doc__)
        return 2
    sel = args[0] if args else "a"
    games = ei.list_games(now_fn())
    if not games:
        write("Keine Spiele zur Eingabe (alle begonnen/beendet oder keine Spieleliste im Zwischenspeicher).")
        return 0
    if sel != "a":
        if not (sel.isdigit() and 1 <= int(sel) <= len(games)):
            write(f"Spielnummer 1 bis {len(games)} oder nichts angeben.")
            return 2
        games = [games[int(sel) - 1]]
    if live and before is not None:                         # z. B. Kader auffrischen, wenn aelter als 2 Tage (ein Abruf bei stats.nba.com, nie bei Betano); Fehler stoeren den Lauf nicht
        try:
            before(write)
        except Exception:
            write("Kader konnte nicht aktualisiert werden")
    payloads = [] if live else load_payloads(src)
    if live:
        payloads = [fetch_json(LIST_PATH)["data"]]
    events = list_events(payloads)
    if not events:
        write("In der Quelle wurden keine Spiele gefunden.")
        return 2
    try:
        for i, g in enumerate(games):
            ev = match_event(g, events)
            if ev is None:
                write(f"{ei.nick(g['home'])} – {ei.nick(g['away'])}: nicht in den Betano-Daten, übersprungen.")
                continue
            data = detail_for(payloads, ev["id"])
            if data is None and live:
                time.sleep(PAUSE_SECONDS)
                data = fetch_json(f"{ev['url']}{EVENT_REQ}".replace("/quoten/", "/api/quoten/", 1))["data"]
            if data is None:
                write(f"{ei.nick(g['home'])} – {ei.nick(g['away'])}: in der Quelle nur der Spielplan, keine Quoten (Spielseite einzeln speichern). Übersprungen.")
                continue
            run_one(write, g, data, real=real, now_fn=now_fn)
    except ei.Quit:
        pass
    write("Beendet. Bestätigte Spiele sind gespeichert.")
    if after is not None:                                    # z. B. ESPN-Verletzungen; ein Fehler dort stoert den Lauf nicht
        try:
            after(write)
        except Exception:
            write("ESPN-Verletzungen: nicht erreichbar")
    return 0


def espn_after(write=print) -> None:
    """Am Ende des Laufs: ESPN-Injury-Report in die Ausfall-Felder (data/espn_injuries.py); Fehler zeigen nur eine Zeile."""
    from data import espn_injuries
    res = espn_injuries.run(time.time())
    write(res["line"])
    for u in res["unmatched"]:
        write(f"  nicht zugeordnet: {u}")


def roster_before(write=print) -> None:
    """Am Anfang eines Live-Laufs: Kader auffrischen, falls aelter als rosters.MAX_AGE_DAYS (data/rosters.ensure_fresh)."""
    msg = rosters.ensure_fresh()
    if msg:
        write(msg)


if __name__ == "__main__":
    sys.exit(main(after=espn_after, before=roster_before))
