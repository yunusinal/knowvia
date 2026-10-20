"""Testlerde ortak kullanılan küçük yardımcılar."""

from app.core.security import create_access_token
from app.db.models import User


def auth_header(user: User) -> dict[str, str]:
    """Login adımını atlayıp kullanıcı için geçerli bir Bearer başlığı üretir."""
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
