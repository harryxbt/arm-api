from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./armageddon.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    deepgram_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    elevenlabs_api_key: str = ""
    musetalk_dir: str = ""  # Path to MuseTalk repo clone
    musetalk_model_dir: str = ""  # Path to MuseTalk model weights directory
    storage_dir: str = "./storage"
    storage_backend: str = "local"  # "local" or "bunny"
    bunny_api_key: str = ""
    bunny_storage_zone: str = ""
    bunny_cdn_hostname: str = ""
    bunny_storage_hostname: str = "storage.bunnycdn.com"
    frontend_url: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
