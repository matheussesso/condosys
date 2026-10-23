"""General settings loaded from environment variables and ``.env``."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BrowserChannel = Literal["chromium", "chrome", "msedge"]


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
    logs_dir: Path = Path("logs")
    debug_dir: Path = Path("debug")

    log_level: str = "INFO"

    headless: bool = False
    # "chromium" uses the browser downloaded by `playwright install chromium`;
    # "msedge"/"chrome" use the browser installed on the machine.
    browser_channel: BrowserChannel = "chromium"
    timeout_ms: int = Field(default=30_000, ge=1_000)
    navigation_timeout_ms: int = Field(default=60_000, ge=1_000)
    # Short pause between browser actions, to be gentle with the portal.
    slow_mo_ms: int = Field(default=300, ge=0)
    # Extra wait while a person solves the "Confirme que é humano" check in the iHub popup.
    human_check_timeout_ms: int = Field(default=180_000, ge=1_000)
    # Pause between two condominiums in batch runs.
    between_condominiums_ms: int = Field(default=3_000, ge=0)

    issnet_login_url: str = (
        "https://iss.fazenda.df.gov.br/online/Login/Login.aspx?ReturnUrl=%2fonline"
    )
    # Origins that receive the client certificate (scheme://host[:port], no path). The
    # ISSNet login delegates the certificate check to the iHub popup (docs/decisoes.md).
    issnet_cert_origins: list[str] = ["https://api.ihub.com.br"]
    # Re-encode the .pfx in memory with modern algorithms before handing it to the browser
    # (A1 certificates often use legacy RC2/3DES encryption that OpenSSL 3 rejects).
    reencode_pfx: bool = True

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        self.base_dir = self.base_dir.expanduser().resolve()
        for name in ("certs_dir", "config_file", "output_dir", "logs_dir", "debug_dir"):
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
