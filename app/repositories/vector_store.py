"""Chunk vektörlerini Qdrant'ta saklar ve izinli belgeler içinde arar.

Yetki kararı burada verilmez: hangi belgelerin aranabileceği (`allowed_document_ids`)
çağıran tarafından SQLite'tan hesaplanır. Qdrant payload'ında yetki/durum alanı tutulmaz.
"""

import uuid
import warnings
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.services.chunking import Chunk
from app.services.embeddings import get_embedder

# Nokta kimliklerinin türetildiği sabit ad alanı: aynı belge + chunk her zaman aynı kimliği alır.
_POINT_NAMESPACE = uuid.UUID("6f1c2b1e-4a8d-4c55-9a8e-6b0d3f6c2a17")


@dataclass(frozen=True)
class ChunkHit:
    document_id: str
    chunk_index: int
    page_number: int | None
    filename: str
    text: str
    score: float


class VectorStore:
    def __init__(self, client: QdrantClient, collection_name: str, dimension: int) -> None:
        self._client = client
        self._collection = collection_name
        self._dimension = dimension

    def ensure_collection(self) -> None:
        """Collection yoksa oluşturur; varsa vektör ayarlarının bu modele uyduğunu doğrular."""
        if self._client.collection_exists(self._collection):
            vectors = self._client.get_collection(self._collection).config.params.vectors
            if (
                not isinstance(vectors, models.VectorParams)
                or vectors.size != self._dimension
                or vectors.distance != models.Distance.COSINE
            ):
                # Farklı modelin vektörleri karşılaştırılamaz; sessizce devam etmek yerine dur.
                raise RuntimeError(
                    f"'{self._collection}' collection'ı bu embedding modeliyle uyumsuz; "
                    "belgeler yeniden indekslenmeli."
                )
            return

        self._client.create_collection(
            self._collection,
            vectors_config=models.VectorParams(size=self._dimension, distance=models.Distance.COSINE),
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

        points = [
            models.PointStruct(
                id=point_id(document_id, chunk.chunk_index),
                vector=list(vector),
                payload={
                    "document_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "filename": filename,
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        if points:
            self._client.upsert(self._collection, points=points, wait=True)

    def search(
        self,
        query_vector: Sequence[float],
        allowed_document_ids: Collection[str],
        limit: int,
    ) -> list[ChunkHit]:
        """Yalnızca izinli belgelerin chunk'ları arasında arar, en benzerden başlayarak döndürür."""
        if limit <= 0:
            raise ValueError("limit pozitif olmalı.")
        if not allowed_document_ids:
            # İzinli belge yoksa Qdrant'a hiç gidilmez (fail closed).
            return []

        result = self._client.query_points(
            self._collection,
            query=list(query_vector),
            query_filter=_document_filter(allowed_document_ids),
            limit=limit,
            with_payload=True,
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
                    score=point.score,
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


@lru_cache
def get_vector_store() -> VectorStore:
    """Diskteki kalıcı Qdrant'ı açar. Local mode klasörü kilitler: tek süreç (tek worker) kullanılmalı."""
    settings = get_settings()
    path = Path(settings.qdrant_path)
    path.mkdir(parents=True, exist_ok=True)
    store = VectorStore(
        QdrantClient(path=str(path)), settings.qdrant_collection, get_embedder().dimension
    )
    store.ensure_collection()
    return store
