from functools import lru_cache

from pydantic import Field, SecretStr
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
    # Qdrant local mode: vektörler bu klasörde, ayrı sunucu gerekmez (yalnızca yerel demo).
    qdrant_path: str = "data/runtime/qdrant"
    qdrant_collection: str = "knowledge_chunks_v1"
    retrieval_top_k: int = Field(default=5, gt=0)
    # En iyi sonucun skoru bunun altındaysa LLM çağrılmaz ("kanıt yok"). Modele ve parçalama
    # yöntemine özeldir; e5-large + paragraf parçalama ile ölçüldü (docs/adr/07-...).
    retrieval_min_score: float = Field(default=0.80, ge=0, le=1)
    # OpenAI uyumlu herhangi bir sağlayıcı; anahtar yoksa /chat temiz bir kurulum hatası döner.
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    # SecretStr: değer loglarda ve hata mesajlarında "**********" olarak görünür.
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0)
    llm_max_output_tokens: int = Field(default=1024, gt=0)
    llm_temperature: float = Field(default=0.0, ge=0, le=2)


@lru_cache
def get_settings() -> Settings:
    # Zorunlu alanlar ortamdan/.env'den okunur; pyright bunu statik olarak göremez.
    return Settings()  # pyright: ignore[reportCallIssue]
