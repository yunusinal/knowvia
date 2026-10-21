"""Belge silme ve erişimin kesilmesi (master plan §6.2, §11.1 test_document_delete_revocation)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Department, Document, DocumentStatus, User, Visibility
from app.repositories.vector_store import VectorStore
from app.services.ingest import ingest_document
from app.services.prompt import INSUFFICIENT_CONTEXT
from app.services.retrieval import retrieve
from tests.fakes import FakeEmbedder, FakeLLM
from tests.helpers import auth_header

VPN = "VPN sorun giderme: sertifika doğrulanamadı hatasında cihaz saatini kontrol edin."
HANDBOOK = "Çalışan el kitabı: mesai saatleri hafta içi dokuz ile on sekiz arasındadır."


@pytest.fixture(autouse=True)
def low_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sahte embedder kelime örtüşmesiyle skor üretir; eşik bu testlerde konu değil.
    monkeypatch.setattr(get_settings(), "retrieval_min_score", 0.1)


@pytest.fixture
def documents(session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User]) -> dict[str, Document]:
    def ingest(name: str, text: str, department: Department) -> Document:
        return ingest_document(
            session, vector_store, fake_embedder,
            filename=f"{name}.md", content=text.encode(), department=department,
            visibility=Visibility.COMPANY, uploaded_by=users["admin"].id, max_mb=10,
        )

    return {"vpn": ingest("vpn", VPN, Department.IT), "handbook": ingest("handbook", HANDBOOK, Department.HR)}


def delete(client: TestClient, user: User, document_id: str):
    return client.delete(f"/documents/{document_id}", headers=auth_header(user))


def reload(session: Session, document: Document) -> Document:
    session.expire_all()  # API ayrı oturumda yazdı; güncel kaydı oku
    fresh = session.get(Document, document.id)
    assert fresh is not None
    return fresh


def listed_ids(client: TestClient, user: User) -> set[str]:
    return {d["id"] for d in client.get("/documents", headers=auth_header(user)).json()}


def test_admin_delete_marks_deleted_and_removes_vectors(
    client: TestClient, session: Session, users: dict[str, User], vector_store: VectorStore, documents: dict[str, Document]
) -> None:
    vpn = documents["vpn"]

    response = delete(client, users["admin"], vpn.id)

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert response.json()["chunk_count"] == 0
    assert vector_store.count_document_chunks(vpn.id) == 0
    assert reload(session, vpn).status == DocumentStatus.DELETED  # satır mezar taşı olarak kalır
    assert vpn.id not in listed_ids(client, users["it"])
    assert vpn.id not in listed_ids(client, users["admin"])
    assert vector_store.count_document_chunks(documents["handbook"].id) == 1  # diğer belgeye dokunulmaz


def test_deleted_document_is_never_used_in_chat_answers(
    client: TestClient, users: dict[str, User], documents: dict[str, Document], fake_llm: FakeLLM
) -> None:
    # master plan §11.1 test_document_delete_revocation
    fake_llm.answers = ["Saati kontrol edin. [S1]"]
    before = client.post("/chat", json={"question": VPN}, headers=auth_header(users["it"])).json()
    assert documents["vpn"].id in {s["document_id"] for s in before["sources"]}

    delete(client, users["admin"], documents["vpn"].id)
    fake_llm.calls.clear()
    fake_llm.answers = [INSUFFICIENT_CONTEXT]
    after = client.post("/chat", json={"question": VPN}, headers=auth_header(users["it"])).json()

    sent_sources = "\n".join(message.split("QUESTION:")[0] for _, message in fake_llm.calls)
    assert VPN not in sent_sources
    assert documents["vpn"].id not in {s["document_id"] for s in after["sources"]}


def test_failed_vector_cleanup_keeps_document_hidden_and_can_be_retried(
    client: TestClient,
    session: Session,
    users: dict[str, User],
    vector_store: VectorStore,
    fake_embedder: FakeEmbedder,
    documents: dict[str, Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vpn = documents["vpn"]
    remove_vectors = vector_store.delete_document

    def unavailable(_document_id: str) -> None:
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(vector_store, "delete_document", unavailable)
    first = delete(client, users["admin"], vpn.id)

    assert first.status_code == 200
    assert first.json()["status"] == "cleanup_pending"
    assert "qdrant" not in first.text  # iç hata ayrıntısı istemciye gitmez
    # Vektörler hâlâ Qdrant'ta ama belge erişime kapalı: SQLite son sözü söyler.
    assert vector_store.count_document_chunks(vpn.id) == 1
    hits = retrieve(session, vector_store, fake_embedder, users["admin"], VPN, 5)
    assert vpn.id not in {hit.document_id for hit in hits}
    assert vpn.id in listed_ids(client, users["admin"])  # admin bekleyen temizliği görür
    assert vpn.id not in listed_ids(client, users["it"])

    monkeypatch.setattr(vector_store, "delete_document", remove_vectors)
    retry = delete(client, users["admin"], vpn.id)

    assert retry.json()["status"] == "deleted"
    assert vector_store.count_document_chunks(vpn.id) == 0
    assert reload(session, vpn).error_message is None


def test_access_is_revoked_before_vector_cleanup_runs(
    client: TestClient,
    session: Session,
    users: dict[str, User],
    vector_store: VectorStore,
    fake_embedder: FakeEmbedder,
    documents: dict[str, Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Temizlik sırasında belge çoktan "deleting" olmalı: bu anda yapılan arama onu görmemeli.
    vpn = documents["vpn"]
    seen_during_cleanup: list[set[str]] = []
    remove_vectors = vector_store.delete_document

    def check_then_remove(document_id: str) -> None:
        hits = retrieve(session, vector_store, fake_embedder, users["admin"], VPN, 5)
        seen_during_cleanup.append({hit.document_id for hit in hits})
        remove_vectors(document_id)

    monkeypatch.setattr(vector_store, "delete_document", check_then_remove)

    delete(client, users["admin"], vpn.id)

    assert seen_during_cleanup and vpn.id not in seen_during_cleanup[0]


@pytest.mark.parametrize("role", ["it", "hr", "finance"])
def test_members_cannot_delete(
    client: TestClient, session: Session, users: dict[str, User], vector_store: VectorStore, documents: dict[str, Document], role: str
) -> None:
    response = delete(client, users[role], documents["vpn"].id)

    assert response.status_code == 403
    assert reload(session, documents["vpn"]).status == DocumentStatus.ACTIVE
    assert vector_store.count_document_chunks(documents["vpn"].id) == 1


def test_delete_requires_authentication(client: TestClient, documents: dict[str, Document]) -> None:
    assert client.delete(f"/documents/{documents['vpn'].id}").status_code == 401


def test_unknown_or_already_deleted_document_returns_404(
    client: TestClient, users: dict[str, User], documents: dict[str, Document]
) -> None:
    assert delete(client, users["admin"], "no-such-document").status_code == 404
    assert delete(client, users["admin"], documents["vpn"].id).status_code == 200
    assert delete(client, users["admin"], documents["vpn"].id).status_code == 404


def test_document_still_processing_cannot_be_deleted(
    client: TestClient, session: Session, users: dict[str, User], documents: dict[str, Document]
) -> None:
    vpn = reload(session, documents["vpn"])
    vpn.status = DocumentStatus.PROCESSING
    session.commit()

    response = delete(client, users["admin"], vpn.id)

    assert response.status_code == 409
    assert reload(session, vpn).status == DocumentStatus.PROCESSING


def test_deleted_content_can_be_uploaded_again(
    client: TestClient, users: dict[str, User], documents: dict[str, Document]
) -> None:
    delete(client, users["admin"], documents["vpn"].id)

    response = client.post(
        "/documents",
        files={"file": ("vpn.md", VPN.encode(), "text/markdown")},
        data={"department": "IT", "visibility": "company"},
        headers=auth_header(users["admin"]),
    )

    assert response.status_code == 201
    assert response.json()["id"] != documents["vpn"].id
