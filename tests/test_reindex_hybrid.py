"""v1 (yalnız dense) koleksiyonun hibrit şemaya taşınması: vektörler korunur, aramada iki yol da çalışır."""

import pytest
from qdrant_client import QdrantClient, models

from app.repositories.vector_store import VectorStore, point_id
from scripts.reindex_hybrid import reindex
from tests.fakes import FakeEmbedder, FakeSparseEncoder

DIM = 32


def v1_collection(client: QdrantClient, embedder: FakeEmbedder) -> None:
    client.create_collection("v1", vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
    texts = ["Yıllık izin 14 iş günüdür.", "Otel ağında istemciyi TCP443 moduna alın."]
    client.upsert("v1", [
        models.PointStruct(
            id=point_id("doc", index), vector=vector,
            payload={"document_id": "doc", "chunk_index": index, "page_number": None, "filename": "doc.md", "text": text},
        )
        for index, (text, vector) in enumerate(zip(texts, embedder.embed_passages(texts), strict=True))
    ])


def test_reindex_copies_vectors_and_payload_and_enables_hybrid_search() -> None:
    client, embedder = QdrantClient(":memory:"), FakeEmbedder(DIM)
    v1_collection(client, embedder)

    copied = reindex(client, "v1", "v2", DIM, FakeSparseEncoder())

    assert copied == 2
    assert client.count("v1", exact=True).count == 2  # kaynak geri dönüş için yerinde kalır
    store = VectorStore(client, "v2", DIM, FakeSparseEncoder())
    store.ensure_collection()  # şema doğru: uyumsuzluk hatası yok
    hits = store.search(embedder.embed_query("yıllık izin"), "TCP443", {"doc"}, 5)
    assert {hit.text for hit in hits} == {"Yıllık izin 14 iş günüdür.", "Otel ağında istemciyi TCP443 moduna alın."}
    assert reindex(client, "v1", "v2", DIM, FakeSparseEncoder()) == 2  # tekrar çalıştırmak kopya üretmez
    assert client.count("v2", exact=True).count == 2


def test_reindex_refuses_same_or_missing_source() -> None:
    client = QdrantClient(":memory:")

    with pytest.raises(ValueError, match="aynı"):
        reindex(client, "v2", "v2", DIM, FakeSparseEncoder())
    with pytest.raises(ValueError, match="yok"):
        reindex(client, "missing", "v2", DIM, FakeSparseEncoder())
