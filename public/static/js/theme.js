(function () {
  var stored = null;
  try {
    stored = localStorage.getItem("nc-theme");
  } catch (error) {
    stored = null;
  }
  var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  var theme = stored || (prefersDark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", theme);
})();
