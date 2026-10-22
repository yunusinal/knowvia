"""Kullanıcıya ait konuşmaları saklar; geçmiş yanıtları güncel belge yetkisiyle süzer."""

from dataclasses import asdict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, ConversationMessage, ConversationRole, User, _utc_now
from app.services.authorization import allowed_document_ids
from app.services.chat import ChatResult, NO_EVIDENCE_MESSAGE
from app.services.prompt import HistoryTurn


def get_owned(db: Session, user: User, conversation_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id)
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı.")
    return conversation


def list_owned(db: Session, user: User) -> list[Conversation]:
    return list(db.scalars(
        select(Conversation).where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    ))


def messages(db: Session, conversation: Conversation) -> list[ConversationMessage]:
    return list(db.scalars(
        select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.id)
    ))


def _authorized_answer(message: ConversationMessage, allowed: set[str]) -> bool:
    """Cevabın dayandığı her belge (atıf yapılan + modele verilen) hâlâ yetkili mi; şüphede hayır."""
    if message.role != ConversationRole.ASSISTANT:
        return True
    document_ids: list[object] = [
        source.get("document_id") if isinstance(source, dict) else None for source in message.sources
    ]
    document_ids.extend(message.context_document_ids or [])
    if message.response_type == "rag" and not message.no_evidence and not document_ids:
        return False  # kanıtlı cevap belgesiz kaydedilmişse kaynağı doğrulanamaz
    return all(isinstance(document_id, str) and document_id in allowed for document_id in document_ids)


def _useful_for_context(answer: ConversationMessage) -> bool:
    # Ret mesajı ve hazır sohbet cevabı takip sorusunu çözmeye yardım etmez; aramayı ve bütçeyi kirletir.
    return not answer.no_evidence and answer.response_type != "canned"


def safe_history(db: Session, user: User, conversation: Conversation) -> list[HistoryTurn]:
    allowed = allowed_document_ids(db, user)
    records = messages(db, conversation)
    history: list[HistoryTurn] = []
    for question, answer in zip(records[::2], records[1::2], strict=False):
        if question.role != ConversationRole.USER or answer.role != ConversationRole.ASSISTANT:
            continue
        if _useful_for_context(answer) and _authorized_answer(answer, allowed):
            history.extend((HistoryTurn("user", question.content), HistoryTurn("assistant", answer.content)))
    return history


def visible_messages(db: Session, user: User, conversation: Conversation) -> list[dict[str, object]]:
    allowed = allowed_document_ids(db, user)
    result: list[dict[str, object]] = []
    for message in messages(db, conversation):
        authorized = _authorized_answer(message, allowed)
        result.append({
            "role": message.role.value,
            "content": message.content if authorized else NO_EVIDENCE_MESSAGE,
            "sources": message.sources if authorized else [],
            "no_evidence": message.no_evidence if authorized else True,
            "response_type": message.response_type,
            "retrieval_ms": message.retrieval_ms,
            "generation_ms": message.generation_ms,
        })
    return result


def append_exchange(
    db: Session, user: User, conversation: Conversation | None, question: str,
    result: ChatResult, response_type: str,
) -> Conversation:
    if conversation is None:
        conversation = Conversation(user_id=user.id, title=question[:80])
        db.add(conversation)
        db.flush()
    db.add(ConversationMessage(
        conversation_id=conversation.id, role=ConversationRole.USER, content=question,
    ))
    db.add(ConversationMessage(
        conversation_id=conversation.id, role=ConversationRole.ASSISTANT,
        content=result.answer, sources=[asdict(source) for source in result.sources],
        context_document_ids=result.context_document_ids,
        no_evidence=result.no_evidence, response_type=response_type,
        retrieval_ms=result.retrieval_ms, generation_ms=result.generation_ms,
    ))
    conversation.updated_at = _utc_now()
    db.commit()
    db.refresh(conversation)
    return conversation
