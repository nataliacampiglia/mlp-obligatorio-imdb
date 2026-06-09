from datetime import datetime
from logging import Logger, Formatter, StreamHandler, FileHandler, getLogger
import os

def custom_logger(logger_name: str, level: int = 10) -> Logger:
    os.makedirs("data/logs", exist_ok=True)

    logger = getLogger(f"{logger_name} - ")
    logger.setLevel(level)

    if not logger.hasHandlers():
        console_handler = StreamHandler()
        console_handler.setLevel(level)
        console_formatter = Formatter(
            "%(asctime)s.%(msecs)03d - %(name)s%(levelname)s: %(message)s",
            datefmt="%m/%d/%Y %I:%M:%S",
        )
        console_handler.setFormatter(console_formatter)

        log_file = f"data/logs/{datetime.now().strftime('%Y-%m-%d')}.log"
        file_handler = FileHandler(log_file)
        file_handler.setLevel(level)
        file_formatter = Formatter(
            "%(asctime)s.%(msecs)03d - %(name)s%(levelname)s: %(message)s",
            datefmt="%m/%d/%Y %I:%M:%S",
        )
        file_handler.setFormatter(file_formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
