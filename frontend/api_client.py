"""Arayüzün backend'e konuştuğu tek yer. Arayüz veritabanına veya Qdrant'a hiç dokunmaz;
yetki kararlarını API verir, arayüz yalnızca JWT taşır."""

from typing import Any

import httpx2

DEFAULT_TIMEOUT_SECONDS = 120  # LLM cevabı birkaç saniye sürebilir


class ApiError(Exception):
    """Kullanıcıya gösterilebilir hata; `message` API'nin kendi açıklamasıdır."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SessionExpiredError(ApiError):
    """Token geçersiz veya süresi dolmuş; kullanıcı yeniden giriş yapmalı."""


class KnowviaClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._transport = transport
        self._timeout = timeout

    def login(self, email: str, password: str) -> str:
        # OAuth2 standardı gereği alan adı "username"; içine e-posta yazılır.
        data = self._request("POST", "/auth/login", data={"username": email, "password": password})
        return data["access_token"]

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/auth/me")

    def list_documents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/documents")

    def upload_document(self, filename: str, content: bytes, department: str, visibility: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/documents",
            files={"file": (filename, content, "application/octet-stream")},
            data={"department": department, "visibility": visibility},
        )

    def delete_document(self, document_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/documents/{document_id}")

    def list_conversations(self) -> list[dict[str, Any]]:
        return self._request("GET", "/conversations")

    def get_conversation_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/conversations/{conversation_id}/messages")

    def chat(self, question: str, conversation_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return self._request("POST", "/chat", json=payload)

    def create_ticket(self, subject: str, description: str, conversation_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"subject": subject, "description": description}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return self._request("POST", "/support-tickets", json=payload)

    def list_tickets(self) -> list[dict[str, Any]]:
        return self._request("GET", "/support-tickets")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            with httpx2.Client(base_url=self._base_url, timeout=self._timeout, transport=self._transport) as client:
                response = client.request(method, path, headers=headers, **kwargs)
        except httpx2.TimeoutException:
            raise ApiError("Sunucu zamanında cevap vermedi; tekrar deneyin.") from None
        except httpx2.TransportError:
            raise ApiError("Sunucuya ulaşılamıyor; API'nin çalıştığından emin olun.") from None

        if response.status_code == 401 and self._token:
            raise SessionExpiredError("Oturumunuzun süresi doldu; lütfen tekrar giriş yapın.", 401)
        if response.status_code >= 400:
            raise ApiError(_error_message(response), response.status_code)
        return response.json()


def _error_message(response: httpx2.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, str) and detail:
        return detail
    if response.status_code == 422:
        return "Geçersiz istek; girdiğiniz değerleri kontrol edin."
    return f"Beklenmeyen bir hata oluştu (HTTP {response.status_code})."
