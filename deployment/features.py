import math
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

VADER_FALLBACK = 0.7
MAX_CAST = 5

_analyzer = SentimentIntensityAnalyzer()


def compute_vader_score(texts: list[str]) -> float:
    """Average VADER compound across texts, normalized to [0, 1].

    Mirrors the ETL formula in scraper/src/processing/etl.py so training and
    serving use the same featurizer (prevents training-serving skew).
    """
    if not texts:
        return VADER_FALLBACK
    compounds = [_analyzer.polarity_scores(t)["compound"] for t in texts if t.strip()]
    if not compounds:
        return VADER_FALLBACK
    return (sum(compounds) / len(compounds) + 1) / 2


def build_features(tmdb_movie: dict, imdb_votes: int | None, reviews_score: float) -> dict:
    credits = tmdb_movie.get("credits") or {}
    directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"]
    cast = [c["name"] for c in credits.get("cast", [])[:MAX_CAST]]

    votes = imdb_votes if imdb_votes is not None else tmdb_movie.get("vote_count", 0)
    year = int(tmdb_movie["release_date"][:4]) if tmdb_movie.get("release_date") else None

    return {
        "title": tmdb_movie.get("title", ""),
        "year": year,
        "log_votes": math.log1p(votes or 0),
        "reviews": reviews_score,
        "directors_text": "|".join(directors),
        "cast_text": "|".join(cast),
    }
