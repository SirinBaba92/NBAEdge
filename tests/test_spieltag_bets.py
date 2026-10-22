"""Tests fuer den Bereich "Wetten eintragen" im Tab "🏀 Spieltag" (Baustein 6): ui/bet_entry.py, Einbindung in ui/live_tab.py.
AppTest mit Attrappen (tests/fake_net.py), Temp-Ordner fuer day_bets.json, Schnappschuesse und Betano-Eingaben, kein Netz, nie die echte day_bets.json, keine Browsertests.
Aufruf aus dem Projektordner: venv/bin/python tests/test_spieltag_bets.py"""
import hashlib, inspect, json, os, re, sys, time, warnings
from pathlib import Path
from statistics import NormalDist
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state as FN, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
from data import day_bets_store as ds
from data import live_feed as lf
from data import market_lines
from data import pre_match_store as ps
from data import projection_snapshots as snap
import ui.bet_entry as be
import ui.live_tab as lt
from ui.score_cards import fmt_num

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

real_tracking = {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in (ROOT / "data" / "tracking").glob("*.json")}
real_now = time.time()
DAY = lf.current_us_day(real_now)
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
NOW = [real_now]
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)

def row(gid, home, away, status, period, clock, text, hs, as_, start):
    hc, hn = home.rsplit(" ", 1); ac, an = away.rsplit(" ", 1)
    return {"gameId": gid, "gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock, "gameEt": f"{DAY}T19:00:00-04:00", "gameTimeUTC": start,
            "homeTeam": {"teamCity": hc, "teamName": hn, "teamTricode": "H", "score": hs, "periods": []}, "awayTeam": {"teamCity": ac, "teamName": an, "teamTricode": "A", "score": as_, "periods": []}}
def box():
    s = {"fieldGoalsAttempted": 60, "freeThrowsAttempted": 20, "reboundsOffensive": 8, "turnoversTotal": 10}
    return {"homeTeam": {"statistics": dict(s)}, "awayTeam": {"statistics": dict(s)}}

LINE_AT = "2026-10-22T16:27:00+02:00"
def version(total=230.0, spread=8.1, home=119.0, away=111.0):
    p = round(NormalDist().cdf(spread / 13.2), 4)
    mk = lambda line: {"line": line, "source": "eigene Eingabe", "bookmaker": "Betano", "line_at": LINE_AT}
    return {"saved_at": "x", "hash": "h", "projection": {"exp_total": total, "exp_spread": spread, "home_score": home, "away_score": away, "home_win_prob": p},
            "markets": {"spread": mk(4.5), "total": mk(231.5), "team_total_home": mk(118.5), "team_total_away": mk(113.5)},
            "sigmas": {"spread": 13.2, "total": 18.6, "team_total": 11.6}, "sigmas_version": "2"}
def mkline(i, line, over=None, under=None, role="main"):
    return {"id": i, "role": role, "active": True, "line": line, "over_odds": over, "under_odds": under, "bookmaker": "Betano", "updated_at": LINE_AT}
def betano_entry(start, home, away):
    return {"game_date": DAY, "start_utc": start, "home": home, "away": away, "markets": {
        "winner_incl_ot": {"home_odds": 1.55, "away_odds": 2.5, "bookmaker": "Betano", "updated_at": LINE_AT},
        "spread": {"lines": [{"id": "main", "role": "main", "active": True, "line_home": -4.5, "line_away": 4.5, "home_odds": 1.91, "away_odds": 1.89, "bookmaker": "Betano", "updated_at": LINE_AT},
                             {"id": "x1", "role": "extra", "active": True, "line_home": -3.5, "line_away": 3.5, "home_odds": 1.75, "away_odds": 2.05, "bookmaker": "Betano", "updated_at": LINE_AT}]},
        "total": {"lines": [mkline("main", 231.5, 1.9, 1.92), mkline("x1", 232.5, 2.0, 1.8, "extra")]},
        "team_totals": {"home": {"lines": [mkline("main", 118.5, 1.85, 1.95)]}, "away": {"lines": [mkline("main", 113.5, 1.8, 2.0)]}}}}

S1, S2, S3 = iso(real_now + 3 * 3600), iso(real_now + 4 * 3600), iso(real_now - 3600)
GAMES = {"E1": {"home": "Philadelphia 76ers", "away": "Cleveland Cavaliers", "start": S1}, "E2": {"home": "Boston Celtics", "away": "Miami Heat", "start": S2},
         "E3": {"home": "Oklahoma City Thunder", "away": "Denver Nuggets", "start": S3}}
def setup(extra_rows=(), games=("E1", "E2", "E3"), snaps_for=("E1",), entry_for=("E1",)):
    fresh_env()
    rows = []
    if "E1" in games: rows.append(row("E1", GAMES["E1"]["home"], GAMES["E1"]["away"], 1, 0, "", "7:00 pm ET", 0, 0, S1))
    if "E2" in games: rows.append(row("E2", GAMES["E2"]["home"], GAMES["E2"]["away"], 1, 0, "", "8:00 pm ET", 0, 0, S2))
    if "E3" in games: rows.append(row("E3", GAMES["E3"]["home"], GAMES["E3"]["away"], 2, 3, "PT06M00.00S", "", 85, 60, S3))
    FN["scoreboard"], FN["boxes"], FN["board_date"] = rows + list(extra_rows), {"E3": box()}, DAY
    ent = {"version": 5, "format": "nbaedge-pre-match-entries", "entries": {}}
    sn = {"version": 1, "format": "nbaedge-projection-snapshots", "updated_at": None, "games": {}}
    for g in snaps_for:
        G = GAMES[g]
        sn["games"][ps.game_key(DAY, G["start"], G["home"], G["away"])] = {"game_date": DAY, "start_utc": G["start"], "home": G["home"], "away": G["away"], "versions": [version()], "card": None, "result": None}
    for g in entry_for:
        G = GAMES[g]
        ent["entries"][ps.game_key(DAY, G["start"], G["home"], G["away"])] = betano_entry(G["start"], G["home"], G["away"])
    ps.store_path().parent.mkdir(parents=True, exist_ok=True)
    ps.store_path().write_text(json.dumps(ent)); snap.snapshot_path().write_text(json.dumps(sn)); snap._cache.update(sig=None, data=None)
    NOW[0] = real_now
    lf._feed = lf.LiveFeed(now=lambda: NOW[0])
def bets(g, removed=False):
    G = GAMES[g]
    return ds.get_bets(DAY, G["start"], G["home"], G["away"], include_removed=removed)
def tok(g, m): return be._token(bets(g, True).get(m))
def K(g, m, suffix): return f"be_{g}_{m}_{tok(g, m)}_{suffix}"
def tab_idx(at): return [t.label for t in at.tabs].index("🏀 Spieltag")
def tab_md(at): return " ".join(m.value for m in at.tabs[tab_idx(at)].markdown)
def card(at, gid):
    c = [m.value for m in at.tabs[tab_idx(at)].markdown if f'data-game="{gid}"' in m.value]
    return c[0] if c else ""
def expander(at): return [e for e in at.expander if e.label == "Wetten eintragen"][0]
def keys(at, kind): return [w.key for w in getattr(at, kind) if w.key and w.key.startswith("be_")]
def counters(): return (FN["nba_calls"], len(FN["odds_calls"]), FN["bdl_calls"], FN["espn_calls"])
def select(at, key, value): at.selectbox(key=key).set_value(value).run(); return at
def captions(at): return " | ".join(c.value for c in at.caption)
def ok_msg(at): return " ".join(m.value for m in at.success)
def err_msg(at): return " ".join(m.value for m in at.error)
def walk(node):
    for ch in node.children.values():
        yield ch
        if hasattr(ch, "children"):
            yield from walk(ch)

# ================================================================= A) Bereich, Spielauswahl, Zeilen je Markt
setup()
at = app().run()
check("Start der Seite mit dem neuen Bereich: keine Exception, keine Warnung", not problems(at), " | ".join(problems(at))[:200])
check("Bereich 'Wetten eintragen' vorhanden, aufgeklappt (noch keine Wetten gespeichert)", expander(at).proto.expanded is True)
order = [("exp" if type(n).__name__ == "Expander" else "md:" + ("ov" if "lv-overview" in getattr(n, "value", "") else "card" if 'data-game="' in getattr(n, "value", "") else "sum" if "lv-sum" in getattr(n, "value", "") else "")) for n in walk(at.tabs[tab_idx(at)])
         if type(n).__name__ in ("Expander", "Markdown") and (type(n).__name__ == "Expander" and n.label == "Wetten eintragen" or "lv-overview" in getattr(n, "value", "") or 'data-game="' in getattr(n, "value", "") or "lv-sum" in getattr(n, "value", ""))]
check("Platz: unter der Tagesuebersicht und den Wetten-Zahlen, ueber den Karten", order and order.index("exp") > order.index("md:ov") and order.index("exp") < order.index("md:card"), str(order))
src_tab = inspect.getsource(lt.render_spieltag_tab)
check("Bereich steht AUSSERHALB der Fragmente: Aufruf zwischen _live_head und _live_cards, nicht in deren Quelltext", src_tab.index("_live_head(auto)") < src_tab.index("render_bet_entry()") < src_tab.index("_live_cards(auto)")
      and "render_bet_entry" not in inspect.getsource(lt._live_head) and "render_bet_entry" not in inspect.getsource(lt._live_cards))
sel = at.selectbox(key="be_game")
check("Spielauswahl: alle Spiele des Spieltags, Standard = erstes noch nicht angepfiffenes Spiel (E1), angepfiffenes (E3) gesperrt gekennzeichnet", sel.value == "E1" and len(sel.options) == 3
      and sum("🔒 Wette ab Anpfiff gesperrt" in o for o in sel.options) == 1 and "🔒 Wette ab Anpfiff gesperrt" in [o for o in sel.options if "Nuggets @ Thunder" in o][0] and all("Uhr" in o for o in sel.options), str(sel.options))
mk_sel = [at.selectbox(key=f"be_E1_{m}_neu_side") for m in ds.MARKETS]
check("je Markt eine Zeile: Sieger, Spread, Total, Team Total Heim, Team Total Gast; Standard 'keine Wette', Pro Markt nur eine Seite", [s.value for s in mk_sel] == ["none"] * 5 and keys(at, "selectbox") == ["be_game"] + [f"be_E1_{m}_neu_side" for m in ds.MARKETS])
check("Seiten: Sieger/Spread Heim oder Gast, Total/Team Totals Over oder Under (jeweils plus 'keine Wette')", mk_sel[0].options == ["keine Wette", "76ers (Heim)", "Cavaliers (Gast)"] and mk_sel[1].options == ["keine Wette", "76ers (Heim)", "Cavaliers (Gast)"]
      and all(s.options == ["keine Wette", "Over", "Under"] for s in mk_sel[2:]))
check("ohne gewaehlte Seite keine Linien-, Quote- oder Einsatzfelder und keine Knoepfe", keys(at, "text_input") == [] and keys(at, "number_input") == [] and keys(at, "button") == [])
check("noch nichts gespeichert, keine Datei angelegt", not ds.store_path().exists())

# ================= Sieger: Quote aus der Betano-Eingabe vorbelegt, speichern
c0 = counters()
select(at, "be_E1_winner_neu_side", "home")
check("Sieger Heim gewaehlt: Quote vorbelegt aus der gespeicherten Betano-Eingabe (1,55) mit Quelle 'Betano, Stand 16:27'", at.text_input(key="be_E1_winner_neu_odds_home_w").value == "1,55" and "vorbelegt aus Betano, Stand 16:27" in captions(at))
check("Einsatz: Zahleneingabe, leer", at.number_input(key="be_E1_winner_neu_stake").value is None and "be_E1_winner_neu_save" in keys(at, "button"))
at.button(key="be_E1_winner_neu_save").click().run()
b = bets("E1")["winner"]
check("Speichern: Sieger Heim, Quote 1,55 (Quelle gespeichert), kein Einsatz, keine Linie; Bestaetigung mit dem gespeicherten Stand", b["side"] == "home" and b["odds"] == 1.55 and b["odds_source"] == "gespeichert" and b["stake"] is None and b["line"] is None and b["line_ref"] is None
      and "Gespeichert: Sieger: 76ers gewinnt · Quote 1,55 (gespeichert) · Einsatz —" in ok_msg(at) and not problems(at), ok_msg(at))
check("Eintragen loest keine Abrufe aus: kein NBA.com-, Odds-API-, BallDontLie- oder ESPN-Abruf, keine Credits", counters() == c0, f"{c0} -> {counters()}")
H = tab_md(at); ce = card(at, "E1")
check("Karte und Tagesuebersicht zeigen die Wette sofort (naechster Lauf, ohne Abruf): Marker, Wett-Zeile 'Sieger: 76ers gewinnt', Status 'Wartet auf Anpfiff'", "🎯 1 Wette" in ce and "Sieger: 76ers gewinnt" in ce and "Wartet auf Anpfiff" in ce and re.search(r'lv-oteams">Cavaliers @ 76ers</span>.*?🎯 1<', H)
      and re.search(r'<div class="pc-label">WETTEN</div><div class="lv-val ">1</div>', H) is not None)
check("nach dem Speichern: Feld-Schluessel neu belegt aus dem Speicher (Seite Heim vorausgewaehlt, Quote 1,55)", at.selectbox(key=K("E1", "winner", "side")).value == "home" and at.text_input(key=K("E1", "winner", "odds_home_w")).value == "1,55")

# ================= Total: Hauptlinie ist Standard, Quote je Seite, andere Linie mit line_ref
select(at, "be_E1_total_neu_side", "over")
ls = at.selectbox(key="be_E1_total_neu_line_over")
exp_opts = [fmt_num(226.5 + i) + (" (Hauptlinie)" if abs(226.5 + i - 231.5) < 1e-9 else "") for i in range(11)]
check("Total Over: Linie = Hauptlinie 231,5 (Standard), Auswahl Hauptlinie +- 5 in Schritten von 1, alle .5, Hauptlinie gekennzeichnet", ls.value == 231.5 and ls.options == exp_opts, str(ls.options))
check("Quote zur Seite/Linie vorbelegt: Over 231,5 = 1,90", at.text_input(key="be_E1_total_neu_odds_over_231.5").value == "1,90")
at.button(key="be_E1_total_neu_save").click().run()
b = bets("E1")["total"]
check("gespeichert mit der Hauptlinie: line 231,5, side over, Quote 1,90 (gespeichert)", b["line"] == 231.5 and b["side"] == "over" and b["odds"] == 1.9 and b["odds_source"] == "gespeichert")
check("line_ref: Hauptlinie 231,5, gewaehlte Linie 231,5, is_main, Quelle 'eigene Eingabe', Buchmacher Betano, Zeit der Linie", b["line_ref"] == {"main_line": 231.5, "chosen_line": 231.5, "is_main": True, "source": "eigene Eingabe", "bookmaker": "Betano", "at": LINE_AT}, str(b["line_ref"]))
# andere Linie waehlen (Under)
select(at, K("E1", "total", "side"), "under")
at.selectbox(key=K("E1", "total", "line_under")).set_value(233.5).run()
check("Under 233,5 gewaehlt: keine gespeicherte Quote fuer diese Seite/Linie, Hinweis, Feld leer", at.text_input(key=K("E1", "total", "odds_under_233.5")).value == "" and "Keine gespeicherte Quote" in captions(at))
at.selectbox(key=K("E1", "total", "line_under")).set_value(232.5).run()
check("Under 232,5 gewaehlt: Quote 1,80 aus der Betano-Zusatzlinie vorbelegt", at.text_input(key=K("E1", "total", "odds_under_232.5")).value == "1,80" and "vorbelegt aus Betano, Stand 16:27" in captions(at))
at.text_input(key=K("E1", "total", "odds_under_232.5")).input("1,85").run()
at.number_input(key=K("E1", "total", "stake")).set_value(12.5).run()
at.button(key=K("E1", "total", "save")).click().run()
b = bets("E1")["total"]
check("andere Linie wird gespeichert (232,5 Under, Quote 1,85 manuell ueberschrieben, Einsatz 12,50); line_ref: Hauptlinie 231,5 gegen gewaehlte 232,5, is_main False", b["line"] == 232.5 and b["side"] == "under" and b["odds"] == 1.85 and b["odds_source"] == "manuell" and b["stake"] == 12.5
      and b["line_ref"]["main_line"] == 231.5 and b["line_ref"]["chosen_line"] == 232.5 and b["line_ref"]["is_main"] is False)
check("Aendern: eine Wette je Markt, alter Stand (Over 231,5, Quote 1,90) als Revision erhalten, placed_at bleibt", len(b["revisions"]) == 1 and b["revisions"][0]["line"] == 231.5 and b["revisions"][0]["side"] == "over" and b["revisions"][0]["odds"] == 1.9 and b["revisions"][0]["reason"] == "geaendert"
      and b["placed_at"] != b["updated_at"] and len(bets("E1")) == 2)
check("Bestaetigung nennt den neuen Stand", "Gespeichert: Total: Under 232,5 · Quote 1,85 (manuell) · Einsatz 12,50" in ok_msg(at), ok_msg(at))
check("Bestaetigung erscheint nur einmal (naechster Lauf ohne Meldung)", (at.run(), ok_msg(at))[1].count("Gespeichert: Total") == 0)

# ================= Spread: Linie aus Sicht der gewaehlten Mannschaft
select(at, "be_E1_spread_neu_side", "home")
lh = at.selectbox(key="be_E1_spread_neu_line_home")
check("Spread Heim: Linie 76ers −4,5 (Hauptlinie, aus Sicht der gewaehlten Mannschaft), Auswahl −9,5 bis 0,5", lh.value == -4.5 and lh.options[0] == "76ers −9,5" and lh.options[-1] == "76ers +0,5" and "76ers −4,5 (Hauptlinie)" in lh.options and len(lh.options) == 11, str(lh.options))
check("Quote Spread Heim −4,5 vorbelegt (1,91)", at.text_input(key="be_E1_spread_neu_odds_home_-4.5").value == "1,91")
select(at, "be_E1_spread_neu_side", "away")
la = at.selectbox(key="be_E1_spread_neu_line_away")
check("Spread Gast: Linie Cavaliers +4,5 (Hauptlinie), Auswahl −0,5 bis +9,5", la.value == 4.5 and "Cavaliers +4,5 (Hauptlinie)" in la.options and la.options[0] == "Cavaliers −0,5" and la.options[-1] == "Cavaliers +9,5", str(la.options))
la.set_value(3.5).run()
check("Gast +3,5 entspricht Heim −3,5: Quote 2,05 vorbelegt (Betano-Zusatzlinie)", at.text_input(key="be_E1_spread_neu_odds_away_3.5").value == "2,05")
at.button(key="be_E1_spread_neu_save").click().run()
b = bets("E1")["spread"]
check("Spread gespeichert aus Sicht der Mannschaft (Gast +3,5), line_ref mit Hauptlinie aus Sicht der Seite (+4,5)", b["side"] == "away" and b["line"] == 3.5 and b["odds"] == 2.05 and b["line_ref"]["main_line"] == 4.5 and b["line_ref"]["chosen_line"] == 3.5 and b["line_ref"]["is_main"] is False)

# ================= Team Totals, Quote ueberschreiben und leeren
select(at, "be_E1_team_total_home_neu_side", "over")
check("Team Total Heim Over: Hauptlinie 118,5 (Standard), Quote 1,85 vorbelegt", at.selectbox(key="be_E1_team_total_home_neu_line_over").value == 118.5 and at.text_input(key="be_E1_team_total_home_neu_odds_over_118.5").value == "1,85")
at.text_input(key="be_E1_team_total_home_neu_odds_over_118.5").input("1,95").run()
at.button(key="be_E1_team_total_home_neu_save").click().run()
b = bets("E1")["team_total_home"]
check("Quote ueberschrieben (1,95): Quelle 'manuell', Linie Hauptlinie", b["odds"] == 1.95 and b["odds_source"] == "manuell" and b["line"] == 118.5 and b["line_ref"]["is_main"] is True)
select(at, "be_E1_team_total_away_neu_side", "under")
at.text_input(key="be_E1_team_total_away_neu_odds_under_113.5").input("").run()
at.button(key="be_E1_team_total_away_neu_save").click().run()
b = bets("E1")["team_total_away"]
check("Quote geleert + kein Einsatz: Wette zaehlt trotzdem (Team Total Gast Under 113,5, ohne Quote, ohne Einsatz)", b["side"] == "under" and b["line"] == 113.5 and b["odds"] is None and b["odds_source"] is None and b["stake"] is None and b["active"])
check("alle fuenf Maerkte gespeichert, je Markt genau eine Wette", set(bets("E1")) == set(ds.MARKETS) and len(bets("E1")) == 5)
H = tab_md(at)
check("Tagesuebersicht/Zahlen zaehlen die 5 Wetten (Einsatz 12,50)", re.search(r'<div class="pc-label">WETTEN</div><div class="lv-val ">5</div>', H) and re.search(r'<div class="pc-label">EINSATZ</div><div class="lv-val ">12,50</div>', H) and "🎯 5 Wetten" in card(at, "E1"))

# ================= Entfernen je Markt
b_before = bets("E1")["total"]
at.button(key=K("E1", "total", "remove")).click().run()
b = bets("E1", True)["total"]
check("Entfernen: nicht geloescht, active false, removed_at gesetzt, letzter aktiver Stand in revisions (reason entfernt)", b["active"] is False and b["removed_at"] and b["revisions"][-1]["reason"] == "entfernt" and b["revisions"][-1]["line"] == 232.5 and "total" not in bets("E1"))
check("Bestaetigung 'Entfernt: ...', Feld wieder 'keine Wette', die anderen Maerkte unveraendert", "Entfernt: Total: Under 232,5" in ok_msg(at) and at.selectbox(key=K("E1", "total", "side")).value == "none" and set(bets("E1")) == {"winner", "spread", "team_total_home", "team_total_away"})
check("Karte zeigt die entfernte Wette nicht mehr (kein 'Total: Under 232,5')", "Under 232,5" not in card(at, "E1") and "🎯 4 Wetten" in card(at, "E1"))
select(at, K("E1", "total", "side"), "over")
at.button(key=K("E1", "total", "save")).click().run()
b = bets("E1")["total"]
check("nach dem Entfernen neu gesetzt: aktiv, Verlauf (Entfernung) bleibt in revisions", b["active"] and b["side"] == "over" and b["line"] == 231.5 and any(r["reason"] == "entfernt" for r in b["revisions"]))

# ================= bereits gespeicherte Wetten werden beim Oeffnen vorausgewaehlt
at2 = app().run()
check("neue Sitzung: gespeicherte Wetten vorausgewaehlt (Sieger Heim, Total Over 231,5, Spread Gast +3,5, Team Totals), Linien und Quoten aus dem Speicher", at2.selectbox(key=K("E1", "winner", "side")).value == "home" and at2.selectbox(key=K("E1", "total", "side")).value == "over"
      and at2.selectbox(key=K("E1", "spread", "side")).value == "away" and at2.selectbox(key=K("E1", "spread", "line_away")).value == 3.5 and at2.text_input(key=K("E1", "spread", "odds_away_3.5")).value == "2,05"
      and at2.selectbox(key=K("E1", "team_total_away", "side")).value == "under" and at2.number_input(key=K("E1", "team_total_home", "stake")).value is None)
check("Bereich ist zugeklappt, wenn schon Wetten gespeichert sind", expander(at2).proto.expanded is False)

# ================= Auswahl bleibt erhalten (Aktualisierung, Abruf, Rerun)
setup()
at = app().run()
select(at, "be_E1_total_neu_side", "over")
at.selectbox(key="be_E1_total_neu_line_over").set_value(233.5).run()
at.text_input(key="be_E1_total_neu_odds_over_233.5").input("2,10").run()
at.number_input(key="be_E1_total_neu_stake").set_value(30.0).run()
NOW[0] += 40
FN["scoreboard"][2]["homeTeam"]["score"] = 99                                      # E3 spielt weiter: neuer Stand im naechsten Abruf
at.button(key="sp_refresh").click().run()
check("nach einem Abruf (Aktualisieren, neuer Spielstand) bleibt die ungespeicherte Auswahl: Seite, Linie 233,5, Quote 2,10, Einsatz 30,00", ">99<" in card(at, "E3") and at.selectbox(key="be_E1_total_neu_side").value == "over"
      and at.selectbox(key="be_E1_total_neu_line_over").value == 233.5 and at.text_input(key="be_E1_total_neu_odds_over_233.5").value == "2,10" and at.number_input(key="be_E1_total_neu_stake").value == 30.0)
at.run(); at.run()
check("auch nach weiteren Reruns (z. B. Klicks in anderen Tabs) bleibt die Auswahl; nichts wurde gespeichert", at.text_input(key="be_E1_total_neu_odds_over_233.5").value == "2,10" and at.selectbox(key="be_E1_total_neu_line_over").value == 233.5 and not ds.store_path().exists())
select(at, "be_game", "E2")
check("Spiel wechseln: Felder des anderen Spiels erscheinen (eigene Schluessel je Spiel), E1-Felder verschwinden", "be_E2_total_neu_side" in keys(at, "selectbox") and "be_E1_total_neu_side" not in keys(at, "selectbox"))
select(at, "be_game", "E1")
check("zurueck zum ersten Spiel: ungespeicherte Eingaben sind zurueckgesetzt (Streamlit verwirft Felder, die nicht angezeigt werden), gespeicherte Wetten bleiben vorausgewaehlt", at.selectbox(key="be_E1_total_neu_side").value == "none" and not ds.store_path().exists())

# ================= Spiel ohne Schnappschuss/Eintrag (E2): nur Sieger waehlbar
select(at, "be_game", "E2")
check("Spiel ohne Schnappschuss und ohne Eingabe: Hinweis, Sieger waehlbar ohne Quote", "Kein Schnappschuss für dieses Spiel" in captions(at) and "be_E2_winner_neu_side" in keys(at, "selectbox"))
select(at, "be_E2_total_neu_side", "over")
check("Total ohne Hauptlinie: keine Linienauswahl, Hinweis 'Keine Hauptlinie bekannt', kein Speichern-Knopf", "Keine Hauptlinie bekannt" in captions(at) and "be_E2_total_neu_save" not in keys(at, "button") and "be_E2_total_neu_line_over" not in keys(at, "selectbox"))
select(at, "be_E2_winner_neu_side", "away")
check("Sieger Gast ohne gespeicherte Quote: Feld leer, Hinweis", at.text_input(key="be_E2_winner_neu_odds_away_w").value == "" and "Keine gespeicherte Quote" in captions(at))
at.button(key="be_E2_winner_neu_save").click().run()
check("Sieger ohne Quote und Einsatz gespeichert (zaehlt trotzdem)", bets("E2")["winner"]["side"] == "away" and bets("E2")["winner"]["odds"] is None and bets("E2")["winner"]["stake"] is None)

# ================= ungueltige Eingaben, gesperrtes Spiel, Anpfiff waehrend der Eingabe
setup()
at = app().run()
select(at, "be_E1_winner_neu_side", "home")
at.text_input(key="be_E1_winner_neu_odds_home_w").input("abc").run()
c1 = counters()
at.button(key="be_E1_winner_neu_save").click().run()
check("ungueltige Quote 'abc': verstaendliche Meldung, nichts gespeichert, kein Absturz", "Eingabe nicht gespeichert: Bitte eine Zahl eingeben (z. B. 1,85)." in err_msg(at) and not ds.store_path().exists() and not at.exception, err_msg(at))
at.text_input(key="be_E1_winner_neu_odds_home_w").input("0,5").run()
at.button(key="be_E1_winner_neu_save").click().run()
check("Quote 0,5 (nicht ueber 1,00): Meldung 'Die Quote muss größer als 1,00 sein.', nichts gespeichert", "Die Quote muss größer als 1,00 sein." in err_msg(at) and not ds.store_path().exists())
at.text_input(key="be_E1_winner_neu_odds_home_w").input("1,4").run()
check("keine Netzabrufe auch bei Fehlern", counters() == c1)
# gesperrtes Spiel E3: nur Ansicht
setup()
ds.set_bet(DAY, S3, GAMES["E3"]["home"], GAMES["E3"]["away"], "total", side="under", line=230.5, odds=1.9, stake=10, now=real_now - 2 * 3600)
at = app().run()
select(at, "be_game", "E3")
check("angepfiffenes Spiel gewaehlt: Hinweis 'Wette ab Anpfiff gesperrt', gespeicherte Wette nur zur Ansicht (Text), keine Eingabefelder", any("Wette ab Anpfiff gesperrt" in i.value for i in at.info) and "Total: Under 230,5 · Quote 1,90 (manuell) · Einsatz 10,00" in tab_md(at)
      and not [k for k in keys(at, "selectbox") if k.startswith("be_E3_")] and keys(at, "button") == [] and keys(at, "text_input") == [])
setup(games=("E1", "E3"))
at = app().run(); select(at, "be_game", "E3")
check("gesperrtes Spiel ohne Wetten: Hinweis und 'keine Wetten gespeichert'", "Für dieses Spiel sind keine Wetten gespeichert." in captions(at))
# Anpfiff waehrend der Eingabe
T4 = time.time() + 30
S4 = iso(T4)
setup(extra_rows=[row("E4", "Utah Jazz", "Phoenix Suns", 1, 0, "", "x", 0, 0, S4)], games=("E3",), snaps_for=(), entry_for=())
GAMES["E4"] = {"home": "Utah Jazz", "away": "Phoenix Suns", "start": S4}
at = app().run()
check("Spiel kurz vor dem Anpfiff ist noch waehlbar (Standard-Auswahl)", at.selectbox(key="be_game").value == "E4", str(at.selectbox(key="be_game").options))
select(at, "be_E4_winner_neu_side", "home")
time.sleep(max(0.0, T4 - time.time() + 1.5))                                               # Anpfiff erreicht, die Seite zeigt noch das Formular
at.button(key="be_E4_winner_neu_save").click().run()
check("Anpfiff zwischen Anzeige und Speichern: Meldung 'Wette ab Anpfiff gesperrt', nichts gespeichert, kein Absturz", "Wette ab Anpfiff gesperrt: Das Spiel hat bereits begonnen" in err_msg(at) and not ds.store_path().exists() and not at.exception, err_msg(at))
check("danach ist das Spiel in der Auswahl als gesperrt gekennzeichnet", "🔒 Wette ab Anpfiff gesperrt" in [o for o in at.selectbox(key="be_game").options if "Suns @ Jazz" in o][0])

# ================= beschaedigte Datei
setup()
ds.store_path().write_text('{"format": "nbaedge-day-bets", "games": {"x": ')
bad_bytes = ds.store_path().read_bytes()
at = app().run()
check("beschaedigte day_bets.json: deutliche Meldung im Bereich, Eintragen gesperrt (keine Felder, keine Knoepfe), Seite laeuft weiter", "beschädigt" in err_msg(at) and "Das Eintragen ist gesperrt" in err_msg(at) and "es wird nichts überschrieben" in err_msg(at)
      and keys(at, "selectbox") == [] and keys(at, "button") == [] and not at.exception and any("Gespeichert" not in t for t in [err_msg(at)]))
check("beschaedigte Datei unveraendert (bytegleich), keine Sicherung durch das reine Anzeigen", ds.store_path().read_bytes() == bad_bytes and not list(Path(ds.store_path().parent).glob("day_bets.corrupt-*")))
check("Karten und Tagesuebersicht laufen weiter (Spiele sichtbar, Hinweis 'noch keine Wetten')", cards := ('data-game="E1"' in tab_md(at)) and "noch keine Wetten gespeichert" in tab_md(at))
ok_, text = be.save_market_bet(type("G", (), {"day": DAY, "start_utc": S1, "home": GAMES["E1"]["home"], "away": GAMES["E1"]["away"], "home_nick": "76ers", "away_nick": "Cavaliers", "game_id": "E1"})(), "winner", "home", None, "", None)
check("direkter Speicherversuch auf beschaedigter Datei: Meldung mit Hinweis auf die Sicherungskopie, Originaldatei bleibt (Sicherung vom Speicher selbst angelegt)", not ok_ and "Sicherungskopie" in text and ds.store_path().read_bytes() == bad_bytes and len(list(Path(ds.store_path().parent).glob("day_bets.corrupt-*"))) == 1, text)

# ================= reine Hilfsfunktionen
check("Uhrzeit aus ISO (Berliner Zeit)", be.fmt_hhmm_iso("2026-10-22T16:27:00+02:00") == "16:27" and be.fmt_hhmm_iso("2026-10-22T14:27:00Z") == "16:27" and be.fmt_hhmm_iso(None) == "" and be.fmt_hhmm_iso("x") == "")
entry = betano_entry(S1, GAMES["E1"]["home"], GAMES["E1"]["away"])
check("Quote-Vorbelegung: Text mit Komma, Quelle 'Betano, Stand 16:27'; keine Quote: None", be.prefill_odds(entry, "total", "over", 231.5) == {"odds": 1.9, "text": "1,90", "label": "Betano, Stand 16:27"} and be.prefill_odds(entry, "total", "over", 240.5) is None and be.prefill_odds(None, "winner", "home", None) is None
      and be.prefill_odds(entry, "spread", "away", 3.5)["text"] == "2,05")
check("Linienauswahl: gespeicherte Linie ausserhalb des Fensters bleibt waehlbar; Sieger keine Linien; Spread Gast gespiegelt", be.line_options("total", {"total": 231.5}, None, 250.5)[-1] == 250.5 and be.line_options("winner", {}, None) == [] and be.line_options("spread", {"spread_home": -4.5}, "away")[0] == -0.5)
check("Standardlinie: Hauptlinie je Markt (Total 231,5; Spread Heim -4,5 / Gast +4,5; ganzzahlige Hauptlinie 118,0 -> 118,5)", be.default_line_for("total", {"total": 231.5}, None) == 231.5 and be.default_line_for("spread", {"spread_home": -4.5}, "home") == -4.5 and be.default_line_for("spread", {"spread_home": -4.5}, "away") == 4.5
      and be.default_line_for("team_total_home", {"team_total_home": 118.0}, None) == 118.5 and be.default_line_for("winner", {}, None) is None)
class FG:
    day, start_utc, home, away, home_nick, away_nick, game_id = DAY, iso(real_now + 3600), "Philadelphia 76ers", "Cleveland Cavaliers", "76ers", "Cavaliers", "FG"
setup()
okk, txt = be.save_market_bet(FG, "total", "over", 231.0, "", None)
check("save_market_bet: ganzzahlige Linie -> Meldung statt Absturz (nichts gespeichert)", not okk and "nur .5-Linien" in txt and not ds.store_path().exists(), txt)
okk, txt = be.remove_market_bet(FG, "total")
check("remove_market_bet ohne aktive Wette: freundliche Meldung, nichts geschrieben", okk and "keine aktive Wette" in txt and not ds.store_path().exists())
class Late(FG): start_utc = iso(real_now - 60)
okk, txt = be.save_market_bet(Late, "winner", "home", None, "", None)
check("save_market_bet nach Anpfiff: GameStartedError -> 'Wette ab Anpfiff gesperrt: ...'", not okk and txt.startswith("Wette ab Anpfiff gesperrt:") and not ds.store_path().exists(), txt)
okk, txt = be.remove_market_bet(Late, "winner")
check("remove_market_bet nach Anpfiff gesperrt", not okk and txt.startswith("Wette ab Anpfiff gesperrt:"))
check("odds_source 'gespeichert' nur bei unveraenderter Betano-Quote (1,90), sonst 'manuell'", be.save_market_bet(FG, "total", "over", 231.5, "1,9", None, {"label": "x", "main_home_view": 231.5}, {"odds": 1.9})[0] and ds.get_bets_by_key(ps.game_key(DAY, FG.start_utc, FG.home, FG.away))["total"]["odds_source"] == "gespeichert"
      and be.save_market_bet(FG, "total", "over", 231.5, "1,91", None, {"label": "x", "main_home_view": 231.5}, {"odds": 1.9})[0] and ds.get_bets_by_key(ps.game_key(DAY, FG.start_utc, FG.home, FG.away))["total"]["odds_source"] == "manuell")
check("Spielbezeichnung in der Auswahl: gesperrt mit Hinweis, sonst nur Anpfiff", be.game_label(type("X", (), {"away_nick": "A", "home_nick": "H", "start_utc": iso(real_now - 10), "status": "LIVE"})()).endswith("🔒 Wette ab Anpfiff gesperrt")
      and "🔒" not in be.game_label(type("X", (), {"away_nick": "A", "home_nick": "H", "start_utc": iso(real_now + 7200), "status": "PRE"})()))

# ================= Geschwindigkeit: Eintragsbereich ist ein eigenes Fragment (ohne Takt), Speichern fuehrt einmal zur Aktualisierung der uebrigen Teile
import streamlit as _st
src_be = inspect.getsource(be)
frag_decl = src_be[src_be.index("@st.fragment\ndef render_bet_entry"):src_be.index("def render_bet_entry")]
check("Eintragsbereich ist ein eigenes st.fragment OHNE run_every (Klicks auf Felder lassen nur ihn neu laufen, nicht die ganze App)", "@st.fragment\ndef render_bet_entry" in src_be and "run_every" not in frag_decl and hasattr(be.render_bet_entry, "__wrapped__"), str(frag_decl))
check("Die beiden Takt-Fragmente (Kopf, Karten) laufen weiter alle 30 s (run_every), Knopf und Schalter ausserhalb", src_tab.count("@st.fragment(run_every=AUTO_SECONDS)") == 0 and inspect.getsource(lt).count("@st.fragment(run_every=AUTO_SECONDS)") == 2 and lt.AUTO_SECONDS == 30
      and "st.toggle(" in src_tab and "st.button(" in src_tab and "_live_head(auto)" in src_tab)
setup()
at = app().run()
select(at, "be_E1_winner_neu_side", "home")
orig_rerun, orig_frag = _st.rerun, be._in_fragment_rerun
calls = []
class _Stop(Exception): pass
def fake_rerun(*a, **k):
    calls.append(1); raise _Stop()
try:
    _st.rerun = fake_rerun
    be._in_fragment_rerun = lambda: False
    at.button(key="be_E1_winner_neu_save").click().run()
    n_full = len(calls)
    page_checks.bad[:] = [b for b in page_checks.bad if "_Stop" not in b]
    check("Lauf der ganzen App (kein Fragment-Lauf): kein zusaetzliches st.rerun, Karten zeigen die Wette schon im selben Lauf", n_full == 0 and "Sieger: 76ers gewinnt" in card(at, "E1") and "🎯 1 Wette" in card(at, "E1"))
    ds.remove_bet(DAY, S1, GAMES["E1"]["home"], GAMES["E1"]["away"], "winner")
    be._in_fragment_rerun = lambda: True                                     # simuliert: Klick kam aus dem Fragment (Fragment-Lauf)
    at = app().run()
    select(at, "be_E1_winner_neu_side", "home")
    at.button(key="be_E1_winner_neu_save").click().run()
    page_checks.bad[:] = [b for b in page_checks.bad if "_Stop" not in b]
    check("Fragment-Lauf nach Speichern: genau EIN st.rerun der ganzen App (damit Karten, Uebersicht und Zahlen die Wette zeigen), vor dem Anzeigen der Meldung", len(calls) == 1 and bets("E1")["winner"]["side"] == "home", str(len(calls)))
    check("Meldung geht dabei nicht verloren (bleibt im Session State fuer den App-Lauf nach dem Rerun)", at.session_state["be_msg"]["ok"] is True and "Gespeichert: Sieger" in at.session_state["be_msg"]["text"])
    be._in_fragment_rerun = lambda: False
    at.run()
    check("Marker 'be_dirty' wird beim Rerun verbraucht: der folgende App-Lauf loest keinen weiteren Rerun aus und zeigt die Meldung genau einmal", len(calls) == 1 and "Gespeichert: Sieger" in ok_msg(at) and "be_dirty" not in at.session_state)
finally:
    _st.rerun, be._in_fragment_rerun = orig_rerun, orig_frag
_t = {}
_orig_body = be.render_bet_entry.__wrapped__
def _timed(*a, **k):
    t0 = time.perf_counter()
    try: return _orig_body(*a, **k)
    finally: _t["s"] = time.perf_counter() - t0
setup()
at = app().run()
check("Eintragsbereich selbst ist billig: sein Funktionskoerper braucht weniger als 1 s (gemessen am Rechner, der Rest der App war bei jedem Klick teuer)", "s" not in _t or _t["s"] < 1.0)

# ================= Rahmen
check("echte Dateien unveraendert: Tracking-Dateien bytegleich, keine day_bets.json im Projekt", {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in (ROOT / "data" / "tracking").glob("*.json")} == real_tracking and not (ROOT / "data" / "tracking" / "day_bets.json").exists())
check("in KEINEM AppTest-Lauf dieser Datei: Streamlit-Exception oder der Satz 'was created with a default value ... Session State API' (Fehlermeldungen der beschaedigten Datei sind gewollt)", not [b for b in page_checks.bad if "Exception" in b or "Session" in b], "; ".join(page_checks.bad[:2]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
