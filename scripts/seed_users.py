"""Demo kullanıcılarını oluşturur. Çalıştırma: uv run python -m scripts.seed_users"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import Department, Role, User
from app.db.session import SessionLocal, init_db

DEMO_USERS: list[tuple[str, Role, Department | None]] = [
    ("admin@demo.local", Role.ADMIN, None),
    ("it@demo.local", Role.MEMBER, Department.IT),
    ("hr@demo.local", Role.MEMBER, Department.HR),
    ("finance@demo.local", Role.MEMBER, Department.FINANCE),
]


def seed_users(session: Session, password: str) -> int:
    """Eksik demo kullanıcılarını ekler; var olanlara dokunmaz. Eklenen sayıyı döndürür."""
    created = 0
    for email, role, department in DEMO_USERS:
        exists = session.scalars(select(User).where(User.email == email)).first()
        if exists is not None:
            continue
        session.add(
            User(
                email=email,
                password_hash=hash_password(password),
                role=role,
                department=department,
            )
        )
        created += 1
    session.commit()
    return created


def main() -> None:
    password = get_settings().demo_user_password
    if not password or password == "replace_me":
        raise SystemExit(
            "DEMO_USER_PASSWORD ayarlanmamış. .env dosyasına bir parola yazın "
            "(bkz. .env.example)."
        )
    init_db()
    with SessionLocal() as session:
        created = seed_users(session, password)
    print(f"{created} demo kullanıcısı oluşturuldu ({len(DEMO_USERS) - created} zaten vardı).")


if __name__ == "__main__":
    main()
