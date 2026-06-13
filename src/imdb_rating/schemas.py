from pydantic import BaseModel, Field
from typing import Optional


class ReviewInput(BaseModel):
    review_text: str = Field(..., description="Free-text content of the review.")
    movie_title: Optional[str] = None
    year: Optional[int] = None
    runtime: Optional[int] = None
    genres: Optional[list[str]] = None


class PredictionOutput(BaseModel):
    prediction: int = Field(..., ge=1, le=10, description="Predicted IMDB rating bucket (1-10).")
    model_version: str
