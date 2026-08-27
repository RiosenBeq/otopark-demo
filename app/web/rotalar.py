"""Otopark Demo arayüzü: özet, ayarlar, kaynak, kalibrasyon, geçmiş."""

from __future__ import annotations

import base64
import csv
import io
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import cv2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import ayarlar as ayarlar_modulu
from app import veritabani, zaman
from app.ayarlar import AyarHatasi
from app.mesafe import OlcekHatasi, esik_dogrula, olcek_hesapla

router = APIRouter()
SABLONLAR = Path(__file__).resolve().parent / "templates"
sablonlar = Jinja2Templates(directory=str(SABLONLAR))

RENK_KODLARI = {
    "beyaz": "#f5f5f4",
    "siyah": "#292524",
    "gri": "#a8a29e",
    "kırmızı": "#dc2626",
    "mavi": "#2563eb",
    "yeşil": "#16a34a",
    "sarı": "#eab308",
    "turuncu": "#ea580c",
    "mor": "#7c3aed",
    "turkuaz": "#0d9488",
    "belirsiz": "#d6d3d1",
}


def baglanti_al(istek: Request):
    baglanti = veritabani.baglanti_ac(istek.app.state.ayarlar.veritabani)
    try:
        yield baglanti
    finally:
        baglanti.close()


def _gun_ozeti(baglanti, gun: str) -> dict:
    satir = baglanti.execute(
        "SELECT "
        " SUM(CASE WHEN tip = 'arac' THEN 1 ELSE 0 END) AS arac, "
        " SUM(CASE WHEN tip = 'insan' THEN 1 ELSE 0 END) AS insan "
        "FROM gecisler WHERE gun = ?",
        (gun,),
    ).fetchone()
    yakinlik = baglanti.execute(
        "SELECT COUNT(*) AS n FROM yakinlik_olaylari WHERE gun = ?", (gun,)
    ).fetchone()["n"]
    return {
        "arac": satir["arac"] or 0,
        "insan": satir["insan"] or 0,
        "yakinlik": yakinlik,
    }


def _renk_dagilimi(baglanti, gun: str) -> list[dict]:
    satirlar = baglanti.execute(
        "SELECT COALESCE(renk, 'belirsiz') AS renk, COUNT(*) AS adet "
        "FROM gecisler WHERE tip = 'arac' AND gun = ? GROUP BY renk ORDER BY adet DESC",
        (gun,),
    ).fetchall()
    toplam = sum(s["adet"] for s in satirlar) or 1
    return [
        {
            "ad": s["renk"],
            "adet": s["adet"],
            "yuzde": round(s["adet"] * 100 / toplam),
            "kod": RENK_KODLARI.get(s["renk"], "#d6d3d1"),
        }
        for s in satirlar
    ]


@router.get("/", response_class=HTMLResponse)
def ozet(
    istek: Request,
    gun: str = "",
    hata: str = "",
    mesaj: str = "",
    baglanti=Depends(baglanti_al),
):
    gun = gun or zaman.bugun()
    ayarlar = veritabani.ayarlari_oku(baglanti)
    analiz = getattr(istek.app.state, "analiz", None)
    nesne_sayisi = baglanti.execute("SELECT COUNT(*) AS n FROM nesneler").fetchone()["n"]

    araclar = [
        {
            "saat": zaman.saat(s["ilk_gorulme"]),
            "renk": s["renk"] or "belirsiz",
            "kod": RENK_KODLARI.get(s["renk"] or "belirsiz", "#d6d3d1"),
            "foto": s["foto"],
            "takip_id": s["takip_id"],
        }
        for s in baglanti.execute(
            "SELECT * FROM gecisler WHERE tip = 'arac' AND gun = ? "
            "ORDER BY ilk_gorulme DESC LIMIT 60",
            (gun,),
        )
    ]
    yakinliklar = [
        {
            "saat": zaman.saat(s["zaman"]),
            "mesafe": f"{s['mesafe_m']:.2f}".replace(".", ","),
            "esik": f"{s['esik_m']:g}".replace(".", ","),
            "foto": s["foto"],
        }
        for s in baglanti.execute(
            "SELECT * FROM yakinlik_olaylari WHERE gun = ? ORDER BY zaman DESC LIMIT 30",
            (gun,),
        )
    ]
    gunler = [
        {"gun": s["gun"], "etiket": zaman.gun_ekranda(s["gun"])}
        for s in baglanti.execute("SELECT DISTINCT gun FROM gecisler ORDER BY gun DESC LIMIT 30")
    ]

    # İstatistik: saat dağılımı Python'da hesaplanır — DB'de UTC saklanır,
    # SQL substr ile alınan saat Türkiye saatine göre yanlış olurdu
    saat_sayim = Counter(
        zaman.saat(s["ilk_gorulme"])[:2]
        for s in baglanti.execute(
            "SELECT ilk_gorulme FROM gecisler WHERE tip = 'arac' AND gun = ?", (gun,)
        )
    )
    saatlik = [{"saat": s, "adet": saat_sayim[s]} for s in sorted(saat_sayim)]
    son7 = [
        {"etiket": zaman.gun_ekranda(s["gun"])[:5], "adet": s["adet"], "bugun": s["gun"] == gun}
        for s in baglanti.execute(
            "SELECT gun, COUNT(*) AS adet FROM gecisler WHERE tip = 'arac' "
            "GROUP BY gun ORDER BY gun DESC LIMIT 7"
        )
    ][::-1]

    olcek = float(ayarlar.get("olcek_m_px", "0") or 0)
    return sablonlar.TemplateResponse(
        istek,
        "ozet.html",
        {
            "gun": gun,
            "gun_etiketi": zaman.gun_ekranda(gun),
            "bugun_mu": gun == zaman.bugun(),
            "ozet": _gun_ozeti(baglanti, gun),
            "renkler": _renk_dagilimi(baglanti, gun),
            "araclar": araclar,
            "yakinliklar": yakinliklar,
            "gunler": gunler,
            "saatlik": saatlik,
            "saatlik_en_yuksek": max((s["adet"] for s in saatlik), default=1) or 1,
            "en_yogun_saat": (
                max(saatlik, key=lambda s: s["adet"])["saat"] + ":00" if saatlik else None
            ),
            "son7": son7,
            "son7_en_yuksek": max((g["adet"] for g in son7), default=1) or 1,
            "esik": ayarlar.get("mesafe_esigi_m", "1.5").replace(".", ","),
            "esik_sayi": ayarlar.get("mesafe_esigi_m", "1.5"),
            "metre_piksel": round(1 / olcek) if olcek > 0 else 0,
            "olcek_hazir": olcek > 0,
            "referans_metre": (ayarlar.get("referans_metre") or "").replace(".", ","),
            "durum": getattr(analiz, "durum", "başlatılmadı"),
            "canli_arac": getattr(analiz, "canli_arac", 0),
            "canli_insan": getattr(analiz, "canli_insan", 0),
            "model_hatasi": getattr(analiz, "model_hatasi", None),
            "kaynak_hatasi": getattr(analiz, "kaynak_hatasi", None),
            "kaynak": kaynak_gorunen(istek.app.state.ayarlar.kaynak),
            "kaynak_ham": istek.app.state.ayarlar.kaynak,
            "kaynak_tur": kaynak_turu(istek.app.state.ayarlar.kaynak),
            "nesne_sayisi": nesne_sayisi,
            "hata": hata,
            "mesaj": mesaj,
        },
    )


@router.post("/ayarlar/mesafe")
def mesafe_esigi_kaydet(esik_m: str = Form(...), baglanti=Depends(baglanti_al)):
    """Güvenli park mesafesini KULLANICI belirler (docs'ta sabit değil)."""
    try:
        deger = esik_dogrula(esik_m)
    except OlcekHatasi as hata:
        return RedirectResponse(f"/?hata={hata}", status_code=303)
    veritabani.ayar_yaz(baglanti, "mesafe_esigi_m", f"{deger:g}")
    return RedirectResponse("/", status_code=303)


@router.post("/ayarlar/kalibrasyon")
def kalibrasyon_kaydet(
    istek: Request,
    cizgi: str = Form(...),  # JSON: [[x1,y1],[x2,y2]] normalize 0-1
    metre: str = Form(...),
    baglanti=Depends(baglanti_al),
):
    analiz = getattr(istek.app.state, "analiz", None)
    genislik, yukseklik = getattr(analiz, "kare_boyutu", (0, 0))
    if genislik == 0:
        return RedirectResponse(
            "/?hata=Görüntü henüz gelmedi; kamera bağlanınca tekrar deneyin.",
            status_code=303,
        )
    try:
        noktalar = json.loads(cizgi)
        uclar = (
            (float(noktalar[0][0]), float(noktalar[0][1])),
            (float(noktalar[1][0]), float(noktalar[1][1])),
        )
        gercek = float(str(metre).replace(",", "."))
        olcek = olcek_hesapla(uclar, gercek, genislik, yukseklik)
    except (json.JSONDecodeError, TypeError, ValueError, IndexError):
        return RedirectResponse(
            "/?hata=Referans çizgisi okunamadı. Görüntüde iki noktaya tıklayıp "
            "uzunluğu metre olarak yazın.",
            status_code=303,
        )
    except OlcekHatasi as hata:
        return RedirectResponse(f"/?hata={hata}", status_code=303)

    veritabani.ayar_yaz(baglanti, "olcek_m_px", repr(olcek))
    veritabani.ayar_yaz(baglanti, "referans_cizgi", cizgi)
    veritabani.ayar_yaz(baglanti, "referans_metre", f"{gercek:g}")
    return RedirectResponse("/", status_code=303)


@router.get("/onizleme.jpg")
def onizleme(istek: Request):
    analiz = getattr(istek.app.state, "analiz", None)
    jpeg = analiz.onizleme() if analiz else None
    if jpeg is None:
        return Response(status_code=204)
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/canli")
def canli_sayilar(istek: Request, gun: str = "", baglanti=Depends(baglanti_al)):
    """Sayfa 2 sn'de bir bu uçtan güncellenir (tam yenileme yok)."""
    gun = gun or zaman.bugun()
    analiz = getattr(istek.app.state, "analiz", None)
    ozet = _gun_ozeti(baglanti, gun)
    return {
        **ozet,
        "canli_arac": getattr(analiz, "canli_arac", 0),
        "canli_insan": getattr(analiz, "canli_insan", 0),
        "durum": getattr(analiz, "durum", "başlatılmadı"),
    }


@router.get("/gorsel/{ad}")
def gorsel(istek: Request, ad: str):
    kok = istek.app.state.ayarlar.goruntu_klasoru.resolve()
    dosya = (kok / ad).resolve()
    if not dosya.is_relative_to(kok) or not dosya.is_file():
        return Response(status_code=404)
    return Response(content=dosya.read_bytes(), media_type="image/jpeg")


@router.get("/rapor.csv")
def rapor(gun: str = "", baglanti=Depends(baglanti_al)):
    gun = gun or zaman.bugun()
    tampon = io.StringIO()
    yazici = csv.writer(tampon, delimiter=";")
    yazici.writerow(["Gün", "Tip", "Saat", "Renk", "Takip No"])
    for s in baglanti.execute("SELECT * FROM gecisler WHERE gun = ? ORDER BY ilk_gorulme", (gun,)):
        yazici.writerow(
            [
                zaman.gun_ekranda(s["gun"]),
                "Araç" if s["tip"] == "arac" else "Kişi",
                zaman.saat(s["ilk_gorulme"]),
                s["renk"] or "",
                s["takip_id"],
            ]
        )
    return Response(
        content="﻿" + tampon.getvalue(),  # Excel'de Türkçe karakterler için
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=otopark-{gun}.csv"},
    )


@router.post("/sifirla")
def gunu_sifirla(istek: Request, gun: str = Form(""), baglanti=Depends(baglanti_al)):
    """Demo sırasında sayaçları temizlemek için (yalnız seçili gün)."""
    gun = gun or zaman.bugun()
    baglanti.execute("DELETE FROM gecisler WHERE gun = ?", (gun,))
    baglanti.execute("DELETE FROM yakinlik_olaylari WHERE gun = ?", (gun,))
    baglanti.commit()
    # Analizin "bunu zaten saydım" hafızası da temizlenmeli; yoksa ekrandaki
    # araçlar tabloya geri dönmez ve sayfa boş görünür.
    analiz = getattr(istek.app.state, "analiz", None)
    if analiz is not None:
        analiz.sayaclari_sifirla(gun)
    return RedirectResponse("/", status_code=303)


# ---- görüntü kaynağı (kamera / IP kamera / video dosyası) ----


class KaynakHatasi(Exception):
    """Kullanıcıya gösterilecek anlaşılır kaynak hatası."""


def kaynak_turu(kaynak: str) -> str:
    """Mevcut KAYNAK değerinden arayüzdeki seçimi çıkarır."""
    ham = (kaynak or "").strip()
    if ham.isdigit():
        return "kamera"
    if ham.lower().startswith(("rtsp://", "http://", "https://")):
        return "rtsp"
    return "dosya"


def kaynak_gorunen(kaynak: str) -> str:
    """Ekranda gösterilecek kaynak: rtsp şifresi maskelenir."""
    ham = (kaynak or "").strip()
    if "://" in ham and "@" in ham:
        sema, kalan = ham.split("://", 1)
        kimlik, sunucu = kalan.rsplit("@", 1)
        if ":" in kimlik:
            kullanici = kimlik.split(":", 1)[0]
            return f"{sema}://{kullanici}:••••@{sunucu}"
    return ham


def _kaynak_degeri(kok: Path, tur: str, kamera_no: str, rtsp_adres: str, dosya_yolu: str) -> str:
    if tur == "kamera":
        no = (kamera_no or "").strip()
        if not (no.isascii() and no.isdigit()) or len(no) > 2:
            raise KaynakHatasi(
                "Kamera numarası 0-99 arası bir sayı olmalı (0 = bilgisayarın kamerası)."
            )
        return no
    if tur == "rtsp":
        adres = (rtsp_adres or "").strip()
        if not adres.lower().startswith(("rtsp://", "http://", "https://")):
            raise KaynakHatasi(
                "Kamera adresi rtsp:// ile başlamalı — "
                "örn. rtsp://kullanici:sifre@192.168.1.50:554/stream1"
            )
        if any(karakter.isspace() for karakter in adres):
            raise KaynakHatasi("Kamera adresinde boşluk ya da satır sonu olamaz.")
        return adres
    if tur == "dosya":
        yol = (dosya_yolu or "").strip()
        if not yol:
            raise KaynakHatasi("Video dosyasının yolunu yazın (örn. veri/kayit.mp4).")
        if "\n" in yol or "\r" in yol:
            raise KaynakHatasi("Dosya yolunda satır sonu olamaz.")
        aday = Path(yol)
        tam = (aday if aday.is_absolute() else kok / aday).resolve()
        if not tam.is_relative_to(kok.resolve()):
            raise KaynakHatasi(
                "Video dosyası proje klasörünün içinde olmalı — dosyayı veri/ "
                "klasörüne kopyalayıp yolunu veri/dosyaadi.mp4 gibi yazın."
            )
        if not tam.is_file():
            raise KaynakHatasi(f"Video dosyası bulunamadı: {yol}")
        return yol
    raise KaynakHatasi("Geçersiz kaynak türü seçildi.")


@router.post("/ayarlar/kaynak")
def kaynak_kaydet(
    istek: Request,
    tur: str = Form(...),
    kamera_no: str = Form("0"),
    rtsp_adres: str = Form(""),
    dosya_yolu: str = Form(""),
):
    """Kaynağı .env'e yazar ve analizi yeni kaynakla yeniden başlatır."""
    ayar = istek.app.state.ayarlar
    try:
        deger = _kaynak_degeri(ayar.kok, tur, kamera_no, rtsp_adres, dosya_yolu)
        ayarlar_modulu.kaynagi_kaydet(ayar.kok, deger)
    except (KaynakHatasi, AyarHatasi) as hata:
        return RedirectResponse(f"/?hata={quote(str(hata))}", status_code=303)

    yeni_ayarlar = replace(ayar, kaynak=deger)
    istek.app.state.ayarlar = yeni_ayarlar

    eski = getattr(istek.app.state, "analiz", None)
    if eski is not None and callable(getattr(eski, "durdur", None)):
        durdu = eski.durdur()
        from app.analiz import Analiz  # analiz kapalıyken (testler) hiç yüklenmesin

        yeni_analiz = Analiz(yeni_ayarlar)
        istek.app.state.analiz = yeni_analiz
        yeni_analiz.baslat()
        mesaj = "Görüntü kaynağı kaydedildi; sistem yeni kaynakla yeniden başlatıldı."
        if durdu is False:  # eski bağlantı hâlâ kapanıyor (zaman aşımlı akış)
            mesaj += (
                " Eski bağlantının kapanması birkaç saniye sürebilir; "
                "görüntü gelmezse sayfayı yenileyin."
            )
    else:
        mesaj = "Görüntü kaynağı kaydedildi."
    return RedirectResponse(f"/?mesaj={quote(mesaj)}", status_code=303)


@router.post("/ayarlar/kaynak/sina")
def kaynak_sina(
    istek: Request,
    tur: str = Form(...),
    kamera_no: str = Form("0"),
    rtsp_adres: str = Form(""),
    dosya_yolu: str = Form(""),
):
    """Kaydetmeden dener: kaynağa bağlanıp tek kare alır, küçük önizleme döndürür."""
    ayar = istek.app.state.ayarlar
    try:
        deger = _kaynak_degeri(ayar.kok, tur, kamera_no, rtsp_adres, dosya_yolu)
    except KaynakHatasi as hata:
        return {"ok": False, "mesaj": str(hata), "gorsel": None}
    return _kaynagi_dene(ayar.kok, deger)


def _kaynagi_dene(kok: Path, deger: str) -> dict:
    ham = deger.strip()
    if ham.isdigit():
        arka_uc = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        yakalayici = cv2.VideoCapture(int(ham), arka_uc)
        ipucu = (
            "Kamera açılamadı. Kamerayı kullanan başka bir program (Zoom, FaceTime) "
            "açıksa kapatın; sistem şu an aynı kamerayla çalışıyorsa bu normaldir — "
            "önce Kaydet'e basıp sonucu canlı görüntüden izleyin. macOS'ta kamera "
            "iznini de kontrol edin (Sistem Ayarları → Gizlilik ve Güvenlik → Kamera)."
        )
    else:
        aday = kok / ham
        kaynak = str(aday) if aday.exists() else ham
        yakalayici = cv2.VideoCapture(
            kaynak,
            cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000],
        )
        ipucu = (
            "Kaynağa bağlanılamadı. Adresi/yolu, kullanıcı adı ve şifreyi kontrol edin; "
            "IP kameraysa bilgisayarla aynı ağda olduğundan emin olun."
        )
    try:
        if not yakalayici.isOpened():
            return {"ok": False, "mesaj": ipucu, "gorsel": None}
        tamam, kare = yakalayici.read()
        if not tamam or kare is None:
            return {
                "ok": False,
                "mesaj": "Bağlantı açıldı ama görüntü alınamadı; birkaç saniye sonra "
                "yeniden deneyin.",
                "gorsel": None,
            }
        yukseklik, genislik = kare.shape[:2]
        kucuk = kare
        if genislik > 480:
            kucuk = cv2.resize(kare, (480, max(1, int(yukseklik * 480 / genislik))))
        tamam2, jpeg = cv2.imencode(".jpg", kucuk, [cv2.IMWRITE_JPEG_QUALITY, 70])
        gorsel = (
            "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode("ascii")
            if tamam2
            else None
        )
        return {
            "ok": True,
            "mesaj": f"Bağlantı başarılı — {genislik}×{yukseklik} boyutunda görüntü alındı.",
            "gorsel": gorsel,
        }
    finally:
        yakalayici.release()
