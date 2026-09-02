"""Model hatası EKRANDA: sayfa gerçekten üretilir, dönen HTML taranır.

NEDEN AYRI BİR TEST — kardeş dosya `test_model_hatasi_metni.py` istisnanın
`mesaj` alanına bakar, bu dosya SAYFANIN KENDİSİNE bakar. Aradaki fark, bu
depoda gerçekten açık kalmış olan boşluktur:

    Sızıntı metin SABİTİNDE değil, ÇALIŞMA ANINDA oluşuyordu. Dosya yolu
    mesaja f-string ile giriyor, kaynak dosyadaki hiçbir sabitte GEÇMİYORDU.
    "Kaynakta 'yolox' ara" tipi bir bekçi bunu göremez; yakalamanın tek yolu
    sayfayı üretip çıktısını okumaktır.

Bu yüzden burada hiçbir metin elle kurulmaz: ayarlar gerçek bir "model yok" /
"model bozuk" durumuna kurulur, sayfa FastAPI ile GERÇEKTEN istenir ve dönen
gövde taranır.

Sınanan iki ekran (model hatasının kullanıcıya göründüğü her yer):
  * `/`        Özet sayfası — analiz iş parçacığının bulduğu hata
  * `/tarama`  Kare tarama — model olmadan taranamayan görüntünün uyarısı

Sınanan iki dal: dosya YOK ve dosya BOZUK.

Her sınamada İKİ yön birden denetlenir; biri olmadan diğeri yanıltır:
  1. Teknik iz ekrana ÇIKMAMALI (dosya adı, uzantı, klasör, indirme adresi,
     tam yol, ham istisna).
  2. Markalı metin ekrana ÇIKMALI. Yoksa bomboş bir sayfa da "sızıntı yok"
     sayılır ve test hiçbir şey korumaz.
"""

from __future__ import annotations

import io
import re
from dataclasses import replace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.uygulama import uygulama_olustur

# Ekranda ASLA görünmemesi gereken izler. Kullanıcı bunların hiçbirini
# kullanamaz; teknik destek ise aynı ayrıntıyı günlükten okur.
YASAKLI = re.compile(
    r"yolox"  # model ailesinin adı
    r"|\.onnx"  # dosya uzantısı
    r"|megvii"  # ağırlıkları yayımlayan kurum
    r"|github\.com"  # indirme adresi
    r"|indir\.sh"  # indirme betiği
    r"|models[/\\]"  # klasör adı (Mac ve Windows yazımı)
    r"|onnxruntime"  # kütüphane adı
    r"|Traceback",  # ham istisna dökümü
    re.I,
)

# Mutlak dosya yolu işareti: Windows sürücü harfi ya da bilinen kök klasörler.
# Sayfadaki "/static/…" gibi web adresleri bilerek dışarıda kalır — onlar yol
# değil, adrestir.
# Windows dalında yalnızca ters bölü aranır ve önünde harf OLMAMASI istenir:
# "rtsp://" ve "http://" da "p:/" desenine uyuyordu; sayfadaki örnek kamera
# adresi testi boşuna kırıyordu.
MUTLAK_YOL = re.compile(
    r"(?<![A-Za-z])[A-Za-z]:\\"  # Windows: C:\Users\...
    r"|/Users/|/home/|/private/|/var/folders/|/tmp/"  # Mac ve Linux kökleri
)

# (model dosyası, ekranda görünmesi gereken ad). Dosya adları teknik gerçektir
# ve DEĞİŞMEZ; ekranda yalnızca karşılarındaki markalı ad görünür.
KADEMELER = [
    ("yolox_s.onnx", "NextGen AI İsabetli"),
    ("yolox_tiny.onnx", "NextGen AI Hızlı"),
    ("kendi_modelim.onnx", "NextGen AI (özel model)"),
]

DALLAR = [
    pytest.param(False, id="dosya-yok"),
    pytest.param(True, id="dosya-bozuk"),
]


@pytest.fixture
def kur(ayarlar):
    """Model dosyası olmayan (ya da bozuk olan) bir kurulum hazırlar.

    Yol BİLEREK `…/models/yolox_s.onnx` biçimindedir: yasaklı parçaların
    (yolox, .onnx, models/, mutlak yol) HEPSİ gerçekten o yolun içindedir.
    Böylece "ekranda yok" sonucu tesadüf değildir — sızsaydı yakalanırdı.
    """

    def _kur(dosya: str, bozuk: bool):
        yol = ayarlar.kok / "models" / dosya
        if bozuk:
            yol.parent.mkdir(parents=True, exist_ok=True)
            yol.write_bytes(b"bu bir model dosyasi DEGIL")
        return replace(ayarlar, model_dosyasi=yol)

    return _kur


def _sizinti_yok(metin: str, ayar, nerede: str) -> None:
    kacak = YASAKLI.search(metin)
    assert not kacak, f"{nerede}: teknik iz görünüyor → {kacak.group(0)!r}"
    yol = MUTLAK_YOL.search(metin)
    assert not yol, f"{nerede}: mutlak dosya yolu görünüyor → {yol.group(0)!r}"
    # Bu kurulumun kendi yolları da adıyla aranır (desen tutmasa bile)
    for beklenmeyen in (str(ayar.model_dosyasi), str(ayar.model_dosyasi.parent), str(ayar.kok)):
        assert beklenmeyen not in metin, f"{nerede}: tam yol görünüyor → {beklenmeyen}"


def _jpeg() -> io.BytesIO:
    gorsel = np.zeros((60, 60, 3), dtype=np.uint8)
    return io.BytesIO(cv2.imencode(".jpg", gorsel)[1].tobytes())


def _modeli_yuklemeyi_dene(ayar):
    """Analiz'in ÜRETİMDEKİ model yükleme adımını kameraya girmeden koşturur.

    `_dur` önceden kurulduğu için `_dongu` yalnızca model denemesini yapar ve
    kamera döngüsüne HİÇ girmeden çıkar. Sayfaya düşen metin böylece testin
    uydurduğu bir metin değil, sistem çalışırken üretilenin ta kendisidir —
    bu testin bütün değeri buradadır.
    """
    from app.analiz import Analiz

    analiz = Analiz(ayar)
    analiz._dur.set()
    analiz._dongu()
    return analiz


@pytest.mark.parametrize("bozuk", DALLAR)
@pytest.mark.parametrize(("dosya", "marka"), KADEMELER)
def test_ozet_sayfasinda_model_hatasi_sade_gorunur(kur, dosya, marka, bozuk):
    """Özet sayfasındaki kırmızı kutu: markalı metin var, teknik iz yok."""
    ayar = kur(dosya, bozuk)
    with TestClient(uygulama_olustur(ayar, analiz_ac=False)) as istemci:
        # Şema, istemci açılırken uygulanır; analiz ondan SONRA kurulmalı
        analiz = _modeli_yuklemeyi_dene(ayar)
        istemci.app.state.analiz = analiz
        sayfa = istemci.get("/").text

    assert analiz.model_hatasi, "Model açılamadı ama ekrana hiçbir uyarı düşmedi"
    # Sızıntı denetimi ÖNCE gelir: bu testin varlık sebebi odur ve kırıldığında
    # kullanıcının okuyacağı hata mesajı "şu teknik iz ekranda görünüyor"
    # olmalıdır — kaçak, ikincil bir eşleşme hatasının altında kalmasın.
    _sizinti_yok(sayfa, ayar, "Özet sayfası")
    # Ekrana basılan metin, çalışırken üretilen metnin TA KENDİSİ olmalı
    assert analiz.model_hatasi in sayfa, "Hata metni sayfada göründüğü gibi geçmiyor"
    assert marka in analiz.model_hatasi
    assert "NextGen AI" in sayfa


@pytest.mark.parametrize("bozuk", DALLAR)
@pytest.mark.parametrize(("dosya", "marka"), KADEMELER)
def test_tarama_sayfasinda_model_hatasi_sade_gorunur(kur, dosya, marka, bozuk):
    """Kare tarama: model olmadan tarama yapılamaz, uyarısı markalı olmalı.

    `marka` burada kullanılmaz — tarama, ayarları görmediği için kademeyi
    (Hızlı/İsabetli) bilemez ve markayı kademesiz yazar. Sınama yine de her
    kademeyle koşar: hangi dosya kurulu olursa olsun ekrana teknik iz düşmesin.
    """
    ayar = kur(dosya, bozuk)
    with TestClient(uygulama_olustur(ayar, analiz_ac=False)) as istemci:
        sayfa = istemci.post(
            "/tarama",
            files=[("kareler", ("deneme.jpg", _jpeg(), "image/jpeg"))],
            data={"esik_yuzde": "42"},
        ).text

    _sizinti_yok(sayfa, ayar, "Tarama sayfası")
    assert "NextGen AI" in sayfa, "Model uyarısı markasız yazılmış"
    assert "tarama yapılamadı" in sayfa


def test_ekran_metni_kullaniciya_NE_YAPACAGINI_soyler(kur):
    """Metin yalnızca sade olmakla yetinmez; yapılacak adımı da söyler.

    Yazılım bilmeyen bir kullanıcı için "sızıntı yok" tek başına yeterli
    değildir: elinde yapabileceği bir adım kalmalıdır. İki adım da aranır,
    çünkü Başlat dosyası modeli İNDİRMEZ — dosya gerçekten yoksa yeniden
    başlatmak düzeltmez ve kullanıcının ikinci adımı görmesi şarttır.
    """
    ayar = kur("yolox_s.onnx", bozuk=False)
    with TestClient(uygulama_olustur(ayar, analiz_ac=False)) as istemci:
        analiz = _modeli_yuklemeyi_dene(ayar)
        istemci.app.state.analiz = analiz
        sayfa = istemci.get("/").text

    metin = analiz.model_hatasi
    assert "Başlat" in metin and "çift tık" in metin  # 1. adım: yeniden başlat
    assert "kurulumu yapan kişi" in metin  # 2. adım: asıl çözüm
    assert "sayımı durur" in metin  # sonucu da söylenir
    assert metin in sayfa


def test_beklenmeyen_model_hatasi_da_sade_gorunur(kur, monkeypatch):
    """ModelHatasi DIŞINDA bir istisna gelirse de ekrana ham metin çıkmasın.

    Analiz'deki genel `except` dalı, dinamik eksenli bir model dosyasında
    ValueError yakalar. Eskiden o dal ham istisnayı doğrudan ekrana basıyordu;
    metin oradan da sızmamalı.
    """
    ayar = kur("yolox_s.onnx", bozuk=False)

    def _patla(*_args, **_kwargs):
        raise ValueError(f"beklenmedik bicim: {ayar.model_dosyasi}")

    monkeypatch.setattr("app.analiz.Tespitci", _patla)
    with TestClient(uygulama_olustur(ayar, analiz_ac=False)) as istemci:
        analiz = _modeli_yuklemeyi_dene(ayar)
        istemci.app.state.analiz = analiz
        sayfa = istemci.get("/").text

    assert "NextGen AI İsabetli" in analiz.model_hatasi
    assert analiz.model_hatasi in sayfa
    _sizinti_yok(sayfa, ayar, "Özet sayfası (beklenmeyen hata)")
