from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base

settings = get_settings()

# FastAPI istekleri farklı thread'lerde işleyebilir; her istek kendi oturumunu
# açıp kapattığı için SQLite'ın tek-thread kısıtını kaldırmak güvenlidir.
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _ensure_sqlite_directory(database_url: str) -> None:
    """SQLite dosyasının klasörü (ör. data/runtime/) yoksa oluşturur."""
    database = make_url(database_url).database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    """Eksik tabloları oluşturur; mevcut tablolara ve verilere dokunmaz."""
    _ensure_sqlite_directory(settings.database_url)
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    """FastAPI bağımlılığı: her istek için bir oturum açar, istek bitince kapatır."""
    with SessionLocal() as session:
        yield session
