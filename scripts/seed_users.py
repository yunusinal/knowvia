"""Demo kullanıcılarını oluşturur. Çalıştırma: uv run python -m scripts.seed_users"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.models import Department, Role, User
from app.db.session import SessionLocal, init_db

DEMO_USERS: list[tuple[str, Role, Department | None]] = [
    ("admin@demo.local", Role.ADMIN, None),
    ("it@demo.local", Role.MEMBER, Department.IT),
    ("hr@demo.local", Role.MEMBER, Department.HR),
    ("finance@demo.local", Role.MEMBER, Department.FINANCE),
]


def seed_users(session: Session, password: str, admin_password: str | None = None) -> int:
    """Eksik demo kullanıcılarını ekler; üyelere dokunmaz. Eklenen sayıyı döndürür.

    `admin_password` verilirse admin onu kullanır ve mevcut admin parolası ona eşitlenir: üye
    parolası herkese açık bir demoda paylaşılırsa admin eski ortak parolayla kalmamalıdır.
    """
    created = 0
    for email, role, department in DEMO_USERS:
        own_password = admin_password if role is Role.ADMIN and admin_password else password
        exists = session.scalars(select(User).where(User.email == email)).first()
        if exists is not None:
            if role is Role.ADMIN and admin_password and not verify_password(admin_password, exists.password_hash):
                exists.password_hash = hash_password(admin_password)
            continue
        session.add(
            User(
                email=email,
                password_hash=hash_password(own_password),
                role=role,
                department=department,
            )
        )
        created += 1
    session.commit()
    return created


def main() -> None:
    secret = get_settings().demo_user_password
    password = secret.get_secret_value() if secret else ""
    if not password or password == "replace_me":
        raise SystemExit(
            "DEMO_USER_PASSWORD ayarlanmamış. .env dosyasına bir parola yazın "
            "(bkz. .env.example)."
        )
    admin_secret = get_settings().admin_password
    admin_password = admin_secret.get_secret_value() if admin_secret else None
    if admin_password == password:
        raise SystemExit("ADMIN_PASSWORD, DEMO_USER_PASSWORD ile aynı olamaz.")
    init_db()
    with SessionLocal() as session:
        created = seed_users(session, password, admin_password)
    print(f"{created} demo kullanıcısı oluşturuldu ({len(DEMO_USERS) - created} zaten vardı).")


if __name__ == "__main__":
    main()
