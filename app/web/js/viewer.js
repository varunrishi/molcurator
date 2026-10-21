/* viewer.js — thin wrapper around 3Dmol.js for rendering an XYZ geometry. */
(function () {
  "use strict";
  window.MOL = window.MOL || {};

  function has3D() { return !!window.$3Dmol; }

  function render(elementId, xyz) {
    var host = document.getElementById(elementId);
    if (!host) return null;
    if (!has3D()) { host.innerHTML = '<div class="v3d-empty">3D viewer unavailable</div>'; return null; }
    if (!xyz) { host.innerHTML = '<div class="v3d-empty">No geometry</div>'; return null; }
    host.innerHTML = "";
    try {
      var viewer = window.$3Dmol.createViewer(host, { backgroundAlpha: 0 });
      viewer.addModel(xyz, "xyz");
      viewer.setStyle({}, { stick: { radius: 0.13 }, sphere: { scale: 0.26 } });
      viewer.zoomTo();
      viewer.render();
      return viewer;
    } catch (e) {
      host.innerHTML = '<div class="v3d-empty">Could not render 3D</div>';
      return null;
    }
  }

  MOL.viewer = { has3D: has3D, render: render };
})();
