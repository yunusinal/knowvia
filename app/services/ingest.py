"""Belge yükleme akışı: doğrula → SQLite'a `processing` → chunk + embed + Qdrant → `active`."""

import hashlib
import logging
import re
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Department, Document, DocumentStatus, Visibility
from app.repositories.vector_store import VectorStore
from app.services.chunking import chunk_pages
from app.services.embeddings import Embedder
from app.services.extraction import extract_text

logger = logging.getLogger(__name__)

_MAX_FILENAME_LENGTH = 255
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class DuplicateDocumentError(Exception):
    """Aynı içerik zaten yüklü (veya yükleniyor)."""


class IngestFailedError(Exception):
    """Belge doğrulandı ama indekslenemedi; SQLite kaydı `failed` olarak kalır."""


def safe_display_filename(filename: str) -> str:
    """İstemcinin verdiği adı yalnızca gösterim için temizler: klasör kısmı ve kontrol karakterleri atılır."""
    name = PurePosixPath(filename.replace("\\", "/")).name
    name = _CONTROL_CHARACTERS.sub("", name).strip()
    if len(name) > _MAX_FILENAME_LENGTH:
        stem, dot, suffix = name.rpartition(".")
        name = stem[: _MAX_FILENAME_LENGTH - len(suffix) - 1] + dot + suffix if dot else name[:_MAX_FILENAME_LENGTH]
    return name or "document"


def ingest_document(
    db: Session,
    store: VectorStore,
    embedder: Embedder,
    *,
    filename: str,
    content: bytes,
    department: Department,
    visibility: Visibility,
    uploaded_by: str,
    max_mb: int,
) -> Document:
    """Belgeyi doğrular ve indeksler. Doğrulama hatası (ExtractionError) hiç kayıt oluşturmaz."""
    display_name = safe_display_filename(filename)
    pages = extract_text(display_name, content, max_mb)

    digest = hashlib.sha256(content).hexdigest()
    duplicate = db.scalars(
        select(Document).where(
            Document.content_sha256 == digest,
            Document.status.in_([DocumentStatus.ACTIVE, DocumentStatus.PROCESSING]),
        )
    ).first()
    if duplicate is not None:
        raise DuplicateDocumentError(duplicate.id)

    document = Document(
        filename_original=display_name,
        content_sha256=digest,
        uploaded_by=uploaded_by,
        department=department,
        visibility=visibility,
        status=DocumentStatus.PROCESSING,
    )
    db.add(document)
    db.commit()

    try:
        chunks = chunk_pages(pages, embedder.count_passage_tokens)
        vectors = embedder.embed_passages([chunk.text for chunk in chunks])
        store.add_chunks(document.id, display_name, chunks, vectors)
    except Exception as error:
        logger.exception("Belge indekslenemedi: %s", document.id)
        _remove_partial_points(store, document.id)
        document.status = DocumentStatus.FAILED
        document.error_message = "İndeksleme başarısız oldu."
        db.commit()
        raise IngestFailedError(document.id) from error

    document.status = DocumentStatus.ACTIVE
    document.chunk_count = len(chunks)
    db.commit()
    return document


def _remove_partial_points(store: VectorStore, document_id: str) -> None:
    # Temizlik başarısız olsa da belge `failed` kalır ve izinli listeye hiç girmez.
    try:
        store.delete_document(document_id)
    except Exception:
        logger.exception("Yarım kalan noktalar silinemedi: %s", document_id)
