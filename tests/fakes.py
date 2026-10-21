"""Testlerde gerçek model yerine kullanılan sahte bileşenler."""

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.llm import LLMResult


@dataclass
class FakeLLM:
    """Sırayla verilen cevapları döndürür ve gelen istekleri kaydeder (LLM'e ne gittiğini test etmek için)."""

    answers: list[str] = field(default_factory=lambda: ["Cevap [S1]."])
    calls: list[tuple[str, str]] = field(default_factory=list)

    def generate(self, system_prompt: str, user_message: str) -> LLMResult:
        self.calls.append((system_prompt, user_message))
        answer = self.answers[min(len(self.calls), len(self.answers)) - 1]
        return LLMResult(text=answer, model="fake-llm", latency_ms=1)


class FakeEmbedder:
    """Modelsiz, deterministik embedder: kelime torbası (bag of words) hash'leri, normalize edilmiş.

    Ortak kelimesi olan metinlerin vektörleri birbirine yakın çıkar; böylece arama testleri
    gerçek modeli yüklemeden anlamlı sıralama görebilir.
    """

    def __init__(self, dimension: int = 32) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def count_passage_tokens(self, text: str) -> int:
        # Kelime sayısı + gerçek modeldeki önek/özel token payını taklit eden sabit.
        return len(text.split()) + 3

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for word in re.findall(r"\w+", text.lower()):
            bucket = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest()) % self._dimension
            vector[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            # Boş metin için sıfır vektör yerine sabit birim vektör (cosine sıfır vektörde tanımsız).
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]
