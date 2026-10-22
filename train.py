"""
Run this ONCE to build & save the ELO model.
  python train.py
"""
import sys
sys.path.insert(0, ".")

from data.fetcher import fetch_seasons
from models.elo import build_model, EloEngine
from config.settings import SEASONS_TO_LOAD

if __name__ == "__main__":
    print("=" * 50)
    print("NBAEdge – Model Training")
    print("=" * 50)

    if EloEngine.exists():
        ans = input("Model already exists. Retrain? [y/N]: ").strip().lower()
        if ans != "y":
            print("Skipping. Run app.py to start dashboard.")
            sys.exit(0)

    print(f"\nFetching {len(SEASONS_TO_LOAD)} seasons from BallDontLie...")
    games = fetch_seasons(SEASONS_TO_LOAD)
    print(f"\nTotal games: {len(games)}")

    print("\nBuilding ELO model...")
    engine = build_model(games)

    print(f"\n  Verarbeitete Spiel-IDs im Modell: {len(engine.processed_ids)} | Ratings bis: {engine.ratings_as_of()}")
    print("  Danach taeglich: python update_model.py")
    print("\n✓ Training complete. Run: streamlit run app.py")
