"""IMDB authentication via Amazon OAuth using Playwright."""

from __future__ import annotations

import re
from logging import Logger

from playwright.sync_api import BrowserContext, Page

from src.settings.constants import IMDB_AMAZON_LOGIN_URL


class IMDBAuth:
    def __init__(
        self,
        session_state_path: str,
        email: str,
        password: str,
        base_url: str,
        logger: Logger,
    ) -> None:
        self.session_state_path = session_state_path
        self.email = email
        self.password = password
        self.base_url = base_url
        self.logger = logger

    def is_session_valid(self, page: Page) -> bool:
        """Return True if the saved session cookies are still active."""
        page.goto(f"{self.base_url}/watchlist/", wait_until="domcontentloaded")
        return "/ap/signin" not in page.url

    def login(self, page: Page, context: BrowserContext) -> bool:
        """Log in to IMDB via Amazon auth. Returns True on success."""
        self.logger.info("Logging in to IMDB as %s", self.email)
        try:
            self.logger.info("Navigating to login URL: %s", IMDB_AMAZON_LOGIN_URL)
            page.goto(IMDB_AMAZON_LOGIN_URL, wait_until="domcontentloaded")
            return self._complete_amazon_login(page, context)
        except Exception as e:
            self.logger.error("Login error: %s", e)
            return False

    def _complete_amazon_login(self, page: Page, context: BrowserContext) -> bool:
        """Fill the Amazon auth form and persist the resulting IMDb session."""
        try:
            email_input = page.locator(
                "input#ap_email, input[name='email'], input[type='email']"
            ).first
            password_input = page.locator(
                "input#ap_password, input[name='password'], input[type='password']"
            ).first

            if not email_input.count() and not password_input.count():
                self.logger.error(
                    "Login form not found at %s; page title: %s",
                    page.url,
                    page.title(),
                )
                return False

            if email_input.count():
                email_input.fill(self.email)

                # Some flows show a separate "Continue" button before the password field
                continue_btn = page.locator(
                    "input#continue, button#continue, input[aria-labelledby='continue-announce']"
                ).first
                if continue_btn.count():
                    continue_btn.click()
                    page.wait_for_load_state("domcontentloaded")

            try:
                page.wait_for_selector(
                    "input#ap_password, input[name='password'], input[type='password']",
                    timeout=15000,
                )
            except Exception:
                error_text = page.locator(
                    "#auth-error-message-box, .a-alert-error, #authportal-main-section"
                ).first
                message = error_text.inner_text().strip() if error_text.count() else ""
                self.logger.error(
                    "Password field not found at %s; page title: %s%s",
                    page.url,
                    page.title(),
                    f"; page message: {message}" if message else "",
                )
                return False

            password_input = page.locator(
                "input#ap_password, input[name='password'], input[type='password']"
            ).first
            password_input.fill(self.password)

            submit = page.locator("input#signInSubmit, button#signInSubmit").first
            if submit.count():
                submit.click()
            else:
                password_input.press("Enter")

            page.wait_for_url("**/imdb.com/**", timeout=15000)

            if "amazon.com/ap/signin" in page.url or "/ap/mfa" in page.url:
                self.logger.error(
                    "Login redirect landed on %s — check credentials or disable 2FA", page.url
                )
                return False

            if self.session_state_path:
                context.storage_state(path=self.session_state_path)
                self.logger.info("Session saved to %s", self.session_state_path)

            self.logger.info("IMDB login successful")
            return True
        except Exception as e:
            self.logger.error("Login error: %s", e)
            return False

    def login_from_reviews_gate(self, page: Page, context: BrowserContext | None) -> bool:
        """Follow the IMDb reviews sign-in card to Amazon auth."""
        if not context:
            self.logger.error(
                "Cannot sign in from reviews page because browser context is unavailable"
            )
            return False

        if not self.email or not self.password:
            self.logger.warning(
                "Reviews page requires login, but IMDB_EMAIL/IMDB_PASSWORD are not set"
            )
            return False

        try:
            self.logger.info("Reviews page is gated; signing in through IMDb")

            sign_in = page.locator("[data-testid='reviews-sign-in-card-button']").first
            if sign_in.count():
                sign_in.click()
                page.wait_for_load_state("domcontentloaded")

            existing_account = page.get_by_text(
                re.compile(r"sign in to an existing account", re.I)
            ).first
            if existing_account.count():
                existing_account.click()
                page.wait_for_load_state("domcontentloaded")

            amazon = page.get_by_text(re.compile(r"sign in with amazon", re.I)).first
            if amazon.count():
                amazon.click()
                page.wait_for_load_state("domcontentloaded")

            return self._complete_amazon_login(page, context)
        except Exception as e:
            self.logger.error("Reviews sign-in flow failed: %s", e)
            return False
