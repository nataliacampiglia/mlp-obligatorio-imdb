import os
import json
import boto3
import wandb
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

WANDB_ENTITY    = "mlprod-obli"
WANDB_PROJECT   = "imdb-rating"
WANDB_ARTIFACT  = "imdb-rating-model"
WANDB_ALIAS     = "production"

S3_BUCKET       = "imdb-test-bucket-2026"
S3_KEY          = os.getenv("S3_MOVIES_KEY", "peliculas_random.json")

app = FastAPI(title="IMDB Rate Prediction")

app.mount("/static", StaticFiles(directory="static"), name="static")


def _get_ssm_parameter(name: str) -> str:
    ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    return response["Parameter"]["Value"].strip()


def _get_wandb_credentials() -> tuple[str, str]:
    """Lee credenciales de SSM. Si no están disponibles, cae en variables de entorno."""
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


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/status")
def status():
    return {"status": "ok", "model": "not loaded"}


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
