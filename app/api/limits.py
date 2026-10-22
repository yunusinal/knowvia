"""İstek sınırlarının API'ye bağlandığı yer: aşılırsa 429 ve Retry-After başlığı döner."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.rate_limit import RateLimiter
from app.db.models import User

WINDOW_SECONDS = 60


@dataclass(frozen=True)
class Limiters:
    chat_per_user: RateLimiter
    chat_global: RateLimiter
    login_per_email: RateLimiter


@lru_cache
def get_limiters() -> Limiters:
    settings = get_settings()
    return Limiters(
        chat_per_user=RateLimiter(settings.chat_limit_per_user_per_minute, WINDOW_SECONDS),
        chat_global=RateLimiter(settings.chat_limit_global_per_minute, WINDOW_SECONDS),
        login_per_email=RateLimiter(settings.login_limit_per_email_per_minute, WINDOW_SECONDS),
    )


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Çok fazla istek gönderildi; {retry_after} saniye sonra tekrar deneyin.",
        headers={"Retry-After": str(retry_after)},
    )


def enforce_chat_limit(user: Annotated[User, Depends(get_current_user)]) -> None:
    """Önce kullanıcı, sonra tüm sistem için sınır; kimlik doğrulamadan sonra çalışır."""
    limiters = get_limiters()
    for limiter, key in ((limiters.chat_per_user, f"user:{user.id}"), (limiters.chat_global, "global")):
        retry_after = limiter.hit(key)
        if retry_after is not None:
            raise _too_many(retry_after)


def enforce_login_limit(email: str) -> None:
    """E-posta başına deneme sınırı: gizli admin parolasına deneme-yanılmayı yavaşlatır."""
    retry_after = get_limiters().login_per_email.hit(f"login:{email.strip().lower()}")
    if retry_after is not None:
        raise _too_many(retry_after)
