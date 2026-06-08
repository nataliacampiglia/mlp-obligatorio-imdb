"""JSONL file helpers for persisting movie and review data."""

from __future__ import annotations

import json
import os


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    lines = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return lines


def write_movie_jsonl(path: str, movie_dict: dict) -> None:
    """Write the movie entry as the first line, preserving any existing review lines."""
    existing = read_jsonl(path)
    reviews_only = [obj for obj in existing if obj.get("type") == "review"]
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(movie_dict, ensure_ascii=False) + "\n")
        for obj in reviews_only:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def append_reviews_jsonl(path: str, reviews: list[dict]) -> None:
    """Append new review entries, deduplicating by reviewer_name or review_title."""
    if not reviews:
        return
    existing = read_jsonl(path)
    seen: set[str] = {
        obj.get("reviewer_name") or obj.get("review_title", "")
        for obj in existing
        if obj.get("type") == "review"
    }
    with open(path, "a", encoding="utf-8") as f:
        for review in reviews:
            key = review.get("reviewer_name") or review.get("review_title") or ""
            if key and key not in seen:
                seen.add(key)
                f.write(json.dumps(review, ensure_ascii=False) + "\n")
