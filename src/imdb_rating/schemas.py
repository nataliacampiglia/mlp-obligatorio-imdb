from pydantic import BaseModel, Field
from typing import Optional


class PredictRequest(BaseModel):
    tmdb_id: int = Field(..., description="The Movie Database id.")


class PredictionOutput(BaseModel):
    prediction: float
    prediction_raw: float
    real_rating: Optional[float] = None
    imdb_id: Optional[str] = None
    model_version: str
