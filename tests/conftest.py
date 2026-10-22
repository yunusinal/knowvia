import os

# Uygulama ayarları ilk import'ta okunur; testlerin kendi JWT anahtarı olmalı.
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-for-real-use-0123456789"

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from sqlalchemy import Engine, create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.models import Base, Department, Role, User  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.vector_store import VectorStore, get_vector_store  # noqa: E402
from app.services.embeddings import SUPPORTED_MODELS, FastEmbedEmbedder, get_embedder  # noqa: E402
from app.api.chat import embedder_dependency, llm_dependency, store_dependency  # noqa: E402
from app.api.limits import get_limiters  # noqa: E402
from tests.fakes import FakeEmbedder, FakeLLM, FakeSparseEncoder  # noqa: E402


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
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def vector_store(fake_embedder: FakeEmbedder) -> Iterator[VectorStore]:
    """Gerçek Qdrant istemcisi, bellekte (master plan §11.1: Qdrant taklit edilmez)."""
    store = VectorStore(QdrantClient(":memory:"), "test_chunks", fake_embedder.dimension, FakeSparseEncoder())
    store.ensure_collection()
    yield store
    store.close()


@pytest.fixture(autouse=True)
def fresh_rate_limits() -> Iterator[None]:
    """Her test kendi sayaçlarıyla başlar; sınır testleri diğer testleri etkilemez."""
    get_limiters.cache_clear()
    yield
    get_limiters.cache_clear()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def client(
    engine: Engine, vector_store: VectorStore, fake_embedder: FakeEmbedder, fake_llm: FakeLLM
) -> Iterator[TestClient]:
    """API istemcisi: bellek içi veritabanı, bellek içi Qdrant, sahte embedder ve sahte LLM kullanır.

    Hiçbir API testi gerçek modeli yüklemez, data/runtime klasörüne yazmaz veya LLM sağlayıcısına gitmez.
    """

    def override_get_db() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: vector_store
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    app.dependency_overrides[llm_dependency] = lambda: fake_llm
    app.dependency_overrides[store_dependency] = lambda: vector_store
    app.dependency_overrides[embedder_dependency] = lambda: fake_embedder
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def users(session: Session) -> dict[str, User]:
    """Yetki matrisindeki dört demo rolü: admin, it, hr, finance."""
    accounts = {
        "admin": User(email="admin@test.local", role=Role.ADMIN, department=None),
        "it": User(email="it@test.local", role=Role.MEMBER, department=Department.IT),
        "hr": User(email="hr@test.local", role=Role.MEMBER, department=Department.HR),
        "finance": User(email="finance@test.local", role=Role.MEMBER, department=Department.FINANCE),
    }
    for account in accounts.values():
        account.password_hash = hash_password("unused-in-these-tests")
        session.add(account)
    session.commit()
    return accounts
