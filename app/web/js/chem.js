/* chem.js — client-side structure helpers built on OpenChemLib (loaded by index.html):
 * a quick SMILES check while typing, 2D depictions, and the structure sketcher.
 * Every property value comes from the server; nothing here estimates a property. */
(function () {
  "use strict";
  window.MOL = window.MOL || {};

  const hasOCL = () => !!(window.OCL && window.OCL.Molecule);
  const hasEditor = () => !!(window.OCL && (window.OCL.CanvasEditor || window.OCL.StructureEditor));

  // Parses with OpenChemLib only to give instant feedback; the server's RDKit check is authoritative.
  function parse(smiles) {
    if (!hasOCL()) return { ok: false, error: "structure library unavailable" };
    try {
      const mol = window.OCL.Molecule.fromSmiles(smiles);
      if (mol.getAllAtoms() === 0) return { ok: false, error: "empty structure" };
      return { ok: true, smiles: mol.toSmiles() };
    } catch (e) {
      return { ok: false, error: (e && e.message) || "invalid SMILES" };
    }
  }

  // Inline SVG of a SMILES (OpenChemLib), or "" if it cannot be drawn.
  function depictSVG(smiles, width, height) {
    if (!hasOCL() || !smiles) return "";
    try {
      return window.OCL.Molecule.fromSmiles(smiles).toSVG(width, height, null, { suppressChiralText: true, autoCrop: true });
    } catch (e) {
      return "";
    }
  }

  /* Structure sketcher in the element with this id. OpenChemLib has two editor APIs: CanvasEditor
     (newer releases) and StructureEditor (the vendored v8.15). Both are wrapped to the same two
     methods, getSmiles() and setSmiles(). onChange runs after every edit. */
  function createEditor(elementId, onChange) {
    const OCL = window.OCL;
    if (OCL && OCL.CanvasEditor) {
      const ed = new OCL.CanvasEditor(document.getElementById(elementId));
      ed.setOnChangeListener(onChange);
      return {
        getSmiles: () => { const m = ed.getMolecule(); return m && m.getAllAtoms() > 0 ? m.toSmiles() : ""; },
        setSmiles: (s) => ed.setMolecule(OCL.Molecule.fromSmiles(s))
      };
    }
    if (OCL && OCL.StructureEditor) {
      const el = document.getElementById(elementId);
      el.removeAttribute("style");               // drop styles a previous editor left (it sets position:relative)
      el.style.width = el.clientWidth + "px";   // this editor sizes itself from the element's inline size
      el.style.height = el.clientHeight + "px";
      const ed = OCL.StructureEditor.createSVGEditor(elementId, 1);
      ed.setChangeListenerCallback(onChange);
      return { getSmiles: () => ed.getSmiles(), setSmiles: (s) => ed.setSmiles(s) };
    }
    return null;
  }

  MOL.chem = { hasOCL, hasEditor, parse, depictSVG, createEditor };
})();
