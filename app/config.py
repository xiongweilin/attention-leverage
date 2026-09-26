from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    max_raw_items: int = int(os.getenv("MAX_RAW_ITEMS", "180"))
    max_filtered_items: int = int(os.getenv("MAX_FILTERED_ITEMS", "60"))
    max_output_items: int = int(os.getenv("MAX_OUTPUT_ITEMS", "20"))
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    source_config: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        cfg_path = ROOT / "config" / "sources.toml"
        source_config = {}
        if cfg_path.exists():
            with cfg_path.open("rb") as f:
                source_config = tomllib.load(f)
        obj = cls()
        obj.source_config = source_config
        return obj
