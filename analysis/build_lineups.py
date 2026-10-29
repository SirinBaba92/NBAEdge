"""
Aufstellungstabelle (Stints) aus dem heruntergeladenen Play-by-Play, mit Pruefung gegen die lokalen Minuten je Spieler und Spiel. NEU, rein lesend, kein Netz, aendert keine Projektdatei.

Eingabe:  <pbp-dir>/<Saison>/<spiel_id>.json.gz (analysis/fetch_pbp_archive.py; Standard ~/NBAEdge_pbp; unlesbare Dateien werden uebersprungen und gezaehlt)
          Minuten je Spieler und Spiel aus data/cache: backtest_player_games_2023-24.json, ..._2024-25.json, player_games_2025-26.json
Ausgabe:  <out-dir>/lineups_<Saison>.csv.gz (Standard ~/NBAEdge_pbp/derived) und der Bericht analysis/results/lineups_check.txt (alle vorhandenen Saisons, je Saison und gesamt)
CSV-Spalten: spiel_id, team, stint_nr, periode, start_s, ende_s, spieler1..spieler5 (personId, aufsteigend), abstand_start, abstand_ende (Punkte des Teams minus Gegner), danach
             punkte_team_start, punkte_gegner_start, punkte_team_ende, punkte_gegner_ende.

Regeln
- Spielsekunden: Periode 1-4 je 720 s, jede Verlaengerung (Periode 5, 6, ...) 300 s; start_s/ende_s zaehlen ab Spielbeginn (Verlaengerungen schliessen mit 2880 an).
- Ein Stint ist ein Abschnitt mit unveraenderten fuenf Spielern innerhalb EINER Periode. An jeder Periodengrenze wird der Stint geteilt (gleiche Spieler laufen im naechsten Stint weiter);
  Wechsel, die zur Periodengrenze notiert sind (vor oder nach dem Ereignis "period start", Uhr 12:00 bzw. 5:00 oder 0:00 der Vorperiode), gehoeren dadurch zum Beginn der neuen Periode.
  Mehrere Wechsel zur selben Sekunde erzeugen keine Stints mit der Dauer 0.
- Startaufstellung: Die lokalen Spielerdaten enthalten keine Starter-Angabe. Deshalb aus den Ereignissen: Wer zum ersten Mal mit etwas anderem als "substitution in" auftaucht
  (Wurf, Rebound, Foul, Assist, Steal, Block, "substitution out" ...), stand schon auf dem Feld. Technische Fouls und Ausschluesse zaehlen nicht (Bankspieler). Fehlen so Spieler (nur 4 gefunden),
  werden - falls Minuten bekannt sind - Spieler des Teams mit Minuten > 0 und ohne jedes Ereignis ergaenzt (sie standen durchgehend auf dem Feld).
  Pruefung der Methode: --starters prueft die 12 aufgezeichneten Spiele (NBAEdge_live_history, nur lesen) gegen das Feld "starter" der Boxscores.
Start:  venv/bin/python analysis/build_lineups.py --seasons 2023-24          (Pruefung)
        venv/bin/python analysis/build_lineups.py                            (alle drei Saisons)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import heapq
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
LOCAL_FILES = {"2023-24": "backtest_player_games_2023-24.json", "2024-25": "backtest_player_games_2024-25.json", "2025-26": "player_games_2025-26.json"}
REG_SECONDS, OT_SECONDS = 720.0, 300.0
EPS = 1e-9
CSV_HEAD = (["spiel_id", "team", "stint_nr", "periode", "start_s", "ende_s"] + [f"spieler{i}" for i in range(1, 6)]
            + ["abstand_start", "abstand_ende", "punkte_team_start", "punkte_gegner_start", "punkte_team_ende", "punkte_gegner_ende"])


# ----------------------------------------------------------------------------- Zeit
def period_start(p: int) -> float:
    return (p - 1) * REG_SECONDS if p <= 4 else 4 * REG_SECONDS + (p - 5) * OT_SECONDS


def period_len(p: int) -> float:
    return REG_SECONDS if p <= 4 else OT_SECONDS


def period_end(p: int) -> float:
    return period_start(p) + period_len(p)


def game_length(max_period: int) -> float:
    return period_end(max(4, max_period))


def clock_remaining(clock) -> float | None:
    m = re.fullmatch(r"PT(?:(\d+)M)?([\d.]+)S", str(clock or ""))
    return None if not m else int(m.group(1) or 0) * 60 + float(m.group(2))


def to_int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- Ereignisse
def parse_events(actions: list[dict]) -> list[dict]:
    """[{'t', 'period', 'type', 'sub', 'pid', 'tid', 'tri', 'score': (heim, gast)|None, 'a': Rohereignis}] in Spielreihenfolge (orderNumber, sonst Dateireihenfolge)."""
    order = sorted(range(len(actions)), key=lambda i: (to_int(actions[i].get("orderNumber")) if to_int(actions[i].get("orderNumber")) is not None else i * 10 ** 6, i))
    out, last_t = [], 0.0
    for i in order:
        a = actions[i]
        p = to_int(a.get("period")) or 0
        rem = clock_remaining(a.get("clock"))
        t = last_t if (rem is None or p < 1) else period_end(p) - rem
        sh, sa = to_int(a.get("scoreHome")), to_int(a.get("scoreAway"))
        out.append({"t": t, "period": p, "type": str(a.get("actionType") or ""), "sub": str(a.get("subType") or ""), "pid": to_int(a.get("personId")) or 0, "tid": to_int(a.get("teamId")) or 0,
                    "tri": a.get("teamTricode"), "score": None if sh is None or sa is None else (sh, sa), "a": a})
        last_t = max(last_t, t)
    return out


def infer_home(ev: list[dict]) -> int | None:
    """Heimteam: das Team, das bei Anstieg von scoreHome den Wurf/Freiwurf ausfuehrte (haeufigstes)."""
    c, prev = Counter(), (0, 0)
    for e in ev:
        if e["score"] is None:
            continue
        if e["score"][0] > prev[0] and e["tid"]:
            c[e["tid"]] += 1
        prev = e["score"]
    return c.most_common(1)[0][0] if c else None


def players_seen(ev: list[dict], teams: list[int]) -> tuple[dict, dict, dict]:
    """(erste Sichtung {pid: ('in'|'on', t)}, Team je Spieler {pid: tid}, Ereignisse je Spieler {pid: Anzahl}). 'on' = stand schon auf dem Feld (nicht ueber 'substitution in' erschienen)."""
    first, team_of, n_events = {}, {}, Counter()
    for e in ev:                                                       # Teamzuordnung nur ueber die Hauptspieler der Ereignisse
        if e["pid"] > 0 and e["tid"] > 0 and e["type"] not in ("period", "game"):
            team_of.setdefault(e["pid"], e["tid"])
    other = (lambda tid: next((t for t in teams if t != tid), 0)) if len(teams) == 2 else (lambda tid: 0)

    def see(pid, kind, t):
        if pid and pid > 0:
            n_events[pid] += 1
            first.setdefault(pid, (kind, t))

    for e in ev:
        a, typ, sub = e["a"], e["type"], e["sub"].lower()
        if typ in ("period", "game", "timeout", "ejection", "instantreplay", "stoppage"):
            continue
        if "technical" in sub:                                         # Technische Fouls/Freiwuerfe koennen Bankspieler betreffen
            continue
        if typ == "substitution":
            see(e["pid"], "in" if sub == "in" else "on", e["t"])
            continue
        see(e["pid"], "on", e["t"])
        pid = to_int(a.get("assistPersonId"))                          # Vorlagengeber: gleiches Team wie der Werfer
        if pid and pid > 0:
            team_of.setdefault(pid, e["tid"])
            see(pid, "on", e["t"])
        for key in ("stealPersonId", "blockPersonId", "foulDrawnPersonId"):
            pid = to_int(a.get(key))
            if pid and pid > 0:
                team_of.setdefault(pid, other(e["tid"]))
                see(pid, "on", e["t"])
        for key in ("jumpBallWonPersonId", "jumpBallLostPersonId", "jumpBallRecoverdPersonId"):
            see(to_int(a.get(key)), "on", e["t"])
    return first, team_of, n_events


def derive_starters(ev: list[dict], teams: list[int], tri_of: dict, played_by_tri: dict | None = None) -> tuple[dict, dict]:
    """({tid: Menge der Starter}, {'zu_wenig': [tid], 'zu_viele': [tid], 'ergaenzt': Anzahl}). Mehr als 5 Kandidaten: die fuenf mit der fruehesten Sichtung."""
    first, team_of, n_events = players_seen(ev, teams)
    info = {"zu_wenig": [], "zu_viele": [], "ergaenzt": 0}
    out = {}
    for tid in teams:
        cand = sorted((v[1], pid) for pid, v in first.items() if v[0] == "on" and team_of.get(pid) == tid)
        if len(cand) > 5:
            info["zu_viele"].append(tid)
        s = [pid for _, pid in cand[:5]]
        if len(s) < 5 and played_by_tri:
            extra = sorted(p for p in played_by_tri.get(tri_of.get(tid), ()) if n_events[p] == 0 and p not in s)
            for p in extra[:5 - len(s)]:
                s.append(p); info["ergaenzt"] += 1
        if len(s) < 5:
            info["zu_wenig"].append(tid)
        out[tid] = set(s)
    return out, info


# ----------------------------------------------------------------------------- Stints
def build_game(actions: list[dict], played_by_tri: dict | None = None, starters: dict | None = None) -> dict:
    """Rueckgabe {'rows': [Stint-Dict], 'tri': {tid: Kuerzel}, 'home': tid|None, 'end_count': {tid: Spieler auf dem Feld am Ende}, 'max_period', 'anomalies': Counter, 'starters': {tid: set}}.
    Stint-Dict: tid, nr, period, start, end, players (5, aufsteigend), score_start (team, gegner), score_end (team, gegner)."""
    ev = parse_events(actions)
    anomalies = Counter()
    teams = sorted({e["tid"] for e in ev if e["tid"] > 0})
    tri = {}
    for e in ev:
        if e["tid"] and e["tri"]:
            tri.setdefault(e["tid"], e["tri"])
    home = infer_home(ev)
    if starters is None:
        starters, info = derive_starters(ev, teams, tri, played_by_tri)
        for k, n in (("starter_zu_wenig", len(info["zu_wenig"])), ("starter_zu_viele", len(info["zu_viele"])), ("starter_ergaenzt", info["ergaenzt"])):
            if n:
                anomalies[k] += n
    state = {tid: {"on": set(starters.get(tid, ())), "t0": 0.0, "p0": 1, "sc0": (0, 0), "nr": 0} for tid in teams}
    rows, score = [], (0, 0)
    cur_p, last_t = 1, 0.0

    def team_score(tid, sc):
        if home is None:
            return (None, None)
        return (sc[0], sc[1]) if tid == home else (sc[1], sc[0])

    def close(tid, t_end):
        s = state[tid]
        if t_end - s["t0"] <= EPS:
            return
        if len(s["on"]) != 5:
            anomalies["stint_nicht_5"] += 1
            return
        s["nr"] += 1
        rows.append({"tid": tid, "nr": s["nr"], "period": s["p0"], "start": s["t0"], "end": t_end, "players": sorted(s["on"]), "score_start": team_score(tid, s["sc0"]), "score_end": team_score(tid, score)})

    def reopen(tid, t_start, period):
        s = state[tid]
        s["t0"], s["p0"], s["sc0"] = t_start, period, score

    for e in ev:
        p = e["period"]
        if p < 1:
            continue
        while cur_p < p:                                                # Periodengrenze: Stints teilen, gleiche Spieler laufen weiter
            for tid in teams:
                close(tid, period_end(cur_p))
            cur_p += 1
            for tid in teams:
                reopen(tid, period_start(cur_p), cur_p)
        if e["type"] == "substitution" and e["tid"] in state and e["pid"] > 0:
            s = state[e["tid"]]
            t = max(e["t"], s["t0"])
            changed = False
            if e["sub"] == "out":
                if e["pid"] in s["on"]:
                    close(e["tid"], t); s["on"].discard(e["pid"]); changed = True
                else:
                    anomalies["out_nicht_auf_feld"] += 1
            elif e["sub"] == "in":
                if e["pid"] not in s["on"]:
                    close(e["tid"], t); s["on"].add(e["pid"]); changed = True
                else:
                    anomalies["in_schon_auf_feld"] += 1
            if changed:
                s["t0"], s["p0"], s["sc0"] = t, cur_p, score
        if e["score"] is not None and e["score"][0] >= score[0] and e["score"][1] >= score[1]:       # Stand nur nach oben (Perioden-Ereignisse tragen manchmal keinen Stand)
            score = e["score"]
        last_t = max(last_t, e["t"])
    for tid in teams:
        close(tid, period_end(cur_p))
    return {"rows": rows, "tri": tri, "home": home, "end_count": {tid: len(state[tid]["on"]) for tid in teams}, "max_period": cur_p, "anomalies": anomalies, "starters": starters}


def csv_rows(game_id: str, g: dict) -> list[list]:
    num = lambda x: ("%g" % round(x, 2))
    out = []
    for r in sorted(g["rows"], key=lambda r: (r["tid"], r["nr"])):
        ss, se = r["score_start"], r["score_end"]
        diff = lambda sc: "" if sc[0] is None else sc[0] - sc[1]
        out.append([game_id, g["tri"].get(r["tid"], r["tid"]), r["nr"], r["period"], num(r["start"]), num(r["end"]), *r["players"], diff(ss), diff(se),
                    "" if ss[0] is None else ss[0], "" if ss[0] is None else ss[1], "" if se[0] is None else se[0], "" if se[0] is None else se[1]])
    return out


def minutes_from_rows(g: dict) -> dict:
    """{personId: Minuten} aus den Stints."""
    sec = defaultdict(float)
    for r in g["rows"]:
        for p in r["players"]:
            sec[p] += r["end"] - r["start"]
    return {p: s / 60.0 for p, s in sec.items()}


# ----------------------------------------------------------------------------- Lokale Spielerdaten
def load_local(season: str, cache_dir: Path | None = None) -> dict:
    """{game_id: {'minutes': {pid: Minuten}, 'names': {pid: Name}, 'played_by_tri': {Kuerzel: {pid mit Minuten > 0}}}}; leer, wenn die Datei fehlt."""
    path = (cache_dir or ROOT / "data" / "cache") / LOCAL_FILES[season]
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("rows", [])
    except (OSError, ValueError):
        return {}
    out = {}
    for r in rows:
        g = out.setdefault(str(r["game_id"]), {"minutes": {}, "names": {}, "played_by_tri": defaultdict(set)})
        pid = int(r["person_id"])
        g["minutes"][pid] = float(r.get("minutes") or 0.0)
        g["names"][pid] = r.get("name")
        if (r.get("minutes") or 0) > 0:
            g["played_by_tri"][r.get("team")].add(pid)
    return out


def read_pbp(path: Path):
    """(game_id, Aktionen) oder None bei unlesbarer/unpassender Datei."""
    try:
        d = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        g = d["game"]
        if str(g.get("gameId")) != path.name.split(".")[0] or not isinstance(g.get("actions"), list):
            return None
        return str(g["gameId"]), g["actions"]
    except Exception:
        return None


# ----------------------------------------------------------------------------- Saison
def new_summary(season: str) -> dict:
    return {"season": season, "pbp_dateien": 0, "gelesen": 0, "nicht_lesbar": 0, "ohne_lokale_daten": 0, "erwartet": 0, "spieler_spiele": 0, "le05": 0, "le10": 0, "gt10": 0, "top": [],
            "spiele_ende_nicht_5": 0, "ende_beispiele": [], "spiele_teamsumme_falsch": 0, "teamsumme_beispiele": [], "anomalien": {}, "stints": 0}


def run_season(season: str, pbp_dir: Path, out_dir: Path, cache_dir: Path | None = None, limit: int | None = None, write=print) -> dict:
    sm = new_summary(season)
    local = load_local(season, cache_dir)
    sm["erwartet"] = len(local)
    files = sorted(p for p in (pbp_dir / season).glob("*.json.gz")) if (pbp_dir / season).is_dir() else []
    sm["pbp_dateien"] = len(files)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"lineups_{season}.csv.gz.tmp"
    anomalies, top = Counter(), []
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEAD)
        for i, path in enumerate(files):
            if limit is not None and sm["gelesen"] >= limit:
                break
            res = read_pbp(path)
            if res is None:
                sm["nicht_lesbar"] += 1
                continue
            gid, actions = res
            sm["gelesen"] += 1
            loc = local.get(gid)
            g = build_game(actions, (loc or {}).get("played_by_tri"))
            anomalies.update(g["anomalies"])
            for row in csv_rows(gid, g):
                w.writerow(row)
            sm["stints"] += len(g["rows"])
            if any(n != 5 for n in g["end_count"].values()) or len(g["end_count"]) != 2:
                sm["spiele_ende_nicht_5"] += 1
                if len(sm["ende_beispiele"]) < 5:
                    sm["ende_beispiele"].append(gid)
            mins = minutes_from_rows(g)
            expected = 5 * game_length(g["max_period"]) / 60.0
            by_team = defaultdict(float)
            for r in g["rows"]:
                by_team[r["tid"]] += 5 * (r["end"] - r["start"]) / 60.0
            if len(by_team) != 2 or any(abs(v - expected) > 1e-6 for v in by_team.values()):
                sm["spiele_teamsumme_falsch"] += 1
                if len(sm["teamsumme_beispiele"]) < 5:
                    sm["teamsumme_beispiele"].append(f"{gid} ({', '.join('%.1f' % v for v in by_team.values())} statt {expected:g})")
            if loc is None:
                sm["ohne_lokale_daten"] += 1
                continue
            for pid in {p for p, m in loc["minutes"].items() if m > 0} | set(mins):
                d = abs(mins.get(pid, 0.0) - loc["minutes"].get(pid, 0.0))
                sm["spieler_spiele"] += 1
                sm["le05"] += d <= 0.5 + 1e-9
                sm["le10"] += d <= 1.0 + 1e-9
                sm["gt10"] += d > 1.0 + 1e-9
                item = (round(d, 2), gid, pid, loc["names"].get(pid), round(mins.get(pid, 0.0), 2), loc["minutes"].get(pid, 0.0))
                if len(top) < 10:
                    heapq.heappush(top, item)
                elif item > top[0]:
                    heapq.heapreplace(top, item)
            if (i + 1) % 200 == 0:
                write(f"{season}: {i + 1} Dateien bearbeitet")
    os.replace(tmp, out_dir / f"lineups_{season}.csv.gz")
    sm["top"] = [list(x) for x in sorted(top, reverse=True)]
    sm["anomalien"] = dict(anomalies)
    (out_dir / f"summary_{season}.json").write_text(json.dumps(sm, ensure_ascii=False, indent=1), encoding="utf-8")
    return sm


# ----------------------------------------------------------------------------- Startaufstellung gegen Boxscores pruefen
def check_starters(live_dir: Path, day: str = "2026-10-28", cache_dir: Path | None = None) -> dict:
    """Vergleich der aus dem Play-by-Play abgeleiteten Starter mit dem Feld 'starter' der aufgezeichneten Boxscores (nur lesen). Gibt die Zahlen fuer beide Varianten
    (nur Ereignisse / mit Ergaenzung aus den Minuten) zurueck."""
    local = {}
    try:
        for r in json.loads(((cache_dir or ROOT / "data" / "cache") / "player_games_2026-27.json").read_text(encoding="utf-8")).get("rows", []):
            g = local.setdefault(str(r["game_id"]), defaultdict(set))
            if (r.get("minutes") or 0) > 0:
                g[r.get("team")].add(int(r["person_id"]))
    except (OSError, ValueError):
        pass
    res = {"spiele": 0, "teams": 0, "ereignisse": {"teams_exakt": 0, "spieler_treffer": 0, "zu_wenig": 0, "zu_viele": 0}, "mit_minuten": {"teams_exakt": 0, "spieler_treffer": 0, "zu_wenig": 0, "zu_viele": 0}, "fehler": []}
    for gdir in sorted((live_dir / day).glob("*/")):
        try:
            box = json.loads(gzip.decompress((gdir / "final_box.json.gz").read_bytes()).decode("utf-8"))["game"]
            actions = json.loads(gzip.decompress((gdir / "final_pbp.json.gz").read_bytes()).decode("utf-8"))["game"]["actions"]
        except Exception:
            continue
        truth = {int(box[k]["teamId"]): {int(p["personId"]) for p in box[k]["players"] if str(p.get("starter")) == "1"} for k in ("homeTeam", "awayTeam")}
        res["spiele"] += 1
        for variant, played in (("ereignisse", None), ("mit_minuten", local.get(gdir.name))):
            ev = parse_events(actions)
            teams = sorted({e["tid"] for e in ev if e["tid"] > 0})
            tri = {e["tid"]: e["tri"] for e in ev if e["tid"] and e["tri"]}
            st, info = derive_starters(ev, teams, tri, played)
            for tid, real in truth.items():
                got = st.get(tid, set())
                v = res[variant]
                v["teams_exakt"] += got == real
                v["spieler_treffer"] += len(got & real)
                v["zu_wenig"] += len(got) < 5
                v["zu_viele"] += tid in info["zu_viele"]
                if variant == "ereignisse":
                    res["teams"] += 1
                    if got != real:
                        res["fehler"].append(f"{gdir.name} {tri.get(tid, tid)}: gefunden {sorted(got)}, Boxscore {sorted(real)}")
    return res


# ----------------------------------------------------------------------------- Bericht
def merge(a: dict, b: dict) -> dict:
    out = new_summary("gesamt")
    for s in (a, b):
        for k in ("pbp_dateien", "gelesen", "nicht_lesbar", "ohne_lokale_daten", "erwartet", "spieler_spiele", "le05", "le10", "gt10", "spiele_ende_nicht_5", "spiele_teamsumme_falsch", "stints"):
            out[k] += s[k]
        out["top"] = sorted(out["top"] + s["top"], reverse=True)[:10]
        out["ende_beispiele"] = (out["ende_beispiele"] + s["ende_beispiele"])[:5]
        out["teamsumme_beispiele"] = (out["teamsumme_beispiele"] + s["teamsumme_beispiele"])[:5]
        for k, v in s["anomalien"].items():
            out["anomalien"][k] = out["anomalien"].get(k, 0) + v
    return out


def season_text(sm: dict) -> list[str]:
    n = sm["spieler_spiele"]
    pct = lambda x: "-" if not n else f"{100 * x / n:.2f} %"
    lines = [f"=== {sm['season']} ===",
             f"Spiele erwartet (lokale Spielerdaten): {sm['erwartet']} | PBP-Dateien: {sm['pbp_dateien']} | gelesen: {sm['gelesen']} | nicht lesbar (uebersprungen): {sm['nicht_lesbar']} | ohne lokale Spielerdaten: {sm['ohne_lokale_daten']}",
             f"Stints: {sm['stints']}",
             f"Minuten je Spieler und Spiel (Stints gegen lokale Minuten, {n} Spieler-Spiele): Abweichung <= 0,5 Min: {sm['le05']} ({pct(sm['le05'])}); <= 1 Min: {sm['le10']} ({pct(sm['le10'])}); groesser als 1 Min: {sm['gt10']} ({pct(sm['gt10'])})",
             "Die 10 groessten Abweichungen (Abweichung, Spiel, Spieler, Minuten aus Stints, lokale Minuten):"]
    lines += [f"  {t[0]:6.2f}  {t[1]}  {t[2]} {t[3] or ''}  Stints {t[4]:.2f}  lokal {t[5]:g}" for t in sm["top"]] or ["  (keine)"]
    lines += [f"Spiele, bei denen am Ende nicht genau 5 Spieler je Team auf dem Feld stehen: {sm['spiele_ende_nicht_5']}" + (f" (z. B. {', '.join(sm['ende_beispiele'])})" if sm["ende_beispiele"] else ""),
              f"Spiele, bei denen die Teamsumme nicht 240 plus 25 je Verlaengerung ist: {sm['spiele_teamsumme_falsch']}" + (f" (z. B. {'; '.join(sm['teamsumme_beispiele'])})" if sm["teamsumme_beispiele"] else ""),
              "Auffaelligkeiten (Zahl der Faelle): " + (", ".join(f"{k} {v}" for k, v in sorted(sm["anomalien"].items())) or "keine"), ""]
    return lines


def build_report(out_dir: Path, starters: dict | None, seasons=SEASONS) -> str:
    sums = []
    for s in seasons:
        p = out_dir / f"summary_{s}.json"
        if p.exists():
            sums.append(json.loads(p.read_text(encoding="utf-8")))
    lines = ["Pruefung der Aufstellungstabelle (analysis/build_lineups.py): Stints aus dem Play-by-Play gegen die lokalen Minuten je Spieler und Spiel.",
             "Lokale Minuten sind ganze Minuten (Ligaprotokoll); Abweichungen bis 0,5 Min sind deshalb durch Rundung allein moeglich.", ""]
    for sm in sums:
        lines += season_text(sm)
    if len(sums) > 1:
        tot = sums[0]
        for sm in sums[1:]:
            tot = merge(tot, sm)
        tot["season"] = "gesamt (" + ", ".join(s["season"] for s in sums) + ")"
        lines += season_text(tot)
    if starters:
        n = starters["teams"]
        lines += ["=== Startaufstellung: aus Ereignissen abgeleitet gegen Boxscore-Feld 'starter' (12 aufgezeichnete Spiele vom 28.10.2026) ===",
                  f"Spiele: {starters['spiele']}, Teams: {n}"]
        for k, name in (("ereignisse", "nur aus Ereignissen"), ("mit_minuten", "Ereignisse + Minuten (Ergaenzung durchgehend aktiver Spieler ohne Ereignis)")):
            v = starters[k]
            lines.append(f"  {name}: Team exakt richtig {v['teams_exakt']} von {n} ({100 * v['teams_exakt'] / max(1, n):.1f} %), Spieler richtig {v['spieler_treffer']} von {5 * n} ({100 * v['spieler_treffer'] / max(1, 5 * n):.1f} %), "
                         f"Teams mit weniger als 5 gefunden: {v['zu_wenig']}, mit mehr als 5 Kandidaten: {v['zu_viele']}")
        lines += [f"  Abweichung: {x}" for x in starters["fehler"][:12]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--out-dir", default=str(HOME / "NBAEdge_pbp" / "derived"))
    ap.add_argument("--seasons", nargs="+", default=list(SEASONS), choices=list(SEASONS))
    ap.add_argument("--limit", type=int, default=None, help="hoechstens so viele Spiele je Saison (Test)")
    ap.add_argument("--report", default=str(ROOT / "analysis" / "results" / "lineups_check.txt"))
    ap.add_argument("--live-dir", default=str(HOME / "NBAEdge_live_history"))
    ap.add_argument("--no-starters", action="store_true", help="Startaufstellungs-Pruefung an den 12 aufgezeichneten Spielen ueberspringen")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    for s in args.seasons:
        sm = run_season(s, Path(args.pbp_dir), out_dir, limit=args.limit)
        print(f"{s}: {sm['gelesen']} Spiele gelesen ({sm['pbp_dateien']} Dateien, {sm['nicht_lesbar']} nicht lesbar), {sm['stints']} Stints")
    starters = None
    if not args.no_starters:
        starters = check_starters(Path(args.live_dir))
        (out_dir / "summary_starters.json").write_text(json.dumps(starters, ensure_ascii=False, indent=1), encoding="utf-8")
    elif (out_dir / "summary_starters.json").exists():
        starters = json.loads((out_dir / "summary_starters.json").read_text(encoding="utf-8"))
    text = build_report(out_dir, starters)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
