/* viewer.js — thin wrapper around 3Dmol.js for showing an XYZ geometry. */
(function () {
  "use strict";
  window.MOL = window.MOL || {};

  const has3D = () => !!window.$3Dmol;

  function clear(elementId, message) {
    const host = document.getElementById(elementId);
    if (host) host.innerHTML = '<div class="v3d-empty">' + MOL.ui.esc(message || "") + "</div>";
  }

  function render(elementId, xyz) {
    const host = document.getElementById(elementId);
    if (!host) return null;
    if (!has3D()) { clear(elementId, "3D viewer unavailable"); return null; }
    if (!xyz) { clear(elementId, "No geometry"); return null; }
    host.innerHTML = "";
    try {
      const view = window.$3Dmol.createViewer(host, { backgroundAlpha: 0 });
      view.addModel(xyz, "xyz");
      view.setStyle({}, { stick: { radius: 0.13 }, sphere: { scale: 0.26 } });
      view.zoomTo();
      view.render();
      return view;
    } catch (e) {
      clear(elementId, "Could not draw this geometry");
      return null;
    }
  }

  MOL.viewer = { has3D, render, clear };
})();
