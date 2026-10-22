"""Harness: rendert nur den Tab "Spieler" (ui/player_tab.py) in einer Streamlit-Seite, fuer AppTest (tests/test_player_tab.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui.player_tab import render_player_tab

render_player_tab()
