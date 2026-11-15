"""Application settings, read from environment variables (prefix SS_) or a .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SS_", env_file=".env", extra="ignore")

    # NASA PSI: fixed hosts; user input never changes them.
    psi_base: str = "https://psi.nasa.gov"
    upstream_timeout_seconds: float = 60.0

    # The committed PSI snapshot (records, test tables, manifest) and the
    # reviewed mapping and flag files live under data/.
    data_dir: Path = ROOT / "data"
    # Rebuilt from the snapshot: the SQLite database and Nimbus run logs.
    cache_dir: Path = ROOT / ".cache"

    # Host headers the app answers to; add your domain when you deploy.
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    # Browser origins allowed to call the API (same-origin needs no entry).
    allowed_origins: list[str] = []

    # Rate limits (slowapi syntax), per client IP.
    api_rate_limit: str = "120/minute"
    ask_rate_limit: str = "10/minute"

    # Ollama: keep it bound to localhost; only this backend talks to it.
    # The app uses one SI model: IBM Granite 3.3 2B (Apache-2.0, OSI).
    ollama_url: str = "http://127.0.0.1:11434"
    si_model: str = "granite3.3:2b"
    si_timeout_seconds: float = 300.0
    si_queue_wait_seconds: float = 90.0   # how long a question may wait for the one model before it is answered from evidence alone
    si_max_waiting: int = 4               # how many questions may wait for the model at once
    # Who a run log belongs to, so measurements are never mixed with development: "user" (a person asking in the app, the default),
    # "evaluation" (python -m app.insights.evaluate) or "development" (scripts and manual testing; set SS_RUN_ORIGIN=development).
    run_origin: str = Field(default="user", pattern=r"^(user|evaluation|development)$")
    si_keep_alive: str = "30m"     # how long Ollama keeps the model in memory after a call (a cold load can take minutes)

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshot"

    @property
    def db_path(self) -> Path:
        return self.cache_dir / "spacesweepers.db"

    @property
    def runs_dir(self) -> Path:
        return self.cache_dir / "nimbus-runs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
