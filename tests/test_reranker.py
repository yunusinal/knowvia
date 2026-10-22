"""Yeniden sıralama: GPU_ENABLED ile açılır, eşiği geçemeyen parça sıralayıcıya da gitmez, yanlış kurulum sessiz kalmaz."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.chat import reranker_dependency
from app.core.config import get_settings
from app.db.models import Department, User, Visibility
from app.main import app
from app.repositories.vector_store import VectorStore
from app.services import reranker as reranker_module
from app.services.ingest import ingest_document
from app.services.reranker import RerankerUnavailableError, get_reranker
from tests.fakes import FakeEmbedder, FakeLLM
from tests.helpers import auth_header

QUESTION = "VPN sertifika kontrol adımı saat önbellek"


@dataclass
class FakeReranker:
    """İçinde `favorite` geçen parçaya en yüksek puanı verir; kendisine gelen metinleri kaydeder."""

    favorite: str
    seen: list[list[str]] = field(default_factory=list)

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        self.seen.append(list(texts))
        return [1.0 if self.favorite in text else 0.0 for text in texts]


@pytest.fixture
def many_chunks(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User],
) -> None:
    # Her paragraf ayrı chunk; "ÖZEL" geçen parça soruya en az benzeyen, yani aramada en altta kalan parça.
    # Paragraflar 50 token'ı aşar ki parçalayıcı onları birleştirmesin; her biri ayrı chunk olur.
    filler = " ".join(f"ek{j}" for j in range(50))
    paragraphs = [f"VPN sertifika kontrol adımı {i}: saat ve önbellek ayarını kontrol edin. {filler}" for i in range(8)]
    paragraphs.append(f"ÖZEL not: sertifika MDM konsolundan yeniden dağıtılır. {filler}")
    ingest_document(
        session, vector_store, fake_embedder, filename="vpn.md",
        content="\n\n".join(paragraphs).encode(), department=Department.IT,
        visibility=Visibility.COMPANY, uploaded_by=users["admin"].id, max_mb=10,
    )


@pytest.fixture
def with_reranker() -> Iterator[FakeReranker]:
    fake = FakeReranker(favorite="ÖZEL")
    app.dependency_overrides[reranker_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(reranker_dependency, None)


@pytest.fixture
def low_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "retrieval_min_score", 0.1)


def ask(client: TestClient, user: User):  # pyright: ignore[reportMissingReturnType]
    return client.post("/chat", json={"question": QUESTION}, headers=auth_header(user))


def test_without_reranker_the_low_ranked_chunk_stays_out_of_the_top_five(
    client: TestClient, users: dict[str, User], many_chunks: None, low_threshold: None, fake_llm: FakeLLM,
) -> None:
    ask(client, users["it"])

    assert "ÖZEL" not in fake_llm.calls[-1][1]  # deneyin anlamlı olduğunu gösterir


def test_reranker_can_promote_a_chunk_from_the_wider_candidate_pool(
    client: TestClient, users: dict[str, User], many_chunks: None, low_threshold: None,
    with_reranker: FakeReranker, fake_llm: FakeLLM,
) -> None:
    fake_llm.answers = ["Sertifikayı yeniden dağıtın. [S1]"]

    response = ask(client, users["it"])

    assert response.status_code == 200
    assert len(with_reranker.seen[-1]) > get_settings().retrieval_top_k  # top_k'dan geniş aday havuzu
    assert response.json()["sources"][0]["snippet"].startswith("ÖZEL")
    assert '<source id="S1"' in fake_llm.calls[-1][1] and "ÖZEL" in fake_llm.calls[-1][1].split("</source>")[0]


def test_chunks_below_the_threshold_never_reach_the_reranker(
    client: TestClient, users: dict[str, User], many_chunks: None, with_reranker: FakeReranker,
    fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "retrieval_min_score", 0.99)

    response = ask(client, users["it"])

    assert response.json()["no_evidence"] is True
    assert with_reranker.seen == [] and fake_llm.calls == []


def test_gpu_disabled_means_no_reranker_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "gpu_enabled", False)
    monkeypatch.setattr(reranker_module, "cuda_available", lambda: pytest.fail("GPU kapalıyken CUDA denetlenmemeli"))

    assert get_reranker() is None


def test_gpu_enabled_without_cuda_fails_loudly(
    client: TestClient, users: dict[str, User], many_chunks: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "gpu_enabled", True)
    monkeypatch.setattr(reranker_module, "cuda_available", lambda: False)

    with pytest.raises(RerankerUnavailableError):
        get_reranker()
    response = ask(client, users["it"])
    assert response.status_code == 503
    assert "GPU_ENABLED" in response.json()["detail"]
    # Hazır sosyal cevaplar sıralayıcıya ihtiyaç duymaz, çalışmaya devam eder.
    assert client.post("/chat", json={"question": "merhaba"}, headers=auth_header(users["it"])).status_code == 200
