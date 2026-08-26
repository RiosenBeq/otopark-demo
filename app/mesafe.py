"""Araçlar arası mesafe — saf mantık (yalnız stdlib).

Ölçek nasıl bulunur: kullanıcı görüntüde uzunluğunu bildiği bir çizgi çizer
(örn. bir park yerinin genişliği, 2,5 m). Sistem o çizginin kaç piksel
olduğunu ölçer ve metre/piksel oranını çıkarır.

Sınır (dürüstçe söylenmeli): tek ölçekli bu yöntem, zemin düz ve araçlar
kameraya benzer uzaklıkta olduğunda doğrudur. Kameraya çok yakın ve çok
uzak araçlar aynı karede kıyaslanırsa perspektif hatası büyür. Kafe
otoparkı gibi küçük ve tek düzlemli alanlar için yeterlidir; fabrika
sistemindeki 4 noktalı homografi kadar hassas değildir.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def yakin_ciftler(
    araclar: list[Arac], olcek_m_px: float, esik_m: float
) -> list[tuple[int, int, float]]:
    """Eşikten yakın araç çiftleri: (küçük takip_id, büyük takip_id, mesafe).

    Ölçek ayarlanmamışsa (0) boş liste döner — yaklaşık bir sayı UYDURMAK
    yerine kural sessizce pasif kalır; ekran 'ölçek ayarlanmadı' der.
    """
    if olcek_m_px <= 0 or esik_m <= 0:
        return []
    sonuc: list[tuple[int, int, float]] = []
    for i, birinci in enumerate(araclar):
        for ikinci in araclar[i + 1 :]:
            uzaklik = mesafe_m(birinci, ikinci, olcek_m_px)
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
