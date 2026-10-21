from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Soru ve sınırlı konuşma bağlamı; yetki bilgisi istekten alınmaz."""

    question: str = Field(min_length=1, max_length=1000)
    history: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=4)


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
