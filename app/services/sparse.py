"""Kelime tabanlı (BM25) seyrek vektörler: hibrit aramanın ikinci ayağı. Gerekçe: docs/adr/11-hybrid-search-and-gpu-reranking.md

Yoğun (dense) vektör anlamı yakalar; BM25 ise "TCP 443", form adları, ürün kodları gibi birebir geçen
terimleri yakalar. Parça vektörü yalnızca terim frekansını taşır; IDF'yi Qdrant koleksiyon
istatistiğinden hesaplar (`Modifier.IDF`), bu yüzden yeni belge eklendikçe ağırlıklar kendiliğinden güncellenir.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from fastembed import SparseTextEmbedding

from app.core.config import get_settings

BM25_MODEL = "Qdrant/bm25"
# Demo belgeleri ağırlıklı Türkçe; Türkçe kök bulma (stemming) "izinler" ile "izin"i eşleştirir.
BM25_LANGUAGE = "turkish"


@dataclass(frozen=True)
class SparseVectorData:
    indices: list[int]
    values: list[float]


class SparseEncoder(Protocol):
    """Gerçek BM25 ve testlerdeki sahte kodlayıcı aynı arayüzü uygular."""

    def embed_documents(self, texts: Sequence[str]) -> list[SparseVectorData]: ...

    def embed_query(self, text: str) -> SparseVectorData: ...


class Bm25Encoder:
    """fastembed'in BM25'i; model dosyası yalnızca kelime listeleri içerir (~10 MB), ilk kullanımda yüklenir."""

    def __init__(self, cache_dir: str) -> None:
        self._cache_dir = cache_dir
        self._model: SparseTextEmbedding | None = None

    def embed_documents(self, texts: Sequence[str]) -> list[SparseVectorData]:
        return [_to_data(vector) for vector in self._load().embed(list(texts))]

    def embed_query(self, text: str) -> SparseVectorData:
        return _to_data(next(iter(self._load().query_embed(text))))

    def _load(self) -> SparseTextEmbedding:
        if self._model is None:
            self._model = SparseTextEmbedding(BM25_MODEL, cache_dir=self._cache_dir, language=BM25_LANGUAGE)
        return self._model


def _to_data(vector: object) -> SparseVectorData:
    indices, values = getattr(vector, "indices"), getattr(vector, "values")
    return SparseVectorData(indices=[int(i) for i in indices], values=[float(v) for v in values])


@lru_cache
def get_sparse_encoder() -> SparseEncoder:
    return Bm25Encoder(get_settings().model_cache_dir)
