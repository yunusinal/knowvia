"""OpenAI uyumlu herhangi bir sağlayıcıyla (Groq, EVREN, OpenAI…) konuşan LLM adaptörü.

Sağlayıcı yalnızca ayarla değişir (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY). Hata mesajları
kullanıcıya gösterilebilir ve asla anahtar ya da sağlayıcının ham cevabını içermez.
"""

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx2
import openai

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {"", "replace_me"}


class LLMNotConfiguredError(Exception):
    """LLM anahtarı ayarlanmamış; uygulama bunu kurulum yönergesiyle bildirir."""


class LLMUnavailableError(Exception):
    """Sağlayıcıya ulaşılamadı veya istek reddedildi (zaman aşımı, yetki, kota…)."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    latency_ms: int


class LLMClient(Protocol):
    """Gerçek adaptör ve testlerdeki sahte LLM aynı arayüzü uygular."""

    def generate(self, system_prompt: str, user_message: str) -> LLMResult: ...


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_output_tokens: int,
        temperature: float,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=1,
            http_client=http_client,
        )

    def generate(self, system_prompt: str, user_message: str) -> LLMResult:
        started = time.perf_counter()
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=self._temperature,
                max_completion_tokens=self._max_output_tokens,
            )
        except openai.APIError as error:
            # Ayrıntı sunucu günlüğüne; kullanıcıya yalnızca genel neden gider.
            logger.warning("LLM isteği başarısız: %s", type(error).__name__)
            raise LLMUnavailableError(_user_message_for(error)) from error

        content = completion.choices[0].message.content if completion.choices else None
        if not content or not content.strip():
            raise LLMUnavailableError("Dil modeli boş cevap döndürdü.")
        return LLMResult(
            text=content.strip(),
            model=completion.model or self._model,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )


def _user_message_for(error: openai.APIError) -> str:
    if isinstance(error, openai.AuthenticationError | openai.PermissionDeniedError):
        return "Dil modeli sağlayıcısı anahtarı reddetti; LLM_API_KEY ayarını kontrol edin."
    if isinstance(error, openai.RateLimitError):
        return "Dil modeli sağlayıcısının kullanım sınırına ulaşıldı; biraz sonra tekrar deneyin."
    if isinstance(error, openai.APITimeoutError):
        return "Dil modeli zamanında cevap vermedi; tekrar deneyin."
    if isinstance(error, openai.NotFoundError):
        return "Dil modeli bulunamadı; LLM_MODEL ve LLM_BASE_URL ayarlarını kontrol edin."
    return "Dil modeli şu anda kullanılamıyor; tekrar deneyin."


@lru_cache
def get_llm() -> LLMClient:
    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    if api_key.strip() in _PLACEHOLDER_KEYS:
        raise LLMNotConfiguredError(
            "LLM anahtarı ayarlanmamış. .env dosyasına LLM_API_KEY, LLM_BASE_URL ve LLM_MODEL "
            "yazın (bkz. .env.example)."
        )
    return OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        api_key=api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        temperature=settings.llm_temperature,
    )
