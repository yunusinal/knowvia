from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.db.models import Department, Role, User
from scripts.seed_users import seed_users


def test_seed_creates_demo_users(session: Session) -> None:
    created = seed_users(session, "demo-password")

    users = {user.email: user for user in session.scalars(select(User))}
    assert created == 4
    assert users["admin@demo.local"].role is Role.ADMIN
    assert users["admin@demo.local"].department is None
    assert users["finance@demo.local"].department is Department.FINANCE
    assert verify_password("demo-password", users["it@demo.local"].password_hash)


def test_seed_is_idempotent(session: Session) -> None:
    seed_users(session, "demo-password")

    created_again = seed_users(session, "demo-password")

    assert created_again == 0
    assert session.scalar(select(func.count()).select_from(User)) == 4
