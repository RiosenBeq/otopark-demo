"""Arayüz testleri: özet sayfası, ayarlar, rapor, görsel servisi."""

from __future__ import annotations

import json

from app import veritabani, zaman


def _gecis_ekle(baglanti, tip="arac", takip_id=1, renk="kırmızı", gun=None):
    gun = gun or zaman.bugun()
    simdi = zaman.simdi_utc()
    baglanti.execute(
        "INSERT OR IGNORE INTO gecisler (tip, takip_id, gun, ilk_gorulme, son_gorulme, renk) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tip, takip_id, gun, simdi, simdi, renk if tip == "arac" else None),
    )
    baglanti.commit()


def test_ozet_sayfasi_acilir(istemci):
    yanit = istemci.get("/")
    assert yanit.status_code == 200
    assert "NextGen" in yanit.text
    assert "araç geldi" in yanit.text
    assert "kişi geçti" in yanit.text


def test_sayimlar_ve_renkler_gorunuyor(istemci, ayarlar):
    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        _gecis_ekle(baglanti, "arac", 1, "kırmızı")
        _gecis_ekle(baglanti, "arac", 2, "beyaz")
        _gecis_ekle(baglanti, "arac", 3, "beyaz")
        _gecis_ekle(baglanti, "insan", 4)
        _gecis_ekle(baglanti, "insan", 5)
    finally:
        baglanti.close()

    sayfa = istemci.get("/").text
    assert ">3<" in sayfa  # 3 araç
    assert ">2<" in sayfa  # 2 kişi
    assert "beyaz" in sayfa and "kırmızı" in sayfa

    canli = istemci.get("/canli").json()
    assert canli["arac"] == 3
    assert canli["insan"] == 2


def test_ayni_arac_iki_kez_sayilmaz(istemci, ayarlar):
    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        _gecis_ekle(baglanti, "arac", 7, "mavi")
        _gecis_ekle(baglanti, "arac", 7, "mavi")  # aynı takip → UNIQUE engeller
    finally:
        baglanti.close()
    assert istemci.get("/canli").json()["arac"] == 1


def test_mesafe_esigi_kullanici_belirler(istemci, ayarlar):
    yanit = istemci.post("/ayarlar/mesafe", data={"esik_m": "2,5"}, follow_redirects=False)
    assert yanit.status_code == 303
    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        assert veritabani.ayarlari_oku(baglanti)["mesafe_esigi_m"] == "2.5"
    finally:
        baglanti.close()
    assert "2,5" in istemci.get("/").text


def test_gecersiz_esik_anlasilir_hata(istemci):
    yanit = istemci.post("/ayarlar/mesafe", data={"esik_m": "çok yakın"}, follow_redirects=False)
    assert yanit.status_code == 303
    assert "hata=" in yanit.headers["location"]
    assert "sayı olmalı" in istemci.get(yanit.headers["location"]).text


def test_kalibrasyon_goruntu_gelmeden_uyarir(istemci, ayarlar):
    # Analiz kapalı olduğu için kare boyutu yok → uydurma ölçek KAYDEDİLMEMELİ
    from urllib.parse import parse_qs, unquote, urlparse

    yanit = istemci.post(
        "/ayarlar/kalibrasyon",
        data={"cizgi": json.dumps([[0.2, 0.5], [0.8, 0.5]]), "metre": "5"},
        follow_redirects=False,
    )
    assert yanit.status_code == 303
    mesaj = parse_qs(urlparse(unquote(yanit.headers["location"])).query)["hata"][0]
    assert "Görüntü henüz gelmedi" in mesaj

    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        assert veritabani.ayarlari_oku(baglanti)["olcek_m_px"] == "0"  # ölçek yazılmadı
    finally:
        baglanti.close()


def test_kalibrasyon_olcegi_kaydeder(istemci, ayarlar):
    # Kare boyutu bilindiğinde ölçek hesaplanır: 1000 px karede yarısı = 5 m
    class SahteAnaliz:
        kare_boyutu = (1000, 600)

    istemci.app.state.analiz = SahteAnaliz()
    yanit = istemci.post(
        "/ayarlar/kalibrasyon",
        data={"cizgi": json.dumps([[0.25, 0.5], [0.75, 0.5]]), "metre": "5"},
        follow_redirects=False,
    )
    assert yanit.status_code == 303
    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        ayar = veritabani.ayarlari_oku(baglanti)
        assert abs(float(ayar["olcek_m_px"]) - 0.01) < 1e-9  # 500 px = 5 m
        assert ayar["referans_metre"] == "5"
    finally:
        baglanti.close()
    metin = istemci.get("/").text
    assert "kalibrasyon hazır" in metin
    assert "1 metre ≈ 100 piksel" in metin  # 0,01 m/px → 100 px/m


def test_csv_raporu(istemci, ayarlar):
    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        _gecis_ekle(baglanti, "arac", 11, "yeşil")
    finally:
        baglanti.close()
    yanit = istemci.get("/rapor.csv")
    assert yanit.status_code == 200
    assert "Gün;Tip;Saat;Renk" in yanit.text
    assert "yeşil" in yanit.text


def test_gun_sifirlama(istemci, ayarlar):
    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        _gecis_ekle(baglanti, "arac", 21, "mor")
    finally:
        baglanti.close()
    assert istemci.get("/canli").json()["arac"] == 1
    istemci.post("/sifirla", data={"gun": zaman.bugun()}, follow_redirects=False)
    assert istemci.get("/canli").json()["arac"] == 0


def test_gorsel_yolu_disari_cikamaz(istemci, ayarlar):
    (ayarlar.goruntu_klasoru / "arac.jpg").write_bytes(b"sahte-jpeg")
    assert istemci.get("/gorsel/arac.jpg").content == b"sahte-jpeg"
    assert istemci.get("/gorsel/../otopark.db").status_code == 404
    assert istemci.get("/gorsel/%2e%2e%2fotopark.db").status_code == 404


def test_onizleme_yoksa_204(istemci):
    assert istemci.get("/onizleme.jpg").status_code == 204


def test_homografi_kaydedilir_ve_aktif_olur(istemci, ayarlar):
    """Hassas (4 nokta) kalibrasyon: kaydet → aktif yöntem olur."""
    import json

    from app import veritabani

    koseler = [[0.40, 0.50], [0.60, 0.50], [0.80, 0.95], [0.20, 0.95]]
    yanit = istemci.post(
        "/ayarlar/homografi",
        data={"noktalar": json.dumps(koseler), "en_m": "2,5", "boy_m": "5"},
        follow_redirects=False,
    )
    assert yanit.status_code == 303
    assert "hata" not in yanit.headers["location"]

    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        ayar = veritabani.ayarlari_oku(baglanti)
        assert ayar["kalibrasyon_modu"] == "homografi"
        matris = json.loads(ayar["homografi"])
        assert len(matris) == 3 and len(matris[0]) == 3
        assert ayar["homografi_en_m"] == "2.5"
    finally:
        baglanti.close()
    assert "kalibrasyon hazır" in istemci.get("/").text


def test_dogrusal_koselerle_homografi_anlasilir_hata(istemci):
    import json

    koseler = [[0.1, 0.5], [0.4, 0.5], [0.7, 0.5], [0.9, 0.5]]  # aynı doğru
    yanit = istemci.post(
        "/ayarlar/homografi",
        data={"noktalar": json.dumps(koseler), "en_m": "2,5", "boy_m": "5"},
        follow_redirects=False,
    )
    assert yanit.status_code == 303
    assert "hata" in yanit.headers["location"]


def test_bozuk_noktalarla_homografi_reddedilir(istemci):
    yanit = istemci.post(
        "/ayarlar/homografi",
        data={"noktalar": "bozuk-json", "en_m": "2,5", "boy_m": "5"},
        follow_redirects=False,
    )
    assert yanit.status_code == 303
    assert "hata" in yanit.headers["location"]


def test_mod_gecisi_yalniz_ayarli_yonteme_izin_verir(istemci, ayarlar):
    import json

    # Hiçbir yöntem ayarlı değilken geçiş reddedilir
    yanit = istemci.post(
        "/ayarlar/kalibrasyon-modu", data={"mod": "homografi"}, follow_redirects=False
    )
    assert "hata" in yanit.headers["location"]

    # Homografi kaydedilince homografi aktif olur; çizgi ayarlanınca ona geçilebilir
    koseler = [[0.40, 0.50], [0.60, 0.50], [0.80, 0.95], [0.20, 0.95]]
    istemci.post(
        "/ayarlar/homografi",
        data={"noktalar": json.dumps(koseler), "en_m": "2,5", "boy_m": "5"},
    )

    class SahteAnaliz:
        kare_boyutu = (1000, 600)

    istemci.app.state.analiz = SahteAnaliz()
    istemci.post(
        "/ayarlar/kalibrasyon",
        data={"cizgi": json.dumps([[0.25, 0.5], [0.75, 0.5]]), "metre": "5"},
    )
    # Çizgi kaydı modu "cizgi" yaptı; homografiye tek tıkla dönülebilir
    yanit = istemci.post(
        "/ayarlar/kalibrasyon-modu", data={"mod": "homografi"}, follow_redirects=False
    )
    assert "mesaj" in yanit.headers["location"]

    from app import veritabani

    baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
    try:
        assert veritabani.ayarlari_oku(baglanti)["kalibrasyon_modu"] == "homografi"
    finally:
        baglanti.close()
