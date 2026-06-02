from pydantic import BaseModel


class Movie(BaseModel):
    imdb_id: str
    title: str
    year: int | None = None
    imdb_rating: float | None = None
    votes: int | None = None
    genres: list[str] = []
    directors: list[str] = []
    main_cast: list[str] = []
    runtime_min: int | None = None
    certificate: str | None = None
    metascore: int | None = None
    plot: str | None = None
