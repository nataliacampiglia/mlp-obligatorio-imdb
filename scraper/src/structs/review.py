from pydantic import BaseModel


class Review(BaseModel):
    movie_imdb_id: str
    reviewer_name: str | None = None
    rating: int | None = None
    date: str | None = None
    review_title: str | None = None
    review_text: str
    helpful_votes: int | None = None
