"""Sadece tamamı tanımlı sosyal ifadelerden oluşan mesajlara modelden bağımsız yanıtlar."""

import re
import unicodedata


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("İ", "i").replace("I", "ı").lower()
    # ASCII klavyeyle yazılmış Türkçe biçimleri de kabul et.
    text = text.translate(str.maketrans("çğıöşü", "cgiosu"))
    # Noktalama kelimeleri birleştirmesin; emoji ve diğer semboller korunur.
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return " ".join(text.split())


_GREETING = r"(?:selam(?:lar)?|merhaba(?:lar)?|gunaydin|iyi aksamlar|iyi gunler|iyi geceler)"
_ADDRESS = r"(?:kanka|dostum|knowvia)"
_HOW_ARE_YOU = r"(?:nasilsin|nasilsiniz|nasilsin bakalim|ne haber|naber)"

# fullmatch zorunlu: 'selam, VPN çalışmıyor' hiçbir kuralla eşleşmez.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), answer)
    for pattern, answer in (
        (
            rf"(?:{_GREETING} )?(?:{_ADDRESS} )?{_HOW_ARE_YOU}(?: {_ADDRESS})?",
            "Teşekkürler, iyiyim! Size nasıl yardımcı olabilirim? Belgeleriniz hakkında bir soru sorabilirsiniz.",
        ),
        (
            rf"{_GREETING}(?: {_ADDRESS})?",
            "Merhaba! Erişebildiğiniz şirket belgeleri hakkında size nasıl yardımcı olabilirim?",
        ),
        (
            r"(?:tesekkurler|tesekkur ederim|cok tesekkurler|cok tesekkur ederim|sag ol|sag olun|sagol|sagolun|eyvallah)(?: knowvia)?",
            "Rica ederim! Başka bir sorunuz varsa buradayım.",
        ),
        (
            r"(?:gorusuruz|gorusmek uzere|hosca kal|hosca kalin|hoscakal|hoscakalin|bay bay)",
            "Görüşmek üzere! Belgelerinizle ilgili bir sorunuz olduğunda buradayım.",
        ),
        (
            r"(?:sen kimsin|kimsin|adin ne|senin adin ne|knowvia nedir)",
            "Ben Knowvia, erişim yetkisine duyarlı bilgi asistanınızım. Şirket belgeleriyle ilgili sorularınızı kaynaklarıyla yanıtlarım.",
        ),
        (
            r"(?:ne yapabilirsin|neler yapabilirsin|ne ise yariyorsun|nasil kullanilir|seni nasil kullanabilirim|bana nasil yardimci olabilirsin|yardim|yardimci olur musun)",
            "Erişebildiğiniz belgeler hakkında bir soru sorun; örneğin ‘VPN bağlantı sorununu nasıl çözebilirim?’ "
            "veya ‘Yıllık izin hakkım kaç gün?’. Bulduğum bilgiyi kaynaklarıyla paylaşırım. "
            "Her soru bağımsız değerlendirilir; gerekli ayrıntıları sorunuza ekleyin.",
        ),
        (
            r"(?:orada misin|burada misin|sesim geliyor mu|calisiyor musun)",
            "Buradayım! Belgeleriniz hakkında bir soru sorarak başlayabilirsiniz.",
        ),
        (
            r"(?:tamam|peki|anladim|olur)",
            "Peki! Başka bir sorunuz varsa yardımcı olmaya hazırım.",
        ),
    )
)


def canned_reply(message: str) -> str | None:
    """Tanımsız veya bir belge sorusu içeren mesajlarda normal RAG akışına bırakır."""
    normalized = _normalize(message)
    for pattern, answer in _RULES:
        if pattern.fullmatch(normalized):
            return answer
    return None
