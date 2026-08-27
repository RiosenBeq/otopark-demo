"""Analiz iş parçacığı: kaynak → tespit → takip → sayım/renk/mesafe → kayıt.

Tek arka plan iş parçacığı; web arayüzüyle aynı süreçte çalışır.
Sayım ilkesi: her BENZERSİZ takip (track) günde bir kez sayılır. Aynı araç
100 karede görünse de "1 araç"tır; kamera açılıp kapansa bile aynı gün
içinde yeni takip ID'si aldığı için yeniden sayılır — bu bilinen sınırdır
ve ekranda dürüstçe yazılıdır.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import supervision as sv  # noqa: E402

from app import renk as renk_modulu  # noqa: E402
from app import veritabani, zaman  # noqa: E402
from app.ayarlar import Ayarlar  # noqa: E402
from app.mesafe import Arac, hesaplayici_kur, yakin_ciftler  # noqa: E402
from app.tespit import ModelHatasi, Tespitci  # noqa: E402

# Bir takip bu kadar kez görülmeden sayılmaz: tek karelik yanlış tespitler
# günlük sayacı şişirmesin.
_SAYMA_ESIGI = 3

# Kayıp bir izin hatırlanma süresi (saniye). Araç kısa süre örtülüp geri
# gelince AYNI takip numarasını alsın ve ikinci kez sayılmasın diye.
_IZ_HAFIZASI_SN = 15.0

_RENKLER = {"arac": (60, 140, 255), "insan": (80, 200, 80)}


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
        self._izleyici = sv.ByteTrack(
            track_activation_threshold=0.20,
            lost_track_buffer=int(_IZ_HAFIZASI_SN * 30),
            frame_rate=max(int(ayarlar.kare_fps), 1),
        )
        self._gorulme: dict[tuple[str, int], int] = {}
        self._sayildi: set[tuple[str, str, int]] = set()
        self._son_yakinlik: dict[tuple[int, int], float] = {}

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
        try:
            self._tespitci = Tespitci(self.ayarlar.model_dosyasi, self.ayarlar.cihaz)
        except ModelHatasi as hata:
            self.model_hatasi = str(hata)
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
                self.durum = f"hata: {hata}"
            gecen = time.monotonic() - baslangic
            if self._dur.wait(max(0.0, aralik - gecen)):
                return

    def _kareyi_degerlendir(self, kare: np.ndarray, baglanti) -> None:
        if self._tespitci is None:
            self._onizleme_yaz(kare, [], [])
            return

        kutular, guvenler, tipler = self._tespitci.bul(kare)
        izler = self._takip_et(kutular, guvenler, tipler)

        araclar = [i for i in izler if i["tip"] == "arac"]
        insanlar = [i for i in izler if i["tip"] == "insan"]
        self.canli_arac, self.canli_insan = len(araclar), len(insanlar)

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

    def _gecisleri_kaydet(self, baglanti, izler: list[dict], kare: np.ndarray) -> None:
        gun = zaman.bugun()
        simdi = zaman.simdi_utc()
        for iz in izler:
            anahtar = (iz["tip"], iz["takip_id"])
            self._gorulme[anahtar] = self._gorulme.get(anahtar, 0) + 1
            if self._gorulme[anahtar] < _SAYMA_ESIGI:
                continue  # tek karelik yanlış tespit sayaca girmesin

            kimlik = (iz["tip"], gun, iz["takip_id"])
            if kimlik in self._sayildi:
                baglanti.execute(
                    "UPDATE gecisler SET son_gorulme = ? "
                    "WHERE tip = ? AND gun = ? AND takip_id = ?",
                    (simdi, iz["tip"], gun, iz["takip_id"]),
                )
                continue

            renk = None
            foto = None
            if iz["tip"] == "arac":
                renk = self._renk_bul(kare, iz["kutu"])
                foto = self._kirpik_kaydet(kare, iz["kutu"])
            baglanti.execute(
                "INSERT OR IGNORE INTO gecisler "
                "(tip, takip_id, gun, ilk_gorulme, son_gorulme, renk, foto) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (iz["tip"], iz["takip_id"], gun, simdi, simdi, renk, foto),
            )
            self._sayildi.add(kimlik)
        baglanti.commit()

        # Ekranda olmayan takiplerin sayaçları büyümesin
        mevcut = {(i["tip"], i["takip_id"]) for i in izler}
        self._gorulme = {a: s for a, s in self._gorulme.items() if a in mevcut}

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
        try:
            cv2.imwrite(str(hedef), kare[y1:y2, x1:x2])
        except (OSError, cv2.error):
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
        for a, b, uzaklik in çiftler:
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
        baglanti.commit()
        return çiftler

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
