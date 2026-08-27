"""Araçlar arası mesafe — saf mantık (stdlib + numpy; kamera/DB bilmez).

İKİ YÖNTEM vardır ve kullanıcı arayüzden seçer:

1. BASİT — tek referans çizgisi: görüntüde uzunluğu bilinen bir çizgi
   çizilir (örn. park yeri genişliği 2,5 m), metre/piksel oranı çıkar.
   Zemin düz ve araçlar kameraya benzer uzaklıktaysa yeterlidir; derinlik
   farkı büyüdükçe yanılır (uzaktaki 1 piksel, yakındakinden uzundur).

2. HASSAS — 4 nokta (homografi): zeminde ölçüleri bilinen bir dikdörtgenin
   4 köşesi tıklanır; görüntü→zemin dönüşümü hesaplanır ve mesafeler
   derinlik farkında da doğru çıkar. Fabrika sistemindeki (DALSAN-ISG)
   yöntemin aynısıdır.

Hiçbiri ayarlanmamışsa mesafe takibi KAPALI kalır — yaklaşık sayı uydurulmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

ESIK_EN_AZ_M = 0.2
ESIK_EN_COK_M = 50.0


class OlcekHatasi(Exception):
    """Ölçek hesaplanamadı — kullanıcıya anlaşılır Türkçe mesaj."""


@dataclass(frozen=True)
class Arac:
    takip_id: int
    kutu: tuple[float, float, float, float]  # piksel (x1, y1, x2, y2)

    def ayak_noktasi(self) -> tuple[float, float]:
        """Kutunun alt-orta noktası: aracın zemine değdiği yer.

        Merkez nokta kullanılırsa yüksek araç (minibüs) ile alçak araç
        (otomobil) arasındaki mesafe yanlış çıkar.
        """
        x1, _, x2, y2 = self.kutu
        return ((x1 + x2) / 2.0, y2)


def olcek_hesapla(
    cizgi_normalize: tuple[tuple[float, float], tuple[float, float]],
    gercek_metre: float,
    kare_genislik: int,
    kare_yukseklik: int,
) -> float:
    """Referans çizgisinden metre/piksel oranı.

    cizgi_normalize: ((x1, y1), (x2, y2)) — 0-1 aralığında, çözünürlükten bağımsız
    """
    if gercek_metre <= 0:
        raise OlcekHatasi("Referans uzunluğu sıfırdan büyük olmalı (örn. 2,5 metre).")
    (x1, y1), (x2, y2) = cizgi_normalize
    piksel = (((x2 - x1) * kare_genislik) ** 2 + ((y2 - y1) * kare_yukseklik) ** 2) ** 0.5
    if piksel < 10:
        raise OlcekHatasi(
            "Referans çizgisi çok kısa. Görüntüde daha uzun, uzunluğunu "
            "bildiğiniz bir mesafe çizin (örn. bir park yerinin genişliği)."
        )
    return gercek_metre / piksel


def mesafe_m(a: Arac, b: Arac, olcek_m_px: float) -> float:
    """İki aracın zemindeki yaklaşık mesafesi (metre)."""
    ax, ay = a.ayak_noktasi()
    bx, by = b.ayak_noktasi()
    piksel = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
    return piksel * olcek_m_px


def yakin_ciftler(araclar: list[Arac], hesap, esik_m: float) -> list[tuple[int, int, float]]:
    """Eşikten yakın araç çiftleri: (küçük takip_id, büyük takip_id, mesafe).

    hesap: CizgiOlcek ya da HomografiOlcek (bkz. hesaplayici_kur).
    Kalibrasyon ayarlanmamışsa boş liste döner — yaklaşık bir sayı UYDURMAK
    yerine kural sessizce pasif kalır; ekran 'kalibrasyon gerekli' der.
    """
    if hesap is None or not hesap.hazir or esik_m <= 0:
        return []
    sonuc: list[tuple[int, int, float]] = []
    for i, birinci in enumerate(araclar):
        for ikinci in araclar[i + 1 :]:
            try:
                uzaklik = hesap.mesafe(birinci, ikinci)
            except OlcekHatasi:
                continue  # ufuk çizgisine taşan nokta: bu çift atlanır
            if uzaklik < esik_m:
                a, b = sorted((birinci.takip_id, ikinci.takip_id))
                sonuc.append((a, b, round(uzaklik, 2)))
    return sonuc


def esik_dogrula(ham: str) -> float:
    """Kullanıcının yazdığı eşiği metreye çevirir (virgül de kabul edilir)."""
    try:
        deger = float(str(ham).strip().replace(",", "."))
    except ValueError:
        raise OlcekHatasi(f"Mesafe eşiği sayı olmalı; '{ham}' yazılmış. Örnek: 1,5") from None
    if not ESIK_EN_AZ_M <= deger <= ESIK_EN_COK_M:
        raise OlcekHatasi(
            f"Mesafe eşiği {ESIK_EN_AZ_M:g} ile {ESIK_EN_COK_M:g} metre arasında olmalı."
        )
    return deger


# ---------------------------------------------------------------- 4 nokta (homografi)
#
# Fabrika sistemindeki (DALSAN-ISG) hassas yöntemin buraya taşınmış hâli.
#
# Fark ne? Tek çizgili ölçek, görüntünün her yerinde "1 piksel = X metre"
# sayar; oysa kameraya uzak bölgede 1 piksel çok daha uzun bir mesafedir.
# Homografi, zeminde köşelerini bildiğiniz bir DİKDÖRTGENİN 4 köşesinden
# görüntü→zemin dönüşümünü çıkarır; mesafeler derinlik farkında da doğru
# hesaplanır.
#
# Kullanım (arayüzden): zeminde gerçek ölçüsünü bildiğiniz bir dikdörtgenin
# (örn. tek park yeri: 2,5 × 5,0 m) 4 köşesine SAAT YÖNÜNDE tıklanır,
# gerçek en/boy metre olarak girilir. Dünya koordinatları buradan otomatik
# üretilir: (0,0), (en,0), (en,boy), (0,boy).


def homografi_hesapla(
    noktalar_normalize: list[tuple[float, float]],
    en_m: float,
    boy_m: float,
) -> list[list[float]]:
    """4 köşeden 3x3 görüntü→zemin homografisi (DLT yöntemi).

    noktalar_normalize: dikdörtgenin köşeleri, SAAT YÖNÜNDE
        (sol-üst, sağ-üst, sağ-alt, sol-alt), 0-1 aralığında
    en_m / boy_m: dikdörtgenin gerçek kenar uzunlukları (metre)
    """
    if len(noktalar_normalize) != 4:
        raise OlcekHatasi("Kalibrasyon için tam olarak 4 köşe gerekir.")
    if en_m <= 0 or boy_m <= 0:
        raise OlcekHatasi("Dikdörtgenin gerçek ölçüleri sıfırdan büyük olmalı (örn. 2,5 ve 5).")
    dunya = [(0.0, 0.0), (en_m, 0.0), (en_m, boy_m), (0.0, boy_m)]

    a_satirlari, b = [], []
    for (x, y), (dx, dy) in zip(noktalar_normalize, dunya, strict=True):
        a_satirlari.append([x, y, 1, 0, 0, 0, -dx * x, -dx * y])
        a_satirlari.append([0, 0, 0, x, y, 1, -dy * x, -dy * y])
        b.extend([dx, dy])
    try:
        h = np.linalg.solve(np.array(a_satirlari, dtype=float), np.array(b, dtype=float))
    except np.linalg.LinAlgError as hata:
        raise OlcekHatasi(
            "Kalibrasyon hesaplanamadı: seçilen 4 köşe bir dikdörtgen oluşturmuyor "
            "(üçü aynı doğru üzerinde olabilir). Zeminde köşeleri belirgin bir "
            "dikdörtgen seçip yeniden deneyin."
        ) from hata
    return np.append(h, 1.0).reshape(3, 3).tolist()


def zemine_cevir(
    homografi: list[list[float]], nokta_normalize: tuple[float, float]
) -> tuple[float, float]:
    """Normalize görüntü noktasını zemin düzlemine (metre) yansıtır."""
    matris = np.array(homografi, dtype=float)
    vektor = matris @ np.array([nokta_normalize[0], nokta_normalize[1], 1.0])
    if abs(vektor[2]) < 1e-9:
        raise OlcekHatasi(
            "Bu nokta zemine yansıtılamıyor (ufuk çizgisine çok yakın). "
            "Kalibrasyon dikdörtgenini görüntünün daha aşağısında seçin."
        )
    return float(vektor[0] / vektor[2]), float(vektor[1] / vektor[2])


# ---- iki yöntemi tek arayüzde toplayan hesaplayıcılar ----------------------
#
# Analiz döngüsü hangi yöntemin seçili olduğunu bilmek zorunda kalmasın diye
# ikisi de aynı soruyu cevaplar: "bu iki aracın zemindeki mesafesi kaç metre?"


@dataclass(frozen=True)
class CizgiOlcek:
    """Basit yöntem: tek referans çizgisinden metre/piksel oranı."""

    olcek_m_px: float

    @property
    def hazir(self) -> bool:
        return self.olcek_m_px > 0

    def mesafe(self, a: Arac, b: Arac) -> float:
        return mesafe_m(a, b, self.olcek_m_px)


@dataclass(frozen=True)
class HomografiOlcek:
    """Hassas yöntem: 4 nokta kalibrasyonuyla zemine yansıtılmış mesafe."""

    homografi: tuple[tuple[float, ...], ...]  # 3x3
    kare_genislik: int
    kare_yukseklik: int

    @property
    def hazir(self) -> bool:
        return len(self.homografi) == 3 and self.kare_genislik > 0 and self.kare_yukseklik > 0

    def _zeminde(self, arac: Arac) -> tuple[float, float]:
        x, y = arac.ayak_noktasi()
        return zemine_cevir(
            [list(satir) for satir in self.homografi],
            (x / self.kare_genislik, y / self.kare_yukseklik),
        )

    def mesafe(self, a: Arac, b: Arac) -> float:
        ax, ay = self._zeminde(a)
        bx, by = self._zeminde(b)
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def hesaplayici_kur(ayarlar: dict, kare_genislik: int, kare_yukseklik: int):
    """Kayıtlı ayarlardan aktif mesafe hesaplayıcısını kurar.

    Dönen nesnenin .hazir'ı False ise mesafe takibi kapalıdır — sistem
    yaklaşık bir sayı uydurmaz. Bozuk kayıt da 'hazır değil' sayılır.
    """
    mod = ayarlar.get("kalibrasyon_modu", "cizgi")
    if mod == "homografi":
        try:
            matris = json.loads(ayarlar.get("homografi") or "[]")
            if len(matris) != 3:
                return HomografiOlcek((), 0, 0)
            return HomografiOlcek(
                tuple(tuple(float(v) for v in satir) for satir in matris),
                kare_genislik,
                kare_yukseklik,
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return HomografiOlcek((), 0, 0)
    try:
        return CizgiOlcek(float(ayarlar.get("olcek_m_px", "0") or 0))
    except ValueError:
        return CizgiOlcek(0.0)
