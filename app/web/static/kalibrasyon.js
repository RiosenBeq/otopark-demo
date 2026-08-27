// Mesafe kalibrasyonu çizimi — iki yöntem, tek tuval.
//
// BASİT (çizgi):   2 noktaya tıkla → uzunluğu metre yaz → kaydet.
// HASSAS (4 nokta): zeminde ölçülerini bildiğin bir dikdörtgenin 4 köşesine
//                   SAAT YÖNÜNDE tıkla (1 sol-üst → 2 sağ-üst → 3 sağ-alt →
//                   4 sol-alt) → gerçek en/boy metre yaz → kaydet.
//
// Ortak davranış: fare gezerken canlı önizleme, noktalar sürüklenerek
// düzeltilebilir, Esc iptal, "Geri Al" son noktayı siler.
// Koordinatlar normalize (0-1) kaydedilir — çözünürlük değişse de geçerli.
(function () {
  var img = document.getElementById("onizleme");
  var tuval = document.getElementById("tuval");
  if (!img || !tuval) return;
  var ctx = tuval.getContext("2d");
  var kilavuz = document.getElementById("cizim-kilavuz");
  var araclar = document.getElementById("cizim-araclar");
  var geriDugme = document.getElementById("cizim-geri");
  var iptalDugme = document.getElementById("cizim-iptal");
  var durumYazi = document.getElementById("cizim-durum");
  var tuvalNot = document.getElementById("tuval-not");
  var varsayilanNot = tuvalNot ? tuvalNot.textContent : "";

  // Mod tanımları: hedef nokta sayısı, renk ve adım adım yönlendirme
  var MODLAR = {
    cizgi: {
      hedef: 2,
      renk: "#22c55e",
      girisAlani: "cizgi",
      kaydetDugmesi: "kalibrasyon-kaydet",
      adimlar: [
        "Çizginin BİRİNCİ ucuna tıklayın — uzunluğunu bildiğiniz bir mesafe seçin (örn. bir park yerinin genişliği).",
        "Şimdi çizginin İKİNCİ ucuna tıklayın.",
        "Çizgi hazır ✓ Uçları sürükleyip düzeltebilir, gerçek uzunluğu metre yazıp 'Ölçeği Kaydet'e basabilirsiniz."
      ]
    },
    homografi: {
      hedef: 4,
      renk: "#2563eb",
      girisAlani: "noktalar",
      kaydetDugmesi: "homografi-kaydet",
      adimlar: [
        "Dikdörtgenin 1. köşesine tıklayın: SOL-ÜST (kameraya uzak sol köşe).",
        "2. köşe: SAĞ-ÜST (kameraya uzak sağ köşe).",
        "3. köşe: SAĞ-ALT (kameraya yakın sağ köşe).",
        "4. köşe: SOL-ALT (kameraya yakın sol köşe).",
        "Dikdörtgen hazır ✓ Köşeleri sürükleyip düzeltebilir, gerçek en/boyu metre yazıp 'Kalibrasyonu Kaydet'e basabilirsiniz."
      ]
    }
  };

  var mod = "cizgi";          // aktif çizim modu
  var noktalar = [];           // [[x,y], ...] normalize
  var aktif = false;           // çizim modu açık mı
  var imlec = null;            // fare konumu (canlı önizleme)
  var tasinan = -1;            // sürüklenen nokta (-1 = yok)
  var TUTMA = 14;              // px — noktayı yakalama yarıçapı

  function ayar() { return MODLAR[mod]; }

  function boyutla() {
    if (tuval.width === tuval.clientWidth && tuval.height === tuval.clientHeight) return;
    tuval.width = tuval.clientWidth;
    tuval.height = tuval.clientHeight;
    ciz();
  }
  window.addEventListener("resize", boyutla);
  img.addEventListener("load", boyutla);

  function pikselde(n) { return [n[0] * tuval.width, n[1] * tuval.height]; }

  function etiketKutusu(metin, x, y) {
    ctx.font = "600 12px -apple-system, sans-serif";
    var gen = ctx.measureText(metin).width + 12;
    ctx.fillStyle = "rgba(15,16,20,0.8)";
    ctx.fillRect(x - gen / 2, y - 22, gen, 18);
    ctx.fillStyle = "#fff";
    ctx.textAlign = "center";
    ctx.fillText(metin, x, y - 9);
  }

  function ciz() {
    ctx.clearRect(0, 0, tuval.width, tuval.height);
    if (noktalar.length === 0 && !aktif) return;
    var renk = ayar().renk;
    var hedef = ayar().hedef;

    // Canlı önizleme: son noktadan fareye kesikli çizgi
    if (aktif && noktalar.length > 0 && noktalar.length < hedef && imlec) {
      var son = pikselde(noktalar[noktalar.length - 1]);
      ctx.setLineDash([7, 6]);
      ctx.strokeStyle = renk;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(son[0], son[1]);
      ctx.lineTo(imlec[0], imlec[1]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Kenarlar: çizgi modunda tek kenar, 4 noktada kapalı dörtgen
    if (noktalar.length >= 2) {
      ctx.strokeStyle = renk;
      ctx.lineWidth = 3;
      ctx.beginPath();
      var ilk = pikselde(noktalar[0]);
      ctx.moveTo(ilk[0], ilk[1]);
      for (var i = 1; i < noktalar.length; i++) {
        var q = pikselde(noktalar[i]);
        ctx.lineTo(q[0], q[1]);
      }
      if (mod === "homografi" && noktalar.length === 4) ctx.closePath();
      ctx.stroke();
      if (mod === "homografi" && noktalar.length === 4) {
        ctx.fillStyle = "rgba(37,99,235,0.12)";
        ctx.fill();
      }
    }

    // Çizgi modunda uzunluk etiketi
    if (mod === "cizgi" && noktalar.length === 2) {
      var a = pikselde(noktalar[0]), b = pikselde(noktalar[1]);
      etiketKutusu(Math.round(Math.hypot(b[0] - a[0], b[1] - a[1])) + " px",
        (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
    }

    // Noktalar + 4 nokta modunda köşe numaraları
    noktalar.forEach(function (n, i) {
      var p = pikselde(n);
      ctx.beginPath();
      ctx.arc(p[0], p[1], tasinan === i ? 8 : 6, 0, 7);
      ctx.fillStyle = renk;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
      if (mod === "homografi") {
        ctx.fillStyle = "#fff";
        ctx.font = "700 10px -apple-system, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(String(i + 1), p[0], p[1] + 3.5);
      }
    });

    // 4 nokta modunda kenar ortalarına en/boy ipuçları
    if (mod === "homografi" && noktalar.length === 4) {
      var p0 = pikselde(noktalar[0]), p1 = pikselde(noktalar[1]);
      var p2 = pikselde(noktalar[2]), p3 = pikselde(noktalar[3]);
      etiketKutusu("en", (p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2 + 26);
      etiketKutusu("boy", (p1[0] + p2[0]) / 2 + 4, (p1[1] + p2[1]) / 2);
    }
  }

  function konum(olay) {
    boyutla();
    var kutu = tuval.getBoundingClientRect();
    return [olay.clientX - kutu.left, olay.clientY - kutu.top];
  }

  function yakinNokta(p) {
    for (var i = 0; i < noktalar.length; i++) {
      var q = pikselde(noktalar[i]);
      if (Math.hypot(q[0] - p[0], q[1] - p[1]) <= TUTMA) return i;
    }
    return -1;
  }

  function kilavuzYaz(metin) {
    if (!kilavuz) return;
    kilavuz.textContent = metin;
    kilavuz.classList.toggle("acik", !!metin);
  }
  function durumYaz(metin) { if (durumYazi) durumYazi.textContent = metin; }

  function formaYaz() {
    var m = ayar();
    var hazir = noktalar.length === m.hedef;
    var alan = document.getElementById(m.girisAlani);
    var kaydet = document.getElementById(m.kaydetDugmesi);
    if (alan) alan.value = hazir ? JSON.stringify(noktalar) : "";
    if (kaydet) kaydet.disabled = !hazir;
    if (geriDugme) geriDugme.disabled = noktalar.length === 0;
  }

  function adimYaz() {
    var m = ayar();
    kilavuzYaz(m.adimlar[Math.min(noktalar.length, m.adimlar.length - 1)]);
    durumYaz(noktalar.length + "/" + m.hedef + " nokta" +
      (noktalar.length === m.hedef ? " ✓" : ""));
  }

  function bitir() {
    aktif = false;
    imlec = null;
    tuval.classList.remove("aktif");
    if (araclar) araclar.classList.remove("acik");
    kilavuzYaz("");
    ciz();
  }

  function iptal() {
    noktalar = [];
    tasinan = -1;
    formaYaz();
    durumYaz("");
    if (tuvalNot) tuvalNot.textContent = varsayilanNot;
    bitir();
  }

  tuval.addEventListener("mousedown", function (olay) {
    if (!aktif && noktalar.length === ayar().hedef) {
      // Çizim bitti ama noktalar sürüklenerek düzeltilebilir
      var i = yakinNokta(konum(olay));
      if (i !== -1) { tasinan = i; olay.preventDefault(); }
      return;
    }
    if (!aktif) return;
    var p = konum(olay);
    var i2 = yakinNokta(p);
    if (i2 !== -1) { tasinan = i2; olay.preventDefault(); return; }
    if (noktalar.length >= ayar().hedef) return;
    noktalar.push([p[0] / tuval.width, p[1] / tuval.height]);
    if (noktalar.length === ayar().hedef) {
      aktif = false;
      tuval.classList.remove("aktif");
      if (tuvalNot) tuvalNot.textContent = ayar().adimlar[ayar().adimlar.length - 1];
    }
    adimYaz();
    ciz();
    formaYaz();
  });

  window.addEventListener("mousemove", function (olay) {
    if (tasinan !== -1) {
      var kutu = tuval.getBoundingClientRect();
      var x = Math.min(Math.max(olay.clientX - kutu.left, 0), kutu.width);
      var y = Math.min(Math.max(olay.clientY - kutu.top, 0), kutu.height);
      noktalar[tasinan] = [x / kutu.width, y / kutu.height];
      formaYaz();
      ciz();
      return;
    }
    if (aktif && noktalar.length > 0 && noktalar.length < ayar().hedef) {
      var kutu2 = tuval.getBoundingClientRect();
      imlec = [olay.clientX - kutu2.left, olay.clientY - kutu2.top];
      ciz();
    }
  });
  window.addEventListener("mouseup", function () {
    if (tasinan !== -1) { tasinan = -1; ciz(); }
  });

  document.addEventListener("keydown", function (olay) {
    if (olay.key === "Escape" && (aktif || tasinan !== -1)) iptal();
  });

  if (geriDugme) geriDugme.addEventListener("click", function () {
    noktalar.pop();
    formaYaz();
    aktif = true;
    tuval.classList.add("aktif");
    adimYaz();
    ciz();
  });
  if (iptalDugme) iptalDugme.addEventListener("click", iptal);

  function baslat(yeniMod) {
    mod = yeniMod;
    aktif = true;
    noktalar = [];
    imlec = null;
    formaYaz();
    ciz();
    tuval.classList.add("aktif");
    if (araclar) araclar.classList.add("acik");
    adimYaz();
    if (tuvalNot) tuvalNot.textContent = ayar().adimlar[0];
  }

  var cizgiBaslat = document.getElementById("cizim-baslat");
  if (cizgiBaslat) cizgiBaslat.addEventListener("click", function () { baslat("cizgi"); });
  var homografiBaslat = document.getElementById("homografi-baslat");
  if (homografiBaslat) homografiBaslat.addEventListener("click", function () { baslat("homografi"); });

  // Yöntem sekmeleri: yalnız görünürlüğü değiştirir; kayıt formlar üzerinden
  document.querySelectorAll("[data-yontem-sec]").forEach(function (dugme) {
    dugme.addEventListener("click", function () {
      var secilen = dugme.dataset.yontemSec;
      document.querySelectorAll("[data-yontem-sec]").forEach(function (d) {
        d.classList.toggle("aktif", d === dugme);
      });
      document.querySelectorAll("[data-yontem]").forEach(function (bolum) {
        bolum.hidden = bolum.dataset.yontem !== secilen;
      });
      iptal();
    });
  });

  setTimeout(boyutla, 300);
  boyutla();
})();
