FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app

COPY pyproject.toml poetry.lock* ./

RUN poetry install --only main,monitoring --no-interaction --no-ansi --no-root

COPY monitoring/ ./monitoring/

EXPOSE 8501

CMD ["streamlit", "run", "monitoring/analyze.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
