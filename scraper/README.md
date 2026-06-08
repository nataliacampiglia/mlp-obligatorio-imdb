# mlp-obligatorio-imdb

IMDB data scraper for a movie rating prediction ML project (obligatorio MLP).

## What it collects

- **Movies**: title, year, IMDB rating, votes, genres, director(s), top cast, runtime, certificate (PG/R/etc.), Metascore, plot — from random IMDB title IDs between `tt0000001` and `tt2488998`
- **Reviews**: reviewer name, score (1–10), date, review text, helpful votes — up to 25 reviews per movie

Data is stored in both **SQLite** (`src/database/imdb.db`) and **JSONL** files (`data/movies/`).

## Setup

```bash
poetry install
poetry run playwright install chromium
```

Or from the project root using Make:

```bash
make scraper-install
```

## Login for full reviews

IMDb requires login to access the full user reviews page. The scraper supports a manual login flow that opens a visible browser, lets you complete the Amazon/IMDb login and any pulse/captcha/MFA step yourself, and then saves the session for later runs.

From the `scraper` directory, run:

```bash
poetry run python src/main.py --login-only
```

Then:

1. Complete the login in the browser.
2. Solve any pulse, captcha, or MFA challenge manually.
3. Wait until you are logged in and back on IMDb.
4. Return to the terminal and press Enter.

If the login is valid, the scraper saves the session to:

```text
data/session.json
```

After that, run the scraper normally:

```bash
poetry run python src/main.py
```

The scraper will reuse `data/session.json` and should be able to read the gated full reviews page. If the session expires, run `--login-only` again.

Do not commit `data/session.json`, passwords, or cookies to the repository.

## Run

```bash
poetry run python src/main.py
```

Or from the project root using Make:

```bash
make scraper-run
```

## Configuration

Edit `src/settings/config.yml` to adjust:

| Key | Default | Description |
|---|---|---|
| `RandomTitleStart` | `1` | First numeric IMDB title ID to sample |
| `RandomTitleEnd` | `2488998` | Last numeric IMDB title ID to sample |
| `MaxMovies` | 20 | How many movies to scrape |
| `MaxReviewsPerMovie` | 20 | Reviews to collect per movie |
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
