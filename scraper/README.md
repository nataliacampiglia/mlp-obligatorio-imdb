# mlp-obligatorio-imdb

IMDB data scraper for a movie rating prediction ML project (obligatorio MLP).

## What it collects

- **Movies**: title, year, IMDB rating, votes, genres, director(s), top cast, runtime, certificate (PG/R/etc.), Metascore, plot — from random IMDB title IDs between `tt0000001` and `tt2488998`
- **Reviews**: reviewer name, score (1–10), review text, helpful votes — up to 25 reviews per movie

Data is stored in both **SQLite** (`src/database/imdb.db`) and **JSONL** files (`data/movies/`).
When `S3Bucket` is configured, the scraped movies and reviews are also uploaded to S3 as Parquet files. Each scraper run creates a new timestamped file, so multiple runs on the same day do not overwrite each other.

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

## ETL — preparar el dataset para entrenar el modelo

El ETL lee los archivos Parquet crudos que el scraper subió a S3, los transforma en un JSON plano y listo para entrenar, y sube el resultado de vuelta a S3.

### Qué hace paso a paso

| Paso | Qué hace |
|---|---|
| **Extract** | Lee todas las particiones y runs de `movies/` y `reviews/` desde S3 |
| **Transform 1** | Deduplica películas si el scraper corrió más de una vez (se queda con la versión más reciente) |
| **Transform 2** | Calcula el sentimiento promedio de las reviews de cada película con VADER |
| **Transform 3** | Elimina filas sin `imdb_rating` |
| **Load** | Guarda el JSON local y lo sube a `s3://{S3Bucket}/{S3Prefix}/processed/training_dataset.json` |

### Columnas del dataset final

| Columna | Tipo | Descripción |
|---|---|---|
| `imdb_id` | string | Identificador de la película |
| `title` | string | Título |
| `year` | int | Año de estreno |
| `imdb_rating` | float | Rating de IMDb normalizado de 0 a 1 |
| `votes` | int | Cantidad de votos en IMDb |
| `directors` | list[string] | Directores |
| `main_cast` | list[string] | Actores principales |
| `reviews` | float | Promedio del `compound` de VADER normalizado de 0 a 1 |

### Cómo correrlo

Primero asegurate de tener datos en S3 (correr el scraper al menos una vez con éxito). Si corrés el scraper varias veces el mismo día, cada corrida queda guardada con un timestamp distinto:

```text
s3://mlp-imdb-data/imdb/movies/scraped_date=YYYY-MM-DD/run_YYYYMMDD_HHMMSS.parquet
s3://mlp-imdb-data/imdb/reviews/scraped_date=YYYY-MM-DD/run_YYYYMMDD_HHMMSS.parquet
```

```bash
cd scraper
poetry run python -m src.processing.etl
```

El output muestra un preview de los datos en cada etapa y termina con:

```
JSON subido → s3://mlp-imdb-data/imdb/processed/training_dataset.json
```

### Cómo usar el dataset en un notebook

```python
import json
import boto3

obj = boto3.client("s3").get_object(
    Bucket="mlp-imdb-data",
    Key="imdb/processed/training_dataset.json",
)
movies = json.loads(obj["Body"].read())
```

### Estructura de S3 después de correr el scraper y el ETL

```
s3://mlp-imdb-data/
  imdb/
    movies/
      scraped_date=YYYY-MM-DD/
        run_YYYYMMDD_HHMMSS.parquet                ← datos crudos de una corrida
        run_YYYYMMDD_HHMMSS.parquet                ← otra corrida del mismo día
    reviews/
      scraped_date=YYYY-MM-DD/
        run_YYYYMMDD_HHMMSS.parquet                ← reviews crudas de una corrida
        run_YYYYMMDD_HHMMSS.parquet                ← otra corrida del mismo día
    processed/
      training_dataset.json                        ← dataset listo para entrenar
```

## Verify the data

```bash
# Count rows
sqlite3 src/database/imdb.db "SELECT COUNT(*) FROM movies;"
sqlite3 src/database/imdb.db "SELECT COUNT(*) FROM reviews;"

# Sample
sqlite3 src/database/imdb.db "SELECT title, imdb_rating, genres FROM movies LIMIT 5;"
```
