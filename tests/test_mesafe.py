"""Mesafe ve ölçek testleri — kullanıcının belirlediği eşiğe göre."""

from __future__ import annotations

import pytest

from app.mesafe import (
    Arac,
    CizgiOlcek,
    HomografiOlcek,
    OlcekHatasi,
    esik_dogrula,
    hesaplayici_kur,
    homografi_hesapla,
    mesafe_m,
    olcek_hesapla,
    yakin_ciftler,
    zemine_cevir,
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

    hesap = CizgiOlcek(olcek)
    yakin = yakin_ciftler(araclar, hesap, esik_m=1.5)
    assert yakin == [(1, 2, 1.2)]  # yalnız 1-2 çifti eşiğin altında

    # Kullanıcı eşiği düşürürse hiçbiri yakın sayılmaz
    assert yakin_ciftler(araclar, hesap, esik_m=1.0) == []
    # Yükseltirse üç çiftin de (1-2, 1-3, 2-3) altında kaldığı görülür
    assert len(yakin_ciftler(araclar, hesap, esik_m=12.0)) == 3
    # Eşik tam mesafeye eşitse ihlal SAYILMAZ (kesin küçük olmalı):
    # 1-3 arası tam 10 m
    assert (1, 3, 10.0) not in yakin_ciftler(araclar, hesap, esik_m=10.0)


def test_olcek_yoksa_mesafe_kurali_pasif():
    # Kalibrasyon ayarlanmadan yaklaşık sayı ÜRETİLMEZ (yanıltıcı olurdu)
    assert yakin_ciftler([arac(1, 100), arac(2, 110)], CizgiOlcek(0.0), esik_m=1.5) == []
    assert yakin_ciftler([arac(1, 100), arac(2, 110)], HomografiOlcek((), 0, 0), esik_m=1.5) == []
    assert yakin_ciftler([arac(1, 100), arac(2, 110)], None, esik_m=1.5) == []


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


# ---------------------------------------------------------------- homografi

# 1000x1000 karede, görüntünün alt yarısında duran bir dikdörtgen:
# perspektif nedeniyle üst kenar (uzak) ekranda DAR, alt kenar (yakın) GENİŞ.
# Gerçekte bu, 4 m eninde ve 10 m boyunda bir park şeridi olsun.
KOSELER = [(0.40, 0.50), (0.60, 0.50), (0.80, 0.95), (0.20, 0.95)]
EN_M, BOY_M = 4.0, 10.0


def test_homografi_koseleri_gercek_olculere_oturur():
    h = homografi_hesapla(KOSELER, EN_M, BOY_M)
    beklenen = [(0.0, 0.0), (EN_M, 0.0), (EN_M, BOY_M), (0.0, BOY_M)]
    for kose, (bx, by) in zip(KOSELER, beklenen, strict=True):
        x, y = zemine_cevir(h, kose)
        assert abs(x - bx) < 1e-6 and abs(y - by) < 1e-6


def test_homografi_derinlik_farkinda_dogru_cizgi_yaniliyor():
    """Bu, 4 nokta yönteminin var olma sebebi.

    Aynı GERÇEK mesafe (dikdörtgenin eni = 4 m), görüntüde uzakta 200 px,
    yakında 600 px yer kaplar. Tek çizgili ölçek hangisiyle ayarlanırsa
    diğerinde yanılır; homografi ikisinde de doğru ölçer.
    """
    h = homografi_hesapla(KOSELER, EN_M, BOY_M)
    hesap = HomografiOlcek(tuple(tuple(r) for r in h), 1000, 1000)

    uzak_a = Arac(takip_id=1, kutu=(380, 440, 420, 500))  # ayak (400, 500) = sol-üst
    uzak_b = Arac(takip_id=2, kutu=(580, 440, 620, 500))  # ayak (600, 500) = sağ-üst
    yakin_a = Arac(takip_id=3, kutu=(180, 890, 220, 950))  # ayak (200, 950) = sol-alt
    yakin_b = Arac(takip_id=4, kutu=(780, 890, 820, 950))  # ayak (800, 950) = sağ-alt

    # Homografi: iki çift de gerçekte tam 4 m
    assert abs(hesap.mesafe(uzak_a, uzak_b) - EN_M) < 1e-6
    assert abs(hesap.mesafe(yakin_a, yakin_b) - EN_M) < 1e-6

    # Tek çizgi (yakın kenardan ayarlanmış: 600 px = 4 m): uzaktaki çifti
    # 1,33 m sanır — 3 kat hata. Homografinin çözdüğü tam bu.
    cizgi = CizgiOlcek(EN_M / 600.0)
    assert cizgi.mesafe(uzak_a, uzak_b) < 1.5


def test_homografi_dogrusal_koselerde_anlasilir_hata():
    ayni_dogru = [(0.1, 0.5), (0.4, 0.5), (0.7, 0.5), (0.9, 0.5)]
    with pytest.raises(OlcekHatasi) as hata:
        homografi_hesapla(ayni_dogru, 4.0, 10.0)
    assert "dikdörtgen" in str(hata.value)


def test_homografi_gecersiz_girdiler():
    with pytest.raises(OlcekHatasi):
        homografi_hesapla(KOSELER[:3], 4.0, 10.0)  # 3 nokta yetmez
    with pytest.raises(OlcekHatasi):
        homografi_hesapla(KOSELER, 0, 10.0)  # en sıfır olamaz


def test_hesaplayici_kur_moda_gore_secer():
    import json

    h = homografi_hesapla(KOSELER, EN_M, BOY_M)

    cizgi = hesaplayici_kur({"kalibrasyon_modu": "cizgi", "olcek_m_px": "0.02"}, 1000, 1000)
    assert isinstance(cizgi, CizgiOlcek) and cizgi.hazir

    hassas = hesaplayici_kur(
        {"kalibrasyon_modu": "homografi", "homografi": json.dumps(h)}, 1000, 1000
    )
    assert isinstance(hassas, HomografiOlcek) and hassas.hazir

    # Ayarsız / bozuk kayıt: hazır DEĞİL — mesafe takibi kapalı kalır
    assert not hesaplayici_kur({}, 1000, 1000).hazir
    assert not hesaplayici_kur(
        {"kalibrasyon_modu": "homografi", "homografi": "bozuk"}, 1000, 1000
    ).hazir
    assert not hesaplayici_kur(
        {"kalibrasyon_modu": "homografi", "homografi": json.dumps(h)}, 0, 0
    ).hazir


def test_ufuk_cizgisindeki_nokta_cift_atlanir():
    """Ufka taşan nokta bütün kuralı çökertmemeli; yalnız o çift atlanır."""
    h = homografi_hesapla(KOSELER, EN_M, BOY_M)
    hesap = HomografiOlcek(tuple(tuple(r) for r in h), 1000, 1000)
    normal_a = Arac(takip_id=1, kutu=(380, 440, 420, 500))
    normal_b = Arac(takip_id=2, kutu=(580, 440, 620, 500))
    # Ufuk: bu perspektifte iki kenarın kesiştiği y'ye yakın bir nokta
    ufukta = Arac(takip_id=3, kutu=(480, 240, 520, 278))
    sonuc = yakin_ciftler([normal_a, normal_b, ufukta], hesap, esik_m=100.0)
    assert (1, 2) in {(a, b) for a, b, _ in sonuc}  # normal çift hesaplandı
