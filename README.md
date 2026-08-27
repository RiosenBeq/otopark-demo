# Otopark Demo — kafe otoparkı takibi

Kafenin otoparkına bakan bir kameradan **kaç araç geldiğini**, **araçların
renklerini**, **günlük yaya sayısını** ve **senin belirlediğin mesafeden daha
yakın park eden araçları** çıkaran deneme uygulaması.

Fabrika sisteminden (DALSAN-ISG) tamamen ayrıdır: kendi klasörü, kendi
veritabanı, kendi portu (8090). Birini kapatmak diğerini etkilemez.

## Çalıştırma

1. **Baslat-Mac.command** (veya Windows'ta **Baslat-Windows.bat**) dosyasına çift tıkla.
   İlk açılışta gerekli paketleri kendisi kurar (birkaç dakika).
2. Uygulama **kendi penceresinde** açılır (tarayıcı gerekmez). Pencereyi kapatmak sistemi durdurur. Gerekirse tarayıcıdan da ulaşılabilir: `http://127.0.0.1:8090`

Kamera veya video kaynağını `.env` dosyasındaki **KAYNAK** satırı belirler:

```
KAYNAK=0                       # bilgisayarın kamerası
KAYNAK=rtsp://kullanici:sifre@192.168.1.50:554/...   # IP kamera
KAYNAK=veri/ornek-otopark.mp4  # kayıtlı video (deneme)
```

## Ekranda ne var

| Bölüm | Ne yapar |
|---|---|
| **Özet sayılar** | Bugün kaç araç geldi, kaç kişi geçti, şu an kaç araç görünüyor |
| **Canlı görüntü** | Tespit kutularıyla birlikte 1 sn'de bir yenilenen görüntü |
| **Mesafe eşiği** | Araçlar arası en az mesafeyi **sen** yazarsın; altına düşen çiftler kaydedilir |
| **Ölçek** | Görüntüde uzunluğunu bildiğin bir mesafeyi çizip metre olarak girersin |
| **Araç renkleri** | Günün renk dağılımı (beyaz, siyah, kırmızı…) |
| **Kütüphane** | Kendi nesnelerini fotoğrafla tanıtırsın (örn. "servis aracımız") |
| **Kare tarama** | Fotoğraf ya da video yükleyip tararsın (videodan kareler otomatik alınır); canlı sayaçlara dokunmaz |

## Dürüst sınırlar

- **Sayım:** her araç/kişi bir kez sayılır (takip numarasıyla). Görüntüden çıkıp
  tekrar giren araç yeni numara alır ve yeniden sayılabilir.
- **Mesafe:** tek ölçekli yaklaşık hesaptır. Küçük ve düz bir otoparkta güvenilir;
  çok derinlikli, geniş açılı sahnelerde yanılır. Ölçek ayarlanmadan mesafe
  takibi **kapalı kalır** — sistem yaklaşık sayı uydurmaz.
- **Renk:** gölgede ve gece isabet düşer; karar verilemezse "belirsiz" yazar.
- **Nesne tanıtma:** model eğitimi değildir; renk + desen parmak izi eşleştirmesidir.
  Logosu/deseni belirgin nesnelerde iyi, düz beyaz nesnelerde zayıf çalışır.

## Platform ve Docker

| | Mac / Windows (çift tık) | Docker (Mac/Win) | Docker (Linux sunucu) |
|---|---|---|---|
| Arayüz, video dosyası, **RTSP kamera** | ✅ | ✅ | ✅ |
| **Bilgisayarın kendi kamerası** | ✅ | ❌ Docker Desktop kamerayı veremez | ⚠️ USB kamera, ayar gerekir |
| GPU hızlandırma | ❌ / ⚠️ WSL2 | ❌ | ✅ NVIDIA |
| 7/24 kendiliğinden çalışma | ⚠️ pencere açık kalmalı | ✅ | ✅ |

Docker ile çalıştırmak için:

```bash
cp .env.example .env
bash models/indir.sh      # model indirilmeden imaj DERLENMEZ (bilerek)
docker compose up -d
docker compose logs -f
```

`veri/` klasörü ve `.env` container dışında durur; container silinse de
veriler kaybolmaz. Ayrıntılı kılavuz: fabrika projesindeki `NASIL-CALISIR.md`.

## Test

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```
