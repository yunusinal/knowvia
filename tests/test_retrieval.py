import pytest
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.db.models import Department, Document, DocumentStatus, User, Visibility
from app.repositories.vector_store import VectorStore
from app.services import retrieval
from app.services.ingest import ingest_document
from app.services.retrieval import retrieve
from tests.fakes import FakeEmbedder

BUDGET = "2026 bütçe planı: bulut altyapı harcamalarına yüzde yirmi artış ayrıldı."
VPN_TROUBLESHOOTING = "VPN sorun giderme: sertifika doğrulanamadı hatasında cihaz saatini kontrol edin."
HANDBOOK = "Çalışan el kitabı: mesai saatleri hafta içi dokuz ile on sekiz arasındadır."


@pytest.fixture
def documents(session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User]) -> dict[str, Document]:
    """Gerçek yükleme akışıyla indekslenmiş üç belge: Finance-gizli, IT-gizli ve şirket geneli."""
    def ingest(name: str, text: str, department: Department, visibility: Visibility) -> Document:
        return ingest_document(
            session,
            vector_store,
            fake_embedder,
            filename=f"{name}.md",
            content=text.encode(),
            department=department,
            visibility=visibility,
            uploaded_by=users["admin"].id,
            max_mb=10,
        )

    return {
        "budget": ingest("budget", BUDGET, Department.FINANCE, Visibility.DEPARTMENT),
        "vpn": ingest("vpn", VPN_TROUBLESHOOTING, Department.IT, Visibility.DEPARTMENT),
        "handbook": ingest("handbook", HANDBOOK, Department.HR, Visibility.COMPANY),
    }


def search(session: Session, vector_store: VectorStore, embedder: FakeEmbedder, user: User, question: str, top_k: int = 5) -> list[str]:
    return [hit.document_id for hit in retrieve(session, vector_store, embedder, user, question, top_k)]


def test_it_member_never_receives_finance_confidential_chunks(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User], documents: dict[str, Document]
) -> None:
    # Soru bütçe belgesiyle birebir aynı; yine de IT üyesine gelmemeli.
    results = search(session, vector_store, fake_embedder, users["it"], BUDGET)

    assert documents["budget"].id not in results
    assert set(results) == {documents["vpn"].id, documents["handbook"].id}


def test_finance_member_gets_own_department_document_first(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User], documents: dict[str, Document]
) -> None:
    results = search(session, vector_store, fake_embedder, users["finance"], BUDGET)

    assert results[0] == documents["budget"].id
    assert documents["vpn"].id not in results


def test_admin_searches_all_active_documents(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User], documents: dict[str, Document]
) -> None:
    results = search(session, vector_store, fake_embedder, users["admin"], "plan")

    assert set(results) == {d.id for d in documents.values()}


def test_no_allowed_documents_means_no_embedding_and_no_search(
    session: Session,
    vector_store: VectorStore,
    fake_embedder: FakeEmbedder,
    users: dict[str, User],
    documents: dict[str, Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.execute(update(Document).values(visibility=Visibility.DEPARTMENT, department=Department.FINANCE))
    session.commit()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("İzinli belge yokken embedding veya arama yapılmamalı.")

    monkeypatch.setattr(fake_embedder, "embed_query", fail)
    monkeypatch.setattr(vector_store, "search", fail)

    assert search(session, vector_store, fake_embedder, users["hr"], "mesai saatleri") == []


@pytest.mark.parametrize(
    "change",
    [
        {"status": DocumentStatus.DELETING},
        {"status": DocumentStatus.FAILED},
        {"visibility": Visibility.DEPARTMENT, "department": Department.FINANCE},
    ],
    ids=["deleted-meanwhile", "failed-meanwhile", "made-confidential-meanwhile"],
)
def test_post_check_drops_documents_whose_access_changed_after_allowlist(
    session: Session,
    vector_store: VectorStore,
    fake_embedder: FakeEmbedder,
    users: dict[str, User],
    documents: dict[str, Document],
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, object],
) -> None:
    # Yarış durumunu taklit et: izin listesi hesaplandıktan hemen sonra belge değişiyor.
    handbook_id = documents["handbook"].id
    compute_allowlist = retrieval.allowed_document_ids

    def allowlist_then_change(db: Session, user: User) -> set[str]:
        allowed = compute_allowlist(db, user)
        db.execute(update(Document).where(Document.id == handbook_id).values(**change))
        db.commit()
        return allowed

    monkeypatch.setattr(retrieval, "allowed_document_ids", allowlist_then_change)

    results = search(session, vector_store, fake_embedder, users["it"], HANDBOOK)

    assert handbook_id not in results
    assert results == [documents["vpn"].id]


def test_post_check_reads_changes_committed_by_another_session(
    engine: Engine,
    session: Session,
    vector_store: VectorStore,
    fake_embedder: FakeEmbedder,
    users: dict[str, User],
    documents: dict[str, Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bu oturum belgenin eski kopyasını hafızasında tutuyor; değişiklik başka bir istekten geliyor
    # (ör. admin aynı anda belgeyi siliyor). Son kontrol hafızadaki kopyaya değil veritabanına bakmalı.
    handbook_id = documents["handbook"].id
    compute_allowlist = retrieval.allowed_document_ids

    def allowlist_then_other_session_deletes(db: Session, user: User) -> set[str]:
        allowed = compute_allowlist(db, user)
        with Session(engine) as other:
            other.execute(update(Document).where(Document.id == handbook_id).values(status=DocumentStatus.DELETING))
            other.commit()
        return allowed

    monkeypatch.setattr(retrieval, "allowed_document_ids", allowlist_then_other_session_deletes)

    results = search(session, vector_store, fake_embedder, users["it"], HANDBOOK)

    assert handbook_id not in results


def test_vectors_of_failed_documents_are_never_returned(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User], documents: dict[str, Document]
) -> None:
    # Ör. temizlik başarısız oldu: noktalar Qdrant'ta kaldı ama belge SQLite'ta failed.
    session.execute(update(Document).where(Document.id == documents["handbook"].id).values(status=DocumentStatus.FAILED))
    session.commit()

    results = search(session, vector_store, fake_embedder, users["admin"], HANDBOOK)

    assert documents["handbook"].id not in results


def test_top_k_limits_results(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User], documents: dict[str, Document]
) -> None:
    assert len(search(session, vector_store, fake_embedder, users["admin"], "plan", top_k=1)) == 1


def test_blank_question_is_rejected(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User]
) -> None:
    with pytest.raises(ValueError):
        retrieve(session, vector_store, fake_embedder, users["it"], "   ", 5)
