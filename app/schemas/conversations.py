"""Konuşma listeleme ve geçmiş gösterimi için API çıktıları."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.chat import SourceOut


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceOut]
    no_evidence: bool
    response_type: Literal["rag", "canned"]
    retrieval_ms: int
    generation_ms: int
