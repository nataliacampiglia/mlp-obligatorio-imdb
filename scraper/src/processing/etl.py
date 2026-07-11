"""ETL — transforma los datos crudos del scraper en un JSON procesado.

Extract  : lee los archivos Parquet de películas y reviews desde S3
Transform: deduplica películas y agrega sentimiento promedio de reviews con VADER
Load     : sube el dataset procesado de vuelta a S3 como JSON

Uso:
    cd scraper
    poetry run python -m src.processing.etl

Resultados:
    s3://{S3Bucket}/{S3Prefix}/processed/training_dataset.json
    data/Processed/training_dataset.json  (copia local)

Columnas del dataset final:
    imdb_id      — identificador de IMDb
    title        — título
    year         — año de estreno
    imdb_rating  — rating de IMDb normalizado de 0 a 1
    votes        — cantidad de votos en IMDb
    directors    — lista de directores
    main_cast    — lista de actores principales
    reviews      — sentimiento promedio de reviews calculado con VADER y normalizado de 0 a 1
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
import numpy as np
import pandas as pd
from tabulate import tabulate
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# agregamos el root del proyecto al path para poder importar src.*
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
os.chdir(_PROJECT_ROOT)

from src.settings.settings import load_settings


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


class S3DataUnavailableError(RuntimeError):
    """Error esperado cuando S3 no está disponible o faltan datos crudos."""


def _mensaje_error_s3(error: Exception) -> str:
    if isinstance(error, (NoCredentialsError, PartialCredentialsError)):
        return (
            "No encontré credenciales AWS válidas. Copiá el bloque AWS CLI del "
            "Learner Lab y corré `make aws-credentials`."
        )

    if isinstance(error, ClientError):
        codigo = error.response.get("Error", {}).get("Code", "")
        if codigo in {"ExpiredToken", "InvalidToken", "TokenRefreshRequired"}:
            return (
                "Las credenciales AWS expiraron. Renová el bloque AWS CLI del "
                "Learner Lab con `make aws-credentials` y volvé a correr el scraper "
                "para subir los Parquet antes del ETL."
            )
        if codigo in {"AccessDenied", "UnauthorizedOperation"}:
            return (
                "AWS rechazó el acceso a S3. Revisá que las credenciales sean las "
                "del Learner Lab activo y que tengan permiso sobre el bucket."
            )
        if codigo in {"NoSuchBucket", "404"}:
            return "El bucket configurado no existe o no es accesible."
        return f"AWS devolvió {codigo or 'un error'} al consultar S3: {error}"

    return str(error)


def _validar_prefijo_s3(bucket: str, prefix: str, nombre: str) -> None:
    """Verifica credenciales y que exista al menos un objeto bajo el prefijo."""
    try:
        respuesta = boto3.client("s3").list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            MaxKeys=1,
        )
    except (ClientError, NoCredentialsError, PartialCredentialsError) as error:
        raise S3DataUnavailableError(_mensaje_error_s3(error)) from error

    if respuesta.get("KeyCount", 0) == 0:
        raise S3DataUnavailableError(
            f"No encontré archivos de {nombre} en s3://{bucket}/{prefix}. "
            "Corré `make scraper-run` con credenciales AWS vigentes antes de `make etl-run`."
        )


def _tabla(df: pd.DataFrame, n: int = 10) -> str:
    """Devuelve las primeras n filas formateadas como tabla legible en el terminal."""
    vista = df.head(n).copy()
    for col in vista.columns:
        if col in _COLS_TRUNCAR or vista[col].dtype == object:
            vista[col] = vista[col].astype(str).str[:_MAX_ANCHO_CELDA]
    return tabulate(vista, headers="keys", tablefmt="rounded_outline", showindex=False)


def _resumen_nulos(df: pd.DataFrame, nombre: str) -> None:
    total = len(df)
    filas = []
    for col in df.columns:
        nulos = int(df[col].isna().sum())
        vacios = 0
        try:
            if df[col].dtype == object:
                vacios = int((df[col].dropna() == "").sum())
        except Exception:
            pass
        if nulos > 0 or vacios > 0:
            filas.append({
                "columna": col,
                "null": f"{nulos} / {total}",
                'vacío ""': f"{vacios} / {total}" if vacios > 0 else "-",
            })
    print(f"\n--- nulos en {nombre} ({total:,} filas) ---")
    if filas:
        print(tabulate(filas, headers="keys", tablefmt="rounded_outline"))
    else:
        print("Sin valores nulos ni vacíos.")


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


def _normalizar_lista_strings(valor) -> list[str]:
    """Devuelve una lista de strings, sin importar cómo pandas/parquet leyó el valor."""
    if valor is None:
        return []

    try:
        if pd.isna(valor):
            return []
    except (TypeError, ValueError):
        pass

    if isinstance(valor, np.ndarray):
        valor = valor.tolist()

    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return []
        try:
            decodificado = json.loads(texto)
        except json.JSONDecodeError:
            return [texto]
        return _normalizar_lista_strings(decodificado)

    if isinstance(valor, (list, tuple, set)):
        return [str(g).strip() for g in valor if g and str(g).strip()]

    return []


def _normalizar_0_1(valor: float | int | None, maximo: float) -> float | None:
    valor = _nan_a_none(valor)
    if valor is None:
        return None
    valor = float(valor)
    if 0 <= valor <= 1:
        return round(valor, 4)
    return round(valor / maximo, 4)


def _sentimiento_vader_por_pelicula(df_reviews: pd.DataFrame) -> pd.DataFrame:
    """Calcula el promedio VADER compound por película, normalizado a 0..1."""
    columnas = ["imdb_id", "reviews"]
    if (
        df_reviews.empty
        or "movie_imdb_id" not in df_reviews.columns
        or "review_text" not in df_reviews.columns
    ):
        print("Advertencia: no hay reviews en S3 — el sentimiento quedará vacío.")
        return pd.DataFrame(columns=columnas)

    analyzer = SentimentIntensityAnalyzer()
    reviews = df_reviews[["movie_imdb_id", "review_text"]].copy()
    reviews["review_text"] = reviews["review_text"].fillna("").astype(str)
    reviews = reviews[reviews["review_text"].str.strip() != ""]

    if reviews.empty:
        print("Advertencia: no hay textos de reviews — el sentimiento quedará vacío.")
        return pd.DataFrame(columns=columnas)

    reviews["vader_compound"] = reviews["review_text"].apply(
        lambda texto: analyzer.polarity_scores(texto)["compound"]
    )
    reviews["reviews"] = (reviews["vader_compound"] + 1) / 2

    return (
        reviews
        .groupby("movie_imdb_id", as_index=False)["reviews"]
        .mean()
        .rename(columns={"movie_imdb_id": "imdb_id"})
    )


def _generar_json_procesado(df: pd.DataFrame) -> list[dict]:
    """Arma el JSON final con sólo los campos pedidos por película."""
    resultado = []
    for _, fila in df.iterrows():
        reviews = _nan_a_none(fila.get("reviews"))
        resultado.append({
            "imdb_id": str(fila["imdb_id"]),
            "title": _nan_a_none(fila.get("title")),
            "year": _nan_a_none(fila.get("year")),
            "imdb_rating": _normalizar_0_1(fila.get("imdb_rating"), 10),
            "votes": _nan_a_none(fila.get("votes")),
            "directors": _normalizar_lista_strings(fila.get("directors")),
            "main_cast": _normalizar_lista_strings(fila.get("main_cast")),
            "reviews": round(float(reviews), 4) if reviews is not None else None,
        })

    return resultado


def build_dataset(bucket: str, prefix: str) -> list[dict]:
    base = f"s3://{bucket}/{prefix}"
    movies_prefix = f"{prefix}/movies/"
    reviews_prefix = f"{prefix}/reviews/"

    # --------------------------------------------------------------------- #
    # EXTRACT — leemos los datos crudos desde S3                            #
    # pandas lee todas las particiones (scraped_date=...) de una sola vez   #
    # --------------------------------------------------------------------- #
    _validar_prefijo_s3(bucket, movies_prefix, "películas")
    _validar_prefijo_s3(bucket, reviews_prefix, "reviews")

    print(f"Leyendo películas  → {base}/movies/")
    try:
        df_movies = pd.read_parquet(f"{base}/movies/")
    except Exception as error:
        raise S3DataUnavailableError(
            "No pude leer los Parquet de películas desde S3. "
            f"Detalle: {_mensaje_error_s3(error)}"
        ) from error

    print(f"Leyendo reviews    → {base}/reviews/")
    try:
        df_reviews = pd.read_parquet(f"{base}/reviews/")
    except Exception as error:
        raise S3DataUnavailableError(
            "No pude leer los Parquet de reviews desde S3. "
            f"Detalle: {_mensaje_error_s3(error)}"
        ) from error

    print(f"Filas crudas  — películas: {len(df_movies):,} | reviews: {len(df_reviews):,}")

    # si no hay datos todavía, salimos con un mensaje claro en vez de crashear
    if df_movies.empty:
        print("\nNo hay películas en S3 todavía. Corré el scraper primero.")
        return []

    preview_movies = df_movies[["imdb_id", "title", "imdb_rating"]].copy()
    preview_movies["imdb_rating"] = pd.to_numeric(preview_movies["imdb_rating"], errors="coerce")

    print("\n--- 10 mejores películas por rating ---")
    print(_tabla(preview_movies.sort_values("imdb_rating", ascending=False)))

    print("\n--- 10 peores películas por rating ---")
    print(_tabla(preview_movies.sort_values("imdb_rating", ascending=True)))

    # mostramos las primeras 10 reviews crudas
    print("\n--- primeras 10 reviews (raw) ---")
    print(_tabla(df_reviews[["movie_imdb_id", "reviewer_name", "rating"]]))

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

    _resumen_nulos(df_movies, "películas")
    _resumen_nulos(df_reviews, "reviews")

    # --------------------------------------------------------------------- #
    # TRANSFORM paso 2 — calculamos sentimiento VADER por película          #
    # VADER devuelve compound entre -1 y 1; lo pasamos a escala 0..1        #
    # --------------------------------------------------------------------- #
    review_agg = _sentimiento_vader_por_pelicula(df_reviews)
    df = df_movies.merge(review_agg, on="imdb_id", how="left")

    # --------------------------------------------------------------------- #
    # TRANSFORM paso 3 — eliminamos filas sin target                        #
    # no podemos entrenar con películas que no tienen imdb_rating            #
    # --------------------------------------------------------------------- #
    antes = len(df)
    df = df.dropna(subset=["imdb_rating"]).reset_index(drop=True)
    eliminadas = antes - len(df)
    if eliminadas:
        print(f"Se eliminaron {eliminadas:,} filas sin imdb_rating")

    print("\nGenerando JSON procesado...")
    datos_procesados = _generar_json_procesado(df)

    # --------------------------------------------------------------------- #
    # resumen del dataset final                                              #
    # --------------------------------------------------------------------- #
    print(f"\nDataset final: {len(datos_procesados):,} películas × 8 campos\n")

    nulos = df.isnull().sum()
    nulos = nulos[nulos > 0]
    # mostramos las columnas con nulos
    if len(nulos):
        filas_nulos = [
            {
                "columna": columna,
                "null": int(cantidad),
                "total": len(df),
            }
            for columna, cantidad in nulos.items()
        ]
        print("\nColumnas con nulos (completar antes de entrenar):")
        print(tabulate(filas_nulos, headers="keys", tablefmt="rounded_outline"))
    else:
        print("\nSin valores nulos — listo para entrenar.")

    return datos_procesados


if __name__ == "__main__":
    # leemos la configuración del bucket y prefix desde config.yml
    settings = load_settings("IMDBScraper")
    bucket: str = settings["S3Bucket"]
    prefix: str = settings["S3Prefix"]

    try:
        datos_procesados = build_dataset(bucket, prefix)
    except S3DataUnavailableError as error:
        print(f"\nError leyendo datos crudos desde S3:\n{error}")
        sys.exit(1)

    # --------------------------------------------------------------------- #
    # LOAD — guardamos el JSON procesado localmente y lo subimos a S3       #
    # --------------------------------------------------------------------- #
    carpeta_procesados = Path("data/Processed")
    carpeta_procesados.mkdir(parents=True, exist_ok=True)
    archivo_local = carpeta_procesados / "training_dataset.json"

    # guardamos una copia local
    with open(archivo_local, "w", encoding="utf-8") as f:
        json.dump(datos_procesados, f, ensure_ascii=False, indent=2, cls=_NumpyEncoder)
    print(f"JSON guardado   → {archivo_local}  ({len(datos_procesados):,} películas)")

    # subimos a S3
    key_json = f"{prefix}/processed/training_dataset.json"
    try:
        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=key_json,
            Body=json.dumps(datos_procesados, ensure_ascii=False, cls=_NumpyEncoder).encode("utf-8"),
            ContentType="application/json",
        )
    except (ClientError, NoCredentialsError, PartialCredentialsError) as error:
        print(f"\nError subiendo JSON procesado a S3:\n{_mensaje_error_s3(error)}")
        sys.exit(1)
    print(f"JSON subido     → s3://{bucket}/{key_json}")
