"""Otopark Demo arayüzü: özet, ayarlar, kalibrasyon, geçmiş."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import veritabani, zaman
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
def ozet(istek: Request, gun: str = "", hata: str = "", baglanti=Depends(baglanti_al)):
    gun = gun or zaman.bugun()
    ayarlar = veritabani.ayarlari_oku(baglanti)
    analiz = getattr(istek.app.state, "analiz", None)

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
            "esik": ayarlar.get("mesafe_esigi_m", "1.5").replace(".", ","),
            "olcek_hazir": olcek > 0,
            "referans_metre": (ayarlar.get("referans_metre") or "").replace(".", ","),
            "durum": getattr(analiz, "durum", "başlatılmadı"),
            "canli_arac": getattr(analiz, "canli_arac", 0),
            "canli_insan": getattr(analiz, "canli_insan", 0),
            "model_hatasi": getattr(analiz, "model_hatasi", None),
            "kaynak_hatasi": getattr(analiz, "kaynak_hatasi", None),
            "kaynak": istek.app.state.ayarlar.kaynak,
            "hata": hata,
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
