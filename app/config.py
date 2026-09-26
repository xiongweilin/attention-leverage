from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / '.env')


@dataclass(slots=True)
class Settings:
    openai_api_key: str = os.getenv('OPENAI_API_KEY', '')
    openai_base_url: str = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    openai_model: str = os.getenv('OPENAI_MODEL', 'gpt-5-mini')
    github_token: str = os.getenv('GITHUB_TOKEN', '')
    nvd_api_key: str = os.getenv('NVD_API_KEY', '')
    sec_user_agent: str = os.getenv('SEC_USER_AGENT', '')
    reliefweb_appname: str = os.getenv('RELIEFWEB_APPNAME', '')
    database_path: str = os.getenv('DATABASE_PATH', str(ROOT / 'data' / 'attention.db'))
    max_raw_items: int = int(os.getenv('MAX_RAW_ITEMS', '320'))
    max_filtered_items: int = int(os.getenv('MAX_FILTERED_ITEMS', '72'))
    max_output_items: int = int(os.getenv('MAX_OUTPUT_ITEMS', '24'))
    request_timeout_seconds: float = float(os.getenv('REQUEST_TIMEOUT_SECONDS', '20'))
    llm_timeout_seconds: float = float(os.getenv('LLM_TIMEOUT_SECONDS', '90'))
    source_concurrency: int = int(os.getenv('SOURCE_CONCURRENCY', '12'))
    source_config: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> 'Settings':
        cfg_path = ROOT / 'config' / 'sources.toml'
        source_config: dict = {}
        if cfg_path.exists():
            with cfg_path.open('rb') as f:
                source_config = tomllib.load(f)
        obj = cls()
        obj.source_config = source_config
        Path(obj.database_path).parent.mkdir(parents=True, exist_ok=True)
        return obj
