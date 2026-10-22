"""
NBAEdge – NBA Value Bet Dashboard
Run: streamlit run app.py
"""

import sys

sys.path.insert(0, ".")

import hashlib
import json
import os
import time
from html import escape as html_escape
from collections import defaultdict
from datetime import datetime, date, timedelta

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from dotenv import load_dotenv
from data.nba_live import fetch_live_scoreboard
from data.mock_loader import load_mock_scoreboard
from data.player_stats import (
    fetch_player_last_games,
    fetch_player_season_averages,
    search_players,
)
from data.nba_player_stats import (
    fetch_player_base_stats as fetch_nba_player_base_stats,
    fetch_player_last_games as fetch_nba_player_last_games,
    search_nba_players,
)
from models.elo import EloEngine, build_model
from data.fetcher import fetch_seasons, fetch_upcoming_games
from data import market_lines, pregame_lines
from data import pre_match_store
from data import projection_snapshots
from data.odds import parse_odds
from data.odds_client import credits_info, describe_age, get_odds
from data.injuries import fetch_team_news
from engine.ev import find_value_bets
from engine.projection import compute_projection, is_playoff_date
from engine.player_props import project_player_points_prop
from engine.live import (
    LiveProjectionInput,
    QuarterProjectionInput,
    QuarterTeamTotalInput,
    live_team_total_projection,
    live_quarter_projection,
    live_quarter_team_total_projection,
    over_probability,
    parse_clock_to_seconds,
)
from engine.bias import (
    load_bias_adjustments,
    build_bias_adjustments,
    save_bias_adjustments,
)
from engine.live_context import build_live_context
from engine.live_bet_tracker import get_live_bet_status
from engine.possessions import empty_possessions_default
from ui.live_dashboard import format_clock, render_live_trading_dashboard
from ui.pre_match_tab import render_pre_match_tab
from ui.score_cards import CARD_CSS, build_card_vm, render_card_html, render_line_expanders
from config.settings import (
    SEASONS_TO_LOAD,
    MIN_EV_THRESHOLD,
    BET_TARGETS,
    SHOW_VALUE_BETS,
    ODDS_MIN_CREDITS_RESERVE,
    ODDS_CREDITS_WARN_YELLOW,
    ODDS_LIVE_AUTO_TTL_SECONDS,
    ODDS_TOTALS_TTL_SECONDS,
)
from config.runtime import OFFLINE_AUDIT_MODE

load_dotenv()

st.set_page_config(
    page_title="NBAEdge",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;600;800&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; background-color: #0a0a0f; color: #e8e8f0; }
.main { background-color: #0a0a0f; }
h1, h2, h3 { font-family: 'Space Mono', monospace; }
.ev-badge { display:inline-block; background:#f97316; color:#0a0a0f; font-family:'Space Mono',monospace; font-weight:700; font-size:0.85rem; padding:2px 8px; border-radius:4px; }
.kelly-badge { display:inline-block; background:#22c55e; color:#0a0a0f; font-family:'Space Mono',monospace; font-weight:700; font-size:0.85rem; padding:2px 8px; border-radius:4px; }
.target-badge { display:inline-block; background:#3b82f6; color:#fff; font-family:'Space Mono',monospace; font-weight:700; font-size:0.75rem; padding:2px 6px; border-radius:4px; margin-left:4px; }
.score-card { background:linear-gradient(135deg,#12121e 0%,#1a1a2e 100%); border:1px solid #2a2a4a; border-radius:12px; padding:16px 20px; text-align:center; margin-bottom:8px; }
.score-team { font-size:0.85rem; color:#64748b; font-family:'Space Mono',monospace; margin-bottom:4px; }
.score-pts { font-size:2.2rem; font-family:'Space Mono',monospace; font-weight:700; color:#f97316; }
.info-line { font-size:0.7rem; color:#94a3b8; font-family:'Space Mono',monospace; }
.warn-line { font-size:0.72rem; color:#ef4444; font-family:'Space Mono',monospace; font-weight:700; }
.sharp-tag { font-size:0.7rem; color:#64748b; font-family:'Space Mono',monospace; }
.status-dot { width:8px; height:8px; background:#22c55e; border-radius:50%; display:inline-block; margin-right:6px; animation:pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
.header-logo { font-family:'Space Mono',monospace; font-size:2rem; font-weight:700; color:#f97316; letter-spacing:-1px; }
.no-bets { text-align:center; padding:60px 20px; color:#64748b; font-family:'Space Mono',monospace; }
.bias-card { padding:10px 14px; border:1px solid #2a2a4a; border-radius:10px; margin-bottom:8px; background:#12121e; }
[data-testid="stSidebar"] { background-color:#0d0d1a; border-right:1px solid #2a2a4a; }
[data-testid="stMetric"] { background:#12121e; border:1px solid #2a2a4a; border-radius:10px; padding:12px 16px; }
div[data-testid="stMetricValue"] { font-family:'Space Mono',monospace; font-size:1.8rem; color:#f97316; }
.stButton > button { background:#f97316; color:#0a0a0f; font-family:'Space Mono',monospace; font-weight:700; border:none; border-radius:8px; padding:8px 20px; width:100%; }
.stButton > button:hover { background:#ea6a10; }
</style>
""",
    unsafe_allow_html=True,
)

if "engine" not in st.session_state:
    st.session_state.engine = None
if "value_bets" not in st.session_state:
    st.session_state.value_bets = []
if "projections" not in st.session_state:
    st.session_state.projections = []
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "bias_adjustments" not in st.session_state:
    st.session_state.bias_adjustments = load_bias_adjustments()
if "player_props_loaded_data" not in st.session_state:
    st.session_state.player_props_loaded_data = {}
if "player_props_candidates" not in st.session_state:
    st.session_state.player_props_candidates = []
if "player_props_selected_player" not in st.session_state:
    st.session_state.player_props_selected_player = None
if "nba_player_props_loaded_data" not in st.session_state:
    st.session_state.nba_player_props_loaded_data = {}
if "nba_player_props_candidates" not in st.session_state:
    st.session_state.nba_player_props_candidates = []
if "nba_player_props_selected_player" not in st.session_state:
    st.session_state.nba_player_props_selected_player = None


@st.cache_resource(show_spinner=False, max_entries=2)
def load_or_train_model(model_mtime_ns: int = 0):
    """model_mtime_ns (Aenderungszeit von data/elo_model.pkl) ist nur der Cache-Schluessel: wird die Datei ersetzt
    (z. B. durch update_model.py), ergibt sich ein neuer Schluessel und das Modell wird neu geladen."""
    if EloEngine.exists():
        return EloEngine.load()
    if OFFLINE_AUDIT_MODE:
        return None
    with st.spinner("⚙️ Training ELO model..."):
        games = fetch_seasons(SEASONS_TO_LOAD)
        return build_model(games)


def bk(key):
    return {
        "draftkings": "DraftKings",
        "fanduel": "FanDuel",
        "betmgm": "BetMGM",
        "williamhill_us": "Caesars",
        "bovada": "Bovada",
        "pinnacle": "Pinnacle ⚡",
        "betfair": "Betfair ⚡",
    }.get(key, key.title())


def ev_color(ev):
    if ev >= 8:
        return "#f97316"
    if ev >= 5:
        return "#fb923c"
    if ev >= 3:
        return "#fdba74"
    return "#fde68a"


def match_lines(market_lines: dict, home: str, away: str):
    home_kw = home.split()[-1].lower()
    away_kw = away.split()[-1].lower()
    return market_lines.get((home_kw, away_kw)) or market_lines.get((away_kw, home_kw))


def team_nick(team: str) -> str:
    return team.split()[-1] if team else ""


def fmt_spread(home: str, away: str, spread) -> str:
    """Spread-Anzeige mit Teamname: Favorit mit Minus. spread: positiv = Heimteam ist Favorit."""
    if spread is None:
        return "—"
    spread = round(float(spread), 1)
    if spread == 0:
        return "PK"
    favorite = home if spread > 0 else away
    return f"{team_nick(favorite)} -{abs(spread):.1f}"


def is_game_running(game: dict) -> bool:
    """Laufendes Spiel laut NBA-Scoreboard: ab Periode 1 und nicht 'Final' (Halbzeit zaehlt als laufend)."""
    try:
        period = int(game.get("period") or 0)
    except (TypeError, ValueError):
        period = 0
    return period >= 1 and "final" not in str(game.get("status") or "").lower()


def render_automation_status(slot) -> None:
    """Sidebar: 'Automatik: letzter Lauf <Auftrag> <Zeit>, <Ergebnis>' aus data/automation.log (gelb bei Fehler oder
    wenn ein Auftrag laenger als 36 Std. ohne erfolgreichen Lauf ist). Ohne Protokoll: keine Zeile."""
    from data import automation_log

    status = automation_log.sidebar_status()
    if status is None:
        return
    names = {"update_model": "Ratings", "fetch_odds_daily": "Quoten"}
    result = {"OK": "OK", "SKIP": "übersprungen", "WARN": "Warnung", "ERROR": "Fehler"}[status["result"]]
    text = (
        f"Automatik: letzter Lauf {names.get(status['job'], status['job'])} "
        f"{status['time'].strftime('%d.%m. %H:%M')}, {result}"
        + (f" ({status['detail']})" if status["detail"] else "")
    )
    with slot.container():
        if status["warn"]:
            st.markdown(
                f'<div style="font-size:0.8rem;color:#facc15;font-weight:600">{html_escape(text)}<br>'
                f"⚠ {html_escape(status['hint'])}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption(text)


def render_odds_status(slot) -> None:
    """Sidebar: Alter der Quoten und Odds-API-Credits (gelb unter 100, rot unter Reserve 50)."""
    entry = get_odds("totals_spreads", caller="sidebar.status", cache_only=True)
    info = credits_info()
    with slot.container():
        if entry.data is not None:
            note = f"Quoten von {describe_age(entry.age)}"
            if entry.stale:
                note += f" (älter als {ODDS_TOTALS_TTL_SECONDS // 60} Min.; „Refresh Odds“ lädt neu)"
            st.caption(note)
        else:
            st.caption("Noch keine Quoten geladen.")
        remaining = info["remaining"]
        if remaining is None:
            st.caption("Odds API: Credits noch unbekannt")
        else:
            color = "#f87171" if remaining < ODDS_MIN_CREDITS_RESERVE else "#facc15" if remaining < ODDS_CREDITS_WARN_YELLOW else "#d7deec"
            st.markdown(
                f'<div style="font-size:0.8rem;color:{color};font-weight:600">Odds API: noch {remaining} Credits</div>',
                unsafe_allow_html=True,
            )
            if info["low"]:
                st.warning(
                    f"Odds-API-Credits unter der Reserve ({ODDS_MIN_CREDITS_RESERVE}): keine automatischen Abrufe mehr. "
                    "„Refresh Odds“ ruft weiterhin manuell ab und verbraucht Credits."
                )


def flat_html(html: str) -> str:
    """HTML ohne Einrueckung und Leerzeilen: Streamlit-Markdown beendet einen HTML-Block bei einer
    Leerzeile und deutet danach eingerueckte Zeilen (>= 4 Leerzeichen) als Codeblock."""
    return "".join(line.strip() for line in html.splitlines())


def build_mock_projections():
    games = load_mock_scoreboard()
    projections = []

    for game in games:
        home = f"{game.get('home_city', '')} {game.get('home_team', '')}".strip()
        away = f"{game.get('away_city', '')} {game.get('away_team', '')}".strip()
        home_score = int(game.get("home_score") or 0)
        away_score = int(game.get("away_score") or 0)
        total = home_score + away_score
        spread = home_score - away_score

        projections.append(
            {
                "home_team": home,
                "away_team": away,
                "home_score": home_score,
                "away_score": away_score,
                "home_win_prob": 0.55 if home_score >= away_score else 0.45,
                "away_win_prob": 0.45 if home_score >= away_score else 0.55,
                "exp_total": total,
                "exp_spread": spread,
                "model_total": total,
                "market_total": 225.5,
                "market_spread": 2.5,
                "market_diff": round(total - 225.5, 1),
                "market_weight": 0.0,
                "lineup_warning": False,
                "is_playoff": is_playoff_date(date.today().isoformat()),
                "home_bias_adjustment": 0.0,
                "away_bias_adjustment": 0.0,
                "game_date": date.today().isoformat(),
                "total_over_odds": None,
                "total_under_odds": None,
                "spread_home_odds": None,
                "spread_away_odds": None,
                "home_team_total": None,
                "away_team_total": None,
            }
        )

    return projections


def build_mock_value_bets():
    games = load_mock_scoreboard()
    if not games:
        return []

    game = games[0]
    home = f"{game.get('home_city', '')} {game.get('home_team', '')}".strip()
    away = f"{game.get('away_city', '')} {game.get('away_team', '')}".strip()
    return [
        {
            "home_team": home,
            "away_team": away,
            "commence_time": datetime.now().isoformat(),
            "bookmaker": "pinnacle",
            "bet_on": away,
            "side": "away",
            "decimal_odds": 1.91,
            "blended_prob": 0.56,
            "ev_pct": 7.0,
            "kelly_pct": 1.5,
            "sharp_source": "OFFLINE_MOCK",
        }
    ]


def _resolve_lines(inp: dict, entries: dict, now: float) -> dict:
    """Eine Marktlinie je Markt (eigene Eingabe oder Cache, die neuere gewinnt): data/market_lines.py."""
    entry = entries.get(inp["entry_key"])
    return market_lines.resolve_market_lines(entry, inp["cache_lines"], inp["cache_at"], inp["cache_source"], inp["home"], inp["away"])


def _set_line_fields(proj: dict, inp: dict, resolved: dict) -> None:
    """Linienfelder im Projektionsergebnis (Quelle/Zeitpunkt der benutzten Linie; werden spaeter im Schnappschuss gespeichert)."""
    proj["market_total"], proj["market_spread"] = market_lines.projection_inputs(resolved)
    proj["cache_market_total"] = (inp["cache_lines"] or {}).get("total")      # fuer den Vorschlag im Pre-Match-Tab (nie die eigene Linie)
    proj["cache_market_spread"] = (inp["cache_lines"] or {}).get("spread")
    proj["market_source"] = inp["cache_source"]                               # Quelle der Cache-Linie: 'cache_vorab', 'gespeichert' oder None
    proj["market_lines"] = resolved
    proj["_lines_key"] = market_lines.resolution_key(resolved)


def apply_market_lines(projections: list[dict], now: float | None = None) -> int:
    """Aktualisiert die Linien der Projektionen, wenn sich die Pre-Match-Datei (Aenderungszeit) geaendert hat.
    Kein API-Abruf. Neu berechnet wird nur das Spiel, dessen Eingangslinie (Total/Spread) sich geaendert hat. Rueckgabe: Zahl neu berechneter Spiele."""
    now = now if now is not None else time.time()
    entries = market_lines.load_entries()
    recomputed = 0
    for proj in projections:
        inp = proj.get("_line_inputs")
        if not inp:
            continue
        resolved = _resolve_lines(inp, entries, now)
        if market_lines.resolution_key(resolved) == proj.get("_lines_key"):
            continue
        total, spread = market_lines.projection_inputs(resolved)
        if (total, spread) != (proj.get("market_total"), proj.get("market_spread")):
            proj.update(compute_projection(inp["pred"], market_total=total, market_spread=spread, game_date=inp["game_date"],
                                           bias_adjustments=st.session_state.bias_adjustments))
            recomputed += 1
        _set_line_fields(proj, inp, resolved)
    return recomputed


def refresh_data(engine, refresh=False):
    """Projektionen (und ggf. Value Bets) neu aufbauen.

    Odds-API: refresh=True nur durch den Knopf 'Refresh Odds'. Beim App-Start (refresh=False) wird nur
    abgefragt, wenn es noch gar keinen Cache gibt; sonst kommen die Quoten aus data/odds_cache.json."""
    if OFFLINE_AUDIT_MODE:
        return build_mock_value_bets(), build_mock_projections()

    caller = "app.refresh_data:" + ("button" if refresh else "start")

    # Moneyline (h2h) nur fuer den Tab Value Bets. Projektionen brauchen sie nicht.
    odds_games = []
    if SHOW_VALUE_BETS:
        with st.spinner("Fetching live odds..."):
            res_h2h = get_odds("h2h", caller=caller, refresh=refresh)
            if res_h2h.error and not res_h2h.data:
                st.error(res_h2h.error)
            if res_h2h.data:
                odds_games = parse_odds(res_h2h.data)

    with st.spinner("Fetching totals & spreads..."):
        res_ts = get_odds("totals_spreads", caller=caller, refresh=refresh)
        if res_ts.error and not res_ts.data:
            st.warning(f"Totals/Spreads nicht geladen: {res_ts.error}")
        # Projektion nur mit VORAB-Linien (vor dem Anpfiff): siehe data/pregame_lines.py
        odds_events = res_ts.data or []
        odds_fetched_at = res_ts.fetched_at
        if odds_events and odds_fetched_at:
            pregame_lines.update_from_snapshot(odds_events, odds_fetched_at)

    with st.spinner("Fetching upcoming games..."):
        try:
            upcoming = fetch_upcoming_games()
        except Exception as e:
            st.error(f"BallDontLie: {e}")
            upcoming = []

    predictions, projections = [], []
    for game in upcoming:
        home = game["home_team"]["full_name"]
        away = game["visitor_team"]["full_name"]
        try:
            game_date = game.get("date") or date.today().isoformat()
            pred = engine.predict(home, away, date.today())
            predictions.append(pred)
            lines, line_source, line_at = pregame_lines.line_for_game_ex(
                odds_events,
                odds_fetched_at,
                home,
                away,
                game_start=pregame_lines.parse_utc(game.get("datetime")),
            )
            # Eine Marktlinie je Markt: eigene Eingabe (Pre-Match Eingabe) oder Cache, die neuere gewinnt (data/market_lines.py)
            inp = {"pred": pred, "home": home, "away": away, "game_date": game_date, "game_start": game.get("datetime"),
                   "cache_lines": lines, "cache_source": line_source, "cache_at": line_at,
                   "entry_key": pre_match_store.game_key(game_date, game.get("datetime"), home, away)}
            resolved = _resolve_lines(inp, market_lines.load_entries(), time.time())
            market_total, market_spread = market_lines.projection_inputs(resolved)
            proj = compute_projection(
                pred,
                market_total=market_total,
                market_spread=market_spread,
                game_date=game_date,
                bias_adjustments=st.session_state.bias_adjustments,
            )
            proj["game_date"] = game_date
            proj["game_start"] = game.get("datetime")  # Anpfiff (UTC, BallDontLie) fuer den Tab Pre-Match Eingabe
            proj["game_status"] = game.get("status")
            proj["_line_inputs"] = inp
            _set_line_fields(proj, inp, resolved)   # market_total/market_spread, Cache-Linien, market_source, market_lines
            proj["total_over_odds"] = lines.get("total_over_odds") if lines else None
            proj["total_under_odds"] = lines.get("total_under_odds") if lines else None
            proj["spread_home_odds"] = lines.get("spread_home_odds") if lines else None
            proj["spread_away_odds"] = lines.get("spread_away_odds") if lines else None
            tt = lines.get("team_totals", {}) if lines else {}
            proj["home_team_total"] = next(
                (v for k, v in tt.items() if home.split()[-1].lower() in k.lower()),
                None,
            )
            proj["away_team_total"] = next(
                (v for k, v in tt.items() if away.split()[-1].lower() in k.lower()),
                None,
            )
            projections.append(proj)
        except Exception as e:
            st.warning(f"Projection übersprungen: {away} @ {home}: {e}")

    value_bets = find_value_bets(predictions, odds_games) if (SHOW_VALUE_BETS and odds_games) else []
    return value_bets, projections


@st.cache_data(ttl=3600)
def fetch_completed_games(days_back: int):
    if OFFLINE_AUDIT_MODE:
        games = []
        for game in load_mock_scoreboard():
            games.append(
                {
                    "_display_date": date.today().isoformat(),
                    "status": "Final",
                    "home_team": {
                        "full_name": f"{game.get('home_city', '')} {game.get('home_team', '')}".strip()
                    },
                    "visitor_team": {
                        "full_name": f"{game.get('away_city', '')} {game.get('away_team', '')}".strip()
                    },
                    "home_team_score": int(game.get("home_score") or 0),
                    "visitor_team_score": int(game.get("away_score") or 0),
                }
            )
        return games

    api_key = os.getenv("BALLDONTLIE_API_KEY")
    headers = {"Authorization": api_key}
    all_games = []
    for days_ago in range(1, days_back + 1):
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        for attempt in range(3):
            r = requests.get(
                "https://api.balldontlie.io/v1/games",
                headers=headers,
                params={"dates[]": d, "per_page": 100},
                timeout=15,
            )
            if r.status_code == 429:
                time.sleep(8 * (attempt + 1))
                continue
            if r.status_code == 200:
                games = [
                    g for g in r.json().get("data", []) if g.get("status") == "Final"
                ]
                for g in games:
                    g["_display_date"] = d
                all_games.extend(games)
            break
        time.sleep(0.7)
    return all_games


# Modell neu laden, wenn data/elo_model.pkl ersetzt wurde (z. B. durch update_model.py): bei jedem Rerun nur os.stat.
# Das Modell steckt in st.session_state.engine UND im @st.cache_resource, beides wird hier erneuert.
_model_mtime = EloEngine.model_mtime_ns()
# Feste Stelle fuer alles, was nur in manchen Laeufen Elemente erzeugt (Lade-Spinner, Hinweise beim Modell-/Datenladen). Der Container ist in JEDEM
# Lauf vorhanden: so verschiebt sich nichts oberhalb der Tabs, und Streamlit baut die Tabs (und damit die Expander darin) bei einem Rerun nicht neu auf.
_boot_slot = st.container()
if (
    st.session_state.engine is not None
    and _model_mtime
    and st.session_state.get("engine_mtime") not in (None, _model_mtime)
):
    with _boot_slot:
        st.session_state.engine = load_or_train_model(_model_mtime)
    st.session_state.engine_mtime = _model_mtime
    st.session_state.last_refresh = None  # Projektionen mit den neuen Ratings neu aufbauen (Cache, keine Credits)

with st.sidebar:
    st.markdown(
        '<div class="header-logo">NBA<span style="color:#e8e8f0">Edge</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown("*Systematic edge detection*")
    st.divider()
    if OFFLINE_AUDIT_MODE:
        st.markdown("🧪 Offline Audit Mode")
        st.caption("Mock data only. External requests disabled.")
        st.divider()

    if EloEngine.exists():
        st.success("✓ ELO Model loaded")
        _as_of = load_or_train_model(EloEngine.model_mtime_ns()).ratings_as_of()
        st.caption(
            f"Ratings bis: {_as_of.strftime('%d.%m.%Y')} (US-Spieldatum)"
            if _as_of
            else "Ratings bis: unbekannt"
        )
    else:
        st.warning("Model not trained")

    if st.button("🔄 Refresh Odds"):
        if st.session_state.engine or OFFLINE_AUDIT_MODE:
            bets, projs = refresh_data(st.session_state.engine, refresh=True)
            st.session_state.value_bets = bets
            st.session_state.projections = projs
            st.session_state.last_refresh = datetime.now()

    if st.session_state.last_refresh:
        st.caption(f"Last update: {st.session_state.last_refresh.strftime('%H:%M:%S')}")
    odds_status_slot = st.empty()  # Quoten-Alter und Credits, am Ende des Skripts gefuellt
    automation_slot = st.empty()  # letzter Lauf der geplanten Auftraege (data/automation.log)

    # Filter nur fuer den Tab Value Bets (config/settings.py: SHOW_VALUE_BETS)
    if SHOW_VALUE_BETS:
        st.divider()
        st.markdown("**Filters**")
        min_ev = st.slider("Min EV %", 1, 15, int(MIN_EV_THRESHOLD * 100), 1)
        min_odds = st.number_input("Min Odds", 1.0, 5.0, 1.5, 0.1)
        max_odds = st.number_input("Max Odds", 1.5, 10.0, 3.5, 0.1)
        all_books = [
            "pinnacle",
            "betfair",
            "draftkings",
            "fanduel",
            "betmgm",
            "williamhill_us",
            "bovada",
        ]
        selected_books = st.multiselect(
            "Bookmakers", all_books, default=all_books, format_func=bk
        )
        targets_only = st.checkbox("⚡ Bet Targets only (Pinnacle / Betfair)", value=False)
    else:
        # Standardwerte, damit Code, der diese Variablen liest, nicht bricht
        min_ev = int(MIN_EV_THRESHOLD * 100)
        min_odds = 1.5
        max_odds = 3.5
        selected_books = []
        targets_only = False

    st.divider()
    st.markdown("**Model Info**")
    st.caption(f"Seasons: {SEASONS_TO_LOAD[0]}–{SEASONS_TO_LOAD[-1]}")
    st.caption(f"Self-correction teams: {len(st.session_state.bias_adjustments)}")
    if SHOW_VALUE_BETS:
        st.caption("Sharp ref: Pinnacle / Betfair")


if st.session_state.engine is None:
    with _boot_slot:
        st.session_state.engine = load_or_train_model(_model_mtime)
    st.session_state.engine_mtime = _model_mtime
engine = st.session_state.engine

if st.session_state.last_refresh is None and (engine or OFFLINE_AUDIT_MODE):
    with _boot_slot:
        bets, projs = refresh_data(engine)
    st.session_state.value_bets = bets
    st.session_state.projections = projs
    st.session_state.last_refresh = datetime.now()

# Pre-Match-Datei geaendert (oder Spiel gestartet)? Dann die Linien der betroffenen Spiele neu aufloesen (kein API-Abruf)
apply_market_lines(st.session_state.projections)

# Schnappschuss der Projektion vor dem Anpfiff (nur Spiele, die noch nicht begonnen haben, nur bei geaendertem Inhalt; kein API-Abruf) und Ergebnisse,
# die lokal schon bekannt sind (upcoming_cache). Ein Fehler hier darf die Seite nie stoeren.
try:
    projection_snapshots.record_snapshots(st.session_state.projections, market_lines.load_entries(), engine=engine)
    projection_snapshots.fill_results_from_upcoming_cache()
except Exception as _snap_err:
    print(f"Schnappschuss nicht gespeichert: {type(_snap_err).__name__}: {_snap_err}")

filtered_bets = [
    b
    for b in st.session_state.value_bets
    if b["ev_pct"] >= min_ev
    and min_odds <= b["decimal_odds"] <= max_odds
    and (not selected_books or b["bookmaker"] in selected_books)
    and (not targets_only or b["bookmaker"] in BET_TARGETS)
]

_tab_labels = [
    "📊 Score Projections",
    "🔴 Live Projection",
    "🎯 Live Bet Tracker",
    "📰 Lineup News",
    "📅 History",
    "📈 ELO Rankings",
    "✍️ Pre-Match Eingabe",
]
if SHOW_VALUE_BETS:
    tab1, tab2, tab3, live_bet_tab, tab4, tab5, tab6, tab_pre_match = st.tabs(["🎯 Value Bets"] + _tab_labels)
else:
    tab1 = None  # Tab Value Bets ausgeblendet (config/settings.py: SHOW_VALUE_BETS)
    tab2, tab3, live_bet_tab, tab4, tab5, tab6, tab_pre_match = st.tabs(_tab_labels)

if tab1 is not None:
    with tab1:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown("## 🏀 Value Bet Scanner")
        with c2:
            if st.session_state.last_refresh:
                st.markdown(
                    '<span class="status-dot"></span><small>Live</small>',
                    unsafe_allow_html=True,
                )

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Value Bets", len(filtered_bets))
        with m2:
            st.metric(
                "Avg EV %",
                f"{round(sum(b['ev_pct'] for b in filtered_bets)/len(filtered_bets),1) if filtered_bets else 0}%",
            )
        with m3:
            st.metric(
                "Best EV %", f"{max((b['ev_pct'] for b in filtered_bets), default=0)}%"
            )
        with m4:
            st.metric(
                "⚡ Bet Targets",
                len([b for b in filtered_bets if b["bookmaker"] in BET_TARGETS]),
            )

        st.divider()
        if not filtered_bets:
            st.markdown(
                '<div class="no-bets"><div style="font-size:3rem">🏀</div><div style="margin-top:16px">No value bets found</div></div>',
                unsafe_allow_html=True,
            )
        else:
            games = {}
            for b in filtered_bets:
                games.setdefault((b["home_team"], b["away_team"]), []).append(b)
            for (home, away), bets in games.items():
                best = bets[0]
                commence = datetime.fromisoformat(
                    best["commence_time"].replace("Z", "+00:00")
                )
                with st.expander(
                    f"🏀 {away} @ {home} · {commence.strftime('%a %b %d, %H:%M')} · {len(bets)} edge(s)",
                    expanded=True,
                ):
                    for bet in bets:
                        is_target = bet["bookmaker"] in BET_TARGETS
                        bc1, bc2, bc3, bc4, bc5 = st.columns([2, 1, 1, 1, 1])
                        with bc1:
                            target_html = (
                                '<span class="target-badge">⚡ BET HERE</span>'
                                if is_target
                                else ""
                            )
                            st.markdown(
                                f"**{bet['bet_on']}** `{'HOME' if bet['side']=='home' else 'AWAY'}` {target_html}",
                                unsafe_allow_html=True,
                            )
                            st.markdown(
                                f'<span class="sharp-tag">via {bk(bet["bookmaker"])} · Sharp: {bet["sharp_source"]}</span>',
                                unsafe_allow_html=True,
                            )
                        with bc2:
                            st.caption("Odds")
                            st.markdown(f"**{bet['decimal_odds']}**")
                        with bc3:
                            st.caption("Blended Prob")
                            st.markdown(f"**{round(bet['blended_prob']*100,1)}%**")
                        with bc4:
                            st.caption("EV")
                            st.markdown(
                                f'<span class="ev-badge" style="background:{ev_color(bet["ev_pct"])}">+{bet["ev_pct"]}%</span>',
                                unsafe_allow_html=True,
                            )
                        with bc5:
                            st.caption("Kelly")
                            st.markdown(
                                f'<span class="kelly-badge">{bet["kelly_pct"]}%</span>',
                                unsafe_allow_html=True,
                            )

with tab2:
    st.markdown("## 📊 Score Projections")
    st.caption(
        "Endprojektion = Modell + Vegas-Mischung + Playoff-Modifikator + gespeicherte Team-Bias-Korrektur."
    )
    projections = st.session_state.projections
    _fin_all = projection_snapshots.finished_cards(exclude={str((p_.get("_line_inputs") or {}).get("entry_key") or p_["home_team"]) for p_ in projections})
    if not projections and not _fin_all:
        st.markdown(
            '<div class="no-bets"><div style="font-size:3rem">📊</div><div style="margin-top:16px">Keine Spiele gefunden</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(flat_html(CARD_CSS), unsafe_allow_html=True)
        # Stabile Identitaet je Spiel: Streamlit ordnet den Auf/Zu-Zustand der Expander ueber die POSITION im Elementbaum zu. Wuerde die Sortierung nach |Spread|
        # (z. B. nach Refresh Odds oder neuer Eigenlinie) die Karten im Baum umstellen, wanderte der Zustand zu einem anderen Spiel. Darum steht jede Karte in einem
        # Container mit festem Schluessel je Spiel in FESTER Reihenfolge (nach Spiel-Schluessel); die sichtbare Sortierung nach |Spread| macht CSS (order).
        _gkey = lambda p_: str((p_.get("_line_inputs") or {}).get("entry_key") or p_["home_team"])
        _hash = lambda p_: hashlib.md5(_gkey(p_).encode("utf-8")).hexdigest()[:10]
        _rank = {_hash(p_): i + 1 for i, p_ in enumerate(sorted(projections, key=lambda x: -abs(x["exp_spread"])))}
        _fin_hashes = [hashlib.md5(f_["key"].encode("utf-8")).hexdigest()[:10] for f_ in _fin_all]
        _rank.update({h_: len(_rank) + 1 + i for i, h_ in enumerate(_fin_hashes)})       # beendete Spiele (aus dem Schnappschuss) stehen unter den uebrigen
        st.markdown("<style>" + "".join(f"div:has(> .st-key-sc_game_{h}){{order:{r};}}" for h, r in _rank.items()) + "</style>", unsafe_allow_html=True)
        with st.container(key="sc_cards"):
            for proj in sorted(projections, key=_gkey):
                _vm = build_card_vm(proj, entry=market_lines.load_entries().get((proj.get("_line_inputs") or {}).get("entry_key")))
                with st.container(key=f"sc_game_{_hash(proj)}"):
                    st.markdown(flat_html(render_card_html(_vm)), unsafe_allow_html=True)
                    # SPREAD / TOTAL / TEAM TOTAL Gast / Heim: Expander direkt unter der Karte
                    render_line_expanders(_vm, _hash(proj))
            # Beendete Spiele mit Schnappschuss und Ergebnis (BallDontLie liefert beendete Spiele nicht mehr): Karte und Zeilen aus dem gespeicherten Schnappschuss,
            # mit Chips "eingetreten / nicht eingetreten". Nur zusaetzliche Karten am Ende; nichts wird neu berechnet.
            for _fin in _fin_all:
                _fh = hashlib.md5(_fin["key"].encode("utf-8")).hexdigest()[:10]
                _fvm = build_card_vm(_fin["card"], tables=_fin["tables"], result=_fin["result"])
                with st.container(key=f"sc_game_{_fh}"):
                    st.markdown(flat_html(render_card_html(_fvm)), unsafe_allow_html=True)
                    render_line_expanders(_fvm, _fh)

with tab3:
    st.markdown("## 🔴 Live Projection Engine")

    live_source_options = ["MOCK"] if OFFLINE_AUDIT_MODE else ["LIVE", "MOCK"]
    replay_mode = False
    replay_minutes = None
    selected_live_game = None

    source_col, game_col = st.columns([1, 2.4])
    with source_col:
        live_source = st.radio(
            "Datenquelle",
            live_source_options,
            horizontal=True,
            label_visibility="collapsed",
            help="LIVE nutzt NBA.com. MOCK nutzt gespeicherte Testdaten aus data/mock.",
        )

    try:
        if live_source == "LIVE":
            live_games = fetch_live_scoreboard()
        else:
            live_games = load_mock_scoreboard()
    except Exception as e:
        st.warning(f"{live_source}-Daten konnten nicht geladen werden: {e}")
        live_games = []

    with game_col:
        if live_games:
            selected_live_game = st.selectbox(
                "Live-Spiel auswählen",
                live_games,
                label_visibility="collapsed",
                format_func=lambda g: (
                    f"{g['away_city']} {g['away_team']} {g['away_score']} @ "
                    f"{g['home_city']} {g['home_team']} {g['home_score']} · "
                    f"{g['status']}"
                ),
            )
        else:
            st.caption("Keine Live Games gefunden")

    if live_source == "MOCK":
        replay_col, replay_slider_col = st.columns([1, 2.4])
        with replay_col:
            replay_mode = st.toggle(
                "Replay-Modus",
                value=False,
                help="Simuliert das Spiel Schritt für Schritt.",
            )
        with replay_slider_col:
            if replay_mode:
                replay_minutes = st.slider(
                    "Replay-Zeitpunkt (Spielminute)",
                    min_value=0,
                    max_value=48,
                    value=24,
                    step=1,
                    label_visibility="collapsed",
                )

    # Live-Linien (Odds API): Abruf nur bei laufendem, ausgewaehltem Spiel UND nur auf Knopfdruck
    # (oder bei eingeschaltetem Auto-Refresh). Das Dashboard darunter liest die Linien nur aus dem Cache.
    if live_source == "LIVE":
        live_running = selected_live_game is not None and is_game_running(selected_live_game)
        ll_btn_col, ll_auto_col = st.columns([1, 1.6])
        with ll_btn_col:
            live_lines_clicked = st.button(
                "Live-Linien aktualisieren",
                key="live_lines_refresh",
                disabled=not live_running,
                help="Ruft die Linien einmal bei der Odds API ab (4 Credits).",
            )
        with ll_auto_col:
            live_lines_auto = st.toggle(
                "Auto-Refresh Live-Linien",
                value=False,
                key="live_lines_auto",
                help=(
                    "Verbraucht Credits: 4 pro Abruf. Bei eingeschaltetem Schalter werden die Linien bei jeder "
                    f"Interaktion neu abgefragt, sobald der Zwischenspeicher älter als {ODDS_LIVE_AUTO_TTL_SECONDS // 60} Min. ist "
                    "(nur bei laufendem Spiel und über der Credit-Reserve)."
                ),
            )
        if not live_running:
            st.caption("Kein laufendes Spiel ausgewählt: keine Odds-API-Abrufe.")
        else:
            if live_lines_clicked:
                _res = get_odds("totals_spreads", caller="live_tab:button", refresh=True)
            elif live_lines_auto:
                _res = get_odds("totals_spreads", caller="live_tab:auto", max_age=ODDS_LIVE_AUTO_TTL_SECONDS)
            else:
                _res = get_odds("totals_spreads", caller="live_tab:status", cache_only=True)
            if _res.error and not _res.data:
                st.warning(f"Live-Linien nicht geladen: {_res.error}")
            if live_lines_auto:
                st.caption("Auto-Refresh ist an und verbraucht Credits.")
            st.caption(
                f"Live-Linien von {describe_age(_res.age)}" if _res.data is not None else "Noch keine Linien im Zwischenspeicher."
            )

    if live_games:
        with st.expander("▼ LIVE TRADING DASHBOARD", expanded=False):
            render_live_trading_dashboard(
                live_games,
                live_source,
                replay_mode=replay_mode,
                replay_minute=replay_minutes,
            )

        st.markdown("### 🏀 NBA Live Games")

        for g in live_games:
            game_status = f"Q{g['period']} · {format_clock(g['clock'])}"
            st.markdown(
                f"""
                <div style='background:#111827;border:1px solid #2b3550;border-radius:10px;padding:9px 12px;margin-bottom:8px;'>
                    <div style='color:#e8e8f0;font-family:Space Mono,monospace;font-size:0.92rem;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3;'>
                        {g['away_city']} {g['away_team']} {g['away_score']} @ {g['home_city']} {g['home_team']} {g['home_score']}
                        <span style='display:inline-block;margin:0 10px;color:#64748b;'>•</span>
                        <span style='color:#f97316;'>{game_status}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info(
            "Keine NBA Live Games gefunden. Du kannst die Live Projection trotzdem manuell nutzen."
        )

    live_mode = st.radio(
        "Live-Modus",
        ["Team Total Over", "Quarter Over/Under", "Quarter Team Total"],
        horizontal=True,
    )

    teams = []
    for p in st.session_state.projections:
        teams.extend([p["away_team"], p["home_team"]])

    if selected_live_game:
        live_away_full = (
            f"{selected_live_game['away_city']} {selected_live_game['away_team']}"
        )
        live_home_full = (
            f"{selected_live_game['home_city']} {selected_live_game['home_team']}"
        )
        teams.extend([live_away_full, live_home_full])
    else:
        live_away_full = None
        live_home_full = None

    teams = sorted(set(teams))

    pace_options = ["slow", "normal", "fast", "chaotic"]
    game_state_options = ["close", "normal", "blowout"]

    try:
        live_context = build_live_context(
            selected_live_game,
            live_source,
            replay_mode=replay_mode,
            replay_minute=replay_minutes,
        )

    except Exception as e:
        st.caption(f"Live/Replay Analyse übersprungen: {e}")
        live_context = build_live_context(None, live_source)

    default_quarter = int(live_context.get("quarter") or 1)
    default_clock = live_context.get("clock") or "12:00"
    default_home_points = int(live_context.get("score_home") or 0)
    default_away_points = int(live_context.get("score_away") or 0)
    default_team = live_home_full or (teams[0] if teams else "OKC")
    default_q_points = live_context.get("q_points") or {}
    default_home_q_points = int(default_q_points.get("home_q_points") or 0)
    default_away_q_points = int(default_q_points.get("away_q_points") or 0)
    default_quarter_total = int(default_q_points.get("quarter_total") or 0)
    default_game_state = live_context.get("game_state") or "normal"
    default_game_state_index = (
        game_state_options.index(default_game_state)
        if default_game_state in game_state_options
        else game_state_options.index("normal")
    )
    default_pace_mode = live_context.get("pace_mode") or "normal"
    default_pace_index = (
        pace_options.index(default_pace_mode)
        if default_pace_mode in pace_options
        else pace_options.index("normal")
    )
    foul_trouble = live_context.get("foul_trouble") or []
    replay_foul_state = live_context.get("replay_foul_state") or {
        "player_fouls": {},
        "team_fouls": {},
    }
    live_team_foul_state = live_context.get("team_fouls") or {
        "home_team_fouls": 0,
        "away_team_fouls": 0,
        "team_fouls_by_tricode": {},
    }
    recent_pbp_summary = live_context.get("recent_pbp_summary") or {}
    context_possession_summary = live_context.get("possession_summary") or {}
    possession_summary = (
        live_context.get("possession_summary") or {}
        if replay_mode
        else {}
    )
    momentum_summary = (
        live_context.get("momentum_summary") or {}
        if replay_mode
        else {}
    )
    live_boxscore = live_context.get("live_boxscore") or {}

    def live_team_tricode(side: str):
        team = live_boxscore.get(side, {}) if live_boxscore else {}
        return team.get("teamTricode")

    def team_fouls_for(team_tricode, quarter):
        if not team_tricode:
            return 2

        if int(quarter) == int(default_quarter):
            fouls_by_tricode = live_team_foul_state.get("team_fouls_by_tricode", {})
            return int(fouls_by_tricode.get(team_tricode, 0))

        quarter_fouls = replay_foul_state.get("team_fouls", {}).get(int(quarter), {})
        return int(quarter_fouls.get(team_tricode, 0))

    def opponent_fouls_for(team_name, quarter):
        if not selected_live_game:
            return 2

        home_tricode = live_team_tricode("homeTeam")
        away_tricode = live_team_tricode("awayTeam")

        if team_name == live_home_full:
            return team_fouls_for(away_tricode, quarter)
        if team_name == live_away_full:
            return team_fouls_for(home_tricode, quarter)

        return 2

    def possession_pace_per_48():
        if not possession_summary:
            return None
        return possession_summary.get("pace_per_48")

    def possession_empty_count():
        if not possession_summary:
            return 0
        if possession_summary.get("empty_possessions_recent") is not None:
            return int(possession_summary.get("empty_possessions_recent") or 0)
        return int(possession_summary.get("empty_possessions") or 0)

    def default_empty_possessions_recent():
        return empty_possessions_default(context_possession_summary)

    def possession_off_rating_for_team(team_name):
        if not possession_summary:
            return None
        if team_name == live_home_full:
            return possession_summary.get("home_off_rating")
        if team_name == live_away_full:
            return possession_summary.get("away_off_rating")
        return None

    def selected_team_side(team_name):
        if team_name == live_home_full:
            return "home"
        if team_name == live_away_full:
            return "away"
        return None

    def default_bonus_for_team(team_name) -> bool:
        side = selected_team_side(team_name)
        if side == "home":
            return bool(live_context.get("bonus_home"))
        if side == "away":
            return bool(live_context.get("bonus_away"))
        return False

    def default_opponent_bonus_for_team(team_name) -> bool:
        side = selected_team_side(team_name)
        if side == "home":
            return bool(live_context.get("bonus_away"))
        if side == "away":
            return bool(live_context.get("bonus_home"))
        return False

    def default_run_state_for_team(team_name):
        side = selected_team_side(team_name)
        if side:
            by_side = live_context.get("run_state_by_side") or {}
            return by_side.get(side) or live_context.get("run_state") or {}
        return live_context.get("run_state") or {}

    def possession_avg_off_rating():
        if not possession_summary:
            return None

        ratings = []
        for key in ["home_off_rating", "away_off_rating"]:
            value = possession_summary.get(key)
            if value is not None:
                ratings.append(float(value))

        if not ratings:
            return None
        return sum(ratings) / len(ratings)

    def momentum_signal():
        if not momentum_summary:
            return "STABLE"
        return momentum_summary.get("momentum_signal") or "STABLE"

    def momentum_factor():
        if not momentum_summary:
            return 1.0
        return float(momentum_summary.get("momentum_factor") or 1.0)

    def live_factor_label(result: dict) -> str:
        confidence = int(result.get("confidence_score") or 0)
        if confidence >= 80:
            return "🔥 Strong live signal"
        if confidence <= 35:
            return "⚠️ Unstable projection"
        return ""

    def edge_label(result: dict) -> str:
        signal = result.get("edge_signal")
        return {
            "STRONG_OVER_EDGE": "🔥 Strong Over Edge",
            "STRONG_UNDER_EDGE": "❄️ Strong Under Edge",
            "TRAP_OVER": "⚠️ Trap Over Risk",
            "UNSTABLE": "⚠️ Unstable Market",
        }.get(signal, "")

    if foul_trouble:
        with st.expander("▶ FOUL TROUBLE", expanded=False):
            for f in foul_trouble:
                st.markdown(
                    f"""
                    <div style='background:#2a1111;border:1px solid #7f1d1d;border-radius:10px;padding:10px 12px;margin-bottom:8px;'>
                        <div style='font-weight:700;color:#fecaca;'>
                            {f['severity']} · {f['player']} · {f['team']}
                        </div>
                        <div class='info-line'>
                            Fouls: {f['fouls']} · Points: {f['points']} · Starter: {f['starter']} · On court: {f['oncourt']}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    if recent_pbp_summary:
        with st.expander("▶ RECENT PLAY-BY-PLAY SIGNAL", expanded=False):
            st.markdown(
                f"""
                <div style='background:#111827;border:1px solid #334155;border-radius:10px;padding:10px 12px;margin-bottom:8px;'>
                    <div style='font-weight:700;color:#e8e8f0;'>
                        Signal: {recent_pbp_summary['pace_signal']}
                    </div>
                    <div class='info-line'>
                        Actions: {recent_pbp_summary['actions']} ·
                        Fouls: {recent_pbp_summary['fouls']} ·
                        Turnovers: {recent_pbp_summary['turnovers']} ·
                        Free Throws: {recent_pbp_summary['free_throws']} ·
                        Points: {recent_pbp_summary['points']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if replay_mode and possession_summary:
                st.markdown(
                    f"""
                    <div style='background:#101923;border:1px solid #256f8f;border-radius:10px;padding:10px 12px;margin-bottom:8px;'>
                        <div style='font-weight:700;color:#bae6fd;'>
                            🏀 Possession Engine
                        </div>
                        <div class='info-line'>
                            Total Possessions: {possession_summary['total_possessions']} ·
                            Avg Possessions: {possession_summary['average_possessions']} ·
                            Pace/48: {possession_summary['pace_per_48']} ·
                            Empty Recent: {possession_summary['empty_possessions_recent']} ·
                            Home Off Rating: {possession_summary['home_off_rating']} ·
                            Away Off Rating: {possession_summary['away_off_rating']}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            if replay_mode and momentum_summary:
                st.markdown(
                    f"""
                    <div style='background:#16131f;border:1px solid #6d4bc3;border-radius:10px;padding:10px 12px;margin-bottom:8px;'>
                        <div style='font-weight:700;color:#ddd6fe;'>
                            ⚡ Momentum Engine
                        </div>
                        <div class='info-line'>
                            Momentum Signal: {momentum_summary['momentum_signal']} ·
                            Largest Run: {momentum_summary['largest_run']} ·
                            Lead Changes: {momentum_summary['lead_changes']} ·
                            Drought: {momentum_summary['scoring_drought_minutes']} min ·
                            Volatility: {momentum_summary['volatility_score']} ·
                            Momentum Modifier: {momentum_summary['momentum_factor']:.2f}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    if live_mode == "Team Total Over":
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            team_options = teams if teams else ["OKC", "LAL"]
            default_team_index = (
                team_options.index(default_team) if default_team in team_options else 0
            )

            team = st.selectbox(
                "Team",
                team_options,
                index=default_team_index,
                key="team_total_team",
            )

            if selected_live_game and team == live_away_full:
                default_points = default_away_points
            elif selected_live_game and team == live_home_full:
                default_points = default_home_points
            else:
                default_points = 0

            pregame_total = st.number_input(
                "Pregame Team Total / eigene Ziel-Line", 70.0, 160.0, 112.5, 0.5
            )
            current_points = st.number_input(
                "Aktuelle Team-Punkte", 0, 180, int(default_points), 1
            )
            target_line = st.number_input("Team Over-Line", 70.0, 160.0, 112.5, 0.5)
        with col_b:
            quarter = st.selectbox(
                "Quarter",
                [1, 2, 3, 4],
                index=max(0, min(3, default_quarter - 1)),
                key="team_total_quarter",
            )
            clock_text = st.text_input(
                "Restzeit im Quarter", default_clock, key="team_total_clock"
            )
            pace_mode = st.selectbox(
                "Pace Eindruck",
                pace_options,
                index=default_pace_index,
                key="team_total_pace",
            )
            game_state = st.selectbox(
                "Spielstand-Situation",
                game_state_options,
                index=default_game_state_index,
                key="team_total_state",
            )
        with col_c:
            opponent_fouls_default = opponent_fouls_for(team, quarter)
            default_run_state = default_run_state_for_team(team)
            team_in_bonus = st.checkbox(
                "Team ist im Bonus",
                value=default_bonus_for_team(team),
            )
            opponent_fouls = st.slider(
                "Opponent Team Fouls im Quarter",
                0,
                5,
                min(5, opponent_fouls_default),
            )
            recent_run_for = st.number_input(
                "Aktueller Run für Team",
                0,
                40,
                int(default_run_state.get("run_for_team") or 0),
                1,
            )
            recent_run_against = st.number_input(
                "Aktueller Run gegen Team",
                0,
                40,
                int(default_run_state.get("run_against_team") or 0),
                1,
            )
            empty_possessions = st.slider(
                "Leere Possessions zuletzt",
                0,
                5,
                default_empty_possessions_recent(),
            )
            manual_foul_trouble = st.checkbox(
                "Gegnerischer Schlüsselspieler Foul Trouble", value=bool(foul_trouble)
            )

        seconds_left_in_quarter = parse_clock_to_seconds(clock_text)
        live_result = live_team_total_projection(
            LiveProjectionInput(
                pregame_team_total=float(pregame_total),
                current_points=int(current_points),
                quarter=int(quarter),
                seconds_left_in_quarter=seconds_left_in_quarter,
                betting_line=float(target_line),
                team_in_bonus=team_in_bonus,
                opponent_team_fouls=int(opponent_fouls),
                pace_mode=pace_mode,
                game_state=game_state,
                recent_run_for_team=int(recent_run_for),
                recent_run_against_team=int(recent_run_against),
                empty_possessions=int(empty_possessions),
                key_player_foul_trouble=manual_foul_trouble,
                pbp_signal=(
                    recent_pbp_summary["pace_signal"] if recent_pbp_summary else None
                ),
                possession_pace_per_48=possession_pace_per_48(),
                possession_empty_count=possession_empty_count(),
                possession_off_rating=possession_off_rating_for_team(team),
                momentum_signal=momentum_signal(),
                momentum_factor=momentum_factor(),
                selected_team_side=selected_team_side(team),
            )
        )
        prob = over_probability(live_result["projected_final_points"], target_line)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Projected Final", live_result["projected_final_points"])
        m2.metric("Need for Over", max(0, round(target_line + 0.5 - current_points, 1)))
        m3.metric("Remaining Pts Projection", live_result["projected_remaining_points"])
        m4.metric("Over Chance", f"{prob}%")
        st.caption(
            f"Rate: live {live_result['current_rate_per_min']} pts/min · projected {live_result['projected_rate_per_min']} pts/min · remaining {live_result['remaining_minutes']} min"
        )
        st.caption(f"PBP signal modifier: {live_result['pbp_signal_factor']:.3f}")
        st.caption(f"Possession modifier: {live_result['possession_factor']:.2f}")
        st.caption(f"Momentum modifier: {live_result['momentum_factor']:.2f}")
        st.caption(f"Team momentum factor: {live_result['team_momentum_factor']:.2f}")
        st.caption(f"Master live factor: {live_result['master_live_factor']:.3f}")
        st.caption(
            f"Stability: {live_result['stability_score']} · Confidence: {live_result['confidence_score']}"
        )
        team_total_signal_label = live_factor_label(live_result)
        if team_total_signal_label:
            st.caption(team_total_signal_label)
        st.caption(
            f"Edge signal: {live_result['edge_signal']} · "
            f"Edge strength: {int(live_result['edge_strength'])} · "
            f"Edge value: {live_result['edge_value']:+.1f}"
        )
        team_total_edge_label = edge_label(live_result)
        if team_total_edge_label:
            st.caption(team_total_edge_label)

    elif live_mode == "Quarter Over/Under":
        st.markdown("### Quarter Over/Under")

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            q_quarter = st.selectbox(
                "Welches Viertel?",
                [1, 2, 3, 4],
                index=max(0, min(3, default_quarter - 1)),
                key="q_ou_quarter",
            )
            q_current_total_default = default_quarter_total
            if replay_mode:
                q_replay_points = live_context["quarter_points_by_quarter"].get(
                    q_quarter,
                    {},
                )
                q_current_total_default = q_replay_points["quarter_total"]

            q_current_total = st.number_input(
                "Aktuelle Punkte in DIESEM Viertel zusammen",
                0,
                120,
                int(q_current_total_default),
                1,
            )
            q_line = st.number_input("Quarter O/U Line", 20.0, 90.0, 55.5, 0.5)
            pregame_game_total = st.number_input(
                "Pregame Game Total / Modell O/U", 160.0, 280.0, 225.0, 0.5
            )
        with col_b:
            q_clock_text = st.text_input(
                "Restzeit im Viertel", default_clock, key="q_ou_clock"
            )
            q_pace_mode = st.selectbox(
                "Pace Eindruck",
                pace_options,
                index=default_pace_index,
                key="q_ou_pace",
            )
            q_game_state = st.selectbox(
                "Spielstand-Situation",
                game_state_options,
                index=default_game_state_index,
                key="q_ou_state",
            )
            recent_total_points = st.number_input(
                "Punkte letzte ~2 Minuten", 0, 40, 0, 1, key="q_recent_total"
            )
        with col_c:
            q_home_fouls_default = (
                team_fouls_for(live_team_tricode("homeTeam"), q_quarter)
                if selected_live_game
                else 2
            )
            q_away_fouls_default = (
                team_fouls_for(live_team_tricode("awayTeam"), q_quarter)
                if selected_live_game
                else 2
            )
            team_fouls_a = st.slider(
                "Team A Fouls im Quarter",
                0,
                5,
                min(5, q_home_fouls_default),
                key="q_fouls_a",
            )
            team_fouls_b = st.slider(
                "Team B Fouls im Quarter",
                0,
                5,
                min(5, q_away_fouls_default),
                key="q_fouls_b",
            )
            q_empty_possessions = st.slider(
                "Leere Possessions zuletzt",
                0,
                5,
                default_empty_possessions_recent(),
                key="q_empty",
            )
            overtime_risk = st.checkbox("OT-Risiko / extrem enges Q4", value=False)

        q_seconds_left_in_quarter = parse_clock_to_seconds(q_clock_text)
        q_result = live_quarter_projection(
            QuarterProjectionInput(
                line=float(q_line),
                current_total_points=int(q_current_total),
                seconds_left_in_quarter=q_seconds_left_in_quarter,
                pregame_game_total=float(pregame_game_total),
                quarter=int(q_quarter),
                pace_mode=q_pace_mode,
                team_fouls_a=int(team_fouls_a),
                team_fouls_b=int(team_fouls_b),
                game_state=q_game_state,
                recent_total_points_last_2min=int(recent_total_points),
                empty_possessions=int(q_empty_possessions),
                overtime_risk=overtime_risk,
                pbp_signal=(
                    recent_pbp_summary["pace_signal"] if recent_pbp_summary else None
                ),
                possession_pace_per_48=possession_pace_per_48(),
                possession_empty_count=possession_empty_count(),
                possession_off_rating=possession_avg_off_rating(),
                momentum_signal=momentum_signal(),
                momentum_factor=momentum_factor(),
            )
        )

        qm1, qm2, qm3, qm4 = st.columns(4)
        qm1.metric("Projected Quarter Total", q_result["projected_quarter_total"])
        qm2.metric("Need for Over", q_result["needed_for_over"])
        qm3.metric("Lean", q_result["lean"])
        qm4.metric("Over Chance", f"{q_result['over_probability']}%")

        st.markdown(
            flat_html(
            f"""
            <div class='bias-card'>
                <div class='info-line'>Quarter: Q{q_result['quarter']} · Line: {q_line} · Margin: {q_result['margin_to_line']}</div>
                <div class='info-line'>Current rate: {q_result['current_q_rate']} pts/min · Projected rate: {q_result['projected_q_rate']} pts/min</div>
                <div class='info-line'>PBP signal modifier: {q_result['pbp_signal_factor']:.3f}</div>
                <div class='info-line'>Possession modifier: {q_result['possession_factor']:.2f}</div>
                <div class='info-line'>Momentum modifier: {q_result['momentum_factor']:.2f}</div>
                <div class='info-line'>Master live factor: {q_result['master_live_factor']:.3f}</div>
                <div class='info-line'>Stability: {q_result['stability_score']} · Confidence: {q_result['confidence_score']}</div>
                {f"<div class='info-line'>{live_factor_label(q_result)}</div>" if live_factor_label(q_result) else ""}
                <div class='info-line'>Edge signal: {q_result['edge_signal']} · Edge strength: {int(q_result['edge_strength'])} · Edge value: {q_result['edge_value']:+.1f}</div>
                {f"<div class='info-line'>{edge_label(q_result)}</div>" if edge_label(q_result) else ""}
                <div class='info-line'>Remaining: {q_result['remaining_minutes_q']} min · Projected remaining: {q_result['projected_remaining_q_points']} pts</div>
            </div>
            """
            ),
            unsafe_allow_html=True,
        )

    else:
        st.markdown("### Quarter Team Total")

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            qtt_team_options = teams if teams else ["OKC", "LAL"]

            qtt_default_team = default_team
            if selected_live_game:
                qtt_default_team = live_home_full or default_team

            qtt_default_index = (
                qtt_team_options.index(qtt_default_team)
                if qtt_default_team in qtt_team_options
                else 0
            )

            qtt_team = st.selectbox(
                "Team",
                qtt_team_options,
                index=qtt_default_index,
                key="qtt_team",
            )

            qtt_quarter = st.selectbox(
                "Welches Viertel?",
                [1, 2, 3, 4],
                index=max(0, min(3, default_quarter - 1)),
                key="qtt_quarter",
            )

            if replay_mode:
                qtt_replay_points = live_context["quarter_points_by_quarter"].get(
                    qtt_quarter,
                    {},
                )
                if selected_live_game and qtt_team == live_home_full:
                    qtt_default_points = qtt_replay_points["home_q_points"]
                elif selected_live_game and qtt_team == live_away_full:
                    qtt_default_points = qtt_replay_points["away_q_points"]
                else:
                    qtt_default_points = 0
            else:
                if selected_live_game and qtt_team == live_home_full:
                    qtt_default_points = default_home_q_points
                elif selected_live_game and qtt_team == live_away_full:
                    qtt_default_points = default_away_q_points
                else:
                    qtt_default_points = 0

            qtt_current = st.number_input(
                "Team-Punkte in DIESEM Viertel",
                0,
                80,
                int(qtt_default_points),
                1,
            )

            qtt_line = st.number_input(
                "Quarter Team Total Line",
                5.0,
                50.0,
                28.5,
                0.5,
            )

        with col_b:
            qtt_pregame_total = st.number_input(
                "Pregame Team Total",
                70.0,
                160.0,
                112.5,
                0.5,
                key="qtt_pregame",
            )
            qtt_clock_text = st.text_input(
                "Restzeit im Viertel",
                default_clock,
                key="qtt_clock",
            )
            qtt_pace = st.selectbox(
                "Pace Eindruck",
                pace_options,
                index=default_pace_index,
                key="qtt_pace",
            )
            qtt_game_state = st.selectbox(
                "Spielstand-Situation",
                game_state_options,
                index=default_game_state_index,
                key="qtt_state",
            )

        with col_c:
            qtt_opp_fouls_default = opponent_fouls_for(qtt_team, qtt_quarter)
            qtt_bonus = st.checkbox(
                "Team ist im Bonus",
                value=default_bonus_for_team(qtt_team),
                key="qtt_bonus",
            )
            qtt_opp_fouls = st.slider(
                "Opponent Fouls im Quarter",
                0,
                5,
                min(5, qtt_opp_fouls_default),
                key="qtt_opp_fouls",
            )
            qtt_run_for = st.number_input(
                "Aktueller Run für Team",
                0,
                40,
                0,
                1,
                key="qtt_run_for",
            )
            qtt_run_against = st.number_input(
                "Aktueller Run gegen Team",
                0,
                40,
                0,
                1,
                key="qtt_run_against",
            )
            qtt_empty = st.slider(
                "Leere Possessions zuletzt",
                0,
                5,
                default_empty_possessions_recent(),
                key="qtt_empty",
            )
            qtt_foul_trouble = st.checkbox(
                "Gegnerischer Schlüsselspieler Foul Trouble",
                value=False,
                key="qtt_foul_trouble",
            )

        qtt_seconds = parse_clock_to_seconds(qtt_clock_text)
        qtt_result = live_quarter_team_total_projection(
            QuarterTeamTotalInput(
                line=float(qtt_line),
                current_team_points_q=int(qtt_current),
                seconds_left_in_quarter=qtt_seconds,
                pregame_team_total=float(qtt_pregame_total),
                quarter=int(qtt_quarter),
                pace_mode=qtt_pace,
                opponent_team_fouls=int(qtt_opp_fouls),
                team_in_bonus=qtt_bonus,
                game_state=qtt_game_state,
                recent_run_for_team=int(qtt_run_for),
                recent_run_against_team=int(qtt_run_against),
                empty_possessions=int(qtt_empty),
                key_player_foul_trouble=qtt_foul_trouble,
                pbp_signal=(
                    recent_pbp_summary["pace_signal"] if recent_pbp_summary else None
                ),
                possession_pace_per_48=possession_pace_per_48(),
                possession_empty_count=possession_empty_count(),
                possession_off_rating=possession_off_rating_for_team(qtt_team),
                momentum_signal=momentum_signal(),
                momentum_factor=momentum_factor(),
                selected_team_side=selected_team_side(qtt_team),
            )
        )

        qtm1, qtm2, qtm3, qtm4 = st.columns(4)
        qtm1.metric(
            "Projected Team Q Total",
            qtt_result["projected_quarter_team_total"],
        )
        qtm2.metric("Need for Over", qtt_result["needed_for_over"])
        qtm3.metric("Lean", qtt_result["lean"])
        qtm4.metric("Over Chance", f"{qtt_result['over_probability']}%")

        st.markdown(
            flat_html(
            f"""
            <div class='bias-card'>
                <div class='info-line'>{qtt_team} Q{qtt_result['quarter']} · Line: {qtt_line} · Margin: {qtt_result['margin_to_line']}</div>
                <div class='info-line'>Current rate: {qtt_result['current_q_team_rate']} pts/min · Projected rate: {qtt_result['projected_q_team_rate']} pts/min</div>
                <div class='info-line'>PBP signal modifier: {qtt_result['pbp_signal_factor']:.3f}</div>
                <div class='info-line'>Possession modifier: {qtt_result['possession_factor']:.2f}</div>
                <div class='info-line'>Momentum modifier: {qtt_result['momentum_factor']:.2f}</div>
                <div class='info-line'>Team momentum factor: {qtt_result['team_momentum_factor']:.2f}</div>
                <div class='info-line'>Master live factor: {qtt_result['master_live_factor']:.3f}</div>
                <div class='info-line'>Stability: {qtt_result['stability_score']} · Confidence: {qtt_result['confidence_score']}</div>
                {f"<div class='info-line'>{live_factor_label(qtt_result)}</div>" if live_factor_label(qtt_result) else ""}
                <div class='info-line'>Edge signal: {qtt_result['edge_signal']} · Edge strength: {int(qtt_result['edge_strength'])} · Edge value: {qtt_result['edge_value']:+.1f}</div>
                {f"<div class='info-line'>{edge_label(qtt_result)}</div>" if edge_label(qtt_result) else ""}
                <div class='info-line'>Remaining: {qtt_result['remaining_minutes_q']} min · Projected remaining: {qtt_result['projected_remaining_q_team_points']} pts</div>
            </div>
            """
            ),
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("### 🎯 Player Props Pre-Game")
    st.caption(
        "Pre-Game Points-Props-Projektion. NBA.com oder BallDontLie können vorbefüllen, alle Inputs bleiben manuell editierbar."
    )

    player_props_season = (
        date.today().year if date.today().month >= 10 else date.today().year - 1
    )
    player_props_nba_season = f"{player_props_season}-{str(player_props_season + 1)[-2:]}"
    ball_loaded_prop_data = st.session_state.player_props_loaded_data or {}
    nba_loaded_prop_data = st.session_state.nba_player_props_loaded_data or {}
    loaded_prop_data = nba_loaded_prop_data or ball_loaded_prop_data

    nba_search_c1, nba_search_c2 = st.columns([2.4, 1])
    with nba_search_c1:
        nba_player_search_query = st.text_input(
            "NBA Player suchen",
            loaded_prop_data.get("player_name", "Shai Gilgeous-Alexander"),
            key="nba_player_props_search_query",
        )
    with nba_search_c2:
        st.write("")
        load_nba_player_data = st.button(
            "NBA.com Daten laden", key="load_nba_player_props_data"
        )

    if load_nba_player_data:
        nba_candidates = search_nba_players(nba_player_search_query)
        st.session_state.nba_player_props_candidates = nba_candidates
        if nba_candidates:
            current_selected = st.session_state.nba_player_props_selected_player
            current_selected_id = (
                current_selected.get("id") if current_selected else None
            )
            if current_selected_id not in {
                candidate["id"] for candidate in nba_candidates
            }:
                st.session_state.nba_player_props_selected_player = nba_candidates[0]
        else:
            st.session_state.nba_player_props_selected_player = None
            st.session_state.nba_player_props_loaded_data = {}
            st.warning(
                "Keine NBA.com Spieler gefunden oder nba_api ist nicht verfügbar. Manuelle Eingabe bleibt möglich."
            )

    nba_candidates = st.session_state.nba_player_props_candidates
    nba_selected_player = st.session_state.nba_player_props_selected_player

    if nba_candidates:
        nba_selected_index = 0
        if nba_selected_player:
            nba_selected_index = next(
                (
                    idx
                    for idx, candidate in enumerate(nba_candidates)
                    if candidate["id"] == nba_selected_player.get("id")
                ),
                0,
            )
        nba_selected_player = st.selectbox(
            "NBA.com gefundene Spieler",
            nba_candidates,
            index=nba_selected_index,
            format_func=lambda player: player["full_name"],
            key="nba_player_props_player_select",
        )
        st.session_state.nba_player_props_selected_player = nba_selected_player

        if load_nba_player_data and nba_selected_player:
            regular_season_data = fetch_nba_player_base_stats(
                nba_selected_player["id"], player_props_nba_season, "Regular Season"
            )
            playoff_season_data = fetch_nba_player_base_stats(
                nba_selected_player["id"], player_props_nba_season, "Playoffs"
            )
            playoff_last_games_data = fetch_nba_player_last_games(
                nba_selected_player["id"],
                player_props_nba_season,
                "Playoffs",
                limit=5,
            )
            regular_last_games_data = fetch_nba_player_last_games(
                nba_selected_player["id"],
                player_props_nba_season,
                "Regular Season",
                limit=5,
            )
            last_games_data = (
                playoff_last_games_data
                if playoff_last_games_data["games"] > 0
                else regular_last_games_data
            )
            expected_minutes_default = (
                last_games_data["minutes"]
                or playoff_season_data["minutes"]
                or regular_season_data["minutes"]
                or loaded_prop_data.get("expected_minutes", 36.0)
            )
            if (
                regular_season_data["gp"] <= 0
                and last_games_data["games"] <= 0
                and playoff_season_data["gp"] <= 0
            ):
                st.session_state.nba_player_props_loaded_data = {}
                st.warning(
                    "NBA.com Daten konnten nicht geladen werden. Manuelle Eingabe bleibt möglich."
                )
            else:
                st.session_state.nba_player_props_loaded_data = {
                    "player_id": nba_selected_player["id"],
                    "player_name": nba_selected_player["full_name"],
                    "team": "NBA.com",
                    "season": player_props_nba_season,
                    "season_ppg": regular_season_data["ppg"],
                    "season_minutes": regular_season_data["minutes"],
                    "games_played": regular_season_data["gp"],
                    "season_fga": regular_season_data["fga"],
                    "season_fta": regular_season_data["fta"],
                    "season_ts": regular_season_data["ts"],
                    "last5_ppg": last_games_data["ppg"],
                    "last5_minutes": last_games_data["minutes"],
                    "last5_games": last_games_data["games"],
                    "last5_fga": last_games_data["fga"],
                    "last5_fta": last_games_data["fta"],
                    "last5_ts": last_games_data["ts"],
                    "expected_minutes": expected_minutes_default,
                    "source": "NBA.com",
                    "last5_source": (
                        "Playoffs"
                        if playoff_last_games_data["games"] > 0
                        else "Regular Season"
                    ),
                }
                nba_loaded_prop_data = st.session_state.nba_player_props_loaded_data
                loaded_prop_data = nba_loaded_prop_data
                st.success("NBA.com Player Stats geladen.")

    search_c1, search_c2 = st.columns([2.4, 1])
    with search_c1:
        player_search_query = st.text_input("Player suchen", "Shai")
    with search_c2:
        st.write("")
        load_player_data = st.button("Daten laden", key="load_player_props_data")

    if load_player_data:
        candidates = search_players(player_search_query)
        st.session_state.player_props_candidates = candidates
        st.session_state.nba_player_props_loaded_data = {}
        if candidates:
            st.session_state.player_props_selected_player = candidates[0]
        else:
            st.session_state.player_props_selected_player = None
            st.session_state.player_props_loaded_data = {}

    candidates = st.session_state.player_props_candidates
    selected_player = st.session_state.player_props_selected_player

    if candidates:
        selected_index = 0
        if selected_player:
            selected_index = next(
                (
                    idx
                    for idx, candidate in enumerate(candidates)
                    if candidate["id"] == selected_player.get("id")
                ),
                0,
            )
        selected_player = st.selectbox(
            "Gefundene Spieler",
            candidates,
            index=selected_index,
            format_func=lambda player: (
                f"{player['full_name']} · {player['team'] or 'Team n/a'}"
            ),
        )
        st.session_state.player_props_selected_player = selected_player

        if load_player_data and selected_player:
            season_data = fetch_player_season_averages(
                selected_player["id"], player_props_season
            )
            last_games_data = fetch_player_last_games(
                selected_player["id"], player_props_season, limit=5
            )
            expected_minutes_default = (
                last_games_data["last5_minutes"]
                or season_data["season_minutes"]
                or loaded_prop_data.get("expected_minutes", 36.0)
            )
            st.session_state.player_props_loaded_data = {
                "player_id": selected_player["id"],
                "player_name": selected_player["full_name"],
                "team": selected_player["team"],
                "season": player_props_season,
                "season_ppg": season_data["season_ppg"],
                "season_minutes": season_data["season_minutes"],
                "games_played": season_data["games_played"],
                "last5_ppg": last_games_data["last5_ppg"],
                "last5_minutes": last_games_data["last5_minutes"],
                "last5_games": last_games_data["games"],
                "expected_minutes": expected_minutes_default,
            }
            ball_loaded_prop_data = st.session_state.player_props_loaded_data
            loaded_prop_data = ball_loaded_prop_data
    elif load_player_data:
        st.info("Keine Spieler gefunden oder BallDontLie ist nicht verfügbar.")

    loaded_prop_data = (
        st.session_state.nba_player_props_loaded_data
        or st.session_state.player_props_loaded_data
        or {}
    )

    if loaded_prop_data:
        source = loaded_prop_data.get("source") or "BallDontLie"
        last5_source = loaded_prop_data.get("last5_source")
        st.caption(
            f"Auto-Fill ({source}): {loaded_prop_data['player_name']} · Saison {loaded_prop_data['season']} · "
            f"Season Games: {loaded_prop_data['games_played']} · Last Games: {loaded_prop_data['last5_games']}"
            f"{f' · Last-5 Quelle: {last5_source}' if last5_source else ''}"
        )

    with st.form("player_points_props_form"):
        prop_c1, prop_c2, prop_c3 = st.columns(3)
        with prop_c1:
            player_name = st.text_input(
                "Player Name",
                loaded_prop_data.get("player_name", "Shai Gilgeous-Alexander"),
            )
            season_ppg = st.number_input(
                "Season PPG",
                0.0,
                60.0,
                float(loaded_prop_data.get("season_ppg") or 31.0),
                0.1,
            )
            last5_ppg = st.number_input(
                "Last 5 PPG",
                0.0,
                70.0,
                float(loaded_prop_data.get("last5_ppg") or 34.0),
                0.1,
            )
        with prop_c2:
            expected_minutes = st.number_input(
                "Expected Minutes",
                0.0,
                60.0,
                float(loaded_prop_data.get("expected_minutes") or 36.0),
                0.5,
            )
            season_minutes = st.number_input(
                "Season Minutes",
                0.0,
                60.0,
                float(loaded_prop_data.get("season_minutes") or 35.0),
                0.5,
            )
            prop_line = st.number_input("Prop Line", 0.0, 70.0, 31.5, 0.5)
        with prop_c3:
            team_pace_factor = st.number_input(
                "Team Pace Factor", 0.80, 1.20, 1.00, 0.01
            )
            opponent_defense_factor = st.number_input(
                "Opponent Defense Factor", 0.80, 1.20, 1.00, 0.01
            )
            blowout_risk = st.selectbox("Blowout Risk", ["normal", "risk", "high"])
            playoff_mode = st.checkbox("Playoff Mode", value=False)

        volume_c1, volume_c2, volume_c3 = st.columns(3)
        with volume_c1:
            season_fga = st.number_input(
                "Season FGA",
                0.0,
                50.0,
                float(loaded_prop_data.get("season_fga") or 0.0),
                0.1,
            )
            last5_fga = st.number_input(
                "Last 5 FGA",
                0.0,
                60.0,
                float(loaded_prop_data.get("last5_fga") or 0.0),
                0.1,
            )
        with volume_c2:
            season_fta = st.number_input(
                "Season FTA",
                0.0,
                30.0,
                float(loaded_prop_data.get("season_fta") or 0.0),
                0.1,
            )
            last5_fta = st.number_input(
                "Last 5 FTA",
                0.0,
                30.0,
                float(loaded_prop_data.get("last5_fta") or 0.0),
                0.1,
            )
        with volume_c3:
            season_ts = st.number_input(
                "Season TS%",
                0.0,
                100.0,
                float(loaded_prop_data.get("season_ts") or 0.0),
                0.1,
            )
            last5_ts = st.number_input(
                "Last 5 TS%",
                0.0,
                100.0,
                float(loaded_prop_data.get("last5_ts") or 0.0),
                0.1,
            )

        calculate_prop = st.form_submit_button("Player Prop berechnen")

    if calculate_prop:
        prop_result = project_player_points_prop(
            season_ppg=float(season_ppg),
            last5_ppg=float(last5_ppg),
            expected_minutes=float(expected_minutes),
            season_minutes=float(season_minutes),
            team_pace_factor=float(team_pace_factor),
            opponent_defense_factor=float(opponent_defense_factor),
            blowout_risk=blowout_risk,
            playoff_mode=playoff_mode,
            line=float(prop_line),
            season_fga=float(season_fga),
            last5_fga=float(last5_fga),
            season_fta=float(season_fta),
            last5_fta=float(last5_fta),
            season_ts=float(season_ts),
            last5_ts=float(last5_ts),
        )

        lean_color = {
            "OVER": "#22c55e",
            "UNDER": "#ef4444",
            "NO_EDGE": "#94a3b8",
        }[prop_result["lean"]]
        st.markdown(
            f"""
            <div style='background:#111827;border:1px solid #2b3550;border-radius:10px;padding:14px 16px;margin-top:12px;'>
                <div style='color:#64748b;font-family:Space Mono,monospace;font-size:0.72rem;font-weight:700;'>PLAYER</div>
                <div style='color:#e8e8f0;font-family:Space Mono,monospace;font-size:1.05rem;font-weight:800;margin-bottom:12px;'>{player_name}</div>
                <div style='display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;'>
                    <div><div class='score-team'>Projected Points</div><div class='score-pts'>{prop_result["projected_points"]}</div></div>
                    <div><div class='score-team'>Market Line</div><div class='score-pts'>{prop_result["line"]}</div></div>
                    <div><div class='score-team'>Difference</div><div class='score-pts'>{prop_result["difference"]:+.1f}</div></div>
                    <div><div class='score-team'>Lean</div><div style='font-family:Space Mono,monospace;font-size:1.5rem;font-weight:800;color:{lean_color};'>{prop_result["lean"]}</div></div>
                    <div><div class='score-team'>Confidence</div><div class='score-pts'>{int(prop_result["confidence"])}%</div></div>
                </div>
                <div class='info-line' style='margin-top:10px;'>Base: {prop_result["base"]} · Minutes factor: {prop_result["minutes_factor"]} · Blowout factor: {prop_result["blowout_factor"]}</div>
                <div class='info-line' style='margin-top:4px;'>Usage Ratio: {prop_result["usage_ratio"]} · FTA Factor: {prop_result["fta_factor"]} · TS Factor: {prop_result["ts_factor"]} · Model {prop_result["model_version"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("### 🧾 Live Bet Log")
    st.caption("Optional: speichert deine Livewetten lokal in data/live_bets_log.csv")
    with st.form("live_bet_log_form"):
        log_c1, log_c2, log_c3, log_c4 = st.columns(4)
        with log_c1:
            log_game_default = (
                f"{selected_live_game['away_city']} {selected_live_game['away_team']} @ {selected_live_game['home_city']} {selected_live_game['home_team']}"
                if selected_live_game
                else "OKC @ LAL"
            )
            log_game = st.text_input("Spiel", log_game_default)
            log_market = st.text_input("Markt", live_mode)
        with log_c2:
            log_line = st.number_input("Line", 0.0, 300.0, 112.5, 0.5)
            log_odds = st.number_input("Quote", 1.0, 20.0, 1.90, 0.01)
        with log_c3:
            log_model_prob = st.number_input("Modell Chance %", 0, 100, 55, 1)
            log_result = st.selectbox("Ergebnis", ["open", "win", "loss", "push"])
        with log_c4:
            log_note = st.text_area("Notiz", "", height=70)
        submitted = st.form_submit_button("Live Bet speichern")
        if submitted:
            import csv
            from pathlib import Path

            log_path = Path("data/live_bets_log.csv")
            log_path.parent.mkdir(exist_ok=True)
            exists = log_path.exists()
            with log_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "game",
                        "market",
                        "line",
                        "odds",
                        "model_prob",
                        "result",
                        "note",
                    ],
                )
                if not exists:
                    writer.writeheader()
                writer.writerow(
                    {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "game": log_game,
                        "market": log_market,
                        "line": log_line,
                        "odds": log_odds,
                        "model_prob": log_model_prob,
                        "result": log_result,
                        "note": log_note,
                    }
                )
            st.success("Live Bet gespeichert.")

with live_bet_tab:
    st.markdown("## 🎯 Live Bet Tracker")

    with open("data/live_bets.json", "r", encoding="utf-8") as f:
        bets = json.load(f)

    st.markdown("### ➕ Add Bet")
    player_name = st.text_input("Player Name")
    line = st.number_input("Line", step=0.5)

    if st.button("Add Bet"):
        if any(bet.get("player") == player_name for bet in bets):
            st.warning("Bet already exists.")
        else:
            bets.append(
                {
                    "player": player_name,
                    "bet_type": "points_over",
                    "line": line,
                }
            )
            with open("data/live_bets.json", "w", encoding="utf-8") as f:
                json.dump(bets, f, indent=2)
            st.success("Bet added.")

    live_boxscore = live_context.get("live_boxscore") or {}
    bet_status = get_live_bet_status(live_boxscore, bets)

    st.table(
        pd.DataFrame(
            [
                {
                    "Player": row["player"],
                    "Line": row["line"],
                    "Current Points": row["current_points"],
                    "Remaining": row["remaining"],
                    "Status": row["status"],
                }
                for row in bet_status
            ]
        )
    )

with tab4:
    st.markdown("## 📰 Lineup / Injury News")
    st.caption(
        "Optional: funktioniert automatisch, wenn NEWS_API_KEY in deiner .env steht. Ohne Key bleibt es leer, aber die Lineup-Warnung aus Vegas-Differenzen funktioniert weiter."
    )
    teams = sorted(
        set(
            [
                t
                for p in st.session_state.projections
                for t in [p["home_team"], p["away_team"]]
            ]
        )
    )
    selected_team = st.selectbox(
        "Team-News prüfen",
        teams if teams else ["Los Angeles Lakers", "Oklahoma City Thunder"],
    )
    if st.button("News laden"):
        articles = (
            []
            if OFFLINE_AUDIT_MODE
            else fetch_team_news(selected_team, max_results=5)
        )
        if not articles:
            st.warning(
                "Keine News geladen. Prüfe NEWS_API_KEY oder nutze die Vegas-Lineup-Warnung im Score-Tab."
            )
        for a in articles:
            st.markdown(f"**{a['title']}**")
            st.caption(f"{a['source']} · {a['publishedAt']}")
            if a.get("url"):
                st.markdown(f"[Artikel öffnen]({a['url']})")
            st.divider()

with tab5:
    st.markdown("## 📅 History / Accuracy / Self-Correction")
    days_back = st.slider("Wie viele Tage zurück laden?", 1, 14, 4)
    yday_games = fetch_completed_games(days_back)
    if not yday_games:
        st.markdown(
            '<div class="no-bets"><div style="font-size:3rem">📅</div><div style="margin-top:16px">Keine Spiele gefunden</div></div>',
            unsafe_allow_html=True,
        )
    elif engine is None:
        st.info(
            "Offline Audit Mode: History ist geladen, ELO-Auswertung ist ohne lokales Modell deaktiviert."
        )
    else:
        by_date = defaultdict(list)
        for g in yday_games:
            by_date[g["_display_date"]].append(g)
        total_correct, total_games = 0, len(yday_games)
        team_bias_stats = {}
        rows = []
        for d in sorted(by_date.keys(), reverse=True):
            st.markdown(f"### 📅 {d}")
            day_correct = 0
            for g in by_date[d]:
                home = g["home_team"]["full_name"]
                away = g["visitor_team"]["full_name"]
                h_pts = g["home_team_score"]
                a_pts = g["visitor_team_score"]
                pred = engine.predict(home, away, date.fromisoformat(d))
                proj = compute_projection(
                    pred,
                    game_date=d,
                    bias_adjustments=st.session_state.bias_adjustments,
                )
                h_proj, a_proj = proj["home_score"], proj["away_score"]
                exp_total = proj["exp_total"]
                actual_total = h_pts + a_pts
                projection_error = round(abs(exp_total - actual_total), 1)
                if projection_error <= 6:
                    projection_grade = "🔥 ELITE"
                elif projection_error <= 12:
                    projection_grade = "✓ SOLID"
                else:
                    projection_grade = "⚠️ OFF"
                home_error = abs(h_proj - h_pts)
                away_error = abs(a_proj - a_pts)
                worst_team = home if home_error > away_error else away
                worst_error = max(home_error, away_error)
                team_bias_direction = (
                    "OVERVALUED"
                    if (
                        (worst_team == home and h_proj > h_pts)
                        or (worst_team == away and a_proj > a_pts)
                    )
                    else "UNDERVALUED"
                )
                if worst_team not in team_bias_stats:
                    team_bias_stats[worst_team] = {
                        "games": 0,
                        "total_error": 0,
                        "overvalued": 0,
                        "undervalued": 0,
                    }
                team_bias_stats[worst_team]["games"] += 1
                team_bias_stats[worst_team]["total_error"] += worst_error
                team_bias_stats[worst_team][
                    (
                        "overvalued"
                        if team_bias_direction == "OVERVALUED"
                        else "undervalued"
                    )
                ] += 1
                pred_home_win = pred["home_win_prob"] > 0.5
                actual_home_win = h_pts > a_pts
                hit = pred_home_win == actual_home_win
                if hit:
                    day_correct += 1
                    total_correct += 1
                border_color = "#22c55e" if hit else "#ef4444"
                icon = "✓" if hit else "✗"
                c1, c2, c3, c4 = st.columns([2, 1.3, 0.4, 2])
                with c1:
                    st.markdown(
                        f"""<div class="score-card" style="border-left:4px solid {border_color}"><div class="score-team">{away} (AWAY)</div><div class="score-pts">{a_pts}</div><div class="score-team" style="margin-top:4px;color:#94a3b8">proj: {a_proj}</div></div>""",
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.markdown(
                        f"""
                    <div style='text-align:center;padding-top:20px;'>
                        <div style='font-size:1.5rem'>{icon}</div>
                        <div class='info-line'>{'RICHTIG' if hit else 'FALSCH'}</div>
                        <div class='info-line' style='margin-top:8px'>Fav: {'HOME' if pred['home_win_prob'] > 0.5 else 'AWAY'}</div>
                        <div class='info-line'>O/U: {round(exp_total)}</div>
                        <div class='info-line'>raw model: {proj['model_total']}</div>
                        <div class='info-line'>quality: {projection_grade}</div>
                        <div class='info-line'>worst: {worst_team} ({worst_error}) · {team_bias_direction}</div>
                        <div class='info-line'>total error: {projection_error}</div>
                        <div class='info-line'>home error: {home_error} · away error: {away_error}</div>
                    </div>""",
                        unsafe_allow_html=True,
                    )
                with c3:
                    st.markdown(
                        '<div style="text-align:center;padding-top:38px;color:#2a2a4a;font-family:Space Mono,monospace;font-size:1.2rem">@</div>',
                        unsafe_allow_html=True,
                    )
                with c4:
                    st.markdown(
                        f"""<div class="score-card" style="border-left:4px solid {border_color}"><div class="score-team">{home} (HOME)</div><div class="score-pts">{h_pts}</div><div class="score-team" style="margin-top:4px;color:#94a3b8">proj: {h_proj}</div></div>""",
                        unsafe_allow_html=True,
                    )
                rows.append(
                    {
                        "date": d,
                        "away": away,
                        "home": home,
                        "actual_total": actual_total,
                        "proj_total": exp_total,
                        "total_error": projection_error,
                        "winner_hit": hit,
                        "worst_team": worst_team,
                        "worst_error": worst_error,
                        "bias": team_bias_direction,
                    }
                )
                st.divider()
            st.caption(f"{d}: {day_correct}/{len(by_date[d])} richtig")

        st.metric(
            "Hit Rate",
            f"{total_correct}/{total_games} = {round(total_correct/total_games*100, 1)}%",
        )
        st.markdown("## 🧠 Team Bias Tracking")
        for team, stats in sorted(
            team_bias_stats.items(),
            key=lambda x: x[1]["total_error"] / x[1]["games"],
            reverse=True,
        ):
            avg_error = round(stats["total_error"] / stats["games"], 1)
            st.markdown(
                f"""<div class='bias-card'><div style='font-weight:700;color:#e8e8f0'>{team}</div><div class='info-line'>avg error: {avg_error} · overvalued: {stats['overvalued']} · undervalued: {stats['undervalued']} · games: {stats['games']}</div></div>""",
                unsafe_allow_html=True,
            )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Self-Correction aus History speichern"):
                adjustments = build_bias_adjustments(team_bias_stats, min_games=2)
                save_bias_adjustments(adjustments)
                st.session_state.bias_adjustments = adjustments
                st.success(
                    f"{len(adjustments)} Team-Adjustments gespeichert. Danach Refresh Odds klicken."
                )
        with c2:
            if st.button("🧹 Self-Correction löschen"):
                save_bias_adjustments({})
                st.session_state.bias_adjustments = {}
                st.success("Self-Correction gelöscht.")

        if rows:
            df = pd.DataFrame(rows)
            st.download_button(
                "📥 History CSV herunterladen",
                df.to_csv(index=False).encode("utf-8"),
                "nbaedge_history.csv",
                "text/csv",
            )

with tab6:
    st.markdown("## 📈 Team ELO Rankings")
    if engine:
        elo_data = [
            {
                "Team": t,
                "ELO": round(r, 0),
                "Form L10 %": round(engine._form_score(t) * 100, 1),
            }
            for t, r in sorted(engine.ratings.items(), key=lambda x: -x[1])
            if engine.form.get(t)
        ]
        df = pd.DataFrame(elo_data)
        df.index = range(1, len(df) + 1)
        fig = px.bar(
            df.head(30),
            x="ELO",
            y="Team",
            orientation="h",
            color="ELO",
            color_continuous_scale=["#1a1a2e", "#f97316"],
            template="plotly_dark",
        )
        fig.update_layout(
            paper_bgcolor="#0a0a0f",
            plot_bgcolor="#0a0a0f",
            height=700,
            showlegend=False,
            yaxis=dict(autorange="reversed"),
            font=dict(family="DM Sans"),
        )
        st.plotly_chart(fig, use_container_width=True)

with tab_pre_match:
    render_pre_match_tab(st.session_state.projections)

render_odds_status(odds_status_slot)
render_automation_status(automation_slot)

st.markdown(
    '<div style="text-align:center;color:#2a2a4a;font-family:Space Mono,monospace;font-size:0.7rem;margin-top:40px">NBAEdge · For research purposes only · Gamble responsibly</div>',
    unsafe_allow_html=True,
)
