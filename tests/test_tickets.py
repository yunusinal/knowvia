"""Destek talebi: model yalnızca önerir, kayıt kullanıcının açık isteğiyle oluşur; sahiplik korunur."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Department, SupportTicket, User, Visibility
from app.repositories.vector_store import VectorStore
from app.services.ingest import ingest_document
from app.services.llm import ToolCall
from app.services.tickets import PROPOSAL_MESSAGE, TOOL_NAME, proposal_from
from tests.fakes import FakeEmbedder, FakeLLM
from tests.helpers import auth_header

PROPOSAL = ToolCall(TOOL_NAME, {"subject": "VPN sertifika hatası", "description": "Saat ve önbellek denendi."})


@pytest.fixture(autouse=True)
def vpn_document(
    session: Session, vector_store: VectorStore, fake_embedder: FakeEmbedder,
    users: dict[str, User], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "retrieval_min_score", 0.1)
    ingest_document(
        session, vector_store, fake_embedder, filename="vpn.md",
        content=b"VPN certificate error: check device clock and clear the client cache.",
        department=Department.IT, visibility=Visibility.COMPANY,
        uploaded_by=users["admin"].id, max_mb=10,
    )


def ask(client: TestClient, user: User, question: str):  # pyright: ignore[reportMissingReturnType]
    return client.post("/chat", json={"question": question}, headers=auth_header(user))


def create(client: TestClient, user: User, **payload: object):  # pyright: ignore[reportMissingReturnType]
    body = {"subject": "VPN sertifika hatası", "description": "Saat ve önbellek denendi.", **payload}
    return client.post("/support-tickets", json=body, headers=auth_header(user))


def test_tool_is_offered_only_in_the_grounded_llm_call(
    client: TestClient, fake_llm: FakeLLM, users: dict[str, User],
) -> None:
    fake_llm.answers = ["Saati kontrol edin. [S1]"]
    response = ask(client, users["it"], "VPN certificate error")

    assert response.json()["ticket_proposal"] is None
    tools = fake_llm.offered_tools[-1]
    assert tools is not None and [tool["function"]["name"] for tool in tools] == [TOOL_NAME]


def test_proposal_creates_nothing_until_the_user_confirms(
    client: TestClient, session: Session, fake_llm: FakeLLM, users: dict[str, User],
) -> None:
    fake_llm.answers = [PROPOSAL]
    response = ask(client, users["it"], "VPN certificate error still there, open a ticket")

    body = response.json()
    assert response.status_code == 200
    assert body["ticket_proposal"] == {"subject": "VPN sertifika hatası", "description": "Saat ve önbellek denendi."}
    # Modelin metni gösterilmez; "talep açıldı" gibi bir iddia çıkamaz.
    assert body["answer"] == PROPOSAL_MESSAGE and body["sources"] == []
    assert session.scalars(select(SupportTicket)).all() == []

    created = create(client, users["it"], conversation_id=body["conversation_id"])
    assert created.status_code == 201
    assert created.json()["status"] == "open"
    assert created.json()["created_by_email"] == users["it"].email
    assert created.json()["conversation_id"] == body["conversation_id"]
    assert len(session.scalars(select(SupportTicket)).all()) == 1


def test_members_see_only_their_tickets_and_admin_sees_all(
    client: TestClient, users: dict[str, User],
) -> None:
    create(client, users["it"], subject="IT talebi")
    create(client, users["hr"], subject="İK talebi")

    def subjects(user: User) -> list[str]:
        return [item["subject"] for item in client.get("/support-tickets", headers=auth_header(user)).json()]

    assert subjects(users["it"]) == ["IT talebi"]
    assert subjects(users["hr"]) == ["İK talebi"]
    assert sorted(subjects(users["admin"])) == ["IT talebi", "İK talebi"]


def test_ticket_cannot_be_linked_to_someone_elses_conversation(
    client: TestClient, users: dict[str, User], fake_llm: FakeLLM,
) -> None:
    fake_llm.answers = ["Saati kontrol edin. [S1]"]
    conversation_id = ask(client, users["it"], "VPN certificate error").json()["conversation_id"]

    assert create(client, users["hr"], conversation_id=conversation_id).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"created_by": "someone-else"},  # sahiplik istemciden alınmaz
        {"status": "closed"},
        {"subject": "ab"},
        {"subject": "x" * 121},
        {"description": ""},
        {"description": "   "},
    ],
)
def test_invalid_ticket_requests_are_rejected(
    client: TestClient, users: dict[str, User], payload: dict[str, object],
) -> None:
    assert create(client, users["it"], **payload).status_code == 422


def test_tickets_require_authentication(client: TestClient) -> None:
    assert client.get("/support-tickets").status_code == 401
    assert client.post("/support-tickets", json={"subject": "abc", "description": "x"}).status_code == 401


@pytest.mark.parametrize(
    "call",
    [
        None,
        ToolCall("delete_all_documents", {"subject": "a", "description": "b"}),  # sunulmamış araç
        ToolCall(TOOL_NAME, {"subject": 5, "description": "b"}),
        ToolCall(TOOL_NAME, {"subject": "  ", "description": "b"}),
        ToolCall(TOOL_NAME, {"subject": "a"}),
    ],
)
def test_invalid_tool_calls_give_no_proposal(call: ToolCall | None) -> None:
    assert proposal_from(call) is None


def test_long_tool_arguments_are_truncated() -> None:
    proposal = proposal_from(ToolCall(TOOL_NAME, {"subject": "s" * 500, "description": "d" * 5000}))
    assert proposal is not None
    assert len(proposal.subject) == 120 and len(proposal.description) == 2000
