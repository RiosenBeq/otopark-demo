"""SQLite bağlantısı, şema ve ekrandan değiştirilen ayarlar.

Fabrika sistemiyle aynı disiplin: yabancı anahtar açık, WAL modu (analiz
yazarken sayfa okuyabilsin), kilit çakışmasında bekle.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SEMA_DOSYASI = Path(__file__).resolve().parent / "sema.sql"

# Ekrandan değiştirilen ayarların varsayılanları
VARSAYILAN_AYARLAR = {
    # Metre/piksel ölçeği: referans çizgisiyle hesaplanır (0 = henüz ayarlanmadı)
    "olcek_m_px": "0",
    # Kullanıcının belirlediği güvenli park mesafesi (metre)
    "mesafe_esigi_m": "1.5",
    # Aynı araç çifti için tekrar uyarı bastırma (saniye)
    "yakinlik_bekleme_s": "60",
    # Referans çizgisinin görüntüdeki normalize uçları ve gerçek uzunluğu
    "referans_cizgi": "",
    "referans_metre": "",
}


class VeritabaniHatasi(Exception):
    pass


def baglanti_ac(yol: Path | str) -> sqlite3.Connection:
    try:
        # check_same_thread=False: analiz iş parçacığı ile web aynı süreçte;
        # her bağlantı tek yerde ve sıralı kullanılır.
        baglanti = sqlite3.connect(str(yol), check_same_thread=False)
        baglanti.row_factory = sqlite3.Row
        baglanti.execute("PRAGMA foreign_keys = ON")
        baglanti.execute("PRAGMA journal_mode = WAL")
        baglanti.execute("PRAGMA busy_timeout = 5000")
    except sqlite3.Error as hata:
        raise VeritabaniHatasi(
            f"Veritabanı açılamadı: {yol} — {hata}. Dosya bozuksa silip "
            "sistemi yeniden başlatabilirsiniz (demo verisi kaybolur)."
        ) from hata
    return baglanti


def semayi_uygula(baglanti: sqlite3.Connection) -> None:
    try:
        baglanti.executescript("BEGIN;\n" + SEMA_DOSYASI.read_text(encoding="utf-8") + "\nCOMMIT;")
    except sqlite3.Error as hata:
        baglanti.rollback()
        raise VeritabaniHatasi(f"Şema uygulanamadı: {hata}") from hata
    for anahtar, deger in VARSAYILAN_AYARLAR.items():
        baglanti.execute(
            "INSERT OR IGNORE INTO ayar (anahtar, deger) VALUES (?, ?)", (anahtar, deger)
        )
    baglanti.commit()


def ayarlari_oku(baglanti: sqlite3.Connection) -> dict[str, str]:
    return {s["anahtar"]: s["deger"] for s in baglanti.execute("SELECT * FROM ayar")}


def ayar_yaz(baglanti: sqlite3.Connection, anahtar: str, deger: str) -> None:
    baglanti.execute(
        "INSERT INTO ayar (anahtar, deger) VALUES (?, ?) "
        "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
        (anahtar, str(deger)),
    )
    baglanti.commit()
