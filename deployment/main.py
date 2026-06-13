import os
import json
import boto3
import wandb
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from imdb_rating.schemas import ReviewInput, PredictionOutput
from imdb_rating.registry import load as load_model_from_registry

WANDB_PROJECT  = "imdb-rating"
WANDB_ARTIFACT = "imdb-rating-model"
WANDB_ALIAS    = "production"
WANDB_ENTITY    = "mlprod-obli"

S3_BUCKET       = "imdb-test-bucket-2026"
S3_KEY          = os.getenv("S3_MOVIES_KEY", "peliculas_random.json")

app = FastAPI(title="IMDB Rate Prediction")

app.mount("/static", StaticFiles(directory="static"), name="static")

_MODEL = None
_MODEL_VERSION: str | None = None


def _get_ssm_parameter(name: str) -> str:
    ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    return response["Parameter"]["Value"].strip()


def _get_wandb_credentials() -> tuple[str, str]:
    """Read credentials from SSM, falling back to env vars."""
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
        _MODEL, _MODEL_VERSION = load_model_from_registry(
            project=WANDB_PROJECT,
            artifact_name=WANDB_ARTIFACT,
            entity=WANDB_ENTITY,
            alias=WANDB_ALIAS,
            api_key=api_key,
        )
        print(f"[startup] Loaded {WANDB_ARTIFACT} version {_MODEL_VERSION}")
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


@app.get("/movies")
def list_movies():
    try:
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        data = json.loads(obj["Body"].read())
        movies = data if isinstance(data, list) else data.get("movies", [])
        return {"movies": movies}
    except s3.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail=f"Archivo '{S3_KEY}' no encontrado en el bucket")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error leyendo desde S3: {e}")


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
def predict(payload: ReviewInput) -> PredictionOutput:
    if _MODEL is None or _MODEL_VERSION is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    prediction = int(_MODEL.predict([payload.model_dump()])[0])
    print(f"Predicted rating {prediction} for review: {payload.review_text[:30]}...")
    return PredictionOutput(prediction=prediction, model_version=_MODEL_VERSION)
