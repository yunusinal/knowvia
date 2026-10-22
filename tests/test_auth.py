from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import Department, Role, User

PASSWORD = "correct-password"


@pytest.fixture
def it_user(session: Session) -> User:
    user = User(
        email="it@demo.local",
        password_hash=hash_password(PASSWORD),
        role=Role.MEMBER,
        department=Department.IT,
    )
    session.add(user)
    session.commit()
    return user


def login(client: TestClient, email: str, password: str):
    # OAuth2 standardı gereği alan adı "username"; içine e-posta yazılır.
    return client.post("/auth/login", data={"username": email, "password": password})


def test_login_success_returns_token(client: TestClient, it_user: User) -> None:
    response = login(client, "it@demo.local", PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password_is_rejected(client: TestClient, it_user: User) -> None:
    response = login(client, "it@demo.local", "wrong-password")

    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_inactive_user_cannot_login(
    client: TestClient, session: Session, it_user: User
) -> None:
    it_user.is_active = False
    session.commit()

    response = login(client, "it@demo.local", PASSWORD)

    assert response.status_code == 401


def test_me_returns_current_user_without_password_hash(
    client: TestClient, it_user: User
) -> None:
    token = login(client, "it@demo.local", PASSWORD).json()["access_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {
        "id": it_user.id,
        "email": "it@demo.local",
        "role": "member",
        "department": "IT",
    }


def test_me_without_token_is_rejected(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_with_tampered_token_is_rejected(client: TestClient, it_user: User) -> None:
    token = login(client, "it@demo.local", PASSWORD).json()["access_token"]
    # Token'ın imza kısmının son karakterini değiştir.
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"})

    assert response.status_code == 401


def test_me_with_expired_token_is_rejected(client: TestClient, it_user: User) -> None:
    expired = jwt.encode(
        {"sub": it_user.id, "exp": datetime.now(UTC) - timedelta(minutes=1)},
        get_settings().jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


def test_deactivated_user_token_is_rejected(
    client: TestClient, session: Session, it_user: User
) -> None:
    # Token alındıktan sonra hesap pasif yapılırsa eski token da çalışmamalı.
    token = login(client, "it@demo.local", PASSWORD).json()["access_token"]
    it_user.is_active = False
    session.commit()

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_unknown_email_gets_same_error(client: TestClient, it_user: User) -> None:
    # Cevaplar farklı olsaydı saldırgan hangi e-postaların kayıtlı olduğunu öğrenirdi.
    wrong_password = login(client, "it@demo.local", "wrong-password")
    unknown_email = login(client, "nobody@demo.local", "wrong-password")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
