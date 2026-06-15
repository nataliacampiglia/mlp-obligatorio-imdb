"""ETL — transforma los datos crudos del scraper en un dataset listo para entrenar.

Extract  : lee los archivos Parquet de películas y reviews desde S3
Transform: une las tablas, agrega features de reviews, codifica géneros y certificados
Load     : sube el dataset procesado de vuelta a S3
           sube además un JSON de inferencia con los datos crudos + reviews anidadas

Uso:
    cd scraper
    poetry run python -m src.processing.etl

Resultados:
    s3://{S3Bucket}/{S3Prefix}/processed/training_dataset.parquet
    s3://{S3Bucket}/{S3Prefix}/inference/inference_dataset.json
    data/Inference/inference_dataset.json  (copia local)

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

import json
import sys
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
from tabulate import tabulate

# agregamos el root del proyecto al path para poder importar src.*
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.settings.settings import load_settings
from src.storage.s3 import upload_dataframe

class _NumpyEncoder(json.JSONEncoder):
    """Convierte tipos numpy a tipos Python nativos para que json.dump no falle.
    pandas devuelve numpy.bool_, numpy.int64, numpy.float64, numpy.ndarray
    al iterar un DataFrame, y el encoder estándar de JSON no los soporta."""

    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return None if np.isnan(obj) else float(obj)
        if isinstance(obj, np.bool_):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


# columnas de texto largo que truncamos para que la tabla entre en el terminal
_COLS_TRUNCAR = {"plot", "review_text", "review_title", "reviewer_name", "title"}
_MAX_ANCHO_CELDA = 40


def _tabla(df: pd.DataFrame, n: int = 10) -> str:
    """Devuelve las primeras n filas formateadas como tabla legible en el terminal."""
    vista = df.head(n).copy()
    for col in vista.columns:
        if col in _COLS_TRUNCAR or vista[col].dtype == object:
            vista[col] = vista[col].astype(str).str[:_MAX_ANCHO_CELDA]
    return tabulate(vista, headers="keys", tablefmt="rounded_outline", showindex=False)


def _nan_a_none(valor):
    """Convierte NaN/NA a None y floats enteros (2012.0) a int para JSON limpio."""
    if isinstance(valor, list):
        return valor
    # numpy y python floats: NaN → None, enteros sin decimales → int
    if isinstance(valor, (float, np.floating)):
        if np.isnan(valor):
            return None
        return int(valor) if valor == int(valor) else float(valor)
    try:
        return None if pd.isna(valor) else valor
    except (TypeError, ValueError):
        return valor



def _generar_json_inferencia(
    df_procesado: pd.DataFrame, df_reviews: pd.DataFrame
) -> list[dict]:
    """Arma la lista de objetos para inferencia: las mismas columnas que el
    parquet de entrenamiento, con las reviews anidadas como lista por película."""

    # agrupamos las reviews por película para accederlas rápido al iterar
    cols_review = ["rating", "review_title", "review_text", "helpful_votes"]
    reviews_por_pelicula: dict[str, list[dict]] = {}
    if not df_reviews.empty and "movie_imdb_id" in df_reviews.columns:
        cols_presentes = [c for c in cols_review if c in df_reviews.columns]
        for imdb_id, grupo in df_reviews.groupby("movie_imdb_id"):
            reviews_por_pelicula[str(imdb_id)] = [
                {col: _nan_a_none(fila[col]) for col in cols_presentes}
                for _, fila in grupo[cols_presentes].iterrows()
            ]

    resultado = []
    for _, fila in df_procesado.iterrows():
        obj = {}
        for col in df_procesado.columns:
            val = _nan_a_none(fila[col])
            # get_dummies devuelve bool en pandas moderno; lo convertimos a 0/1
            if isinstance(val, bool):
                val = int(val)
            obj[col] = val
        obj["reviews"] = reviews_por_pelicula.get(str(fila["imdb_id"]), [])
        resultado.append(obj)

    return resultado


def build_dataset(bucket: str, prefix: str) -> tuple[pd.DataFrame, list[dict]]:
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

    # mostramos las primeras 10 películas crudas para verificar que los datos llegaron bien
    print("\n--- primeras 10 películas (raw) ---")
    print(_tabla(df_movies[["imdb_id", "title", "imdb_rating"]]))

    # mostramos las primeras 10 reviews crudas
    print("\n--- primeras 10 reviews (raw) ---")
    print(_tabla(df_reviews[["movie_imdb_id", "reviewer_name", "rating"]]))

    # si no hay datos todavía, salimos con un mensaje claro en vez de crashear
    if df_movies.empty:
        print("\nNo hay películas en S3 todavía. Corré el scraper primero.")
        return pd.DataFrame(), []

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
    # columnas_a_eliminar = ["metascore", "plot", "votes", "directors", "main_cast"]
    # df = df.drop(columns=[c for c in columnas_a_eliminar if c in df.columns])

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
    # generamos el JSON de inferencia usando el df procesado (mismo contenido
    # que el parquet) y agregamos las reviews como lista anidada por película #
    # --------------------------------------------------------------------- #
    print("\nGenerando JSON de inferencia...")
    datos_inferencia = _generar_json_inferencia(df, df_reviews)

    # --------------------------------------------------------------------- #
    # resumen del dataset final                                              #
    # --------------------------------------------------------------------- #
    print(f"\nDataset final: {df.shape[0]:,} películas × {df.shape[1]} columnas")
    print(f"Columnas: {list(df.columns)}")

    # mostramos las primeras 10 filas del dataset ya procesado
    print("\n--- primeras 10 filas del dataset procesado (listo para entrenar) ---")
    print(_tabla(df[["imdb_id", "imdb_rating"]]))
    nulos = df.isnull().sum()
    nulos = nulos[nulos > 0]
    if len(nulos):
        print(f"\nColumnas con nulos (completar antes de entrenar):\n{nulos.to_string()}")
    else:
        print("\nSin valores nulos — listo para entrenar.")

    return df, datos_inferencia


if __name__ == "__main__":
    # leemos la configuración del bucket y prefix desde config.yml
    settings = load_settings("IMDBScraper")
    bucket: str = settings["S3Bucket"]
    prefix: str = settings["S3Prefix"]

    df, datos_inferencia = build_dataset(bucket, prefix)

    # --------------------------------------------------------------------- #
    # LOAD 1 — subimos el dataset de entrenamiento a S3 como Parquet        #
    # --------------------------------------------------------------------- #
    key_parquet = f"{prefix}/processed/training_dataset.parquet"
    upload_dataframe(df, bucket, key_parquet)
    print(f"\nParquet subido  → s3://{bucket}/{key_parquet}")

    # --------------------------------------------------------------------- #
    # LOAD 2 — guardamos el JSON de inferencia localmente y lo subimos a S3 #
    # el JSON tiene los datos crudos de cada película con sus reviews        #
    # anidadas, listo para usar en predicción                                #
    # --------------------------------------------------------------------- #
    carpeta_inferencia = Path("data/Inference")
    carpeta_inferencia.mkdir(parents=True, exist_ok=True)
    archivo_local = carpeta_inferencia / "inference_dataset.json"

    # guardamos una copia local
    with open(archivo_local, "w", encoding="utf-8") as f:
        json.dump(datos_inferencia, f, ensure_ascii=False, indent=2, cls=_NumpyEncoder)
    print(f"JSON guardado   → {archivo_local}  ({len(datos_inferencia):,} películas)")

    # subimos a S3
    key_json = f"{prefix}/inference/inference_dataset.json"
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key_json,
        Body=json.dumps(datos_inferencia, ensure_ascii=False, cls=_NumpyEncoder).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"JSON subido     → s3://{bucket}/{key_json}")
