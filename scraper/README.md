# mlp-obligatorio-imdb

IMDB data scraper for a movie rating prediction ML project (obligatorio MLP).

## What it collects

- **Movies**: title, year, IMDB rating, votes, genres, director(s), top cast, runtime, certificate (PG/R/etc.), Metascore, plot — from the IMDB Top 250 list
- **Reviews**: reviewer name, score (1–10), date, review text, helpful votes — up to 25 reviews per movie

Data is stored in both **SQLite** (`src/database/imdb.db`) and **JSONL** files (`data/movies/`).

## Setup

```bash
poetry install
poetry run playwright install chromium
```

## Run

```bash
poetry run python src/main.py
```

## Configuration

Edit `src/settings/config.yml` to adjust:

| Key | Default | Description |
|---|---|---|
| `MaxMovies` | 250 | How many movies to scrape |
| `MaxReviewsPerMovie` | 25 | Reviews to collect per movie |
| `DBPath` | `src/database/imdb.db` | SQLite database path |
| `OutputDir` | `data/movies` | JSONL output directory |

## Verify the data

```bash
# Count rows
sqlite3 src/database/imdb.db "SELECT COUNT(*) FROM movies;"
sqlite3 src/database/imdb.db "SELECT COUNT(*) FROM reviews;"

# Sample
sqlite3 src/database/imdb.db "SELECT title, imdb_rating, genres FROM movies LIMIT 5;"
```
