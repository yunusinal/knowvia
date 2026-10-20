"""Metni vektöre çevirir (embedding). Model seçimi ve gerekçesi: docs/adr/05-embedding-model.md"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from tokenizers import Tokenizer

from app.core.config import get_settings


@dataclass(frozen=True)
class EmbeddingModelSpec:
    hf_repo: str
    dimension: int
    max_tokens: int
    query_prefix: str
    passage_prefix: str
    model_file: str
    additional_files: tuple[str, ...] = ()


# EMBEDDING_MODEL ayarı yalnızca burada tanımlı ve ölçülmüş modellerden biri olabilir.
SUPPORTED_MODELS: dict[str, EmbeddingModelSpec] = {
    "intfloat/multilingual-e5-large": EmbeddingModelSpec(
        hf_repo="intfloat/multilingual-e5-large",
        dimension=1024,
        max_tokens=512,
        query_prefix="query: ",
        passage_prefix="passage: ",
        model_file="onnx/model.onnx",
        additional_files=("onnx/model.onnx_data",),
    ),
}


class Embedder(Protocol):
    """Gerçek model ve testlerdeki sahte model aynı arayüzü uygular."""

    @property
    def dimension(self) -> int: ...

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def count_passage_tokens(self, text: str) -> int: ...


class FastEmbedEmbedder:
    """fastembed (ONNX Runtime) ile çalışan embedder; model ilk kullanımda yüklenir."""

    def __init__(self, spec: EmbeddingModelSpec, cache_dir: Path) -> None:
        self._spec = spec
        self._cache_dir = cache_dir
        self._model: TextEmbedding | None = None
        self._counting_tokenizer: Tokenizer | None = None

    @property
    def dimension(self) -> int:
        return self._spec.dimension

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([self._spec.passage_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self._spec.query_prefix + text])[0]

    def count_passage_tokens(self, text: str) -> int:
        """Modelin göreceği token sayısı: `passage: ` öneki ve özel token'lar dahil."""
        counting = self._counting_tokenizer
        if counting is None:
            # Modelin tokenizer'ı 512'de keser; kesilmiş sayı sınır aşımını gizlerdi.
            # Bu yüzden saymak için kesmesiz bir kopya kullanılır.
            tokenizer = self._load().model.tokenizer  # pyright: ignore[reportAttributeAccessIssue]
            counting = Tokenizer.from_str(tokenizer.to_str())
            counting.no_truncation()
            counting.no_padding()
            self._counting_tokenizer = counting
        return len(counting.encode(self._spec.passage_prefix + text).ids)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = [vector.tolist() for vector in self._load().embed(texts)]
        if any(len(vector) != self._spec.dimension for vector in vectors):
            raise RuntimeError("Embedding boyutu beklenen model boyutuyla uyuşmuyor.")
        return vectors

    def _load(self) -> TextEmbedding:
        if self._model is None:
            name = _register_official_onnx(self._spec)
            self._model = TextEmbedding(model_name=name, cache_dir=str(self._cache_dir))
        return self._model


def _register_official_onnx(spec: EmbeddingModelSpec) -> str:
    """Modelin resmi ONNX dosyasını mean pooling + normalize ile kaydeder (ölçülen kurulum).

    fastembed'in hazır e5-large kaydı farklı bir ONNX dönüşümü kullanır ve normalize etmez;
    karışmasın diye ayrı bir adla kaydedilir.
    """
    name = f"{spec.hf_repo}-official-onnx"
    registered = {model["model"] for model in TextEmbedding.list_supported_models()}
    if name not in registered:
        TextEmbedding.add_custom_model(
            model=name,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=spec.hf_repo),
            dim=spec.dimension,
            model_file=spec.model_file,
            additional_files=list(spec.additional_files) or None,
        )
    return name


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    spec = SUPPORTED_MODELS.get(settings.embedding_model)
    if spec is None:
        supported = ", ".join(SUPPORTED_MODELS)
        raise ValueError(f"Desteklenmeyen EMBEDDING_MODEL; desteklenenler: {supported}")
    return FastEmbedEmbedder(spec, Path(settings.model_cache_dir))
