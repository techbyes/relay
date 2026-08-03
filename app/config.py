from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://relay:relay@localhost:5432/relay"
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: str = ""
    anthropic_api_key: str = ""

    default_requests_per_minute: int = 20
    default_monthly_budget_usd: float = 10.0

    # Comma-separated provider names in fallback order, e.g. "anthropic,openai"
    provider_order: str = "anthropic,openai"

    @property
    def provider_order_list(self) -> list[str]:
        return [p.strip() for p in self.provider_order.split(",") if p.strip()]


settings = Settings()
