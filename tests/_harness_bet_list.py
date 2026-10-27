"""Harness: rendert nur die Wettliste (ui/bet_list.py) in einer Streamlit-Seite, fuer AppTest (tests/test_bet_categories.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui.bet_list import render_bet_list

render_bet_list()
