from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import Department, DocumentStatus, Visibility


class DocumentOut(BaseModel):
    """API'nin gösterdiği belge bilgisi; içerik hash'i ve yükleyen kimliği bilerek yok."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str = Field(validation_alias="filename_original")
    department: Department
    visibility: Visibility
    status: DocumentStatus
    chunk_count: int
    created_at: datetime
