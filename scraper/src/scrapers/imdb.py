"""Scraper for https://www.imdb.com Top 250 movies using Playwright."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

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
        session_state_path: str = "",
        imdb_email: str = "",
        imdb_password: str = "",
        log_level: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.top_list_url = top_list_url
        self.max_movies = max_movies
        self.max_reviews_per_movie = max_reviews_per_movie
        self.output_dir = output_dir
        self.session_state_path = session_state_path
        self.imdb_email = imdb_email
        self.imdb_password = imdb_password
        self.logger = custom_logger(self.__class__.__name__, log_level)

        os.makedirs(self.output_dir, exist_ok=True)
        if session_state_path:
            os.makedirs(Path(session_state_path).parent, exist_ok=True)

    _UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def run(self) -> None:
        self.logger.info(
            "Starting IMDB scraper — top list: %s, max movies: %d, max reviews: %d",
            self.top_list_url,
            self.max_movies,
            self.max_reviews_per_movie,
        )
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            saved_state = (
                self.session_state_path
                if self.session_state_path and Path(self.session_state_path).exists()
                else None
            )
            context = browser.new_context(
                user_agent=self._UA,
                locale="en-US",
                storage_state=saved_state,
            )
            page = context.new_page()

            # Login if credentials are provided
            self._logged_in = False
            if self.imdb_email and self.imdb_password:
                if saved_state and self._is_session_valid(page):
                    self.logger.info("Reusing saved IMDB session")
                    self._logged_in = True
                else:
                    self._logged_in = self._login(page, context)
                    if not self._logged_in:
                        self.logger.error(
                            "IMDB login failed — reviews will be limited to featured only"
                        )

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
    # Authentication
    # ------------------------------------------------------------------

    def _is_session_valid(self, page: Page) -> bool:
        """Return True if the saved session cookies are still active."""
        page.goto(f"{self.base_url}/watchlist/", wait_until="domcontentloaded")
        return "/ap/signin" not in page.url

    def _login(self, page: Page, context: BrowserContext) -> bool:
        """Log in to IMDB via Amazon auth. Returns True on success."""
        self.logger.info("Logging in to IMDB as %s", self.imdb_email)
        login_url = (
            f"{self.base_url}/ap/signin"
            "?openid.return_to=https%3A%2F%2Fwww.imdb.com%2F"
            "&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select"
            "&openid.assoc_handle=imdb_us"
            "&openid.mode=checkid_setup"
            "&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select"
            "&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0"
        )
        try:
            page.goto(login_url, wait_until="domcontentloaded")

            # Email field
            page.wait_for_selector("input#ap_email", timeout=10000)
            page.fill("input#ap_email", self.imdb_email)

            # Some flows show a separate "Continue" button before the password field
            continue_btn = page.locator("input#continue").first
            if continue_btn.count():
                continue_btn.click()

            # Password field
            page.wait_for_selector("input#ap_password", timeout=8000)
            page.fill("input#ap_password", self.imdb_password)
            page.click("input#signInSubmit")

            # Wait for redirect back to IMDB (not Amazon)
            page.wait_for_url("**/imdb.com/**", timeout=15000)

            if "/ap/signin" in page.url or "/ap/mfa" in page.url:
                self.logger.error(
                    "Login redirect landed on %s — check credentials or disable 2FA", page.url
                )
                return False

            # Persist session so next run skips login
            if self.session_state_path:
                context.storage_state(path=self.session_state_path)
                self.logger.info("Session saved to %s", self.session_state_path)

            self.logger.info("IMDB login successful")
            return True
        except Exception as e:
            self.logger.error("Login error: %s", e)
            return False

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

    # Tried in order on the /reviews/ page
    _REVIEWS_PAGE_SELECTORS = [
        "div[data-testid='shoveler-items-container'] > div",
        "div.ipc-list-card--span",
        "article",
        "div.lister-item",
    ]

    def _scrape_reviews(self, page: Page, imdb_id: str) -> list[Review]:
        if self._logged_in:
            reviews = self._scrape_reviews_page(page, imdb_id)
            if reviews:
                return reviews
            self.logger.warning("Reviews page returned nothing for %s — falling back to featured", imdb_id)

        return self._scrape_featured_reviews(page, imdb_id)

    def _scrape_reviews_page(self, page: Page, imdb_id: str) -> list[Review]:
        """Scrape the full /reviews/ listing page (requires login)."""
        url = f"{self.base_url}/title/{imdb_id}/reviews/"
        page.goto(url, wait_until="domcontentloaded")

        reviews: list[Review] = []
        collected = 0

        while collected < self.max_reviews_per_movie:
            cards: list = []
            for selector in self._REVIEWS_PAGE_SELECTORS:
                cards = page.locator(selector).all()
                if cards:
                    break

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

    def _scrape_featured_reviews(self, page: Page, imdb_id: str) -> list[Review]:
        """Extract Featured reviews from the already-loaded main movie page."""
        # Navigate back to the main movie page if we left it
        if f"/title/{imdb_id}" not in page.url:
            page.goto(f"{self.base_url}/title/{imdb_id}/", wait_until="domcontentloaded")

        try:
            page.wait_for_selector("section[data-testid='UserReviews']", timeout=8000)
        except Exception:
            self.logger.warning("No UserReviews section found for %s", imdb_id)
            return []

        cards = page.locator("div[data-testid='shoveler-items-container'] > div").all()
        if not cards:
            self.logger.warning("No featured review cards found for %s", imdb_id)
            return []

        reviews: list[Review] = []
        for card in cards[: self.max_reviews_per_movie]:
            review = self._parse_review_card(card, imdb_id)
            if review:
                reviews.append(review)
        return reviews

    def _parse_review_card(self, card: Any, imdb_id: str) -> Review | None:
        try:
            # Review text
            text_el = card.locator("div.ipc-html-content-inner-div").first
            review_text = text_el.inner_text().strip() if text_el.count() else ""
            if not review_text:
                return None

            # Rating from aria-label "Author rating is 7"
            rating: int | None = None
            rating_el = card.locator("span.ipc-rating-star[aria-label^='Author rating']").first
            if rating_el.count():
                label = rating_el.get_attribute("aria-label") or ""
                m = re.search(r"(\d+)", label)
                if m:
                    rating = int(m.group(1))

            # Reviewer name from aria-label "User gobosox"
            reviewer_name: str | None = None
            name_el = card.locator("a[aria-label^='User ']").first
            if name_el.count():
                label = name_el.get_attribute("aria-label") or ""
                reviewer_name = label.removeprefix("User ").strip() or None

            # Review title from h3
            review_title: str | None = None
            title_el = card.locator("h3.ipc-title__text").first
            if title_el.count():
                review_title = title_el.inner_text().strip() or None

            return Review(
                movie_imdb_id=imdb_id,
                reviewer_name=reviewer_name,
                rating=rating,
                date=None,
                review_title=review_title,
                review_text=review_text,
                helpful_votes=None,
            )
        except Exception as e:
            self.logger.debug("Failed to parse review card: %s", e)
            return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _read_jsonl(self, path: str) -> list[dict]:
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

    def _save_movie(self, movie: Movie) -> None:
        jsonl_path = os.path.join(self.output_dir, f"{movie.imdb_id}.jsonl")
        existing = self._read_jsonl(jsonl_path)
        # Keep only review lines; the movie entry is replaced by the fresh one
        reviews_only = [obj for obj in existing if obj.get("type") == "review"]
        with open(jsonl_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(movie.model_dump(), ensure_ascii=False) + "\n")
            for obj in reviews_only:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        insert_movie(movie)

    def _save_reviews(self, reviews: list[Review]) -> None:
        if not reviews:
            return
        imdb_id = reviews[0].movie_imdb_id
        jsonl_path = os.path.join(self.output_dir, f"{imdb_id}.jsonl")
        existing = self._read_jsonl(jsonl_path)
        # Build a set of already-saved reviewer keys to skip duplicates
        seen: set[str] = {
            obj.get("reviewer_name") or obj.get("review_title", "")
            for obj in existing
            if obj.get("type") == "review"
        }
        new_entries = []
        for review in reviews:
            key = review.reviewer_name or review.review_title or ""
            if key and key not in seen:
                seen.add(key)
                new_entries.append({"type": "review", **review.model_dump()})
        if new_entries:
            with open(jsonl_path, "a", encoding="utf-8") as f:
                for entry in new_entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
