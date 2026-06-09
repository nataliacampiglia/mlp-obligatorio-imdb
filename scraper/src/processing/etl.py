"""ETL — transforma los datos crudos del scraper en un dataset listo para entrenar.

Extract  : lee los archivos Parquet de películas y reviews desde S3
Transform: une las tablas, agrega features de reviews, codifica géneros y certificados
Load     : sube el dataset procesado de vuelta a S3

Uso:
    cd scraper
    poetry run python -m src.processing.etl

Resultado:
    s3://{S3Bucket}/{S3Prefix}/processed/training_dataset.parquet

Columnas del dataset final:
    imdb_id            — identificador de la película (no usar como feature)
    year, runtime_min, metascore          — features numéricas
    genre_{*}          — géneros codificados como multi-hot (0 o 1 por género)
    cert_{*}           — clasificación de contenido codificada como one-hot
    num_reviews        — cantidad de reviews scrapeadas para esa película
    avg_review_rating  — promedio del rating dado por los usuarios en sus reviews
    avg_helpful_votes  — promedio de votos "útiles" por review
    imdb_rating        — TARGET que queremos predecir (float entre 1 y 10)

Columnas que se excluyen y por qué:
    title, plot        — texto libre; si queremos usarlos hay que hacer embeddings aparte
    votes              — es la cantidad de votos del rating de IMDB, correlaciona
                         directamente con el target y no estaría disponible al predecir
    directors, main_cast — listas de strings complejas de codificar; se pueden agregar después
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# agregamos el root del proyecto al path para poder importar src.*
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.settings.settings import load_settings
from src.storage.s3 import upload_dataframe


def build_dataset(bucket: str, prefix: str) -> pd.DataFrame:
    base = f"s3://{bucket}/{prefix}"

    # --------------------------------------------------------------------- #
    # EXTRACT — leemos los datos crudos desde S3                            #
    # pandas lee todas las particiones (scraped_date=...) de una sola vez   #
    # --------------------------------------------------------------------- #
    print(f"Leyendo películas  → {base}/movies/")
    df_movies = pd.read_parquet(f"{base}/movies/")

    print(f"Leyendo reviews    → {base}/reviews/")
    df_reviews = pd.read_parquet(f"{base}/reviews/")

    print(f"Filas crudas  — películas: {len(df_movies):,} | reviews: {len(df_reviews):,}")

    # si no hay datos todavía, salimos con un mensaje claro en vez de crashear
    if df_movies.empty:
        print("\nNo hay películas en S3 todavía. Corré el scraper primero.")
        return pd.DataFrame()

    # --------------------------------------------------------------------- #
    # TRANSFORM paso 1 — deduplicación de películas                         #
    # si corrimos el scraper varias veces, la misma película puede aparecer  #
    # en varias particiones; nos quedamos con la versión más reciente        #
    # --------------------------------------------------------------------- #
    if "scraped_date" in df_movies.columns:
        df_movies = (
            df_movies
            .sort_values("scraped_date", ascending=False)
            .drop_duplicates("imdb_id")
            .drop(columns=["scraped_date"])
        )
        print(f"Después de dedup  — películas: {len(df_movies):,}")

    # --------------------------------------------------------------------- #
    # TRANSFORM paso 2 — agregamos features de reviews por película         #
    # en vez de tener una fila por review, calculamos estadísticas           #
    # resumidas para cada película: cuántas reviews tiene, el rating         #
    # promedio que le dieron los usuarios, y los votos de utilidad promedio  #
    # --------------------------------------------------------------------- #
    review_agg = (
        df_reviews
        .groupby("movie_imdb_id")
        .agg(
            num_reviews=("review_text", "count"),
            avg_review_rating=("rating", "mean"),
            avg_helpful_votes=("helpful_votes", "mean"),
        )
        .reset_index()
        .rename(columns={"movie_imdb_id": "imdb_id"})
    )

    # si no hay reviews todavía, creamos un DataFrame vacío con las columnas esperadas
    # para que el merge no falle y las columnas de reviews queden como NaN
    if df_reviews.empty or "movie_imdb_id" not in df_reviews.columns:
        print("Advertencia: no hay reviews en S3 — las columnas de reviews quedarán vacías.")
        review_agg = pd.DataFrame(
            columns=["imdb_id", "num_reviews", "avg_review_rating", "avg_helpful_votes"]
        )

    # unimos las películas con sus estadísticas de reviews
    # usamos left join para no perder películas que no tengan reviews
    df = df_movies.merge(review_agg, on="imdb_id", how="left")

    # --------------------------------------------------------------------- #
    # TRANSFORM paso 3 — codificamos géneros como multi-hot                 #
    # cada género se convierte en una columna binaria (0 o 1)               #
    # por ejemplo: genre_action=1, genre_drama=0, etc.                      #
    # --------------------------------------------------------------------- #
    todos_los_generos = sorted({
        g
        for generos in df["genres"].dropna()
        for g in generos
        if g
    })
    for genero in todos_los_generos:
        col = f"genre_{genero.lower().replace(' ', '_').replace('-', '_')}"
        df[col] = df["genres"].apply(
            lambda x, g=genero: int(isinstance(x, list) and g in x)
        )
    # ya no necesitamos la columna original de géneros
    df = df.drop(columns=["genres"])

    # --------------------------------------------------------------------- #
    # TRANSFORM paso 4 — codificamos el certificado como one-hot            #
    # (PG, R, PG-13, etc.) cada valor se convierte en su propia columna     #
    # --------------------------------------------------------------------- #
    df = pd.get_dummies(df, columns=["certificate"], prefix="cert", dummy_na=False)

    # --------------------------------------------------------------------- #
    # TRANSFORM paso 5 — eliminamos columnas que no sirven como features    #
    # --------------------------------------------------------------------- #
    columnas_a_eliminar = ["title", "plot", "votes", "directors", "main_cast"]
    df = df.drop(columns=[c for c in columnas_a_eliminar if c in df.columns])

    # --------------------------------------------------------------------- #
    # TRANSFORM paso 6 — eliminamos filas sin target                        #
    # no podemos entrenar con películas que no tienen imdb_rating            #
    # --------------------------------------------------------------------- #
    antes = len(df)
    df = df.dropna(subset=["imdb_rating"]).reset_index(drop=True)
    eliminadas = antes - len(df)
    if eliminadas:
        print(f"Se eliminaron {eliminadas:,} filas sin imdb_rating")

    # --------------------------------------------------------------------- #
    # resumen del dataset final                                              #
    # --------------------------------------------------------------------- #
    print(f"\nDataset final: {df.shape[0]:,} películas × {df.shape[1]} columnas")
    print(f"Columnas: {list(df.columns)}")
    nulos = df.isnull().sum()
    nulos = nulos[nulos > 0]
    if len(nulos):
        print(f"\nColumnas con nulos (completar antes de entrenar):\n{nulos.to_string()}")
    else:
        print("\nSin valores nulos — listo para entrenar.")

    return df


if __name__ == "__main__":
    # leemos la configuración del bucket y prefix desde config.yml
    settings = load_settings("IMDBScraper")
    bucket: str = settings["S3Bucket"]
    prefix: str = settings["S3Prefix"]

    df = build_dataset(bucket, prefix)

    # --------------------------------------------------------------------- #
    # LOAD — subimos el dataset procesado a S3                              #
    # --------------------------------------------------------------------- #
    key = f"{prefix}/processed/training_dataset.parquet"
    upload_dataframe(df, bucket, key)
    print(f"\nDataset subido → s3://{bucket}/{key}")
