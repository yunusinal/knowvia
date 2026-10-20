"""Belge erişim kararının tek yeri (master plan §6.1 yetki matrisi).

Kural: belge aktif ve demo organizasyonuna ait olmalı; admin tümünü, üye `company`
belgelerini ve kendi departmanının `department` belgelerini görür. Rol ve departman
her zaman SQLite'taki kullanıcı kaydından gelir, istekten alınmaz.
"""

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import DEMO_TENANT, Document, DocumentStatus, Role, User, Visibility


def can_access_document(user: User, document: Document) -> bool:
    """Tek bir belge için karar; arama sonrası son kontrolde kullanılır."""
    if not user.is_active:
        return False
    if document.tenant_id != DEMO_TENANT or document.status != DocumentStatus.ACTIVE:
        return False
    if user.role == Role.ADMIN:
        return True
    if document.visibility == Visibility.COMPANY:
        return True
    return user.department is not None and document.department == user.department


def allowed_document_ids(db: Session, user: User) -> set[str]:
    """Kullanıcının arayabileceği belge kimlikleri; arama öncesi Qdrant filtresine verilir.

    `can_access_document` ile aynı kuralın SQL hâlidir; ikisinin uyumu testle denetlenir.
    """
    if not user.is_active:
        return set()
    query = select(Document.id).where(
        Document.tenant_id == DEMO_TENANT, Document.status == DocumentStatus.ACTIVE
    )
    if user.role != Role.ADMIN:
        query = query.where(_member_visibility(user))
    return set(db.scalars(query))


def visible_documents(db: Session, user: User) -> list[Document]:
    """Belge listesi ekranı: üye yalnızca erişebildiği aktif belgeleri, admin silinmemiş tümünü görür."""
    if not user.is_active:
        return []
    query = select(Document).where(Document.tenant_id == DEMO_TENANT)
    if user.role == Role.ADMIN:
        query = query.where(Document.status != DocumentStatus.DELETED)
    else:
        query = query.where(Document.status == DocumentStatus.ACTIVE, _member_visibility(user))
    return list(db.scalars(query.order_by(Document.created_at)))


def _member_visibility(user: User) -> ColumnElement[bool]:
    conditions: list[ColumnElement[bool]] = [Document.visibility == Visibility.COMPANY]
    if user.department is not None:
        conditions.append(
            and_(Document.visibility == Visibility.DEPARTMENT, Document.department == user.department)
        )
    return or_(*conditions)
