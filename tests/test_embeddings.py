import math

import pytest

from app.services.embeddings import FastEmbedEmbedder
from tests.fakes import FakeEmbedder


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # vektörler normalize


def norm(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def test_fake_embedder_is_deterministic_normalized_and_sized() -> None:
    embedder = FakeEmbedder(dimension=16)

    first = embedder.embed_query("VPN bağlantısı kopuyor")
    again = embedder.embed_passages(["VPN bağlantısı kopuyor"])[0]

    assert first == again
    assert len(first) == 16
    assert norm(first) == pytest.approx(1.0)
    assert norm(embedder.embed_query("")) == pytest.approx(1.0)


def test_fake_embedder_ranks_shared_words_higher() -> None:
    embedder = FakeEmbedder()
    query = embedder.embed_query("yıllık izin kaç gün")
    leave, vpn = embedder.embed_passages(["Yıllık izin 14 gündür.", "VPN istemcisini kurun."])

    assert cosine(query, leave) > cosine(query, vpn)


@pytest.mark.model
def test_real_embedder_returns_normalized_vectors_of_model_dimension(real_embedder: FastEmbedEmbedder) -> None:
    vectors = real_embedder.embed_passages(["Yıllık izin 14 iş günüdür.", "VPN kurulum rehberi."])

    assert [len(v) for v in vectors] == [1024, 1024]
    assert all(norm(v) == pytest.approx(1.0, abs=1e-4) for v in vectors)


@pytest.mark.model
def test_real_embedder_applies_query_and_passage_prefixes(real_embedder: FastEmbedEmbedder) -> None:
    text = "Haftada kaç gün evden çalışabilirim?"

    # Önek uygulanmasaydı aynı metin aynı vektörü verirdi.
    assert real_embedder.embed_query(text) != real_embedder.embed_passages([text])[0]


@pytest.mark.model
def test_real_embedder_ranks_related_passage_higher(real_embedder: FastEmbedEmbedder) -> None:
    query = real_embedder.embed_query("Tatil hakkım kaç gün?")
    leave, vpn = real_embedder.embed_passages([
        "Yıllık İzin Politikası. Çalışanlar yılda 14 iş günü ücretli izin hakkına sahiptir.",
        "VPN Kurulum Rehberi. GlobalConnect istemcisini Yazılım Merkezi'nden kurun.",
    ])

    assert cosine(query, leave) > cosine(query, vpn)


@pytest.mark.model
def test_token_count_is_not_truncated_at_model_limit(real_embedder: FastEmbedEmbedder) -> None:
    # Sayaç 512'de kesseydi sınırı aşan chunk'lar fark edilemezdi.
    long_text = "Çalışanlar yıllık izin taleplerini İK portalından girer. " * 100

    assert real_embedder.count_passage_tokens(long_text) > 512


@pytest.mark.model
def test_token_count_includes_passage_prefix_and_special_tokens(real_embedder: FastEmbedEmbedder) -> None:
    # "passage: " öneki ve başlangıç/bitiş özel token'ları boş metinde bile sayılır.
    assert real_embedder.count_passage_tokens("") >= 3
