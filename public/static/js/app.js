(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";

  function el(name, attrs, text) {
    var node = document.createElementNS(SVG_NS, name);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  function compact(value) {
    var abs = Math.abs(value);
    if (abs >= 1e9) return (value / 1e9).toFixed(1).replace(".0", "") + " mil M";
    if (abs >= 1e6) return (value / 1e6).toFixed(1).replace(".0", "") + " M";
    if (abs >= 1e3) return (value / 1e3).toFixed(1).replace(".0", "") + " k";
    return String(Math.round(value * 10) / 10);
  }

  function drawChart(container) {
    var data;
    try {
      data = JSON.parse(container.getAttribute("data-chart"));
    } catch (error) {
      return;
    }
    if (!data || !data.length) {
      container.textContent = "Sin datos para mostrar.";
      container.classList.add("muted");
      return;
    }
    var type = container.getAttribute("data-type") || "bars";
    var width = 720;
    var height = 260;
    var pad = { top: 16, right: 12, bottom: 34, left: 52 };
    var inner = { w: width - pad.left - pad.right, h: height - pad.top - pad.bottom };
    var max = Math.max.apply(null, data.map(function (d) { return d.value; }));
    if (max <= 0) max = 1;

    var svg = el("svg", { viewBox: "0 0 " + width + " " + height, role: "img", "aria-label": container.getAttribute("data-label") || "Gráfico" });

    for (var i = 0; i <= 4; i++) {
      var y = pad.top + inner.h - (inner.h * i) / 4;
      svg.appendChild(el("line", { x1: pad.left, x2: width - pad.right, y1: y, y2: y, "class": "grid-line" }));
      svg.appendChild(el("text", { x: pad.left - 8, y: y + 4, "text-anchor": "end" }, compact((max * i) / 4)));
    }

    var step = inner.w / data.length;
    var every = Math.ceil(data.length / 10);

    if (type === "line") {
      var points = data.map(function (d, index) {
        var x = pad.left + step * index + step / 2;
        var yy = pad.top + inner.h - (d.value / max) * inner.h;
        return [x, yy];
      });
      var path = points.map(function (p, index) { return (index ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" ");
      var area = path + " L" + points[points.length - 1][0].toFixed(1) + " " + (pad.top + inner.h) + " L" + points[0][0].toFixed(1) + " " + (pad.top + inner.h) + " Z";
      svg.appendChild(el("path", { d: area, "class": "area" }));
      svg.appendChild(el("path", { d: path, "class": "line" }));
      points.forEach(function (p, index) {
        var dot = el("circle", { cx: p[0], cy: p[1], r: 3, "class": "dot" });
        dot.appendChild(el("title", {}, data[index].label + ": " + compact(data[index].value)));
        svg.appendChild(dot);
      });
    } else {
      var barWidth = Math.max(step * 0.7, 2);
      data.forEach(function (d, index) {
        var h = (d.value / max) * inner.h;
        var rect = el("rect", {
          x: pad.left + step * index + (step - barWidth) / 2,
          y: pad.top + inner.h - h,
          width: barWidth,
          height: Math.max(h, 0),
          rx: 3,
          "class": "bar"
        });
        rect.appendChild(el("title", {}, d.label + ": " + compact(d.value)));
        svg.appendChild(rect);
      });
    }

    data.forEach(function (d, index) {
      if (index % every === 0) {
        svg.appendChild(el("text", { x: pad.left + step * index + step / 2, y: height - 12, "text-anchor": "middle" }, d.label));
      }
    });

    container.textContent = "";
    container.appendChild(svg);
  }

  function initCharts() {
    document.querySelectorAll(".chart[data-chart]").forEach(drawChart);
  }

  function initTheme() {
    var toggle = document.querySelectorAll("[data-theme-toggle]");
    toggle.forEach(function (button) {
      button.addEventListener("click", function () {
        var current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
        var next = current === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        try {
          localStorage.setItem("nc-theme", next);
        } catch (error) {
          return;
        }
      });
    });
  }

  function initConfirm() {
    document.addEventListener("click", function (event) {
      var target = event.target.closest("[data-confirm]");
      if (target && !window.confirm(target.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    });
  }

  function initLines() {
    var container = document.getElementById("lines");
    var template = document.getElementById("line-template");
    var add = document.getElementById("add-line");
    if (!container || !template || !add) return;

    function addLine() {
      container.appendChild(template.content.cloneNode(true));
    }

    add.addEventListener("click", addLine);
    container.addEventListener("click", function (event) {
      var remove = event.target.closest("[data-remove-line]");
      if (remove) {
        var row = remove.closest(".line-row");
        if (row && container.children.length > 1) {
          row.remove();
        }
      }
    });
    addLine();
  }

  function initAutoSubmit() {
    document.querySelectorAll("[data-autosubmit]").forEach(function (field) {
      field.addEventListener("change", function () {
        if (field.form) field.form.submit();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initConfirm();
    initCharts();
    initLines();
    initAutoSubmit();
  });
})();
