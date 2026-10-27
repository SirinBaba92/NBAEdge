"""
Team-Modell "team-2": Verletzungs-Korrektur fuer Spread und Siegchance. Das heutige Modell (engine/projection.compute_projection) bleibt unveraendert und der Standard; team-2 ist eine
ZUSAETZLICHE Variante, die aus der fertigen Projektion und den gespeicherten Ausfaellen (data/absences_store, Status "fehlt"; "fraglich" zaehlt nicht) berechnet wird. Kein Netz, schreibt nichts.

Ausfall-Mass je Team (Mass wie in analysis/backtest_winner_injuries.py): Summe der Punkte-pro-Spiel-Anteile (Punkte pro gespieltem Spiel des Spielers / Teampunkte pro Teamspiel) der
fehlenden Spieler aus den Top 8 des Teams nach Minuten.
Basis (pro Spiel EINE, nie gemischt): Haben beide Teams vor diesem Spiel weniger als 10 Spiele in der laufenden Saison (gezaehlt aus dem Spielerverlauf), gilt die LETZTE Saison: Top 8 und
Anteile aus den Spielen der Vorsaison mit diesem Team, nur Spieler, die jetzt im Kader dieses Teams stehen und letzte Saison fuer dasselbe Team gespielt haben (Neuzugaenge und Rookies zaehlen
noch nicht). Ab dem 10. Teamspiel beider Teams gilt die laufende Saison bis zu diesem Spiel (alle Spiele mit dem Team davor).
Korrektur: delta = FACTOR * SLOPE * (Mass Heim - Mass Gast) = 0,5 * (-14,4) * (...), addiert auf den Heim-Spread (positiv = Heim staerker). Die Punkte beider Teams verschieben sich je zur Haelfte
(Heim +delta/2, Gast -delta/2, gerundet; Gast = altes Total - Heim, das Total bleibt also gleich). Die Siegchance kommt aus dem korrigierten Spread (engine/line_probabilities.win_prob_home, gleiches Sigma).
Die Steigung -14,4 stammt aus analysis/reports/winner_injuries_2025-26.txt (Obergrenze, Wissen aus der Zukunft); FACTOR 0,5 nimmt unsichere Meldungen vorweg.
"""
from __future__ import annotations

import math

from engine import line_probabilities as lp

TEAM_MODEL_VERSION = "team-2"
SLOPE = -14.4
FACTOR = 0.5
MIN_TEAM_GAMES = 10
TOP_N = 8
PP_NOTE = 2.0                       # gelbes Zeichen, wenn sich die Siegchance um mehr als so viele Prozentpunkte verschiebt
BASE_PREV, BASE_CUR = "Vorjahr", "laufende Saison"


def top_players(rows: list[dict], abbr: str, before_day: str | None = None, candidates: set | None = None) -> tuple[list[dict], int]:
    """Top 8 des Teams nach Minuten und ihre Punkte-pro-Spiel-Anteile. rows: Spielerzeilen (data/player_history); nur Zeilen mit team == abbr und date < before_day (None: alle).
    candidates: nur diese person_ids kommen in Frage. Rueckgabe ([{'person_id', 'name', 'share', 'minutes'}], Zahl der Teamspiele)."""
    games, cum = set(), {}
    team_pts = 0.0
    for r in rows:
        if r.get("team") != abbr or (before_day is not None and str(r.get("date")) >= before_day):
            continue
        games.add(r["game_id"])
        team_pts += r.get("points") or 0
        m = r.get("minutes") or 0
        if m <= 0 or (candidates is not None and int(r["person_id"]) not in candidates):
            continue
        c = cum.setdefault(int(r["person_id"]), {"name": r.get("name"), "min": 0.0, "pts": 0.0, "gp": 0})
        c["min"] += m
        c["pts"] += r.get("points") or 0
        c["gp"] += 1
    if not games or team_pts <= 0:
        return [], len(games)
    tppg = team_pts / len(games)
    top = sorted(cum.items(), key=lambda kv: (-kv[1]["min"], kv[0]))[:TOP_N]
    return [{"person_id": pid, "name": c["name"], "share": (c["pts"] / c["gp"]) / tppg, "minutes": c["min"]} for pid, c in top], len(games)


_CACHE: dict = {}


def _sig(rows: list[dict]):
    return (len(rows), rows[-1].get("game_id") if rows else None, rows[0].get("game_id") if rows else None)


def cached_top(rows: list[dict], abbr: str, before_day: str | None, candidates: set | None) -> tuple[list[dict], int]:
    """top_players mit Zwischenspeicher (gleiche Zeilen, gleiches Team, gleicher Tag, gleicher Kader -> gleiches Ergebnis); die App ruft das bei jedem Neuaufbau je Karte auf."""
    key = (_sig(rows), abbr, before_day, None if candidates is None else frozenset(candidates))
    hit = _CACHE.get(key)
    if hit is None:
        if len(_CACHE) > 400:
            _CACHE.clear()
        hit = _CACHE[key] = top_players(rows, abbr, before_day, candidates)
    return hit


def team_games_before(rows: list[dict], abbr: str, day: str) -> int:
    return len({r["game_id"] for r in rows if r.get("team") == abbr and str(r.get("date")) < day})


def prev_season(season: str) -> str:
    """'2026-27' -> '2025-26'."""
    y = int(season[:4]) - 1
    return f"{y}-{str(y + 1)[2:]}"


def team_measure(top: list[dict], out_ids: set) -> tuple[float, list[dict]]:
    """Mass und die zaehlenden Spieler (fehlende Spieler aus den Top 8)."""
    miss = [{"person_id": p["person_id"], "name": p["name"], "share": round(p["share"], 4)} for p in top if int(p["person_id"]) in out_ids]
    return round(sum(m["share"] for m in miss), 4), miss


def compute(home_abbr: str, away_abbr: str, day: str, out_home: set, out_away: set, rows_cur: list[dict], rows_prev: list[dict],
            roster_home: set | None, roster_away: set | None) -> dict:
    """Ausfall-Mass beider Teams mit EINER Basis fuer das Spiel. out_*: person_ids mit Status 'fehlt'. roster_*: person_ids im aktuellen Kader (nur fuer die Vorjahres-Basis)."""
    n_home, n_away = team_games_before(rows_cur, home_abbr, day), team_games_before(rows_cur, away_abbr, day)
    cur = min(n_home, n_away) >= MIN_TEAM_GAMES
    if cur:
        th, _ = cached_top(rows_cur, home_abbr, day, None)
        ta, _ = cached_top(rows_cur, away_abbr, day, None)
    else:
        th, _ = cached_top(rows_prev, home_abbr, None, roster_home)
        ta, _ = cached_top(rows_prev, away_abbr, None, roster_away)
    mh, miss_h = team_measure(th, out_home)
    ma, miss_a = team_measure(ta, out_away)
    return {"version": TEAM_MODEL_VERSION, "base": BASE_CUR if cur else BASE_PREV, "games_home": n_home, "games_away": n_away,
            "measure_home": mh, "measure_away": ma, "missing_home": miss_h, "missing_away": miss_a}


def apply(proj: dict, info: dict) -> dict:
    """Ergaenzt info um die korrigierten Werte: delta_spread, exp_spread, home_score, away_score, home_win_prob, away_win_prob, pp_shift (Siegchance Heim, Prozentpunkte), active (Mass != 0 bei mindestens
    einem Team = Schalter anzeigen). Das Total (exp_total) bleibt gleich. Aendert proj nicht."""
    delta = FACTOR * SLOPE * (info["measure_home"] - info["measure_away"])
    spread2 = round(float(proj["exp_spread"]) + delta, 1)
    total = int(proj["home_score"]) + int(proj["away_score"])
    home2 = int(math.floor(int(proj["home_score"]) + delta / 2 + 0.5)) if delta else int(proj["home_score"])
    p2 = round(lp.win_prob_home(spread2), 4)
    out = dict(info)
    out.update(delta_spread=round(delta, 2), exp_spread=spread2, home_score=home2, away_score=total - home2, exp_total=proj["exp_total"],
               home_win_prob=p2, away_win_prob=round(1.0 - p2, 4), pp_shift=round((p2 - float(proj["home_win_prob"])) * 100, 1),
               active=bool(info["measure_home"] or info["measure_away"]))
    return out


def variant_proj(proj: dict, t2: dict) -> dict:
    """Projektion mit den team-2-Werten (Spread, Punkte, Siegchance); alles andere, auch das Total, wie in proj."""
    return {**proj, "exp_spread": t2["exp_spread"], "home_score": t2["home_score"], "away_score": t2["away_score"], "home_win_prob": t2["home_win_prob"], "away_win_prob": t2["away_win_prob"]}


def note_text(proj: dict, t2: dict, nick_home: str, nick_away: str) -> str | None:
    """'Ausfall: +4 PP fuer Wizards' wenn sich die Siegchance durch team-2 um mehr als PP_NOTE Prozentpunkte verschiebt, sonst None."""
    pp = t2["pp_shift"]
    if abs(pp) <= PP_NOTE:
        return None
    return f"Ausfall: +{abs(pp):.0f} PP für {nick_home if pp > 0 else nick_away}"


# ----------------------------------------------------------------------------- Anbindung an die Daten (Spielerverlauf, Kader, Ausfaelle)
def attach(proj: dict, game_key: str, season_rows_fn=None, rosters_info: dict | None = None, absences: dict | None = None) -> None:
    """Haengt proj['team2'] an (oder entfernt es bei Fehlern). Nutzt nur lokale Daten: Ausfaelle (data/absences_store.get), Kader (data/rosters), Spielerverlauf (data/player_history).
    Ein Fehler hier darf die Karte nie stoeren: dann ohne team2."""
    try:
        from data import absences_store as ab
        from data import player_history as ph
        from data import rosters
        from ui.score_cards import team_info          # Kuerzel zum Teamnamen (gleiche Tabelle wie die Karte)
        day = str(proj.get("game_date") or game_key.split("|", 1)[0])
        home, away = proj["home_team"], proj["away_team"]
        ha, aa = team_info(home)["abbr"], team_info(away)["abbr"]
        out = (absences if absences is not None else ab.get(game_key)).get("out", {})
        out_h = {int(pid) for pid, v in out.items() if team_info(v.get("team") or "")["abbr"] == ha}
        out_a = {int(pid) for pid, v in out.items() if team_info(v.get("team") or "")["abbr"] == aa}
        info_r = rosters_info if rosters_info is not None else rosters.load()
        ros = lambda name: {int(p["person_id"]) for p in (info_r.get("teams") or {}).get(name, [])} or None
        season = ph.current_season()
        cur = (season_rows_fn or ph.season_rows)(season)
        pf = ph.league_file(prev_season(season))
        prev = pf["rows"] if pf else []
        info = compute(ha, aa, day, out_h, out_a, cur, prev, ros(home), ros(away))
        proj["team2"] = apply(proj, info)
    except Exception:
        proj.pop("team2", None)
