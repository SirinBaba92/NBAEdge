"""
History-Tab, reine Logik (kein Netz, keine Oberflaeche, schreibt nichts): beendete Spiele mit der Vorab-Prognose und dem tatsaechlichen Ergebnis.

Prognose: data/tracking/projection_snapshots.json (data/projection_snapshots.py). Es zaehlt NUR der Stand vor dem Anpfiff: die letzte Version mit saved_at <= start_utc
(Versionen danach werden ignoriert; gibt es keine, hat das Spiel keine Vorab-Prognose und erscheint nicht).
Ergebnis: Feld "result" des Snapshots (home_points / away_points); fehlt es, result.json des Recorders (~/NBAEdge_live_history/<Tag>/<game_id>/, nur lesen, NBAEDGE_LIVE_DIR).
Linien: Markt-Total (projection.market_total) und Markt-Spread (projection.market_spread, Heim-Vorsprung; Spread-Zahlen ueberall aus Sicht des Heimteams).
Modell-Tipp: Total Ueber, wenn exp_total > Linie, Unter, wenn kleiner; Spread Heim deckt, wenn exp_spread > Linie, Gast deckt, wenn kleiner; Sieger: Heim, wenn home_win_prob > 0,5.
Ergebnis eines Tipps: "treffer" | "fehlschlag" | "push" (Ergebnis genau auf der Linie, bei ganzzahligen Linien moeglich: weder Sieg noch Niederlage) | "kein_tipp" (Prognose genau auf der Linie) | None (keine Linie).
Abweichung = Ist minus Prognose (positiv: mehr Punkte / groesserer Heim-Vorsprung als prognostiziert).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from data import pre_match_store as store
from data import projection_snapshots as snaps

EPS = 1e-9
OUTCOME_LABEL = {"treffer": "Treffer", "fehlschlag": "Fehlschlag", "push": "Push", "kein_tipp": "kein Tipp", None: "—"}


def pre_game_version(game: dict) -> dict | None:
    """Letzte Version mit saved_at <= start_utc; ohne Anpfiffzeit oder ohne solche Version None."""
    start = store.parse_utc(game.get("start_utc"))
    if start is None:
        return None
    ok = [v for v in (game.get("versions") or []) if (store.parse_utc(v.get("saved_at")) or float("inf")) <= start]
    return ok[-1] if ok else None


def live_root() -> Path:
    return Path(os.environ.get("NBAEDGE_LIVE_DIR") or Path.home() / "NBAEdge_live_history")


def recorder_result(day: str, home: str, away: str, root: Path | None = None) -> dict | None:
    """Endstand aus result.json des Recorders (Heim/Gast ueber den Teamnamen); None, wenn nicht gefunden."""
    base = Path(root or live_root()) / str(day)
    try:
        for p in sorted(base.glob("*/result.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            if (r.get("home") or {}).get("team") == home and (r.get("away") or {}).get("team") == away:
                return {"home_points": int(r["home"]["final"]), "away_points": int(r["away"]["final"]), "source": "recorder"}
    except Exception:
        return None
    return None


def game_result(game: dict, root: Path | None = None) -> dict | None:
    r = game.get("result")
    if isinstance(r, dict) and r.get("home_points") is not None and r.get("away_points") is not None:
        return {"home_points": int(r["home_points"]), "away_points": int(r["away_points"]), "source": "snapshot"}
    return recorder_result(game.get("game_date"), game.get("home"), game.get("away"), root)


def _cmp(actual: float, line: float) -> int:
    d = actual - line
    return 0 if abs(d) < EPS else (1 if d > 0 else -1)


def judge(tip: int | None, actual: int) -> str | None:
    """tip/actual: +1 / -1 (Ueber oder Heim | Unter oder Gast), 0 beim Ergebnis = genau auf der Linie. tip None -> keine Linie, 0 -> Prognose auf der Linie."""
    if tip is None:
        return None
    if actual == 0:
        return "push"
    if tip == 0:
        return "kein_tipp"
    return "treffer" if tip == actual else "fehlschlag"


def evaluate(key: str, game: dict, root: Path | None = None) -> dict | None:
    """Eine Zeile fuer ein beendetes Spiel oder None (kein Ergebnis oder keine Vorab-Prognose)."""
    res, ver = game_result(game, root), pre_game_version(game)
    if not res or not ver:
        return None
    pr = ver.get("projection") or {}
    if pr.get("home_score") is None or pr.get("away_score") is None:
        return None
    hp, ap = res["home_points"], res["away_points"]
    total, margin = hp + ap, hp - ap
    exp_total, exp_spread = pr.get("exp_total"), pr.get("exp_spread")
    t_line = pr.get("market_total") if pr.get("market_total") is not None else ((ver.get("markets") or {}).get("total") or {}).get("line")
    s_line = pr.get("market_spread") if pr.get("market_spread") is not None else ((ver.get("markets") or {}).get("spread") or {}).get("line")
    out = {
        "key": key, "day": game.get("game_date"), "start_utc": game.get("start_utc"), "home": game.get("home"), "away": game.get("away"),
        "forecast_saved_at": ver.get("saved_at"), "result_source": res["source"],
        "pred_home": pr["home_score"], "pred_away": pr["away_score"], "pred_total": exp_total, "pred_spread": exp_spread,
        "home_win_prob": pr.get("home_win_prob"),
        "act_home": hp, "act_away": ap, "act_total": total, "act_spread": margin,
        "dev_home": hp - pr["home_score"], "dev_away": ap - pr["away_score"],
        "dev_total": None if exp_total is None else total - exp_total, "dev_spread": None if exp_spread is None else margin - exp_spread,
        "total_line": t_line, "spread_line": s_line,
    }
    hwp = pr.get("home_win_prob")
    out["winner"] = None if hwp is None else judge(_sign(hwp - 0.5), 1 if margin > 0 else -1)
    if t_line is None or exp_total is None:
        out["total_tip"], out["total_result"], out["total_outcome"] = None, None, None
    else:
        tip, act = _sign(exp_total - t_line), _cmp(total, t_line)
        out["total_tip"], out["total_result"] = {1: "Über", -1: "Unter", 0: None}[tip], {1: "Über", -1: "Unter", 0: "Push"}[act]
        out["total_outcome"] = judge(tip, act)
    if s_line is None or exp_spread is None:
        out["spread_tip"], out["spread_result"], out["spread_outcome"] = None, None, None
    else:
        tip, act = _sign(exp_spread - s_line), _cmp(margin, s_line)
        out["spread_tip"], out["spread_result"] = {1: "Heim", -1: "Gast", 0: None}[tip], {1: "Heim", -1: "Gast", 0: "Push"}[act]
        out["spread_outcome"] = judge(tip, act)
    return out


def _sign(x: float) -> int:
    return 0 if abs(x) < EPS else (1 if x > 0 else -1)


def finished_games(data: dict | None = None, root: Path | None = None) -> list[dict]:
    """Alle beendeten Spiele mit Vorab-Prognose, neueste Tage zuerst (innerhalb eines Tages nach Anpfiff)."""
    games = (data if data is not None else snaps.load()).get("games", {})
    rows = [r for k, g in games.items() if (r := evaluate(k, g, root))]
    rows.sort(key=lambda r: (r["start_utc"] or ""))
    rows.sort(key=lambda r: r["day"] or "", reverse=True)
    return rows


def summarize(rows: list[dict]) -> dict:
    """Zaehlung je Markt: treffer / fehlschlag / push / kein_tipp / ohne_linie, plus mittlerer absoluter Fehler (Total, Spread, Punkte je Team)."""
    def count(field):
        c = {"treffer": 0, "fehlschlag": 0, "push": 0, "kein_tipp": 0, "ohne_linie": 0}
        for r in rows:
            c[r[field] or "ohne_linie"] += 1
        return c
    def mae(field):
        v = [abs(r[field]) for r in rows if r[field] is not None]
        return None if not v else sum(v) / len(v)
    return {"games": len(rows), "winner": count("winner"), "total": count("total_outcome"), "spread": count("spread_outcome"),
            "mae_total": mae("dev_total"), "mae_spread": mae("dev_spread"), "mae_team": mae_team(rows)}


def mae_team(rows: list[dict]) -> float | None:
    v = [abs(r[k]) for r in rows for k in ("dev_home", "dev_away")]
    return None if not v else sum(v) / len(v)
