import re
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.services.extraction import ExtractedPage, ExtractionError, extract_text

MAX_MB = 1
FIXTURES = Path(__file__).parent / "fixtures"


def make_text_pdf(page_texts: list[str]) -> bytes:
    """Her sayfasına verilen metni yazan en küçük geçerli PDF'i üretir (boş metin = boş sayfa).

    Standart Helvetica fontu kullanıldığı için yalnızca ASCII metin desteklenir.
    """
    page_count = len(page_texts)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(page_count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(page_texts):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_offset = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_offset)
    return bytes(out)


def write_pdf(writer: PdfWriter) -> bytes:
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def encrypted_pdf(user_password: str) -> bytes:
    writer = PdfWriter()
    writer.append(BytesIO(make_text_pdf(["Secret page"])))
    # RC4 ek kütüphane gerektirmez; burada yalnızca test dosyası üretmek için kullanılıyor.
    writer.encrypt(user_password=user_password, owner_password="owner", algorithm="RC4-128")
    return write_pdf(writer)


def assert_rejected(filename: str, content: bytes, code: str) -> None:
    with pytest.raises(ExtractionError) as exc_info:
        extract_text(filename, content, max_mb=MAX_MB)
    assert exc_info.value.code == code


def test_txt_keeps_turkish_text_as_single_page_without_number() -> None:
    text = "Yıllık izin: 1–5 yıl kıdemde 14 iş günü. Çalışanlar İK portalından başvurur."

    pages = extract_text("izin.txt", text.encode("utf-8"), max_mb=MAX_MB)

    assert pages == [ExtractedPage(page_number=None, text=text)]


def test_md_strips_bom_and_normalizes_line_endings() -> None:
    content = "\ufeff# VPN Kurulumu\r\nAdım 1: İstemciyi kurun.\r\n".encode("utf-8")

    pages = extract_text("vpn.md", content, max_mb=MAX_MB)

    assert pages[0].text == "# VPN Kurulumu\nAdım 1: İstemciyi kurun.\n"


def test_pdf_returns_pages_with_original_numbers_and_skips_blank_pages() -> None:
    content = make_text_pdf(["First page text", "", "Third page text"])

    pages = extract_text("policy.pdf", content, max_mb=MAX_MB)

    assert [p.page_number for p in pages] == [1, 3]
    assert "First page text" in pages[0].text
    assert "Third page text" in pages[1].text


def test_turkish_pdf_text_is_extracted_intact() -> None:
    # Sentetik içerikli, Edge (Chromium) "PDF olarak yazdır" ile üretilmiş gerçek bir PDF.
    content = (FIXTURES / "turkish-two-pages.pdf").read_bytes()

    pages = extract_text("izin.pdf", content, max_mb=10)

    # PDF görsel satırlara böler; cümle içindeki satır sonları karşılaştırmadan önce boşluğa çevrilir.
    first, second = (re.sub(r"\s+", " ", page.text) for page in pages)
    assert [p.page_number for p in pages] == [1, 2]
    assert "Yıllık İzin Politikası" in first
    assert "Kullanılmayan iznin en fazla 5 günü bir sonraki yıla devredilebilir." in first
    assert "Pijamalı hasta yağız şoföre çabucak güvendi." in first
    assert "PİJAMALI HASTA YAĞIZ ŞOFÖRE ÇABUCAK GÜVENDİ." in first
    assert "Uzaktan Çalışma Politikası (2026)" in second
    assert "Şirket, ev ofisi için 2.500 TL ekipman desteği verir." in second
    assert all(letter in first + second for letter in "çğıöşüÇĞİÖŞÜ")


def test_extension_check_is_case_insensitive() -> None:
    pages = extract_text("Policy.PDF", make_text_pdf(["Hello"]), max_mb=MAX_MB)

    assert pages[0].page_number == 1


def test_pdf_with_empty_user_password_is_opened() -> None:
    # Yalnızca yazdırma/kopyalama kısıtı olan PDF'ler parola sormadan açılır.
    pages = extract_text("restricted.pdf", encrypted_pdf(user_password=""), max_mb=MAX_MB)

    assert "Secret page" in pages[0].text


def test_size_limit_is_checked_before_parsing() -> None:
    too_big = b"%PDF-" + b"x" * (MAX_MB * 1024 * 1024)

    assert_rejected("big.pdf", too_big, "too_large")


def test_file_at_exact_size_limit_is_accepted() -> None:
    content = b"a" * (MAX_MB * 1024 * 1024)

    pages = extract_text("limit.txt", content, max_mb=MAX_MB)

    assert len(pages[0].text) == MAX_MB * 1024 * 1024


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("empty.txt", b"", "empty_file"),
        ("notes.docx", b"some text", "unsupported_type"),
        ("no_extension", b"some text", "unsupported_type"),
        ("fake.pdf", b"This is plain text renamed to .pdf", "invalid_pdf"),
        ("broken.pdf", b"%PDF-1.4\nthis is not a real pdf body", "invalid_pdf"),
        ("binary.txt", b"abc\x00def", "not_text"),
        ("cp1254.txt", "Şifre değişikliği".encode("cp1254"), "not_utf8"),
        ("utf16.txt", "Merhaba".encode("utf-16"), "not_utf8"),
        ("blank.md", b"  \n\t\n", "no_text"),
    ],
)
def test_invalid_files_are_rejected_with_code(filename: str, content: bytes, code: str) -> None:
    assert_rejected(filename, content, code)


def test_pdf_without_text_layer_is_rejected() -> None:
    # Taranmış belgeyi temsil eder: sayfalar var ama metin katmanı yok.
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)

    assert_rejected("scanned.pdf", write_pdf(writer), "no_text")


def test_password_protected_pdf_is_rejected() -> None:
    assert_rejected("locked.pdf", encrypted_pdf(user_password="secret"), "encrypted_pdf")


def test_error_message_does_not_leak_file_details() -> None:
    with pytest.raises(ExtractionError) as exc_info:
        extract_text("C:/Users/someone/secret-plan.pdf", b"not a pdf", max_mb=MAX_MB)

    assert "secret-plan" not in exc_info.value.message
    assert "Users" not in exc_info.value.message
