// Referans çizgisi çizimi — kolaylaştırılmış sürüm.
//
// Kullanım: "Referans çizgisi çiz"e bas, görüntüde iki noktaya tıkla.
// Fare gezerken çizgi canlı önizlenir; noktalar sonradan SÜRÜKLENEREK
// düzeltilebilir. Esc iptal eder, "Geri Al" son noktayı siler.
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

  var noktalar = [];       // [[x,y], ...] normalize
  var aktif = false;       // çizim modu açık mı
  var imlec = null;        // fare konumu (canlı önizleme için)
  var tasinan = -1;     // sürüklenen nokta indeksi (-1 = yok)
  var RENK = "#22c55e";
  var TUTMA = 14;          // px — noktayı yakalama yarıçapı

  function boyutla() {
    if (tuval.width === tuval.clientWidth && tuval.height === tuval.clientHeight) return;
    tuval.width = tuval.clientWidth;
    tuval.height = tuval.clientHeight;
    ciz();
  }
  window.addEventListener("resize", boyutla);
  // Canlı görüntü sonradan gelince kart büyür; tampon ile ekran boyutu
  // ayrışırsa tıklama noktaları kayar — her yenilemede eşitle.
  img.addEventListener("load", boyutla);

  function pikselde(n) { return [n[0] * tuval.width, n[1] * tuval.height]; }

  function ciz() {
    ctx.clearRect(0, 0, tuval.width, tuval.height);
    if (noktalar.length === 0 && !aktif) return;

    // canlı önizleme: ilk nokta konduysa fareye kadar kesikli çizgi
    if (aktif && noktalar.length === 1 && imlec) {
      var a = pikselde(noktalar[0]);
      ctx.setLineDash([7, 6]);
      ctx.strokeStyle = RENK;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(imlec[0], imlec[1]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    if (noktalar.length === 2) {
      var b1 = pikselde(noktalar[0]), b2 = pikselde(noktalar[1]);
      ctx.strokeStyle = RENK;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(b1[0], b1[1]);
      ctx.lineTo(b2[0], b2[1]);
      ctx.stroke();
      // uzunluk etiketi (piksel) — kullanıcı çizgiyi görsün diye ortada
      var ox = (b1[0] + b2[0]) / 2, oy = (b1[1] + b2[1]) / 2;
      var uz = Math.round(Math.hypot(b2[0] - b1[0], b2[1] - b1[1]));
      ctx.font = "600 12px -apple-system, sans-serif";
      var metin = uz + " px";
      var gen = ctx.measureText(metin).width + 12;
      ctx.fillStyle = "rgba(15,16,20,0.8)";
      ctx.fillRect(ox - gen / 2, oy - 22, gen, 18);
      ctx.fillStyle = "#fff";
      ctx.textAlign = "center";
      ctx.fillText(metin, ox, oy - 9);
    }

    noktalar.forEach(function (n, i) {
      var p = pikselde(n);
      ctx.beginPath();
      ctx.arc(p[0], p[1], tasinan === i ? 8 : 6, 0, 7);
      ctx.fillStyle = RENK;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
    });
  }

  function konum(olay) {
    boyutla(); // tıklamadan önce tampon ve ekran boyutu aynı olsun
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

  function durumYaz(metin) {
    if (durumYazi) durumYazi.textContent = metin;
  }

  function formaYaz() {
    var hazir = noktalar.length === 2;
    document.getElementById("cizgi").value = hazir ? JSON.stringify(
      noktalar.map(function (n) { return [n[0], n[1]]; })
    ) : "";
    document.getElementById("kalibrasyon-kaydet").disabled = !hazir;
    if (geriDugme) geriDugme.disabled = noktalar.length === 0;
  }

  function bitir() {
    aktif = false;
    imlec = null;
    tuval.classList.remove("aktif");
    if (araclar) araclar.classList.remove("acik");
    kilavuzYaz("");
    ciz();
  }

  var varsayilanNot = document.getElementById("tuval-not").textContent;

  function iptal() {
    noktalar = [];
    tasinan = -1;
    formaYaz();
    durumYaz("");
    document.getElementById("tuval-not").textContent = varsayilanNot;
    bitir();
  }

  tuval.addEventListener("mousedown", function (olay) {
    if (!aktif && noktalar.length === 2) {
      // çizim bitti ama nokta sürüklenerek düzeltilebilir
      var i = yakinNokta(konum(olay));
      if (i !== -1) { tasinan = i; olay.preventDefault(); }
      return;
    }
    if (!aktif) return;
    var p = konum(olay);
    var i2 = yakinNokta(p);
    if (i2 !== -1) { tasinan = i2; olay.preventDefault(); return; }
    if (noktalar.length >= 2) return;
    noktalar.push([p[0] / tuval.width, p[1] / tuval.height]);
    if (noktalar.length === 1) {
      kilavuzYaz("Şimdi çizginin İKİNCİ ucuna tıklayın. (Esc: iptal, Geri Al: son nokta)");
      durumYaz("1/2 nokta");
    } else {
      formaYaz();
      kilavuzYaz("Çizgi hazır. Uçları sürükleyerek düzeltebilirsiniz. " +
        "Gerçek uzunluğu metre olarak yazıp 'Ölçeği Kaydet'e basın.");
      durumYaz("Çizgi hazır ✓");
      document.getElementById("tuval-not").textContent =
        "Çizgi hazır. Gerçek uzunluğunu metre olarak yazıp 'Ölçeği Kaydet'e basın.";
      aktif = false;
      tuval.classList.remove("aktif");
    }
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
    if (aktif && noktalar.length === 1) {
      var kutu2 = tuval.getBoundingClientRect();
      imlec = [olay.clientX - kutu2.left, olay.clientY - kutu2.top];
      ciz();
    }
  });
  window.addEventListener("mouseup", function () {
    if (tasinan !== -1) { tasinan = -1; ciz(); }
  });

  document.addEventListener("keydown", function (olay) {
    // Yalnız çizim modunda ya da uç sürüklerken: bitmiş çizgi, başka bir
    // amaçla basılan Esc ile yanlışlıkla silinmesin (İptal düğmesi her an var)
    if (olay.key === "Escape" && (aktif || tasinan !== -1)) iptal();
  });

  if (geriDugme) geriDugme.addEventListener("click", function () {
    noktalar.pop();
    formaYaz();
    if (noktalar.length === 0) {
      kilavuzYaz("Çizginin BİRİNCİ ucuna tıklayın — uzunluğunu bildiğiniz bir mesafe seçin.");
      durumYaz("0/2 nokta");
    } else {
      kilavuzYaz("Şimdi çizginin İKİNCİ ucuna tıklayın.");
      durumYaz("1/2 nokta");
    }
    aktif = true;
    tuval.classList.add("aktif");
    ciz();
  });
  if (iptalDugme) iptalDugme.addEventListener("click", iptal);

  document.getElementById("cizim-baslat").addEventListener("click", function () {
    aktif = true;
    noktalar = [];
    imlec = null;
    formaYaz();
    ciz();
    tuval.classList.add("aktif");
    if (araclar) araclar.classList.add("acik");
    document.getElementById("kalibrasyon-kaydet").disabled = true;
    kilavuzYaz("Çizginin BİRİNCİ ucuna tıklayın — uzunluğunu bildiğiniz bir mesafe seçin " +
      "(örn. bir park yerinin genişliği).");
    durumYaz("0/2 nokta");
    document.getElementById("tuval-not").textContent =
      "Görüntüde, uzunluğunu bildiğiniz mesafenin iki ucuna sırayla tıklayın.";
  });

  setTimeout(boyutla, 300);
  boyutla();
})();
