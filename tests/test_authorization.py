import itertools

import pytest
from sqlalchemy.orm import Session

from app.db.models import Department, Document, DocumentStatus, User, Visibility
from app.services.authorization import allowed_document_ids, can_access_document, visible_documents


def add_document(
    session: Session,
    uploader: User,
    department: Department,
    visibility: Visibility,
    status: DocumentStatus = DocumentStatus.ACTIVE,
    tenant_id: str = "demo-org",
) -> Document:
    document = Document(
        filename_original=f"{department}-{visibility}-{status}.md",
        content_sha256=f"{department}{visibility}{status}{tenant_id}",
        uploaded_by=uploader.id,
        department=department,
        visibility=visibility,
        status=status,
        tenant_id=tenant_id,
    )
    session.add(document)
    session.commit()
    return document


@pytest.fixture
def all_documents(session: Session, users: dict[str, User]) -> list[Document]:
    """Her departman × görünürlük × durum birleşimi + başka organizasyona ait bir belge."""
    admin = users["admin"]
    documents = [
        add_document(session, admin, department, visibility, status)
        for department, visibility, status in itertools.product(Department, Visibility, DocumentStatus)
    ]
    documents.append(add_document(session, admin, Department.IT, Visibility.COMPANY, tenant_id="other-org"))
    return documents


def ids(documents: list[Document], **criteria: object) -> set[str]:
    return {d.id for d in documents if all(getattr(d, key) == value for key, value in criteria.items())}


def test_access_matrix_matches_master_plan(all_documents: list[Document], users: dict[str, User]) -> None:
    active = [d for d in all_documents if d.status == DocumentStatus.ACTIVE and d.tenant_id == "demo-org"]
    company = ids(active, visibility=Visibility.COMPANY)

    def accessible(user: User) -> set[str]:
        return {d.id for d in all_documents if can_access_document(user, d)}

    assert accessible(users["admin"]) == {d.id for d in active}
    for name, department in [("it", Department.IT), ("hr", Department.HR), ("finance", Department.FINANCE)]:
        own_department = ids(active, visibility=Visibility.DEPARTMENT, department=department)
        assert accessible(users[name]) == company | own_department


def test_sql_allowlist_agrees_with_single_document_check(
    session: Session, all_documents: list[Document], users: dict[str, User]
) -> None:
    # Aynı kural iki yerde yazılı (Python ve SQL); birbirinden kaymadığını tüm birleşimlerde denetler.
    for user in users.values():
        expected = {d.id for d in all_documents if can_access_document(user, d)}
        assert allowed_document_ids(session, user) == expected, user.email


def test_inactive_user_gets_nothing(session: Session, all_documents: list[Document], users: dict[str, User]) -> None:
    admin = users["admin"]
    admin.is_active = False
    session.commit()

    assert allowed_document_ids(session, admin) == set()
    assert visible_documents(session, admin) == []
    assert not any(can_access_document(admin, d) for d in all_documents)


def test_member_without_department_sees_only_company_documents(
    session: Session, all_documents: list[Document], users: dict[str, User]
) -> None:
    member = users["it"]
    member.department = None
    session.commit()

    allowed = allowed_document_ids(session, member)

    assert allowed == ids(all_documents, status=DocumentStatus.ACTIVE, visibility=Visibility.COMPANY, tenant_id="demo-org")


def test_admin_listing_includes_non_active_but_not_deleted(
    session: Session, all_documents: list[Document], users: dict[str, User]
) -> None:
    listed = {d.id for d in visible_documents(session, users["admin"])}

    assert listed == {d.id for d in all_documents if d.status != DocumentStatus.DELETED and d.tenant_id == "demo-org"}


def test_member_listing_equals_allowlist(session: Session, all_documents: list[Document], users: dict[str, User]) -> None:
    for name in ("it", "hr", "finance"):
        user = users[name]
        assert {d.id for d in visible_documents(session, user)} == allowed_document_ids(session, user)
