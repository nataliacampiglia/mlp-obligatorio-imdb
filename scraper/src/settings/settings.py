from typing import Any
from pathlib import Path

from yaml import load
from yaml.loader import SafeLoader

CONFIG_PATH = Path(__file__).resolve().with_name("config.yml")


def load_settings(key: str | None = None) -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = load(f, Loader=SafeLoader)

    if key:
        return config[key]

    return config
