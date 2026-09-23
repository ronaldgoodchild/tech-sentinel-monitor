"""Probe worker configuration."""

from pydantic_settings import BaseSettings


class WorkerSettings(BaseSettings):
    postgres_host: str = "timescaledb"
    postgres_port: int = 5432
    postgres_db: str = "techsentinel"
    postgres_user: str = "tsadmin"
    postgres_password: str = "changeme_db_password"

    redis_host: str = "redis"
    redis_port: int = 6379

    ts_probe_concurrency: int = 10
    ts_probe_interval_seconds: int = 60
    ts_probe_timeout_seconds: int = 10

    @property
    def asyncpg_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}"

    model_config = {"env_file": ".env", "extra": "ignore"}


worker_settings = WorkerSettings()
