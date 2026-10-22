"""Herkese açık demoda ziyaretçi verisini temizler: sohbetler, mesajlar ve destek talepleri.

Kullanıcılara ve belgelere dokunmaz. Sunucuda günlük çalıştırılır (docs/deploy-oracle.md):

    docker compose exec app python -m scripts.reset_demo
"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Conversation, ConversationMessage, SupportTicket
from app.db.session import SessionLocal, init_db


def reset_demo(session: Session) -> dict[str, int]:
    """Silinen satır sayılarını döndürür. Talepler sohbete bağlı olduğu için önce onlar silinir."""
    counts: dict[str, int] = {}
    for model in (SupportTicket, ConversationMessage, Conversation):
        counts[model.__tablename__] = session.scalar(select(func.count()).select_from(model)) or 0
        session.execute(delete(model))
    session.commit()
    return counts


def main() -> None:
    init_db()
    with SessionLocal() as session:
        counts = reset_demo(session)
    print(", ".join(f"{name}: {count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()
