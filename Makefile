SCRAPER_DIR := scraper

scraper-install:
	cd $(SCRAPER_DIR) && poetry install && poetry run playwright install chromium

scraper-run:
	cd $(SCRAPER_DIR) && poetry run python src/main.py
