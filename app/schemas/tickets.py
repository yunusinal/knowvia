"""Destek talebi oluşturma ve listeleme şemaları."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.tickets import MAX_DESCRIPTION_CHARS, MAX_SUBJECT_CHARS


class TicketCreate(BaseModel):
    """Kullanıcının onayladığı (gerekirse düzenlediği) talep; sahiplik token'dan alınır."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=3, max_length=MAX_SUBJECT_CHARS)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    conversation_id: UUID | None = None


class TicketOut(BaseModel):
    id: str
    subject: str
    description: str
    status: Literal["open", "closed"]
    created_by_email: str
    conversation_id: str | None
    created_at: datetime
