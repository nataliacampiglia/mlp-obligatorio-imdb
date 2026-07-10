import os
import requests

TMDB_BASE = "https://api.themoviedb.org/3"
OMDB_BASE = "http://www.omdbapi.com/"


def _tmdb_headers() -> dict:
    token = os.getenv("TMDB_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "accept": "application/json"}


def get_movie_with_credits(tmdb_id: int) -> dict:
    r = requests.get(
        f"{TMDB_BASE}/movie/{tmdb_id}",
        headers=_tmdb_headers(),
        params={"append_to_response": "credits,reviews"},
        timeout=5,
    )
    r.raise_for_status()
    return r.json()


def get_movie_review_texts(tmdb_movie: dict, limit: int = 10) -> list[str]:
    reviews = (tmdb_movie.get("reviews") or {}).get("results", [])
    return [r["content"] for r in reviews[:limit] if r.get("content")]


def get_imdb_rating_and_votes(imdb_id: str) -> tuple[float | None, int | None]:
    api_key = os.getenv("OMDB_API_KEY", "")
    r = requests.get(OMDB_BASE, params={"apikey": api_key, "i": imdb_id}, timeout=5)
    r.raise_for_status()
    data = r.json()
    if data.get("Response") != "True":
        return None, None
    try:
        rating = float(data.get("imdbRating", "N/A"))
    except ValueError:
        rating = None
    try:
        votes = int(data.get("imdbVotes", "0").replace(",", ""))
    except ValueError:
        votes = None
    return rating, votes
