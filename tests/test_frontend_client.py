import json

import httpx2
import pytest

from frontend.api_client import ApiError, KnowviaClient, SessionExpiredError

BASE = "http://api.test"


def client_with(handler, token: str | None = "tok") -> KnowviaClient:  # pyright: ignore[reportMissingParameterType]
    return KnowviaClient(BASE, token, transport=httpx2.MockTransport(handler))


def test_login_sends_oauth2_form_and_returns_token() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers.get("authorization", "")
        return httpx2.Response(200, json={"access_token": "jwt-123", "token_type": "bearer"})

    token = client_with(handler, token=None).login("it@demo.local", "secret")

    assert token == "jwt-123"
    assert seen["path"] == "/auth/login"
    assert "username=it%40demo.local" in seen["body"] and "password=secret" in seen["body"]
    assert seen["auth"] == ""  # girişte token gönderilmez


def test_requests_carry_bearer_token_and_chat_sends_json() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"answer": "a", "sources": [], "no_evidence": False})

    client_with(handler).chat("VPN nasıl kurulur?", ["VPN bağlanmıyor"])

    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"question": "VPN nasıl kurulur?", "history": ["VPN bağlanmıyor"]}


def test_upload_sends_multipart_with_department_and_visibility() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["type"] = request.headers["content-type"]
        seen["body"] = request.content.decode(errors="ignore")
        return httpx2.Response(201, json={"id": "d1", "filename": "a.md", "chunk_count": 1})

    client_with(handler).upload_document("a.md", b"# Baslik", "IT", "company")

    assert seen["type"].startswith("multipart/form-data")
    assert 'name="department"' in seen["body"] and "IT" in seen["body"]
    assert 'filename="a.md"' in seen["body"]


def test_401_with_token_means_session_expired() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"detail": "Kimlik doğrulanamadı."})

    with pytest.raises(SessionExpiredError):
        client_with(handler).me()


def test_failed_login_shows_api_message_not_session_expired() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"detail": "E-posta veya parola hatalı."})

    with pytest.raises(ApiError) as exc_info:
        client_with(handler, token=None).login("x@demo.local", "wrong")

    assert not isinstance(exc_info.value, SessionExpiredError)
    assert exc_info.value.message == "E-posta veya parola hatalı."


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (403, {"detail": "Bu işlem için yetkiniz yok."}, "Bu işlem için yetkiniz yok."),
        (415, {"detail": "Yalnızca PDF, TXT ve MD dosyaları desteklenir."}, "Yalnızca PDF, TXT ve MD dosyaları desteklenir."),
        (422, {"detail": [{"msg": "field required"}]}, "Geçersiz istek; girdiğiniz değerleri kontrol edin."),
        (500, {}, "Beklenmeyen bir hata oluştu (HTTP 500)."),
    ],
)
def test_error_responses_become_readable_messages(status: int, payload: dict[str, object], expected: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=payload)

    with pytest.raises(ApiError) as exc_info:
        client_with(handler).list_documents()

    assert exc_info.value.message == expected
    assert exc_info.value.status_code == status


def test_unreachable_server_gives_clear_message() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(ApiError, match="Sunucuya ulaşılamıyor"):
        client_with(handler).list_documents()
