# Haber Akışı

Google Haberler RSS'inden her gün **30 haber** derleyip Tailwind tabanlı bir **PWA**'da sunan bülten.
İki kullanım biçimi var: kartlar arasında elle gezinme, ya da **hands-free** dinleme — okunan haber öne gelir, bitince sıradaki gelir.

Kategoriler: **Türkiye**, **Bilim & Teknoloji**, **Spor** (her birinden 10 haber).

## Hızlı başlangıç

Python 3.10+ yeterli, **pip bağımlılığı yok** (yalnızca standart kütüphane).

```bash
python -m mynews health     # 4 feed'in durumu
python -m mynews rank       # seçilen haberler + skor kırılımı
python -m mynews build      # site/data/latest.json üret

cd site && python -m http.server 8765
# http://127.0.0.1:8765
```

## Nasıl çalışıyor?

### Önem sinyali: kaç kaynak yazdı

Google Haberler RSS'inde her öğenin `<description>` alanı, aynı olayın farklı yayıncılardaki
hallerini `<ol><li>` listesi olarak veriyor. Bu liste doğrudan bir önem sinyali:

```
Gökçek'in oğlu adli kontrolle serbest bırakıldı      → 5 kaynak
"Yapay zeka akım başlattı: Ünlü isimler ışınlandı"   → 1 kaynak
```

Gerçek gündem maddeleri 4-5 kaynakta çıkıyor, tıklama tuzağı tek kaynakta kalıyor.
Skor şöyle: `log2(1+kaynak) × w1 + tazelik × w2 + yayıncı güveni × w3 − clickbait cezası`

### Filtreler

- **Format elemesi** — "Canlı Anlatım", "Puan Durumu", "Hangi kanalda", burç/hava durumu…
- **Clickbait cezası** — "flaş", "şok", "sayılı gün kaldı", ünlem yoğunluğu, tamamı büyük harf
- **Yayıncı güveni** — `config/settings.json` içinde kaynak bazlı ağırlık
- **Tekrar elemesi** — benzer başlıklar (Jaccard) tek habere iner; yayıncı başına en fazla 3 haber

**Segment bazlı ayar:** Google, Bilim ve Teknoloji feed'lerinde kümeleme yapmıyor — orada her haber
tek kaynak görünüyor, yani ana sinyal çalışmıyor. Bu yüzden o segmentte yayıncı güveni ve clickbait
cezası ağırlıklandırılıyor (`scoring_override`), ayrıca `min_trust` eşiği içerik çiftliklerini eliyor.

### Ses

Öncelik sırası:

1. **Hazır ses dosyası** — `python -m mynews build --with-audio` ile üretilmişse (haber başına bir dosya)
2. **Tarayıcının Türkçe sesi** — Web Speech API; anahtar gerekmez, varsayılan olarak bu çalışır

İki TTS motoru destekleniyor, anahtarı tanımlı olan seçilir:

| Motor | Ortam değişkeni | API |
|---|---|---|
| ElevenLabs | `ELEVENLABS_API_KEY` | `POST /v1/text-to-dialogue` (Eleven v3) |
| Gemini | `GEMINI_API_KEY` | `gemini-2.5-flash-preview-tts` |

Bülteni tek uzun MP3'te birleştirmek yerine **haber başına bir dosya** üretiliyor. Böylece ffmpeg
bağımlılığı, zaman damgası senkronu ve uzun üretimde kalite kaybı sorunlarının üçü de ortadan kalkıyor.

## Bilinçli sınırlar

Google Haberler RSS'inin verdikleri ve vermedikleri araştırmayla doğrulandı:

| Var | Yok |
|---|---|
| Başlık | **Makale gövdesi** — `description` yalnızca ilgili haber listesi |
| Yayıncı adı ve alan adı (`<source url>`) | **Görsel** — `media:content`/`enclosure`/`thumbnail` hiçbiri yok |
| Yayın zamanı | **Yayıncıya doğrudan link** — bkz. aşağıda |
| Aynı olayın diğer kaynaklardaki başlıkları | |

**Linkler `CBMi…` biçiminde kodlu ve sunucu tarafında çözülemiyor.** Makale sayfası tam Chrome
User-Agent'ıyla çekildiğinde 592 KB HTML dönüyor ve içinde tek bir yayıncı URL'si bulunmuyor
(yalnızca `angular.dev/license`); yönlendirmeyi tarayıcıda JS yapıyor. Bu yüzden kartlardaki bağlantı
Google Haberler bağlantısıdır — tarayıcıda tıklanınca yayıncıya gider.

**Seslendirme başlıkla sınırlı.** Gövde metni olmadığı için LLM'e serbest metin yazdırmıyoruz;
`speech` alanı yalnızca başlık, yayıncı adı ve kaç kaynağın yazdığından oluşuyor. Uydurma riski
böylece tasarımdan kaldırılmış oluyor. Görsel de üretmiyoruz — kartlar yayıncı favicon'u ve tipografi
üzerine kurulu.

## Yayına alma (GitHub Pages)

`.github/workflows/daily.yml` her gün 06:00'da (TR) çalışır: feed sağlığını kontrol eder, bülteni
üretir, testleri koşar, `site/data`'yı işler ve Pages'e dağıtır.

```bash
git init && git add . && git commit -m "İlk sürüm"
git branch -M main
git remote add origin git@github.com:<kullanıcı>/<repo>.git
git push -u origin main
```

Ardından depo ayarlarından **Settings → Pages → Source: GitHub Actions** seçin.
Ses üretimi istiyorsanız `ELEVENLABS_API_KEY` veya `GEMINI_API_KEY` değerini
**Settings → Secrets and variables → Actions** altına ekleyin ve workflow'daki build adımını
`python -m mynews build --with-audio` yapın.

## Yapı

```
mynews/
├── gnews.py      Google News RSS çekme + ayrıştırma (source url, ilgili haberler)
├── rank.py       filtreler + skorlama + segment bazlı ağırlıklar
├── build.py      bülten JSON'u ve seslendirme metni
├── tts.py        ElevenLabs / Gemini, haber başına ses
└── cli.py        health | rank | build

site/             PWA — Tailwind (CDN), vanilla JS, service worker
├── index.html    kabuk
├── app.js        deste, hands-free oynatıcı, arama, kaydedilenler
├── sw.js         kabuk cache-first, veri network-first
└── data/         latest.json + günlük arşiv

config/settings.json   kategoriler, kotalar, ağırlıklar, yayıncı güveni, filtreler
tests/                 22 birim testi (ağ erişimsiz)
```

## Testler

```bash
python -m unittest discover -s tests -v
```

Kapsam: başlık/yayıncı ayrıştırma, ilgili haber listesi, Türkçe normalizasyon (`İ`/`I` tuzağı dahil),
benzerlik, format elemesi, clickbait cezası, yayıncı kotası, tekrar elemesi, seslendirme metni.

## PWA notları

- Telefonda **Ana ekrana ekle** ile kurulur; ikon, tam ekran ve çevrimdışı açılış çalışır.
- Service worker kabuğu cache-first, bülten verisini network-first tutar — internet yoksa son bülten görünür.
- Hands-free sırasında ekranın kapanmaması için Wake Lock istenir.
- Tailwind CDN'den geliyor; ilk açılışta internet gerekir, sonrasında cache'ten gelir.
