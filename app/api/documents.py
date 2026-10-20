from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import get_settings
from app.db.models import Department, User, Visibility
from app.db.session import get_db
from app.repositories.vector_store import VectorStore, get_vector_store
from app.schemas.documents import DocumentOut
from app.services.authorization import visible_documents
from app.services.embeddings import Embedder, get_embedder
from app.services.extraction import ExtractionError
from app.services.ingest import DuplicateDocumentError, IngestFailedError, ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])

_EXTRACTION_STATUS = {
    "too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    "unsupported_type": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
}


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile,
    department: Annotated[Department, Form()],
    visibility: Annotated[Visibility, Form()],
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    store: Annotated[VectorStore, Depends(get_vector_store)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
) -> DocumentOut:
    """Yalnızca admin: PDF/TXT/MD belge yükler ve indeksler."""
    max_mb = get_settings().max_upload_mb
    # Sınırın bir bayt fazlası okunur: dosya büyükse tamamı belleğe alınmadan "too_large" olur.
    content = file.file.read(max_mb * 1024 * 1024 + 1)
    try:
        document = ingest_document(
            db,
            store,
            embedder,
            filename=file.filename or "",
            content=content,
            department=department,
            visibility=visibility,
            uploaded_by=admin.id,
            max_mb=max_mb,
        )
    except ExtractionError as error:
        code = _EXTRACTION_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=code, detail=error.message) from None
    except DuplicateDocumentError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Bu içerik zaten yüklenmiş."
        ) from None
    except IngestFailedError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Belge indekslenemedi; daha sonra tekrar deneyin.",
        ) from None
    return DocumentOut.model_validate(document)


@router.get("")
def list_documents(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DocumentOut]:
    """Kullanıcının görebildiği belgeler; yetki SQLite'taki kullanıcı kaydına göre belirlenir."""
    return [DocumentOut.model_validate(document) for document in visible_documents(db, user)]
