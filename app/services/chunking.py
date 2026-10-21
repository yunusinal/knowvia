"""Sayfa metnini paragraf sınırlarını koruyarak token bütçesine sığan chunk'lara böler.

Her paragraf kendi chunk'ıdır; farklı paragraflar birleştirilmez, çünkü ilgisiz konuları aynı
chunk'ta toplamak aramayı bozar (ölçüm: docs/adr/07-paragraph-chunking-and-threshold.md).
Çok kısa paragraflar (başlık, not satırı) bir sonrakiyle birleşir; bütçeyi aşan paragraf
cümle ve kelime sınırlarından, örtüşmeli olarak bölünür.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.services.extraction import ExtractedPage

PARAGRAPH_SEPARATOR = "\n\n"

# Bütçeyi aşan paragraf içinde sırayla denenen ayırıcılar. Cümle sonu tek satır sonundan önce
# gelir: PDF metni görsel satırlarda bölündüğü için "\n" çoğu zaman cümlenin ortasındadır.
SEPARATORS: tuple[str, ...] = (". ", "? ", "! ", "\n", "; ", ", ", " ")

TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class Chunk:
    # Belge içindeki sıra (0'dan başlar); kaynak gösterirken kararlı kimlik olarak kullanılır.
    chunk_index: int
    page_number: int | None
    text: str
    token_count: int


def chunk_pages(
    pages: Sequence[ExtractedPage],
    count_tokens: TokenCounter,
    chunk_tokens: int = 350,
    overlap_tokens: int = 50,
    min_tokens: int = 50,
) -> list[Chunk]:
    """Sayfaları chunk'lara böler; bir chunk asla iki sayfaya yayılmaz (sayfa numarası kesin kalır).

    `count_tokens` modelin gördüğü metni saymalıdır (önek ve özel token'lar dahil);
    her chunk için `count_tokens(chunk.text) <= chunk_tokens` garanti edilir.
    `min_tokens` altındaki paragraflar bir sonraki paragrafla birleştirilir.
    """
    if not 0 <= overlap_tokens < chunk_tokens:
        raise ValueError("overlap_tokens 0 ile chunk_tokens arasında olmalı.")
    if not 0 <= min_tokens <= chunk_tokens:
        raise ValueError("min_tokens 0 ile chunk_tokens arasında olmalı.")

    chunks: list[Chunk] = []
    for page in pages:
        for paragraph in _paragraph_units(page.text, count_tokens, min_tokens):
            pieces = _atomize(paragraph, count_tokens, chunk_tokens, SEPARATORS)
            for text in _merge(pieces, count_tokens, chunk_tokens, overlap_tokens):
                stripped = text.strip()
                if stripped:
                    chunks.append(
                        Chunk(
                            chunk_index=len(chunks),
                            page_number=page.page_number,
                            text=stripped,
                            token_count=count_tokens(stripped),
                        )
                    )
    return chunks


def _paragraph_units(text: str, count_tokens: TokenCounter, min_tokens: int) -> list[str]:
    """Metni paragraflara ayırır; `min_tokens` altındaki paragrafı sonrakine katar.

    Başlık gibi kısa satırlar böylece altındaki içerikle aynı chunk'ta kalır. Sayfanın sonunda
    kısa bir parça kalırsa önceki paragrafa eklenir.
    """
    units: list[str] = []
    pending = ""
    for paragraph in (p.strip() for p in text.split(PARAGRAPH_SEPARATOR)):
        if not paragraph:
            continue
        pending = f"{pending}{PARAGRAPH_SEPARATOR}{paragraph}" if pending else paragraph
        if count_tokens(pending) >= min_tokens:
            units.append(pending)
            pending = ""
    if pending:
        if units:
            units[-1] = f"{units[-1]}{PARAGRAPH_SEPARATOR}{pending}"
        else:
            units.append(pending)
    return units


def _atomize(
    text: str, count_tokens: TokenCounter, limit: int, separators: Sequence[str]
) -> list[str]:
    """Metni, her biri tek başına bütçeye sığan parçalara ayırır; ayırıcılar parçanın sonunda kalır."""
    if count_tokens(text) <= limit:
        return [text]
    for position, separator in enumerate(separators):
        if separator in text:
            pieces: list[str] = []
            for part in _split_keeping_separator(text, separator):
                pieces.extend(_atomize(part, count_tokens, limit, separators[position + 1 :]))
            return pieces
    return _split_by_characters(text, count_tokens, limit)


def _split_keeping_separator(text: str, separator: str) -> list[str]:
    parts = text.split(separator)
    with_separator = [part + separator for part in parts[:-1]] + [parts[-1]]
    return [part for part in with_separator if part]


def _split_by_characters(text: str, count_tokens: TokenCounter, limit: int) -> list[str]:
    """Ayırıcısı olmayan çok uzun metin (ör. boşluksuz dize) için son çare: sığan en uzun önekler."""
    pieces: list[str] = []
    while text:
        low, high = 1, len(text)
        while low < high:  # sığan en uzun öneki ikili arama ile bul
            middle = (low + high + 1) // 2
            if count_tokens(text[:middle]) <= limit:
                low = middle
            else:
                high = middle - 1
        pieces.append(text[:low])
        text = text[low:]
    return pieces


def _merge(
    pieces: Sequence[str], count_tokens: TokenCounter, limit: int, overlap: int
) -> list[str]:
    """Bir paragrafın parçalarını bütçe dolana kadar birleştirir; yeni chunk öncekinin son parçalarıyla başlar."""
    chunks: list[str] = []
    current: list[str] = []
    for piece in pieces:
        if current and count_tokens("".join([*current, piece])) > limit:
            chunks.append("".join(current))
            current = _overlap_tail(current, count_tokens, overlap)
            while current and count_tokens("".join([*current, piece])) > limit:
                current.pop(0)
        current.append(piece)
    if current:
        chunks.append("".join(current))
    return chunks


def _overlap_tail(pieces: list[str], count_tokens: TokenCounter, overlap: int) -> list[str]:
    """Bütün parçalardan (cümle, satır) oluşan, `overlap` token'ı aşmayan en uzun son kısım."""
    tail: list[str] = []
    for piece in reversed(pieces):
        if count_tokens("".join([piece, *tail])) > overlap:
            break
        tail.insert(0, piece)
    return tail
