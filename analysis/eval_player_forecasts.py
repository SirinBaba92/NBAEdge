"""
Auswertung der festgehaltenen Spieler-Prognosen (analysis/results/forecast_snapshots/<Tag>.json, geschrieben von analysis/print_player_forecast.py) gegen die Ergebnisse. UNGEPRUEFT.
Nur lesend, kein Netz.

Aufruf:  venv/bin/python analysis/eval_player_forecasts.py [Tag JJJJ-MM-TT] [--dir <Snapshot-Ordner>]
  mit Tag:  Auswertung dieses Tages plus Gesamtblock ueber alle vorhandenen Snapshots;  ohne Tag: jeder Tag einzeln plus Gesamtblock.
Ergebnisse je Spieler: ~/NBAEdge_live_history/<Tag>/<game_id>/final_box.json.gz (Recorder, nur lesen), sonst die Liga-Datei data/cache/player_games_*.json.
Spieler mit 0 Minuten oder ohne Eintrag im Boxscore zaehlen als "nicht gespielt" und werden aus der Wertung genommen. Zeile = (Spieler, Meilenstein N), Treffer = Punkte >= N.
Ausgabe auch nach analysis/results/eval_player_forecasts_<Tag|alle>.txt (nicht im Repository).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data import player_history as ph                  # noqa: E402

MARK_PP = 5.0
CHANCES = (("bookmaker", "Buchmacher (inkl. Marge)"), ("raw", "Modell roh"), ("team", "Modell Teamabgleich"))
NOTE = ("Kleine Stichprobe: die Zeilen eines Spielers (Meilensteine 10+, 11+, 12+ ...) sind stark korreliert, "
        "die Zahl unabhängiger Beobachtungen ist die Zahl der Spieler, nicht der Zeilen.")


def snapshot_dir(override: str | None = None) -> Path:
    return Path(override or os.environ.get("NBAEDGE_SNAPSHOT_DIR") or ROOT / "analysis" / "results" / "forecast_snapshots")


def live_root() -> Path:
    return Path(os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history")


def load_snapshots(directory: Path, day: str | None = None) -> dict[str, dict]:
    out = {}
    for f in sorted(Path(directory).glob("????-??-??.json")):
        if day and f.stem != day:
            continue
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return out


# ----------------------------------------------------------------------------- Ergebnisse
def _nick(name: str) -> str:
    return str(name or "").lower().split(" ")[-1]


def _box_results(day: str, home: str, away: str) -> dict | None:
    ddir = live_root() / day
    try:
        dirs = sorted(p for p in ddir.iterdir() if p.is_dir())
    except OSError:
        return None
    for gdir in dirs:
        f = gdir / "final_box.json.gz"
        if not f.is_file():
            continue
        try:
            game = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8")).get("game") or {}
        except Exception:
            continue
        h, a = game.get("homeTeam") or {}, game.get("awayTeam") or {}
        if str(h.get("teamName", "")).lower() == _nick(home) and str(a.get("teamName", "")).lower() == _nick(away):
            res = {}
            for team in (h, a):
                for p in team.get("players") or []:
                    s = p.get("statistics") or {}
                    res[int(p["personId"])] = {"minutes": ph.minutes_to_float(s.get("minutes")), "points": int(s.get("points") or 0)}
            return res
    return None


def _league_results(day: str, abbrs: set[str]) -> dict | None:
    try:
        rows = ph.season_rows(ph.season_of_date(day), with_recorder=False)
    except Exception:
        return None
    game = [r for r in rows if r["date"] == day and r["team"] in abbrs]
    return {r["person_id"]: {"minutes": r["minutes"], "points": r["points"]} for r in game} if game else None


def game_results(day: str, entry: dict) -> tuple[dict | None, str]:
    parts = entry["game_key"].split("|")
    res = _box_results(day, parts[2], parts[3])
    if res is not None:
        return res, "Recorder-Boxscore"
    abbrs = {p.get("team_abbreviation") for p in entry["players"] if p.get("team_abbreviation")}
    res = _league_results(day, abbrs)
    return res, "Liga-Datei" if res is not None else "keine Ergebnisse"


# ----------------------------------------------------------------------------- Kennzahlen
def collect(days: dict[str, dict]) -> dict:
    """Zeilen und Spieler aus den Snapshots mit Ergebnissen. Rueckgabe {'rows', 'players', 'games', 'skipped_games', 'not_played', 'no_forecast'}."""
    rows, players, games, skipped, not_played, no_fc = [], [], 0, [], [], []
    for day, data in days.items():
        for key, entry in data["games"].items():
            res, source = game_results(day, entry)
            if res is None:
                skipped.append(f"{day} {key.split('|')[3]} @ {key.split('|')[2]}: {source}")
                continue
            games += 1
            for p in entry["players"]:
                got = res.get(int(p["person_id"]))
                if not got or got["minutes"] <= 0:
                    not_played.append(f"{p['name']} ({p['team']})")
                    continue
                if not p["ok"]:
                    no_fc.append(p["name"])
                    continue
                players.append({"day": day, "name": p["name"], "team": p["team"], "minutes_pred": p["minutes_adjusted"], "minutes": got["minutes"], "points": got["points"],
                                "points_raw": p["expected_points_raw"], "points_team": p["expected_points_adjusted"]})
                for q in p["quotes"]:
                    n = q["milestone"]
                    rows.append({"day": day, "name": p["name"], "team": p["team"], "n": n, "hit": got["points"] >= n, "odds": q["odds"], "bookmaker": q["bookmaker_probability"],
                                 "raw": p["p_ge_raw"][str(n)], "team_p": p["p_ge_adjusted"][str(n)]})
    return {"rows": rows, "players": players, "games": games, "skipped_games": skipped, "not_played": not_played, "no_forecast": no_fc}


def prob(row: dict, kind: str) -> float:
    return row["bookmaker"] if kind == "bookmaker" else row["raw"] if kind == "raw" else row["team_p"]


def brier(rows: list[dict], kind: str) -> float | None:
    return sum((prob(r, kind) - r["hit"]) ** 2 for r in rows) / len(rows) if rows else None


def bias(rows: list[dict], kind: str) -> float | None:
    return sum(prob(r, kind) - r["hit"] for r in rows) / len(rows) if rows else None


def bins5(rows: list[dict], kind: str) -> list[tuple[int, float, float]]:
    """5 Stufen (0-20 ... 80-100 %): (Anzahl, mittlere Chance, Trefferquote); leere Stufen entfallen."""
    out = []
    for b in range(5):
        sel = [r for r in rows if min(4, int(prob(r, kind) * 5)) == b]
        if sel:
            out.append((len(sel), sum(prob(r, kind) for r in sel) / len(sel), sum(r["hit"] for r in sel) / len(sel)))
    return out


def mean_abs_dev(rows: list[dict], kind: str) -> float | None:
    b = bins5(rows, kind)
    return sum(n * abs(h - p) for n, p, h in b) / sum(n for n, _, _ in b) if b else None


def units(rows: list[dict]) -> tuple[int, float, float, float]:
    """(Zeilen, Trefferquote, mittlere Quote, Gewinn in Einheiten bei Einsatz 1 je Zeile)."""
    if not rows:
        return 0, 0.0, 0.0, 0.0
    return len(rows), sum(r["hit"] for r in rows) / len(rows), sum(r["odds"] for r in rows) / len(rows), sum((r["odds"] - 1) if r["hit"] else -1.0 for r in rows)


# ----------------------------------------------------------------------------- Ausgabe
def pct(x) -> str:
    return "-" if x is None else f"{100 * x:5.1f}%"


def render_block(title: str, c: dict) -> list[str]:
    rows, players = c["rows"], c["players"]
    L = [f"=== {title} ===", f"Spiele {c['games']}, Spieler gewertet {len(players)}, Zeilen {len(rows)}, nicht gespielt {len(c['not_played'])}"
         + (f" ({', '.join(c['not_played'][:8])}{' …' if len(c['not_played']) > 8 else ''})" if c["not_played"] else "") + f", ohne Prognose {len(c['no_forecast'])}"]
    for s in c["skipped_games"]:
        L.append(f"  ohne Ergebnisse übersprungen: {s}")
    if not rows:
        return L + ["(keine Zeilen)"]
    L.append("\nTrefferquote gegen Chance (5 Stufen):")
    for kind, label in CHANCES:
        L.append(f"  {label}:")
        for n, p, h in bins5(rows, kind):
            L.append(f"    Chance ~{100*p:4.1f}%  Zeilen {n:>4}  Trefferquote {100*h:5.1f}%  Abweichung {100*(h-p):+5.1f}")
    L.append("\nBrier-Wert (kleiner ist besser) / mittlere Abweichung der Stufen / Verzerrung (Chance minus Trefferquote):")
    for kind, label in CHANCES:
        L.append(f"  {label:<26} Brier {brier(rows, kind):.4f}   Abweichung {100*mean_abs_dev(rows, kind):4.1f} PP   Verzerrung {100*bias(rows, kind):+5.1f} PP")
    teams = sorted({r["team"] for r in rows})
    L.append("\nJe Team (Brier: Buchmacher / roh / Teamabgleich):")
    for t in teams:
        sel = [r for r in rows if r["team"] == t]
        L.append(f"  {t:<24} Zeilen {len(sel):>4}  {brier(sel,'bookmaker'):.4f} / {brier(sel,'raw'):.4f} / {brier(sel,'team'):.4f}")
    up = [r for r in rows if r["team_p"] * 100 - r["bookmaker"] * 100 >= MARK_PP]
    down = [r for r in rows if r["team_p"] * 100 - r["bookmaker"] * 100 <= -MARK_PP]
    L.append(f"\nMarkierte Zeilen (Modell Teamabgleich gegen Buchmacher, Schwelle {MARK_PP:g} PP; Einsatz 1 je Zeile auf Over, hypothetisch):")
    for sym, sel, txt in (("◀", up, "Modell höher"), ("▼", down, "Modell niedriger")):
        n, hit, odds, prof = units(sel)
        L.append(f"  {sym} {txt}: Zeilen {n}, Trefferquote {pct(hit)}, mittlere Quote {odds:.2f}, Einheiten {prof:+.1f}"
                 + (f" (Buchmacher-Erwartung der Zeilen {pct(sum(r['bookmaker'] for r in sel)/n)})" if n else ""))
    L.append("\nVorhergesagte gegen tatsächliche Werte, 10 größte Punkte-Abweichungen (Teamabgleich):")
    for p in sorted(players, key=lambda p: -abs(p["points"] - p["points_team"]))[:10]:
        L.append(f"  {p['name']:<26} Punkte erwartet {p['points_team']:5.1f} (roh {p['points_raw']:5.1f}) tatsächlich {p['points']:>3}   Minuten erwartet {p['minutes_pred']:4.1f} tatsächlich {p['minutes']:4.1f}")
    if players:
        L.append(f"  Mittel über alle Spieler: Punkte Fehler {sum(p['points_team']-p['points'] for p in players)/len(players):+.2f} (roh {sum(p['points_raw']-p['points'] for p in players)/len(players):+.2f}), "
                 f"Minuten Fehler {sum(p['minutes_pred']-p['minutes'] for p in players)/len(players):+.2f}")
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Wertet festgehaltene Spieler-Prognosen gegen Ergebnisse aus (UNGEPRÜFT)")
    ap.add_argument("tag", nargs="?", help="Spieltag JJJJ-MM-TT (Standard: alle vorhandenen Snapshots)")
    ap.add_argument("--dir", help="Snapshot-Ordner")
    args = ap.parse_args(argv)
    directory = snapshot_dir(args.dir)
    everything = load_snapshots(directory)
    if not everything:
        print(f"Keine Snapshots in {directory}.")
        return 2
    if args.tag and args.tag not in everything:
        print(f"Kein Snapshot für {args.tag} (vorhanden: {', '.join(everything)}).")
        return 2
    L = ["UNGEPRÜFT – " + NOTE, ""]
    shown = [args.tag] if args.tag else list(everything)
    for d in shown:
        L += render_block(f"Spieltag {d}", collect({d: everything[d]})) + [""]
    if len(everything) > 1 or not args.tag:
        L += render_block(f"GESAMT über {len(everything)} Spieltag(e): {', '.join(everything)}", collect(everything))
    text = "\n".join(L)
    print(text)
    out = ROOT / "analysis" / "results" / f"eval_player_forecasts_{args.tag or 'alle'}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\n(gespeichert: {out.relative_to(ROOT)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
