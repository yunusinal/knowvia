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
from app.services.chat import ChatResult
from app.services.conversations import append_exchange, get_owned, safe_history
from app.services.embeddings import Embedder, get_embedder
from app.services.llm import LLMClient, LLMNotConfiguredError, get_llm
from app.services.smalltalk import canned_reply

router = APIRouter(tags=["chat"])


def canned_dependency(request: ChatRequest) -> str | None:
    return canned_reply(request.question)


CannedReply = Annotated[str | None, Depends(canned_dependency)]


def store_dependency(reply: CannedReply) -> VectorStore | None:
    return None if reply is not None else get_vector_store()


def embedder_dependency(reply: CannedReply) -> Embedder | None:
    return None if reply is not None else get_embedder()


def llm_dependency(reply: CannedReply) -> LLMClient | None:
    """LLM ayarlanmamışsa istek 503 ve kurulum yönergesiyle reddedilir (anahtar yokken uygulama yine açılır)."""
    if reply is not None:
        return None
    try:
        return get_llm()
    except LLMNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None


@router.post("/chat")
def chat(
    request: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    reply: CannedReply,
    store: Annotated[VectorStore | None, Depends(store_dependency)],
    embedder: Annotated[Embedder | None, Depends(embedder_dependency)],
    llm: Annotated[LLMClient | None, Depends(llm_dependency)],
) -> ChatResponse:
    """Kullanıcının yetkili olduğu belgelerden kaynaklı cevap; kanıt yoksa sabit ret cevabı."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Soru boş olamaz.")
    conversation = get_owned(db, user, str(request.conversation_id)) if request.conversation_id else None
    history = safe_history(db, user, conversation) if conversation else []
    if reply is not None:
        result = ChatResult(
            answer=reply, sources=[], no_evidence=False, retrieval_ms=0, generation_ms=0,
        )
        response_type = "canned"
    else:
        assert store is not None and embedder is not None and llm is not None
        settings = get_settings()
        result = answer_question(
            db, store, embedder, llm, user, question,
            top_k=settings.retrieval_top_k,
            min_score=settings.retrieval_min_score,
            history=history,
        )
        response_type = "rag"
    saved = append_exchange(db, user, conversation, question, result, response_type)
    return ChatResponse.model_validate({
        "answer": result.answer, "sources": result.sources, "no_evidence": result.no_evidence,
        "retrieval_ms": result.retrieval_ms, "generation_ms": result.generation_ms,
        "response_type": response_type, "conversation_id": saved.id,
    })
