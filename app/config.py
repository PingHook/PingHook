from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    BASE_URL: str = "https://api.pinghook.dev"

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)


settings = Settings()
