# Oracle Cloud Always Free üzerinde canlı demo

Bu rehber Knowvia'yı Oracle'ın ücretsiz ARM sunucusunda, kendi alan adınızla ve HTTPS ile yayına alır. Mimari: tek bir uygulama konteyneri (API + Streamlit) ve önünde otomatik HTTPS sağlayan Caddy. Ana adreste (`/`) etkileşimli tanıtım sayfası (`docs/index.html`), `/app/` altında uygulamanın kendisi yayınlanır. Kararların gerekçesi: [ADR-12](adr/12-public-demo-deployment.md).

> Bu bir portföy demosudur: yalnızca sentetik belgelerle çalışır, belge parçaları yapılandırılan LLM sağlayıcısına gönderilir. Gerçek şirket verisi yüklemeyin.

## Gereksinimler

| Kaynak | Değer | Neden |
|---|---|---|
| Sunucu | `VM.Standard.A1.Flex`, 2 OCPU, 12 GB RAM (Always Free sınırı; Oracle 2026'da 4 OCPU / 24 GB'tan düşürdü, güncel sınırı konsoldan kontrol edin) | e5-large modeli ~2.3 GB, uygulama toplam ~3–4 GB RAM kullanır |
| Disk | Varsayılan 50 GB önyükleme diski yeterli | İmaj + model + veri ~6–8 GB |
| İşletim sistemi | Ubuntu 24.04 (aarch64) | Docker resmi paketleri ARM'ı destekler |
| Alan adı | Ücretsiz bir alt alan adı yeterli (ör. [DuckDNS](https://www.duckdns.org)) | Let's Encrypt sertifikası IP adresine değil alan adına verilir |
| LLM anahtarı | Groq (ücretsiz katman) veya OpenAI uyumlu başka bir sağlayıcı | Cevap üretimi |

## 1. Sunucuyu oluşturun

1. Oracle Cloud konsolunda **Compute → Instances → Create instance**.
2. **Image:** Canonical Ubuntu 24.04. **Shape:** Ampere `VM.Standard.A1.Flex`, 2 OCPU ve 12 GB bellek.
3. **SSH anahtarı** ekleyin (kendi açık anahtarınızı yükleyin veya Oracle'ın ürettiği özel anahtarı indirin).
4. Oluşturduktan sonra **Public IP** adresini not edin.

"Out of capacity" hatası alırsanız başka bir Availability Domain deneyin veya bir süre sonra tekrar deneyin; ücretsiz ARM kapasitesi bölgeye göre dolabiliyor.

## 2. 80 ve 443 portlarını açın

Oracle'da iki ayrı güvenlik duvarı vardır; ikisinde de açılmalıdır.

**a) Ağ (Security List):** Instance → Subnet → Security List → **Add Ingress Rules**:

| Source CIDR | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

**b) Sunucunun kendi iptables kuralları** (Oracle'ın Ubuntu imajları 22 dışındaki portları reddeder). SSH ile bağlanın:

```bash
ssh ubuntu@<PUBLIC_IP>
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Alan adını sunucuya yönlendirin

DuckDNS örneği: duckdns.org'da bir alt alan adı oluşturun (ör. `knowvia-demo`) ve **current ip** alanına sunucunun Public IP adresini yazın. Birkaç dakika içinde `knowvia-demo.duckdns.org` sunucunuzu gösterir. Kontrol:

```bash
getent hosts knowvia-demo.duckdns.org   # Public IP'yi göstermeli
```

## 4. Docker'ı kurun

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit   # oturumu kapatıp yeniden bağlanın ki grup değişikliği geçerli olsun
ssh ubuntu@<PUBLIC_IP>
docker version && docker compose version
```

## 5. Projeyi indirip ayarlayın

```bash
git clone https://github.com/yunusinal/knowvia.git
cd knowvia
cp .env.example .env
```

`.env` dosyasını düzenleyin (`nano .env`). Sunucuda **gerçek değerler bu dosyada olmalıdır**; konteyner yalnızca bu dosyayı okur.

| Ayar | Ne yazılmalı |
|---|---|
| `JWT_SECRET_KEY` | En az 32 karakter rastgele: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DEMO_USER_PASSWORD` | Ziyaretçilere açıklanacak üye parolası (ör. `knowvia-demo`) |
| `KNOWVIA_PUBLIC_DEMO_PASSWORD` | `DEMO_USER_PASSWORD` ile aynı; giriş ekranında üye hesaplarıyla birlikte gösterilir |
| `ADMIN_PASSWORD` | Uzun, gizli, farklı bir parola; **kimseyle paylaşmayın** (admin belge yükleyip silebilir) |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | LLM sağlayıcınız (örnek dosyada Groq) |
| `KNOWVIA_DOMAIN` | Alan adınız, ör. `knowvia-demo.duckdns.org` |

`DATABASE_URL`, `QDRANT_PATH`, `MODEL_CACHE_DIR`, `GPU_ENABLED` ve `WARMUP_ON_START` değerlerini `docker-compose.yml` kalıcı birime göre zaten ayarlar; `.env`'deki değerleri önemli değildir.

Dosyanın izinlerini kısıtlayın:

```bash
chmod 600 .env
```

## 6. Başlatın

```bash
docker compose up -d --build
docker compose logs -f app
```

İlk açılışta şunlar olur (ARM sunucuda toplam ~10–20 dakika):

1. İmaj derlenir (bağımlılıklar `uv.lock` sürümleriyle kurulur).
2. Demo kullanıcıları ve 13 sentetik belge yüklenir; embedding modeli (~2.3 GB) indirilir.
3. API modelleri belleğe yükler (`WARMUP_ON_START`), ardından arayüz hazır olur.

`docker compose ps` çıktısında `app` için **healthy** görünce `https://<KNOWVIA_DOMAIN>` adresini açın: tanıtım sayfası gelir, "Canlı demoyu dene" uygulamaya (`https://<KNOWVIA_DOMAIN>/app/`) geçer. Caddy sertifikayı ilk istekte alır; birkaç saniye sürebilir.

**ARM doğrulaması** (imaj yalnızca x86_64'te çalıştırılarak denendi; ARM'da ilk kez burada çalışır):

```bash
docker compose exec app python -c "import platform, onnxruntime, fastembed, py_rust_stemmers; print(platform.machine(), onnxruntime.__version__, onnxruntime.get_available_providers())"
# Beklenen: aarch64 1.30.0 [... 'CPUExecutionProvider']
docker compose logs app | grep -E "demo kullanıcısı|demo belgesi|startup complete"
# Beklenen: 4 kullanıcı ve 13 belge (ilk açılış), ardından "Application startup complete."
```

Ardından tarayıcıda bir üye hesabıyla giriş yapıp örnek bir soru sorun; cevabın altında kaynak kartı ve süre satırı görünmelidir.

Sonraki açılışlarda kullanıcı ve belgeler tekrar oluşturulmaz, model indirilmez.

## 7. Günlük demo sıfırlama

Ziyaretçi sohbetleri ve destek talepleri birikmesin diye her gece temizlenir; kullanıcılar ve belgeler korunur:

```bash
crontab -e
# Her gece 04:00 (sunucu saati):
0 4 * * * cd /home/ubuntu/knowvia && docker compose exec -T app python -m scripts.reset_demo >> /home/ubuntu/knowvia-reset.log 2>&1
```

Elle çalıştırmak için: `docker compose exec app python -m scripts.reset_demo`.

## 8. Güncelleme, yedek, sorun giderme

**Güncelleme:**

```bash
cd ~/knowvia && git pull && docker compose up -d --build
```

**Yedek** (SQLite + Qdrant + model, tek birimde):

```bash
docker run --rm -v knowvia_knowvia-data:/data -v "$PWD":/backup alpine tar czf /backup/knowvia-data.tgz -C /data app.db qdrant
```

**Sık karşılaşılanlar:**

| Belirti | Neden / çözüm |
|---|---|
| Tarayıcı bağlanamıyor | 2. adımdaki iki güvenlik duvarından biri kapalı; `sudo iptables -L INPUT -n --line-numbers` |
| Caddy sertifika alamıyor | Alan adı henüz Public IP'yi göstermiyor (3. adım) veya 80 portu kapalı |
| `app` sürekli yeniden başlıyor | `docker compose logs app`; çoğunlukla `.env`'de eksik `JWT_SECRET_KEY` (32+ karakter) veya `DEMO_USER_PASSWORD` |
| Sohbet "kurulum hatası" (503) veriyor | `LLM_API_KEY` eksik veya geçersiz |
| "Çok fazla istek" (429) | Dakikalık istek sınırı; `CHAT_LIMIT_*` ayarlarıyla değiştirilebilir |

## Güvenlik notları

- Dışarı yalnızca 80/443 (Caddy) açıktır; API konteynerin içinde `127.0.0.1:8000`'de kalır, arayüz de yalnızca Caddy üzerinden erişilir.
- Ziyaretçiler yalnızca üye hesaplarıyla girer; admin parolası ayrıdır ve giriş ekranında gösterilmez. E-posta başına giriş denemesi ve kullanıcı başına/genel sohbet istekleri dakikalık sınırlıdır.
- Konteyner root olmayan bir kullanıcıyla çalışır; sırlar yalnızca sunucudaki `.env` dosyasındadır ve imaja girmez (`.dockerignore`).
- Oracle, uzun süre çok düşük kullanımda kalan Always Free sunucuları geri alabileceğini belirtir; demo kullanılmadığı dönemlerde sunucunun durumunu kontrol edin.
