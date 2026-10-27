"""
Adapter fuer den Spieler-Backtest (Walk-forward): ruft die Bausteine von engine/player_forecast.py (forecast_player, team_match) mit HISTORISCHEN Eingaben auf, ohne Produktivcode zu aendern.
NUR LESEND, kein Netz. Das Produktivmodell bleibt unveraendert: team_match liest den heutigen Kader (rosters.load) und die Verlaeufe (ph.get_player_games) und braucht league_ppm; diese drei
Zugriffe werden hier zur LAUFZEIT durch die historischen Quellen ersetzt (Monkeypatch im Prozess des Backtests, keine Datei wird geaendert). Rotation, Minutenverteilung, Starter-Obergrenze,
Faktor f, Blowout-Kurve usw. bleiben die Regeln von engine/player_forecast.py.

Regeln des Adapters
- Fuer Spieltag D sieht der Adapter NUR Spielerzeilen mit Datum < D. Jede an forecast_player uebergebene Zeile wird per Assertion auf Datum < D geprueft (Zaehler: checked_rows).
- Verlauf = laufende Saison + Vorsaison (wie das Produktivmodell mit zwei Saisons; game_weights kennt "laufende Saison" und "Vorsaison").
- Kader eines Teams an Tag D = Spieler, die in den letzten ROSTER_GAMES Spielen des Teams (vor D, laufende Saison + Vorsaison) gespielt haben (Minuten > 0) UND deren letzte Zeile vor D zu diesem
  Team gehoert (Transfers werden so erfasst). Offseason-Wechsel ohne Spiel sind unbekannt: am Saisonanfang gilt der Kader vom Saisonende.
- league_ppm: Standard = Produktivwert (Liga-Schnitt Punkte/Minute 2025-26, also fuer 2025-26 "in-sample", fuer 2024-25 "aus der Zukunft"); mit causal=True nur Zeilen vor D (laufende Saison + Vorsaison).
Selbsttest: venv/bin/python analysis/bt_player_adapter.py --selftest
"""
import sys
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from data import player_history as ph  # noqa: E402
from data import rosters  # noqa: E402
from engine import player_forecast as pf  # noqa: E402

ROSTER_GAMES = 10
MAX_N = pf.MAX_N
ORIG_FORECAST = pf.forecast_player                 # Original, bevor der Adapter es umleitet
ORIG_LEAGUE_PPM = pf.league_ppm
ORIG_ROSTERS_LOAD = rosters.load


def prev_season(season: str) -> str:
    y = int(season[:4]) - 1
    return f"{y}-{(y + 1) % 100:02d}"


class HistoryStore:
    """Alle Spielerzeilen (Liste von Dicts im Format der player_games-Dateien), chronologisch geordnet, mit schnellem Zugriff 'vor Tag D'."""

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: (r["date"], r["game_id"], r["person_id"]))
        self.by_player = defaultdict(list)
        for r in self.rows:
            self.by_player[r["person_id"]].append(r)
        self.dates = {pid: [r["date"] for r in lst] for pid, lst in self.by_player.items()}
        tg = defaultdict(lambda: defaultdict(list))
        for r in self.rows:
            if r["minutes"] > 0:
                tg[r["team"]][(r["date"], r["game_id"])].append(r["person_id"])
        self.team_games = {t: sorted((d, g, tuple(p)) for (d, g), p in v.items()) for t, v in tg.items()}
        self.team_dates = {t: [x[0] for x in v] for t, v in self.team_games.items()}
        self.ppm_cum = {}
        by_season = defaultdict(list)
        for r in self.rows:
            by_season[r["season"]].append(r)
        for s, lst in by_season.items():
            dates = [r["date"] for r in lst]
            cp = np.concatenate([[0.0], np.cumsum([r["points"] for r in lst])])
            cm = np.concatenate([[0.0], np.cumsum([r["minutes"] for r in lst])])
            self.ppm_cum[s] = (dates, cp, cm)
        self._season_cache = {}

    def season_of(self, day: str) -> str:
        if day not in self._season_cache:
            self._season_cache[day] = ph.season_of_date(day)
        return self._season_cache[day]

    def history(self, pid: int, day: str) -> list[dict]:
        """Zeilen des Spielers mit Datum < day aus laufender Saison und Vorsaison."""
        lst = self.by_player.get(int(pid))
        if not lst:
            return []
        j = bisect_left(self.dates[int(pid)], day)
        cur = self.season_of(day)
        keep = (cur, prev_season(cur))
        return [r for r in lst[:j] if r["season"] in keep]

    def roster(self, team: str, day: str) -> list[int]:
        """Kader-Kandidaten des Teams an Tag day (siehe Modulkopf)."""
        tg = self.team_games.get(team)
        if not tg:
            return []
        j = bisect_left(self.team_dates[team], day)
        cur = self.season_of(day)
        keep = (cur, prev_season(cur))
        pids, seen_games = [], 0
        for d, gid, ps in reversed(tg[:j]):
            if self.season_of(d) not in keep:
                break
            for p in ps:
                if p not in pids:
                    pids.append(p)
            seen_games += 1
            if seen_games >= ROSTER_GAMES:
                break
        out = []
        for p in pids:
            lst = self.by_player[p]
            k = bisect_left(self.dates[p], day) - 1
            if k >= 0 and lst[k]["team"] == team:
                out.append(p)
        return out

    def names(self, pid: int) -> str:
        return self.by_player[int(pid)][-1]["name"]

    def ppm_before(self, day: str) -> float | None:
        """Liga-Schnitt Punkte/Minute aus allen Zeilen vor day (laufende Saison + Vorsaison)."""
        cur = self.season_of(day)
        pts = mins = 0.0
        for s in (cur, prev_season(cur)):
            if s in self.ppm_cum:
                dates, cp, cm = self.ppm_cum[s]
                j = bisect_left(dates, day)
                pts += cp[j]; mins += cm[j]
        return pts / mins if mins > 0 else None


class Adapter:
    """Installiert die historischen Quellen und liefert je Spiel die Prognosen der Varianten A (roh), B (Teamabgleich, Ausfaelle unbekannt), C (Teamabgleich, Ausfaelle bekannt = Obergrenze)."""

    def __init__(self, store: HistoryStore, league_ppm_causal: bool = False):
        self.store = store
        self.causal = league_ppm_causal
        self.prod_ppm = ORIG_LEAGUE_PPM()                       # Produktivwert (liest die Produktivdatei player_games_2025-26.json nur lesend)
        self.state = {"day": None, "roster": {}, "ppm": self.prod_ppm}
        self.checked_rows = 0
        self.calls = 0
        self.max_date_seen = ""
        self._install()

    # -- Umleitung der drei Zugriffe von engine/player_forecast.team_match (nur im Prozess)
    def _install(self):
        me = self

        def hist_forecast(person_id, before_date, home=None, exp_spread=None, exp_total=None, games=None, name=None, minutes_mean_override=None, points_scale=1.0):
            day = str(before_date)[:10]
            rows = me.store.history(person_id, day)
            assert all(r["date"] < day for r in rows), f"Zeile ab Spieltag {day} im Verlauf von {person_id}"      # Selbstkontrolle: nur die Vergangenheit
            me.checked_rows += len(rows)
            me.calls += 1
            if rows:
                me.max_date_seen = max(me.max_date_seen, rows[-1]["date"]) if rows[-1]["date"] < day else (_ for _ in ()).throw(AssertionError("Zukunft"))
            return ORIG_FORECAST(person_id, before_date, home=home, exp_spread=exp_spread, exp_total=exp_total, games=rows, name=name,
                                 minutes_mean_override=minutes_mean_override, points_scale=points_scale)

        pf.forecast_player = hist_forecast
        pf.league_ppm = lambda: me.state["ppm"]
        rosters.load = lambda now=None: {"status": "ok", "teams": me.state["roster"]}
        self.forecast_player = hist_forecast

    def set_day(self, day: str, teams: tuple):
        """Kader der beiden Teams und league_ppm fuer den Tag setzen."""
        self.state["day"] = day
        self.state["roster"] = {t: [{"person_id": p, "name": self.store.names(p)} for p in self.store.roster(t, day)] for t in teams}
        if self.causal:
            ppm = self.store.ppm_before(day)
            self.state["ppm"] = ppm if ppm is not None else self.prod_ppm
        else:
            self.state["ppm"] = self.prod_ppm

    def team_variants(self, team: str, is_home: bool, ctx: dict, day: str, played: set):
        """B und C fuer ein Team. played = person_ids mit Minuten > 0 im Spiel (nur fuer Variante C genutzt). Rueckgabe (B, C, absent_ids)."""
        B = pf.team_match(team, is_home, ctx, day, None, None)
        absent = {p for p, rank in B["rank"].items() if rank <= pf.ROTATION_SIZE and p not in played}
        C = pf.team_match(team, is_home, ctx, day, None, absent) if absent else B
        return B, C, absent

    def forecast_team(self, team: str, is_home: bool, ctx: dict, day: str, played_rows: list[dict]) -> tuple[list[dict], dict]:
        """Prognosen aller Spieler des Teams, die im Spiel gespielt haben (Minuten > 0). Rueckgabe (Liste von Datensaetzen, Kennzahlen)."""
        played = {r["person_id"] for r in played_rows}
        B, C, absent = self.team_variants(team, is_home, ctx, day, played)
        out, skipped = [], 0
        for r in played_rows:
            pid = r["person_id"]
            raw = B["raw"].get(pid)
            if raw is None:
                raw = self.forecast_player(pid, day, home=is_home, exp_spread=ctx["exp_spread"], exp_total=ctx.get("exp_total"), name=r["name"])
            if not raw["ok"]:
                skipped += 1
                continue
            adjB = B["adjusted"].get(pid)
            adjC = C["adjusted"].get(pid)
            rawC = C["raw"].get(pid) or raw
            var = {"A": raw, "B": adjB or raw, "C": adjC or rawC}
            out.append({"person_id": pid, "row": r, "variants": var, "in_rot_B": adjB is not None, "in_rot_C": adjC is not None, "rank_B": B["rank"].get(pid)})
        info = {"roster": len(self.state["roster"].get(team, [])), "rotation_B": len(B["info"]["rotation"]), "absent": len(absent), "matched_B": bool(B["info"]["matched"]), "matched_C": bool(C["info"]["matched"]),
                "factor_B": B["info"]["factor_applied"], "factor_C": C["info"]["factor_applied"], "skipped": skipped}
        return out, info


def p_array(fc: dict) -> np.ndarray:
    return np.array([fc["p_ge"][k] for k in range(1, MAX_N + 1)], float)


def exp_values(fc: dict) -> tuple[float, float]:
    """(erwartete Minuten, erwartete Punkte) der Prognose: mit Teamabgleich die angepassten Werte, sonst roh."""
    if "minutes_mean_adj" in fc:
        return fc["minutes_mean_adj"], fc["expected_points"]
    return fc["minutes"]["mean"], fc["expected_points"]


# ----------------------------------------------------------------------------------------------- Selbsttest
def _fake_rows(seed=1):
    rng = np.random.default_rng(seed)
    teams = ["AAA", "BBB", "CCC", "DDD"]
    rows, gid = [], 0
    days = []
    for season, start in (("2023-24", "2023-11-"), ("2024-25", "2024-11-")):
        for d in range(1, 29):
            days.append((season, f"{start}{d:02d}"))
    roster = {t: [(1000 * (i + 1) + j, f"P{i}{j}") for j in range(9)] for i, t in enumerate(teams)}
    for season, day in days:
        for a, b in (("AAA", "BBB"), ("CCC", "DDD")) if int(day[-2:]) % 2 else (("AAA", "CCC"), ("BBB", "DDD")):
            gid += 1
            for team, opp, home in ((a, b, True), (b, a, False)):
                for k, (pid, name) in enumerate(roster[team]):
                    mins = float(max(0, rng.normal(32 - 3 * k, 3)))
                    rows.append({"game_id": f"g{gid}", "date": day, "season": season, "person_id": pid, "name": name, "team": team, "opponent": opp, "home": home, "minutes": mins,
                                 "points": int(max(0, rng.normal(0.5 * mins, 3))), "fga": 0, "fgm": 0, "fta": 0, "ftm": 0, "fg3a": 0, "fg3m": 0, "fouls": 2, "plus_minus": 0, "win": True, "margin": 0, "source": "league"})
    return rows


def selftest() -> int:
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    rows = _fake_rows()
    store = HistoryStore(rows)
    day = "2024-11-15"
    check("Verlauf nur vor dem Spieltag, nur laufende Saison + Vorsaison", all(r["date"] < day for r in store.history(1000, day)) and {r["season"] for r in store.history(1000, day)} <= {"2024-25", "2023-24"})
    check("Verlauf enthaelt keinen Spieltag D selbst und keine Zukunft", all(r["date"] != day for r in store.history(1000, day)) and len(store.history(1000, "2023-11-01")) == 0)
    ad = Adapter(store)
    ctx = {"found": True, "exp_spread": 3.0, "exp_total": 224.0, "home_score": 113.5, "away_score": 110.5}
    ad.set_day(day, ("AAA", "BBB"))
    played = [r for r in rows if r["date"] == day and r["team"] == "AAA"][:8]
    out1, info1 = ad.forecast_team("AAA", True, ctx, day, played)
    # Zukunft veraendern (Zeilen ab Spieltag D): Prognose muss identisch bleiben
    rows2 = [dict(r, points=r["points"] + 40, minutes=r["minutes"] + 5) if r["date"] >= day else dict(r) for r in rows]
    store2 = HistoryStore(rows2)
    ad2 = Adapter(store2)
    ad2.set_day(day, ("AAA", "BBB"))
    out2, info2 = ad2.forecast_team("AAA", True, ctx, day, played)
    same = all(np.allclose(p_array(a["variants"][v]), p_array(b["variants"][v])) for a, b in zip(out1, out2) for v in "ABC")
    check("Zukunft (Zeilen ab D) veraendert keine Prognose (A, B, C)", same and len(out1) == len(out2) > 0, len(out1))
    check("Selbstkontrolle zaehlt Zeilen und alle haben Datum < D", ad.checked_rows > 0 and ad.max_date_seen < day, (ad.checked_rows, ad.max_date_seen))
    try:
        ad = Adapter(store)                                              # pf.forecast_player zeigt immer auf den zuletzt installierten Adapter
        pf.forecast_player(1000, day, home=True, exp_spread=0.0)       # normaler Aufruf geht
        broken = HistoryStore(rows)
        broken.history = lambda pid, d: [dict(rows[-1])]               # Verlauf mit Zukunftszeile einschleusen
        ad.store = broken
        raised = False
        try:
            pf.forecast_player(1000, "2023-11-02", home=True, exp_spread=0.0)
        except AssertionError:
            raised = True
        ad.store = store
        check("Assertion schlaegt bei einer Zeile ab Spieltag D an", raised)
    except Exception as e:
        check("Assertion-Test lief", False, repr(e))
    # Adapter gegen direkten Aufruf mit unabhaengig (brute force) gefilterten Eingaben
    pid = 1002
    brute = [r for r in rows if r["person_id"] == pid and r["date"] < day and r["season"] in ("2024-25", "2023-24")]
    direct = ORIG_FORECAST(pid, day, home=True, exp_spread=3.0, exp_total=224.0, games=brute, name="x")
    via = ad.forecast_player(pid, day, home=True, exp_spread=3.0, exp_total=224.0, name="x")
    check("Adapter = direkter Aufruf von forecast_player mit denselben historischen Eingaben (identisch)", direct["ok"] and np.array_equal(p_array(direct), p_array(via)) and direct["expected_points"] == via["expected_points"])
    # Kader: Transfer
    rows3 = [dict(r) for r in rows]
    for r in rows3:
        if r["person_id"] == 1000 and r["date"] >= "2024-11-10":
            r["team"] = "BBB"
    st3 = HistoryStore(rows3)
    check("Transfer: Spieler mit letzter Zeile bei BBB steht im Kader von BBB, nicht mehr von AAA", 1000 in st3.roster("BBB", "2024-11-20") and 1000 not in st3.roster("AAA", "2024-11-20"))
    check("Kader: nur Spieler der letzten Teamspiele, Vorsaison am Saisonanfang als Rueckgriff", len(store.roster("AAA", "2024-11-15")) == 9 and len(store.roster("AAA", "2024-11-01")) >= 1)
    # league_ppm kausal
    adc = Adapter(store, league_ppm_causal=True)
    adc.set_day("2024-11-15", ("AAA",))
    manual = [r for r in rows if r["date"] < "2024-11-15" and r["season"] in ("2024-25", "2023-24")]
    check("league_ppm kausal = Schnitt der Zeilen vor D (laufende Saison + Vorsaison)", abs(adc.state["ppm"] - sum(r["points"] for r in manual) / sum(r["minutes"] for r in manual)) < 1e-12 and adc.state["ppm"] != adc.prod_ppm)
    ad.set_day("2024-11-15", ("AAA",))
    check("Standard: league_ppm = Produktivwert", ad.state["ppm"] == ad.prod_ppm)
    print("\nADAPTER-SELBSTTEST BESTANDEN" if ok else "\nADAPTER-SELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
