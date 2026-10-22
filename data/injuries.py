from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_ENDPOINT = "https://newsapi.org/v2/everything"


def fetch_team_news(team: str, max_results: int = 3) -> list[dict]:
    """Optional NewsAPI integration. Returns [] when NEWS_API_KEY is missing.

    Put NEWS_API_KEY=... in .env to activate.
    """
    if not NEWS_API_KEY:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=4)).date().isoformat()
    query = f'"{team}" NBA injury OR out OR questionable OR doubtful OR suspension OR suspended'
    params = {
        "apiKey": NEWS_API_KEY,
        "q": query,
        "from": since,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": max_results,
    }
    try:
        r = requests.get(NEWS_ENDPOINT, params=params, timeout=12)
        r.raise_for_status()
        articles = r.json().get("articles", [])
    except Exception:
        return []
    clean = []
    for a in articles[:max_results]:
        clean.append({
            "title": a.get("title") or "",
            "source": (a.get("source") or {}).get("name") or "",
            "url": a.get("url") or "",
            "publishedAt": a.get("publishedAt") or "",
        })
    return clean
