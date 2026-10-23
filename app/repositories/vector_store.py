"""Chunk vektörlerini Qdrant'ta saklar ve izinli belgeler içinde hibrit arama yapar.

Yetki kararı burada verilmez: hangi belgelerin aranabileceği (`allowed_document_ids`)
çağıran tarafından SQLite'tan hesaplanır. Qdrant payload'ında yetki/durum alanı tutulmaz.

Her nokta iki isimli vektör taşır: anlam için `dense` (e5) ve kelime eşleşmesi için `bm25`.
Arama iki listeyi Reciprocal Rank Fusion (RRF) ile birleştirir (ADR-11); yetki filtresi her iki
aramaya ayrı ayrı uygulanır.
"""

import uuid
import warnings
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.services.chunking import Chunk
from app.services.embeddings import get_embedder
from app.services.sparse import SparseEncoder, SparseVectorData, get_sparse_encoder

# Nokta kimliklerinin türetildiği sabit ad alanı: aynı belge + chunk her zaman aynı kimliği alır.
_POINT_NAMESPACE = uuid.UUID("6f1c2b1e-4a8d-4c55-9a8e-6b0d3f6c2a17")
DENSE = "dense"
SPARSE = "bm25"
# RRF'e her iki aramadan en az bu kadar aday girer; ölçüm 20 adayla yapıldı (ADR-10, ADR-11).
MIN_PREFETCH = 20


@dataclass(frozen=True)
class ChunkHit:
    document_id: str
    chunk_index: int
    page_number: int | None
    filename: str
    text: str
    score: float  # dense kosinüs benzerliği; sıralama RRF'ten gelir, eşik bu skora uygulanır


class VectorStore:
    def __init__(self, client: QdrantClient, collection_name: str, dimension: int, sparse: SparseEncoder) -> None:
        self._client = client
        self._collection = collection_name
        self._dimension = dimension
        self._sparse = sparse

    def ensure_collection(self) -> None:
        """Collection yoksa oluşturur; varsa vektör şemasının bu sürüme ve modele uyduğunu doğrular."""
        if self._client.collection_exists(self._collection):
            params = self._client.get_collection(self._collection).config.params
            dense = params.vectors.get(DENSE) if isinstance(params.vectors, dict) else None
            if (
                dense is None
                or dense.size != self._dimension
                or dense.distance != models.Distance.COSINE
                or SPARSE not in (params.sparse_vectors or {})
            ):
                # Farklı model veya eski (yalnız dense) şema karşılaştırılamaz; sessizce devam etmek yerine dur.
                raise RuntimeError(
                    f"'{self._collection}' collection'ı bu sürümle uyumsuz; "
                    "`uv run python -m scripts.reindex_hybrid` ile taşıyın veya belgeleri yeniden yükleyin."
                )
            return

        self._client.create_collection(
            self._collection,
            vectors_config={DENSE: models.VectorParams(size=self._dimension, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        # Local mode indeksleri kullanmaz ve her seferinde uyarı verir; indeks, Qdrant sunucusuna
        # geçildiğinde filtreli aramayı hızlandırmak için yine de oluşturulur.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Payload indexes have no effect in the local Qdrant")
            self._client.create_payload_index(
                self._collection, "document_id", models.PayloadSchemaType.KEYWORD
            )

    def add_chunks(
        self,
        document_id: str,
        filename: str,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        """Chunk'ları yazar. Aynı belge tekrar yazılırsa noktaların üzerine yazılır (kopya oluşmaz)."""
        if len(chunks) != len(vectors):
            raise ValueError("Chunk ve vektör sayısı eşit olmalı.")
        if any(len(vector) != self._dimension for vector in vectors):
            raise ValueError("Vektör boyutu collection boyutuyla uyuşmuyor.")

        sparse = self._sparse.embed_documents([chunk.text for chunk in chunks]) if chunks else []
        points = [
            models.PointStruct(
                id=point_id(document_id, chunk.chunk_index),
                vector={DENSE: list(vector), SPARSE: _sparse_vector(sparse_vector)},
                payload={
                    "document_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "filename": filename,
                    "text": chunk.text,
                },
            )
            for chunk, vector, sparse_vector in zip(chunks, vectors, sparse, strict=True)
        ]
        if points:
            self._client.upsert(self._collection, points=points, wait=True)

    def search(
        self,
        query_vector: Sequence[float],
        query_text: str,
        allowed_document_ids: Collection[str],
        limit: int,
    ) -> list[ChunkHit]:
        """İzinli belgelerin chunk'ları arasında hibrit arar; RRF sırasıyla, dense skorlarıyla döndürür."""
        if limit <= 0:
            raise ValueError("limit pozitif olmalı.")
        if not allowed_document_ids:
            # İzinli belge yoksa Qdrant'a hiç gidilmez (fail closed).
            return []

        allowed = _document_filter(allowed_document_ids)
        candidates = max(limit, MIN_PREFETCH)
        dense_query = list(query_vector)
        result = self._client.query_points(
            self._collection,
            prefetch=[
                # Yetki filtresi her iki aday listesine ayrı ayrı uygulanır; biri unutulsa yetkisiz parça RRF'e girerdi.
                models.Prefetch(query=dense_query, using=DENSE, filter=allowed, limit=candidates),
                models.Prefetch(
                    query=_sparse_vector(self._sparse.embed_query(query_text)), using=SPARSE,
                    filter=allowed, limit=candidates,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=allowed,
            limit=limit,
            with_payload=True,
            with_vectors=[DENSE],
        )
        hits = []
        for point in result.points:
            payload = point.payload or {}
            hits.append(
                ChunkHit(
                    document_id=payload["document_id"],
                    chunk_index=payload["chunk_index"],
                    page_number=payload["page_number"],
                    filename=payload["filename"],
                    text=payload["text"],
                    # RRF skoru sıra tabanlıdır ve eşikle kıyaslanamaz; eşik için kosinüs hesaplanır.
                    score=_cosine(dense_query, _dense_of(point)),
                )
            )
        return hits

    def delete_document(self, document_id: str) -> None:
        self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(filter=_document_filter([document_id])),
            wait=True,
        )

    def count_document_chunks(self, document_id: str) -> int:
        return self._client.count(
            self._collection, count_filter=_document_filter([document_id]), exact=True
        ).count

    def close(self) -> None:
        """Local mode'un klasör kilidini bırakır; uygulama kapanırken çağrılmalı."""
        self._client.close()


def point_id(document_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{document_id}:{chunk_index}"))


def _document_filter(document_ids: Collection[str]) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="document_id", match=models.MatchAny(any=list(document_ids)))]
    )


def _sparse_vector(data: SparseVectorData) -> models.SparseVector:
    return models.SparseVector(indices=data.indices, values=data.values)


def _dense_of(point: models.ScoredPoint) -> list[float]:
    vector = point.vector
    dense = vector.get(DENSE) if isinstance(vector, dict) else None
    if not isinstance(dense, list):
        raise RuntimeError("Qdrant sonucu dense vektör içermiyor.")
    return [float(value) for value in cast(list[float], dense)]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norms = (sum(a * a for a in left) ** 0.5) * (sum(b * b for b in right) ** 0.5)
    return dot / norms if norms else 0.0


@lru_cache
def get_vector_store() -> VectorStore:
    """Diskteki kalıcı Qdrant'ı açar. Local mode klasörü kilitler: tek süreç (tek worker) kullanılmalı."""
    settings = get_settings()
    path = Path(settings.qdrant_path)
    path.mkdir(parents=True, exist_ok=True)
    # Klasörü kilitleyen istemci en son açılır; hata olursa kapatılır ki sonraki istek asıl hatayı
    # görsün, yanıltıcı "already accessed" kilit hatasını değil (lru_cache hatayı önbelleğe almaz).
    dimension, sparse = get_embedder().dimension, get_sparse_encoder()
    client = QdrantClient(path=str(path))
    store = VectorStore(client, settings.qdrant_collection, dimension, sparse)
    try:
        store.ensure_collection()
    except Exception:
        client.close()
        raise
    return store
