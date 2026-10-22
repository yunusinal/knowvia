"""Destek talepleri: yalnızca kullanıcının açık isteğiyle oluşturulur, sahibine (ve admin'e) görünür."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import SupportTicket, User
from app.db.session import get_db
from app.schemas.tickets import TicketCreate, TicketOut
from app.services.conversations import get_owned
from app.services.tickets import create_ticket, visible_tickets

router = APIRouter(prefix="/support-tickets", tags=["support-tickets"])


def _out(ticket: SupportTicket, email: str) -> TicketOut:
    return TicketOut(
        id=ticket.id, subject=ticket.subject, description=ticket.description, status=ticket.status.value,
        created_by_email=email, conversation_id=ticket.conversation_id, created_at=ticket.created_at,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create(
    request: TicketCreate,
    user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)],
) -> TicketOut:
    subject, description = request.subject.strip(), request.description.strip()
    if len(subject) < 3 or not description:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Konu ve açıklama boş olamaz.")
    # Başkasının sohbetine bağlanamaz; sohbet yoksa veya başkasınınsa 404.
    conversation = get_owned(db, user, str(request.conversation_id)) if request.conversation_id else None
    ticket = create_ticket(db, user, subject, description, conversation)
    return _out(ticket, user.email)


@router.get("")
def list_tickets(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)],
) -> list[TicketOut]:
    return [_out(ticket, email) for ticket, email in visible_tickets(db, user)]
