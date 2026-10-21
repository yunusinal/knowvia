from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.repositories.vector_store import VectorStore, get_vector_store
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import answer_question
from app.services.embeddings import Embedder, get_embedder
from app.services.llm import LLMClient, LLMNotConfiguredError, get_llm

router = APIRouter(tags=["chat"])


def llm_dependency() -> LLMClient:
    """LLM ayarlanmamışsa istek 503 ve kurulum yönergesiyle reddedilir (anahtar yokken uygulama yine açılır)."""
    try:
        return get_llm()
    except LLMNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None


@router.post("/chat")
def chat(
    request: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    store: Annotated[VectorStore, Depends(get_vector_store)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLMClient, Depends(llm_dependency)],
) -> ChatResponse:
    """Kullanıcının yetkili olduğu belgelerden kaynaklı cevap; kanıt yoksa sabit ret cevabı."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Soru boş olamaz.")
    settings = get_settings()
    result = answer_question(
        db,
        store,
        embedder,
        llm,
        user,
        question,
        top_k=settings.retrieval_top_k,
        min_score=settings.retrieval_min_score,
    )
    return ChatResponse.model_validate(result)
