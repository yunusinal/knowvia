"""Arayüz testleri (Streamlit AppTest): tarayıcı, sunucu, model veya LLM gerekmez.

API istemcisi sahte bir istemciyle değiştirilir; arayüzün doğru ekranları, mesajları ve
oturum davranışını gösterdiği test edilir. Yetki kararları API'dedir ve orada ayrıca test edilir.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from frontend import api_client
from frontend.api_client import ApiError, SessionExpiredError

APP = Path(__file__).resolve().parents[1] / "frontend" / "streamlit_app.py"
PASSWORD = "demo-pw"

USERS = {
    "admin@demo.local": {"id": "u1", "email": "admin@demo.local", "role": "admin", "department": None},
    "it@demo.local": {"id": "u2", "email": "it@demo.local", "role": "member", "department": "IT"},
}
DOCUMENT = {
    "id": "d1", "filename": "vpn-setup.md", "department": "IT", "visibility": "company",
    "status": "active", "chunk_count": 3, "created_at": "2026-10-22T10:00:00Z",
}


@dataclass
class FakeBackend:
    chat_result: dict[str, Any] = field(default_factory=lambda: {
        "answer": "Cihaz saatini kontrol edin. [S1]",
        "sources": [{"source_id": "S1", "document_id": "d1", "filename": "vpn-troubleshooting.md",
                     "page_number": None, "chunk_id": "c1", "snippet": "Sertifika doğrulanamadı hatasında…"}],
        "no_evidence": False, "retrieval_ms": 1, "generation_ms": 1,
    })
    chat_error: ApiError | None = None
    deleted: list[str] = field(default_factory=list)
    uploads: list[tuple[str, str, str]] = field(default_factory=list)


backend = FakeBackend()


class FakeKnowviaClient:
    def __init__(self, base_url: str, token: str | None = None, **_: object) -> None:
        self.token = token

    def login(self, email: str, password: str) -> str:
        if email not in USERS or password != PASSWORD:
            raise ApiError("E-posta veya parola hatalı.", 401)
        return f"token:{email}"

    def me(self) -> dict[str, Any]:
        assert self.token is not None
        return USERS[self.token.removeprefix("token:")]

    def list_documents(self) -> list[dict[str, Any]]:
        return [DOCUMENT]

    def chat(self, question: str) -> dict[str, Any]:
        if backend.chat_error is not None:
            raise backend.chat_error
        return backend.chat_result

    def delete_document(self, document_id: str) -> dict[str, Any]:
        backend.deleted.append(document_id)
        return {**DOCUMENT, "status": "deleted"}

    def upload_document(self, filename: str, content: bytes, department: str, visibility: str) -> dict[str, Any]:
        backend.uploads.append((filename, department, visibility))
        return {**DOCUMENT, "filename": filename}


@pytest.fixture(autouse=True)
def fake_api(monkeypatch: pytest.MonkeyPatch) -> None:
    global backend
    backend = FakeBackend()
    monkeypatch.setattr(api_client, "KnowviaClient", FakeKnowviaClient)


def app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=30).run()


def logged_in(email: str) -> AppTest:
    at = app()
    at.text_input[0].set_value(email)
    at.text_input[1].set_value(PASSWORD)
    at.button[0].click().run()
    return at


def texts(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [t.value for t in at.text]
    parts += [e.value for e in at.info] + [e.value for e in at.error] + [e.value for e in at.sidebar.markdown]
    parts += [c.value for c in at.sidebar.caption]
    return "\n".join(str(p) for p in parts)


def test_login_screen_is_shown_first() -> None:
    at = app()

    assert not at.exception
    assert at.title[0].value == "Knowvia"
    assert [t.label for t in at.text_input] == ["E-posta", "Parola"]
    assert len(at.chat_input) == 0  # giriş yapmadan sohbet yok


def test_wrong_password_shows_error_and_stays_on_login() -> None:
    at = app()
    at.text_input[0].set_value("it@demo.local")
    at.text_input[1].set_value("wrong")
    at.button[0].click().run()

    assert at.error[0].value == "E-posta veya parola hatalı."
    assert "token" not in at.session_state


def test_login_opens_chat_with_user_in_sidebar() -> None:
    at = logged_in("it@demo.local")

    assert not at.exception
    assert len(at.chat_input) == 1
    sidebar = texts(at)
    assert "it@demo.local" in sidebar and "Rol: member" in sidebar and "Departman: IT" in sidebar


def test_chat_answer_shows_source_cards() -> None:
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("VPN sertifika hatası").run()

    content = texts(at)
    assert "Cihaz saatini kontrol edin. [S1]" in content
    assert "**[S1] vpn-troubleshooting.md**" in content
    assert "Sertifika doğrulanamadı hatasında…" in content


def test_no_evidence_answer_is_shown_as_info_without_sources() -> None:
    backend.chat_result = {"answer": "Yetkiniz dahilindeki belgelerde bu soruya yeterli bilgi bulamadım.",
                           "sources": [], "no_evidence": True, "retrieval_ms": 1, "generation_ms": 0}
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("Bütçe ne kadar?").run()

    assert at.info[-1].value == "Yetkiniz dahilindeki belgelerde bu soruya yeterli bilgi bulamadım."
    assert "[S1]" not in texts(at)


def test_api_error_is_shown_in_chat() -> None:
    backend.chat_error = ApiError("Dil modeli şu anda kullanılamıyor; tekrar deneyin.", 503)
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("VPN?").run()

    assert at.error[-1].value == "Dil modeli şu anda kullanılamıyor; tekrar deneyin."


def test_expired_session_returns_to_login_with_notice() -> None:
    backend.chat_error = SessionExpiredError("Oturumunuzun süresi doldu; lütfen tekrar giriş yapın.", 401)
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("VPN?").run()

    assert "token" not in at.session_state
    assert at.info[0].value == "Oturumunuzun süresi doldu; lütfen tekrar giriş yapın."
    assert [t.label for t in at.text_input] == ["E-posta", "Parola"]


def test_logout_clears_the_session() -> None:
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("VPN?").run()
    at.sidebar.button[0].click().run()

    assert "token" not in at.session_state
    assert "messages" not in at.session_state  # sohbet geçmişi de silinir
    assert at.info[0].value == "Çıkış yapıldı."


def test_member_sees_documents_but_no_admin_controls() -> None:
    at = logged_in("it@demo.local").switch_page("views/documents.py").run()

    assert not at.exception
    assert len(at.dataframe) == 1
    assert len(at.selectbox) == 0  # yükleme/silme formları yok (asıl engel API'nin 403'ü)


def test_admin_sees_upload_and_delete_and_can_delete_with_confirmation() -> None:
    at = logged_in("admin@demo.local").switch_page("views/documents.py").run()
    labels = [s.label for s in at.selectbox]
    assert labels == ["Departman", "Görünürlük", "Silinecek belge"]

    delete_button = next(b for b in at.button if b.label == "Sil")
    delete_button.click().run()
    assert at.error[0].value == "Silmek için onay kutusunu işaretleyin."
    assert backend.deleted == []

    at.checkbox[0].check()
    next(b for b in at.button if b.label == "Sil").click().run()
    assert backend.deleted == ["d1"]
    assert at.info[0].value == "vpn-setup.md silindi."


def test_frontend_never_uses_shared_streamlit_caches() -> None:
    # Paylaşılan önbellekte bir kullanıcının cevabı başka bir kullanıcıya görünebilir (master plan §6).
    # Açıklama metinlerindeki adlar değil, gerçek kullanım (çağrı veya dekoratör) aranır.
    sources = "\n".join(p.read_text(encoding="utf-8") for p in APP.parent.rglob("*.py"))

    assert re.search(r"@st\.cache|st\.cache_(data|resource)\s*\(", sources) is None
