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
    chunks = chunk_pages([page("  Kısa bir metin.  \n", 4)], count_words, chunk_tokens=10, overlap_tokens=2, min_tokens=0)

    assert chunks == [Chunk(chunk_index=0, page_number=4, text="Kısa bir metin.", token_count=3)]


def test_chunks_never_span_pages_and_indexes_continue_across_pages() -> None:
    pages = [page(" ".join(sentences(6)), 1), page(" ".join(sentences(6)), 2)]

    chunks = chunk_pages(pages, count_words, chunk_tokens=12, overlap_tokens=0, min_tokens=0)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    page_numbers = [c.page_number for c in chunks]
    first_of_page_two = page_numbers.index(2)
    # Önce 1. sayfanın tüm chunk'ları, sonra 2. sayfanınkiler; hiçbiri iki sayfayı karıştırmaz.
    assert set(page_numbers[:first_of_page_two]) == {1}
    assert set(page_numbers[first_of_page_two:]) == {2}


def test_every_chunk_fits_the_token_budget() -> None:
    text = " ".join(sentences(200, words_each=7))

    chunks = chunk_pages([page(text)], count_words, chunk_tokens=20, overlap_tokens=5, min_tokens=0)

    assert len(chunks) > 10
    assert all(count_words(c.text) <= 20 for c in chunks)
    assert all(c.token_count == count_words(c.text) for c in chunks)


def test_splits_at_sentence_ends_when_possible() -> None:
    text = " ".join(sentences(10))  # her cümle 5 kelime; bütçeye 2 cümle sığar

    chunks = chunk_pages([page(text)], count_words, chunk_tokens=12, overlap_tokens=0, min_tokens=0)

    assert all(c.text.endswith(".") for c in chunks)


def test_sentence_end_is_preferred_over_line_break_inside_sentence() -> None:
    # PDF'teki gibi: satır sonu cümlenin ortasında.
    first = "Kullanılmayan iznin en fazla beş günü bir sonraki\nyıla devredilebilir."
    second = "Kalan günler yıl sonunda yanar ve geri alınamaz."

    chunks = chunk_pages([page(f"{first} {second}")], count_words, chunk_tokens=12, overlap_tokens=0, min_tokens=0)

    assert [c.text for c in chunks] == [first, second]


def test_paragraphs_are_never_merged_even_when_budget_allows() -> None:
    # İlgisiz konuları aynı chunk'a toplamak aramayı bozar (ADR-07); her paragraf ayrı chunk.
    paragraphs = [" ".join([f"konu{i}"] * 20) + "." for i in range(3)]

    chunks = chunk_pages([page("\n\n".join(paragraphs))], count_words, chunk_tokens=350, overlap_tokens=50, min_tokens=5)

    assert [c.text for c in chunks] == paragraphs


def test_short_paragraph_joins_the_next_one() -> None:
    # Başlık tek başına anlamsız bir chunk olmasın; altındaki içerikle birlikte kalsın.
    heading = "# İzin Politikası"
    body = " ".join(["izin"] * 30) + "."

    chunks = chunk_pages([page(f"{heading}\n\n{body}\n\nKısa kapanış.")], count_words, chunk_tokens=350, overlap_tokens=50, min_tokens=10)

    assert [c.text for c in chunks] == [f"{heading}\n\n{body}\n\nKısa kapanış."]


def test_short_trailing_paragraph_joins_the_previous_one() -> None:
    first = " ".join(["birinci"] * 20) + "."
    second = " ".join(["ikinci"] * 20) + "."

    chunks = chunk_pages([page(f"{first}\n\n{second}\n\nSon not.")], count_words, chunk_tokens=350, overlap_tokens=50, min_tokens=10)

    assert [c.text for c in chunks] == [first, f"{second}\n\nSon not."]


def test_long_paragraph_is_split_inside_with_overlap() -> None:
    long_paragraph = " ".join(sentences(10))  # 50 kelime, bütçe 15
    other = " ".join(["diğer"] * 12) + "."

    chunks = chunk_pages(
        [page(f"{long_paragraph}\n\n{other}")], count_words, chunk_tokens=15, overlap_tokens=5, min_tokens=5
    )

    assert chunks[-1].text == other  # paragraf sınırı korunur; sonraki paragrafa örtüşme taşınmaz
    assert all(count_words(c.text) <= 15 for c in chunks)
    assert len(chunks) > 3


def test_min_tokens_cannot_exceed_chunk_size() -> None:
    with pytest.raises(ValueError):
        chunk_pages([page("metin")], count_words, chunk_tokens=10, overlap_tokens=0, min_tokens=11)


def test_overlap_repeats_last_sentence_of_previous_chunk() -> None:
    parts = sentences(8)  # 5 kelimelik cümleler; örtüşmeye tam bir cümle sığar

    chunks = chunk_pages([page(" ".join(parts))], count_words, chunk_tokens=15, overlap_tokens=5, min_tokens=0)

    for previous, current in zip(chunks, chunks[1:]):
        last_sentence = previous.text.rsplit(". ", 1)[-1]
        assert current.text.startswith(last_sentence.rstrip("."))


def test_no_text_is_lost_without_overlap() -> None:
    parts = sentences(30)

    chunks = chunk_pages([page(" ".join(parts))], count_words, chunk_tokens=13, overlap_tokens=0, min_tokens=0)

    assert " ".join(c.text for c in chunks) == " ".join(parts)


def test_text_without_separators_is_split_by_characters() -> None:
    chunks = chunk_pages([page("x" * 50)], len, chunk_tokens=20, overlap_tokens=0, min_tokens=0)

    assert [len(c.text) for c in chunks] == [20, 20, 10]


def test_whitespace_only_page_produces_no_chunks() -> None:
    assert chunk_pages([page(" \n\n \t ")], count_words, chunk_tokens=10, overlap_tokens=2, min_tokens=0) == []


@pytest.mark.parametrize("overlap", [-1, 10, 11])
def test_overlap_must_be_smaller_than_chunk_size(overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_pages([page("metin")], count_words, chunk_tokens=10, overlap_tokens=overlap, min_tokens=0)


@pytest.mark.model
def test_real_tokenizer_chunks_stay_within_model_limit(real_embedder: FastEmbedEmbedder) -> None:
    from scripts.embedding_bench.corpus_large import PASSAGES

    count = real_embedder.count_passage_tokens
    fixture = Path(__file__).parent / "fixtures" / "turkish-two-pages.pdf"
    pdf_pages = extract_text("izin.pdf", fixture.read_bytes(), max_mb=10)
    paragraphs_page = page("\n\n".join(PASSAGES.values()), None)  # 55 kısa Türkçe/İngilizce paragraf
    # Paragraf ayırıcısı olmayan ~3 000 token'lık tek blok (ör. boş satırsız PDF sayfası).
    single_block_page = page(" ".join(PASSAGES.values()), None)

    paragraph_chunks = chunk_pages([paragraphs_page], count)
    block_chunks = chunk_pages([*pdf_pages, single_block_page], count)

    # `passage: ` öneki ve özel token'lar dahil sayım; bütçe 350, model sınırı 512.
    assert all(count(c.text) <= 350 for c in [*paragraph_chunks, *block_chunks])
    # Her chunk tek bir paragraftan (ya da kısa paragraf + komşusundan) oluşur; konular karışmaz.
    assert all(c.text.count("\n\n") <= 1 for c in paragraph_chunks)
    assert len(paragraph_chunks) >= 40
    # Paragrafsız uzun metinde bütçe gerçekten kullanılır, parçalar ufalanmaz.
    assert max(c.token_count for c in block_chunks) > 250
