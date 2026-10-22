import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_warm_up_runs_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    import app.main as main
    from app.core.config import get_settings

    calls: list[str] = []
    monkeypatch.setattr(main, "warm_up", lambda: calls.append("warm"))
    monkeypatch.setattr(get_settings(), "warmup_on_start", False)
    with TestClient(main.app):
        pass
    monkeypatch.setattr(get_settings(), "warmup_on_start", True)
    with TestClient(main.app):
        pass

    assert calls == ["warm"]
