"""Sayım doğruluğu, renk kararı ve uyarı akışı.

Buradaki her test, sahada ÖLÇÜLMÜŞ bir hatanın geri gelmesini engeller.
Hiçbiri kamera ya da model gerektirmez.
"""

from __future__ import annotations

import numpy as np

from app import renk as renk_modulu
from app import veritabani, zaman
from app.analiz import Analiz


def _analiz(ayarlar) -> Analiz:
    analiz = Analiz(ayarlar)
    analiz._kare_boyutu = (640, 480)
    return analiz


def _kare():
    return np.random.default_rng(4).integers(0, 255, (480, 640, 3), dtype=np.uint8)


def _iz(tip: str, takip_id: int, kutu=(100.0, 100.0, 200.0, 220.0)) -> dict:
    return {"tip": tip, "takip_id": takip_id, "kutu": kutu}


# ---- giriş: Türkçe şifre ----


def test_turkce_sifre_kullaniciyi_kilitlemez(ayarlar, monkeypatch):
    """KRİTİK ESKİ HATA: hmac.compare_digest METİN karşılaştırmasında ASCII dışı
    karakteri kabul etmez ve TypeError fırlatır. PANEL_SIFRESI=şifre123 girildiğinde
    giriş kalıcı olarak 500 veriyor, kullanıcı sisteme HİÇ giremiyordu."""
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.uygulama import uygulama_olustur

    korumali = replace(ayarlar, panel_sifresi="şifre123")
    with TestClient(uygulama_olustur(korumali, analiz_ac=False)) as istemci:
        yanit = istemci.post("/giris", data={"sifre": "şifre123"}, follow_redirects=False)
        assert yanit.status_code == 303
        assert yanit.headers["location"] == "/", "doğru şifre kabul edilmeli"

        yanlis = istemci.post("/giris", data={"sifre": "yanlış"}, follow_redirects=False)
        assert yanlis.headers["location"] == "/giris?hata=1"


# ---- sayım ----


def test_titreyen_arac_yine_de_sayilir(ayarlar):
    """ESKİ HATA: ekranda görünmeyen takiplerin sayacı SIFIRLANIYORDU. Tespit
    kaçağı olağandır; gör/gör/kaçır/gör/gör düzeninde ilerleyen bir araç
    ASLA sayılmıyordu (ölçüldü: 8 karede 6 tespit = 0 kayıt)."""
    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        veritabani.semayi_uygula(baglanti)
        analiz = _analiz(ayarlar)
        kare = _kare()
        desen = [True, True, False, True, True, False, True, True]
        for gorunuyor in desen:
            analiz._gecisleri_kaydet(baglanti, [_iz("arac", 1)] if gorunuyor else [], kare)
        adet = baglanti.execute("SELECT COUNT(*) AS n FROM gecisler").fetchone()["n"]
        assert adet == 1, "titreyen araç sayılmalı"
    finally:
        baglanti.close()


def test_yeniden_baslatma_yeni_araclari_yutmaz(ayarlar):
    """ESKİ HATA: takip numaraları 1'den başlıyordu ve INSERT OR IGNORE ile
    aynı gün ikinci kez kullanılan numara SESSİZCE düşüyordu — uygulama
    yeniden başlatıldıktan sonraki N araç hiç sayılmıyordu."""
    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        veritabani.semayi_uygula(baglanti)
        kare = _kare()

        ilk = _analiz(ayarlar)
        ilk._id_ofsetini_tazele(baglanti)
        for _ in range(3):
            ilk._gecisleri_kaydet(baglanti, [_iz("arac", 1), _iz("arac", 2)], kare)
        assert baglanti.execute("SELECT COUNT(*) AS n FROM gecisler").fetchone()["n"] == 2

        # Uygulama yeniden başladı: numaralar yine 1'den başlıyor
        ikinci = _analiz(ayarlar)
        ikinci._id_ofsetini_tazele(baglanti)
        for _ in range(3):
            ikinci._gecisleri_kaydet(baglanti, [_iz("arac", 1), _iz("arac", 2)], kare)

        adet = baglanti.execute("SELECT COUNT(*) AS n FROM gecisler").fetchone()["n"]
        assert adet == 4, f"yeniden başlatma sonrası araçlar da sayılmalı, bulunan: {adet}"
    finally:
        baglanti.close()


def test_canli_sayac_tek_karelik_kacakta_titremez(ayarlar):
    """Ekrandaki 'şu an görünen' değeri ham kare sayısı olursa, tek karelik bir
    kaçak kullanıcıya rastgele bir sayı gösterir."""
    analiz = _analiz(ayarlar)
    degerler = [3, 3, 0, 3, 3]  # ortadaki kare tespiti kaçırdı
    sonuclar = [analiz._yumusat("arac", d) for d in degerler]
    assert sonuclar[-1] == 3, f"ortanca 3 olmalı, çıkan: {sonuclar}"
    assert 0 not in sonuclar[-2:], "kaçak ekrana sıfır olarak yansımamalı"


# ---- renk ----


def test_baskin_renk_salinimi_giderir():
    """ESKİ HATA: renk TEK kareye bakarak karara bağlanıyordu. Aynı beyaz araç
    güneşte 'beyaz', gölgede 'gri' okunuyor; hangi karede sayıldıysa o renk
    kalıcı yazılıyordu."""
    assert renk_modulu.baskin_renk(["beyaz", "beyaz", "gri", "beyaz"]) == "beyaz"


def test_kararsiz_renk_belirsiz_kalir():
    """Uydurma renk üretilmez: oylar bölünmüşse 'belirsiz'."""
    assert renk_modulu.baskin_renk(["beyaz", "gri", "siyah"]) == renk_modulu.BELIRSIZ
    assert renk_modulu.baskin_renk([]) == renk_modulu.BELIRSIZ
    assert renk_modulu.baskin_renk([renk_modulu.BELIRSIZ] * 4) == renk_modulu.BELIRSIZ


# ---- tespit ----


def _tespitci(guven=0.35):
    from app.tespit import Tespitci

    t = Tespitci.__new__(Tespitci)
    t._boy = 416
    t.guven = guven
    return t


def _cikti(satirlar):
    toplam = sum((416 // adim) ** 2 for adim in (8, 16, 32))
    c = np.zeros((toplam, 85), dtype=np.float32)
    for i, (cx, cy, w, h, nesnelik, siniflar) in enumerate(satirlar):
        c[i, 0] = cx / 8.0
        c[i, 1] = cy / 8.0
        c[i, 2] = np.log(w / 8.0)
        c[i, 3] = np.log(h / 8.0)
        c[i, 4] = nesnelik
        for sinif, skor in siniflar.items():
            c[i, 5 + sinif] = skor
    return c


def test_ilgisiz_sinif_baskin_olsa_bile_arac_kaybolmaz():
    """ESKİ HATA: 80 COCO sınıfı üzerinde argmax alınıyordu; ilgilenmediğimiz
    bir sınıf öne geçtiğinde araç TAMAMEN düşüyordu."""
    t = _tespitci(guven=0.35)
    # 2 = car (bizim), 60 = dining table (ilgisiz, daha yüksek)
    _, _, tipler = t._son_isle(
        _cikti([(200, 200, 120, 90, 1.0, {2: 0.40, 60: 0.75})]), 1.0, 640, 480
    )
    assert list(tipler) == ["arac"]


def test_insan_ve_arac_birbirini_bastirmaz():
    t = _tespitci(guven=0.30)
    _, _, tipler = t._son_isle(
        _cikti(
            [
                (200, 250, 60, 160, 1.0, {0: 0.80}),
                (205, 255, 130, 100, 1.0, {2: 0.85}),
            ]
        ),
        1.0,
        640,
        480,
    )
    assert sorted(tipler) == ["arac", "insan"]


def test_dusuk_hassasiyette_olu_bant_yok(ayarlar):
    """supervision içeride det_thresh = eşik + 0,1 kullanır. Sabit 0,20 eşik →
    0,30 gerçek taban demekti: tespit.py'nin insan için tanıdığı 0,28'lik
    ayrıcalık ÖLÜ kalıyordu."""
    analiz = _analiz(ayarlar)
    for hassasiyet in (0.15, 0.25, 0.35, 0.60):
        izleyici = analiz._izleyici_kur(hassasiyet)
        assert izleyici.det_thresh < hassasiyet, (
            f"hassasiyet {hassasiyet}: yeni iz için gereken {izleyici.det_thresh:.2f} "
            "eşiğin üstünde — araç sayılamaz"
        )


def test_hassasiyet_ekrandan_ayarlanabilir(istemci):
    yanit = istemci.post("/ayarlar/hassasiyet", data={"hassasiyet": "0,25"}, follow_redirects=False)
    assert yanit.status_code == 303
    assert "hata" not in yanit.headers["location"]
    assert "0.25" in istemci.get("/").text


def test_gecersiz_hassasiyet_reddedilir(istemci):
    for kotu in ("abc", "0.05", "2"):
        yanit = istemci.post(
            "/ayarlar/hassasiyet", data={"hassasiyet": kotu}, follow_redirects=False
        )
        assert "hata" in yanit.headers["location"], kotu


# ---- uyarı akışı ----


def test_yakinlik_olayi_akisa_dusser(ayarlar):
    analiz = _analiz(ayarlar)
    analiz._olay_uret(1.2, 1.5, "foto.jpg")
    olaylar = analiz.olaylar()
    assert len(olaylar) == 1
    assert olaylar[0]["mesafe_m"] == 1.2
    assert olaylar[0]["esik_m"] == 1.5
    assert analiz.son_olay_id == 1


def test_gorulen_olaylar_tekrar_gonderilmez(ayarlar):
    analiz = _analiz(ayarlar)
    for _ in range(3):
        analiz._olay_uret(1.0, 1.5, None)
    assert len(analiz.olaylar(sonra=0)) == 3
    assert len(analiz.olaylar(sonra=2)) == 1
    assert analiz.olaylar(sonra=3) == []


def test_canli_ucu_olaylari_dondurur(istemci):
    veri = istemci.get("/canli").json()
    for anahtar in ("olaylar", "son_olay_id", "son_hata"):
        assert anahtar in veri, anahtar


def test_silme_onayi_js_kaynagina_gomulmez(istemci):
    """ESKİ HATA: onay metni onsubmit içine gömülüydü; adında kesme işareti olan
    bir kayıt ("Ahmet'in aracı") JS'i bozup onay SORULMADAN siliniyordu."""
    for yol in ("/", "/kutuphane"):
        metin = istemci.get(yol).text
        assert 'onsubmit="return confirm(' not in metin, yol


def test_gunluk_dosyasi_olusur(ayarlar):
    analiz = _analiz(ayarlar)
    analiz._log.info("deneme satırı")
    for islem in analiz._log.handlers:
        islem.flush()
    gunluk = ayarlar.veritabani.parent / "loglar" / "otopark.log"
    assert gunluk.is_file()
    assert "deneme satırı" in gunluk.read_text(encoding="utf-8")


def test_kanit_fotografi_guvenli_yazilir(ayarlar):
    """cv2.imwrite Türkçe klasör adında hata FIRLATMADAN başarısız olur."""
    analiz = _analiz(ayarlar)
    ad = analiz._kirpik_kaydet(_kare(), (50.0, 50.0, 200.0, 220.0))
    assert ad is not None
    dosya = ayarlar.goruntu_klasoru / ad
    assert dosya.is_file() and dosya.read_bytes()[:2] == b"\xff\xd8"


def test_zaman_damgasi_gecerli(ayarlar):
    """Olay akışındaki saat, ekranda gösterilebilir olmalı."""
    analiz = _analiz(ayarlar)
    analiz._olay_uret(1.0, 1.5, None)
    assert analiz.olaylar()[0]["zaman"] == zaman.saat(zaman.simdi_utc())
