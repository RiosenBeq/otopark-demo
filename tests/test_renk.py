"""Renk sınıflandırma testleri — kamerasız, sahte piksellerle."""

from __future__ import annotations

import numpy as np

from app.renk import BELIRSIZ, govde_bolgesi, hsv_cevir, renk_bul


def yama(bgr: tuple[int, int, int], boyut: int = 20) -> np.ndarray:
    """Tek renkli kare bir görüntü parçası."""
    return np.full((boyut, boyut, 3), bgr, dtype=np.uint8)


def test_temel_renkler():
    assert renk_bul(yama((30, 30, 220))) == "kırmızı"
    assert renk_bul(yama((220, 40, 40))) == "mavi"
    assert renk_bul(yama((40, 180, 40))) == "yeşil"
    assert renk_bul(yama((40, 220, 230))) == "sarı"
    assert renk_bul(yama((20, 120, 240))) == "turuncu"


def test_renksiz_aile_parlakliga_gore():
    assert renk_bul(yama((245, 245, 245))) == "beyaz"
    assert renk_bul(yama((20, 20, 20))) == "siyah"
    assert renk_bul(yama((130, 130, 130))) == "gri"


def test_hafif_renk_tonlu_gri_gri_kalir():
    # Gerçek araç fotoğrafında gri, tam nötr değildir — yine gri denmeli
    assert renk_bul(yama((140, 135, 132))) == "gri"


def test_karisik_piksellerde_cogunluk_kazanir():
    # %70 kırmızı gövde + %30 cam/gölge → kırmızı
    gorsel = np.zeros((20, 20, 3), dtype=np.uint8)
    gorsel[:14] = (30, 30, 220)
    gorsel[14:] = (60, 60, 60)
    assert renk_bul(gorsel) == "kırmızı"


def test_belirgin_baskin_yoksa_belirsiz():
    # Eşit oranda kırmızı/mavi/yeşil: uydurma renk yerine 'belirsiz'
    gorsel = np.zeros((30, 30, 3), dtype=np.uint8)
    gorsel[:10] = (30, 30, 220)
    gorsel[10:20] = (220, 40, 40)
    gorsel[20:] = (40, 200, 40)
    assert renk_bul(gorsel) == BELIRSIZ


def test_golgedeki_koyu_arac_mavi_denmez():
    """Gerçek sahnede öğrenilen tuzak: gölgeli gri/siyah araçlar orta
    doygunlukta MAVİMSİ görünür. Eşikler gevşek olursa otoparktaki her araç
    'mavi' sayılır ve renk raporu anlamsızlaşır."""
    golgeli_siyah = yama((70, 55, 45))  # koyu, hafif mavimsi
    assert renk_bul(golgeli_siyah) == "siyah"
    golgeli_gri = yama((110, 95, 85))
    assert renk_bul(golgeli_gri) in ("gri", "siyah")


def test_gercekten_mavi_arac_mavi_kalir():
    # Doygun ve yeterince aydınlık mavi: karar mavi olmalı
    assert renk_bul(yama((190, 110, 45))) == "mavi"


def test_loş_isikta_kirmizi_arac_kirmizi_kalir():
    # Kırmızı araç loş ışıkta bile yüksek doygunluktadır (gerçek ölçüm:
    # doygunluk ~0,68 / parlaklık ~0,29) — siyah denmemeli
    assert renk_bul(yama((18, 18, 120))) == "kırmızı"


def test_bos_veya_kucuk_ornek_belirsiz():
    assert renk_bul(None) == BELIRSIZ
    assert renk_bul(np.zeros((0, 0, 3), dtype=np.uint8)) == BELIRSIZ
    assert renk_bul(np.full((2, 2, 3), 200, dtype=np.uint8)) == BELIRSIZ


def test_hsv_cevirme_dogru():
    ton, doygunluk, parlaklik = hsv_cevir(np.array([[0, 0, 255]], dtype=np.uint8))  # saf kırmızı
    assert abs(ton[0]) < 1e-6
    assert abs(doygunluk[0] - 1.0) < 1e-6
    assert abs(parlaklik[0] - 1.0) < 1e-6

    ton, _, _ = hsv_cevir(np.array([[0, 255, 0]], dtype=np.uint8))  # saf yeşil
    assert abs(ton[0] - 120) < 1e-6
    ton, _, _ = hsv_cevir(np.array([[255, 0, 0]], dtype=np.uint8))  # saf mavi
    assert abs(ton[0] - 240) < 1e-6


def test_govde_bolgesi_orta_bant():
    x1, y1, x2, y2 = govde_bolgesi((100, 100, 200, 200))
    assert (x1, x2) == (120, 180)  # yatayda %20-80
    assert (y1, y2) == (135, 180)  # dikeyde %35-80
