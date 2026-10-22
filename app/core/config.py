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
    # SecretStr: değer repr, log ve hata çıktılarında "**********" görünür (test hataları dahil).
    demo_user_password: SecretStr | None = None
    # Zorunlu ve varsayılanı yok: ayarlanmamışsa uygulama başlamaz (fail closed).
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_expire_minutes: int = 60
    max_upload_mb: int = Field(default=10, gt=0)
    embedding_model: str = "intfloat/multilingual-e5-large"
    # Model dosyaları (~2,3 GB) ilk kullanımda buraya indirilir; klasör git dışında.
    model_cache_dir: str = "data/runtime/models"
    # Qdrant local mode: vektörler bu klasörde, ayrı sunucu gerekmez (yalnızca yerel demo).
    qdrant_path: str = "data/runtime/qdrant"
    # v2: isimli dense + bm25 vektörleri (hibrit arama, ADR-11). v1'den taşıma: scripts.reindex_hybrid
    qdrant_collection: str = "knowledge_chunks_v2"
    retrieval_top_k: int = Field(default=5, gt=0)
    # true: arama adayları GPU'da çapraz kodlayıcıyla yeniden sıralanır (onnxruntime-gpu ortamı gerekir,
    # README "GPU ile çalıştırma"). false: yeniden sıralama kapalı; CPU'da soru başına ~14 sn sürerdi (ADR-10).
    gpu_enabled: bool = False
    rerank_candidates: int = Field(default=20, gt=0)
    # Herkese açık demo için dakikalık sınırlar (ADR-12). Genel sınır, LLM sağlayıcısının dakikalık
    # kotasının (Groq ücretsiz: 8000 token) tek kişi tarafından tüketilmesini önler.
    chat_limit_per_user_per_minute: int = Field(default=8, gt=0)
    chat_limit_global_per_minute: int = Field(default=20, gt=0)
    login_limit_per_email_per_minute: int = Field(default=10, gt=0)
    # Ayarlanırsa admin bu parolayı kullanır; üye parolası (DEMO_USER_PASSWORD) herkese açıklansa da admin gizli kalır.
    admin_password: SecretStr | None = None
    # true: API açılırken embedding/BM25 modelleri ve Qdrant yüklenir (Docker'da açık; testlerde kapalı).
    warmup_on_start: bool = False
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
    # Varsayılan Groq gpt-oss-120b içindir; model değişirse sağlayıcının sınırına göre güncellenir.
    llm_context_window_tokens: int = Field(default=131072, gt=0)
    # Uygulama limiti, sağlayıcının tam penceresinden küçüktür; geçmiş kaynaklara göre yer açar.
    chat_input_budget_tokens: int = Field(default=8000, gt=0)
    chat_history_budget_tokens: int = Field(default=2500, gt=0)


@lru_cache
def get_settings() -> Settings:
    # Zorunlu alanlar ortamdan/.env'den okunur; pyright bunu statik olarak göremez.
    return Settings()  # pyright: ignore[reportCallIssue]
