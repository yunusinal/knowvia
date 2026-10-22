# Knowvia

Erişim yetkisine duyarlı bir RAG bilgi asistanı. Kullanıcılar şirket belgelerine doğal dille soru sorar; cevaplar yalnızca erişebildikleri belgelerden hazırlanır ve kaynaklarıyla gösterilir.

Sentetik belgeler ve demo hesaplarıyla çalışan, geliştirme aşamasındaki yerel bir portföy projesidir.

## Neler yapıyor?

- PDF, TXT ve Markdown belgelerini yükleme, indeksleme ve silme (admin).
- Departman ve şirket geneli görünürlüğüne göre belge erişimi.
- Yetkili belgelerde anlamsal arama ve dosya adı, sayfa, alıntı içeren kaynaklı cevaplar.
- Yeterli bilgi bulunamadığında sabit ret cevabı.
- Selamlama ve teşekkür gibi tanımlı mesajlara LLM kullanmadan hazır yanıt.
- Takip sorularında aynı sohbetin önceki kullanıcı sorularını ve asistan yanıtlarını bağlam bütçesine göre kullanma.
- Belgedeki adımlar sorunu çözmediğinde destek talebi taslağı: model yalnızca taslak önerir (tool calling), talep kullanıcı onaylayınca oluşturulur. Üye kendi taleplerini, admin tüm talepleri görür.

**Teknolojiler:** Python, FastAPI, Streamlit, SQLite / SQLAlchemy, Qdrant local, FastEmbed (`multilingual-e5-large`), JWT ve Argon2. Cevap üretimi için OpenAI uyumlu bir LLM sağlayıcısı kullanılır.

**Akış:** Streamlit → FastAPI → SQLite erişim kontrolü → filtreli Qdrant araması → SQLite son kontrolü → LLM → kaynaklı cevap.

## Yerel kurulum

Python 3.11+ ve `uv` gereklidir. Aşağıdaki komutlar Windows PowerShell içindir; proje kökünde çalıştırın.

```powershell
uv sync --locked
Copy-Item .env.example .env
```

`.env` kopyalama adımını yalnız ilk kurulumda uygulayın; mevcut ayarlarınızın üzerine yazmayın. Dosyada şu alanları düzenleyin:

- `DEMO_USER_PASSWORD`: Demo hesapları için kendi belirlediğiniz ortak parola.
- `JWT_SECRET_KEY`: En az 32 karakterlik rastgele anahtar. Üretmek için:

  ```powershell
  uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

- `LLM_API_KEY`: Seçtiğiniz sağlayıcının API anahtarı. `LLM_BASE_URL` ve `LLM_MODEL` değerlerini de sağlayıcınıza göre ayarlayın; örnek dosyada Groq yapılandırması bulunur.

`.env` dosyasını ve `data/runtime/` içeriğini paylaşmayın. Kaynak belge parçaları yanıt üretimi için seçtiğiniz LLM sağlayıcısına gönderilir; demoda yalnız sentetik veri kullanın.

API sunucusu **kapalıyken** demo verilerini hazırlayın:

```powershell
uv run python -m scripts.seed_users
uv run python -m scripts.seed_demo_documents
```

İlk indekslemede embedding modeli indirilir (yaklaşık 2,3 GB); süre bağlantınıza ve donanımınıza bağlıdır. Qdrant için ayrı sunucu gerekmez. Seed komutları mevcut kullanıcıları ve aynı içerikteki belgeleri tekrar eklemez; mevcut hesapların parolasını değiştirmez.

## Çalıştırma

Birinci terminalde API'yi başlatın:

```powershell
uv run uvicorn app.main:app --reload
```

İkinci terminalde, yine proje kökünden arayüzü başlatın:

```powershell
uv run streamlit run frontend/streamlit_app.py
```

Arayüz: http://localhost:8501 · API dokümanı: http://127.0.0.1:8000/docs

Qdrant local aynı veri klasörünü yalnızca tek süreçte açabilir. API çalışırken belge seed komutunu çalıştırmayın ve birden fazla API worker kullanmayın.

## Demo hesapları

Parola, ilk seed sırasında `.env` içindeki `DEMO_USER_PASSWORD` değeridir.

| Hesap | Erişim |
|---|---|
| `admin@demo.local` | Tüm aktif belgeler; yükleme ve silme |
| `it@demo.local` | Şirket geneli ve IT departmanı belgeleri |
| `hr@demo.local` | Şirket geneli ve İK departmanı belgeleri |
| `finance@demo.local` | Şirket geneli ve Finans departmanı belgeleri |

IT hesabıyla “VPN sertifika doğrulanamadı hatası veriyor, ne yapmalıyım?” sorusunu deneyin. Ardından “2026 yılında bulut altyapı harcamalarına yüzde kaç artış ayrıldı?” sorusunu IT ve Finans hesaplarıyla ayrı ayrı sorun: IT için sabit ret, Finans için kaynaklı cevap beklenir.

## Testler

```powershell
uv run pytest -q
```

API testleri sahte embedding ve LLM kullanır; sağlayıcı anahtarı gerektirmez. Gerçek embedding modelini kullanan testler model önbellekte yoksa atlanır. Teknik kararlar ve ölçümler için [ADR dizinine](docs/adr/README.md) bakabilirsiniz.

## Mini RAG ölçümü

22 sentetik soruluk başlangıç ölçümü, mevcut Groq `openai/gpt-oss-120b` ve `multilingual-e5-large` ayarlarıyla 2026-10-22 tarihinde yapıldı. Bu küçük test setindeki sonuçlar: Recall@5 **16/16**, etiketli cevap olgularının kapsanması **16/16**, çekimserlik **22/22**, kaynak doğruluğu **22/22**, ACL sızıntısı **0**. Retrieval süresi ortalama/medyan **61/58 ms**; LLM üretimi (17 çağrı) **3070/2511 ms**; uçtan uca **2433/834 ms** ölçüldü. Bunlar bu sentetik küme ve yerel konfigürasyon için bir başlangıç ölçümüdür; genel başarı veya hız garantisi değildir.

Ölçümü tekrarlamak için API sunucusunu çalıştırmak gerekmez; corpus, SQLite ve Qdrant bellek içinde hazırlanır. Komut gerçek LLM sağlayıcısına istek gönderir ve sonucu `eval/results/` altına yazar:

```powershell
uv run python -m scripts.rag_eval
```

## Mevcut sınırlar

- Yerel demo kapsamındadır; üretim ortamına hazır bir kurumsal sistem iddiası taşımaz.
- Sohbetler kullanıcı hesabına bağlı olarak SQLite'ta saklanır. Takip sorusunda önceki soru ve yanıtlar bütçeye göre seçilir; kaynakların güncel erişim yetkisi yeniden denetlenir. Eski yanıtlar kanıt sayılmaz.
- Destek talepleri yerel SQLite'ta tutulur; gerçek bir yardım masasına gönderilmez ve durum akışı yalnızca "açık"tır. Talep önerisi, LLM sağlayıcısının tool calling desteğine bağlıdır.
- Taranmış PDF / OCR, DOCX ve görsel içerik işleme desteklenmez.
- LLM ayarlanmadan belge soruları kurulum hatası verir; tanımlı hazır sosyal yanıtlar çalışmaya devam eder.
- Belge silme yeni aramalarda erişimi hemen keser. O belgeye dayanan eski cevaplar sohbet geçmişinde gizlenir ve yeni bağlama alınmaz, ancak metinleri SQLite'ta kalır; sohbet silme ve saklama süresi politikası henüz yok.
