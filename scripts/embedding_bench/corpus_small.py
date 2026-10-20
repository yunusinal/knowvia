"""Küçük sentetik deney verisi: 21 parça, 21 cevaplı ve 5 cevapsız soru."""

PASSAGES: dict[str, str] = {
    "handbook-1": "Çalışan El Kitabı — Mesai ve Ofis Düzeni. Standart çalışma saatleri hafta içi 09:00–18:00 arasıdır; 12:30–13:30 öğle arasıdır. Esnek mesai kapsamındaki çalışanlar güne 08:00 ile 10:00 arasında başlayabilir, ancak 10:00–16:00 arasındaki çekirdek saatlerde ulaşılabilir olmalıdır.",
    "handbook-2": "Çalışan El Kitabı — Kıyafet ve Ziyaretçi Kuralları. Ofiste iş rahatı (smart casual) kıyafet yeterlidir; müşteri toplantılarında resmi kıyafet beklenir. Ziyaretçiler resepsiyonda kayıt yaptırır ve misafir kartını gün sonunda iade eder.",
    "remote2026-1": "Uzaktan Çalışma Politikası (2026, yürürlükte). Çalışanlar haftada en fazla 3 gün uzaktan çalışabilir. Salı ve Perşembe günleri tüm ekipler için ofis günüdür. Uzaktan çalışma günleri yöneticiyle önceden planlanır.",
    "remote2026-2": "Uzaktan Çalışma Politikası (2026) — Ekipman. Şirket, uzaktan çalışan her personele bir kez 2.500 TL ev ofisi ekipman desteği verir. Şirket dizüstü bilgisayarı iç sistemlere yalnızca şirket VPN'i üzerinden bağlanır.",
    "remote2024-1": "Uzaktan Çalışma Politikası (2024, arşiv — yürürlükten kalkmıştır). Çalışanlar haftada en fazla 2 gün uzaktan çalışabilir. Ev ofisi ekipman desteği 1.500 TL olarak uygulanır.",
    "leave-1": "Yıllık İzin Politikası. 1–5 yıl kıdemi olan çalışanlar yılda 14 iş günü, 5–15 yıl arası kıdemi olanlar 20 iş günü, 15 yıldan fazla kıdemi olanlar 26 iş günü ücretli yıllık izin hakkına sahiptir.",
    "leave-2": "Yıllık İzin Politikası — Başvuru ve Devir. İzin talepleri İK portalından en az 7 gün önceden girilir ve yönetici onayıyla kesinleşir. Kullanılmayan iznin en fazla 5 günü bir sonraki yıla devredilebilir; kalan günler yıl sonunda yanar.",
    "hiring-1": "İşe Alım Rehberi (Gizli — yalnızca İK). Yazılım mühendisi pozisyonlarında süreç dört aşamalıdır: ön görüşme, teknik ödev, ekip mülakatı ve referans kontrolü. Teklif onayı için İK direktörü ve bölüm müdürünün imzası gerekir.",
    "hiring-2": "İşe Alım Rehberi — Maaş Bantları (Gizli). Teklif hazırlanırken bandın orta noktası esas alınır; bandın üst sınırını aşan teklifler genel müdür onayına tabidir. Adayla paylaşılan teklif mektubu İK şablonundan üretilir.",
    "vpn-1": "VPN Kurulum Rehberi. Şirket ağına evden erişmek için GlobalConnect istemcisini Yazılım Merkezi'nden kurun. Sunucu adresi olarak vpn.demo.local girin ve şirket e-posta adresinizle oturum açın; ikinci adım doğrulaması için Authenticator uygulamasındaki kodu kullanın.",
    "vpn-2": "VPN Kurulum Rehberi — Mac ve Linux. macOS kullanıcıları istemciyi Self Service uygulamasından indirir. Linux için resmi destek yoktur; açık kaynak OpenConnect istemcisi IT onayıyla kullanılabilir.",
    "vpntr-1": "VPN Sorun Giderme (IT iç). 'Sertifika doğrulanamadı' hatasında önce cihaz saatinin doğru olduğunu kontrol edin, ardından istemci önbelleğini temizleyin. Sorun sürerse cihaz sertifikası MDM konsolundan yeniden dağıtılır.",
    "vpntr-2": "VPN Sorun Giderme — Bağlantı Kopmaları. Bağlantı 30 dakikada bir kopuyorsa kullanıcının ev modeminde MTU değerini 1400'e düşürün. Otel ve kafe ağlarında UDP engelleniyorsa istemciyi TCP 443 moduna alın.",
    "pw-1": "Parola Sıfırlama Prosedürü. Parolanızı unuttuysanız giriş ekranındaki 'Parolamı unuttum' bağlantısına tıklayın, kurumsal e-posta adresinizi girin ve telefonunuza gelen 6 haneli kodu yazın. Yeni parola en az 12 karakter olmalı ve son 5 parolanızdan farklı olmalıdır.",
    "pw-2": "Parola Sıfırlama — Hesap Kilidi. Art arda 5 hatalı girişte hesap 15 dakika kilitlenir. Kilit süresi dolmadan erişim gerekiyorsa IT Servis Masası'nı dahili 4357 numarasından arayın.",
    "incident-1": "Olay Müdahale Planı (IT iç). Bir oltalama e-postasına tıklandığından şüpheleniliyorsa cihaz derhal ağdan ayrılır ve güvenlik ekibine 15 dakika içinde bildirilir. Olay kaydı açılır ve önem derecesi P1–P4 arasında belirlenir.",
    "expense-1": "Harcama Politikası. İş seyahatlerinde günlük yemek harcama limiti yurt içinde 750 TL'dir. Taksi masrafları yalnızca toplu taşımanın mümkün olmadığı durumlarda karşılanır.",
    "expense-2": "Harcama Politikası — Masraf Bildirimi. Masraflar harcamadan sonraki 30 gün içinde Masraf Portalı'na fiş fotoğrafıyla girilir. 5.000 TL üzerindeki harcamalar için önceden bölüm müdürü onayı alınmalıdır; onaylanan masraflar bir sonraki maaşla ödenir.",
    "budget-1": "2026 Bütçe Planı (Gizli — yalnızca Finans). 2026 yılı toplam işletme bütçesi 48 milyon TL olarak planlanmıştır. Pazarlama bütçesi %12 azaltılırken bulut altyapı harcamalarına %20 artış ayrılmıştır.",
    "vendor-1": "Tedarikçi Sözleşme Koşulları (Finans iç). Standart ödeme vadesi fatura tarihinden itibaren 60 gündür. Bir yıldan uzun sözleşmelerde yıllık fiyat artışı TÜFE ile sınırlıdır ve fesih için 90 gün önceden yazılı bildirim gerekir.",
    "laptop-en": "Laptop Security Basics. Lock your screen whenever you leave your desk (Windows+L). Company laptops are encrypted with BitLocker; never disable it. Report a lost or stolen device to IT within 24 hours.",
}

# (soru, beklenen parça, tür)
QUESTIONS: list[tuple[str, str, str]] = [
    ("Tatil hakkım kaç gün? 3 yıldır çalışıyorum.", "leave-1", "farklı kelime"),
    ("Bu yıl kullanamadığım izin günlerine ne olur?", "leave-2", "farklı kelime"),
    ("Evden şirket sistemlerine nasıl bağlanırım?", "vpn-1", "farklı kelime"),
    ("Şifremi hatırlamıyorum, ne yapmalıyım?", "pw-1", "farklı kelime"),
    ("Çok kez yanlış şifre girdim, hesabıma giremiyorum.", "pw-2", "farklı kelime"),
    ("Seyahatte akşam yemeğine en fazla ne kadar harcayabilirim?", "expense-1", "farklı kelime"),
    ("Fişlerimi ne zamana kadar sisteme yüklemem gerekiyor?", "expense-2", "farklı kelime"),
    ("Ofise saat kaçta gelmem gerekiyor?", "handbook-1", "farklı kelime"),
    ("Müşteri görüşmesine ne giymeliyim?", "handbook-2", "farklı kelime"),
    ("Otelde internet var ama VPN bağlanmıyor, sürekli kopuyor.", "vpntr-2", "farklı kelime"),
    ("Linux bilgisayarda uzaktan erişim kurabilir miyim?", "vpn-2", "farklı kelime"),
    ("Şüpheli bir maildeki linke tıkladım, ne yapmalıyım?", "incident-1", "farklı kelime"),
    ("Tedarikçiye faturayı kaç gün içinde ödüyoruz?", "vendor-1", "farklı kelime"),
    ("Gelecek yıl bulut harcamaları ne kadar artacak?", "budget-1", "farklı kelime"),
    ("Mülakat süreci kaç aşamadan oluşuyor?", "hiring-1", "farklı kelime"),
    ("Haftada kaç gün evden çalışabilirim?", "remote2026-1", "eski sürüm tuzağı"),
    ("Ev ofisi için masa sandalye alacağım, şirket ne kadar destek veriyor?", "remote2026-2", "eski sürüm tuzağı"),
    ("How many days of annual leave do I get?", "leave-1", "İngilizce soru → Türkçe belge"),
    ("How do I connect to the company network from home?", "vpn-1", "İngilizce soru → Türkçe belge"),
    ("Bilgisayarımı kaybettim, kime ne zamana kadar haber vermeliyim?", "laptop-en", "Türkçe soru → İngilizce belge"),
    ("Masamdan kalkarken ekranı hangi kısayolla kilitlerim?", "laptop-en", "Türkçe soru → İngilizce belge"),
]

# Cevabı belgelerde olmayan sorular (bazıları bilerek yakın konularda).
NO_ANSWER: list[str] = [
    "Şirket otoparkının aylık ücreti ne kadar?",
    "Doğum izni kaç hafta?",
    "Yemekhanede bugün ne var?",
    "What is the dress code for the New Year party?",
    "Hisse opsiyonu planı nasıl işliyor?",
]
