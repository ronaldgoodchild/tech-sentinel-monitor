"""Application configuration loaded from environment variables."""

import sys
from pydantic_settings import BaseSettings

# Known insecure JWT secrets that must be rejected
INSECURE_JWT_SECRETS = {
    "changeme",
    "changeme_jwt_secret",
    "secret",
    "jwt_secret",
    "default",
    "test",
    "dev",
    "development",
    "password",
    "admin",
}


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

    def validate_jwt_secret(self) -> None:
        """Validate that JWT secret is not a known insecure default.

        This prevents tenant impersonation attacks by ensuring the application
        fails closed when deployed with a predictable signing key.
        """
        if self.ts_jwt_secret in INSECURE_JWT_SECRETS:
            print(
                f"FATAL: TS_JWT_SECRET is set to a known insecure default value. "
                f"This allows attackers to forge authentication tokens and impersonate tenants. "
                f"Set TS_JWT_SECRET to a cryptographically random value (minimum 32 bytes). "
                f"Example: openssl rand -base64 32",
                file=sys.stderr,
            )
            sys.exit(1)

        if len(self.ts_jwt_secret) < 32:
            print(
                f"FATAL: TS_JWT_SECRET is too short ({len(self.ts_jwt_secret)} bytes). "
                f"For HS256, the secret must be at least 32 bytes to prevent brute-force attacks. "
                f"Set TS_JWT_SECRET to a cryptographically random value. "
                f"Example: openssl rand -base64 32",
                file=sys.stderr,
            )
            sys.exit(1)


settings = Settings()
settings.validate_jwt_secret()
