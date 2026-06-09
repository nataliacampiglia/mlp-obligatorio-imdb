import json
import sqlite3

from src.database.sql_queries import (
    CREATE_MOVIES_TABLE,
    CREATE_REVIEWS_TABLE,
    INSERT_MOVIE,
    INSERT_REVIEW,
    SELECT_ALL_MOVIES,
    SELECT_ALL_REVIEWS,
)
from src.settings.settings import load_settings
from src.structs.movie import Movie
from src.structs.review import Review

settings = load_settings(key="IMDBScraper")
DB_PATH = settings["DBPath"]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables() -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(CREATE_MOVIES_TABLE)
    cursor.execute(CREATE_REVIEWS_TABLE)
    conn.commit()
    conn.close()


def insert_movie(movie: Movie) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            INSERT_MOVIE,
            {
                "imdb_id": movie.imdb_id,
                "title": movie.title,
                "year": movie.year,
                "imdb_rating": movie.imdb_rating,
                "votes": movie.votes,
                "genres": json.dumps(movie.genres),
                "directors": json.dumps(movie.directors),
                "main_cast": json.dumps(movie.main_cast),
                "runtime_min": movie.runtime_min,
                "certificate": movie.certificate,
                "metascore": movie.metascore,
                "plot": movie.plot,
            },
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error inserting movie {movie.imdb_id}: {e}")
        conn.rollback()
    finally:
        conn.close()


def insert_reviews(reviews: list[Review]) -> None:
    if not reviews:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.executemany(
            INSERT_REVIEW,
            [
                {
                    "movie_imdb_id": r.movie_imdb_id,
                    "reviewer_name": r.reviewer_name,
                    "rating": r.rating,
                    "review_title": r.review_title,
                    "review_text": r.review_text,
                    "helpful_votes": r.helpful_votes,
                }
                for r in reviews
            ],
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error inserting reviews: {e}")
        conn.rollback()
    finally:
        conn.close()


def show_all_movies() -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(SELECT_ALL_MOVIES)
        for row in cursor.fetchall():
            print(dict(row))
    except sqlite3.Error as e:
        print(f"Error reading movies: {e}")
    finally:
        conn.close()


def show_all_reviews() -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(SELECT_ALL_REVIEWS)
        for row in cursor.fetchall():
            print(dict(row))
    except sqlite3.Error as e:
        print(f"Error reading reviews: {e}")
    finally:
        conn.close()
