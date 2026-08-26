-- Otopark Demo şeması. Tüm zamanlar ISO-8601 UTC metni; ekranda Türkiye saati.
-- BEGIN/COMMIT yok: uygulama tek transaction içinde uygular.

CREATE TABLE IF NOT EXISTS ayar (
    anahtar TEXT PRIMARY KEY,
    deger   TEXT NOT NULL
);

-- Her benzersiz takip (araç veya kişi) bir satır: "kaç araç geldi" sayımı budur.
CREATE TABLE IF NOT EXISTS gecisler (
    id            INTEGER PRIMARY KEY,
    tip           TEXT NOT NULL CHECK (tip IN ('arac', 'insan')),
    takip_id      INTEGER NOT NULL,
    gun           TEXT NOT NULL,           -- YYYY-AA-GG (Türkiye günü)
    ilk_gorulme   TEXT NOT NULL,           -- ISO-8601 UTC
    son_gorulme   TEXT NOT NULL,
    renk          TEXT,                    -- yalnız araçlarda
    foto          TEXT,                    -- veri/goruntuler altına göreli yol
    UNIQUE (tip, gun, takip_id)            -- aynı araç iki kez sayılmaz
);

CREATE INDEX IF NOT EXISTS idx_gecis_gun ON gecisler (gun, tip);

-- Kullanıcının belirlediği eşiğin altına düşen araç çiftleri
CREATE TABLE IF NOT EXISTS yakinlik_olaylari (
    id        INTEGER PRIMARY KEY,
    zaman     TEXT NOT NULL,               -- ISO-8601 UTC
    gun       TEXT NOT NULL,
    takip_a   INTEGER NOT NULL,
    takip_b   INTEGER NOT NULL,
    mesafe_m  REAL NOT NULL,
    esik_m    REAL NOT NULL,               -- olay anındaki eşik (sonradan değişse de anlamı kalsın)
    foto      TEXT
);

CREATE INDEX IF NOT EXISTS idx_yakinlik_gun ON yakinlik_olaylari (gun);

-- Kullanıcının kendi tanıttığı nesneler (ör. "Servis aracımız")
CREATE TABLE IF NOT EXISTS nesneler (
    id          INTEGER PRIMARY KEY,
    ad          TEXT NOT NULL UNIQUE,
    olusturuldu TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nesne_fotolari (
    id       INTEGER PRIMARY KEY,
    nesne_id INTEGER NOT NULL REFERENCES nesneler (id) ON DELETE CASCADE,
    dosya    TEXT NOT NULL,
    eklendi  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_foto_nesne ON nesne_fotolari (nesne_id);
