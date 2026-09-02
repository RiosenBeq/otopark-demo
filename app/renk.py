"""Araç rengi sınıflandırma — saf mantık (yalnız numpy, OpenCV yok).

Neden ayrı ve saf: renk kararı sahte piksellerle saniyeler içinde test
edilebilsin. Kameraya, modele veya veritabanına bağımlılığı yoktur.

Yöntem: aracın gövde bölgesi (kutunun orta bandı) HSV'ye çevrilir.
- Doygunluğu düşük pikseller renksizdir → parlaklığa göre beyaz/gri/siyah
- Doygun pikseller renklidir → hue (renk tonu) aralığına göre isimlendirilir
Karar, tek pikselle değil, bölgedeki piksellerin ÇOĞUNLUĞUYLA verilir;
cam, gölge ve far yansımaları tek tek pikselleri bozar ama çoğunluğu bozmaz.
"""

from __future__ import annotations

import numpy as np

BELIRSIZ = "belirsiz"

# Renk tonu (0-360) aralıkları → Türkçe ad. Kırmızı iki uçta olduğu için iki aralık.
_TON_ARALIKLARI: list[tuple[float, float, str]] = [
    (0, 12, "kırmızı"),
    (12, 40, "turuncu"),
    (40, 68, "sarı"),
    (68, 165, "yeşil"),
    (165, 200, "turkuaz"),
    (200, 260, "mavi"),
    (260, 320, "mor"),
    (320, 360, "kırmızı"),
]

# Bir pikselin RENKLİ sayılması için iki koşul birden gerekir:
#  - Doygunluk yüksek olacak. Gölgeli sahnelerde gri/siyah araçlar orta
#    doygunlukta mavimsi görünür; eşik düşük tutulursa her araç "mavi" çıkar.
#  - Piksel karanlık olmayacak. Çok karanlık pikselde renk tonu gürültüdür.
# Bu iki eşik gerçek araç fotoğraflarıyla ölçülerek seçildi.
_DOYGUNLUK_ESIGI = 0.45
_RENK_ICIN_PARLAKLIK = 0.25
# Renkli sayılabilmesi için piksellerin en az bu oranı iki koşulu da geçmeli
_RENKLI_ORANI = 0.35
# Kararın güvenilir sayılması için baskın rengin en az bu oranda olması gerekir
_BASKINLIK_ORANI = 0.45

_KOYU_ESIGI = 0.28  # parlaklık bunun altındaysa siyah
_ACIK_ESIGI = 0.62  # bunun üstündeyse beyaz


def hsv_cevir(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """BGR pikselleri (N,3 uint8) → (ton 0-360, doygunluk 0-1, parlaklık 0-1)."""
    piksel = bgr.reshape(-1, 3).astype(np.float64) / 255.0
    b, g, r = piksel[:, 0], piksel[:, 1], piksel[:, 2]
    en_buyuk = np.maximum(np.maximum(r, g), b)
    en_kucuk = np.minimum(np.minimum(r, g), b)
    fark = en_buyuk - en_kucuk

    ton = np.zeros_like(en_buyuk)
    renkli = fark > 1e-9
    kirmizi_baskin = renkli & (en_buyuk == r)
    yesil_baskin = renkli & (en_buyuk == g) & ~kirmizi_baskin
    mavi_baskin = renkli & ~kirmizi_baskin & ~yesil_baskin

    with np.errstate(invalid="ignore", divide="ignore"):
        ton[kirmizi_baskin] = 60 * (((g - b)[kirmizi_baskin] / fark[kirmizi_baskin]) % 6)
        ton[yesil_baskin] = 60 * ((b - r)[yesil_baskin] / fark[yesil_baskin] + 2)
        ton[mavi_baskin] = 60 * ((r - g)[mavi_baskin] / fark[mavi_baskin] + 4)

    doygunluk = np.zeros_like(en_buyuk)
    pozitif = en_buyuk > 1e-9
    doygunluk[pozitif] = fark[pozitif] / en_buyuk[pozitif]
    return ton % 360, doygunluk, en_buyuk


def _ton_adi(ton: float) -> str:
    for alt, ust, ad in _TON_ARALIKLARI:
        if alt <= ton < ust:
            return ad
    return BELIRSIZ


def renk_bul(gövde_bgr: np.ndarray) -> str:
    """Araç gövdesi piksellerinden renk adı döndürür.

    Karar verilemiyorsa 'belirsiz' döner — uydurma renk yazmaktansa
    bilinmiyor demek yeğdir (rapordaki sayılar güvenilir kalsın).
    """
    if gövde_bgr is None or gövde_bgr.size == 0:
        return BELIRSIZ
    ton, doygunluk, parlaklik = hsv_cevir(np.asarray(gövde_bgr))
    if ton.size < 20:
        return BELIRSIZ  # örneklem çok küçük, karar verme

    renkli_maske = (doygunluk >= _DOYGUNLUK_ESIGI) & (parlaklik >= _RENK_ICIN_PARLAKLIK)
    renkli_orani = float(renkli_maske.mean())

    if renkli_orani >= _RENKLI_ORANI:
        adlar = [_ton_adi(t) for t in ton[renkli_maske]]
        return _baskin(adlar)

    # Renksiz aile: parlaklığa göre siyah / gri / beyaz
    ortalama_parlaklik = float(np.median(parlaklik))
    if ortalama_parlaklik <= _KOYU_ESIGI:
        return "siyah"
    if ortalama_parlaklik >= _ACIK_ESIGI:
        return "beyaz"
    return "gri"


def _baskin(adlar: list[str]) -> str:
    if not adlar:
        return BELIRSIZ
    sayim: dict[str, int] = {}
    for ad in adlar:
        sayim[ad] = sayim.get(ad, 0) + 1
    en_iyi, adet = max(sayim.items(), key=lambda x: x[1])
    if adet / len(adlar) < _BASKINLIK_ORANI:
        return BELIRSIZ  # renkler karışık, güvenilir karar yok
    return en_iyi


def govde_bolgesi(kutu: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """Aracın kaportasının ağırlıkta olduğu orta bant.

    Kutunun tamamı alınırsa asfalt, gölge ve cam rengi karara karışır;
    orta bant (yatayda %20-80, dikeyde %35-80) gövdeyi daha iyi temsil eder.
    """
    x1, y1, x2, y2 = kutu
    genislik, yukseklik = x2 - x1, y2 - y1
    return (
        int(x1 + genislik * 0.20),
        int(y1 + yukseklik * 0.35),
        int(x1 + genislik * 0.80),
        int(y1 + yukseklik * 0.80),
    )


def baskin_renk(oylar: list[str]) -> str:
    """Birkaç karedeki renk kararından BASKIN olanı seçer.

    Neden gerekli: renk kararı tek kareye bakarak veriliyordu. Aynı beyaz araç
    güneşte "beyaz", gölgede "gri" ya da "siyah" okunuyor; hangi karede
    sayıldıysa o renk kalıcı olarak yazılıyordu. Birkaç oyun ortancası bu
    salınımı büyük ölçüde giderir.

    Baskın renk oyların yarısından fazlasını almalıdır; almazsa "belirsiz"
    döner — uydurma renk üretilmez (docs: kanıt zayıfsa belirsiz).
    """
    gecerli = [o for o in oylar if o and o != BELIRSIZ]
    if not gecerli:
        return BELIRSIZ
    sayim: dict[str, int] = {}
    for oy in gecerli:
        sayim[oy] = sayim.get(oy, 0) + 1
    kazanan, adet = max(sayim.items(), key=lambda ikili: ikili[1])
    return kazanan if adet * 2 > len(gecerli) else BELIRSIZ
