"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    postgres_host: str = "timescaledb"
    postgres_port: int = 5432
    postgres_db: str = "techsentinel"
    postgres_user: str = "tsadmin"
    postgres_password: str = "changeme_db_password"

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379

    # API
    ts_api_host: str = "0.0.0.0"
    ts_api_port: int = 8000
    ts_api_key: str = "changeme_api_key"
    ts_jwt_secret: str = "changeme_jwt_secret"
    ts_jwt_algorithm: str = "HS256"
    ts_jwt_expire_minutes: int = 60

    # Alerting
    ts_alert_consecutive_failures: int = 3
    ts_slack_webhook_url: str = ""
    ts_pagerduty_routing_key: str = ""
    ts_automation_url: str = ""
    ts_automation_api_key: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def asyncpg_dsn(self) -> str:
        return self.database_url

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
