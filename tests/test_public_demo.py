"""Herkese açık demo korumaları: istek sınırları, ayrı admin parolası ve ziyaretçi verisinin sıfırlanması."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.limits import get_limiters
from app.core.config import get_settings
from app.core.rate_limit import RateLimiter
from app.core.security import hash_password, verify_password
from app.db.models import Conversation, ConversationMessage, Document, SupportTicket, User
from scripts.reset_demo import reset_demo
from scripts.seed_users import seed_users
from tests.helpers import auth_header


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_blocks_within_the_window_and_recovers_after_it() -> None:
    clock = FakeClock()
    limiter = RateLimiter(2, 60, clock=clock)

    assert limiter.hit("k") is None and limiter.hit("k") is None
    assert limiter.hit("k") == 60
    assert limiter.hit("other") is None  # anahtarlar birbirinden bağımsız
    clock.now += 30
    assert limiter.hit("k") == 30
    clock.now += 31
    assert limiter.hit("k") is None


def limits(monkeypatch: pytest.MonkeyPatch, **values: int) -> None:
    for name, value in values.items():
        monkeypatch.setattr(get_settings(), name, value)
    get_limiters.cache_clear()


def say_hello(client: TestClient, user: User):  # pyright: ignore[reportMissingReturnType]
    return client.post("/chat", json={"question": "merhaba"}, headers=auth_header(user))


def test_chat_is_limited_per_user_with_retry_after(
    client: TestClient, users: dict[str, User], monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits(monkeypatch, chat_limit_per_user_per_minute=2, chat_limit_global_per_minute=100)

    assert [say_hello(client, users["it"]).status_code for _ in range(2)] == [200, 200]
    blocked = say_hello(client, users["it"])
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert "saniye sonra" in blocked.json()["detail"]
    assert say_hello(client, users["hr"]).status_code == 200  # başka kullanıcı etkilenmez


def test_chat_has_a_global_limit_across_users(
    client: TestClient, users: dict[str, User], monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits(monkeypatch, chat_limit_per_user_per_minute=100, chat_limit_global_per_minute=3)

    codes = [say_hello(client, users[name]).status_code for name in ("it", "hr", "finance", "admin")]

    assert codes == [200, 200, 200, 429]


def test_unauthenticated_chat_is_rejected_before_counting(
    client: TestClient, users: dict[str, User], monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits(monkeypatch, chat_limit_per_user_per_minute=100, chat_limit_global_per_minute=1)

    assert client.post("/chat", json={"question": "merhaba"}).status_code == 401
    assert say_hello(client, users["it"]).status_code == 200  # 401 alan istek genel kotayı yemedi


def test_login_is_limited_per_email_even_with_the_right_password(
    client: TestClient, session: Session, users: dict[str, User], monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits(monkeypatch, login_limit_per_email_per_minute=3)
    users["it"].password_hash = hash_password("dogru-parola")
    session.commit()

    def login(email: str, password: str) -> int:
        return client.post("/auth/login", data={"username": email, "password": password}).status_code

    assert [login("it@test.local", "yanlis") for _ in range(3)] == [401, 401, 401]
    assert login("IT@test.local ", "dogru-parola") == 429  # büyük harf/boşlukla sınır aşılamaz
    assert login("hr@test.local", "yanlis") == 401  # diğer hesaplar etkilenmez


def test_admin_gets_its_own_password_and_an_old_shared_one_is_replaced(session: Session) -> None:
    seed_users(session, "uye-parolasi")  # eski kurulum: admin de ortak parolayla
    seed_users(session, "uye-parolasi", "gizli-admin-parolasi")

    found = {user.email: user for user in session.scalars(select(User))}
    assert verify_password("gizli-admin-parolasi", found["admin@demo.local"].password_hash)
    assert not verify_password("uye-parolasi", found["admin@demo.local"].password_hash)
    assert verify_password("uye-parolasi", found["it@demo.local"].password_hash)


def test_reset_removes_visitor_data_but_keeps_users_and_documents(
    client: TestClient, session: Session, users: dict[str, User],
) -> None:
    conversation_id = say_hello(client, users["it"]).json()["conversation_id"]
    client.post(
        "/support-tickets", json={"subject": "VPN", "description": "Denendi.", "conversation_id": conversation_id},
        headers=auth_header(users["it"]),
    )
    users_before = session.scalar(select(func.count()).select_from(User))
    documents_before = session.scalar(select(func.count()).select_from(Document))

    counts = reset_demo(session)

    assert counts == {"support_tickets": 1, "conversation_messages": 2, "conversations": 1}
    for model in (SupportTicket, ConversationMessage, Conversation):
        assert session.scalar(select(func.count()).select_from(model)) == 0
    assert session.scalar(select(func.count()).select_from(User)) == users_before
    assert session.scalar(select(func.count()).select_from(Document)) == documents_before
