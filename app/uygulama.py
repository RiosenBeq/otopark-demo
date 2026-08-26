"""FastAPI uygulama fabrikası (test edilebilir: analiz kapatılabilir)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import veritabani
from app.ayarlar import Ayarlar
from app.web import nesne_rotalari, rotalar

STATIK = Path(__file__).resolve().parent / "web" / "static"


def uygulama_olustur(ayarlar: Ayarlar, analiz_ac: bool = True) -> FastAPI:
    @asynccontextmanager
    async def yasam(uygulama: FastAPI):
        baglanti = veritabani.baglanti_ac(ayarlar.veritabani)
        try:
            veritabani.semayi_uygula(baglanti)
        finally:
            baglanti.close()

        analiz = None
        if analiz_ac:
            from app.analiz import Analiz, ornek_video_uret

            kaynak_yolu = ayarlar.kok / ayarlar.kaynak
            if kaynak_yolu.suffix == ".mp4" and not kaynak_yolu.exists():
                ornek_video_uret(kaynak_yolu)  # ilk açılışta ekran boş kalmasın
            analiz = Analiz(ayarlar)
            uygulama.state.analiz = analiz
            analiz.baslat()

        yield

        if analiz is not None:
            analiz.durdur()

    uygulama = FastAPI(title="Otopark Demo", lifespan=yasam)
    uygulama.state.ayarlar = ayarlar

    @uygulama.exception_handler(Exception)
    async def hata_yakala(istek, hata: Exception):
        return JSONResponse(
            status_code=500,
            content={"hata": f"Beklenmeyen hata: {hata}"},
        )

    uygulama.include_router(rotalar.router)
    uygulama.include_router(nesne_rotalari.router)
    uygulama.mount("/static", StaticFiles(directory=str(STATIK)), name="static")
    return uygulama
