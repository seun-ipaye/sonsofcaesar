from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reads settings from environment variables (or backend/.env locally)."""

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    database_url: str = 'postgresql+psycopg://localhost/sonsofcaesar_dev'
    stripe_secret_key: str = ''
    stripe_webhook_secret: str = ''
    resend_api_key: str = ''
    email_from: str = 'Sons of Caesar <tickets@sonsofcaesar.xyz>'
    site_url: str = 'http://localhost:5173'
    # Websites allowed to call the API from the browser, comma-separated
    cors_origins: str = 'http://localhost:5173'

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]


settings = Settings()
