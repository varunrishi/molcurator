# PREDICT: cheap physics-based property estimate for a candidate.
#
# Pipeline: SMILES -> RDKit 3D embedding -> xTB (GFN2) geometry optimisation
#           -> property extraction (e.g. HOMO, LUMO, HOMO-LUMO gap)
# Calls the external `xtb` binary; its path comes from the XTB_BIN environment variable.
# Output: optimised XYZ geometry + PropertyValue entries with method "xtb".
