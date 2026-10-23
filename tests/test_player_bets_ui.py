"""Tests fuer den Tab "Spieler" Stufe 2 (Spieler-Wetten eintragen und verfolgen): ui/player_bet_entry.py, ui/player_tab.py ('Meine Spieler-Wetten'), ui/player_view.py.
Nur Temp-Ordner, Live-Feed mit Attrappe (nie ein echter Abruf), keine echten Dateien. Aufruf aus dem Projektordner: venv/bin/python tests/test_player_bets_ui.py"""
import hashlib, json, os, re, sys, tempfile, time, warnings
from pathlib import Path
from types import SimpleNamespace
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

TMP = tempfile.TemporaryDirectory(); T = Path(TMP.name)
os.environ.update(NBAEDGE_TRACKING_DIR=str(T / "tracking"), NBAEDGE_SNAPSHOT_DIR=str(T / "snaps"), NBAEDGE_PLAYER_CACHE_DIR=str(T / "cache"),
                  NBAEDGE_ROSTERS=str(T / "rosters.json"), NBAEDGE_LIVE_DIR=str(T / "live"))
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
from data import day_bets_store as ds
from data import live_feed as lf
from data import pre_match_store as ps
from ui import player_bet_entry as pe
from ui import player_tab as pt
from ui import player_view as pv

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def real_files():
    files = list((ROOT / "data" / "tracking").glob("*")) + list((ROOT / "analysis" / "results" / "forecast_snapshots").glob("*"))
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.is_file()}
real_before = real_files()

NOW = time.time()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
FUT, PAST = iso(NOW + 5 * 3600), iso(NOW - 2 * 3600)
D = lf.current_us_day(NOW)
K1 = ps.game_key(D, FUT, "Heim Falken", "Gast Baeren")
K2 = ps.game_key(D, PAST, "Zwei Loewen", "Zwei Adler")
def line(th, odds): return {"id": f"x{th}", "threshold": th, "odds": odds, "bookmaker": "Betano", "active": True, "updated_at": "2026-10-22T20:00:00+02:00", "entered_at": "2026-10-22T20:00:00+02:00"}
def block(pid, name, team, abbr, lines): return {"id": f"p{pid}", "person_id": pid, "name": name, "team": team, "team_abbreviation": abbr, "mode": "milestones", "active": True, "lines": lines}
(T / "tracking").mkdir(parents=True)
(T / "tracking" / "pre_match_entries.json").write_text(json.dumps({"version": 5, "format": "nbaedge-pre-match", "markets": {}, "last_bookmaker": {}, "updated_at": None, "entries": {
    K1: {"game_date": D, "markets": {"player_points": {"players": [block(1, "Anton Alt", "Heim Falken", "HEI", [line(15, 1.5), line(20, 2.2), line(25, 4.0)]), block(2, "Bruno Bank", "Heim Falken", "HEI", [line(8, 1.6)])]}}},
    K2: {"game_date": D, "markets": {"player_points": {"players": [block(11, "Lena Lauf", "Zwei Loewen", "LOE", [line(12, 1.8), line(18, 3.0)]), block(12, "Nora Nie", "Zwei Adler", "ADL", [line(10, 1.7)])]}}}}}))

# ---------------------------------------------------------------- A) reine Funktionen
check("game_parts", pe.game_parts(K1) == {"game_date": D, "start_utc": FUT, "home": "Heim Falken", "away": "Gast Baeren"})
opts = ds.player_bet_options(K1)
anton = next(p for p in opts["players"] if p["person_id"] == 1)
check("Optionstext: Meilenstein, Quote, Buchmacher-Chance (ohne Snapshot kein Modell)", pe.option_label(anton["options"][1]) == "20+ · Quote 2,20 · Buchmacher 45 %", pe.option_label(anton["options"][1]))
ok1, msg1 = pe.save_player_bet(K1, anton, 20, "2,20", 10.0, opts, now=NOW)
b = ds.get_player_bets_by_key(K1)[1]
check("Speichern: Quote unveraendert aus Betano -> Quelle 'gespeichert' mit odds_ref, Meldung deutsch", ok1 and msg1.startswith("Gespeichert: Anton Alt: mindestens 20 Punkte") and b["odds_source"] == "gespeichert" and b["odds_ref"]["milestone"] == 20 and b["stake"] == 10.0, msg1)
ok2, msg2 = pe.save_player_bet(K1, anton, 20, "2,20", 10.0, opts, now=NOW + 1)
check("nochmal dasselbe: 'Unveraendert'", ok2 and msg2.startswith("Unverändert"))
ok3, msg3 = pe.save_player_bet(K1, anton, 25, "3,90", None, ds.player_bet_options(K1), now=NOW + 2)
b = ds.get_player_bets_by_key(K1)[1]
check("Aendern: anderer Meilenstein und handgeschriebene Quote -> Quelle 'manuell', Revision 'geaendert'", ok3 and b["milestone"] == 25 and b["odds"] == 3.9 and b["odds_source"] == "manuell" and b["revisions"][-1]["reason"] == "geaendert" and b["revisions"][-1]["milestone"] == 20)
ok4, msg4 = pe.save_player_bet(K1, anton, 22, "2", None, opts, now=NOW)
check("Meilenstein nicht in der eingelesenen Liste: abgelehnt, nichts gespeichert", not ok4 and "nicht in der eingelesenen Betano-Liste" in msg4 and ds.get_player_bets_by_key(K1)[1]["milestone"] == 25)
ok5, msg5 = pe.save_player_bet(K1, anton, 20, "abc", None, opts, now=NOW)
check("ungueltige Quote: verstaendliche Meldung", not ok5 and msg5.startswith("Eingabe nicht gespeichert"), msg5)
ok6, msg6 = pe.save_player_bet(K1, anton, 20, "2,2", None, opts, now=NOW + 6 * 3600)
check("nach dem Anpfiff gesperrt: Meldung 'Wette ab Anpfiff gesperrt', nichts geaendert", not ok6 and msg6.startswith("Wette ab Anpfiff gesperrt") and ds.get_player_bets_by_key(K1)[1]["milestone"] == 25, msg6)
ok7, msg7 = pe.remove_player_bet(K1, anton, now=NOW + 3)
check("Entfernen: Meldung, Verlauf bleibt", ok7 and msg7.startswith("Entfernt:") and 1 not in ds.get_player_bets_by_key(K1) and 1 in ds.get_player_bets_by_key(K1, include_removed=True))
ok8, msg8 = pe.remove_player_bet(K1, anton, now=NOW + 4)
check("Entfernen ohne aktive Wette: freundliche Meldung", ok8 and "keine aktive Wette" in msg8)
check("Entfernen nach Anpfiff gesperrt", not pe.remove_player_bet(K1, anton, now=NOW + 7 * 3600)[0])
T0j = T / "tracking" / "day_bets.json"
T0j.write_text("{kaputt")
ok9, msg9 = pe.save_player_bet(K1, anton, 20, None, None, opts, now=NOW)
check("beschaedigte Datei: deutliche Meldung, Datei bleibt", not ok9 and "beschädigt" in msg9 and T0j.read_text() == "{kaputt", msg9)
T0j.unlink()
for f in (T / "tracking").glob("day_bets.corrupt-*"): f.unlink()

# ---------------------------------------------------------------- B) Wettkarten und Tagessumme (ohne Streamlit)
def plv(pid, name, pts, mins, status="spielt"): return lf.PlayerLive(pid, name, "home", "HEI", pts, mins, 2, status, mins > 0)
def gv(status, players, complete=True, hs=80, as_=78):
    clock = SimpleNamespace(is_live=status == "LIVE", is_final=status == "FINAL")
    return SimpleNamespace(clock=clock, players=tuple(players), players_complete=complete, status=status, home_nick="Falken", away_nick="Baeren", home_score=hs, away_score=as_, clock_label="Q3 6:00")
bets = {1: {"active": True, "name": "Anton Alt", "team": "Heim Falken", "milestone": 20, "odds": 2.0, "stake": 10.0}, 2: {"active": True, "name": "Bruno Bank", "team": "Heim Falken", "milestone": 8, "odds": 1.6, "stake": 5.0},
        3: {"active": True, "name": "Cora Cut", "team": "Heim Falken", "milestone": 5, "odds": 1.5, "stake": 20.0}}
game = gv("FINAL", [plv(1, "A", 22, 30), plv(2, "B", 4, 20), plv(3, "C", 0, 0.0, "nicht gespielt")])
rows = [{"key": K1, "game": game, "info": {"home": "Heim Falken", "away": "Gast Baeren"}, "bets": bets, "lives": ds.evaluate_player_bets(bets, game)}]
summ = pt.bets_summary(rows)
check("Tagessumme: 3 Wetten, 1 gewonnen, 1 verloren, 1 nicht gespielt separat, Einsatz 35, Gewinn/Verlust +10 - 5 = +5", (summ["wetten"], summ["gewonnen"], summ["verloren"], summ["offen"], summ["nicht_gespielt"], summ["einsatz"], summ["gewinn_verlust"]) == (3, 1, 1, 0, 1, 35.0, 5.0), str(summ))
sh, cards = pt.bets_html(rows)
joined = " ".join(cards)
check("Karten: Name, Meilenstein 'mindestens 20 Punkte (Over 19,5)', Quote/Einsatz, Status mit Text und Farbe", len(cards) == 3 and "mindestens 20 Punkte (Over 19,5)" in joined and "Quote 2,00" in joined and "Einsatz 10,00" in joined
      and "lv-st lv-st-gruen'>Gewonnen" in joined and "lv-st lv-st-rot'>Verloren" in joined and "Nicht gespielt, Einsatz meist zurück, bitte prüfen" in joined)
check("Karte Gewinn/Verlust nur bei entschiedener Wette (+10,00 / -5,00), nicht gespielt ohne", "Gewinn/Verlust +10,00" in joined and "Gewinn/Verlust −5,00" in joined and joined.count("Gewinn/Verlust") == 2)
check("Summen-HTML: Kacheln inkl. 'NICHT GESPIELT' und Hinweis zur Pruefung beim Buchmacher", "NICHT GESPIELT" in sh and "bitte beim Buchmacher prüfen" in sh and "+5,00" in sh)
live_game = gv("LIVE", [plv(1, "A", 9, 18.5)], hs=60, as_=85)
rows_l = [{"key": K1, "game": live_game, "info": {"home": "Heim Falken", "away": "Gast Baeren"}, "bets": {1: bets[1]}, "lives": ds.evaluate_player_bets({1: bets[1]}, live_game)}]
_, cards_l = pt.bets_html(rows_l)
check("laufend: 'Läuft: 9 von 20 Punkten, noch 11', Minuten, Fouls, Spielerstatus, Spielstand mit Uhr", "Läuft: 9 von 20 Punkten, noch 11" in cards_l[0] and "18,5 Min" in cards_l[0] and "2 Fouls" in cards_l[0] and "spielt" in cards_l[0] and "85 : 60 (Q3 6:00)" in cards_l[0], cards_l[0][:400])
rows_n = [{"key": K1, "game": None, "info": {"home": "Heim Falken", "away": "Gast Baeren"}, "bets": {1: bets[1]}, "lives": {}}]
sn, cn = pt.bets_html(rows_n)
check("Spiel nicht im Scoreboard: Karte bleibt, 'Kein Status', Tagessumme zaehlt die Wette", "Kein Status" in cn[0] and pt.bets_summary(rows_n)["wetten"] == 1 and pt.bets_summary(rows_n)["ohne_status"] == 1)
check("ohne Wetten: freundlicher Hinweis", "noch keine Spieler-Wetten gespeichert" in pv.bet_summary_html(pt.bets_summary([])))
check("Farben: Gruen/Rot nur im Status der Wette (lv-st), nie bei Modell-Differenzen", "pl-diff" not in cards[0])
live_prob = SimpleNamespace(**{**ds.evaluate_player_bets({1: bets[1]}, live_game)[1].__dict__, "probability": 0.42})
check("vorbereitetes Feld Live-Chance wird angezeigt, sobald vorhanden (ungeprueft)", "Live-Chance 42 % (ungeprüft)" in pv.bet_card_html(bets[1], live_prob, "x"))

# ---------------------------------------------------------------- C) Tab im Harness mit Attrappe als Live-Feed
class R:
    def __init__(self, payload): self.status_code, self._p, self.text = 200, payload, ""
    def json(self): return self._p
class Stub:
    def __init__(self): self.rows, self.boxes = [], {}
    def get(self, url, headers=None, params=None, timeout=None):
        if "scoreboard" in url:
            return R({"scoreboard": {"gameDate": D, "games": self.rows}})
        return R({"game": self.boxes.get(url.rsplit("_", 1)[1].split(".")[0], {})})
def srow(gid, home, away, status, period, clock, hs, as_, start):
    t = lambda nick, sc: {"teamCity": nick.split()[0], "teamName": nick.split()[1], "teamTricode": nick[:3].upper(), "score": sc, "periods": []}
    return {"gameId": gid, "gameStatus": status, "gameStatusText": "", "period": period, "gameClock": clock, "gameEt": f"{D}T19:00:00-04:00", "gameTimeUTC": start, "homeTeam": t(home, hs), "awayTeam": t(away, as_)}
def boxg(hs, as_, players):
    s = {"fieldGoalsAttempted": 30, "freeThrowsAttempted": 8, "reboundsOffensive": 4, "turnoversTotal": 5}
    return {"gameStatus": 2, "period": 3, "gameClock": "PT06M00.00S", "homeTeam": {"score": hs, "statistics": dict(s), "teamTricode": "ZWE", "players": players}, "awayTeam": {"score": as_, "statistics": dict(s), "players": []}}
def bp(pid, name, pts, mins, oncourt="1"): return {"personId": pid, "name": name, "oncourt": oncourt, "played": "1", "status": "ACTIVE", "statistics": {"points": pts, "minutes": f"PT{mins:02d}M00.00S", "foulsPersonal": 2}}
stub = Stub()
stub.rows = [srow("A1", "Heim Falken", "Gast Baeren", 1, 0, "", 0, 0, FUT), srow("A2", "Zwei Loewen", "Zwei Adler", 2, 3, "PT06M00.00S", 85, 60, PAST)]
stub.boxes = {"A2": boxg(85, 60, [bp(11, "Lena Lauf", 14, 22)])}
lf._feed = lf.LiveFeed(http_get=stub.get)
# eine vor dem Anpfiff gesetzte Wette im laufenden Spiel (Zeitpunkt der Wette in der Vergangenheit)
ds.set_player_bet(D, PAST, "Zwei Loewen", "Zwei Adler", 11, "Lena Lauf", "Zwei Loewen", 12, odds=1.8, stake=10, now=NOW - 3 * 3600)
ds.set_player_bet(D, PAST, "Zwei Loewen", "Zwei Adler", 12, "Nora Nie", "Zwei Adler", 10, odds=1.7, stake=5, now=NOW - 3 * 3600)
HARNESS = str(ROOT / "tests" / "_harness_player_tab.py")
def run():
    at = AppTest.from_file(HARNESS, default_timeout=60).run()
    return at.selectbox(key="pl_day").set_value(D).run()
at = run()
md = " ".join(x.value for x in at.markdown)
check("Tab: 'Meine Spieler-Wetten' oben, keine Exception/Warnung", "Meine Spieler-Wetten" in md and not at.exception and not problems(at), " | ".join(problems(at))[:200])
check("laufendes Spiel (Q3, 85:60): Lena 14 Punkte, Meilenstein 12 -> sofort gewonnen; Nora (nicht im Boxscore) 'Keine Spielerdaten'", "lv-st-gruen'>Gewonnen" in md and "Lena Lauf" in md and "Keine Spielerdaten" in md, "")
check("Tagessumme im Tab: 2 Wetten, 1 gewonnen, 1 offen", "lv-tile" in md and re.search(r"WETTEN</div><div class='lv-val '>2<", md) is not None and re.search(r"GEWONNEN</div><div class='lv-val '>1<", md) is not None)
sel = at.selectbox(key=f"pl_game_{D}")
sel.set_value(K2).run()
check("begonnenes Spiel: Eingabe gesperrt ('🔒 Wette ab Anpfiff gesperrt'), gespeicherte Wetten nur zur Ansicht", any("gesperrt" in i.value for i in at.info) and not [b for b in at.button if b.label == "Speichern"])
at.selectbox(key=f"pl_game_{D}").set_value(K1).run()
at.selectbox(key=f"pe_player_{K1}").set_value(1).run()
check("offenes Spiel: Spieler- und Meilenstein-Auswahl, Quote vorbelegt, Knopf 'Speichern', kein 'Entfernen' ohne Wette", [s.label for s in at.selectbox if s.label.startswith("Meilenstein")] and [b.label for b in at.button if b.label in ("Speichern", "Wette entfernen")] == ["Speichern"]
      and any(t.label == "Quote (optional)" and t.value == "1,50" for t in at.text_input), str([t.value for t in at.text_input]))
ms_box = next(s for s in at.selectbox if s.label.startswith("Meilenstein"))
ms_box.set_value(20).run()
check("Meilenstein wechseln lädt die passende Quote (20+: 2,20)", any(t.label == "Quote (optional)" and t.value == "2,20" for t in at.text_input))
next(n for n in at.number_input if n.label == "Einsatz (optional)").set_value(12.5).run()
next(b for b in at.button if b.label == "Speichern").click().run()
saved = ds.get_player_bets_by_key(K1)
md = " ".join(x.value for x in at.markdown)
check("Speichern: Wette in day_bets.json (Anton, 20+, Quote 2,20 'gespeichert', Einsatz 12,50), keine Exception", set(saved) == {1} and saved[1]["milestone"] == 20 and saved[1]["odds"] == 2.2 and saved[1]["odds_source"] == "gespeichert" and saved[1]["stake"] == 12.5 and not at.exception, str(saved))
check("nach dem Speichern: Bestaetigung, Karte 'Wartet auf Anpfiff' in 'Meine Spieler-Wetten', Marker 🎯 20+ @ 2,20 in der Tabelle", any("Gespeichert: Anton Alt" in x.value for x in at.success) and "Wartet auf Anpfiff" in md and "Anton Alt" in md, "")
check("Seite ohne Warnung/Fehler nach dem Speichern", not problems(at) and not page_checks.bad, " | ".join(problems(at))[:200] + str(page_checks.bad)[:100])
# Aendern
ms_box = next(s for s in at.selectbox if s.label.startswith("Meilenstein"))
check("gespeicherte Wette ist in der Auswahl vorbelegt (20+), 'Wette entfernen' sichtbar", ms_box.value == 20 and [b.label for b in at.button if b.label in ("Speichern", "Wette entfernen")] == ["Speichern", "Wette entfernen"])
ms_box.set_value(25).run()
next(b for b in at.button if b.label == "Speichern").click().run()
saved = ds.get_player_bets_by_key(K1)
check("Aendern: Meilenstein 25, Revision 'geaendert' (Verlauf)", saved[1]["milestone"] == 25 and saved[1]["revisions"][-1]["reason"] == "geaendert" and saved[1]["revisions"][-1]["milestone"] == 20)
next(b for b in at.button if b.label == "Wette entfernen").click().run()
check("Entfernen: keine aktive Wette, Verlauf bleibt, Meldung 'Entfernt'", 1 not in ds.get_player_bets_by_key(K1) and 1 in ds.get_player_bets_by_key(K1, include_removed=True) and any("Entfernt: Anton Alt" in x.value for x in at.success))
# zweiter Spieler im selben Spiel
at.selectbox(key=f"pe_player_{K1}").set_value(2).run()
next(b for b in at.button if b.label == "Speichern").click().run()
check("mehrere Spieler je Spiel: Bruno gespeichert, Anton bleibt entfernt", set(ds.get_player_bets_by_key(K1)) == {2})

# Abgleich mit der Datei: Ende der Teststufe
check("echte Dateien (Tracking, Snapshots) unveraendert", real_files() == real_before)
print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
