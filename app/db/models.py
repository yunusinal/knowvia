import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# MVP'de tek demo organizasyonu vardır (master plan §6.1).
DEMO_TENANT = "demo-org"


class Base(DeclarativeBase):
    pass


class Role(enum.StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class Department(enum.StrEnum):
    IT = "IT"
    HR = "HR"
    FINANCE = "FINANCE"


class Visibility(enum.StrEnum):
    COMPANY = "company"  # tüm çalışanlar
    DEPARTMENT = "department"  # yalnızca belgenin departmanı (ve admin)


class DocumentStatus(enum.StrEnum):
    PROCESSING = "processing"
    ACTIVE = "active"  # yalnızca bu durumdaki belgeler aranabilir
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"
    CLEANUP_PENDING = "cleanup_pending"


class ConversationRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class TicketStatus(enum.StrEnum):
    OPEN = "open"
    CLOSED = "closed"


def _enum_type(enum_class: type[enum.Enum], name: str) -> Enum:
    """Enum değerini (ör. "admin") saklar; listede olmayan değeri hem Python'da hem DB'de reddeder."""
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
        create_constraint=True,
    )


def _new_id() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum_type(Role, "user_role"))
    department: Mapped[Department | None] = mapped_column(
        _enum_type(Department, "user_department"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class Document(Base):
    """Belgenin yetki ve durum bilgisi; tek doğru kaynak burasıdır (Qdrant'ta tutulmaz)."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEMO_TENANT)
    # Yalnızca gösterim için normalize edilmiş ad; dosya yolu olarak kullanılmaz.
    filename_original: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    department: Mapped[Department] = mapped_column(_enum_type(Department, "document_department"))
    visibility: Mapped[Visibility] = mapped_column(_enum_type(Visibility, "document_visibility"))
    status: Mapped[DocumentStatus] = mapped_column(
        _enum_type(DocumentStatus, "document_status"), default=DocumentStatus.PROCESSING
    )
    chunk_count: Mapped[int] = mapped_column(default=0)
    # Kullanıcıya gösterilebilecek genel mesaj; iç hata ayrıntısı yazılmaz.
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[ConversationRole] = mapped_column(_enum_type(ConversationRole, "conversation_role"))
    content: Mapped[str] = mapped_column(Text)
    # Kaynakları saklamak, eski assistant yanıtını sonraki turda güncel ACL ile yeniden kontrol etmeyi sağlar.
    sources: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    # Atıf yapılmasa da modele verilen belgeler; cevap bunlardan bilgi taşıyabilir.
    context_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    no_evidence: Mapped[bool] = mapped_column(default=False)
    response_type: Mapped[str] = mapped_column(String(16), default="rag")
    retrieval_ms: Mapped[int] = mapped_column(default=0)
    generation_ms: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class SupportTicket(Base):
    """Yerel destek talebi kaydı; gerçek bir yardım masası entegrasyonu değildir."""

    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(
        _enum_type(TicketStatus, "ticket_status"), default=TicketStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
