from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Geçmiş sunucudan okunur; istemci yalnızca konuşma kimliğini taşır."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    document_id: str
    filename: str
    page_number: int | None
    chunk_id: str
    snippet: str


class ChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer: str
    sources: list[SourceOut]
    no_evidence: bool
    retrieval_ms: int
    generation_ms: int
    response_type: Literal["rag", "canned"] = "rag"
    conversation_id: str
