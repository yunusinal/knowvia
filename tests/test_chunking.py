from pathlib import Path

import pytest

from app.services.chunking import Chunk, chunk_pages
from app.services.embeddings import FastEmbedEmbedder
from app.services.extraction import ExtractedPage, extract_text


def count_words(text: str) -> int:
    """Mantık testleri için öngörülebilir sayaç: her kelime bir token."""
    return len(text.split())


def sentences(count: int, words_each: int = 5) -> list[str]:
    return [" ".join([f"kelime{i}"] * (words_each - 1)) + f" son{i}." for i in range(count)]


def page(text: str, number: int | None = None) -> ExtractedPage:
    return ExtractedPage(page_number=number, text=text)


def test_short_page_becomes_single_stripped_chunk() -> None:
    chunks = chunk_pages([page("  Kısa bir metin.  \n", 4)], count_words, chunk_tokens=10, overlap_tokens=2)

    assert chunks == [Chunk(chunk_index=0, page_number=4, text="Kısa bir metin.", token_count=3)]


def test_chunks_never_span_pages_and_indexes_continue_across_pages() -> None:
    pages = [page(" ".join(sentences(6)), 1), page(" ".join(sentences(6)), 2)]

    chunks = chunk_pages(pages, count_words, chunk_tokens=12, overlap_tokens=0)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    page_numbers = [c.page_number for c in chunks]
    first_of_page_two = page_numbers.index(2)
    # Önce 1. sayfanın tüm chunk'ları, sonra 2. sayfanınkiler; hiçbiri iki sayfayı karıştırmaz.
    assert set(page_numbers[:first_of_page_two]) == {1}
    assert set(page_numbers[first_of_page_two:]) == {2}


def test_every_chunk_fits_the_token_budget() -> None:
    text = " ".join(sentences(200, words_each=7))

    chunks = chunk_pages([page(text)], count_words, chunk_tokens=20, overlap_tokens=5)

    assert len(chunks) > 10
    assert all(count_words(c.text) <= 20 for c in chunks)
    assert all(c.token_count == count_words(c.text) for c in chunks)


def test_splits_at_sentence_ends_when_possible() -> None:
    text = " ".join(sentences(10))  # her cümle 5 kelime; bütçeye 2 cümle sığar

    chunks = chunk_pages([page(text)], count_words, chunk_tokens=12, overlap_tokens=0)

    assert all(c.text.endswith(".") for c in chunks)


def test_sentence_end_is_preferred_over_line_break_inside_sentence() -> None:
    # PDF'teki gibi: satır sonu cümlenin ortasında.
    first = "Kullanılmayan iznin en fazla beş günü bir sonraki\nyıla devredilebilir."
    second = "Kalan günler yıl sonunda yanar ve geri alınamaz."

    chunks = chunk_pages([page(f"{first} {second}")], count_words, chunk_tokens=12, overlap_tokens=0)

    assert [c.text for c in chunks] == [first, second]


def test_paragraph_break_is_preferred_over_sentence_end() -> None:
    paragraph_one = "Birinci paragraf. Kısa iki cümle."
    paragraph_two = "İkinci paragraf burada başlıyor. O da kısa."

    chunks = chunk_pages(
        [page(f"{paragraph_one}\n\n{paragraph_two}")], count_words, chunk_tokens=10, overlap_tokens=0
    )

    assert [c.text for c in chunks] == [paragraph_one, paragraph_two]


def test_overlap_repeats_last_sentence_of_previous_chunk() -> None:
    parts = sentences(8)  # 5 kelimelik cümleler; örtüşmeye tam bir cümle sığar

    chunks = chunk_pages([page(" ".join(parts))], count_words, chunk_tokens=15, overlap_tokens=5)

    for previous, current in zip(chunks, chunks[1:]):
        last_sentence = previous.text.rsplit(". ", 1)[-1]
        assert current.text.startswith(last_sentence.rstrip("."))


def test_no_text_is_lost_without_overlap() -> None:
    parts = sentences(30)

    chunks = chunk_pages([page(" ".join(parts))], count_words, chunk_tokens=13, overlap_tokens=0)

    assert " ".join(c.text for c in chunks) == " ".join(parts)


def test_text_without_separators_is_split_by_characters() -> None:
    chunks = chunk_pages([page("x" * 50)], len, chunk_tokens=20, overlap_tokens=0)

    assert [len(c.text) for c in chunks] == [20, 20, 10]


def test_whitespace_only_page_produces_no_chunks() -> None:
    assert chunk_pages([page(" \n\n \t ")], count_words, chunk_tokens=10, overlap_tokens=2) == []


@pytest.mark.parametrize("overlap", [-1, 10, 11])
def test_overlap_must_be_smaller_than_chunk_size(overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_pages([page("metin")], count_words, chunk_tokens=10, overlap_tokens=overlap)


@pytest.mark.model
def test_real_tokenizer_chunks_stay_within_model_limit(real_embedder: FastEmbedEmbedder) -> None:
    from scripts.embedding_bench.corpus_large import PASSAGES

    fixture = Path(__file__).parent / "fixtures" / "turkish-two-pages.pdf"
    pdf_pages = extract_text("izin.pdf", fixture.read_bytes(), max_mb=10)
    long_page = page("\n\n".join(PASSAGES.values()) * 3, None)  # ~10 000 token'lık Türkçe/İngilizce metin

    chunks = chunk_pages([*pdf_pages, long_page], real_embedder.count_passage_tokens)

    assert len(chunks) > 20
    # `passage: ` öneki ve özel token'lar dahil sayım; bütçe 350, model sınırı 512.
    assert all(real_embedder.count_passage_tokens(c.text) <= 350 for c in chunks)
    assert max(c.token_count for c in chunks) > 250  # bütçe gerçekten kullanılıyor, parçalar ufalanmıyor
