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


class PredictBatchRequest(BaseModel):
    tmdb_ids: list[int] = Field(..., max_length=100, description="Up to 100 The Movie Database ids.")


class PredictBatchItem(BaseModel):
    tmdb_id: int
    prediction: Optional[PredictionOutput] = None
    error: Optional[str] = None


class PredictBatchResponse(BaseModel):
    items: list[PredictBatchItem]
