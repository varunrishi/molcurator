/* chem.js — client-side chemistry helpers built on OpenChemLib.
 * Provides SMILES canonicalisation, 2D depiction, a quick 3D conformer, and the OFFLINE
 * fallbacks (a transparent demo generator and a clearly-labelled toy gap estimator) used when
 * no backend is connected. The toy estimator is NOT a physical prediction. */
(function () {
  "use strict";
  window.MOL = window.MOL || {};

  var ELEMENTS = ["X","H","He","Li","Be","B","C","N","O","F","Ne","Na","Mg","Al","Si","P","S","Cl","Ar",
    "K","Ca","Sc","Ti","V","Cr","Mn","Fe","Co","Ni","Cu","Zn","Ga","Ge","As","Se","Br","Kr","Rb","Sr","Y",
    "Zr","Nb","Mo","Tc","Ru","Rh","Pd","Ag","Cd","In","Sn","Sb","Te","I","Xe","Cs","Ba"];

  function OCL() { return window.OCL; }
  function hasOCL() { return !!(window.OCL && window.OCL.Molecule); }
  function hasEditor() { return !!(window.OCL && window.OCL.CanvasEditor); }

  function clamp(x, lo, hi) { return Math.min(hi, Math.max(lo, x)); }
  function hash32(str) {
    var h = 2166136261 >>> 0;
    for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function canonical(smiles) {
    if (!hasOCL()) return { ok: false, smiles: smiles, error: "OpenChemLib unavailable" };
    try {
      var mol = OCL().Molecule.fromSmiles(smiles);
      if (mol.getAllAtoms() === 0) return { ok: false, smiles: "", error: "empty structure" };
      return { ok: true, smiles: mol.toSmiles(), atoms: mol.getAllAtoms() };
    } catch (e) {
      return { ok: false, smiles: smiles, error: (e && e.message) || "invalid SMILES" };
    }
  }

  function toXYZ(smiles) {
    if (!hasOCL() || !OCL().ConformerGenerator) return null;
    try {
      var mol = OCL().Molecule.fromSmiles(smiles);
      var conf = new OCL().ConformerGenerator(0x5eed).getOneConformerAsMolecule(mol);
      if (!conf) return null;
      var n = conf.getAllAtoms(), lines = [];
      for (var i = 0; i < n; i++) {
        var z = conf.getAtomicNo(i), sym = ELEMENTS[z] || ("Z" + z);
        lines.push(sym + " " + conf.getAtomX(i).toFixed(4) + " " + conf.getAtomY(i).toFixed(4) + " " + conf.getAtomZ(i).toFixed(4));
      }
      return n + "\n" + smiles + "\n" + lines.join("\n") + "\n";
    } catch (e) { return null; }
  }

  function depictSVG(smiles, w, h) {
    if (!hasOCL()) return "";
    try {
      return OCL().Molecule.fromSmiles(smiles).toSVG(w, h, null, { suppressChiralText: true, autoCrop: true });
    } catch (e) { return ""; }
  }

  /* Transparent surrogate so the UI is usable offline. More conjugation -> smaller gap.
     Deterministic per SMILES. NOT a physical prediction. */
  function toyGap(smiles) {
    var arom = (smiles.match(/[cnops]/g) || []).length;
    var dbl = (smiles.match(/=/g) || []).length;
    var trip = (smiles.match(/#/g) || []).length;
    var rings = (smiles.match(/[1-9]/g) || []).length / 2;
    var halo = (smiles.match(/F|Cl|Br|I/g) || []).length;
    var conj = arom + 1.5 * dbl + 2 * trip + 0.5 * rings;
    var rng = mulberry32(hash32(smiles));
    var gap = clamp(7.4 - 0.72 * Math.log(1 + conj) - 0.10 * halo + (rng() - 0.5) * 0.5, 0.6, 8.5);
    return { gap: gap, uncertainty: 0.25 + 0.15 * rng(), method: "toy estimator (demo, not a real prediction)" };
  }

  /* Valence-aware random graph edits — a demo generator, NOT GB-GA. */
  function demoMutate(parent, strength, rng) {
    if (!hasOCL()) return null;
    var swaps = { 6: [7, 8], 7: [6, 8], 8: [7, 6] }, halo = [9, 17, 35, 53];
    try {
      var mol = OCL().Molecule.fromSmiles(parent);
      var edits = 1 + Math.floor(rng() * strength);
      for (var e = 0; e < edits; e++) {
        var n = mol.getAllAtoms(); if (n === 0) return null;
        var i = Math.floor(rng() * n), z = mol.getAtomicNo(i), op = rng();
        if (op < 0.45 && swaps[z]) { mol.setAtomicNo(i, swaps[z][Math.floor(rng() * swaps[z].length)]); }
        else { var a = mol.addAtom(halo[Math.floor(rng() * halo.length)]); mol.addBond(i, a, 1); }
      }
      var smi = mol.toSmiles();
      var check = OCL().Molecule.fromSmiles(smi);
      return check.getAllAtoms() === 0 ? null : check.toSmiles();
    } catch (e) { return null; }
  }

  MOL.chem = {
    hasOCL: hasOCL, hasEditor: hasEditor,
    clamp: clamp, hash32: hash32, mulberry32: mulberry32,
    canonical: canonical, toXYZ: toXYZ, depictSVG: depictSVG,
    toyGap: toyGap, demoMutate: demoMutate
  };
})();
