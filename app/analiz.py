"""Analiz iş parçacığı: kaynak → tespit → takip → sayım/renk/mesafe → kayıt.

Tek arka plan iş parçacığı; web arayüzüyle aynı süreçte çalışır.
Sayım ilkesi: her BENZERSİZ takip (track) günde bir kez sayılır. Aynı araç
100 karede görünse de "1 araç"tır; kamera açılıp kapansa bile aynı gün
içinde yeni takip ID'si aldığı için yeniden sayılır — bu bilinen sınırdır
ve ekranda dürüstçe yazılıdır.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

from collections import deque  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import supervision as sv  # noqa: E402

from app import renk as renk_modulu  # noqa: E402
from app import veritabani, zaman  # noqa: E402
from app.ayarlar import Ayarlar, gorunen_model_adi  # noqa: E402
from app.mesafe import Arac, hesaplayici_kur, yakin_ciftler  # noqa: E402
from app.tespit import (  # noqa: E402
    YENIDEN_BASLATMA_ONERISI,
    ModelHatasi,
    Tespitci,
)

# Bir takip bu kadar kez görülmeden sayılmaz: tek karelik yanlış tespitler
# günlük sayacı şişirmesin.
_SAYMA_ESIGI = 3

# Kayıp bir izin hatırlanma süresi (saniye). Araç kısa süre örtülüp geri
# gelince AYNI takip numarasını alsın ve ikinci kez sayılmasın diye.
_IZ_HAFIZASI_SN = 15.0

# Renk kararı için toplanan oy sayısı (tek kareye güvenilmez)
_RENK_OYU_SAYISI = 5
# Canlı sayaç kaç karenin ortancasıyla gösterilsin (ekran titremesin)
_CANLI_PENCERE = 5
# Yakınlık olayı için gereken ARDIŞIK onay: tek karelik kutu hatası, kalıcı
# bir olay ve fotoğraf yazmamalı
_YAKINLIK_ONAY = 3

# Ekrandan ayarlanabilen tespit hassasiyetinin sınırları
_HASSASIYET_EN_AZ = 0.15
_HASSASIYET_EN_COK = 0.90

_RENKLER = {"arac": (60, 140, 255), "insan": (80, 200, 80)}


def _log_kur(ayarlar: Ayarlar) -> logging.Logger:
    """Günlük dosyası: veri/loglar/otopark.log.

    Eskiden hiçbir yere yazılmıyordu; hata yalnızca `durum` metnine düşüyor ve
    bir sonraki başarılı karede siliniyordu.
    """
    log = logging.getLogger("otopark")
    klasor = ayarlar.veritabani.parent / "loglar"
    hedef = str((klasor / "otopark.log").resolve())
    if log.handlers:
        if any(getattr(h, "baseFilename", None) == hedef for h in log.handlers):
            return log
        for h in list(log.handlers):
            log.removeHandler(h)
            h.close()
    log.setLevel(logging.INFO)
    log.propagate = False
    try:
        klasor.mkdir(parents=True, exist_ok=True)
        dosya = RotatingFileHandler(
            hedef, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        dosya.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(dosya)
    except OSError:
        pass
    ekran = logging.StreamHandler()
    ekran.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(ekran)
    return log


class Analiz:
    def __init__(self, ayarlar: Ayarlar) -> None:
        self.ayarlar = ayarlar
        self._dur = threading.Event()
        self._is = threading.Thread(target=self._dongu, name="analiz", daemon=True)
        self._kilit = threading.Lock()
        self._son_jpeg: bytes | None = None
        self._kare_boyutu: tuple[int, int] = (0, 0)

        self.durum = "başlatılıyor"
        self.model_hatasi: str | None = None
        self.kaynak_hatasi: str | None = None
        self.canli_arac = 0
        self.canli_insan = 0

        self._tespitci: Tespitci | None = None
        # ByteTrack, aktivasyon eşiğinin ALTINDA kalan tespitlerle yeni iz
        # BAŞLATMAZ. Eşik, tespit güveniyle (0,35) aynı seviyede olursa uzak
        # ve küçük araçlar tespit edilse bile hiç takip edilmez ve sayaca
        # girmez; bu yüzden belirgin şekilde altında tutulur.
        #
        # DİKKAT: supervision, lost_track_buffer'ı kare olarak SAYMAZ:
        #     max_time_lost = int(frame_rate / 30 * lost_track_buffer)
        # Kardeş projede (LAFFOGATO) çift sayımın kök nedeni buydu — 45 gibi
        # düz bir sayı 3 fps'te yalnızca 4 kare = 1,3 saniye hafıza demekti.
        # İz hafızası bu yüzden SANİYE cinsinden ifade edilir.
        self._hassasiyet = 0.35
        self._izleyici = self._izleyici_kur(self._hassasiyet)
        self._gorulme: dict[tuple[str, int], int] = {}
        self._sayildi: set[tuple[str, str, int]] = set()
        self._son_yakinlik: dict[tuple[int, int], float] = {}
        # Takip numaraları izleyici her kurulduğunda 1'den başlar. gecisler
        # tablosunda UNIQUE (tip, gun, takip_id) olduğu için, uygulama gün
        # içinde yeniden başlatıldığında yeni araçlar ESKİ numaralara çakışıyor
        # ve INSERT OR IGNORE ile SESSİZCE sayılmıyordu. Ofset, o günkü en
        # büyük numaranın üstünden devam ederek çakışmayı imkânsız kılar.
        self._id_ofseti: dict[str, int] = {}
        # Canlı sayaç için kısa geçmiş: tek karelik kaçaklar ekranı titretmesin
        self._canli_gecmis: dict[str, deque] = {}
        # Renk kararı için biriken oylar (tek kareye güvenilmez)
        self._renk_oylari: dict[tuple[str, int], list[str]] = {}
        # Yakınlık için ardışık onay sayacı (tek karelik kutu hatası olay yazmasın)
        self._yakinlik_sayaci: dict[tuple[int, int], int] = {}
        # Yakınlık uyarıları: ekran bunları tek tek okur (sayaç farkı değil)
        self._olaylar: deque = deque(maxlen=100)
        self._olay_sayaci = 0
        self.son_hata: str = ""
        self._log = _log_kur(ayarlar)

    # ---- yaşam döngüsü ----

    def baslat(self) -> None:
        self._is.start()

    def durdur(self) -> bool:
        """Durdurma isteği gönderir; iş parçacığı gerçekten bittiyse True döner."""
        self._dur.set()
        if self._is.is_alive():
            self._is.join(timeout=8)
        return not self._is.is_alive()

    def onizleme(self) -> bytes | None:
        with self._kilit:
            return self._son_jpeg

    def sayaclari_sifirla(self, gun: str) -> None:
        """Ekrandan 'günü sıfırla' denince analizin sayım hafızası da silinir;
        aksi halde hâlâ görünen araçlar tabloya geri dönmezdi."""
        self._sayildi = {k for k in self._sayildi if k[1] != gun}
        self._gorulme.clear()
        self._son_yakinlik.clear()

    @property
    def kare_boyutu(self) -> tuple[int, int]:
        return self._kare_boyutu

    # ---- ana döngü ----

    def _dongu(self) -> None:
        baglanti = veritabani.baglanti_ac(self.ayarlar.veritabani)
        # Takip numaraları izleyici her kurulduğunda 1'den başlar; uygulama gün
        # içinde yeniden başlatılırsa yeni araçlar eski numaralara çakışıp
        # SESSİZCE sayılmıyordu. Ofset o günkü en büyük numaradan devam eder.
        self._id_ofsetini_tazele(baglanti)
        try:
            self._tespitci = Tespitci(self.ayarlar.model_dosyasi, self.ayarlar.cihaz)
        except ModelHatasi as hata:
            # Ekrana YALNIZCA sade metin çıkar (özet sayfasındaki kırmızı kutu).
            # Tam yol ve özgün istisna metni tespit.py içinde günlüğe yazıldı.
            self.model_hatasi = hata.mesaj
            self._log.error("Tespit modeli açılamadı: %s", hata.teknik)
            self.durum = "model yok"
        except Exception as hata:  # noqa: BLE001 — iş parçacığı sessizce ölmesin
            # Dinamik eksenli model dışa aktarımı gibi durumlarda ValueError
            # gelir; yakalanmazsa analiz iş parçacığı ölür ve durum sonsuza dek
            # "başlatılıyor" kalırdı.
            #
            # Ham istisna metni EKRANA BASILMAZ: içinde dosya yolu ve kütüphane
            # adı geçer, kullanıcı hiçbirini kullanamaz. Ekranda diğer iki
            # daldakiyle AYNI cümle görünür, ayrıntı günlüğe yazılır.
            self.model_hatasi = (
                f"{gorunen_model_adi(str(self.ayarlar.model_dosyasi))} açılamadı. "
                f"{YENIDEN_BASLATMA_ONERISI}"
            )
            self._log.error(
                "Tespit modeli açılamadı (%s): %s",
                self.ayarlar.model_dosyasi,
                hata,
                exc_info=hata,
            )
            self.durum = "model yok"

        bekleme = 1.0
        try:
            while not self._dur.is_set():
                yakalayici = self._kaynagi_ac()
                if yakalayici is None:
                    self.durum = "kaynağa bağlanılamadı"
                    if self._dur.wait(bekleme):
                        break
                    bekleme = min(bekleme * 2, 30.0)
                    continue
                bekleme = 1.0
                self.kaynak_hatasi = None
                self.durum = "çalışıyor"
                try:
                    self._kareleri_isle(yakalayici, baglanti)
                finally:
                    yakalayici.release()
        finally:
            baglanti.close()
            self.durum = "durdu"

    def _kaynagi_ac(self):
        kaynak = self.ayarlar.kaynak_cozumle()
        if isinstance(kaynak, int):
            # Windows'ta varsayılan arka uç (MSMF) sık takılır; DirectShow daha sağlam
            arka_uc = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
            yakalayici = cv2.VideoCapture(kaynak, arka_uc)
        else:
            # Zaman aşımı olmadan kopan RTSP bağlantısı read() içinde dakikalarca
            # bloklanabilir; o zaman durdur() da bekler. 10 sn üst sınır koyuyoruz.
            yakalayici = cv2.VideoCapture(
                kaynak,
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000],
            )
        if not yakalayici.isOpened():
            yakalayici.release()
            self.kaynak_hatasi = (
                f"Görüntü kaynağı açılamadı: {self.ayarlar.kaynak}\n"
                "Kamera numarasını, RTSP adresini veya video dosyasının yolunu "
                "Özet sayfasındaki 'Görüntü kaynağı' bölümünden kontrol edin."
            )
            return None
        return yakalayici

    def _kareleri_isle(self, yakalayici, baglanti) -> None:
        aralik = 1.0 / self.ayarlar.kare_fps
        kaynak = self.ayarlar.kaynak_cozumle()
        # Kamera (int), rtsp ve http akıştır; yalnız video DOSYASI bitince başa sarılır
        dosya_mi = isinstance(kaynak, str) and not kaynak.lower().startswith(("rtsp", "http"))
        while not self._dur.is_set():
            baslangic = time.monotonic()
            tamam, kare = yakalayici.read()
            if not tamam:
                if dosya_mi:
                    yakalayici.set(cv2.CAP_PROP_POS_FRAMES, 0)  # video biterse başa sar
                    if self._dur.wait(0.1):  # bozuk dosyada boş dönüp CPU yakmasın
                        return
                    continue
                return  # kamera/RTSP koptu → yeniden bağlan
            self._kare_boyutu = (kare.shape[1], kare.shape[0])
            try:
                self._kareyi_degerlendir(kare, baglanti)
            except Exception as hata:  # noqa: BLE001 — demo döngüsü ölmemeli
                # `durum` bir sonraki başarılı karede silinir; son_hata KALIR,
                # ekranda görünür ve günlüğe yazılır. Eskiden hata hiçbir yere
                # düşmüyordu: kullanıcının kopyalayacak bir satırı yoktu.
                self.durum = f"hata: {hata}"
                self.son_hata = f"{zaman.saat(zaman.simdi_utc())} — {hata}"
                self._log.error(f"Kare işlenemedi: {hata}", exc_info=hata)
            gecen = time.monotonic() - baslangic
            if self._dur.wait(max(0.0, aralik - gecen)):
                return

    def _kareyi_degerlendir(self, kare: np.ndarray, baglanti) -> None:
        if self._tespitci is None:
            self._onizleme_yaz(kare, [], [])
            return

        # Hassasiyet ekrandan değiştirilebilir; koda gömülü eşik bırakılmaz.
        # Değer değişince takipçi de yeniden kurulur (aktivasyon eşiği ona bağlı)
        # ve açık gözlem sayaçları temizlenir: yeni numaralar eski sayaçların
        # üstüne binmesin.
        self._hassasiyeti_uygula(veritabani.ayarlari_oku(baglanti), baglanti)

        kutular, guvenler, tipler = self._tespitci.bul(kare)
        izler = self._takip_et(kutular, guvenler, tipler)

        araclar = [i for i in izler if i["tip"] == "arac"]
        insanlar = [i for i in izler if i["tip"] == "insan"]
        # Ekrandaki "şu an görünen" sayısı ham kare sayısı DEĞİL, son birkaç
        # karenin ORTANCASI: tek karelik bir tespit kaçağı sayacı titretiyor ve
        # kullanıcı 2 saniyede bir rastgele bir değer görüyordu.
        self.canli_arac = self._yumusat("arac", len(araclar))
        self.canli_insan = self._yumusat("insan", len(insanlar))

        ayarlar = veritabani.ayarlari_oku(baglanti)
        self._gecisleri_kaydet(baglanti, izler, kare)
        yakinlar = self._yakinliklari_kaydet(baglanti, araclar, ayarlar, kare)
        self._onizleme_yaz(kare, izler, yakinlar)

    def _takip_et(self, kutular, guvenler, tipler) -> list[dict]:
        if len(kutular) == 0:
            algilar = sv.Detections.empty()
        else:
            algilar = sv.Detections(
                xyxy=kutular.astype(float),
                confidence=guvenler.astype(float),
                class_id=np.array([0 if t == "insan" else 1 for t in tipler]),
            )
        sonuc = self._izleyici.update_with_detections(algilar)
        izler = []
        for i in range(len(sonuc)):
            takip_id = sonuc.tracker_id[i] if sonuc.tracker_id is not None else None
            if takip_id is None:
                continue
            izler.append(
                {
                    "tip": "insan" if int(sonuc.class_id[i]) == 0 else "arac",
                    "takip_id": int(takip_id),
                    "kutu": tuple(float(v) for v in sonuc.xyxy[i]),
                }
            )
        return izler

    # ---- sayım ----

    def _id_ofsetini_tazele(self, baglanti) -> None:
        """O gün kullanılmış en büyük takip numarasını her tip için okur."""
        gun = zaman.bugun()
        self._id_ofseti = {}
        for satir in baglanti.execute(
            "SELECT tip, COALESCE(MAX(takip_id), 0) AS son FROM gecisler "
            "WHERE gun = ? GROUP BY tip",
            (gun,),
        ):
            self._id_ofseti[satir["tip"]] = int(satir["son"])

    def _kayit_id(self, tip: str, takip_id: int) -> int:
        return self._id_ofseti.get(tip, 0) + takip_id

    def _gecisleri_kaydet(self, baglanti, izler: list[dict], kare: np.ndarray) -> None:
        gun = zaman.bugun()
        simdi = zaman.simdi_utc()
        for iz in izler:
            anahtar = (iz["tip"], iz["takip_id"])
            self._gorulme[anahtar] = min(self._gorulme.get(anahtar, 0) + 1, _SAYMA_ESIGI + 3)

            # Renk oyu HER karede toplanır: tek kareye bakan karar, aynı beyaz
            # aracı güneşte "beyaz", gölgede "gri" gösteriyordu (docs: kare
            # başına karar yasak).
            if iz["tip"] == "arac" and len(self._renk_oylari.get(anahtar, ())) < _RENK_OYU_SAYISI:
                self._renk_oylari.setdefault(anahtar, []).append(self._renk_bul(kare, iz["kutu"]))

            if self._gorulme[anahtar] < _SAYMA_ESIGI:
                continue  # tek karelik yanlış tespit sayaca girmesin

            kayit_id = self._kayit_id(iz["tip"], iz["takip_id"])
            kimlik = (iz["tip"], gun, iz["takip_id"])
            if kimlik in self._sayildi:
                guncelle = ["son_gorulme = ?"]
                degerler: list = [simdi]
                # Renk oyları tamamlandığında kararı bir kez düzelt
                oylar = self._renk_oylari.get(anahtar)
                if iz["tip"] == "arac" and oylar and len(oylar) >= _RENK_OYU_SAYISI:
                    guncelle.append("renk = ?")
                    degerler.append(renk_modulu.baskin_renk(oylar))
                    self._renk_oylari[anahtar] = []  # bir daha yazma
                degerler += [iz["tip"], gun, kayit_id]
                baglanti.execute(
                    f"UPDATE gecisler SET {', '.join(guncelle)} "
                    "WHERE tip = ? AND gun = ? AND takip_id = ?",
                    degerler,
                )
                continue

            renk = None
            foto = None
            if iz["tip"] == "arac":
                renk = renk_modulu.baskin_renk(self._renk_oylari.get(anahtar, []))
                foto = self._kirpik_kaydet(kare, iz["kutu"])
            # INSERT OR IGNORE DEĞİL: ofset sayesinde çakışma imkânsız, çakışma
            # olursa da sessizce yutulmamalı.
            baglanti.execute(
                "INSERT INTO gecisler "
                "(tip, takip_id, gun, ilk_gorulme, son_gorulme, renk, foto) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (iz["tip"], kayit_id, gun, simdi, simdi, renk, foto),
            )
            self._sayildi.add(kimlik)
        baglanti.commit()

        # Ekranda olmayan takiplerin sayaçları AZALIR ama sıfırlanmaz:
        # tek karelik tespit kaçağı olağandır ve eskiden sayacı sıfırlıyordu —
        # titreyen bir araç ASLA sayılmıyordu (ölçüldü: 8 karede 6 tespit = 0 kayıt).
        mevcut = {(i["tip"], i["takip_id"]) for i in izler}
        for a in list(self._gorulme):
            if a in mevcut:
                continue
            self._gorulme[a] -= 1
            if self._gorulme[a] <= 0:
                del self._gorulme[a]
                self._renk_oylari.pop(a, None)

    def _izleyici_kur(self, hassasiyet: float) -> sv.ByteTrack:
        """ByteTrack'i tespit hassasiyetine göre kurar.

        supervision içeride det_thresh = eşik + 0,1 kullanır ve yeni izi ANCAK
        bunun üstünde başlatır. Sabit 0,20 eşik → 0,30 gerçek taban demekti:
        tespit.py'nin insan için tanıdığı 0,28'lik ayrıcalık ÖLÜ KALIYORDU
        (0,29 güvenli bir insan tespit ediliyor ama hiç takip edilmiyordu).
        """
        return sv.ByteTrack(
            track_activation_threshold=max(0.02, hassasiyet - 0.12),
            lost_track_buffer=int(_IZ_HAFIZASI_SN * 30),
            # Varsayılan eşleştirme toleransı (0,8) düşük kare hızında hızlı
            # hareket eden aracın izini koparıyordu.
            minimum_matching_threshold=0.92,
            frame_rate=max(int(self.ayarlar.kare_fps), 1),
        )

    def _hassasiyeti_uygula(self, ayarlar: dict[str, str], baglanti) -> None:
        """Ekrandan ayarlanan tespit hassasiyetini uygular."""
        ham = (ayarlar.get("tespit_hassasiyeti") or "0.35").replace(",", ".")
        try:
            deger = float(ham)
        except ValueError:
            return  # bozuk değer: mevcut ayar korunur
        deger = min(max(deger, _HASSASIYET_EN_AZ), _HASSASIYET_EN_COK)
        if self._tespitci is not None:
            self._tespitci.guven = deger
        if abs(deger - self._hassasiyet) < 1e-9:
            return
        self._hassasiyet = deger
        self._izleyici = self._izleyici_kur(deger)
        # Takipçi numaraları 1'den başlayacak: açık sayaçlar ve ofset tazelenir,
        # yoksa yeni numaralar eski araçların sayaçlarının üstüne binerdi.
        self._gorulme.clear()
        self._renk_oylari.clear()
        self._yakinlik_sayaci.clear()
        self._id_ofsetini_tazele(baglanti)

    def _yumusat(self, ad: str, deger: int) -> int:
        gecmis = self._canli_gecmis.setdefault(ad, deque(maxlen=_CANLI_PENCERE))
        gecmis.append(deger)
        sirali = sorted(gecmis)
        return sirali[len(sirali) // 2]

    def _renk_bul(self, kare: np.ndarray, kutu) -> str:
        x1, y1, x2, y2 = renk_modulu.govde_bolgesi(kutu)
        x1, y1 = max(x1, 0), max(y1, 0)
        x2, y2 = min(x2, kare.shape[1]), min(y2, kare.shape[0])
        if x2 - x1 < 3 or y2 - y1 < 3:
            return renk_modulu.BELIRSIZ
        return renk_modulu.renk_bul(kare[y1:y2, x1:x2])

    def _kirpik_kaydet(self, kare: np.ndarray, kutu) -> str | None:
        x1, y1, x2, y2 = (int(v) for v in kutu)
        x1, y1 = max(x1, 0), max(y1, 0)
        x2, y2 = min(x2, kare.shape[1]), min(y2, kare.shape[0])
        if x2 - x1 < 8 or y2 - y1 < 8:
            return None
        goreli = f"arac-{zaman.bugun()}-{uuid.uuid4().hex[:8]}.jpg"
        hedef = self.ayarlar.goruntu_klasoru / goreli
        # cv2.imwrite KULLANILMAZ: yolu işletim sisteminin kod sayfasıyla kodlar
        # ve Türkçe klasör adında (C:\Users\Gökhan\...) hata FIRLATMADAN
        # başarısız olur — veritabanında var görünen, diskte olmayan fotoğraflar.
        try:
            tamam, tampon = cv2.imencode(".jpg", kare[y1:y2, x1:x2])
            if not tamam:
                return None
            hedef.write_bytes(tampon.tobytes())
        except (OSError, cv2.error) as hata:
            self._log.error(f"Kanıt fotoğrafı yazılamadı ({goreli}): {hata}")
            return None
        return goreli

    # ---- mesafe ----

    def _yakinliklari_kaydet(
        self, baglanti, araclar: list[dict], ayarlar: dict[str, str], kare
    ) -> list[tuple[int, int, float]]:
        try:
            esik = float(ayarlar.get("mesafe_esigi_m", "1.5") or 1.5)
            bekleme = float(ayarlar.get("yakinlik_bekleme_s", "60") or 60)
        except ValueError:
            return []

        # Seçili kalibrasyona göre hesaplayıcı: basit (çizgi) ya da hassas
        # (4 nokta homografi). Hiçbiri ayarlı değilse .hazir False olur ve
        # yakin_ciftler boş döner — mesafe takibi sessizce kapalı kalır.
        genislik, yukseklik = self._kare_boyutu
        hesap = hesaplayici_kur(ayarlar, genislik, yukseklik)
        çiftler = yakin_ciftler(
            [Arac(takip_id=a["takip_id"], kutu=a["kutu"]) for a in araclar], hesap, esik
        )
        if not çiftler:
            return []

        simdi_mono = time.monotonic()
        # ARDIŞIK ONAY: tek karelik bir kutu hatası (birleşmiş ya da kesilmiş
        # tespit) kalıcı bir olay ve fotoğraf yazmamalı. Aynı çift ardışık
        # _YAKINLIK_ONAY karede eşiğin altında kalmalı (docs: kare başına karar
        # yasak — kararlar zaman içinde doğrulanır).
        yakin_ciftler_kumesi = {(a, b) for a, b, _ in çiftler}
        for cift in list(self._yakinlik_sayaci):
            if cift not in yakin_ciftler_kumesi:
                del self._yakinlik_sayaci[cift]

        for a, b, uzaklik in çiftler:
            self._yakinlik_sayaci[(a, b)] = self._yakinlik_sayaci.get((a, b), 0) + 1
            if self._yakinlik_sayaci[(a, b)] < _YAKINLIK_ONAY:
                continue
            if simdi_mono - self._son_yakinlik.get((a, b), -1e9) < bekleme:
                continue  # aynı çift için tekrar tekrar kayıt açma
            self._son_yakinlik[(a, b)] = simdi_mono
            foto = None
            tamam, jpeg = cv2.imencode(".jpg", kare, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if tamam:
                goreli = f"yakinlik-{zaman.bugun()}-{uuid.uuid4().hex[:8]}.jpg"
                try:
                    (self.ayarlar.goruntu_klasoru / goreli).write_bytes(jpeg.tobytes())
                    foto = goreli
                except OSError:
                    foto = None
            baglanti.execute(
                "INSERT INTO yakinlik_olaylari "
                "(zaman, gun, takip_a, takip_b, mesafe_m, esik_m, foto) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (zaman.simdi_utc(), zaman.bugun(), a, b, uzaklik, esik, foto),
            )
            self._olay_uret(uzaklik, esik, foto)
        baglanti.commit()
        return çiftler

    def _olay_uret(self, uzaklik: float, esik: float, foto: str | None) -> None:
        """Yakınlık uyarısını olay akışına koyar — ekrandaki uyarının kaynağı.

        Ekran eskiden GÜNLÜK SAYAÇ FARKINA bakıyordu: aynı iki saniyelik
        pencerede iki olay tek uyarıya iniyor, geçmiş bir gün görüntülenirken
        hiç uyarı gelmiyor, "Sıfırla" basılınca uyarılar kayboluyordu.
        """
        self._olay_sayaci += 1
        self._olaylar.append(
            {
                "id": self._olay_sayaci,
                "mesafe_m": round(uzaklik, 2),
                "esik_m": round(esik, 2),
                "zaman": zaman.saat(zaman.simdi_utc()),
                "foto": foto,
            }
        )
        self._log.info(f"Yakınlık uyarısı: {uzaklik:.2f} m (eşik {esik:.2f} m)")

    def olaylar(self, sonra: int = 0) -> list[dict]:
        return [o for o in list(self._olaylar) if o["id"] > sonra]

    @property
    def son_olay_id(self) -> int:
        return self._olay_sayaci

    # ---- önizleme ----

    def _onizleme_yaz(self, kare, izler, yakinlar) -> None:
        gorsel = kare.copy()
        yakin_idler = {t for cift in yakinlar for t in cift[:2]}
        for iz in izler:
            x1, y1, x2, y2 = (int(v) for v in iz["kutu"])
            kirmizi = iz["takip_id"] in yakin_idler and iz["tip"] == "arac"
            renk = (0, 0, 220) if kirmizi else _RENKLER[iz["tip"]]
            cv2.rectangle(gorsel, (x1, y1), (x2, y2), renk, 2)
            cv2.putText(
                gorsel,
                f"{iz['tip']} #{iz['takip_id']}",
                (x1, max(y1 - 6, 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                renk,
                1,
                cv2.LINE_AA,
            )
        tamam, jpeg = cv2.imencode(".jpg", gorsel, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if tamam:
            with self._kilit:
                self._son_jpeg = jpeg.tobytes()


def ornek_video_uret(hedef: Path) -> None:
    """Kaynak yoksa demo için basit bir otopark videosu üretir (renkli araçlar).

    Gerçek kamera bağlanana kadar arayüzün boş kalmaması içindir; tespit
    modeli bu çizimleri araç saymaz — gerçek görüntüyle deneyin.
    """
    hedef.parent.mkdir(parents=True, exist_ok=True)
    yazici = cv2.VideoWriter(str(hedef), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 360))
    for _ in range(100):
        kare = np.full((360, 640, 3), 60, dtype=np.uint8)
        cv2.putText(
            kare,
            "Ornek video - gerçek kaynak icin .env KAYNAK satirini duzenleyin",
            (20, 180),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )
        yazici.write(kare)
    yazici.release()
