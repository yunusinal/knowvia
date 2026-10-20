"""Sentetik demo belgelerini indeksler (data/demo_docs + manifest.json).

Çalıştırma (API sunucusu kapalıyken; Qdrant local mode klasörü tek süreçle açılabilir):
    uv run python -m scripts.seed_demo_documents
Önce demo kullanıcıları oluşturulmalı: uv run python -m scripts.seed_users
"""

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Department, Role, User, Visibility
from app.db.session import SessionLocal, init_db
from app.repositories.vector_store import VectorStore, get_vector_store
from app.services.embeddings import Embedder, get_embedder
from app.services.ingest import DuplicateDocumentError, ingest_document

DEMO_DOCS_DIR = Path(__file__).resolve().parents[1] / "data" / "demo_docs"


@dataclass(frozen=True)
class DemoDocument:
    filename: str
    department: Department
    visibility: Visibility


def load_manifest(directory: Path = DEMO_DOCS_DIR) -> list[DemoDocument]:
    data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    return [
        DemoDocument(entry["filename"], Department(entry["department"]), Visibility(entry["visibility"]))
        for entry in data["documents"]
    ]


def seed_documents(
    db: Session,
    store: VectorStore,
    embedder: Embedder,
    uploaded_by: str,
    directory: Path = DEMO_DOCS_DIR,
) -> tuple[int, int]:
    """Manifest'teki belgeleri yükler; aynı içerik zaten yüklüyse atlar. (eklenen, atlanan) döndürür."""
    max_mb = get_settings().max_upload_mb
    created = skipped = 0
    for demo in load_manifest(directory):
        try:
            ingest_document(
                db,
                store,
                embedder,
                filename=demo.filename,
                content=(directory / demo.filename).read_bytes(),
                department=demo.department,
                visibility=demo.visibility,
                uploaded_by=uploaded_by,
                max_mb=max_mb,
            )
            created += 1
        except DuplicateDocumentError:
            skipped += 1
    return created, skipped


def main() -> None:
    init_db()
    with SessionLocal() as db:
        admin = db.scalars(select(User).where(User.role == Role.ADMIN, User.is_active)).first()
        if admin is None:
            raise SystemExit("Admin kullanıcısı yok. Önce çalıştırın: uv run python -m scripts.seed_users")
        try:
            store = get_vector_store()
        except RuntimeError as error:
            raise SystemExit(
                f"Qdrant açılamadı ({error}). API sunucusu çalışıyorsa önce durdurun."
            ) from None
        try:
            created, skipped = seed_documents(db, store, get_embedder(), admin.id)
        finally:
            store.close()
    print(f"{created} demo belgesi indekslendi ({skipped} zaten yüklüydü).")


if __name__ == "__main__":
    main()
