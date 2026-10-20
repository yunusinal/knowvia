from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Uygulama ayarları; değerler ortam değişkenlerinden veya .env dosyasından okunur."""

    # hide_input_in_errors: ayar hatası mesajları .env'deki sırları (parola, anahtar) ekrana basmaz.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: str = "development"
    database_url: str = "sqlite:///./data/runtime/app.db"
    # Varsayılanı yok: parola koda yazılmaz, .env'den gelir.
    demo_user_password: str | None = None
    # Zorunlu ve varsayılanı yok: ayarlanmamışsa uygulama başlamaz (fail closed).
    jwt_secret_key: str = Field(min_length=32)
    jwt_expire_minutes: int = 60
    max_upload_mb: int = Field(default=10, gt=0)
    embedding_model: str = "intfloat/multilingual-e5-large"
    # Model dosyaları (~2,3 GB) ilk kullanımda buraya indirilir; klasör git dışında.
    model_cache_dir: str = "data/runtime/models"


@lru_cache
def get_settings() -> Settings:
    # Zorunlu alanlar ortamdan/.env'den okunur; pyright bunu statik olarak göremez.
    return Settings()  # pyright: ignore[reportCallIssue]
