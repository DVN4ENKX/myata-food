from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "Myata Food"
    api_prefix: str = "/api"

    # --- database -----------------------------------------------------
    database_url: str = "sqlite:///./storage/myata.db"
    db_echo: bool = False

    # --- security -----------------------------------------------------
    secret_key: str = "dev-secret-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    # --- urls ---------------------------------------------------------
    # Base URL guests will reach the menu from (used to build QR codes)
    public_base_url: str = "http://localhost:5173"
    api_public_url: str = "http://localhost:8000"

    cors_origins: list[str] | str = ["http://localhost:5173"]

    # --- storage ------------------------------------------------------
    storage_dir: str = "./storage"
    max_upload_mb: int = 8

    # --- seed ---------------------------------------------------------
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin123"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    @property
    def images_path(self) -> Path:
        return self.storage_path / "images"

    @property
    def exports_path(self) -> Path:
        return self.storage_path / "exports"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
