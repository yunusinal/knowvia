import os

# Uygulama ayarları ilk import'ta okunur; testlerin kendi JWT anahtarı olmalı.
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-for-real-use-0123456789"

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.embeddings import SUPPORTED_MODELS, FastEmbedEmbedder  # noqa: E402


@pytest.fixture(scope="session")
def real_embedder() -> FastEmbedEmbedder:
    """Gerçek embedding modeli; testler internete bağlı olmasın diye önbellekte yoksa test atlanır.

    Oturum boyunca bir kez yüklenir (~2,3 GB, birkaç saniye).
    """
    settings = get_settings()
    spec = SUPPORTED_MODELS[settings.embedding_model]
    cache_dir = Path(settings.model_cache_dir)
    if not (cache_dir / ("models--" + spec.hf_repo.replace("/", "--"))).exists():
        pytest.skip("Embedding modeli önbellekte yok; gerçek model testleri atlandı.")
    return FastEmbedEmbedder(spec, cache_dir)


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Bellekte veritabanı. StaticPool: testteki oturum ile API aynı bağlantıyı (aynı veriyi) görür."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Her test için bellekte, boş bir veritabanı; gerçek dosyaya dokunmaz."""
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """API istemcisi; gerçek DB yerine testin bellek-içi veritabanını kullanır."""

    def override_get_db() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
