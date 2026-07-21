"""Configuration and project paths.

The project intentionally avoids a dotenv dependency. A small parser loads plain
KEY=VALUE lines from `.env`, while real environment variables always win.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.json"


def load_dotenv(path: Path | None = None) -> None:
    """Load simple environment variables without overwriting the current process."""

    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_project_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _boolean_from_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalised = raw.strip().lower()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    candidates_path: Path
    model_path: Path
    live_listings_path: Path
    product_status_path: Path
    onemap_email: str
    onemap_password: str
    onemap_token: str
    lta_account_key: str
    data_gov_sg_api_key: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    enable_llm: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv()
        return cls(
            project_root=PROJECT_ROOT,
            candidates_path=_path_from_env(
                "HOMELENS_CANDIDATES_PATH", "data/processed/hdb_candidates.csv"
            ),
            model_path=_path_from_env(
                "HOMELENS_MODEL_PATH", "artifacts/models/price_model.joblib"
            ),
            live_listings_path=_path_from_env(
                "HOMELENS_LIVE_LISTINGS_PATH", "data/processed/live_listings_enriched.csv"
            ),
            product_status_path=_path_from_env(
                "HOMELENS_PRODUCT_STATUS_PATH", "map/public/data-status.json"
            ),
            onemap_email=os.getenv("ONEMAP_EMAIL", "").strip(),
            onemap_password=os.getenv("ONEMAP_PASSWORD", "").strip(),
            onemap_token=os.getenv("ONEMAP_TOKEN", "").strip(),
            lta_account_key=os.getenv("LTA_ACCOUNT_KEY", "").strip(),
            data_gov_sg_api_key=os.getenv("DATA_GOV_SG_API_KEY", "").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_base_url=os.getenv(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ).strip().rstrip("/"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip(),
            enable_llm=_boolean_from_env("HOMELENS_ENABLE_LLM", False),
        )

    def integration_status(self) -> dict[str, bool]:
        return {
            "onemap": bool(self.onemap_token or (self.onemap_email and self.onemap_password)),
            "lta_datamall": bool(self.lta_account_key),
            "openai": bool(
                self.enable_llm
                and self.openai_api_key
                and self.openai_base_url
                and self.openai_model
            ),
        }


def ensure_output_directories() -> None:
    for relative in (
        "data/raw",
        "data/processed",
        "artifacts/models",
        "artifacts/metrics",
        "artifacts/manifests",
    ):
        (PROJECT_ROOT / relative).mkdir(parents=True, exist_ok=True)
