# mlp-obligatorio-imdb

IMDB data scraper for a movie rating prediction ML project (obligatorio MLP).

## What it collects

- **Movies**: title, year, IMDB rating, votes, genres, director(s), top cast, runtime, certificate (PG/R/etc.), Metascore, plot — from random IMDB title IDs between `tt0000001` and `tt2488998`
- **Reviews**: reviewer name, score (1–10), review text, helpful votes — up to 25 reviews per movie

Data is stored in both **SQLite** (`src/database/imdb.db`) and **JSONL** files (`data/movies/`).
When `S3Bucket` is configured, the scraped movies and reviews are also uploaded to S3 as Parquet files.

## Setup

```bash
poetry install
poetry run playwright install chromium
```

Or from the project root using Make:

```bash
make scraper-install
```

## AWS credentials for S3 upload

The scraper uses `boto3` to upload Parquet files to S3. `boto3` reads AWS credentials automatically from your local AWS credentials file, so no credentials should be added to the code.

If you are using AWS Learner Lab, the credentials expire every time the lab session restarts. After each restart:

1. Open **AWS Details** in the lab console.
2. Copy the values from **AWS CLI**.
3. Create or edit the local credentials file:

```bash
mkdir -p ~/.aws
nano ~/.aws/credentials
```

Paste the values using this format:

```ini
[default]
aws_access_key_id=ASIA...
aws_secret_access_key=...
aws_session_token=...
```

Save and close the file. In `nano`, use `Ctrl + O`, `Enter`, and `Ctrl + X`.

Do not commit AWS credentials to the repository.

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
| `S3Bucket` | `mlp-imdb-data` | S3 bucket used for Parquet uploads |
| `S3Prefix` | `imdb` | Prefix inside the S3 bucket |

## Verify the data

```bash
# Count rows
sqlite3 src/database/imdb.db "SELECT COUNT(*) FROM movies;"
sqlite3 src/database/imdb.db "SELECT COUNT(*) FROM reviews;"

# Sample
sqlite3 src/database/imdb.db "SELECT title, imdb_rating, genres FROM movies LIMIT 5;"
```
