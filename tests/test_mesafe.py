"""Mesafe ve ölçek testleri — kullanıcının belirlediği eşiğe göre."""

from __future__ import annotations

import pytest

from app.mesafe import (
    Arac,
    OlcekHatasi,
    esik_dogrula,
    mesafe_m,
    olcek_hesapla,
    yakin_ciftler,
)


def arac(takip_id: int, x: float, y: float = 400, genislik: float = 80) -> Arac:
    """Ayak noktası (x, y) olan araç."""
    return Arac(takip_id=takip_id, kutu=(x - genislik / 2, y - 60, x + genislik / 2, y))


def test_olcek_yatay_cizgiden():
    # 1000 px genişlikte karede tam yarısı (500 px) = 5 metre → 0,01 m/px
    olcek = olcek_hesapla(((0.25, 0.5), (0.75, 0.5)), 5.0, 1000, 600)
    assert abs(olcek - 0.01) < 1e-9


def test_olcek_capraz_cizgiden():
    # 300-400-500 üçgeni: 500 px = 10 m → 0,02 m/px
    olcek = olcek_hesapla(((0.0, 0.0), (0.3, 0.4)), 10.0, 1000, 1000)
    assert abs(olcek - 0.02) < 1e-9


def test_gecersiz_olcek_anlasilir_hata():
    with pytest.raises(OlcekHatasi) as hata:
        olcek_hesapla(((0.5, 0.5), (0.501, 0.5)), 2.5, 1000, 600)  # 1 px
    assert "çok kısa" in str(hata.value)

    with pytest.raises(OlcekHatasi):
        olcek_hesapla(((0.0, 0.0), (1.0, 0.0)), 0, 1000, 600)  # 0 metre


def test_mesafe_olcekle_carpiliyor():
    olcek = 0.02  # 1 px = 2 cm
    assert abs(mesafe_m(arac(1, 100), arac(2, 200), olcek) - 2.0) < 1e-9


def test_ayak_noktasi_yukseklikten_etkilenmiyor():
    # Alçak otomobil ile yüksek minibüs aynı yerde duruyorsa mesafe ~0 olmalı
    otomobil = Arac(takip_id=1, kutu=(90, 350, 170, 400))
    minibus = Arac(takip_id=2, kutu=(90, 250, 170, 400))  # çok daha yüksek kutu
    assert mesafe_m(otomobil, minibus, 0.02) < 1e-9


def test_yakin_ciftler_esige_gore():
    araclar = [arac(1, 100), arac(2, 160), arac(3, 600)]
    olcek = 0.02  # 60 px = 1,2 m ; 440 px = 8,8 m

    yakin = yakin_ciftler(araclar, olcek, esik_m=1.5)
    assert yakin == [(1, 2, 1.2)]  # yalnız 1-2 çifti eşiğin altında

    # Kullanıcı eşiği düşürürse hiçbiri yakın sayılmaz
    assert yakin_ciftler(araclar, olcek, esik_m=1.0) == []
    # Yükseltirse üç çiftin de (1-2, 1-3, 2-3) altında kaldığı görülür
    assert len(yakin_ciftler(araclar, olcek, esik_m=12.0)) == 3
    # Eşik tam mesafeye eşitse ihlal SAYILMAZ (kesin küçük olmalı):
    # 1-3 arası tam 10 m
    assert (1, 3, 10.0) not in yakin_ciftler(araclar, olcek, esik_m=10.0)


def test_olcek_yoksa_mesafe_kurali_pasif():
    # Ölçek ayarlanmadan yaklaşık sayı ÜRETİLMEZ (yanıltıcı olurdu)
    assert yakin_ciftler([arac(1, 100), arac(2, 110)], olcek_m_px=0, esik_m=1.5) == []


def test_esik_dogrulama():
    assert esik_dogrula("1,5") == 1.5  # virgüllü Türkçe giriş
    assert esik_dogrula(" 2.0 ") == 2.0
    with pytest.raises(OlcekHatasi) as hata:
        esik_dogrula("iki metre")
    assert "sayı olmalı" in str(hata.value)
    with pytest.raises(OlcekHatasi):
        esik_dogrula("0")
    with pytest.raises(OlcekHatasi):
        esik_dogrula("500")
