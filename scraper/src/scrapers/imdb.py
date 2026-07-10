"""Scraper for random https://www.imdb.com title pages using Playwright."""

from __future__ import annotations

import os
import random
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
from tabulate import tabulate

from src.database.database_connection import insert_movie, insert_reviews
from src.scrapers.auth import IMDBAuth
from src.scrapers import parsers
from src.settings import custom_logger
from src.storage.jsonl import append_reviews_jsonl, write_movie_jsonl
from src.structs.movie import Movie
from src.structs.review import Review


class IMDBScraper:
    def __init__(
        self,
        base_url: str,
        max_movies: int,
        max_reviews_per_movie: int,
        output_dir: str,
        random_title_start: int = 1,
        random_title_end: int = 2_488_998,
        session_state_path: str = "",
        imdb_email: str = "",
        imdb_password: str = "",
        log_level: int = 20,
        s3_bucket: str = "",
        s3_prefix: str = "imdb",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_movies = max_movies
        self.max_reviews_per_movie = max_reviews_per_movie
        self.output_dir = output_dir
        self.random_title_start = random_title_start
        self.random_title_end = random_title_end
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix
        self.logger = custom_logger(self.__class__.__name__, log_level)

        self._auth = IMDBAuth(
            session_state_path=session_state_path,
            email=imdb_email,
            password=imdb_password,
            base_url=self.base_url,
            logger=self.logger,
        )

        os.makedirs(self.output_dir, exist_ok=True)
        if session_state_path:
            os.makedirs(Path(session_state_path).parent, exist_ok=True)

    _UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # Tried in order on the /reviews/ page
    _REVIEWS_PAGE_SELECTORS = [
        "article.user-review-item",
        "div[data-testid='review-card-parent']",
        "div[data-testid='shoveler-items-container'] > div",
        "div.ipc-list-card--span",
        "article",
        "div.lister-item",
    ]
    _REVIEWS_LOAD_MORE_SELECTOR = (
        "div[data-testid='tturv-pagination'] button, "
        "button.ipc-see-more__button, "
        "button[data-testid='load-more-btn'], "
        "button.ipl-load-more__button"
    )
    _REVIEWS_SPOILER_SELECTOR = (
        "button.review-spoiler-button, "
        "button[aria-label='Expand Spoiler']"
    )

    def run(self) -> None:
        self.logger.info(
            "Starting IMDB scraper — random title IDs: tt%07d-tt%07d, max movies: %d, max reviews: %d",
            self.random_title_start,
            self.random_title_end,
            self.max_movies,
            self.max_reviews_per_movie,
        )
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            saved_state = (
                self._auth.session_state_path
                if self._auth.session_state_path
                and Path(self._auth.session_state_path).exists()
                else None
            )
            context: BrowserContext = browser.new_context(
                user_agent=self._UA,
                locale="en-US",
                storage_state=saved_state,
            )
            self._context = context
            page = context.new_page()

            self._logged_in = False
            if self._auth.email and self._auth.password:
                if saved_state and self._auth.is_session_valid(page):
                    self.logger.info("Reusing saved IMDB session")
                    self._logged_in = True
                else:
                    self._logged_in = self._auth.login(page, context)
                    if not self._logged_in:
                        self.logger.error(
                            "IMDB login failed — reviews will be limited to featured only"
                        )

            saved_movies: list[dict] = []
            saved_reviews: list[dict] = []
            attempted_ids: set[str] = set()
            total_available_ids = self.random_title_end - self.random_title_start + 1

            while len(saved_movies) < self.max_movies and len(attempted_ids) < total_available_ids:
                imdb_id = self._generate_random_title_id(attempted_ids)
                attempted_ids.add(imdb_id)
                try:
                    movie = self._scrape_movie(page, imdb_id)
                    if not movie:
                        continue
                    self._save_movie(movie)
                    saved_movies.append(movie.model_dump())
                except Exception as e:
                    self.logger.error("Failed to scrape movie %s: %s", imdb_id, e)
                    continue

                try:
                    reviews = self._scrape_reviews(page, imdb_id)
                    insert_reviews(reviews)
                    self._save_reviews(reviews)
                    saved_reviews.extend(r.model_dump() for r in reviews)
                    print("----------------------------------------------------------------------------------------------------------------")
                    self.logger.info(
                        "Saved movie: %s (%s/%s),  reviews: %d",
                        imdb_id, len(saved_movies), self.max_movies, len(reviews)
                    )
                    print("----------------------------------------------------------------------------------------------------------------")
                except Exception as e:
                    self.logger.error("Failed to scrape reviews for %s: %s", imdb_id, e)

                time.sleep(1.5)

            if len(saved_movies) < self.max_movies:
                self.logger.warning(
                    "Only saved %d/%d movies after trying all %d configured title IDs",
                    len(saved_movies),
                    self.max_movies,
                    total_available_ids,
                )

            self._print_saved_movies_summary(saved_movies, saved_reviews)

            if self.s3_bucket:
                self._upload_to_s3(saved_movies, saved_reviews)

            browser.close()
        self.logger.info("Scraping complete.")

    def _print_saved_movies_summary(
        self,
        movies: list[dict],
        reviews: list[dict],
    ) -> None:
        if not movies:
            print("\nNo se guardaron películas.")
            return

        review_counts = Counter(review.get("movie_imdb_id") for review in reviews)
        rows = [
            {
                "imdb_id": movie.get("imdb_id", ""),
                "titulo": movie.get("title", ""),
                "rating": movie.get("imdb_rating", ""),
                "cantidad_reviews": review_counts.get(movie.get("imdb_id"), 0),
            }
            for movie in movies
        ]
        rows.sort(key=lambda row: row["cantidad_reviews"], reverse=True)
        con_rating_sin_reviews = sum(
            1
            for row in rows
            if row["rating"] not in (None, "") and row["cantidad_reviews"] == 0
        )

        print("\n--- películas guardadas por cantidad de reviews ---")
        print(tabulate(rows, headers="keys", tablefmt="rounded_outline", showindex=False))
        print(
            "\nPelículas con rating pero sin reviews: "
            f"{con_rating_sin_reviews} / {len(rows)}"
        )

    def manual_login(self) -> None:
        """Open a visible browser so a human can complete login and save session state."""
        if not self._auth.session_state_path:
            raise ValueError("SessionStatePath is required for manual login")

        self.logger.info("Opening visible browser for manual IMDB login")
        with sync_playwright() as p:
            from src.settings.constants import IMDB_AMAZON_LOGIN_URL

            browser = p.chromium.launch(headless=False)
            context = browser.new_context(user_agent=self._UA, locale="en-US")
            page = context.new_page()
            page.goto(IMDB_AMAZON_LOGIN_URL, wait_until="domcontentloaded")

            print(
                "\nComplete the IMDB/Amazon login in the browser, including any pulse, "
                "captcha, or MFA step. When you are logged in and back on IMDB, "
                "press Enter here to save the session.\n"
            )
            input("Press Enter after login is complete...")

            if self._auth.is_session_valid(page):
                context.storage_state(path=self._auth.session_state_path)
                self.logger.info("Session saved to %s", self._auth.session_state_path)
            else:
                self.logger.error(
                    "Session was not valid after manual login; not saving %s",
                    self._auth.session_state_path,
                )

            browser.close()

    # ------------------------------------------------------------------
    # Random title ID generation
    # ------------------------------------------------------------------

    def _generate_random_title_ids(self) -> list[str]:
        """Return unique random imdb_ids between tt0000001 and tt2488998."""
        start = self.random_title_start
        end = self.random_title_end
        if start > end:
            raise ValueError("RandomTitleStart must be lower than or equal to RandomTitleEnd")

        count = min(self.max_movies, end - start + 1)
        return [f"tt{number:07d}" for number in random.sample(range(start, end + 1), count)]

    def _generate_random_title_id(self, excluded_ids: set[str]) -> str:
        """Return one random imdb_id that has not been tried in this run."""
        start = self.random_title_start
        end = self.random_title_end
        if start > end:
            raise ValueError("RandomTitleStart must be lower than or equal to RandomTitleEnd")

        for _ in range(100):
            imdb_id = f"tt{random.randint(start, end):07d}"
            if imdb_id not in excluded_ids:
                return imdb_id

        for number in range(start, end + 1):
            imdb_id = f"tt{number:07d}"
            if imdb_id not in excluded_ids:
                return imdb_id

        raise ValueError("No title IDs left to try in the configured range")

    # ------------------------------------------------------------------
    # Movie detail scraping
    # ------------------------------------------------------------------

    def _scrape_movie(self, page: Page, imdb_id: str) -> Movie | None:
        page.goto(f"{self.base_url}/title/{imdb_id}/", wait_until="domcontentloaded")
        ld = parsers.extract_json_ld(page)
        title_type = parsers.parse_title_type(ld)
        if title_type != "Movie":
            self.logger.info(
                "Skipping %s because title type is %s, not Movie",
                imdb_id,
                title_type or "unknown",
            )
            return None
        movie = parsers.build_movie(imdb_id, page, ld)
        if not movie:
            self.logger.warning("Skipping %s because no title was found", imdb_id)
        return movie

    # ------------------------------------------------------------------
    # Reviews scraping
    # ------------------------------------------------------------------

    def _scrape_reviews(self, page: Page, imdb_id: str) -> list[Review]:
        reviews = self._scrape_reviews_page(page, imdb_id)
        if reviews:
            return reviews
        # self.logger.warning(
        #     "Reviews page returned nothing for %s — falling back to featured", imdb_id
        # )
        return self._scrape_featured_reviews(page, imdb_id)

    def _scrape_reviews_page(self, page: Page, imdb_id: str) -> list[Review]:
        url = self._get_user_reviews_url(page, imdb_id)
        page.goto(url, wait_until="domcontentloaded")

        if "/ap/signin" in page.url:
            self.logger.warning("Reviews page requires login for %s", imdb_id)
            return []

        if page.locator("section[data-testid='reviews-sign-in-card']").count():
            if not self._auth.login_from_reviews_gate(page, self._context):
                return []
            page.goto(url, wait_until="domcontentloaded")

        total_reviews_text = self._review_total_text(page)
        # if total_reviews_text:
        #     self.logger.info("Reviews page for %s reports %s", imdb_id, total_reviews_text)

        reviews: list[Review] = []
        processed = 0

        while len(reviews) < self.max_reviews_per_movie:
            cards = self._review_cards(page)

            if not cards or len(cards) <= processed:
                break

            self._expand_review_spoilers(page, imdb_id)

            for card in cards[processed:]:
                if len(reviews) >= self.max_reviews_per_movie:
                    break
                review = parsers.parse_review_card(card, imdb_id)
                if review:
                    reviews.append(review)

            processed = len(cards)

            if len(reviews) >= self.max_reviews_per_movie:
                # self.logger.info(
                #     "Stopping reviews for %s: reached MaxReviewsPerMovie=%d",
                #     imdb_id,
                #     self.max_reviews_per_movie,
                # )
                break

            cards_before = len(cards)
            if not self._click_reviews_load_more(page, imdb_id, cards_before):
                break

        return reviews

    def _review_total_text(self, page: Page) -> str | None:
        total_el = page.locator("div[data-testid='tturv-total-reviews']").first
        if not total_el.count():
            return None
        return total_el.inner_text().strip() or None

    def _review_cards(self, page: Page) -> list:
        for selector in self._REVIEWS_PAGE_SELECTORS:
            cards = page.locator(selector).all()
            if cards:
                return cards
        return []

    def _expand_review_spoilers(self, page: Page, imdb_id: str) -> None:
        spoiler_buttons = page.locator(self._REVIEWS_SPOILER_SELECTOR).all()
        if not spoiler_buttons:
            return

        expanded = 0
        for button in spoiler_buttons:
            try:
                if button.is_visible():
                    button.click()
                    expanded += 1
            except Exception:
                continue

        # if expanded:
        #     self.logger.info("Expanded %d spoiler reviews for %s", expanded, imdb_id)

    def _click_reviews_load_more(self, page: Page, imdb_id: str, cards_before: int) -> bool:
        load_more = self._reviews_load_more_button(page)
        if not load_more:
            self.logger.info("Stopping reviews for %s: no load-more button found", imdb_id)
            return False

        label = load_more.inner_text().strip() or load_more.get_attribute("aria-label") or "load more"
        # self.logger.info(
        #     "Clicking reviews pagination for %s: %s (cards before=%d)",
        #     imdb_id,
        #     label,
        #     cards_before,
        # )

        try:
            load_more.click()
            page.wait_for_function(
                """([selectors, previousCount]) => {
                    for (const selector of selectors) {
                        const count = document.querySelectorAll(selector).length;
                        if (count > previousCount) return true;
                    }
                    return false;
                }""",
                arg=[self._REVIEWS_PAGE_SELECTORS, cards_before],
                timeout=8000,
            )
        except PlaywrightTimeoutError:
            cards_after = len(self._review_cards(page))
            # self.logger.info(
            #     "Stopping reviews for %s: pagination did not add cards (before=%d, after=%d)",
            #     imdb_id,
            #     cards_before,
            #     cards_after,
            # )
            return False
        except Exception as e:
            # self.logger.warning("Stopping reviews for %s: pagination click failed: %s", imdb_id, e)
            return False

        cards_after = len(self._review_cards(page))
        # self.logger.info(
        #     "Loaded more reviews for %s: cards before=%d, cards after=%d",
        #     imdb_id,
        #     cards_before,
        #     cards_after,
        # )
        return cards_after > cards_before

    def _reviews_load_more_button(self, page: Page):
        buttons = page.locator(self._REVIEWS_LOAD_MORE_SELECTOR).all()
        for button in buttons:
            try:
                text = button.inner_text().strip().lower()
                class_name = button.get_attribute("class") or ""
                if (
                    "more" in text
                    or "see all" in text
                    or "ipc-see-more__button" in class_name
                    or button.get_attribute("data-testid") == "load-more-btn"
                    or "ipl-load-more__button" in class_name
                ):
                    return button
            except Exception:
                continue
        return None

    def _get_user_reviews_url(self, page: Page, imdb_id: str) -> str:
        title_url = f"{self.base_url}/title/{imdb_id}/"
        if page.url.rstrip("/") != title_url.rstrip("/"):
            page.goto(title_url, wait_until="domcontentloaded")

        link = page.locator(
            "section[data-testid='UserReviews'] "
            ".ipc-title__wrapper a[href*='/reviews/']"
        ).first
        if not link.count():
            self.logger.warning(
                "No User reviews header link found for %s; using default reviews URL",
                imdb_id,
            )
            return f"{self.base_url}/title/{imdb_id}/reviews/"

        href = link.get_attribute("href") or f"/title/{imdb_id}/reviews/"

        count_el = page.locator(
            "section[data-testid='UserReviews'] .ipc-title__subtext"
        ).first
        # if count_el.count():
        #     self.logger.info(
        #         "User reviews header for %s reports %s reviews",
        #         imdb_id,
        #         count_el.inner_text().strip(),
        #     )

        return urljoin(self.base_url, href)

    def _scrape_featured_reviews(self, page: Page, imdb_id: str) -> list[Review]:
        page.goto(f"{self.base_url}/title/{imdb_id}/", wait_until="domcontentloaded")

        try:
            page.wait_for_selector("section[data-testid='UserReviews']", timeout=8000)
        except Exception:
            self.logger.warning("No UserReviews section found for %s", imdb_id)
            return []

        cards = page.locator(
            "section[data-testid='UserReviews'] div[data-testid='shoveler-items-container'] > div"
        ).all()
        if not cards:
            # self.logger.warning("No featured review cards found for %s", imdb_id)
            return []

        reviews: list[Review] = []
        for card in cards[: self.max_reviews_per_movie]:
            review = parsers.parse_review_card(card, imdb_id)
            if review:
                reviews.append(review)
        return reviews

    # ------------------------------------------------------------------
    # S3 upload
    # ------------------------------------------------------------------

    def _upload_to_s3(self, movies: list[dict], reviews: list[dict]) -> None:
        if not movies:
            self.logger.warning("Nada que subir a S3 — el scraper no guardó ninguna película")
            return

        from datetime import datetime
        from src.storage.s3 import upload_parquet

        now = datetime.now()
        today = now.date().isoformat()
        run_id = now.strftime("%Y%m%d_%H%M%S")
        try:
            upload_parquet(
                movies,
                self.s3_bucket,
                f"{self.s3_prefix}/movies/scraped_date={today}/run_{run_id}.parquet",
            )
            upload_parquet(
                reviews,
                self.s3_bucket,
                f"{self.s3_prefix}/reviews/scraped_date={today}/run_{run_id}.parquet",
            )
            self.logger.info(
                "Uploaded %d movies and %d reviews to s3://%s/%s with run_id=%s",
                len(movies), len(reviews), self.s3_bucket, self.s3_prefix, run_id,
            )
        except Exception as e:
            self.logger.error("S3 upload failed (credentials expired?): %s", e)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_movie(self, movie: Movie) -> None:
        path = os.path.join(self.output_dir, f"{movie.imdb_id}.jsonl")
        write_movie_jsonl(path, movie.model_dump())
        insert_movie(movie)

    def _save_reviews(self, reviews: list[Review]) -> None:
        if not reviews:
            return
        imdb_id = reviews[0].movie_imdb_id
        path = os.path.join(self.output_dir, f"{imdb_id}.jsonl")
        entries = [{"type": "review", **r.model_dump()} for r in reviews]
        append_reviews_jsonl(path, entries)
