"""Settings, read once from environment variables.

Docker Compose passes everything in (see docker-compose.yml and .env.example),
so the same image runs locally and on the server without code changes.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    geojson_path: str
    schema_path: str
    ee_project: str | None
    ee_service_account_json: str | None
    ee_credentials_json: str | None
    gemini_api_key: str | None
    gemini_model: str
    groq_api_key: str | None
    groq_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            # psycopg wants plain postgresql://, so we drop an SQLAlchemy-style driver suffix if present
            database_url=os.environ.get(
                "DATABASE_URL", "postgresql://gras:gras_dev@localhost:5432/gras"
            ).replace("postgresql+psycopg://", "postgresql://"),
            geojson_path=os.environ.get("GEOJSON_PATH", "/data/gold_deforestation_labels.geojson"),
            schema_path=os.environ.get("SCHEMA_PATH", "/db/init.sql"),
            ee_project=os.environ.get("EE_PROJECT") or None,
            ee_service_account_json=os.environ.get("EE_SERVICE_ACCOUNT_JSON") or None,
            ee_credentials_json=os.environ.get("EE_CREDENTIALS_JSON") or None,
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            gemini_model=os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash",
            groq_api_key=os.environ.get("GROQ_API_KEY") or None,
            groq_model=os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b",
        )


settings = Settings.from_env()


def load_ee_credentials() -> tuple[str | None, dict | None]:
    """Return (service_account_email, key) or (None, None) when no key is configured.

    The inline JSON wins over the mounted key file, which makes it easy to
    override on a host where mounting secrets is awkward.
    """
    raw = settings.ee_credentials_json
    if raw:
        try:
            creds = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"EE_CREDENTIALS_JSON is not valid JSON: {e}") from e
        return creds.get("client_email"), creds

    if settings.ee_service_account_json:
        p = Path(settings.ee_service_account_json)
        if p.exists():
            creds = json.loads(p.read_text())
            return creds.get("client_email"), creds

    return None, None
