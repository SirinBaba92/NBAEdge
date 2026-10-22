"""Tests fuer Pre-Match Eingabe, Schritt 6: Markt "Team Totals" (je Team getrennt), rechnerischer Vorschlag, kompakte Zeilen fuer weitere Linien
(Spread, Total, Team Totals), Buchmacher der Zeile folgt der Hauptlinie, ein Speichern fuer vier Maerkte, Dateiversion 4.
Offline (tests/fake_net.py, Temp-Verzeichnisse), keine echten Calls; Pickle und echte Tracking-Datei nur gelesen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_pre_match_team.py"""
import datetime as dt, hashlib, json, os, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
import data.nba_live as _nba_live
_nba_live.NBA_CACHE_SECONDS = 10 ** 6
import data.pre_match_store as ps
import ui.pre_match_tab as pmt
from models.elo import MODEL_PATH
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
real_file = ROOT / "data" / "tracking" / "pre_match_entries.json"
real_bytes = real_file.read_bytes() if real_file.exists() else None
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
fsha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
K, P = "New York Knicks", "Philadelphia 76ers"

def pm_expanders(at):
    """Expander des Tabs Pre-Match Eingabe (nicht die Zeilen-Bloecke der Score-Projections-Karten)."""
    return [x for x in at.expander if x.label != "Wetten eintragen" and not any("pc-l" in m.value for m in x.markdown)]   # ohne die Linien-Expander der Karten und den Bereich "Wetten eintragen" (Tab Spieltag)
def trow(rid="main", line="113,5", o="1,91", u="1,89", b="Pinnacle", d=None):
    return {"id": rid, "direction": d, "line": line, "over_odds": o, "under_odds": u, "bookmaker": b}
def win(h="1,55", a="2,50", b="Betano"): return {"home_odds": h, "away_odds": a, "bookmaker": b}
def srow(rid="main", line="-4,5", h="1,91", a="1,95", b="Pinnacle"):
    return {"id": rid, "line": line, "home_odds": h, "away_odds": a, "bookmaker": b}
NAMES = {"away": "76ers", "home": "Knicks"}
def card(start, now, winner=None, rows=None, trows=None, team=None, tsugg=None, home=K, away=P, date="2026-10-20"):
    return ps.save_card(date, start, home, away, winner=winner, spread_rows=rows, total_rows=trows, team_rows=team, team_suggestion=tsugg, team_names=NAMES, now=now)
def fails(fn, exc=ps.OddsInputError):
    try: fn(); return None
    except exc as e: return e
def entry0(): return list(ps.load()["entries"].values())[0]

# ===================================================== A) Eingabe 40 bis 200, halbe Linien
check("gueltige Team-Total-Linien (Komma/Punkt, ganz/halb, 40 bis 200)", all(ps.parse_team_total_input(k) == v for k, v in {"113,5": 113.5, "113.5": 113.5, "113": 113.0, "40": 40.0, "200": 200.0}.items()))
bad = ["", None, "abc", "113,25", "113,75", "113,3", "39,5", "39", "200,5", "201", "0", "-113,5", "nan", "1,2,3"]
errs = {t: (lambda e: str(e) if e else None)(fails(lambda t=t: ps.parse_team_total_input(t))) for t in bad}
check("Viertel-/Fremdwerte und Werte ausserhalb 40 bis 200 werden abgelehnt", all(errs.values()), str({k: v for k, v in errs.items() if not v}))
check("Meldungen: Viertellinie / 'unrealistisch (erwartet 40 bis 200 Punkte)'", "ganze und halbe" in errs["113,25"] and "40 bis 200" in errs["201"] and "40 bis 200" in errs["39,5"])

# ===================================================== B) Rechnerischer Vorschlag
d = ps.derive_team_suggestions(231.5, -4.5)
check("Vorschlag Heim-Favorit: Total 231,5, Heim -4,5 -> Heim 118,0 / Gast 113,5, source 'derived', ungerundet + gerundet",
      d["home"] == {"line": 118.0, "line_rounded": 118.0, "source": "derived"} and d["away"] == {"line": 113.5, "line_rounded": 113.5, "source": "derived"}, str(d))
d = ps.derive_team_suggestions(231.5, 3.0)
check("Vorschlag Gast-Favorit: Total 231,5, Heim +3 -> Heim 114,25 (gerundet 114,5) / Gast 117,25 (gerundet 117,5)",
      d["home"]["line"] == 114.25 and d["home"]["line_rounded"] == 114.5 and d["away"]["line"] == 117.25 and d["away"]["line_rounded"] == 117.5, str(d))
d = ps.derive_team_suggestions(231.5, 0.0)
check("Vorschlag Pick'em: beide 115,75 -> 116,0", d["home"]["line"] == d["away"]["line"] == 115.75 and d["home"]["line_rounded"] == d["away"]["line_rounded"] == 116.0, str(d))
check("Vorschlag ohne Total oder ohne Spread: None", ps.derive_team_suggestions(None, -4.5) is None and ps.derive_team_suggestions(231.5, None) is None)
check("Oberflaeche: _team_suggestion (market_spread positiv = Heim Favorit; ohne Total/Spread None)",
      pmt._team_suggestion({"market_total": 231.5, "market_spread": 4.5})["home"]["line"] == 118.0 and pmt._team_suggestion({"market_total": 231.5}) is None and pmt._team_suggestion({"market_spread": 4.5}) is None)

# ===================================================== C) Speichern, Laden, Aendern je Team
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
tsugg = ps.derive_team_suggestions(231.5, -4.5)
r = card(start, now, team={"away": [trow()], "home": [trow(line="118", o="1,85", u="1,95", b="Bet365")]}, tsugg=tsugg)
d = ps.load(); e = entry0(); tm = e["markets"]["team_totals"]; a, h = tm["away"]["lines"][0], tm["home"]["lines"][0]
check("Team Totals gespeichert: Version 5, je Team getrennt, Linie, Over/Under, Buchmacher, Zeitstempel, Revision, Vorschlag 'derived'",
      d["version"] == 5 and r["markets"]["team_totals"] == "saved" and r["markets"]["total"] == "skipped" and a["line"] == 113.5 and h["line"] == 118.0
      and a["over_odds"] == 1.91 and a["under_odds"] == 1.89 and h["bookmaker"] == "Bet365" and a["entered_at"] and len(a["revisions"]) == 1
      and a["market_suggestion"] == tsugg["away"] and h["market_suggestion"] == tsugg["home"] and a["market_suggestion"]["source"] == "derived"
      and tm["away"]["team"] == P and tm["home"]["team"] == K and "team_totals" in d["markets"] and d["last_bookmaker"]["team_totals_home"] == "Bet365", str(tm)[:200])
b = fsha(ps.store_path()); r = card(start, now + 1, team={"away": [trow()], "home": [trow(line="118", o="1,85", u="1,95", b="Bet365")]})
check("unveraendert: 'unchanged', Datei byte-identisch", r["status"] == "unchanged" and r["markets"]["team_totals"] == "unchanged" and fsha(ps.store_path()) == b)
r = card(start, now + 2, team={"away": [trow(o="2,00")], "home": [trow(line="118", o="1,85", u="1,95", b="Bet365")]})
e = entry0(); a, h = e["markets"]["team_totals"]["away"]["lines"][0], e["markets"]["team_totals"]["home"]["lines"][0]
check("nur ein Team geaendert: Gast bekommt eine Revision, Heim bleibt ohne neue", r["status"] == "saved" and len(a["revisions"]) == 2 and a["over_odds"] == 2.0 and len(h["revisions"]) == 1)
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
r = card(start, now, team={"away": [trow()], "home": [trow(o="", u="")]})
e = entry0()
check("nur ein Team ausgefuellt: das andere (nur vorbefuellte Linie ohne Quoten) wird uebersprungen", r["status"] == "saved" and len(ps.team_total_lines(e, "away")) == 1 and ps.team_total_lines(e, "home") == [])
saved, last = ps.saved_summary(e)
check("Chip: Team Totals zaehlen als gespeichert", saved and last)
check("Gast-Linie 113,5 und Heim-Linie 113,5 duerfen gleich sein (Duplikat nur je Team)", card(start, now + 1, team={"away": [trow()], "home": [trow(line="113,5")]})["status"] == "saved")

# ===================================================== D) Weitere Linien je Team
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
def extras(first=115.5, last=111.5):
    return ([trow(None, "114,5", d="higher"), trow(None, "115,5", d="higher"), trow(None, "116,5", d="higher"),
             trow(None, "112,5", d="lower"), trow(None, "111,5", d="lower"), trow(None, "110,5", d="lower")])
r = card(start, now, team={"away": [trow()] + extras(), "home": [trow(line="118")]})
e = entry0(); la = ps.team_total_lines(e, "away")
check("7 Linien fuer ein Team (Hauptlinie + 3 hoehere + 3 niedrigere), Richtungen festgehalten, anderes Team unberuehrt",
      [x["id"] for x in la] == ["main", "x1", "x2", "x3", "x4", "x5", "x6"] and [x["direction"] for x in la] == [None] + ["higher"] * 3 + ["lower"] * 3 and len(ps.team_total_lines(e, "home")) == 1)
b = fsha(ps.store_path())
saved_rows = lambda: [trow()] + [trow(l["id"], f'{l["line"]}'.replace(".", ","), d=l["direction"]) for l in la[1:]]
x = fails(lambda: card(start, now + 1, team={"away": saved_rows() + [trow(None, "120,5", d="higher")]}), ps.CardInputError)
check("4. hoehere Linie eines Teams: abgelehnt (hoechstens 3), nichts geschrieben", x and "Team Totals · 76ers" in str(x) and "höchstens 3 höhere" in str(x) and fsha(ps.store_path()) == b, str(x))
x = fails(lambda: card(start, now + 1, team={"away": saved_rows() + [trow(None, "100,5", d="lower")]}), ps.CardInputError)
check("4. niedrigere Linie eines Teams: abgelehnt", x and "höchstens 3 niedrigere" in str(x) and fsha(ps.store_path()) == b)
x = fails(lambda: card(start, now + 1, team={"away": saved_rows() + [trow(None, "115,5", d="higher")]}), ps.CardInputError)
check("Duplikat desselben Teams: abgelehnt mit Team genannt", x and "mehrfach" in str(x) and "76ers" in str(x) and fsha(ps.store_path()) == b)
rows = saved_rows(); rows[2] = trow("x2", "113,5", d="higher")
x = fails(lambda: card(start, now + 1, team={"away": rows}), ps.CardInputError)
check("gespeicherte Linie so geaendert, dass sie die Hauptlinie doppelt: Warnung", x and "mehrfach" in str(x) and fsha(ps.store_path()) == b)
r = card(start, now + 2, team={"away": [trow(line="120")] + saved_rows()[1:]})
la2 = ps.team_total_lines(entry0(), "away")
check("Hauptlinie nachtraeglich geaendert verschiebt weitere Linien nicht", r["status"] == "saved" and la2[0]["line"] == 120.0 and [x["line"] for x in la2[1:]] == [114.5, 115.5, 116.5, 112.5, 111.5, 110.5])
r = ps.remove_team_total_line("2026-10-20", start, K, P, "away", "x2", now=now + 3)
e = entry0(); allx = e["markets"]["team_totals"]["away"]["lines"]; rem = next(x for x in allx if x["id"] == "x2")
check("Entfernen: inaktiv, removed_at, Revision 'removed', nichts geloescht; Heim unberuehrt", r["status"] == "removed" and rem["active"] is False and rem["revisions"][-1]["action"] == "removed" and len(allx) == 7 and len(ps.team_total_lines(e, "away")) == 6 and len(ps.team_total_lines(e, "home")) == 1)
check("Hauptlinie kann nicht entfernt werden; unbekanntes Team abgelehnt", fails(lambda: ps.remove_team_total_line("2026-10-20", start, K, P, "away", "main", now=now + 4)) and fails(lambda: ps.remove_team_total_line("2026-10-20", start, K, P, "both", "x1", now=now + 4)))

# ===================================================== E) Ein Knopf, vier Maerkte
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
full = dict(winner=win(), rows=[srow()], trows=[trow(line="231,5")], team={"away": [trow()], "home": [trow(line="118")]})
r = card(start, now, **full)
e = entry0(); stamps = {e["markets"]["winner_incl_ot"]["updated_at"], e["markets"]["spread"]["updated_at"], e["markets"]["total"]["updated_at"], e["markets"]["team_totals"]["updated_at"]}
check("alle vier Maerkte in EINEM Schreibvorgang (gleicher Zeitstempel)", r["markets"] == {"winner_incl_ot": "saved", "spread": "saved", "total": "saved", "team_totals": "saved", "player_points": "skipped"} and len(stamps) == 1)
b = fsha(ps.store_path()); r = card(start, now + 1, **full)
check("alles unveraendert: 'unchanged', byte-identisch", r["status"] == "unchanged" and set(r["markets"].values()) == {"unchanged", "skipped"} and fsha(ps.store_path()) == b)
blocks = {
    "Sieger ungueltig blockiert alle anderen": (dict(full, winner=win(h="abc")), "Sieger inkl. OT"),
    "Spread ungueltig blockiert alle anderen": (dict(full, rows=[srow(line="-4,25")]), "Spread"),
    "Total ungueltig blockiert alle anderen": (dict(full, trows=[trow(line="231,25")]), "Total"),
    "Team Totals Gast: Quote Under fehlt blockiert alles": (dict(full, team={"away": [trow(u="")], "home": [trow(line="118")]}), "Team Totals · 76ers: Quote Under fehlt."),
    "Team Totals Heim: Viertellinie blockiert alles": (dict(full, team={"away": [trow()], "home": [trow(line="118,25")]}), "Team Totals · Knicks"),
    "Team Totals Gast ausserhalb 40 bis 200 blockiert alles": (dict(full, team={"away": [trow(line="39")], "home": [trow(line="118")]}), "Team Totals · 76ers"),
}
for name, (kw, needle) in blocks.items():
    kw = {**kw, "winner": kw["winner"] if kw["winner"] != win() else win(h="1,60")}
    x = fails(lambda kw=kw: card(start, now + 3, **{**kw, "trows": [trow(line="231,5", o="2,10")] if kw["trows"] == full["trows"] else kw["trows"]}), ps.CardInputError)
    check(name + " (Warnung nennt Markt und Team, Datei unveraendert)", x and any(needle in m for m in x.errors) and fsha(ps.store_path()) == b, str(getattr(x, "errors", x)))
x = fails(lambda: card(start, now + 3, winner=win(h="x"), rows=[srow(line="-4,3")], trows=[trow(line="231,3")], team={"away": [trow(u="")], "home": [trow(line="118,25")]}), ps.CardInputError)
check("alle Maerkte falsch: je eine Warnung (Sieger, Spread, Total, Team Totals Gast, Team Totals Heim)", x and len(x.errors) == 5 and fsha(ps.store_path()) == b, str(getattr(x, "errors", x)))
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
x = fails(lambda: card(start, now, team={"away": [trow(o="", u="")], "home": [trow(o="", u="")]}), ps.OddsInputError)
check("nur vorbefuellte Team-Linien ohne Quoten: 'Nichts eingetragen', nichts geschrieben", x and "Nichts eingetragen" in str(x) and not ps.store_path().exists())

# ===================================================== F) Sperre (inkl. Rennen)
tmp = fresh_env(); now = time.time(); start_ts = now + 600; start = iso(start_ts)
card(start, now, team={"away": [trow()]}); b = fsha(ps.store_path())
for name, ts in (("genau zum Anpfiff", start_ts), ("nach dem Anpfiff", start_ts + 5)):
    x = fails(lambda ts=ts: card(start, ts, team={"away": [trow(o="2,00")]}), ps.GameStartedError)
    check(f"Team-Totals-Speichern {name}: abgelehnt, Datei unveraendert", x and fsha(ps.store_path()) == b)
check("Team-Total-Linie entfernen nach Anpfiff: abgelehnt", fails(lambda: ps.remove_team_total_line("2026-10-20", start, K, P, "away", "x1", now=start_ts + 1), ps.GameStartedError))
check("eine Sekunde vor dem Anpfiff: noch moeglich", card(start, start_ts - 1, team={"away": [trow(o="2,00")]})["status"] == "saved")

# ===================================================== G) Dateiversionen 1 bis 3 lesbar, Version 3 wird byte-genau gesichert
def old_file(version, start):
    e = {"game_date": "2026-10-20", "start_utc": start, "home": K, "away": P, "markets": {
        "winner_incl_ot": {"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "entered_at": "2026-10-21T01:10:31+02:00", "updated_at": "2026-10-21T01:10:31+02:00",
                           "revisions": [{"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "saved_at": "2026-10-21T01:10:31+02:00"}]}}}
    if version >= 3:
        e["markets"]["total"] = {"entered_at": "2026-10-21T01:20:00+02:00", "updated_at": "2026-10-21T01:20:00+02:00", "lines": [{
            "id": "main", "role": "main", "direction": None, "active": True, "line": 231.5, "over_odds": 1.9, "under_odds": 1.9, "bookmaker": "Betano",
            "entered_at": "2026-10-21T01:20:00+02:00", "updated_at": "2026-10-21T01:20:00+02:00", "market_suggestion": None,
            "revisions": [{"action": "saved", "line": 231.5, "over_odds": 1.9, "under_odds": 1.9, "bookmaker": "Betano", "saved_at": "2026-10-21T01:20:00+02:00", "market_suggestion": None}]}]}
    return {"version": version, "format": "nbaedge-pre-match-entries", "markets": {"winner_incl_ot": "x"}, "last_bookmaker": {"winner_incl_ot": "Betano"},
            "updated_at": "2026-10-21T01:10:31+02:00", "entries": {f"2026-10-20|{start}|{K}|{P}": e}}
for ver in (1, 2, 3):
    tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
    f = old_file(ver, start); ps.store_path().parent.mkdir(parents=True, exist_ok=True); ps.store_path().write_text(json.dumps(f, indent=2)); old = ps.store_path().read_bytes()
    d = ps.load()
    check(f"Version-{ver}-Datei ist lesbar, Lesen aendert nichts", not d.get("error") and d["version"] == ver and ps.store_path().read_bytes() == old and ps.team_total_lines(list(d["entries"].values())[0], "away") == [])
    r = card(start, now, winner=win("1,50", "2,60"), team={"away": [trow()]})
    backups = list(ps.history_dir().glob(f"pre_match_entries.v{ver}_vor_Upgrade_*.json")); d = ps.load(); ee = list(d["entries"].values())[0]["markets"]
    same_total = ee.get("total") == f["entries"][f"2026-10-20|{start}|{K}|{P}"]["markets"].get("total")
    check(f"erstes Schreiben auf Version {ver}: Datei byte-genau gesichert, danach Version 5, Sieger{' und Total' if ver == 3 else ''} unveraendert",
          len(backups) == 1 and backups[0].read_bytes() == old and d["version"] == 5 and ee["winner_incl_ot"] == f["entries"][f"2026-10-20|{start}|{K}|{P}"]["markets"]["winner_incl_ot"]
          and same_total and r["markets"]["winner_incl_ot"] == "unchanged" and r["markets"]["team_totals"] == "saved")

# ===================================================== H) Oberflaeche (AppTest)
fresh_env(remaining=400)
n = time.time()
def mk_event(home, away, total, home_points, commence, eid):
    bms = []
    for bk, hp in zip(("pinnacle", "draftkings", "fanduel")[:len(home_points)], home_points):
        ms = [{"key": "totals", "last_update": iso(n - 700), "outcomes": [{"name": "Over", "point": total, "price": 1.9}, {"name": "Under", "point": total, "price": 1.9}]},
              {"key": "spreads", "last_update": iso(n - 700), "outcomes": [{"name": home, "point": hp, "price": 1.9}, {"name": away, "point": -hp, "price": 1.9}]}]
        bms.append({"key": bk, "last_update": iso(n - 700), "markets": ms})
    return {"id": eid, "home_team": home, "away_team": away, "commence_time": iso(commence), "bookmakers": bms}
state["commence_offsets"] = {K: 3 * H, "San Antonio Spurs": 3 * H, "Detroit Pistons": -600}
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu",
    "data": [mk_event(K, P, 232.0, [-4.5, -4.5, -4.0], n + 3 * H, "ev-k")]}}, "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def btn(at, key): return [b for b in at.button if b.key == key][0]
def ti(at, key): return at.text_input(key=key)
def kid_of(at, home):
    p = [x for x in at.session_state["projections"] if x["home_team"] == home][0]
    return hashlib.md5(ps.game_key(p["game_date"], ps.normalize_start(p["game_start"]), p["home_team"], p["away_team"]).encode()).hexdigest()[:10]
def keys(at, kid, which): return [t.key for t in at.text_input if (t.key or "").startswith(f"pm_{which}_{kid}_") and t.key.endswith("_line")]
def clean(at): return not page_checks.problems(at)
def rid_of(k): return k.split("_")[3]

at = app().run(); kid = kid_of(at, K); pj = [x for x in at.session_state["projections"] if x["home_team"] == K][0]
exp = ps.derive_team_suggestions(pj["market_total"], -pj["market_spread"])
check("Start: keine Exception/Warnung", clean(at), str(page_checks.problems(at)))
check("Team-Total-Hauptlinien mit dem rechnerischen Vorschlag vorbefuellt (Gast, Heim)", ti(at, f"pm_ta_{kid}_main_line").value == pmt.fmt_total(exp["away"]["line_rounded"]) and ti(at, f"pm_th_{kid}_main_line").value == pmt.fmt_total(exp["home"]["line_rounded"]),
      f'{ti(at, f"pm_ta_{kid}_main_line").value} / {ti(at, f"pm_th_{kid}_main_line").value} erwartet {exp["away"]["line_rounded"]} / {exp["home"]["line_rounded"]}')
caps = [c.value for c in at.caption if c.value.startswith("Rechnerischer Vorschlag aus Total und Spread (Vorab-Linie):")]
check("Hinweis 'Rechnerischer Vorschlag aus Total und Spread (Vorab-Linie): ...' je Team", len(caps) == 2, str(caps))
heads = [m.value for m in at.markdown if 'class="pm-team-title"' in m.value]
titles = [x.label for x in pm_expanders(at)]
check("Zwischenueberschriften 'Sixers (Gast)'/'Knicks (Heim)' (Gast zuerst)", len(heads) >= 2 and "(Gast)" in heads[0] and "Knicks (Heim)" in heads[1], str(heads))
check("Marktreihenfolge: Sieger, Spread, Total, Team Totals", titles[:4] == ["SIEGER INKL. OT", "SPREAD", "TOTAL", "TEAM TOTALS"], str(titles))
kid_s = kid_of(at, "San Antonio Spurs")
check("Ohne Total/Spread-Vorab-Linie bleiben die Team-Felder leer (kein Vorschlag)", ti(at, f"pm_ta_{kid_s}_main_line").value == "" and ti(at, f"pm_th_{kid_s}_main_line").value == "")

# Klicks je Team
pa, ph = f"pm_ta_{kid}", f"pm_th_{kid}"
btn(at, f"{pa}_main_plus").click().run()
check("Team-Total '+' (Gast): Linie +0,5; Heim unveraendert", ti(at, f"{pa}_main_line").value == pmt.fmt_total(exp["away"]["line_rounded"] + 0.5) and ti(at, f"{ph}_main_line").value == pmt.fmt_total(exp["home"]["line_rounded"]) and clean(at))
for i in range(3): btn(at, f"{pa}__addh").click().run()
for i in range(3): btn(at, f"{pa}__addl").click().run()
check("Gast: je 3 hoehere/niedrigere Linien, Maximum mit Notiz, Heim-Knoepfe weiter aktiv", btn(at, f"{pa}__addh").disabled and btn(at, f"{pa}__addl").disabled and not btn(at, f"{ph}__addh").disabled
      and any(c.value == "maximal 3 höhere Linien" for c in at.caption) and any(c.value == "maximal 3 niedrigere Linien" for c in at.caption) and clean(at))
base_v = exp["away"]["line_rounded"] + 0.5
check("Zwischenueberschrift zaehlt alle sichtbaren Zeilen (6 neue, noch nicht gespeicherte): 'Weitere Linien (6)'", any("Weitere Linien (6)" in m.value for m in at.markdown if "pm-sub" in m.value), str([m.value for m in at.markdown if "pm-sub" in m.value][:4]))
order = [ti(at, k).value for k in keys(at, kid, "ta")]
check("Gast: Sortierung Hauptlinie, dann hoehere (absteigend), dann niedrigere (absteigend), je 1,0 weiter",
      order == [pmt.fmt_total(v) for v in [base_v, base_v + 3, base_v + 2, base_v + 1, base_v - 1, base_v - 2, base_v - 3]], str(order))
btn(at, f"{ph}__addh").click().run()
check("Heim: eigene Linien (hoeher ab Heim-Hauptlinie), Gast unveraendert", [ti(at, k).value for k in keys(at, kid, "th")][1:] == [pmt.fmt_total(exp["home"]["line_rounded"] + 1)] and len(keys(at, kid, "ta")) == 7)

# kompakte Zeilen: eine Zeile = ein st.columns-Aufruf mit allen Feldern; Kopfzeile einmal
tkeys = [k for k in keys(at, kid, "ta") if not k.endswith("_main_line")]
hdr = [m.value for m in at.markdown if "pm-flabel" in m.value and "text-align:center" in m.value and ">Quote Over<" in m.value]
check("kompakte Zeilen (Total-Struktur): Kopfzeile 'Quote Over | Linie | Quote Under | Buchmacher' steht je Block einmal, nicht je Zeile", len(hdr) == 2, str(len(hdr)))
row_keys = lambda base: [t.key for t in at.text_input if (t.key or "").startswith(base + "_")]
check("kompakte Zeile enthaelt alle Felder: Over, Linie, Under, Buchmacher, dazu -, +, Entfernen", all(x in [t.key for t in at.text_input] for x in [f"{pa}_{rid_of(tkeys[0])}_{s}" for s in ("over", "line", "under", "book")])
      and all(x in [b.key for b in at.button] for x in [f"{pa}_{rid_of(tkeys[0])}_{s}" for s in ("minus", "plus", "rm")]))
check("'Entfernen' der weiteren Zeilen ist tertiary (grauer Text)", all(btn(at, f"{pa}_{rid_of(k)}_rm").proto.type == "tertiary" for k in tkeys))

# Buchmacher: folgt der Hauptlinie, solange nicht manuell geaendert
ti(at, f"{pa}_main_book").input("Pinnacle").run()
first, second = f"{pa}_{rid_of(tkeys[0])}_book", f"{pa}_{rid_of(tkeys[1])}_book"
check("Buchmacher der Hauptlinie geaendert: neue Zeilen uebernehmen ihn", ti(at, first).value == "Pinnacle" and ti(at, second).value == "Pinnacle")
ti(at, second).input("Bet365").run(); ti(at, f"{pa}_main_book").input("Betano").run()
check("manuell geaenderte Zeile bleibt (Bet365), nicht abweichende folgt (Betano)", ti(at, second).value == "Bet365" and ti(at, first).value == "Betano", f"{ti(at, first).value} / {ti(at, second).value}")
btn(at, f"{pa}__addh").click().run() if not btn(at, f"{pa}__addh").disabled else None
check("neue Zeile bekommt den aktuellen Buchmacher der Hauptlinie vorbelegt (Heim: eigener Buchmacher)", all(ti(at, k.replace("_line", "_book")).value in ("Betano", "Bet365") for k in tkeys) and ti(at, f"{ph}_main_book").value != "Betano")

# Spread: kompakte Zeile + Buchmacher-Folge
b0 = f"pm_sp_{kid}_main"
ti(at, f"{b0}_book").input("Pinnacle").run()
btn(at, f"pm_add_{kid}").click().run(); btn(at, f"pm_add_{kid}").click().run()
n1, n2 = f"pm_sp_{kid}_n1", f"pm_sp_{kid}_n2"
check("Spread: weitere Linien sind kompakte Zeilen mit allen Feldern; Buchmacher der Hauptlinie vorbelegt", all(ti(at, f"{n}_{s}") for n in (n1, n2) for s in ("away", "gline", "line", "home", "book")) and ti(at, f"{n1}_book").value == "Pinnacle" and clean(at))
sp_hdr = [m.value for m in at.markdown if "pm-flabel" in m.value and "text-align:center" in m.value and "Quote Gast" in m.value]
check("Spread: Kopfzeile steht einmal im Expander", len(sp_hdr) == 1, str(len(sp_hdr)))
ti(at, f"{n1}_book").input("Bet365").run(); ti(at, f"{b0}_book").input("Betano").run()
check("Spread: manuell geaenderter Buchmacher bleibt, anderer folgt der Hauptlinie", ti(at, f"{n1}_book").value == "Bet365" and ti(at, f"{n2}_book").value == "Betano")

# Speichern: vier Maerkte
def fill(a, base, o, u):
    ti(a, f"{base}_over").input(o); ti(a, f"{base}_under").input(u)
ti(at, f"pm_home_{kid}").input("1,60"); ti(at, f"pm_away_{kid}").input("2,50")
ti(at, f"{b0}_away").input("1,95"); ti(at, f"{b0}_home").input("1,91")
ti(at, f"{n1}_away").input("1,90"); ti(at, f"{n1}_home").input("1,92")
fill(at, f"pm_tt_{kid}_main", "1,95", "1,87")
fill(at, f"{pa}_main", "1,91", "1,89"); fill(at, f"{ph}_main", "1,85", "1,95")
for k in tkeys: fill(at, k.rsplit("_line", 1)[0], "1,90", "1,90")
# leere neue Heim-Zeile bleibt leer und wird uebersprungen
btn(at, f"pm_save_{kid}").click().run()
e = entry0() if ps.store_path().exists() else {"markets": {}}
check("Speichern (ein Klick): Sieger, Spread, Total und Team Totals (Gast 7 Linien, Heim 1 Linie) in einem Schreibvorgang",
      set(e["markets"]) == {"winner_incl_ot", "spread", "total", "team_totals"} and len(ps.team_total_lines(e, "away")) == 7 and len(ps.team_total_lines(e, "home")) == 1
      and clean(at), str(page_checks.problems(at)) + str(set(e["markets"])))
la = ps.team_total_lines(e, "away")
check("gespeichert: Buchmacher der Zeilen wie in der Zeile (Bet365 manuell, sonst Betano), Vorschlag 'derived' nur an der Hauptlinie",
      sorted({l["bookmaker"] for l in la[1:]}) == ["Bet365", "Betano"] and la[0]["market_suggestion"]["source"] == "derived" and all(l["market_suggestion"] is None for l in la[1:]), str([l["bookmaker"] for l in la]))
at = app().run(); kid = kid_of(at, K); pa, ph = f"pm_ta_{kid}", f"pm_th_{kid}"
check("Neu laden: gespeicherte Team-Linien sortiert und gefuellt, Buchmacher je Zeile wie gespeichert, keine Warnung",
      clean(at) and len(keys(at, kid, "ta")) == 7 and ti(at, f"{pa}_main_over").value == "1,91", str(page_checks.problems(at)))
ti(at, f"{pa}_main_book").input("Pinnacle").run()
check("Buchmacher der Hauptlinie spaeter geaendert: bereits gespeicherte Zeilen bleiben (nicht rueckwirkend)", sorted({ti(at, k.replace("_line", "_book")).value for k in keys(at, kid, "ta") if not k.endswith("_main_line")}) == ["Bet365", "Betano"])
# Duplikat per Eingabe
first_x = [k for k in keys(at, kid, "ta") if not k.endswith("_main_line")][0]
ti(at, first_x).input(ti(at, f"{pa}_main_line").value).run(); btn(at, f"pm_save_{kid}").click().run()
check("Linie per Eingabe auf die Hauptlinie gesetzt: gelbe Warnung mit Team, nichts gespeichert", any("mehrfach" in w.value and "76ers" in w.value for w in at.warning) and len(ps.team_total_lines(entry0(), "away")) == 7, str([w.value for w in at.warning]))
# Entfernen einer gespeicherten Team-Linie (ganze App wird neu geladen)
at = app().run(); kid = kid_of(at, K); pa = f"pm_ta_{kid}"
rid = rid_of([k for k in keys(at, kid, "ta") if not k.endswith("_main_line")][0])
btn(at, f"{pa}_{rid}_rm").click().run()
e = entry0()
check("Entfernen einer gespeicherten Team-Linie: inaktiv + Revision, 6 aktiv, Heim unberuehrt", len(ps.team_total_lines(e, "away")) == 6 and len(ps.team_total_lines(e, "home")) == 1 and sum(1 for x in e["markets"]["team_totals"]["away"]["lines"] if not x["active"]) == 1)
# Rennen
at = app().run(); kid = kid_of(at, K)
b = fsha(ps.store_path()); ti(at, f"pm_ta_{kid}_main_over").input("2,22")
real_now = pmt._now; calls = {"n": 0}
def late_now():
    calls["n"] += 1
    return time.time() if calls["n"] == 1 else time.time() + 4 * H
pmt._now = late_now; btn(at, f"pm_save_{kid}").click().run(); pmt._now = real_now
check("Rennen (Seite offen, Anpfiff vorbei): Speichern abgelehnt, Datei unveraendert", any("begonnen" in w.value for w in at.warning) and fsha(ps.store_path()) == b)
at = app().run()
check("laufendes Spiel: nur Anzeige ('Keine Team-Total-Linie vor dem Anpfiff eingetragen.')", [m for m in at.markdown if "Keine Team-Total-Linie vor dem Anpfiff eingetragen." in m.value])
check("echtes Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
check("echte Tracking-Datei byte-identisch", (real_file.read_bytes() if real_file.exists() else None) == real_bytes)
check("in KEINEM AppTest-Lauf Exception oder 'default value'-Satz", not page_checks.bad, str(page_checks.bad[:3]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
