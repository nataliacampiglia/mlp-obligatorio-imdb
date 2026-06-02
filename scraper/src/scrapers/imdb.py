"""Scraper for https://www.imdb.com Top 250 movies using Playwright."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from playwright.sync_api import Page, sync_playwright

from src.database.database_connection import insert_movie, insert_reviews
from src.settings import custom_logger
from src.structs.movie import Movie
from src.structs.review import Review

_IMDB_ID_RE = re.compile(r"/(tt\d+)")


def _extract_imdb_id(url: str) -> str | None:
    m = _IMDB_ID_RE.search(url)
    return m.group(1) if m else None


def _parse_votes(text: str | None) -> int | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else None


def _parse_runtime(text: str | None) -> int | None:
    """Convert 'PT142M' (ISO 8601 duration) or '2h 22m' to total minutes."""
    if not text:
        return None
    # ISO duration from JSON-LD: PT2H22M or PT142M
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if m:
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        return hours * 60 + minutes
    # Human-readable fallback: "2h 22m"
    hours = re.search(r"(\d+)h", text)
    mins = re.search(r"(\d+)m", text)
    total = (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
    return total if total else None


class IMDBScraper:
    def __init__(
        self,
        base_url: str,
        top_list_url: str,
        max_movies: int,
        max_reviews_per_movie: int,
        output_dir: str,
        log_level: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.top_list_url = top_list_url
        self.max_movies = max_movies
        self.max_reviews_per_movie = max_reviews_per_movie
        self.output_dir = output_dir
        self.logger = custom_logger(self.__class__.__name__, log_level)

        os.makedirs(self.output_dir, exist_ok=True)

    def run(self) -> None:
        self.logger.info(
            "Starting IMDB scraper — top list: %s, max movies: %d, max reviews: %d",
            self.top_list_url,
            self.max_movies,
            self.max_reviews_per_movie,
        )
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = context.new_page()

            movie_ids = self._scrape_top_list(page)
            self.logger.info("Found %d movie IDs in Top 250 list", len(movie_ids))

            for i, imdb_id in enumerate(movie_ids[: self.max_movies], start=1):
                self.logger.info("Processing movie %d/%d: %s", i, self.max_movies, imdb_id)
                try:
                    movie = self._scrape_movie(page, imdb_id)
                    if not movie:
                        continue
                    self._save_movie(movie)
                except Exception as e:
                    self.logger.error("Failed to scrape movie %s: %s", imdb_id, e)
                    continue

                try:
                    reviews = self._scrape_reviews(page, imdb_id)
                    insert_reviews(reviews)
                    self._save_reviews(reviews)
                    self.logger.info(
                        "Saved movie %s with %d reviews", imdb_id, len(reviews)
                    )
                except Exception as e:
                    self.logger.error("Failed to scrape reviews for %s: %s", imdb_id, e)

                time.sleep(1.5)

            browser.close()
        self.logger.info("Scraping complete.")

    # ------------------------------------------------------------------
    # Top-list scraping
    # ------------------------------------------------------------------

    def _scrape_top_list(self, page: Page) -> list[str]:
        """Return ordered list of imdb_ids from the Top 250 chart."""
        page.goto(self.top_list_url, wait_until="domcontentloaded")
        page.wait_for_selector("a[href*='/title/tt']", timeout=15000)

        hrefs = page.eval_on_selector_all(
            "a[href*='/title/tt']",
            "els => els.map(e => e.getAttribute('href'))",
        )
        seen: set[str] = set()
        ids: list[str] = []
        for href in hrefs:
            imdb_id = _extract_imdb_id(href or "")
            if imdb_id and imdb_id not in seen:
                seen.add(imdb_id)
                ids.append(imdb_id)
        return ids

    # ------------------------------------------------------------------
    # Movie detail scraping
    # ------------------------------------------------------------------

    def _scrape_movie(self, page: Page, imdb_id: str) -> Movie | None:
        url = f"{self.base_url}/title/{imdb_id}/"
        page.goto(url, wait_until="domcontentloaded")

        # IMDB embeds structured data as JSON-LD — parse it first
        ld_json = self._extract_json_ld(page)

        title = self._ld_str(ld_json, "name")
        if not title:
            # fallback to page title
            title_el = page.locator("h1[data-testid='hero__pageTitle'] span").first
            title = title_el.inner_text() if title_el.count() else imdb_id

        year = self._parse_year(ld_json)
        imdb_rating = self._parse_rating(ld_json)
        votes = self._parse_votes_ld(ld_json)
        genres = self._parse_genres(ld_json)
        directors = self._parse_directors(ld_json)
        main_cast = self._parse_cast(ld_json)
        runtime_min = _parse_runtime(ld_json.get("duration") if ld_json else None)
        certificate = self._parse_certificate(ld_json)
        metascore = self._parse_metascore(page)
        plot = self._ld_str(ld_json, "description")

        return Movie(
            imdb_id=imdb_id,
            title=title,
            year=year,
            imdb_rating=imdb_rating,
            votes=votes,
            genres=genres,
            directors=directors,
            main_cast=main_cast,
            runtime_min=runtime_min,
            certificate=certificate,
            metascore=metascore,
            plot=plot,
        )

    def _extract_json_ld(self, page: Page) -> dict[str, Any]:
        try:
            raw = page.eval_on_selector(
                'script[type="application/ld+json"]',
                "el => el.textContent",
            )
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def _ld_str(self, ld: dict[str, Any], key: str) -> str | None:
        val = ld.get(key)
        return str(val).strip() if val else None

    def _parse_year(self, ld: dict[str, Any]) -> int | None:
        date = ld.get("datePublished") or ld.get("startDate") or ""
        m = re.search(r"\d{4}", str(date))
        return int(m.group()) if m else None

    def _parse_rating(self, ld: dict[str, Any]) -> float | None:
        agg = ld.get("aggregateRating") or {}
        val = agg.get("ratingValue")
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _parse_votes_ld(self, ld: dict[str, Any]) -> int | None:
        agg = ld.get("aggregateRating") or {}
        val = agg.get("ratingCount")
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    def _parse_genres(self, ld: dict[str, Any]) -> list[str]:
        val = ld.get("genre")
        if isinstance(val, list):
            return [str(g).strip() for g in val]
        if isinstance(val, str):
            return [val.strip()]
        return []

    def _parse_directors(self, ld: dict[str, Any]) -> list[str]:
        directors = ld.get("director") or []
        if isinstance(directors, dict):
            directors = [directors]
        return [d.get("name", "").strip() for d in directors if d.get("name")]

    def _parse_cast(self, ld: dict[str, Any]) -> list[str]:
        actors = ld.get("actor") or []
        if isinstance(actors, dict):
            actors = [actors]
        return [a.get("name", "").strip() for a in actors[:5] if a.get("name")]

    def _parse_certificate(self, ld: dict[str, Any]) -> str | None:
        val = ld.get("contentRating")
        return str(val).strip() if val else None

    def _parse_metascore(self, page: Page) -> int | None:
        el = page.locator("span.score-meta").first
        if el.count():
            try:
                return int(el.inner_text().strip())
            except ValueError:
                pass
        return None

    # ------------------------------------------------------------------
    # Reviews scraping
    # ------------------------------------------------------------------

    # Selectors tried in order — from most specific to broadest fallback
    _REVIEW_CARD_SELECTORS = [
        "article[data-testid='review-card']",
        "div[data-testid='review-card']",
        "article.sc-f37d8606-1",
        "div.review-container",
        "article",
    ]

    def _find_review_cards(self, page: Page) -> list:
        for selector in self._REVIEW_CARD_SELECTORS:
            cards = page.locator(selector).all()
            if cards:
                return cards
        return []

    def _scrape_reviews(self, page: Page, imdb_id: str) -> list[Review]:
        url = f"{self.base_url}/title/{imdb_id}/reviews/"
        page.goto(url, wait_until="domcontentloaded")

        # Wait for any known review container; return [] if none appear
        try:
            page.wait_for_selector(
                ", ".join(self._REVIEW_CARD_SELECTORS), timeout=10000
            )
        except Exception:
            self.logger.warning("No review cards found for %s — skipping reviews", imdb_id)
            return []

        reviews: list[Review] = []
        collected = 0

        while collected < self.max_reviews_per_movie:
            cards = self._find_review_cards(page)
            if not cards:
                break

            for card in cards:
                if collected >= self.max_reviews_per_movie:
                    break
                review = self._parse_review_card(card, imdb_id)
                if review:
                    reviews.append(review)
                    collected += 1

            load_more = page.locator(
                "button[data-testid='load-more-btn'], button.ipl-load-more__button"
            ).first
            if load_more.count() and collected < self.max_reviews_per_movie:
                load_more.click()
                time.sleep(1.5)
            else:
                break

        return reviews

    def _parse_review_card(self, card: Any, imdb_id: str) -> Review | None:
        try:
            # Review text — try multiple layouts
            text_el = card.locator(
                "div[data-testid='review-overflow'], "
                "div[data-testid='review-text'], "
                "div[data-testid='review-summary'] + div, "
                "div.text.show-more__control, "
                "div.content .text, "
                "div.ipc-html-content-inner-div"
            ).first
            review_text = text_el.inner_text().strip() if text_el.count() else ""
            if not review_text:
                return None

            # Rating (reviewer's own score)
            rating: int | None = None
            rating_el = card.locator(
                "span[data-testid='review-rating'], span.rating-other-user-rating span"
            ).first
            if rating_el.count():
                try:
                    rating = int(rating_el.inner_text().strip().split("/")[0])
                except (ValueError, IndexError):
                    pass

            # Reviewer name
            name_el = card.locator(
                "a[data-testid='author-name'], span.display-name-link a"
            ).first
            reviewer_name = name_el.inner_text().strip() if name_el.count() else None

            # Review date
            date_el = card.locator(
                "span[data-testid='review-date'], span.review-date"
            ).first
            date = date_el.inner_text().strip() if date_el.count() else None

            # Helpful votes
            helpful_votes: int | None = None
            helpful_el = card.locator(
                "div[data-testid='review-helpful'], div.actions.text-muted"
            ).first
            if helpful_el.count():
                helpful_text = helpful_el.inner_text()
                m = re.search(r"(\d[\d,]*)", helpful_text)
                if m:
                    helpful_votes = int(m.group(1).replace(",", ""))

            return Review(
                movie_imdb_id=imdb_id,
                reviewer_name=reviewer_name,
                rating=rating,
                date=date,
                review_text=review_text,
                helpful_votes=helpful_votes,
            )
        except Exception as e:
            self.logger.debug("Failed to parse review card: %s", e)
            return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_movie(self, movie: Movie) -> None:
        jsonl_path = os.path.join(self.output_dir, f"{movie.imdb_id}.jsonl")
        entry = movie.model_dump()
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        insert_movie(movie)

    def _save_reviews(self, reviews: list[Review]) -> None:
        for review in reviews:
            jsonl_path = os.path.join(self.output_dir, f"{review.movie_imdb_id}.jsonl")
            entry = {"type": "review", **review.model_dump()}
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
