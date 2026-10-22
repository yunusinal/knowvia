from collections.abc import Iterator
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models

from app.repositories.vector_store import ChunkHit, VectorStore, point_id
from app.services.chunking import Chunk
from tests.fakes import FakeEmbedder, FakeSparseEncoder

COLLECTION = "test_chunks"


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(dimension=32)


@pytest.fixture
def client() -> Iterator[QdrantClient]:
    client = QdrantClient(":memory:")
    yield client
    client.close()


@pytest.fixture
def store(client: QdrantClient, embedder: FakeEmbedder) -> VectorStore:
    store = VectorStore(client, COLLECTION, embedder.dimension, FakeSparseEncoder())
    store.ensure_collection()
    return store


def make_chunks(*texts: str, page_number: int | None = None) -> list[Chunk]:
    return [
        Chunk(chunk_index=i, page_number=page_number, text=text, token_count=len(text.split()))
        for i, text in enumerate(texts)
    ]


def add_document(
    store: VectorStore, embedder: FakeEmbedder, document_id: str, *texts: str, page_number: int | None = None
) -> None:
    chunks = make_chunks(*texts, page_number=page_number)
    store.add_chunks(document_id, f"{document_id}.md", chunks, embedder.embed_passages([c.text for c in chunks]))


def search(store: VectorStore, embedder: FakeEmbedder, query: str, allowed: set[str], limit: int = 5) -> list[ChunkHit]:
    return store.search(embedder.embed_query(query), query, allowed, limit)


def test_ensure_collection_is_idempotent(client: QdrantClient, store: VectorStore) -> None:
    store.ensure_collection()

    assert client.collection_exists(COLLECTION)


def test_existing_collection_with_other_dimension_is_rejected(client: QdrantClient) -> None:
    VectorStore(client, COLLECTION, 32, FakeSparseEncoder()).ensure_collection()

    # Ör. embedding modeli değişti: eski vektörlerle karşılaştırma anlamsız olurdu.
    with pytest.raises(RuntimeError, match="uyumsuz"):
        VectorStore(client, COLLECTION, 1024, FakeSparseEncoder()).ensure_collection()


def test_old_dense_only_collection_is_rejected_with_migration_hint(client: QdrantClient) -> None:
    # v1 şeması: isimsiz tek dense vektör, BM25 yok.
    client.create_collection(COLLECTION, vectors_config=models.VectorParams(size=32, distance=models.Distance.COSINE))

    with pytest.raises(RuntimeError, match="reindex_hybrid"):
        VectorStore(client, COLLECTION, 32, FakeSparseEncoder()).ensure_collection()


def test_search_returns_chunk_fields_and_ranks_best_match_first(store: VectorStore, embedder: FakeEmbedder) -> None:
    add_document(store, embedder, "leave", "Yıllık izin 14 iş günüdür.", "İzin talebi İK portalından girilir.", page_number=2)

    hits = search(store, embedder, "yıllık izin kaç gün", {"leave"})

    assert hits[0] == ChunkHit(
        document_id="leave",
        chunk_index=0,
        page_number=2,
        filename="leave.md",
        text="Yıllık izin 14 iş günüdür.",
        score=hits[0].score,
    )
    assert hits[0].score > hits[1].score


def test_search_never_returns_documents_outside_allowed_list(store: VectorStore, embedder: FakeEmbedder) -> None:
    # Gizli belge sorguyla birebir aynı metni içeriyor; yine de izinli değilse dönmemeli.
    add_document(store, embedder, "budget-confidential", "2026 bütçe planı bulut harcamaları artış")
    add_document(store, embedder, "handbook", "Çalışan el kitabı mesai saatleri")

    hits = search(store, embedder, "2026 bütçe planı bulut harcamaları artış", {"handbook"})

    assert [h.document_id for h in hits] == ["handbook"]


def test_search_with_empty_allowed_list_does_not_query_qdrant(
    store: VectorStore, embedder: FakeEmbedder, client: QdrantClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_document(store, embedder, "handbook", "Çalışan el kitabı")

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("İzinli belge yokken Qdrant sorgulanmamalı.")

    monkeypatch.setattr(client, "query_points", fail_if_called)

    assert search(store, embedder, "el kitabı", set()) == []


def test_search_respects_limit(store: VectorStore, embedder: FakeEmbedder) -> None:
    add_document(store, embedder, "doc", *[f"izin kuralı {i}" for i in range(10)])

    assert len(search(store, embedder, "izin kuralı", {"doc"}, limit=3)) == 3


def test_search_rejects_non_positive_limit(store: VectorStore, embedder: FakeEmbedder) -> None:
    with pytest.raises(ValueError):
        search(store, embedder, "izin", {"doc"}, limit=0)


def test_payload_contains_no_authorization_fields(store: VectorStore, embedder: FakeEmbedder, client: QdrantClient) -> None:
    add_document(store, embedder, "doc", "VPN kurulum rehberi")

    records = client.retrieve(COLLECTION, ids=[point_id("doc", 0)], with_payload=True)

    # Yetki ve durum bilgisi yalnızca SQLite'ta; payload'a yanlışlıkla eklenirse bu test kırılır.
    assert records[0].payload is not None
    assert set(records[0].payload) == {"document_id", "chunk_index", "page_number", "filename", "text"}


def test_rewriting_a_document_overwrites_instead_of_duplicating(store: VectorStore, embedder: FakeEmbedder) -> None:
    add_document(store, embedder, "doc", "birinci", "ikinci")
    add_document(store, embedder, "doc", "birinci", "ikinci")

    assert store.count_document_chunks("doc") == 2


def test_delete_document_removes_only_that_document(store: VectorStore, embedder: FakeEmbedder) -> None:
    add_document(store, embedder, "keep", "kalacak belge")
    add_document(store, embedder, "remove", "silinecek belge", "silinecek ikinci parça")

    store.delete_document("remove")

    assert store.count_document_chunks("remove") == 0
    assert store.count_document_chunks("keep") == 1
    assert search(store, embedder, "silinecek belge", {"remove", "keep"})[0].document_id == "keep"


def test_add_chunks_rejects_mismatched_input(store: VectorStore, embedder: FakeEmbedder) -> None:
    chunks = make_chunks("bir", "iki")

    with pytest.raises(ValueError):
        store.add_chunks("doc", "doc.md", chunks, embedder.embed_passages(["bir"]))
    with pytest.raises(ValueError):
        store.add_chunks("doc", "doc.md", chunks[:1], [[0.1, 0.2]])


def test_point_ids_are_deterministic_and_unique_per_chunk() -> None:
    assert point_id("doc", 0) == point_id("doc", 0)
    assert len({point_id("doc", 0), point_id("doc", 1), point_id("other", 0)}) == 3


def test_vectors_persist_on_disk_across_clients(tmp_path: Path, embedder: FakeEmbedder) -> None:
    path = str(tmp_path / "qdrant")
    store = VectorStore(QdrantClient(path=path), COLLECTION, embedder.dimension, FakeSparseEncoder())
    store.ensure_collection()
    add_document(store, embedder, "doc", "kalıcı metin")
    store.close()  # local mode klasörü kilitler; yeniden açmadan önce kapatılmalı

    reopened = VectorStore(QdrantClient(path=path), COLLECTION, embedder.dimension, FakeSparseEncoder())
    reopened.ensure_collection()

    assert reopened.count_document_chunks("doc") == 1
    reopened.close()


def test_keyword_only_match_in_a_forbidden_document_is_not_returned(store: VectorStore, embedder: FakeEmbedder) -> None:
    add_document(store, embedder, "secret", "Kod adı ZX9QK proje bütçesi")
    add_document(store, embedder, "handbook", "Çalışan el kitabı mesai saatleri")
    # Dense sorgu el kitabına benzesin; yalnızca BM25 gizli belgedeki nadir terimi yakalayabilir.
    dense = embedder.embed_query("Çalışan el kitabı mesai saatleri")

    hits = store.search(dense, "ZX9QK", {"handbook"}, 5)

    assert {hit.document_id for hit in hits} == {"handbook"}


def test_keyword_search_finds_exact_terms_the_dense_query_misses(store: VectorStore, embedder: FakeEmbedder) -> None:
    add_document(store, embedder, "vpn", "Otel ağında UDP engelliyse istemciyi TCP443 moduna alın")
    add_document(store, embedder, *(["handbook"] + [f"Çalışan el kitabı bölüm {i}" for i in range(30)]))
    dense = embedder.embed_query("Çalışan el kitabı bölüm")  # dense tek başına VPN belgesini ilk 20'ye sokmaz

    hits = store.search(dense, "TCP443", {"vpn", "handbook"}, 5)

    assert "vpn" in {hit.document_id for hit in hits}


def test_acl_filter_is_applied_to_both_candidate_searches(
    store: VectorStore, embedder: FakeEmbedder, client: QdrantClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_document(store, embedder, "doc", "izin kuralı")
    calls: list[dict[str, object]] = []
    original = client.query_points

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return original(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(client, "query_points", spy)
    search(store, embedder, "izin", {"doc"})

    prefetch = calls[0]["prefetch"]
    assert isinstance(prefetch, list) and len(prefetch) == 2
    assert all(item.filter == calls[0]["query_filter"] for item in prefetch)  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]


def test_hit_score_is_dense_cosine_not_fusion_rank(store: VectorStore, embedder: FakeEmbedder) -> None:
    add_document(store, embedder, "doc", "Yıllık izin 14 iş günüdür.", "VPN kurulum rehberi")

    query = "izin rehberi"
    hits = {hit.text: hit.score for hit in search(store, embedder, query, {"doc"})}

    # Eşik kosinüse göre ölçüldü; RRF sıra puanı (1/(k+sıra)) bu skorların yerine geçmemeli.
    query_vector = embedder.embed_query(query)
    for text, score in hits.items():
        passage = embedder.embed_passages([text])[0]
        assert score == pytest.approx(sum(a * b for a, b in zip(query_vector, passage, strict=True)))
