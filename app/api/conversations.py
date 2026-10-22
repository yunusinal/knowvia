"""Yalnızca oturum sahibinin konuşmalarını gösteren uçlar."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.conversations import ConversationOut, MessageOut
from app.services.conversations import get_owned, list_owned, visible_messages

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)],
) -> list[ConversationOut]:
    return [ConversationOut.model_validate(item) for item in list_owned(db, user)]


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages(
    conversation_id: UUID,
    user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)],
) -> list[MessageOut]:
    conversation = get_owned(db, user, str(conversation_id))
    return [MessageOut.model_validate(item) for item in visible_messages(db, user, conversation)]
