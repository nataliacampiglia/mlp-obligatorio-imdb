FROM python:3.11-slim

WORKDIR /app

COPY src/ /app/src/
RUN pip install --no-cache-dir -e /app/src

COPY deployment/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY deployment/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
