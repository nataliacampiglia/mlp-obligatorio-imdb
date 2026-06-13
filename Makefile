SCRAPER_DIR := scraper

# ─── setup ────────────────────────────────────────────────────────────────────

scraper-install:
	cd $(SCRAPER_DIR) && poetry install && poetry run playwright install chromium

# ─── aws ──────────────────────────────────────────────────────────────────────

# Actualiza las credenciales de AWS copiando el bloque del Learner Lab.
# Uso:
#   1. Copiá el bloque completo de AWS Details → AWS CLI (incluye [default] y las 3 líneas)
#   2. Corré: make aws-credentials
aws-credentials:
	@mkdir -p ~/.aws
	@pbpaste > ~/.aws/credentials
	@echo "Credenciales guardadas en ~/.aws/credentials"
	@echo "--- contenido ---"
	@cat ~/.aws/credentials

# ─── scraper ──────────────────────────────────────────────────────────────────

# Abre el navegador para hacer login manual en IMDB y guarda la sesión
scraper-login:
	cd $(SCRAPER_DIR) && poetry run python -m src.main --login-only

# Corre el scraper y sube los datos a S3 como Parquet
scraper-run:
	cd $(SCRAPER_DIR) && poetry run python -m src.main

# ─── etl ──────────────────────────────────────────────────────────────────────

# Lee los datos crudos de S3, los procesa y sube el dataset de entrenamiento
etl-run:
	cd $(SCRAPER_DIR) && poetry run python -m src.processing.etl

# ─── pipeline completo ────────────────────────────────────────────────────────

# Corre todo en orden: credenciales → login IMDB → scraper → etl
# Uso:
#   1. Copiá el bloque de credenciales del Learner Lab
#   2. Corré: make pipeline
#   3. Completá el login en el navegador y presioná Enter cuando estés logueado
pipeline: aws-credentials scraper-login scraper-run etl-run
