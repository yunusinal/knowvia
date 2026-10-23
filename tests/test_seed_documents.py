from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Department, Document, DocumentStatus, User, Visibility
from app.repositories.vector_store import VectorStore
from app.services.authorization import allowed_document_ids
from app.services.extraction import extract_text
from scripts.seed_demo_documents import DEMO_DOCS_DIR, load_manifest, seed_documents
from tests.fakes import FakeEmbedder


def test_manifest_lists_exactly_the_demo_files() -> None:
    listed = {demo.filename for demo in load_manifest()}
    on_disk = {path.name for path in DEMO_DOCS_DIR.glob("*.md")}

    assert listed == on_disk
    assert len(listed) >= 12  # master plan §10


def test_every_department_has_public_and_confidential_documents() -> None:
    pairs = {(demo.department, demo.visibility) for demo in load_manifest()}

    assert pairs == {(department, visibility) for department in Department for visibility in Visibility}


def test_demo_documents_pass_upload_validation() -> None:
    for demo in load_manifest():
        pages = extract_text(demo.filename, (DEMO_DOCS_DIR / demo.filename).read_bytes(), max_mb=10)
        assert pages and pages[0].text.startswith("# "), demo.filename


def test_seeding_is_idempotent(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User]
) -> None:
    count = len(load_manifest())

    assert seed_documents(session, vector_store, fake_embedder, users["admin"].id) == (count, 0)
    assert seed_documents(session, vector_store, fake_embedder, users["admin"].id) == (0, count)

    documents = list(session.scalars(select(Document)))
    assert len(documents) == count
    assert all(d.status == DocumentStatus.ACTIVE and d.chunk_count > 0 for d in documents)


def test_seeded_confidential_documents_follow_department_acl(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder, users: dict[str, User]
) -> None:
    seed_documents(session, vector_store, fake_embedder, users["admin"].id)
    filenames = {d.id: d.filename_original for d in session.scalars(select(Document))}

    def visible_to(name: str) -> set[str]:
        return {filenames[i] for i in allowed_document_ids(session, users[name])}

    assert "budget-plan-2026-confidential.md" not in visible_to("it")
    assert "hiring-guide-confidential.md" not in visible_to("finance")
    assert "incident-response-internal.md" in visible_to("it")
    assert "incident-response-internal.md" not in visible_to("hr")
    # VPN sorunları herkesi ilgilendirir: sorun giderme belgesi şirket geneline açıktır.
    assert "vpn-troubleshooting.md" in visible_to("hr")
    assert visible_to("admin") == set(filenames.values())
