CREATE_MOVIES_TABLE = """
    CREATE TABLE IF NOT EXISTS movies (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        imdb_id      TEXT    NOT NULL UNIQUE,
        title        TEXT    NOT NULL,
        year         INTEGER,
        imdb_rating  REAL,
        votes        INTEGER,
        genres       TEXT,
        directors    TEXT,
        main_cast    TEXT,
        runtime_min  INTEGER,
        certificate  TEXT,
        metascore    INTEGER,
        plot         TEXT
    )
"""

CREATE_REVIEWS_TABLE = """
    CREATE TABLE IF NOT EXISTS reviews (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        movie_imdb_id  TEXT    NOT NULL,
        reviewer_name  TEXT,
        rating         INTEGER,
        date           TEXT,
        review_text    TEXT    NOT NULL,
        helpful_votes  INTEGER
    )
"""

INSERT_MOVIE = """
    INSERT OR IGNORE INTO movies
        (imdb_id, title, year, imdb_rating, votes, genres, directors, main_cast,
         runtime_min, certificate, metascore, plot)
    VALUES
        (:imdb_id, :title, :year, :imdb_rating, :votes, :genres, :directors, :main_cast,
         :runtime_min, :certificate, :metascore, :plot)
"""

INSERT_REVIEW = """
    INSERT INTO reviews (movie_imdb_id, reviewer_name, rating, date, review_text, helpful_votes)
    VALUES (:movie_imdb_id, :reviewer_name, :rating, :date, :review_text, :helpful_votes)
"""

SELECT_ALL_MOVIES = "SELECT * FROM movies"
SELECT_ALL_REVIEWS = "SELECT * FROM reviews"
