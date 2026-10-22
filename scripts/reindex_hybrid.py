"""Eski yalnız-dense koleksiyonu (v1) hibrit şemaya (v2) taşır; embedding modeli yeniden çalışmaz.

Dense vektörler olduğu gibi kopyalanır, her parça için yalnızca BM25 seyrek vektörü üretilir (saniyeler).
Kaynak koleksiyon silinmez: sorun çıkarsa .env'de QDRANT_COLLECTION eski ada çevrilerek geri dönülür.
Qdrant local mode klasörü kilitlediği için API sunucusu KAPALIYKEN çalıştırın:

    uv run python -m scripts.reindex_hybrid --source knowledge_chunks_v1
"""

import argparse
from pathlib import Path

from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.repositories.vector_store import DENSE, SPARSE, VectorStore
from app.services.embeddings import get_embedder
from app.services.sparse import SparseEncoder, get_sparse_encoder

BATCH = 256


def reindex(client: QdrantClient, source: str, target: str, dimension: int, sparse: SparseEncoder) -> int:
    """Kopyalanan nokta sayısını döndürür. Aynı kimliklerle yazdığı için tekrar çalıştırmak güvenlidir."""
    if source == target:
        raise ValueError("Kaynak ve hedef koleksiyon aynı olamaz.")
    if not client.collection_exists(source):
        raise ValueError(f"Kaynak koleksiyon yok: {source}")
    VectorStore(client, target, dimension, sparse).ensure_collection()

    copied, offset = 0, None
    while True:
        points, offset = client.scroll(source, limit=BATCH, offset=offset, with_vectors=True, with_payload=True)
        texts = [(point.payload or {})["text"] for point in points]
        upserts = []
        for point, sparse_vector in zip(points, sparse.embed_documents(texts), strict=True):
            dense = point.vector
            if not isinstance(dense, list) or len(dense) != dimension:
                raise ValueError(f"Beklenmeyen vektör biçimi: {point.id} (kaynak v1 şemasında mı?)")
            upserts.append(models.PointStruct(
                id=point.id, payload=point.payload,
                vector={DENSE: dense, SPARSE: models.SparseVector(indices=sparse_vector.indices, values=sparse_vector.values)},  # pyright: ignore[reportArgumentType]
            ))
        if upserts:
            client.upsert(target, points=upserts, wait=True)
            copied += len(upserts)
        if offset is None:
            break

    expected = client.count(source, exact=True).count
    actual = client.count(target, exact=True).count
    if actual < expected:
        raise RuntimeError(f"Taşıma eksik: kaynakta {expected}, hedefte {actual} nokta var.")
    return copied


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="knowledge_chunks_v1")
    parser.add_argument("--target", default="knowledge_chunks_v2")
    args = parser.parse_args()

    client = QdrantClient(path=str(Path(settings.qdrant_path)))
    try:
        copied = reindex(client, args.source, args.target, get_embedder().dimension, get_sparse_encoder())
    finally:
        client.close()
    print(f"{copied} parça '{args.source}' → '{args.target}' taşındı. "
          f".env içinde QDRANT_COLLECTION={args.target} olmalı; '{args.source}' geri dönüş için duruyor.")


if __name__ == "__main__":
    main()
