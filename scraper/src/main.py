import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.database.database_connection import create_tables
from src.scrapers.imdb import IMDBScraper
from src.settings.settings import load_settings

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IMDB scraper → SQLite + JSONL")
    parser.add_argument(
        "--scraper",
        choices=["IMDBScraper"],
        default="IMDBScraper",
        help='Scraper to run (default: "IMDBScraper")',
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Open a visible browser to manually log in and save the IMDB session",
    )
    args = parser.parse_args()

    settings = load_settings(key="IMDBScraper")

    scraper = IMDBScraper(
        base_url=settings["BaseUrl"],
        max_movies=settings["MaxMovies"],
        max_reviews_per_movie=settings["MaxReviewsPerMovie"],
        output_dir=settings["OutputDir"],
        random_title_start=settings["RandomTitleStart"],
        random_title_end=settings["RandomTitleEnd"],
        session_state_path=settings["SessionStatePath"],
        imdb_email=os.environ.get("IMDB_EMAIL", ""),
        imdb_password=os.environ.get("IMDB_PASSWORD", ""),
        log_level=settings["LogLevel"],
    )

    if args.login_only:
        scraper.manual_login()
    else:
        create_tables()
        scraper.run()
