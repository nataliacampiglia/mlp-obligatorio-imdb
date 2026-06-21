"""Append-only prediction logger backed by a public S3 bucket.

Each prediction is written as its own object so concurrent writes never
race against each other. Listing + analytics happen in `analyze.py`.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests

BUCKET_NAME = os.getenv("OBS_BUCKET_NAME", "mlp-imdb-observability-2026")
BUCKET_REGION = os.getenv("OBS_BUCKET_REGION", "us-east-1")
BUCKET_URL = f"https://{BUCKET_NAME}.s3.{BUCKET_REGION}.amazonaws.com"
PREFIX = "predictions"


def log_prediction(
    tmdb_id: int,
    imdb_id: Optional[str],
    movie_title: str,
    prediction: int,
    prediction_raw: float,
    real_rating: Optional[float],
    model_version: str,
    model_strategy: Optional[str],
    review_count: int,
    vader_score: float,
    log_votes: float,
) -> Optional[str]:
    """Write the prediction event to S3. Returns the key, or None on failure."""
    ts = datetime.now(timezone.utc)
    error = abs(prediction - real_rating) if real_rating is not None else None
    record = {
        "ts": ts.isoformat(),
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "movie_title": movie_title,
        "prediction": prediction,
        "prediction_raw": prediction_raw,
        "real_rating": real_rating,
        "error": error,
        "model_version": model_version,
        "model_strategy": model_strategy,
        "review_count": review_count,
        "vader_score": vader_score,
        "log_votes": log_votes,
    }
    key = f"{PREFIX}/dt={ts:%Y-%m-%d}/{uuid.uuid4().hex[:12]}.json"
    try:
        r = requests.put(
            f"{BUCKET_URL}/{key}",
            data=json.dumps(record).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=3,
        )
        r.raise_for_status()
        return key
    except Exception as e:
        print(f"[logger] Failed to write prediction: {e}")
        return None
