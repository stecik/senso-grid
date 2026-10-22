from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENSOGRID_", extra="ignore")
    mode: Literal["demo", "ble", "off"] = "demo"
    data_dir: Path = Path("./data")
    influx_url: str = "http://localhost:8181"
    influx_token: str = ""
    influx_database: str = "sensogrid"
    sample_interval_seconds: int = Field(900, ge=10, le=86400)
    stale_after_seconds: int = Field(1800, ge=30, le=604800)
    ble_concurrency: int = Field(10, ge=1, le=10)
    diagnostics: bool = False
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@example.invalid"
    secure_cookies: bool = False
    session_hours: int = Field(168, ge=1, le=8760)
    static_dir: Path = Path("frontend/dist")
