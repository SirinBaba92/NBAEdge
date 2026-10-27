"""
Kategorien fuer Wetten (reine Logik, kein Netz, keine Oberflaeche).

Feste Kategorien mit stabilen IDs; nur der Anzeigename ist aenderbar (umbenennen, nicht anlegen oder loeschen):
  Team-Wetten (Sieger, Spread, Total, Team Total):  team_1 "Bankroll 1", team_2 "Bankroll 2"
  Spieler-Wetten:                                   player_ta "Teamabgleich", player_raw "Roh"
Eine Wette kann in MEHREREN Kategorien ihrer Wettart liegen: Feld "categories" = Liste von IDs (data/day_bets_store.py; neue Wetten mindestens eine). Fehlt das Feld oder ist die Liste leer,
gilt die Wette als "Ohne Kategorie". Aeltere Wetten ohne Feld und das fruehere Einzelfeld "category" (Text) werden beim Lesen zur Liste (normalize), die Datei wird dabei nicht veraendert.
Umbenennen aendert die Zuordnung der Wetten nicht.

Datei: bet_categories.json im Tracking-Ordner (NBAEDGE_TRACKING_DIR wie pre_match_entries.json):
  {"version": 1, "format": "nbaedge-bet-categories", "names": {"<id>": "<Name>"}, "last_team": ["team_1"]}
Nur geaenderte Namen stehen in der Datei; fehlt die Datei oder ist sie unlesbar, gelten die Standardnamen. Schreiben: Temp-Datei + fsync + os.replace.
"""
from __future__ import annotations

import json
import threading

from data import pre_match_store as store

FORMAT = "nbaedge-bet-categories"
TEAM_IDS = ("team_1", "team_2")
PLAYER_IDS = ("player_ta", "player_raw")
ALL_IDS = TEAM_IDS + PLAYER_IDS
DEFAULT_NAMES = {"team_1": "Bankroll 1", "team_2": "Bankroll 2", "player_ta": "Teamabgleich", "player_raw": "Roh"}
NO_CATEGORY_LABEL = "Ohne Kategorie"
MAX_NAME_LEN = 30
MODE_CATEGORY = {"team": "player_ta", "raw": "player_raw"}      # Anzeigemodus der Spieler-Karten -> Kategorie
_lock = threading.RLock()


class CategoryError(ValueError):
    """Ungueltige Eingabe (kurze deutsche Meldung)."""


def settings_path():
    return store.tracking_dir() / "bet_categories.json"


def kind_of(category_id: str) -> str | None:
    """'team' | 'player' | None (unbekannte ID)."""
    return "team" if category_id in TEAM_IDS else "player" if category_id in PLAYER_IDS else None


def ids_for_kind(kind: str) -> tuple:
    return TEAM_IDS if kind == "team" else PLAYER_IDS


def normalize(raw) -> list:
    """Kategorie-IDs als Liste (Reihenfolge wie ALL_IDS, ohne Doppelte, unbekannte IDs entfallen). Akzeptiert None, einen Text (frueheres Einzelfeld) oder eine Liste."""
    if raw is None or raw == "":
        return []
    vals = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, (list, tuple, set)) else []
    return [c for c in ALL_IDS if c in vals]


def validate(kind: str, categories) -> list | None:
    """None bleibt None (keine Angabe). Sonst Liste (oder einzelne ID): mindestens eine, alle muessen zur Wettart passen (Team-Wette: team_*, Spieler-Wette: player_*), unbekannte IDs sind Fehler.
    Rueckgabe: normalisierte Liste; CategoryError bei Fehlern."""
    if categories is None:
        return None
    vals = [categories] if isinstance(categories, str) else list(categories)
    for c in vals:
        if c not in ALL_IDS:
            raise CategoryError(f"Unbekannte Kategorie: {c}.")
        if kind_of(c) != kind:
            raise CategoryError("Diese Kategorie passt nicht zur Wettart (Team-Wetten und Spieler-Wetten haben getrennte Kategorien).")
    out = normalize(vals)
    if not out:
        raise CategoryError("Bitte mindestens eine Kategorie wählen.")
    return out


def _read() -> dict:
    try:
        d = json.loads(settings_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("format") == FORMAT else {}
    except Exception:
        return {}


def names() -> dict:
    """{id: Anzeigename}; ungueltige oder fehlende Eintraege fallen auf den Standardnamen zurueck."""
    saved = _read().get("names")
    saved = saved if isinstance(saved, dict) else {}
    out = dict(DEFAULT_NAMES)
    for cid in ALL_IDS:
        v = saved.get(cid)
        if isinstance(v, str) and v.strip():
            out[cid] = v.strip()[:MAX_NAME_LEN]
    return out


def labels(categories, nm: dict | None = None) -> str:
    """'Bankroll 1, Bankroll 2' bzw. 'Ohne Kategorie' fuer eine leere Liste."""
    cats = normalize(categories)
    return ", ".join(label(c, nm) for c in cats) if cats else NO_CATEGORY_LABEL


def label(category_id, nm: dict | None = None) -> str:
    """Anzeigename; None oder unbekannt -> 'Ohne Kategorie'."""
    if category_id not in ALL_IDS:
        return NO_CATEGORY_LABEL
    return (nm or names())[category_id]


def _write(names_: dict, last_team) -> None:
    changed = {cid: n for cid, n in names_.items() if cid in ALL_IDS and n != DEFAULT_NAMES[cid]}
    data = {"version": 1, "format": FORMAT, "names": changed}
    lt = [c for c in normalize(last_team) if c in TEAM_IDS]
    if lt:
        data["last_team"] = lt
    store._atomic_write(settings_path(), data)


def _clean_name(new_name) -> str:
    n = " ".join(str(new_name or "").split())
    if not n:
        raise CategoryError("Der Name darf nicht leer sein.")
    if len(n) > MAX_NAME_LEN:
        raise CategoryError(f"Der Name ist zu lang (höchstens {MAX_NAME_LEN} Zeichen).")
    if n.casefold() == NO_CATEGORY_LABEL.casefold():
        raise CategoryError(f"„{NO_CATEGORY_LABEL}“ ist für Wetten ohne Kategorie reserviert.")
    return n


def rename_many(mapping: dict) -> dict:
    """Mehrere Anzeigenamen auf einmal aendern ({id: neuer Name}); geprueft wird das Endergebnis (Namen tauschen ist moeglich). Unbekannte ID, leer, zu lang oder doppelt (ohne Gross-/Kleinschreibung):
    CategoryError, nichts geschrieben. Die IDs und die Zuordnung der Wetten bleiben. Rueckgabe: alle Namen."""
    for cid in mapping:
        if cid not in ALL_IDS:
            raise CategoryError(f"Unbekannte Kategorie: {cid}.")
    with _lock:
        final = names()
        final.update({cid: _clean_name(n) for cid, n in mapping.items()})
        low = [v.casefold() for v in final.values()]
        if len(set(low)) != len(low):
            raise CategoryError("Die Namen müssen verschieden sein (ein Name wird schon von einer anderen Kategorie verwendet).")
        _write(final, _read().get("last_team"))
        return names()


def rename(category_id: str, new_name: str) -> dict:
    """Einen Anzeigenamen aendern (siehe rename_many)."""
    return rename_many({category_id: new_name})


def last_team() -> list:
    """Zuletzt benutzte Team-Kategorien (Liste); ohne Angabe ['team_1']."""
    v = [c for c in normalize(_read().get("last_team")) if c in TEAM_IDS]
    return v or [TEAM_IDS[0]]


def set_last_team(categories) -> None:
    """Merkt die zuletzt benutzten Team-Kategorien (Voreinstellung der naechsten Team-Wette). Spieler-Kategorien werden ignoriert, ohne Team-Kategorie passiert nichts.
    Fehler beim Schreiben werden verschluckt (nur Komfort)."""
    cats = [c for c in normalize(categories) if c in TEAM_IDS]
    if not cats:
        return
    with _lock:
        try:
            _write(names(), cats)
        except Exception:
            pass


def default_player_category(mode: str) -> str:
    """Voreinstellung fuer Spieler-Wetten aus dem angezeigten Modus: 'team' (Teamabgleich) -> player_ta, 'raw' (roh) -> player_raw."""
    return MODE_CATEGORY.get(mode, MODE_CATEGORY["team"])
