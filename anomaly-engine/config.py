from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    prometheus_url: str = "http://prometheus:9090"
    sample_interval: float = 1.0
    query_window: str = "8s"
    rate_window: str = "15s"

    anomaly_window: int = 60
    z_score_threshold: float = 3.0
    min_request_count: int = 20
    consecutive_breaches: int = 3
    alert_cooldown: int = 30
    recovery_observations: int = 5
    warmup_samples: int = 12

    slack_webhook_url: str = ""
    dashboard_url: str = "http://localhost:3030"
    listen_host: str = "0.0.0.0"
    listen_port: int = 8080
    log_level: str = "INFO"

    services: str = "api-gateway,user-service,payment-service,notification-service"

    def service_names(self) -> list[str]:
        return [item.strip() for item in self.services.split(",") if item.strip()]


settings = Settings()
