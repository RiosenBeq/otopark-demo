# CLAUDE.md — NextGen Detector (Otopark)

Claude Code'un bu depoda çalışırken uyacağı kurallar. Her oturumun başında okunur.

> **ÖNEMLİ:** Projeyi yazılım bilmeyen bir kişi, yapay zeka yardımıyla yürütüyor.
> Kullanıcı kodu okumaz; sistemin **davranışını** deneyerek onaylar.
> Bu, kalite standardını düşürmez — basitlik standardını yükseltir.

## 1. Proje tek cümleyle

Otoparka bakan tek kameradan **araç/kişi sayan**, araç **renklerini** çıkaran ve
**birbirine çok yakın park eden** araçları fotoğraflı kaydeden; tek portta (8090),
tek süreçte çalışan demo uygulaması. NextGen'in müşteri demolarında kullandığı
üründür; kardeş projeleri DALSAN-ISG (fabrika) ve LAFFOGATO'dan (kafe) tamamen
bağımsız çalışır.

## 2. Altın kurallar

1. **En az parça:** yeni araç/kütüphane/servis eklemeden önce sor: "bu olmadan
   yapılabilir mi?" Evetse ekleme. Kullanıcının öğreneceği parça sayısı ölçüttür.
2. **Sayı uydurma:** kalibrasyon/veri yoksa özellik SESSİZCE KAPALI kalır ve
   ekran nedenini söyler. Yaklaşık değer asla gerçekmiş gibi gösterilmez.
3. **Her şey Türkçe ve açıklamalı:** kullanıcıya görünen her metin Türkçe;
   her ana kart başlığında "?" balonu, her kritik düğmede `title` açıklaması olur.
   Yeni bir arayüz öğesi eklerken açıklamasını da ekle.

## 3. Teknoloji — sabit

| Katman | Karar |
|---|---|
| Dil / çatı | Python 3.12, FastAPI, Jinja2 + sade JS (React/Node YOK) |
| Veritabanı | SQLite tek dosya: `veri/otopark.db`; şema `app/sema.sql` (idempotent) |
| Görüntü | OpenCV; tespit YOLOX ONNX + onnxruntime (**torch YOK, eklenemez**) |
| Takip | supervision (ByteTrack) — `lost_track_buffer` SANİYE üzerinden: `int(sn*30)` |
| Test / lint | pytest, ruff (line-length 100) |
| Süreç | TEK program; analiz FastAPI içinde arka plan iş parçacığı |

## 4. Mesafe kalibrasyonu — iki yöntem

- `app/mesafe.py` saf mantıktır (kamera/DB bilmez): testi saniyeler sürer.
- **Basit (çizgi):** tek referans çizgisi → metre/piksel. Derinlik farkında yanılır.
- **Hassas (4 nokta / homografi):** zemindeki dikdörtgenin köşelerinden
  görüntü→zemin dönüşümü. DALSAN-ISG'deki yöntemin aynısı.
- Aktif yöntemi `kalibrasyon_modu` ayarı belirler; `hesaplayici_kur` tek kapıdır.
- Hiçbiri ayarlı değilse `hazir=False` → mesafe takibi kapalı, sayı uydurulmaz.

## 5. Asla yapma

| Yasak | Yerine |
|---|---|
| `except Exception: pass` | Tiplenmiş hata + anlaşılır Türkçe mesaj |
| Sabit kodlanmış eşik/yol/şifre | `.env` ya da `ayar` tablosu |
| Kare başına karar | Takip bazlı sayım (`_SAYMA_ESIGI`) |
| "Belirsiz"i sonuç saymak | Belirsiz ayrı gösterilir, uydurulmaz |
| Sınırsız dosya/bellek okuma | Boyut sınırları (bkz. nesne_rotalari.py) |
| Ölçüm sonucu abartma | Dürüst sınırlar README'de yazılıdır, korunur |

## 6. Test komutları

```bash
.venv/bin/python -m pytest -q     # tümü (~85 test, kamerasız, saniyeler)
.venv/bin/ruff check . && .venv/bin/ruff format .
```

Her davranış değişikliğinde test yaz; kalibrasyon matematiğine dokununca
`tests/test_mesafe.py` çalıştırıp sonucu kullanıcıya göster.

## 7. Marka

Ürün adı **NextGen Detector**. Logo: `app/web/static/logo.svg` (viewfinder + N
monogramı) — her sayfanın başlığında ve faviconda kullanılır. Kardeş projelerde
de aynı dosya vardır; logoda değişiklik üçüne birden uygulanır.
