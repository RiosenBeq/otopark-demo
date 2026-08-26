// Referans çizgisi çizimi: görüntüde iki noktaya tıkla, uzunluğu metre olarak gir.
// Koordinatlar normalize (0-1) kaydedilir — çözünürlük değişse de geçerli kalır.
(function () {
  var img = document.getElementById("onizleme");
  var tuval = document.getElementById("tuval");
  if (!img || !tuval) return;
  var ctx = tuval.getContext("2d");
  var noktalar = [];
  var aktif = false;

  function boyutla() {
    tuval.width = tuval.clientWidth;
    tuval.height = tuval.clientHeight;
    ciz();
  }
  window.addEventListener("resize", boyutla);

  function ciz() {
    ctx.clearRect(0, 0, tuval.width, tuval.height);
    if (noktalar.length === 0) return;
    ctx.strokeStyle = "#22c55e";
    ctx.fillStyle = "#22c55e";
    ctx.lineWidth = 3;
    noktalar.forEach(function (n) {
      ctx.beginPath();
      ctx.arc(n[0] * tuval.width, n[1] * tuval.height, 5, 0, 7);
      ctx.fill();
    });
    if (noktalar.length === 2) {
      ctx.beginPath();
      ctx.moveTo(noktalar[0][0] * tuval.width, noktalar[0][1] * tuval.height);
      ctx.lineTo(noktalar[1][0] * tuval.width, noktalar[1][1] * tuval.height);
      ctx.stroke();
    }
  }

  tuval.addEventListener("click", function (olay) {
    if (!aktif) return;
    var kutu = tuval.getBoundingClientRect();
    if (noktalar.length >= 2) noktalar = [];
    noktalar.push([
      (olay.clientX - kutu.left) / kutu.width,
      (olay.clientY - kutu.top) / kutu.height,
    ]);
    ciz();
    if (noktalar.length === 2) {
      document.getElementById("cizgi").value = JSON.stringify(noktalar);
      document.getElementById("kalibrasyon-kaydet").disabled = false;
      document.getElementById("tuval-not").textContent =
        "Çizgi hazır. Gerçek uzunluğunu metre olarak yazıp 'Ölçeği Kaydet'e basın.";
      aktif = false;
      tuval.classList.remove("aktif");
    }
  });

  document.getElementById("cizim-baslat").addEventListener("click", function () {
    aktif = true;
    noktalar = [];
    ciz();
    tuval.classList.add("aktif");
    document.getElementById("kalibrasyon-kaydet").disabled = true;
    document.getElementById("tuval-not").textContent =
      "Görüntüde, uzunluğunu bildiğiniz mesafenin iki ucuna sırayla tıklayın.";
  });

  setTimeout(boyutla, 300);
  boyutla();
})();
