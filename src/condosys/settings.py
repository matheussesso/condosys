"""General settings loaded from environment variables and ``.env``."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Every field can be overridden with a ``CONDOSYS_*`` variable.

    Relative paths are resolved against ``base_dir``.
    """

    model_config = SettingsConfigDict(
        env_prefix="CONDOSYS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_dir: Path = Field(default_factory=Path.cwd)
    certs_dir: Path = Path("certs")
    config_file: Path = Path("config/condominios.xlsx")
    output_dir: Path = Path("output")
    # Local data downloaded from official APIs (fiscal data, git-ignored).
    data_dir: Path = Path("data")
    logs_dir: Path = Path("logs")
    debug_dir: Path = Path("debug")

    log_level: str = "INFO"

    # National NFS-e data environment (ADN), contributor distribution API.
    adn_base_url: str = "https://adn.nfse.gov.br"
    # One request at a time, with a pause; the next run continues after max_batches.
    adn_pause_ms: int = Field(default=1_000, ge=0)
    adn_max_batches: int = Field(default=100, ge=1)
    # Pause between two condominiums in batch runs.
    between_condominiums_ms: int = Field(default=1_000, ge=0)

    # Local API used by the desktop app (Electron). Loopback only.
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8765, ge=0, le=65535)

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        self.base_dir = self.base_dir.expanduser().resolve()
        for name in (
            "certs_dir",
            "config_file",
            "output_dir",
            "data_dir",
            "logs_dir",
            "debug_dir",
        ):
            path: Path = getattr(self, name).expanduser()
            if not path.is_absolute():
                setattr(self, name, self.base_dir / path)
        return self

    @property
    def example_config_file(self) -> Path:
        """Path of the example condominium workbook."""
        return self.config_file.with_name("condominios.example.xlsx")


def find_project_dir(start: Path | None = None) -> Path:
    """Finds the project folder from ``start`` (default: cwd) or any parent.

    The project folder is the first one with a ``.env``/``.env.example`` file or with both
    ``certs/`` and ``config/``, so commands work from subfolders such as ``certs/``.
    Falls back to ``start`` itself.
    """
    origin = (start or Path.cwd()).resolve()
    for candidate in (origin, *origin.parents):
        if (candidate / ".env").is_file() or (candidate / ".env.example").is_file():
            return candidate
        if (candidate / "certs").is_dir() and (candidate / "config").is_dir():
            return candidate
    return origin


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the process-wide settings instance.

    ``CONDOSYS_BASE_DIR`` wins; otherwise the project folder is searched upwards from the
    current directory, and its ``.env`` is the one loaded.
    """
    explicit = os.environ.get("CONDOSYS_BASE_DIR")
    base_dir = Path(explicit) if explicit else find_project_dir()
    return Settings(base_dir=base_dir, _env_file=base_dir / ".env")  # type: ignore[call-arg]
