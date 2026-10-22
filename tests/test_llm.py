import json

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.services import llm
from app.services.llm import LLMNotConfiguredError, LLMUnavailableError, OpenAICompatibleLLM

SECRET_KEY = "gsk_test_secret_value_123"


def completion_body(content: str | None, model: str = "test-model") -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def make_llm(handler) -> OpenAICompatibleLLM:  # pyright: ignore[reportMissingParameterType]
    # Gerçek OpenAI istemcisi; yalnızca ağ katmanı sahte (istek doğru kuruluyor mu, test edilir).
    return OpenAICompatibleLLM(
        base_url="https://llm.example.test/v1",
        api_key=SECRET_KEY,
        model="test-model",
        timeout_seconds=5,
        max_output_tokens=256,
        temperature=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )


def test_generate_sends_openai_compatible_request_and_returns_text() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=completion_body("  Yıllık izin 14 gündür. [S1]  "))

    result = make_llm(handler).generate("sistem talimatı", "kullanıcı mesajı")

    assert result.text == "Yıllık izin 14 gündür. [S1]"
    assert result.model == "test-model"
    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["auth"] == f"Bearer {SECRET_KEY}"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "test-model"
    assert body["messages"] == [
        {"role": "system", "content": "sistem talimatı"},
        {"role": "user", "content": "kullanıcı mesajı"},
    ]
    assert body["temperature"] == 0
    assert body["max_completion_tokens"] == 256


@pytest.mark.parametrize(
    ("status", "expected_phrase"),
    [
        (401, "anahtarı reddetti"),
        (403, "anahtarı reddetti"),
        (404, "LLM_MODEL"),
        (429, "kullanım sınırına"),
        (500, "kullanılamıyor"),
    ],
)
def test_provider_errors_become_safe_messages(status: int, expected_phrase: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": {"message": f"raw provider detail for {SECRET_KEY}"}})

    with pytest.raises(LLMUnavailableError) as exc_info:
        make_llm(handler).generate("s", "u")

    message = str(exc_info.value)
    assert expected_phrase in message
    assert SECRET_KEY not in message
    assert "raw provider detail" not in message


def test_timeout_becomes_safe_message() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    with pytest.raises(LLMUnavailableError, match="zamanında cevap vermedi"):
        make_llm(handler).generate("s", "u")


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_answer_is_an_error(content: str | None) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=completion_body(content))

    with pytest.raises(LLMUnavailableError, match="boş cevap"):
        make_llm(handler).generate("s", "u")


@pytest.mark.parametrize("key", [None, "", "replace_me"])
def test_missing_key_gives_setup_instructions(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    llm.get_llm.cache_clear()
    monkeypatch.setattr(get_settings(), "llm_api_key", SecretStr(key) if key is not None else None)

    with pytest.raises(LLMNotConfiguredError, match="LLM_API_KEY"):
        llm.get_llm()
    llm.get_llm.cache_clear()


def test_api_key_is_hidden_when_settings_are_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", SecretStr(SECRET_KEY))

    assert SECRET_KEY not in repr(settings)
    assert SECRET_KEY not in str(settings.model_dump())


TOOL = {"type": "function", "function": {"name": "create_support_ticket", "parameters": {"type": "object"}}}


def tool_call_body(name: str, arguments: str) -> dict[str, object]:
    body = completion_body(None)
    message = body["choices"][0]["message"]  # pyright: ignore[reportIndexIssue]
    message["tool_calls"] = [  # pyright: ignore[reportIndexIssue]
        {"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}
    ]
    return body


def test_tools_are_sent_only_when_given() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=completion_body("cevap"))

    make_llm(handler).generate("s", "u")
    make_llm(handler).generate("s", "u", tools=[TOOL])

    assert "tools" not in bodies[0]
    assert bodies[1]["tools"] == [TOOL]


def test_offered_tool_call_is_parsed() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=tool_call_body("create_support_ticket", '{"subject": "VPN"}'))

    result = make_llm(handler).generate("s", "u", tools=[TOOL])

    assert result.text == ""
    assert result.tool_call is not None
    assert result.tool_call.name == "create_support_ticket"
    assert result.tool_call.arguments == {"subject": "VPN"}


@pytest.mark.parametrize(
    ("name", "arguments"),
    [("delete_everything", "{}"), ("create_support_ticket", "not json"), ("create_support_ticket", "[1, 2]")],
)
def test_unoffered_or_malformed_tool_calls_are_ignored(name: str, arguments: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=tool_call_body(name, arguments))

    # Geçerli araç çağrısı ve metin yoksa boş cevapla aynı güvenli hata.
    with pytest.raises(LLMUnavailableError, match="boş cevap"):
        make_llm(handler).generate("s", "u", tools=[TOOL])
