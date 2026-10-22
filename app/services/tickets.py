"""Destek talebi (master plan US-07): model yalnızca önerir, talebi kullanıcı onaylayınca uygulama açar.

Araç çağrısı hiçbir zaman kendiliğinden kayıt oluşturmaz. Belge metni de modeli "talep aç" diye
yönlendirebileceği için öneri kullanıcıya gösterilir; kullanıcı konuyu ve açıklamayı görüp düzenledikten
sonra ayrı bir istekle onaylar.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Role, SupportTicket, User
from app.services.llm import ToolCall

MAX_SUBJECT_CHARS = 120
MAX_DESCRIPTION_CHARS = 2000
TOOL_NAME = "create_support_ticket"
PROPOSAL_MESSAGE = (
    "Bu sorun için bir destek talebi taslağı hazırladım. Talep yalnızca siz onaylarsanız oluşturulur."
)

SUPPORT_TICKET_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Propose an IT support ticket for the current user. Use it only when the user says the "
            "documented steps did not solve the problem or explicitly asks for a support ticket. "
            "This only drafts the ticket; the user must confirm it in the app."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Short title of the problem, max 120 characters."},
                "description": {
                    "type": "string",
                    "description": "What the problem is and which steps the user already tried.",
                },
            },
            "required": ["subject", "description"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class TicketProposal:
    subject: str
    description: str


def proposal_from(call: ToolCall | None) -> TicketProposal | None:
    """Modelin araç çağrısını doğrular; beklenmeyen ad veya boş alan varsa öneri yok sayılır."""
    if call is None or call.name != TOOL_NAME:
        return None
    subject, description = call.arguments.get("subject"), call.arguments.get("description")
    if not isinstance(subject, str) or not isinstance(description, str):
        return None
    subject, description = subject.strip()[:MAX_SUBJECT_CHARS], description.strip()[:MAX_DESCRIPTION_CHARS]
    if not subject or not description:
        return None
    return TicketProposal(subject=subject, description=description)


def create_ticket(
    db: Session, user: User, subject: str, description: str, conversation: Conversation | None,
) -> SupportTicket:
    ticket = SupportTicket(
        created_by=user.id, subject=subject, description=description,
        conversation_id=conversation.id if conversation else None,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def visible_tickets(db: Session, user: User) -> list[tuple[SupportTicket, str]]:
    """Üye yalnızca kendi taleplerini, admin tüm talepleri görür; talep sahibinin e-postasıyla döner."""
    query = select(SupportTicket, User.email).join(User, SupportTicket.created_by == User.id)
    if user.role != Role.ADMIN:
        query = query.where(SupportTicket.created_by == user.id)
    rows = db.execute(query.order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc()))
    return [(ticket, email) for ticket, email in rows]
