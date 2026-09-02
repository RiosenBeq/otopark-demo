"""Nesne tespiti: YOLOX (Apache-2.0) + ONNX Runtime — torch gerekmez."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import cv2
import numpy as np

from app.ayarlar import gorunen_model_adi

# COCO sınıfı → bizim tip. Otoparkta ilgilendiğimiz her şey burada.
SINIF_ESLEME: dict[int, str] = {
    0: "insan",
    2: "arac",  # otomobil
    3: "arac",  # motosiklet
    5: "arac",  # otobüs / minibüs
    7: "arac",  # kamyonet / kamyon
}


# Kişi (COCO 0) eşiği çarpanı ve gürültü kutusu alt sınırı
KISI_ESIK_CARPANI = 0.8
EN_KUCUK_KENAR_PX = 6


_log = logging.getLogger("otopark.tespit")

# Model açılamadığında kullanıcıya söylenecek çözüm.
# Kullanıcı yazılımcı değildir ve terminal kullanmaz — bu yüzden ekrandaki
# metinde komut, dosya yolu ya da betik adı GEÇMEZ.
#
# İKİ ADIM, SIRAYLA — ve ikincisi ASIL çözümdür:
#   1) Yeniden başlatmak ucuzdur ve gerçekten işe yaradığı hâller vardır
#      (dosya yarım yazılmışken açılmış, başka program dosyayı kilitlemiş).
#   2) Ama Başlat dosyası modeli İNDİRMEZ; model kuruluma dahildir. Dosya
#      gerçekten yoksa yeniden başlatmak DURUMU DÜZELTMEZ. Bu yüzden metin,
#      yeniden başlatmayı tek çare gibi sunmaz: aynı yazı yine çıkarsa
#      kullanıcı kurulumu yapan kişiye yönlendirilir ve o kişiye NE
#      söyleyeceği de yazılır. Aksi hâlde kullanıcı aynı adımı tekrarlayıp
#      sıkışıp kalıyordu.
# Sonucun da söylenmesi gerekir: model olmadan sayım durur; kullanıcı ekranda
# sayaç ilerlemeyince bunun ayrı bir arıza olduğunu sanmasın.
YENIDEN_BASLATMA_ONERISI = (
    "Yapılacak: uygulamayı kapatın ve Başlat dosyasına yeniden çift tıklayın. "
    "Aynı yazı yine çıkıyorsa kurulumu yapan kişiyi arayın — tanıma modelinin "
    "bu bilgisayara kurulması gerekiyor. O kurulana kadar araç ve kişi sayımı durur."
)


class ModelHatasi(Exception):
    """Ekrana çıkan sade metni, günlüğe yazılan teknik ayrıntıdan AYIRIR.

    `mesaj` (ve `str(hata)`) KULLANICIYA gösterilir: markalı model adı ve ne
    yapması gerektiği. Dosya adı, tam yol ve özgün istisna metni yalnızca
    `teknik` alanındadır; o alan günlüğe yazılır, ekrana ASLA çıkmaz.

    Neden ayrı: eskiden tek bir metin hem ekrana hem günlüğe gidiyordu; ekranda
    dosya yolu ve çalıştırılacak terminal komutu görünüyordu. Kullanıcı bunların
    hiçbirini yapamaz, teknik destek ise tam yolu görmek zorundadır.
    """

    def __init__(self, mesaj: str, teknik: str = "") -> None:
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.teknik = teknik or mesaj


class Tespitci:
    def __init__(self, model_dosyasi: Path, cihaz: str = "cpu", guven: float = 0.35) -> None:
        import onnxruntime

        if not model_dosyasi.exists():
            teknik = f"Tespit modeli bulunamadı: {model_dosyasi}"
            _log.error(teknik)
            raise ModelHatasi(
                f"{gorunen_model_adi(str(model_dosyasi))} bu bilgisayarda kurulu değil. "
                f"{YENIDEN_BASLATMA_ONERISI}",
                teknik,
            )
        saglayicilar = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if cihaz == "cuda"
            else ["CPUExecutionProvider"]
        )
        try:
            self._oturum = onnxruntime.InferenceSession(str(model_dosyasi), providers=saglayicilar)
        except Exception as hata:
            teknik = f"Model yüklenemedi ({model_dosyasi}): {hata}"
            _log.error(teknik)
            raise ModelHatasi(
                f"{gorunen_model_adi(str(model_dosyasi))} açılamadı; "
                f"dosyası yarım inmiş ya da bozulmuş olabilir. {YENIDEN_BASLATMA_ONERISI}",
                teknik,
            ) from hata
        girdi = self._oturum.get_inputs()[0]
        self._girdi_adi = girdi.name
        self._boy = int(girdi.shape[2])
        self.guven = guven
        self._kilit = threading.Lock()

    def bul(self, kare: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """BGR kare → (kutular_xyxy, güvenler, tipler['insan'|'arac'])."""
        girdi, oran = self._on_isle(kare)
        with self._kilit:
            cikti = self._oturum.run(None, {self._girdi_adi: girdi})[0]
        return self._son_isle(cikti[0], oran, kare.shape[1], kare.shape[0])

    def _on_isle(self, kare: np.ndarray) -> tuple[np.ndarray, float]:
        dolgulu = np.full((self._boy, self._boy, 3), 114, dtype=np.uint8)
        oran = min(self._boy / kare.shape[0], self._boy / kare.shape[1])
        yeni = (int(kare.shape[1] * oran), int(kare.shape[0] * oran))
        dolgulu[: yeni[1], : yeni[0]] = cv2.resize(kare, yeni, interpolation=cv2.INTER_LINEAR)
        girdi = dolgulu.transpose(2, 0, 1).astype(np.float32)[np.newaxis]
        return np.ascontiguousarray(girdi), oran

    def _son_isle(self, cikti, oran, kare_g, kare_y):
        izgaralar, adimlar = [], []
        for adim in (8, 16, 32):
            kenar = self._boy // adim
            xv, yv = np.meshgrid(np.arange(kenar), np.arange(kenar))
            izgara = np.stack((xv, yv), 2).reshape(-1, 2)
            izgaralar.append(izgara)
            adimlar.append(np.full((izgara.shape[0], 1), adim))
        izgaralar = np.concatenate(izgaralar, 0)
        adimlar = np.concatenate(adimlar, 0)

        cikti = cikti.copy()
        cikti[:, :2] = (cikti[:, :2] + izgaralar) * adimlar
        cikti[:, 2:4] = np.exp(cikti[:, 2:4]) * adimlar

        skorlar = cikti[:, 4:5] * cikti[:, 5:]
        bos = (np.empty((0, 4)), np.empty((0,)), np.empty((0,), dtype=object))

        # SINIF SEÇİMİ: 80 COCO sınıfının TÜMÜ üzerinde argmax almak, bizim
        # ilgilendiğimiz sınıfı ilgilenmediğimiz bir sınıf geçtiğinde tespiti
        # TAMAMEN düşürüyordu. Otoparkta bir araç kolayca 0,34 "otomobil" /
        # 0,36 "kamyonet olmayan bir sınıf" okunabilir. Artık yalnızca
        # ilgilendiğimiz sınıflara bakılır (YOLOX'un class-aware yolu).
        ilgi_idler = np.array(sorted(SINIF_ESLEME))
        ilgi_skorlari = skorlar[:, ilgi_idler]
        yerel = ilgi_skorlari.argmax(1)
        sinif_idler = ilgi_idler[yerel]
        guvenler = ilgi_skorlari[np.arange(len(ilgi_skorlari)), yerel]

        # Kişiler sahnede küçük/kısmen örtülü görünür; eşiği biraz daha cömert
        # tutmak kaçan kişileri azaltır (yanlış pozitifler NMS + takip ile elenir)
        sinif_esikleri = np.where(sinif_idler == 0, self.guven * KISI_ESIK_CARPANI, self.guven)
        maske = guvenler >= sinif_esikleri
        if not maske.any():
            return bos

        merkez = cikti[maske, :4] / oran
        guvenler, sinif_idler = guvenler[maske], sinif_idler[maske]
        kutular = np.empty_like(merkez)
        kutular[:, 0] = (merkez[:, 0] - merkez[:, 2] / 2).clip(0, kare_g)
        kutular[:, 1] = (merkez[:, 1] - merkez[:, 3] / 2).clip(0, kare_y)
        kutular[:, 2] = (merkez[:, 0] + merkez[:, 2] / 2).clip(0, kare_g)
        kutular[:, 3] = (merkez[:, 1] + merkez[:, 3] / 2).clip(0, kare_y)

        # Birkaç pikselden küçük kutular gürültüdür; takibe girmeden elensin
        genislikler = kutular[:, 2] - kutular[:, 0]
        yukseklikler = kutular[:, 3] - kutular[:, 1]
        boyut_maskesi = (genislikler >= EN_KUCUK_KENAR_PX) & (yukseklikler >= EN_KUCUK_KENAR_PX)
        if not boyut_maskesi.any():
            return bos
        kutular = kutular[boyut_maskesi]
        guvenler, sinif_idler = guvenler[boyut_maskesi], sinif_idler[boyut_maskesi]

        # Tip-bilinçli NMS: kutular TİP başına ayrı uzaya kaydırılır. Aynı tipe
        # eşlenen sınıflar (örn. otomobil+kamyon → arac) birbirini bastırabilsin
        # ki aynı nesne iki sınıf olarak çift sayılmasın; farklı tipler
        # (kişi vs diğer) ise birbirini bastırmasın.
        tip_indeksleri = np.where(sinif_idler == 0, 0.0, 1.0)
        kaydirma = tip_indeksleri[:, None] * (max(kare_g, kare_y) + 1.0)
        nms_kutulari = kutular + kaydirma
        secilen = cv2.dnn.NMSBoxes(
            [(x1, y1, x2 - x1, y2 - y1) for x1, y1, x2, y2 in nms_kutulari.tolist()],
            guvenler.tolist(),
            self.guven * KISI_ESIK_CARPANI,  # sınıf eşiği zaten uygulandı
            0.45,
        )
        if len(secilen) == 0:
            return bos
        secilen = np.array(secilen).reshape(-1)
        tipler = np.array([SINIF_ESLEME[int(s)] for s in sinif_idler[secilen]], dtype=object)
        return kutular[secilen], guvenler[secilen], tipler
