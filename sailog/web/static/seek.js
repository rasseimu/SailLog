document.addEventListener("click", (e) => {
  const el = e.target.closest(".seek");
  if (!el) return;
  e.preventDefault();
  const v = document.getElementById("player");
  if (v) { v.currentTime = parseFloat(el.dataset.t); v.play(); }
});
