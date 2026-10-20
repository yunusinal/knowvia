"""Yüklenen belgeyi doğrular ve metnini çıkarır: PDF sayfa sayfa, TXT/MD tek parça."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath

from pypdf import PasswordType, PdfReader

ALLOWED_EXTENSIONS = frozenset({".pdf", ".txt", ".md"})

# PDF standardı başlığın ilk 1024 bayt içinde olmasına izin verir.
_PDF_SIGNATURE = b"%PDF-"
_PDF_SIGNATURE_WINDOW = 1024
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


@dataclass(frozen=True)
class ExtractedPage:
    # PDF'te 1'den başlayan sayfa numarası; TXT/MD'de sayfa yoktur (None).
    page_number: int | None
    text: str


class ExtractionError(Exception):
    """Belge reddedildi. `code` sabittir (test ve API için); `message` kullanıcıya gösterilebilir."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def extract_text(filename: str, content: bytes, max_mb: int) -> list[ExtractedPage]:
    """Dosyayı doğrular ve metin içeren sayfaları döndürür; uygun değilse ExtractionError fırlatır.

    Kontroller ucuzdan pahalıya sıralanır: boyut → uzantı → içerik → ayrıştırma.
    Uzantı yalnızca bir iddiadır; içerik ayrıca kontrol edilir.
    """
    if not content:
        raise ExtractionError("empty_file", "Dosya boş.")
    if len(content) > max_mb * 1024 * 1024:
        raise ExtractionError("too_large", f"Dosya en fazla {max_mb} MB olabilir.")

    extension = PurePath(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ExtractionError("unsupported_type", "Yalnızca PDF, TXT ve MD dosyaları desteklenir.")

    if extension == ".pdf":
        return _extract_pdf(content)
    return _extract_plain_text(content)


def _extract_plain_text(content: bytes) -> list[ExtractedPage]:
    if content.startswith(_UTF16_BOMS):
        raise ExtractionError("not_utf8", "Metin dosyası UTF-8 kodlamasında olmalı.")
    if b"\x00" in content:
        raise ExtractionError("not_text", "Dosya metin değil, ikili veri içeriyor.")
    try:
        # utf-8-sig: Windows araçlarının eklediği BOM işaretini atar.
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ExtractionError("not_utf8", "Metin dosyası UTF-8 kodlamasında olmalı.") from None

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ExtractionError("no_text", "Dosyada metin yok.")
    return [ExtractedPage(page_number=None, text=text)]


def _extract_pdf(content: bytes) -> list[ExtractedPage]:
    invalid = ExtractionError("invalid_pdf", "Dosya geçerli bir PDF değil veya bozuk.")
    if _PDF_SIGNATURE not in content[:_PDF_SIGNATURE_WINDOW]:
        raise invalid

    # Güvenilmeyen dosya: ayrıştırıcının herhangi bir hatası belgeyi reddeder (fail closed).
    try:
        reader = PdfReader(BytesIO(content))
    except Exception:
        raise invalid from None

    if reader.is_encrypted:
        # Yalnızca kısıt koyan (boş parolalı) PDF'ler açılabilir; parola isteyenler reddedilir.
        try:
            opened = reader.decrypt("") != PasswordType.NOT_DECRYPTED
        except Exception:
            opened = False
        if not opened:
            raise ExtractionError("encrypted_pdf", "Parola korumalı PDF'ler desteklenmez.")

    try:
        texts = [page.extract_text() for page in reader.pages]
    except Exception:
        raise invalid from None
    if not texts:
        raise invalid

    # Boş sayfalar atlanır ama numaralar korunur: kaynakta "sayfa 3" gerçekten 3. sayfa olmalı.
    pages = [
        ExtractedPage(page_number=number, text=text)
        for number, text in enumerate(texts, start=1)
        if text.strip()
    ]
    if not pages:
        raise ExtractionError(
            "no_text",
            "PDF'te okunabilir metin yok (taranmış belge olabilir); OCR desteklenmiyor.",
        )
    return pages
