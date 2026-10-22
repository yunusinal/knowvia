"""Yetki filtreli anlamsal arama (master plan §5.2 adım 5–6).

1. Arama öncesi: SQLite'tan kullanıcının izinli belge listesi çıkarılır; boşsa arama yapılmaz.
2. Qdrant yalnızca bu listedeki belgelerin chunk'larında arar.
3. Arama sonrası: her sonucun belgesi SQLite'tan taze okunup tekrar denetlenir; iki adım arasında
   silinen veya yetkisi değişen belge sonuçtan çıkar (son söz SQLite'ındır).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, User
from app.repositories.vector_store import ChunkHit, VectorStore
from app.services.authorization import allowed_document_ids, can_access_document
from app.services.embeddings import Embedder


def retrieve(
    db: Session,
    store: VectorStore,
    embedder: Embedder,
    user: User,
    question: str,
    top_k: int,
) -> list[ChunkHit]:
    """Kullanıcının yetkili olduğu chunk'lar arasından soruya en benzer `top_k` tanesini döndürür."""
    if not question.strip():
        raise ValueError("Soru boş olamaz.")

    allowed = allowed_document_ids(db, user)
    if not allowed:
        return []  # yetkili belge yoksa soru embed edilmez, Qdrant'a gidilmez (fail closed)

    hits = store.search(embedder.embed_query(question), question, allowed, top_k)
    return _recheck_access(db, user, hits)


def _recheck_access(db: Session, user: User, hits: list[ChunkHit]) -> list[ChunkHit]:
    if not hits:
        return []
    # populate_existing: oturumda önceden yüklenmiş kopya değil, veritabanındaki güncel kayıt okunur.
    documents = db.scalars(
        select(Document)
        .where(Document.id.in_({hit.document_id for hit in hits}))
        .execution_options(populate_existing=True)
    )
    accessible = {document.id for document in documents if can_access_document(user, document)}
    return [hit for hit in hits if hit.document_id in accessible]
