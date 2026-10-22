"""Arama adaylarını çapraz kodlayıcıyla (cross-encoder) yeniden sıralar; yalnızca GPU_ENABLED=true iken.

Çapraz kodlayıcı soru ile parçayı birlikte okuyup alaka puanı verir: vektör aramasından daha isabetli,
ama çok daha yavaş. Ölçüm (ADR-10, ADR-11): doc2dial'da ilk sıradaki doğru belge %66.5 → %78.6
(hibritle birlikte); RTX 4050'de soru başına ~0.34 sn, CPU'da ~14 sn. Bu yüzden CPU'da kapalıdır.
"""

from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Protocol

from app.core.config import get_settings

# BAAI/bge-reranker-v2-m3 (Apache-2.0, çok dilli) için Hugging Face'in ONNX dönüşümü.
RERANKER_REPO = "onnx-community/bge-reranker-v2-m3-ONNX"
# GPU'da fp16; int8 nicemlenmiş model CUDA'da hızlanmaz.
RERANKER_FILE = "onnx/model_fp16.onnx"


class RerankerUnavailableError(Exception):
    """GPU_ENABLED=true ama bu ortamda CUDA yok; kurulum yönergesiyle bildirilir."""


class Reranker(Protocol):
    """Gerçek çapraz kodlayıcı ve testlerdeki sahte sıralayıcı aynı arayüzü uygular."""

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]: ...


class CrossEncoderReranker:
    """fastembed TextCrossEncoder; model (~1.1 GB) ilk kullanımda indirilir ve GPU'ya yüklenir."""

    def __init__(self, cache_dir: str) -> None:
        self._cache_dir = cache_dir
        self._model: Any = None

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        return [float(score) for score in self._load().rerank(query, list(texts))]

    def _load(self) -> Any:
        if self._model is None:
            from fastembed.common.model_description import ModelSource
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            registered = {model["model"] for model in TextCrossEncoder.list_supported_models()}
            if RERANKER_REPO not in registered:
                TextCrossEncoder.add_custom_model(
                    model=RERANKER_REPO, sources=ModelSource(hf=RERANKER_REPO), model_file=RERANKER_FILE,
                    description="bge-reranker-v2-m3 fp16", license="apache-2.0", size_in_gb=1.14,
                )
            self._model = TextCrossEncoder(
                RERANKER_REPO, cache_dir=self._cache_dir, providers=["CUDAExecutionProvider"]
            )
        return self._model


def cuda_available() -> bool:
    """onnxruntime-gpu kurulu ve CUDA sağlayıcısı yüklenebiliyor mu?"""
    import onnxruntime

    preload = getattr(onnxruntime, "preload_dlls", None)
    if preload is not None:
        try:
            preload(directory="")  # pip ile gelen CUDA/cuDNN DLL'leri; CUDA Toolkit kurmak gerekmez
        except Exception:  # noqa: BLE001 - yüklenemezse aşağıdaki sağlayıcı kontrolü karar verir
            pass
    return "CUDAExecutionProvider" in onnxruntime.get_available_providers()


@lru_cache
def _cached_reranker(cache_dir: str) -> Reranker:
    return CrossEncoderReranker(cache_dir)


def get_reranker() -> Reranker | None:
    """GPU kapalıysa None (yeniden sıralama yok). Açık ama CUDA yoksa sessizce yavaş moda düşmez, hata verir."""
    settings = get_settings()
    if not settings.gpu_enabled:
        return None
    if not cuda_available():
        raise RerankerUnavailableError(
            "GPU_ENABLED=true ama bu ortamda CUDA kullanılamıyor. GPU ortamını kurun "
            "(README: GPU ile çalıştırma) veya .env'de GPU_ENABLED=false yapın."
        )
    return _cached_reranker(settings.model_cache_dir)
