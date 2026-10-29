"""
Boxscore-Archiv mit Inaktiven: laedt die Boxscores aller regulaeren Spiele der Saisons 2023-24, 2024-25 und 2025-26 von cdn.nba.com nach und baut daraus eine Tabelle mit Status je Kaderspieler.
NEU, nach dem Vorbild von analysis/fetch_pbp_archive.py (gleiche Spielliste aus den lokalen Spielerdaten, gleiche Wartezeit, Wiederaufnahme, Stopp bei 403/429); aendert keine bestehende Datei.

Abruf: wie data/nba_live.py (NBA_BOXSCORE_URL, requests, NBA_HEADERS), ohne dessen Cache; ein Abruf alle 2 Sekunden (hoechstens 0,5 pro Sekunde), nie parallel. Nur Lesezugriffe.
Ablage Rohdaten: <Ordner>/boxscore/<Saison>/<spiel_id>.json.gz (unveraenderte Antwort, gepackt); vorhandene Dateien werden uebersprungen. Protokoll: <Ordner>/boxscore/protokoll.txt, fehlschlaege.txt, bericht.txt.
Tabelle: <Ordner>/derived/inactives_<Saison>.csv.gz mit spiel_id, datum, team, spieler_id, name, status, minuten, punkte. status = notPlayingReason (z. B. INACTIVE_INJURY, INACTIVE_GLEAGUE_TWOWAY) wenn gesetzt,
sonst 'aktiv' bei status ACTIVE, sonst der Wert des Feldes status unveraendert. Kaderspieler ohne Einsatz sind enthalten (minuten 0). Bericht: analysis/results/boxscore_archive.txt.

Start (Standard-Ordner /Users/baranalturk/NBAEdge_pbp):
    venv/bin/python analysis/fetch_boxscore_archive.py
Test mit wenigen Abrufen:  venv/bin/python analysis/fetch_boxscore_archive.py --out /tmp/box_test --seasons 2025-26 --limit 3 --results /tmp/box_test/bericht_test.txt
Nur Tabelle und Bericht aus vorhandenen Rohdateien (ohne Netz):  ... --no-fetch

Fehler: 403/429 = sofort Stopp (Exit-Code 3, kein Wiederholen). Timeout/5xx/Netz: hoechstens 2 Wiederholungen mit 10 s Pause, dann Eintrag in fehlschlaege.txt und weiter. Andere Antworten (z. B. 404) oder eine ungueltige Datei: kein Wiederholen.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from analysis.fetch_pbp_archive import Blocked, PAUSE_SECONDS, RETRY_PAUSE_SECONDS, MAX_RETRIES, TIMEOUT_SECONDS, PROGRESS_EVERY, SEASONS, game_ids, save_gz, DEFAULT_OUT  # noqa: E402

RESULTS = ROOT / "analysis" / "results" / "boxscore_archive.txt"
COLS = ["spiel_id", "datum", "team", "spieler_id", "name", "status", "minuten", "punkte"]
OUT_MIN = 20.0


# ----------------------------------------------------------------------------- Antwort pruefen und auswerten
def game_of(data) -> dict | None:
    """Das Spiel-Objekt: Antwort {'meta','game'} oder schon das Spiel selbst (wie die Dateien des Recorders)."""
    if not isinstance(data, dict):
        return None
    g = data.get("game") if isinstance(data.get("game"), dict) else data
    return g if isinstance(g, dict) else None


def parse_response(body: bytes, game_id: str) -> int:
    """Gueltiges JSON, Spiel-ID stimmt, beide Teams mit Spielerliste. Gibt die Zahl der Spieler zurueck, sonst ValueError."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("kein gueltiges JSON")
    g = game_of(data)
    if g is None or "homeTeam" not in g:
        raise ValueError("Feld 'game' fehlt")
    if str(g.get("gameId")) != game_id:
        raise ValueError(f"Spiel-ID stimmt nicht ({g.get('gameId')})")
    n = 0
    for side in ("homeTeam", "awayTeam"):
        t = g.get(side)
        pl = t.get("players") if isinstance(t, dict) else None
        if not isinstance(pl, list) or not pl:
            raise ValueError(f"keine Spielerliste ({side})")
        n += len(pl)
    return n


def minutes_of(text) -> float:
    """'PT28M40.00S' -> 28.667; fehlend/leer -> 0."""
    m = re.match(r"^PT(?:(\d+)M)?(?:([\d.]+)S)?$", str(text or ""))
    if not m:
        return 0.0
    return int(m.group(1) or 0) + float(m.group(2) or 0) / 60.0


def status_of(p: dict) -> str:
    reason = p.get("notPlayingReason")
    if reason:
        return str(reason)
    st = p.get("status")
    return "aktiv" if st == "ACTIVE" else str(st)


def date_of(g: dict) -> str:
    for k in ("gameEt", "gameTimeLocal", "gameTimeUTC"):
        v = str(g.get(k) or "")
        if re.match(r"\d{4}-\d{2}-\d{2}", v):
            return v[:10]
    return ""


def table_rows(body: bytes, game_id: str) -> list[list]:
    g = game_of(json.loads(body.decode("utf-8")))
    day, out = date_of(g), []
    for side in ("homeTeam", "awayTeam"):
        t = g[side]
        for p in t["players"]:
            st = p.get("statistics") or {}
            out.append([game_id, day, t.get("teamTricode"), int(p.get("personId")), p.get("name"), status_of(p), round(minutes_of(st.get("minutes")), 4), int(st.get("points") or 0)])
    return out


# ----------------------------------------------------------------------------- Abruf
def target_path(out: Path, season: str, game_id: str) -> Path:
    return out / "boxscore" / season / f"{game_id}.json.gz"


def http_fetch(game_id: str) -> tuple[int | None, bytes]:
    import requests
    from data.nba_live import NBA_HEADERS, NBA_BOXSCORE_URL
    try:
        r = requests.get(NBA_BOXSCORE_URL.format(game_id=game_id), headers=NBA_HEADERS, timeout=TIMEOUT_SECONDS)
        return r.status_code, r.content
    except requests.exceptions.RequestException:
        return None, b""


class Archive:
    def __init__(self, out: Path, fetch=http_fetch, sleep=time.sleep, now=time.time, write=print):
        self.out, self.fetch, self.sleep, self.now, self.write = Path(out), fetch, sleep, now, write
        self.logdir = self.out / "boxscore"
        self.last_call = None
        self.calls = 0

    def log(self, game_id: str, status: str) -> None:
        self.logdir.mkdir(parents=True, exist_ok=True)
        with open(self.logdir / "protokoll.txt", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.now()))}\t{game_id}\t{status}\n")

    def _wait(self, seconds: float) -> None:
        if self.last_call is not None:
            rest = seconds - (self.now() - self.last_call)
            if rest > 0:
                self.sleep(rest)

    def get(self, game_id: str) -> tuple[bytes | None, str]:
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
            if status is not None and 400 <= status < 500:
                return None, f"HTTP {status}"
            self.log(game_id, f"Versuch {attempt + 1}: {'Netz/Timeout' if status is None else f'HTTP {status}'}")
        return None, "Netz/Timeout" if status is None else f"HTTP {status}"

    def run(self, seasons=SEASONS, cdir: Path | None = None, limit: int | None = None) -> dict:
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
                            self.log(gid, f"gespeichert, {n} Spieler")
                        except ValueError as e:
                            body, status = None, f"ungueltig: {e}"
                    if body is None:
                        rep["failed"].append((gid, status))
                        self.log(gid, f"FEHLSCHLAG {status}")
                        with open(self.logdir / "fehlschlaege.txt", "a", encoding="utf-8") as f:
                            f.write(f"{season}\t{gid}\t{status}\n")
                if done % PROGRESS_EVERY == 0:
                    self.write(f"[{time.strftime('%H:%M:%S', time.localtime(self.now()))}] {season}: {done} Spiele bearbeitet, {self.calls} Abrufe")
            d = self.out / "boxscore" / season
            rep["bytes"] = sum(p.stat().st_size for p in d.glob("*.json.gz")) if d.exists() else 0
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


# ----------------------------------------------------------------------------- Tabelle und Bericht
def build_table(out: Path, season: str, cdir: Path | None = None) -> dict:
    """Liest vorhandene Rohdateien, schreibt derived/inactives_<Saison>.csv.gz. Rueckgabe {'rows', 'expected', 'present', 'missing', 'unreadable'}."""
    ids = game_ids(season, cdir)
    rows, present, bad = [], 0, 0
    for gid in ids:
        p = target_path(out, season, gid)
        if not (p.exists() and p.stat().st_size > 0):
            continue
        try:
            body = gzip.decompress(p.read_bytes())
            rows += table_rows(body, gid)
            present += 1
        except Exception:
            bad += 1
    dest = out / "derived" / f"inactives_{season}.csv.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    return {"rows": rows, "expected": len(ids), "present": present, "missing": len(ids) - present, "unreadable": bad}


def recent_means(rows: list[list]) -> dict:
    """{(spieler_id, spiel_id): (Anzahl, Mittel Minuten)} der letzten 10 Einsaetze (Minuten > 0) VOR dem Spiel, aus der Tabelle selbst (Saison)."""
    by_pl = defaultdict(list)
    for r in rows:
        by_pl[r[3]].append((r[1], r[0], r[6]))
    out = {}
    for pid, lst in by_pl.items():
        lst.sort()
        played = []
        for d, gid, m in lst:
            last = played[-10:]
            out[(pid, gid)] = (len(last), sum(last) / len(last) if last else 0.0)
            if m > 0:
                played.append(m)
    return out


def forecast_check(out: Path, season: str, rows: list[list]) -> dict | None:
    f = out / "derived" / f"forecast_players_{season}.csv.gz"
    if not f.exists():
        return None
    inv = {(r[0], r[3]): r for r in rows}
    games = {r[0] for r in rows}
    n = hit = in_games = big = big_inj = 0
    with gzip.open(f, "rt", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            n += 1
            key = (r["spiel_id"], int(r["spieler_id"]))
            if r["spiel_id"] in games:
                in_games += 1
                hit += key in inv
            if float(r["minuten_erw_roh"]) > OUT_MIN:
                big += 1
                if key in inv and inv[key][5] == "INACTIVE_INJURY":
                    big_inj += 1
    played = [r for r in rows if r[6] > 0]
    pf = {(r["spiel_id"], int(r["spieler_id"])) for r in csv.DictReader(gzip.open(f, "rt", encoding="utf-8", newline=""))}
    back = sum(1 for r in played if (r[0], r[3]) in pf)
    return {"forecast_rows": n, "in_downloaded_games": in_games, "matched": hit, "big_rows": big, "big_inactive_injury": big_inj, "played": len(played), "played_in_forecast": back}


def season_report(season: str, t: dict, fc: dict | None) -> list[str]:
    rows = t["rows"]
    cnt = Counter(r[5] for r in rows)
    games = {r[0] for r in rows}
    inj_games = {r[0] for r in rows if r[5] == "INACTIVE_INJURY"}
    lines = [f"{season}",
             f"  Spiele erwartet {t['expected']}, Rohdateien vorhanden {t['present']}, fehlend {t['missing']}, unlesbar {t['unreadable']}; Tabellenzeilen {len(rows)}",
             "  Zeilen je Status: " + (", ".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])) or "-"),
             f"  Spiele mit mindestens einem INACTIVE_INJURY: {len(inj_games)} von {len(games)}" + (f" = {100 * len(inj_games) / len(games):.1f} %" if games else "")]
    if fc:
        lines.append(f"  IDs: von {fc['in_downloaded_games']} Prognosezeilen in heruntergeladenen Spielen stehen {fc['matched']} (Spiel + Spieler-ID) in der Tabelle"
                     + (f" = {100 * fc['matched'] / fc['in_downloaded_games']:.2f} %" if fc["in_downloaded_games"] else "")
                     + f"; von {fc['played']} Tabellenspielern mit Minuten > 0 haben {fc['played_in_forecast']} eine Prognosezeile")
        lines.append(f"  Prognosezeilen mit erwarteten Minuten roh > 20: {fc['big_rows']}, davon in der Tabelle als INACTIVE_INJURY: {fc['big_inactive_injury']} (die Prognosedatei enthaelt nur Spieler mit Einsatz)")
    else:
        lines.append("  forecast_players_<Saison>.csv.gz nicht gefunden: keine ID-Kontrolle")
    rm = recent_means(rows)
    inj = [r for r in rows if r[5] == "INACTIVE_INJURY"]
    big_inj = [r for r in inj if rm.get((r[3], r[0]), (0, 0))[0] >= 5 and rm[(r[3], r[0])][1] > OUT_MIN]
    lines.append(f"  INACTIVE_INJURY-Zeilen {len(inj)}, davon Spieler mit Mittel > {OUT_MIN:.0f} Min. in den letzten 10 Einsaetzen (mind. 5, aus der Tabelle): {len(big_inj)}")
    return lines


def run_report(out: Path, seasons, cdir: Path | None = None, results: Path = RESULTS, fetch_text: str = "") -> str:
    lines = ["Boxscore-Archiv mit Inaktiven (nur Zahlen)", fetch_text, ""] if fetch_text else ["Boxscore-Archiv mit Inaktiven (nur Zahlen)", ""]
    for s in seasons:
        t = build_table(out, s, cdir)
        lines += season_report(s, t, forecast_check(out, s, t["rows"]))
    text = "\n".join(lines) + "\n"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seasons", nargs="+", default=list(SEASONS), choices=list(SEASONS))
    ap.add_argument("--limit", type=int, default=None, help="hoechstens so viele Abrufe (Test)")
    ap.add_argument("--no-fetch", action="store_true", help="nur Tabelle und Bericht aus vorhandenen Rohdateien")
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args(argv)
    out = Path(args.out)
    code, fetch_text = 0, ""
    if not args.no_fetch:
        arc = Archive(out)
        result = arc.run(args.seasons, limit=args.limit)
        fetch_text = arc.report_text(result)
        print(fetch_text)
        (out / "boxscore").mkdir(parents=True, exist_ok=True)
        (out / "boxscore" / "bericht.txt").write_text(fetch_text + "\n", encoding="utf-8")
        code = 3 if result["stopped"] == "gesperrt" else 0
    print(run_report(out, args.seasons, results=Path(args.results), fetch_text=fetch_text))
    return code


if __name__ == "__main__":
    sys.exit(main())
