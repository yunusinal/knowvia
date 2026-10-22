"""Belge silme (master plan §6.2): önce erişimi kes, sonra vektörleri temizle.

Belgeyi görünmez yapan adım SQLite'taki durum değişikliğidir; izin listesi her sorguda SQLite'tan
üretildiği için `deleting` olan belge bir sonraki sorudan itibaren kimseye dönmez. Qdrant silmesi
yalnızca temizliktir: başarısız olursa belge `cleanup_pending` kalır ve silme tekrar denenebilir.
"""

import logging

from sqlalchemy.orm import Session

from app.db.models import DEMO_TENANT, Document, DocumentStatus
from app.repositories.vector_store import VectorStore

logger = logging.getLogger(__name__)


class DocumentNotFoundError(Exception):
    """Belge yok veya zaten silinmiş."""


class DocumentBusyError(Exception):
    """Belge hâlâ yükleniyor; yükleme bitince silme yeniden denenebilir."""


def delete_document(db: Session, store: VectorStore, document_id: str) -> Document:
    document = db.get(Document, document_id)
    # Okuma kuralıyla aynı: başka kiracının belgesi bu uygulama için yoktur (404, varlığı ele verilmez).
    if document is None or document.tenant_id != DEMO_TENANT or document.status == DocumentStatus.DELETED:
        raise DocumentNotFoundError(document_id)
    if document.status == DocumentStatus.PROCESSING:
        # Yükleme bitince belgeyi `active` yapıp silmeyi geri alabilirdi.
        raise DocumentBusyError(document_id)

    # 1. Erişimi kes: bu commit'ten sonra belge hiçbir aramada izinli listeye girmez.
    document.status = DocumentStatus.DELETING
    db.commit()

    # 2. Temizlik: vektörleri sil. Hata erişimi açmaz, yalnızca temizliği yarım bırakır.
    try:
        store.delete_document(document.id)
    except Exception:
        logger.exception("Belge vektörleri silinemedi: %s", document.id)
        document.status = DocumentStatus.CLEANUP_PENDING
        document.error_message = "Vektör temizliği başarısız oldu; silmeyi tekrar deneyin."
        db.commit()
        return document

    # 3. Kayıt silinmez, mezar taşı (tombstone) olarak `deleted` durumunda kalır.
    document.status = DocumentStatus.DELETED
    document.chunk_count = 0
    document.error_message = None
    db.commit()
    return document
