from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reads settings from environment variables (or backend/.env locally)."""

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    # Required: no default, so a missing variable fails loudly instead of
    # silently pointing somewhere else
    database_url: str
    stripe_secret_key: str = ''
    stripe_webhook_secret: str = ''
    resend_api_key: str = ''
    email_from: str = 'Sons of Caesar <tickets@sonsofcaesar.xyz>'
    site_url: str = 'http://localhost:5173'
    # Where this API is reachable (used for QR image links in emails)
    api_url: str = 'http://localhost:8000'
    # Websites allowed to call the API from the browser, comma-separated
    cors_origins: str = 'http://localhost:5173'

    @property
    def test_payments_allowed(self) -> bool:
        # Sandbox (fake-money) payments only on a developer's machine. On the real
        # site they'd create real, scannable tickets for free, so they're refused.
        return 'localhost' in self.site_url or '127.0.0.1' in self.site_url

    @property
    def stripe_is_live(self) -> bool:
        return self.stripe_secret_key.startswith(('sk_live_', 'rk_live_'))

    @property
    def sqlalchemy_url(self) -> str:
        # Railway gives "postgresql://..."; SQLAlchemy needs to be told to use psycopg 3
        url = self.database_url
        for prefix in ('postgres://', 'postgresql://'):
            if url.startswith(prefix):
                return 'postgresql+psycopg://' + url[len(prefix):]
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]


settings = Settings()
