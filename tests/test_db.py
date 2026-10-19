import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db.models import Department, Role, User


def test_user_is_created_with_defaults(session: Session) -> None:
    session.add(
        User(
            email="it@demo.local",
            password_hash="not-a-real-hash",
            role=Role.MEMBER,
            department=Department.IT,
        )
    )
    session.commit()

    user = session.scalars(select(User).where(User.email == "it@demo.local")).one()

    assert len(user.id) == 36
    assert user.is_active is True
    assert user.created_at is not None
    assert user.role is Role.MEMBER
    assert user.department is Department.IT


def test_invalid_role_is_rejected(session: Session) -> None:
    session.add(User(email="x@demo.local", password_hash="h", role="superadmin"))  # type: ignore[arg-type]

    with pytest.raises(StatementError):
        session.commit()


def test_duplicate_email_is_rejected(session: Session) -> None:
    # 1) Bir kullanıcı ekle ve kaydet (commit)
    session.add(
        User(
            email="it0@demo.local",
            password_hash="not-a-real-hash",
            role=Role.MEMBER,
            department=Department.IT,
        )
    )
    session.commit()

    # 2) AYNI e-postayla ikinci bir kullanıcı ekle
    session.add(
        User(
            email="it0@demo.local",
            password_hash="not-a-real-hash",
            role=Role.MEMBER,
            department=Department.HR,
        )
    )

    # 3) İkinci kayıt reddedilmeli
    with pytest.raises(IntegrityError):
        session.commit()
