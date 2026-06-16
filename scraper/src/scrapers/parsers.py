"""Pure parsing helpers for IMDB movie and review data."""

from __future__ import annotations

import json
import re
from typing import Any

from playwright.sync_api import Page

from src.structs.movie import Movie
from src.structs.review import Review


def extract_json_ld(page: Page) -> dict[str, Any]:
    try:
        raw = page.eval_on_selector(
            'script[type="application/ld+json"]',
            "el => el.textContent",
        )
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def ld_str(ld: dict[str, Any], key: str) -> str | None:
    val = ld.get(key)
    return str(val).strip() if val else None


def parse_runtime(text: str | None) -> int | None:
    """Convert 'PT142M' (ISO 8601 duration) or '2h 22m' to total minutes."""
    if not text:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if m:
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        return hours * 60 + minutes
    hours = re.search(r"(\d+)h", text)
    mins = re.search(r"(\d+)m", text)
    total = (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
    return total if total else None


def parse_year(ld: dict[str, Any], page: Page | None = None) -> int | None:
    date = ld.get("datePublished") or ld.get("startDate") or ""
    m = re.search(r"\d{4}", str(date))
    if m:
        return int(m.group())
    # fallback: year in the hero metadata link to /releaseinfo/
    if page:
        el = page.locator('a[href*="/releaseinfo/"]').first
        if el.count():
            m = re.search(r"\d{4}", el.inner_text())
            if m:
                return int(m.group())
    return None


def parse_rating(ld: dict[str, Any]) -> float | None:
    agg = ld.get("aggregateRating") or {}
    val = agg.get("ratingValue")
    try:
        return normalize_rating(float(val))
    except (TypeError, ValueError):
        return None


def parse_votes(ld: dict[str, Any]) -> int | None:
    agg = ld.get("aggregateRating") or {}
    val = agg.get("ratingCount")
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def parse_genres(ld: dict[str, Any]) -> list[str]:
    val = ld.get("genre")
    if isinstance(val, list):
        return [str(g).strip() for g in val]
    if isinstance(val, str):
        return [val.strip()]
    return []


def parse_directors(ld: dict[str, Any]) -> list[str]:
    directors = ld.get("director") or []
    if isinstance(directors, dict):
        directors = [directors]
    return [d.get("name", "").strip() for d in directors if d.get("name")]


def parse_cast(ld: dict[str, Any]) -> list[str]:
    actors = ld.get("actor") or []
    if isinstance(actors, dict):
        actors = [actors]
    return [a.get("name", "").strip() for a in actors[:5] if a.get("name")]


def parse_certificate(ld: dict[str, Any]) -> str | None:
    val = ld.get("contentRating")
    return str(val).strip() if val else None


def parse_title_type(ld: dict[str, Any]) -> str | None:
    val = ld.get("@type")
    if isinstance(val, list):
        return str(val[0]).strip() if val else None
    return str(val).strip() if val else None


def parse_metascore(page: Page) -> int | None:
    el = page.locator("span.score-meta").first
    if el.count():
        try:
            return int(el.inner_text().strip())
        except ValueError:
            pass
    return None


def parse_count(text: str | None) -> int | None:
    if not text:
        return None

    cleaned = text.strip().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([KkMm])?", cleaned)
    if not m:
        return None

    value = float(m.group(1))
    suffix = (m.group(2) or "").lower()
    multiplier = {"k": 1_000, "m": 1_000_000}.get(suffix, 1)
    return int(value * multiplier)


def normalize_rating(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 10, 4)


def build_movie(imdb_id: str, page: Page, ld: dict[str, Any]) -> Movie | None:
    """Assemble a Movie from a loaded title page and its JSON-LD blob."""
    title = ld_str(ld, "name")
    if not title:
        title_el = page.locator("h1[data-testid='hero__pageTitle'] span").first
        title = title_el.inner_text() if title_el.count() else None

    if not title:
        return None

    return Movie(
        imdb_id=imdb_id,
        title=title,
        year=parse_year(ld, page),
        imdb_rating=parse_rating(ld),
        votes=parse_votes(ld),
        genres=parse_genres(ld),
        directors=parse_directors(ld),
        main_cast=parse_cast(ld),
        runtime_min=parse_runtime(ld.get("duration")),
        certificate=parse_certificate(ld),
        metascore=parse_metascore(page),
        plot=ld_str(ld, "description"),
    )


def parse_review_card(card: Any, imdb_id: str) -> Review | None:
    try:
        text_el = card.locator("div.ipc-html-content-inner-div").first
        review_text = text_el.inner_text().strip() if text_el.count() else ""
        if not review_text:
            return None

        rating: float | None = None
        raw_rating: int | None = None
        rating_label: str | None = None
        rating_el = card.locator("span.ipc-rating-star[aria-label*='rating']").first
        if rating_el.count():
            rating_label = rating_el.get_attribute("aria-label") or ""
            m = re.search(r"rating:\s*(\d+)", rating_label, flags=re.IGNORECASE)
            if m:
                raw_rating = int(m.group(1))
            else:
                rating_text_el = rating_el.locator(".ipc-rating-star--rating").first
                rating_text = rating_text_el.inner_text().strip() if rating_text_el.count() else ""
                raw_rating = parse_count(rating_text)
            rating = normalize_rating(raw_rating)

        reviewer_name: str | None = None
        name_el = card.locator("a[aria-label^='User ']").first
        if name_el.count():
            label = name_el.get_attribute("aria-label") or ""
            reviewer_name = label.removeprefix("User ").strip() or None
        elif rating_label:
            m = re.search(r"(.+?)'s rating:", rating_label)
            if m:
                reviewer_name = m.group(1).strip() or None

        review_title: str | None = None
        title_el = card.locator(
            "[data-testid='review-summary'] .ipc-title__text, "
            "h3.ipc-title__text, "
            "h4.ipc-title__text"
        ).first
        if title_el.count():
            review_title = title_el.inner_text().strip() or None

        helpful_votes: int | None = None
        helpful_el = card.locator(".ipc-voting__label__count--up").first
        if helpful_el.count():
            helpful_votes = parse_count(helpful_el.inner_text())

        return Review(
            movie_imdb_id=imdb_id,
            reviewer_name=reviewer_name,
            rating=rating,
            review_title=review_title,
            review_text=review_text,
            helpful_votes=helpful_votes,
        )
    except Exception:
        return None
