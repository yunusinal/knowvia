import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Role(enum.StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class Department(enum.StrEnum):
    IT = "IT"
    HR = "HR"
    FINANCE = "FINANCE"


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
