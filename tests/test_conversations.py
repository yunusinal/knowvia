"""Sunucu geçmişi: sahiplik, yetki geri alma ve bütçeyle seçim."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Department, Document, DocumentStatus, User, Visibility
from app.repositories.vector_store import VectorStore
from app.services.ingest import ingest_document
from tests.fakes import FakeEmbedder, FakeLLM
from tests.helpers import auth_header


@pytest.fixture(autouse=True)
def low_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "retrieval_min_score", 0.1)


def ask(client: TestClient, user: User, question: str, conversation_id: str | None = None):  # pyright: ignore[reportMissingReturnType]
    payload = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return client.post("/chat", json=payload, headers=auth_header(user))


def test_history_persists_and_only_owner_can_read(
    client: TestClient, users: dict[str, User],
) -> None:
    first = ask(client, users["it"], "merhaba")
    conversation_id = first.json()["conversation_id"]
    second = ask(client, users["it"], "teşekkürler", conversation_id)

    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    listing = client.get("/conversations", headers=auth_header(users["it"]))
    assert [item["id"] for item in listing.json()] == [conversation_id]
    history = client.get(f"/conversations/{conversation_id}/messages", headers=auth_header(users["it"]))
    assert [item["role"] for item in history.json()] == ["user", "assistant", "user", "assistant"]
    assert client.get("/conversations", headers=auth_header(users["hr"])).json() == []
    assert client.get(f"/conversations/{conversation_id}/messages", headers=auth_header(users["hr"])).status_code == 404
    assert ask(client, users["hr"], "merhaba", conversation_id).status_code == 404


def test_revoked_source_is_redacted_and_excluded_from_future_prompt(
    client: TestClient, session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder,
    fake_llm: FakeLLM, users: dict[str, User],
) -> None:
    document = ingest_document(
        session, vector_store, fake_embedder, filename="vpn.md",
        content=b"VPN certificate error: check device clock and renew certificate.",
        department=Department.IT, visibility=Visibility.DEPARTMENT,
        uploaded_by=users["admin"].id, max_mb=10,
    )
    fake_llm.answers = ["Check device clock. [S1]"]
    first = ask(client, users["it"], "VPN certificate error")
    assert first.status_code == 200
    assert first.json()["sources"][0]["document_id"] == document.id
    conversation_id = first.json()["conversation_id"]

    document.status = DocumentStatus.DELETED
    session.commit()
    history = client.get(f"/conversations/{conversation_id}/messages", headers=auth_header(users["it"]))
    assert history.json()[1]["sources"] == []
    assert "Check device clock" not in history.json()[1]["content"]

    fake_llm.calls.clear()
    ask(client, users["it"], "What about the certificate?", conversation_id)
    assert all("Check device clock" not in message for _, message in fake_llm.calls)


def test_history_budget_keeps_latest_complete_exchange(
    client: TestClient, session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder,
    fake_llm: FakeLLM, users: dict[str, User], monkeypatch: pytest.MonkeyPatch,
) -> None:
    ingest_document(
        session, vector_store, fake_embedder, filename="vpn.md",
        content=b"VPN certificate errors: check device clock and retry VPN.",
        department=Department.IT, visibility=Visibility.DEPARTMENT,
        uploaded_by=users["admin"].id, max_mb=10,
    )
    fake_llm.answers = ["First answer. [S1]"]
    first = ask(client, users["it"], "VPN first issue")
    conversation_id = first.json()["conversation_id"]
    fake_llm.answers = ["Second answer. [S1]"]
    ask(client, users["it"], "VPN second issue", conversation_id)
    monkeypatch.setattr(get_settings(), "chat_history_budget_tokens", 230)
    fake_llm.calls.clear()
    fake_llm.answers = ["Third answer. [S1]"]
    third = ask(client, users["it"], "VPN third issue", conversation_id)

    assert third.status_code == 200
    prompt = fake_llm.calls[-1][1]
    assert "VPN second issue" in prompt and "Second answer" in prompt
    assert "VPN first issue" not in prompt and "First answer" not in prompt


def _history_block(prompt: str) -> str:
    return prompt.split("<history>", 1)[1].split("</history>", 1)[0] if "<history>" in prompt else ""


def test_old_citation_labels_are_not_sent_as_history(
    client: TestClient, session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder,
    fake_llm: FakeLLM, users: dict[str, User],
) -> None:
    ingest_document(
        session, vector_store, fake_embedder, filename="vpn.md",
        content=b"VPN certificate error: check device clock and renew certificate.",
        department=Department.IT, visibility=Visibility.DEPARTMENT,
        uploaded_by=users["admin"].id, max_mb=10,
    )
    fake_llm.answers = ["Check device clock. 【S1】 Renew it. [S1, S2]"]
    first = ask(client, users["it"], "VPN certificate error")
    fake_llm.answers = ["Renew the certificate. [S1]"]
    ask(client, users["it"], "VPN certificate again?", first.json()["conversation_id"])

    history = _history_block(fake_llm.calls[-1][1])
    # Eski [S1] bu turda başka bir parça olabilir; model kopyalayıp yanlış kaynağa atıf yapmasın.
    assert "Check device clock." in history and "Renew it." in history
    assert "S1" not in history and "S2" not in history


def test_revoking_an_uncited_context_document_hides_the_answer(
    client: TestClient, session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder,
    fake_llm: FakeLLM, users: dict[str, User],
) -> None:
    for name, text in [("vpn-a.md", b"VPN certificate error: check device clock."),
                       ("vpn-b.md", b"VPN certificate error: renew certificate yearly.")]:
        ingest_document(
            session, vector_store, fake_embedder, filename=name, content=text,
            department=Department.IT, visibility=Visibility.DEPARTMENT,
            uploaded_by=users["admin"].id, max_mb=10,
        )
    fake_llm.answers = ["Check the clock and renew yearly. [S1]"]
    first = ask(client, users["it"], "VPN certificate error")
    cited = {source["document_id"] for source in first.json()["sources"]}
    assert len(cited) == 1  # model iki parçayı gördü ama yalnız birine atıf yaptı
    uncited = session.query(Document).filter(Document.id.not_in(cited)).one()

    uncited.status = DocumentStatus.DELETED
    session.commit()
    conversation_id = first.json()["conversation_id"]
    history = client.get(f"/conversations/{conversation_id}/messages", headers=auth_header(users["it"]))
    assert "renew yearly" not in history.json()[1]["content"]
    fake_llm.calls.clear()
    ask(client, users["it"], "And the clock?", conversation_id)
    assert all("renew yearly" not in message for _, message in fake_llm.calls)


def test_refusals_and_canned_replies_stay_out_of_context(
    client: TestClient, session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder,
    fake_llm: FakeLLM, users: dict[str, User],
) -> None:
    first = ask(client, users["it"], "merhaba")
    conversation_id = first.json()["conversation_id"]
    refused = ask(client, users["it"], "VPN certificate error", conversation_id)  # henüz belge yok
    assert refused.json()["no_evidence"] is True
    ingest_document(
        session, vector_store, fake_embedder, filename="vpn.md",
        content=b"VPN certificate error: check device clock.",
        department=Department.IT, visibility=Visibility.DEPARTMENT,
        uploaded_by=users["admin"].id, max_mb=10,
    )
    fake_llm.answers = ["Check device clock. [S1]"]
    ask(client, users["it"], "VPN certificate error again", conversation_id)

    assert "<history>" not in fake_llm.calls[-1][1]
    # Ekranda geçmiş eksiksiz kalır; yalnızca modele giden bağlamdan çıkarılır.
    shown = client.get(f"/conversations/{conversation_id}/messages", headers=auth_header(users["it"]))
    assert len(shown.json()) == 6
