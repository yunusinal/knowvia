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
    documents_error: ApiError | None = None
    documents: list[dict[str, Any]] = field(default_factory=lambda: [DOCUMENT.copy()])
    deleted: list[str] = field(default_factory=list)
    uploads: list[tuple[str, str, str]] = field(default_factory=list)
    chat_requests: list[tuple[str, str | None]] = field(default_factory=list)
    conversations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    tickets: list[dict[str, Any]] = field(default_factory=list)


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
        if backend.documents_error is not None:
            raise backend.documents_error
        return backend.documents

    def list_conversations(self) -> list[dict[str, Any]]:
        return [{"id": key, "title": values[0]["content"][:80]} for key, values in backend.conversations.items()]

    def get_conversation_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return backend.conversations[conversation_id]

    def chat(self, question: str, conversation_id: str | None = None) -> dict[str, Any]:
        if backend.chat_error is not None:
            raise backend.chat_error
        backend.chat_requests.append((question, conversation_id))
        conversation_id = conversation_id or f"00000000-0000-4000-8000-{len(backend.conversations) + 1:012d}"
        result = {**backend.chat_result, "conversation_id": conversation_id}
        backend.conversations.setdefault(conversation_id, []).extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": result["answer"], "sources": result["sources"],
             "no_evidence": result["no_evidence"], "retrieval_ms": result["retrieval_ms"],
             "generation_ms": result["generation_ms"], "response_type": result.get("response_type", "rag")},
        ])
        return result

    def create_ticket(self, subject: str, description: str, conversation_id: str | None = None) -> dict[str, Any]:
        assert self.token is not None
        ticket = {"id": f"t{len(backend.tickets) + 1}", "subject": subject, "description": description,
                  "status": "open", "created_by_email": self.token.removeprefix("token:"),
                  "conversation_id": conversation_id, "created_at": "2026-10-22T10:00:00+00:00"}
        backend.tickets.append(ticket)
        return ticket

    def list_tickets(self) -> list[dict[str, Any]]:
        assert self.token is not None
        email = self.token.removeprefix("token:")
        if USERS[email]["role"] == "admin":
            return backend.tickets
        return [ticket for ticket in backend.tickets if ticket["created_by_email"] == email]

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


def test_landing_page_with_login_is_shown_first() -> None:
    at = app()

    assert not at.exception
    assert at.title[0].value == "Knowvia"
    assert [t.label for t in at.text_input] == ["E-posta", "Parola"]
    assert len(at.chat_input) == 0  # giriş yapmadan sohbet yok
    assert [h.value for h in at.header] == ["Neden Knowvia?", "Nasıl çalışır?"]
    assert "Sızıntısız ret" in texts(at)
    github = at.get("link_button")[0]
    assert github.proto.url == "https://github.com/yunusinal/knowvia"  # pyright: ignore[reportAttributeAccessIssue]


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
    sidebar = "\n".join(m.value for m in at.sidebar.markdown)
    assert "it@demo.local" in sidebar
    assert ":blue-badge[:material/person: Üye]" in sidebar  # rol rozeti
    assert ":gray-badge[:material/apartment: IT]" in sidebar  # departman rozeti


def test_empty_chat_offers_example_questions_that_disappear_after_asking() -> None:
    at = logged_in("it@demo.local")
    assert len(at.get("button_group")) == 1  # örnek soru düğmeleri (st.pills)

    at.get("button_group")[0].set_value(":violet[:material/vpn_key:] VPN hatası").run()  # pyright: ignore[reportAttributeAccessIssue]

    assert "Cihaz saatini kontrol edin. [S1]" in texts(at)
    assert at.session_state["messages"][0]["content"].startswith("VPN 'sertifika doğrulanamadı'")
    assert len(at.get("button_group")) == 0  # sohbet başlayınca örnekler kaybolur


def test_sidebar_counts_only_active_documents() -> None:
    backend.documents.append({**DOCUMENT, "id": "d2", "status": "failed"})
    at = logged_in("admin@demo.local")

    assert not at.exception
    assert "1 aktif belge erişiminize açık." in texts(at)


def test_document_count_failure_keeps_chat_available_without_showing_zero() -> None:
    backend.documents_error = ApiError("API'ye bağlanılamadı.")
    at = logged_in("it@demo.local")

    assert not at.exception
    assert len(at.chat_input) == 1
    assert "Belge sayısı alınamadı: API'ye bağlanılamadı." in texts(at)
    assert "0 aktif belge" not in texts(at)


def test_expired_session_during_document_count_returns_to_login() -> None:
    backend.documents_error = SessionExpiredError("Oturumunuzun süresi doldu; lütfen tekrar giriş yapın.", 401)
    at = logged_in("it@demo.local")

    assert not at.exception
    assert "token" not in at.session_state
    assert "messages" not in at.session_state
    assert at.info[0].value == "Oturumunuzun süresi doldu; lütfen tekrar giriş yapın."


def test_answer_shows_response_time() -> None:
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("VPN sertifika hatası").run()

    assert "0.0 sn · arama 1 ms · dil modeli 1 ms" in texts(at)


def test_follow_up_sends_conversation_id_without_history() -> None:
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("VPN sertifika hatası").run()
    at.chat_input[0].set_value("Peki bunun istisnası ne?").run()

    assert backend.chat_requests == [
        ("VPN sertifika hatası", None),
        ("Peki bunun istisnası ne?", "00000000-0000-4000-8000-000000000001"),
    ]


def test_new_chat_starts_separate_conversation() -> None:
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("VPN sertifika hatası").run()
    next(button for button in at.button if button.label == "Yeni sohbet").click().run()
    assert at.session_state["conversation_id"] is None
    at.chat_input[0].set_value("Yıllık izin nedir?").run()

    assert backend.chat_requests == [("VPN sertifika hatası", None), ("Yıllık izin nedir?", None)]
    assert len(backend.conversations) == 2
    assert at.session_state["conversation_id"] == "00000000-0000-4000-8000-000000000002"


def test_canned_reply_has_no_source_card_or_search_timing_even_after_rerun() -> None:
    backend.chat_result = {
        "answer": "Merhaba! Nasıl yardımcı olabilirim?", "sources": [], "no_evidence": False,
        "retrieval_ms": 0, "generation_ms": 0, "response_type": "canned",
    }
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("selam").run()
    at.run()

    assert not at.exception
    assert "Merhaba! Nasıl yardımcı olabilirim?" in texts(at)
    assert not at.info
    assert not at.expander
    assert " ms" not in texts(at)
    assert at.session_state["messages"][-1]["response_type"] == "canned"


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


PROPOSAL_RESULT = {
    "answer": "Bu sorun için bir destek talebi taslağı hazırladım. Talep yalnızca siz onaylarsanız oluşturulur.",
    "sources": [], "no_evidence": False, "retrieval_ms": 1, "generation_ms": 1,
    "ticket_proposal": {"subject": "VPN sertifika hatası", "description": "Saat ve önbellek denendi."},
}


def proposal_shown(at: AppTest) -> bool:
    return any(button.label == "Talebi oluştur" for button in at.button)


def test_ticket_proposal_is_created_only_after_confirmation_with_user_edits() -> None:
    backend.chat_result = PROPOSAL_RESULT.copy()
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("Hâlâ çalışmıyor, talep açar mısın?").run()

    assert proposal_shown(at)
    assert backend.tickets == []  # taslak kendiliğinden kayıt olmaz
    next(t for t in at.text_input if t.label == "Konu").set_value("VPN hâlâ bağlanmıyor")
    next(button for button in at.button if button.label == "Talebi oluştur").click().run()

    assert [ticket["subject"] for ticket in backend.tickets] == ["VPN hâlâ bağlanmıyor"]
    assert backend.tickets[0]["conversation_id"] == "00000000-0000-4000-8000-000000000001"
    assert at.success[0].value == "Destek talebi oluşturuldu: VPN hâlâ bağlanmıyor"
    assert not proposal_shown(at)


def test_cancelled_proposal_creates_nothing() -> None:
    backend.chat_result = PROPOSAL_RESULT.copy()
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("Talep açar mısın?").run()
    next(button for button in at.button if button.label == "Vazgeç").click().run()

    assert backend.tickets == []
    assert not proposal_shown(at)


def test_next_question_discards_an_unconfirmed_proposal() -> None:
    backend.chat_result = PROPOSAL_RESULT.copy()
    at = logged_in("it@demo.local")
    at.chat_input[0].set_value("Talep açar mısın?").run()
    backend.chat_result = FakeBackend().chat_result
    at.chat_input[0].set_value("VPN sertifika hatası").run()

    assert not proposal_shown(at)


def test_tickets_page_shows_own_tickets_and_admin_sees_owners() -> None:
    backend.tickets = [
        {"id": "t1", "subject": "IT talebi", "description": "Ayrıntı", "status": "open",
         "created_by_email": "it@demo.local", "conversation_id": None, "created_at": "2026-10-22T10:00:00+00:00"},
    ]
    member = logged_in("it@demo.local")
    member.switch_page("views/tickets.py").run()
    assert "**IT talebi**" in texts(member)
    assert "it@demo.local" not in [c.value for c in member.caption]

    admin = logged_in("admin@demo.local")
    admin.switch_page("views/tickets.py").run()
    assert "22.10.2026 10:00 · it@demo.local" in [c.value for c in admin.caption]


def test_tickets_page_explains_empty_state() -> None:
    at = logged_in("it@demo.local")
    at.switch_page("views/tickets.py").run()

    assert "Henüz destek talebi yok" in at.info[0].value
