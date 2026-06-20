import os
import sys
import boto3
import wandb
import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from imdb_rating.schemas import PredictRequest, PredictionOutput
from imdb_rating.registry import load as load_model_from_registry, get_production_metadata

from external_apis import get_movie_with_credits, get_imdb_rating_and_votes, get_movie_review_texts
from features import build_features, compute_vader_score
from monitoring.logger import log_prediction


def _pipe_tokenizer(x: str) -> list[str]:
    return x.split("|")


# joblib pickle resolves the tokenizer via __main__; uvicorn replaces it, so we inject.
sys.modules["__main__"]._pipe_tokenizer = _pipe_tokenizer


WANDB_PROJECT  = "imdb-rating"
WANDB_ARTIFACT = "imdb-rating-model"
WANDB_ALIAS    = "production"
WANDB_ENTITY   = "mlprod-obli"

app = FastAPI(title="IMDB Rate Prediction")
app.mount("/static", StaticFiles(directory="static"), name="static")

_MODEL = None
_MODEL_VERSION: str | None = None
_MODEL_STRATEGY: str | None = None


def _get_ssm_parameter(name: str) -> str:
    ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    return response["Parameter"]["Value"].strip()


def _get_wandb_credentials() -> tuple[str, str]:
    try:
        user = _get_ssm_parameter("wandb-org")
        api_key = _get_ssm_parameter("wandb-api-key")
        return user, api_key
    except (BotoCoreError, ClientError):
        user = os.getenv("WANDB_USER")
        api_key = os.getenv("WANDB_API_KEY")
        if not user or not api_key:
            raise
        return user, api_key


@app.on_event("startup")
def _load_model() -> None:
    global _MODEL, _MODEL_VERSION
    try:
        entity, api_key = _get_wandb_credentials()
    except (BotoCoreError, ClientError) as e:
        print(f"[startup] W&B credentials unavailable, skipping model load: {e}")
        return

    try:
        global _MODEL_STRATEGY
        _MODEL, _MODEL_VERSION = load_model_from_registry(
            project=WANDB_PROJECT,
            artifact_name=WANDB_ARTIFACT,
            entity=WANDB_ENTITY,
            alias=WANDB_ALIAS,
            api_key=api_key,
        )
        meta = get_production_metadata(
            project=WANDB_PROJECT,
            artifact_name=WANDB_ARTIFACT,
            entity=WANDB_ENTITY,
            alias=WANDB_ALIAS,
            api_key=api_key,
        ) or {}
        _MODEL_STRATEGY = meta.get("strategy")
        print(f"[startup] Loaded {WANDB_ARTIFACT} version {_MODEL_VERSION} strategy={_MODEL_STRATEGY}")
    except Exception as e:
        print(f"[startup] Could not load model from W&B: {e}")


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/status")
def status():
    return {
        "status": "ok",
        "model": "loaded" if _MODEL is not None else "not loaded",
        "model_version": _MODEL_VERSION,
    }


@app.get("/config")
def config():
    return {"tmdb_token": os.getenv("TMDB_TOKEN", "")}


@app.get("/model")
def get_production_model():
    try:
        _, api_key = _get_wandb_credentials()
    except (BotoCoreError, ClientError) as e:
        raise HTTPException(status_code=503, detail=f"No se pudo leer credenciales de SSM: {e}")

    try:
        api = wandb.Api(api_key=api_key)
        artifact = api.artifact(f"{WANDB_ENTITY}/{WANDB_PROJECT}/{WANDB_ARTIFACT}:{WANDB_ALIAS}")
        return {
            "name": WANDB_ARTIFACT,
            "version": artifact.version,
            "aliases": artifact.aliases,
            "created_at": artifact.created_at,
            "url": artifact.url,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al conectar con W&B: {e}")


@app.post("/predict", response_model=PredictionOutput)
def predict(payload: PredictRequest) -> PredictionOutput:
    if _MODEL is None or _MODEL_VERSION is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        movie = get_movie_with_credits(payload.tmdb_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TMDb fetch failed: {e}")

    imdb_id = movie.get("imdb_id")
    real_rating, imdb_votes = (None, None)
    if imdb_id:
        try:
            real_rating, imdb_votes = get_imdb_rating_and_votes(imdb_id)
        except Exception as e:
            print(f"[predict] OMDb fetch failed: {e}")

    review_texts = get_movie_review_texts(movie)
    reviews_score = compute_vader_score(review_texts)

    features = build_features(movie, imdb_votes, reviews_score)
    raw = float(_MODEL.predict(pd.DataFrame([features]))[0])
    prediction = max(1, min(10, round(raw * 10)))

    print(f"[predict] tmdb={payload.tmdb_id} imdb={imdb_id} pred={prediction} real={real_rating} reviews_n={len(review_texts)} vader={reviews_score:.3f}")

    log_prediction(
        tmdb_id=payload.tmdb_id,
        imdb_id=imdb_id,
        movie_title=movie.get("title", ""),
        prediction=prediction,
        prediction_raw=raw,
        real_rating=real_rating,
        model_version=_MODEL_VERSION,
        model_strategy=_MODEL_STRATEGY,
        review_count=len(review_texts),
        vader_score=reviews_score,
        log_votes=features["log_votes"],
    )

    return PredictionOutput(
        prediction=prediction,
        prediction_raw=raw,
        real_rating=real_rating,
        imdb_id=imdb_id,
        model_version=_MODEL_VERSION,
    )
