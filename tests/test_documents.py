import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Department, Document, DocumentStatus, User, Visibility
from app.repositories.vector_store import VectorStore
from app.services.ingest import safe_display_filename
from tests.fakes import FakeEmbedder
from tests.helpers import auth_header

VPN_GUIDE = "# VPN Kurulumu\n\nGlobalConnect istemcisini kurun ve vpn.demo.local adresine bağlanın.\n".encode()


def upload(
    client: TestClient,
    user: User,
    content: bytes = VPN_GUIDE,
    filename: str = "vpn.md",
    department: str = "IT",
    visibility: str = "company",
):
    return client.post(
        "/documents",
        files={"file": (filename, content, "application/octet-stream")},
        data={"department": department, "visibility": visibility},
        headers=auth_header(user),
    )


def all_documents(session: Session) -> list[Document]:
    session.expire_all()  # API ayrı oturumda yazdı; güncel kaydı oku
    return list(session.scalars(select(Document)))


def test_admin_upload_indexes_chunks_and_activates_document(
    client: TestClient, session: Session, users: dict[str, User], vector_store: VectorStore
) -> None:
    response = upload(client, users["admin"])

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "vpn.md"
    assert body["status"] == "active"
    assert body["chunk_count"] >= 1
    assert vector_store.count_document_chunks(body["id"]) == body["chunk_count"]
    [document] = all_documents(session)
    assert document.status == DocumentStatus.ACTIVE
    assert document.uploaded_by == users["admin"].id


@pytest.mark.parametrize("role", ["it", "hr", "finance"])
def test_members_cannot_upload(client: TestClient, session: Session, users: dict[str, User], role: str) -> None:
    response = upload(client, users[role])

    assert response.status_code == 403
    assert all_documents(session) == []


def test_upload_without_token_is_rejected(client: TestClient) -> None:
    response = client.post("/documents", files={"file": ("vpn.md", VPN_GUIDE)}, data={"department": "IT", "visibility": "company"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("filename", "content", "expected_status"),
    [
        ("big.txt", b"a" * (10 * 1024 * 1024 + 1), 413),
        ("notes.docx", b"some text", 415),
        ("broken.pdf", b"%PDF-1.4 not really a pdf", 400),
        ("empty.md", b"", 400),
    ],
    ids=["too-large", "unsupported-type", "broken-pdf", "empty"],
)
def test_invalid_files_are_rejected_without_creating_records(
    client: TestClient,
    session: Session,
    users: dict[str, User],
    filename: str,
    content: bytes,
    expected_status: int,
) -> None:
    response = upload(client, users["admin"], content=content, filename=filename)

    assert response.status_code == expected_status
    assert isinstance(response.json()["detail"], str)
    assert all_documents(session) == []


def test_invalid_department_or_visibility_is_rejected(client: TestClient, users: dict[str, User]) -> None:
    assert upload(client, users["admin"], department="LEGAL").status_code == 422
    assert upload(client, users["admin"], visibility="public").status_code == 422


def test_duplicate_content_is_rejected(client: TestClient, session: Session, users: dict[str, User]) -> None:
    assert upload(client, users["admin"]).status_code == 201

    response = upload(client, users["admin"], filename="copy-of-vpn.md")

    assert response.status_code == 409
    assert len(all_documents(session)) == 1


def test_failed_embedding_marks_document_failed_without_leaking_details(
    client: TestClient,
    session: Session,
    users: dict[str, User],
    fake_embedder: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_embedding(_texts: object) -> list[list[float]]:
        raise RuntimeError("model crashed")

    monkeypatch.setattr(fake_embedder, "embed_passages", broken_embedding)

    response = upload(client, users["admin"])

    assert response.status_code == 500
    assert "model crashed" not in response.text  # iç hata ayrıntısı istemciye sızmaz
    [document] = all_documents(session)
    assert document.status == DocumentStatus.FAILED
    assert document.error_message == "İndeksleme başarısız oldu."


def test_failure_after_vectors_were_written_removes_them(
    client: TestClient,
    session: Session,
    users: dict[str, User],
    vector_store: VectorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Noktalar Qdrant'a yazıldıktan sonra hata çıkarsa yarım kalan veri temizlenmeli.
    write_chunks = vector_store.add_chunks

    def write_then_fail(*args: object, **kwargs: object) -> None:
        write_chunks(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        raise RuntimeError("connection lost after write")

    monkeypatch.setattr(vector_store, "add_chunks", write_then_fail)

    response = upload(client, users["admin"])

    assert response.status_code == 500
    [document] = all_documents(session)
    assert document.status == DocumentStatus.FAILED
    assert vector_store.count_document_chunks(document.id) == 0


def test_client_filename_is_reduced_to_a_safe_display_name(client: TestClient, users: dict[str, User]) -> None:
    response = upload(client, users["admin"], filename="..\\..\\secret\\vpn-guide.md")

    assert response.json()["filename"] == "vpn-guide.md"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.md", "passwd.md"),
        ("C:\\Users\\someone\\plan.pdf", "plan.pdf"),
        ("vpn\x00guide\x1b.md", "vpnguide.md"),
        ("   ", "document"),
        ("x" * 300 + ".pdf", "x" * 251 + ".pdf"),
    ],
    ids=["posix-path", "windows-path", "control-characters", "blank", "too-long-keeps-extension"],
)
def test_safe_display_filename(raw: str, expected: str) -> None:
    # HTTP istemcisi kontrol karakterlerini göndermeden kodlar; temizlik fonksiyonu doğrudan sınanır.
    assert safe_display_filename(raw) == expected


def add_document(session: Session, users: dict[str, User], department: Department, visibility: Visibility, status: DocumentStatus = DocumentStatus.ACTIVE) -> Document:
    document = Document(
        filename_original=f"{department}-{visibility}-{status}.md",
        content_sha256=f"{department}{visibility}{status}",
        uploaded_by=users["admin"].id,
        department=department,
        visibility=visibility,
        status=status,
    )
    session.add(document)
    session.commit()
    return document


def listed_filenames(client: TestClient, user: User, **params: str) -> set[str]:
    response = client.get("/documents", headers=auth_header(user), params=params)
    assert response.status_code == 200
    return {d["filename"] for d in response.json()}


def test_document_list_follows_access_matrix(client: TestClient, session: Session, users: dict[str, User]) -> None:
    add_document(session, users, Department.HR, Visibility.COMPANY)
    add_document(session, users, Department.IT, Visibility.DEPARTMENT)
    add_document(session, users, Department.FINANCE, Visibility.DEPARTMENT)
    add_document(session, users, Department.IT, Visibility.DEPARTMENT, DocumentStatus.FAILED)

    assert listed_filenames(client, users["it"]) == {"HR-company-active.md", "IT-department-active.md"}
    assert listed_filenames(client, users["finance"]) == {"HR-company-active.md", "FINANCE-department-active.md"}
    assert listed_filenames(client, users["admin"]) == {
        "HR-company-active.md",
        "IT-department-active.md",
        "FINANCE-department-active.md",
        "IT-department-failed.md",
    }


def test_document_list_ignores_spoofed_role_and_department(
    client: TestClient, session: Session, users: dict[str, User]
) -> None:
    add_document(session, users, Department.FINANCE, Visibility.DEPARTMENT)

    # Rol/departman istekten okunmaz; yetki SQLite'taki kullanıcı kaydından gelir.
    assert listed_filenames(client, users["it"], role="admin", department="FINANCE") == set()


def test_document_list_requires_authentication(client: TestClient) -> None:
    assert client.get("/documents").status_code == 401
