# NextGen Detector — otopark takibi

Otoparka bakan bir kameradan **kaç araç geldiğini**, **araçların
renklerini**, **günlük yaya sayısını** ve **senin belirlediğin mesafeden daha
yakın park eden araçları** çıkaran uygulama.

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
| **Mesafe kalibrasyonu** | İki yöntem: **Basit** — uzunluğunu bildiğin tek çizgi; **Hassas (4 nokta)** — zeminde ölçülerini bildiğin bir dikdörtgenin köşelerini işaretlersin, mesafeler derinlik farkında da doğru çıkar |
| **Araç renkleri** | Günün renk dağılımı (beyaz, siyah, kırmızı…) |
| **Kütüphane** | Kendi nesnelerini fotoğrafla tanıtırsın (örn. "servis aracımız") |
| **Kare tarama** | Fotoğraf ya da video yükleyip tararsın (videodan kareler otomatik alınır); canlı sayaçlara dokunmaz |

## Dürüst sınırlar

- **Sayım:** her araç/kişi bir kez sayılır (takip numarasıyla). Görüntüden çıkıp
  tekrar giren araç yeni numara alır ve yeniden sayılabilir.
- **Mesafe (Basit yöntem):** tek ölçekli yaklaşık hesaptır; derinlikli sahnede
  yanılır. Böyle bir sahnede **Hassas (4 nokta)** yöntemini kullanın — zemine
  yansıtılan mesafeler uzak/yakın farkında da doğrudur. Hiçbir kalibrasyon
  ayarlanmadan mesafe takibi **kapalı kalır** — sistem yaklaşık sayı uydurmaz.
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

## Yönetici şifresi

Panel varsayılan olarak **şifresizdir** — aynı bilgisayarda açıldığı için
demo kullanımında giriş istenmez.

Şifre koymak isterseniz proje klasöründeki `.env` dosyasında şu satırı doldurun
ve uygulamayı yeniden başlatın:

```
PANEL_SIFRESI=buraya-sifrenizi-yazin
```

- Şifre doluysa panel açılışta şifre sorar; boş bırakılırsa sormaz.
- Şifreyi unutursanız `.env` dosyasından silmeniz yeterlidir.
- `.env` dosyası GitHub'a gönderilmez (`.gitignore` içindedir) — şifreniz
  yalnızca kendi bilgisayarınızda durur.

## Marka

Bu ürün **NextGen Detector** ailesindendir. Logo: `app/web/static/logo.svg`.
Kardeş projeler: **DALSAN-ISG** (fabrika iş güvenliği) ve **LAFFOGATO**
(kafe bar sayacı) — her biri kendi klasöründe, kendi portunda bağımsız çalışır.

---

## Sayım nasıl çalışıyor (özet)

Bir araç, kadrajda göründüğü sürece TEK bir takip numarasıyla izlenir ve üç kez
görüldükten sonra günlük sayaca girer. Tek karelik tespit kaçakları sayacı
**sıfırlamaz** (azaltır): titreyen bir araç da sayılır.

Uygulama gün içinde yeniden başlatılırsa takip numaraları baştan başlar; sistem
o günkü en büyük numaranın üstünden devam eder, böylece yeni araçlar eski
kayıtlarla çakışıp **sessizce kaybolmaz**.

**Renk** tek kareye bakarak değil, birkaç karenin oyuyla belirlenir; oylar
bölünürse "belirsiz" yazılır — uydurma renk üretilmez.

Ekrandaki "şu an görünen" sayısı son birkaç karenin ortancasıdır: tek karelik
bir kaçak sayacı titretmez.

## Hassasiyet

Özet sayfasındaki **Tespit hassasiyeti** kaydırıcısı, kaç güvenle bulunan
nesnenin sayılacağını belirler. Düşük değer daha çok araç yakalar ama yanlış
tespit artar. Uzaktaki araçlar görünmüyorsa 0,05'lik adımlarla düşürün.
Değişiklik anında geçerlidir, yeniden başlatma gerekmez.

## Uyarılar

İki araç arasındaki mesafe eşiğin altına düştüğünde uyarı çıkar. Uyarı,
**ardışık üç karede** doğrulanmadan yazılmaz: tek karelik bir kutu hatası
kalıcı bir olay ve fotoğraf üretmez.

Uyarılar sunucudaki olay akışından gelir; aynı anda oluşan iki olay iki ayrı
uyarı olur. İsteğe bağlı **sesli bildirim** ve **Türkçe sesli okuma** vardır
(tarayıcı kuralı gereği sayfaya bir kez tıklamak gerekir).

## Günlük

`veri/loglar/otopark.log` — sorun bildirirken bu dosyadaki satırları olduğu gibi
kopyalayın. Analizde bir hata olursa özet sayfasında da kırmızı bir satır olarak
görünür.
